from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import requests
from AI.models import AiProviderAccount
from AI.processors import cloud_runtime
from AI.processors import agent as ai_agent
from AI.processors import local_runtime
from AI.processors import operation_runtime
from AI.processors import pipeline as ai_pipeline
from AI.processors import provider_adapters
from AI.processors import tools as ai_tools
from AI.processors.agent import choose_action, choose_tool, run_agent_turn
from AI.processors import staging_marketplace_evidence_cli
from AI.processors.local_resources import GIB, ResourceSnapshot, build_local_resource_plan
from AI.processors.tools import available_tools
from Account.models.models import ApiAccount
from Feedback.processors.pipeline import Result
from Core.utils.model_utils import get_engine
from Labels.processors import pipeline as labels_pipeline
from Listing.models.models import ListingProduct, ListingProductCostSnapshot, ListingProductStockSnapshot
from Logistics.models.models import LogisticsCargoTariff
from Finance.models.trendyol.models import Brand, Company, FinanceCostItem, FinanceInvoiceDocument, FinanceManualTransaction
from Orders.constants import TZ_GMT3
from Orders.models.trendyol.models import OrderData, OrderHeader, OrderItem, ReturnClaim
from Stock.models.models import StockItem, StockTx, Warehouse
from sqlmodel import Session, select
from tests.support.db_case import IsolatedDbTestCase


class _FakeDownloadResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None, status_code: int = 200):
        self._body = body
        self.headers = dict(headers or {})
        self.status_code = int(status_code)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1024 * 1024):
        for index in range(0, len(self._body), max(1, int(chunk_size))):
            yield self._body[index:index + chunk_size]


class _FakeProviderResponse:
    def __init__(
        self,
        payload: dict,
        *,
        status_code: int = 200,
        reason: str = "OK",
        url: str = "https://api.example.test",
    ):
        self._payload = payload
        self.status_code = status_code
        self.reason = reason
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error: {self.reason} for url: {self.url}",
                response=self,
            )
        return None

    def json(self) -> dict:
        return dict(self._payload)


class TestAiPipeline(IsolatedDbTestCase):
    def test_qwen3_low_reasoning_uses_non_thinking_prompt_control(self) -> None:
        controlled, mode = local_runtime._apply_local_reasoning_control(
            "Sadece dogal metin yaz.",
            model_hint="Qwen3-4B-Q4_K_M.gguf",
            reasoning_effort="low",
        )

        self.assertEqual(mode, "qwen3_no_think")
        self.assertTrue(controlled.startswith("/no_think\n"))

    def test_local_reasoning_control_does_not_leak_to_other_families(self) -> None:
        controlled, mode = local_runtime._apply_local_reasoning_control(
            "Sadece dogal metin yaz.",
            model_hint="Llama-3.2-1B-Instruct-Q8_0.gguf",
            reasoning_effort="low",
        )

        self.assertEqual(mode, "")
        self.assertEqual(controlled, "Sadece dogal metin yaz.")

    def test_direct_chat_quality_rejects_non_idiomatic_turkish(self) -> None:
        self.assertEqual(
            ai_agent._direct_answer_violation_reason(
                "Benim biraz keyfim yok, iki laf edelim.",
                "Üzgünüm duymak, konuşmak istersen buradayım.",
                history=[],
            ),
            "non_idiomatic_turkish",
        )

    def test_casual_context_return_rejects_formal_service_boilerplate(self) -> None:
        history = [
            {"role": "user", "content": "ORD-QUALITY-1 siparişini aç."},
            {
                "role": "assistant",
                "content": "ORD-QUALITY-1 numaralı siparişi açtım.",
            },
        ]

        self.assertEqual(
            ai_agent._direct_answer_violation_reason(
                "Tamam, az önceki işe dönebiliriz.",
                (
                    "Sayın kullanıcı, ORD-QUALITY-1 numaralı sipariş talebiniz "
                    "dâhilindeyiz; ek bir destek talebiniz olursa yardımcı "
                    "olmamız mümkündür."
                ),
                history=history,
            ),
            "mismatched_formal_service_tone",
        )

    def test_provider_response_strips_only_edge_chat_template_tokens(self) -> None:
        leaked = cloud_runtime._extract_openai_text(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<|im_end|> Production veride 11 siparis var. "
                                "Literal </|turn> aciklamasi korunur.\n</|turn>"
                            )
                        }
                    }
                ]
            }
        )

        self.assertEqual(
            leaked,
            "Production veride 11 siparis var. Literal </|turn> aciklamasi korunur.",
        )

    def test_ai_latest_order_and_return_helpers_delegate_to_orders_domain_queries(self) -> None:
        order_row = SimpleNamespace(orderNumber="ORD-DOMAIN-1")
        return_row = SimpleNamespace(claimId="CLAIM-DOMAIN-1")
        with patch.object(
            ai_tools,
            "domain_get_latest_orders_filtered",
            return_value=Result.ok(
                "ok",
                close_dialog=False,
                data={"orders": [order_row], "simulated_excluded": 2},
            ),
        ) as orders_mock, patch.object(
            ai_tools,
            "domain_get_latest_return_claims_filtered",
            return_value=Result.ok(
                "ok",
                close_dialog=False,
                data={"claims": [return_row]},
            ),
        ) as returns_mock:
            orders, order_meta = ai_tools._latest_orders(
                db_name=self.db_path,
                period="all",
            )
            returns, return_meta = ai_tools._latest_returns(
                db_name=self.db_path,
                period="all",
            )

        self.assertEqual(orders, [order_row])
        self.assertEqual(order_meta.get("simulated_excluded"), 2)
        self.assertEqual(returns, [return_row])
        self.assertEqual(return_meta.get("period_label"), "all")
        self.assertEqual(orders_mock.call_args.kwargs.get("db_name"), self.db_path)
        self.assertEqual(returns_mock.call_args.kwargs.get("db_name"), self.db_path)

    def _insert_order_snapshot(
        self,
        order_number: str,
        order_date_ms: int,
        *,
        package_id: int,
        status: str = "Created",
        cargo_tracking_number: str | None = None,
        cargo_provider_name: str | None = None,
        printed: bool = False,
        extracted: bool = False,
        total_price: float | None = None,
        agreed_delivery_date: int | None = None,
        api_account_id: int | None = None,
    ) -> None:
        with Session(get_engine(self.db_path)) as session:
            header = session.exec(select(OrderHeader).where(OrderHeader.orderNumber == order_number)).first()
            if header is None:
                header = OrderHeader(
                    orderNumber=order_number,
                    api_account_id=api_account_id,
                    is_printed=printed,
                    is_extracted=extracted,
                )
                session.add(header)
                session.flush()
            else:
                header.is_printed = printed
                header.is_extracted = extracted
            session.add(
                OrderData(
                    order_header_id=header.pk,
                    orderNumber=order_number,
                    api_account_id=api_account_id,
                    id=package_id,
                    orderDate=order_date_ms,
                    lastModifiedDate=order_date_ms + package_id,
                    status=status,
                    shipmentPackageStatus=status,
                    cargoTrackingNumber=cargo_tracking_number,
                    cargoProviderName=cargo_provider_name,
                    totalPrice=total_price,
                    packageTotalPrice=total_price,
                    agreedDeliveryDate=agreed_delivery_date,
                )
            )
            session.commit()

    def _decision_tool_names(self, result: Result) -> list[str]:
        decision = (result.data or {}).get("decision")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        if not calls and getattr(decision, "tool_name", None):
            return [str(getattr(decision, "tool_name"))]
        return [str(call.tool_name) for call in calls]

    def test_provider_account_crud_roundtrip(self) -> None:
        settings_path = Path(tempfile.mkdtemp()) / "ai_config.json"
        save_res = ai_pipeline.save_provider_account(
            provider_code="gemini",
            label="Gemini Free",
            api_key="AIzaSy-test-secret",
            endpoint_url="https://generativelanguage.googleapis.com",
            default_model="gemini-2.5-flash-lite",
            db_name=self.db_path,
        )
        self.assertTrue(save_res.success, save_res.message)
        saved = (save_res.data or {}).get("record") or {}
        provider_id = int(saved.get("id") or 0)
        self.assertGreater(provider_id, 0)
        self.assertEqual(str(saved.get("provider_label")), "Google Gemini")
        self.assertEqual(str(saved.get("api_key_masked")), "AIza...cret")
        self.assertTrue(saved.get("credential_managed"))
        with Session(get_engine(self.db_path)) as session:
            stored_provider = session.get(AiProviderAccount, provider_id)
            self.assertIsNotNone(stored_provider)
            self.assertTrue(str(stored_provider.api_key).startswith("credential://"))
            self.assertNotEqual(str(stored_provider.api_key), "AIzaSy-test-secret")

        runtime_res = ai_pipeline.save_provider_runtime_config(
            saved,
            reasoning_effort="high",
            settings_path=settings_path,
        )
        self.assertTrue(runtime_res.success, runtime_res.message)
        runtime_record = (runtime_res.data or {}).get("record") or {}
        self.assertEqual(runtime_record.get("reasoning_effort"), "high")
        self.assertTrue((runtime_record.get("reasoning_capabilities") or {}).get("supported"))

        list_res = ai_pipeline.list_provider_accounts(db_name=self.db_path, settings_path=settings_path)
        self.assertTrue(list_res.success, list_res.message)
        records = (list_res.data or {}).get("records") or []
        self.assertEqual(len(records), 1)
        self.assertEqual(str(records[0].get("label")), "Gemini Free")
        self.assertNotIn("api_key", records[0])
        self.assertEqual(records[0].get("reasoning_effort"), "high")

        runtime_list_res = ai_pipeline.list_provider_accounts(
            db_name=self.db_path,
            include_secret=True,
            settings_path=settings_path,
        )
        self.assertTrue(runtime_list_res.success, runtime_list_res.message)
        runtime_records = (runtime_list_res.data or {}).get("records") or []
        self.assertEqual(len(runtime_records), 1)
        self.assertEqual(str(runtime_records[0].get("api_key")), "AIzaSy-test-secret")
        self.assertEqual(runtime_records[0].get("reasoning_effort"), "high")

        get_res = ai_pipeline.get_provider_account(provider_id, db_name=self.db_path, settings_path=settings_path)
        self.assertTrue(get_res.success, get_res.message)
        detail = (get_res.data or {}).get("record") or {}
        self.assertEqual(str(detail.get("api_key")), "AIzaSy-test-secret")
        self.assertEqual(detail.get("reasoning_effort"), "high")

        delete_res = ai_pipeline.delete_provider_accounts([provider_id], db_name=self.db_path)
        self.assertTrue(delete_res.success, delete_res.message)

        list_after_delete = ai_pipeline.list_provider_accounts(db_name=self.db_path, settings_path=settings_path)
        self.assertTrue(list_after_delete.success, list_after_delete.message)
        self.assertEqual((list_after_delete.data or {}).get("records") or [], [])

    def test_provider_model_catalog_filters_free_openrouter_models(self) -> None:
        payload = {
            "data": [
                {
                    "id": "openai/gpt-4.1-mini",
                    "name": "GPT 4.1 Mini",
                    "pricing": {"prompt": "0.0000004", "completion": "0.0000016"},
                    "context_length": 1047576,
                },
                {
                    "id": "google/lyria-3-pro-preview",
                    "name": "Lyria Zero Priced Media",
                    "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                    "context_length": 8192,
                },
                {
                    "id": "meta-llama/llama-3.3-70b-instruct:free",
                    "name": "Llama Free",
                    "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                    "context_length": 131072,
                },
            ]
        }

        with patch.object(ai_pipeline.requests, "get", return_value=_FakeProviderResponse(payload)) as get_mock:
            result = ai_pipeline.list_provider_models(
                provider_code="openrouter",
                endpoint_url="https://openrouter.ai/api/v1",
                api_key="sk-test",
                free_only=True,
            )

        self.assertTrue(result.success, result.message)
        records = (result.data or {}).get("records") or []
        self.assertEqual([row.get("id") for row in records], ["meta-llama/llama-3.3-70b-instruct:free"])
        self.assertEqual(records[0].get("pricing_label"), "free")
        self.assertEqual((result.data or {}).get("free_total"), 1)
        self.assertEqual(get_mock.call_args.kwargs["headers"].get("Authorization"), "Bearer sk-test")

    def test_provider_model_catalog_lists_gemini_generate_content_models(self) -> None:
        payload = {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "displayName": "Gemini 2.5 Flash",
                    "description": "Fast model",
                    "inputTokenLimit": 1048576,
                    "supportedGenerationMethods": ["generateContent", "countTokens"],
                },
                {
                    "name": "models/embedding-001",
                    "displayName": "Embedding",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        }

        with patch.object(ai_pipeline.requests, "get", return_value=_FakeProviderResponse(payload)) as get_mock:
            result = ai_pipeline.list_provider_models(
                provider_code="gemini",
                endpoint_url="https://generativelanguage.googleapis.com/v1beta",
                api_key="AIza-test",
                free_only=True,
            )

        self.assertTrue(result.success, result.message)
        records = (result.data or {}).get("records") or []
        self.assertEqual([row.get("id") for row in records], ["gemini-2.5-flash"])
        self.assertEqual(records[0].get("pricing_label"), "verified free tier")
        self.assertEqual(records[0].get("free_tier_status"), "verified_free")
        self.assertEqual(records[0].get("context_length"), 1048576)
        self.assertEqual(get_mock.call_args.kwargs.get("params"), {"key": "AIza-test"})
        self.assertNotIn("Authorization", get_mock.call_args.kwargs["headers"])

    def test_gemini_free_catalog_excludes_paid_specialized_and_unknown_models(self) -> None:
        payload = {
            "models": [
                {
                    "name": "models/gemini-3.5-flash",
                    "displayName": "Gemini 3.5 Flash",
                    "inputTokenLimit": 1048576,
                    "outputTokenLimit": 65536,
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-3.1-pro-preview",
                    "displayName": "Gemini 3.1 Pro Preview",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-3.1-flash-image",
                    "displayName": "Gemini 3.1 Flash Image",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-future-unknown",
                    "displayName": "Unknown future model",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }

        with patch.object(ai_pipeline.requests, "get", return_value=_FakeProviderResponse(payload)):
            result = ai_pipeline.list_provider_models(
                provider_code="gemini",
                endpoint_url="https://generativelanguage.googleapis.com/v1beta",
                api_key="AIza-test",
                free_only=True,
            )

        self.assertTrue(result.success, result.message)
        records = (result.data or {}).get("records") or []
        self.assertEqual([row.get("id") for row in records], ["gemini-3.5-flash"])
        self.assertEqual((result.data or {}).get("free_total"), 1)

    def test_gemini_runtime_catalog_fallback_is_verified_free_chat_only(self) -> None:
        payload = {
            "models": [
                {
                    "name": "models/gemini-3.1-pro-preview",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-3.1-flash-image",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-3.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }

        self.assertEqual(
            cloud_runtime._extract_gemini_catalog_model_ids(payload),
            ["gemini-3.5-flash", "gemini-2.5-flash"],
        )

    def test_provider_model_catalog_http_error_redacts_gemini_api_key(self) -> None:
        response = _FakeProviderResponse(
            {},
            status_code=429,
            reason="Too Many Requests",
            url="https://generativelanguage.googleapis.com/v1beta/models?key=AIza-secret-token",
        )

        with patch.object(ai_pipeline.requests, "get", return_value=response):
            result = ai_pipeline.list_provider_models(
                provider_code="gemini",
                endpoint_url="https://generativelanguage.googleapis.com/v1beta",
                api_key="AIza-secret-token",
                free_only=True,
            )

        self.assertFalse(result.success)
        self.assertNotIn("AIza-secret-token", result.message)
        self.assertNotIn("AIza-secret-token", str(result.error))
        self.assertIn("key=%2A%2A%2A", str(result.error))

    def test_gemini_chat_http_error_redacts_api_key(self) -> None:
        response = _FakeProviderResponse(
            {},
            status_code=429,
            reason="Too Many Requests",
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-2.5-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(cloud_runtime.requests, "get", return_value=_FakeProviderResponse({"models": []})), patch.object(
            cloud_runtime.requests,
            "post",
            return_value=response,
        ):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-2.5-flash-lite",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            with self.assertRaises(requests.HTTPError) as ctx:
                client("Sadece OK yaz.")

        message = str(ctx.exception)
        self.assertNotIn("AIza-chat-secret", message)
        self.assertIn("key=%2A%2A%2A", message)
        self.assertIn("rate limit/quota", message)

    def test_gemini_25_chat_applies_thinking_budget_from_reasoning_effort(self) -> None:
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "Dusunme ayari calisti."}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-2.5-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(cloud_runtime.requests, "get", return_value=_FakeProviderResponse({"models": []})), patch.object(
            cloud_runtime.requests,
            "post",
            return_value=ok,
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-2.5-flash-lite",
                    "reasoning_effort": "low",
                    "is_enabled": True,
                    "maxOutputTokens": 64,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Sadece OK yaz."), "Dusunme ayari calisti.")

        payload = post_mock.call_args.kwargs["json"]
        generation_config = payload.get("generationConfig") or {}
        self.assertEqual(generation_config.get("thinkingConfig"), {"thinkingBudget": 512})
        self.assertEqual(generation_config.get("maxOutputTokens"), 64)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("reasoning_effort"), "low")

    def test_gemini_latest_alias_uses_thinking_level_and_keeps_effort(self) -> None:
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "Alias calisti."}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-flash-lite-latest:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(
            cloud_runtime.requests,
            "get",
            return_value=_FakeProviderResponse({"models": []}),
        ), patch.object(
            cloud_runtime.requests,
            "post",
            return_value=ok,
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-flash-lite-latest",
                    "reasoning_effort": "high",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Sadece cevap ver."), "Alias calisti.")

        generation_config = post_mock.call_args.kwargs["json"]["generationConfig"]
        self.assertEqual(
            generation_config.get("thinkingConfig"),
            {"thinkingLevel": "high"},
        )
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("reasoning_effort"), "high")
        self.assertTrue(
            (plan.get("reasoning_capabilities") or {}).get("supported")
        )

    def test_gemini_chat_falls_back_to_next_free_model_on_rate_limit(self) -> None:
        rate_limited = _FakeProviderResponse(
            {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Quota exceeded.",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {
                                    "quotaId": (
                                        "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                                    ),
                                    "quotaDimensions": {
                                        "model": "gemini-2.5-flash-lite"
                                    },
                                }
                            ],
                        }
                    ],
                }
            },
            status_code=429,
            reason="Too Many Requests",
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-2.5-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )
        ok = _FakeProviderResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Calisiyorum."},
                            ]
                        }
                    }
                ]
            },
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{cloud_runtime.GEMINI_VALIDATED_FREE_MODEL}:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(cloud_runtime.requests, "get", return_value=_FakeProviderResponse({"models": []})), patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[rate_limited, ok],
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-2.5-flash-lite",
                    "reasoning_effort": "high",
                    "is_enabled": True,
                    "maxOutputTokens": 32,
                }
            )
            self.assertIsNotNone(client)
            answer = client("Sadece OK yaz.")

        self.assertEqual(answer, "Calisiyorum.")
        self.assertEqual(getattr(client, "model_name", ""), cloud_runtime.GEMINI_VALIDATED_FREE_MODEL)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("requested_model"), "gemini-2.5-flash-lite")
        self.assertEqual(plan.get("actual_model"), cloud_runtime.GEMINI_VALIDATED_FREE_MODEL)
        self.assertTrue(plan.get("fallback_used"))
        self.assertEqual(
            (plan.get("normalized_error_history") or [])[0].get(
                "quota_scope"
            ),
            "model",
        )
        self.assertEqual(
            (
                plan.get("invocation_outcome_history") or []
            )[-1]["normalized_error_history"][0]["quota_scope"],
            "model",
        )
        self.assertEqual(plan.get("reasoning_effort"), "high")
        self.assertEqual(
            (plan.get("reasoning_capabilities") or {}).get("control"),
            "thinking_level",
        )
        called_urls = [str(call.args[0]) for call in post_mock.call_args_list]
        self.assertIn("models/gemini-2.5-flash-lite:generateContent", called_urls[0])
        self.assertIn(
            f"models/{cloud_runtime.GEMINI_VALIDATED_FREE_MODEL}:generateContent",
            called_urls[1],
        )
        first_config = post_mock.call_args_list[0].kwargs["json"]["generationConfig"]
        second_config = post_mock.call_args_list[1].kwargs["json"]["generationConfig"]
        self.assertEqual(first_config.get("thinkingConfig"), {"thinkingBudget": 8192})
        self.assertEqual(second_config.get("thinkingConfig"), {"thinkingLevel": "high"})

    def test_gemini_exact_model_evaluation_disables_fallback(self) -> None:
        rate_limited = _FakeProviderResponse(
            {},
            status_code=429,
            reason="Too Many Requests",
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-2.5-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(cloud_runtime.requests, "get") as get_mock, patch.object(
            cloud_runtime.requests,
            "post",
            return_value=rate_limited,
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-2.5-flash-lite",
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            with self.assertRaises(requests.HTTPError):
                client("Sadece cevap ver.")

        get_mock.assert_not_called()
        self.assertEqual(len(post_mock.call_args_list), 1)
        self.assertIn(
            "models/gemini-2.5-flash-lite:generateContent",
            str(post_mock.call_args.args[0]),
        )
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertFalse(plan.get("fallback_allowed"))

    def test_gemini_exact_model_waits_for_bounded_model_rate_limit_and_retries(
        self,
    ) -> None:
        rate_limited = _FakeProviderResponse(
            {
                "error": {
                    "message": "modelRateLimit; retryDelay 1s",
                    "details": [{"retryDelay": "1s"}],
                }
            },
            status_code=429,
            reason="Too Many Requests",
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-3.1-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-3.1-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[rate_limited, ok],
        ) as post_mock, patch.object(cloud_runtime.time, "sleep") as sleep_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": (
                        "https://generativelanguage.googleapis.com/v1beta"
                    ),
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-3.1-flash-lite",
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client("Sadece OK yaz.")

        self.assertEqual(answer, "OK")
        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("actual_model"), "gemini-3.1-flash-lite")
        self.assertFalse(plan.get("fallback_used"))
        self.assertEqual(
            plan.get("same_model_retry_events"),
            [
                {
                    "model": "gemini-3.1-flash-lite",
                    "attempt": 1,
                    "reason": "http_429",
                    "quota_scope": "model",
                    "wait_seconds": 2,
                }
            ],
        )
        prompt_hashes = plan.get("request_prompt_hashes") or []
        self.assertEqual(len(prompt_hashes), 2)
        self.assertEqual(
            prompt_hashes[0].get("prompt_sha256"),
            prompt_hashes[1].get("prompt_sha256"),
        )

    def test_gemini_exact_model_accepts_rate_limit_wait_at_sixty_second_boundary(
        self,
    ) -> None:
        rate_limited = _FakeProviderResponse(
            {
                "error": {
                    "message": "modelRateLimit; retryDelay 60s",
                }
            },
            status_code=429,
            reason="Too Many Requests",
        )
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[rate_limited, ok],
        ) as post_mock, patch.object(cloud_runtime.time, "sleep") as sleep_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": (
                        "https://generativelanguage.googleapis.com/v1beta"
                    ),
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-3.1-flash-lite",
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client("Sadece OK yaz.")

        self.assertEqual(answer, "OK")
        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once_with(60)

    def test_gemini_exact_accessibility_probe_can_disable_rate_limit_wait(
        self,
    ) -> None:
        rate_limited = _FakeProviderResponse(
            {"error": {"message": "modelRateLimit; retryDelay 1s"}},
            status_code=429,
            reason="Too Many Requests",
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            return_value=rate_limited,
        ) as post_mock, patch.object(cloud_runtime.time, "sleep") as sleep_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": (
                        "https://generativelanguage.googleapis.com/v1beta"
                    ),
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-3.1-flash-lite",
                    "allow_model_fallback": False,
                    "max_exact_model_rate_limit_wait_seconds": 0,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            with self.assertRaises(requests.HTTPError):
                client("Sadece OK yaz.")

        self.assertEqual(post_mock.call_count, 1)
        sleep_mock.assert_not_called()

    def test_gemini_exact_model_survives_transient_then_bounded_rate_limit(
        self,
    ) -> None:
        unavailable = _FakeProviderResponse(
            {},
            status_code=503,
            reason="Service Unavailable",
        )
        rate_limited = _FakeProviderResponse(
            {"error": {"message": "modelRateLimit; retryDelay 1s"}},
            status_code=429,
            reason="Too Many Requests",
        )
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[unavailable, rate_limited, ok],
        ) as post_mock, patch.object(cloud_runtime.time, "sleep") as sleep_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": (
                        "https://generativelanguage.googleapis.com/v1beta"
                    ),
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-2.5-flash-lite",
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client("Sadece OK yaz.")

        self.assertEqual(answer, "OK")
        self.assertEqual(post_mock.call_count, 3)
        sleep_mock.assert_called_once_with(2)
        self.assertEqual(
            (getattr(client, "resource_plan", {}) or {}).get(
                "same_model_retry_events"
            ),
            [
                {
                    "model": "gemini-2.5-flash-lite",
                    "attempt": 1,
                    "reason": "http_503",
                },
                {
                    "model": "gemini-2.5-flash-lite",
                    "attempt": 2,
                    "reason": "http_429",
                    "quota_scope": "model",
                    "wait_seconds": 2,
                },
            ],
        )

    def test_gemini_exact_model_retries_one_transient_503_without_fallback(self) -> None:
        unavailable = _FakeProviderResponse(
            {},
            status_code=503,
            reason="Service Unavailable",
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-3.5-flash:generateContent?key=AIza-chat-secret"
            ),
        )
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-3.5-flash:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[unavailable, ok],
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-3.5-flash",
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client("Sadece OK yaz.")

        self.assertEqual(answer, "OK")
        self.assertEqual(post_mock.call_count, 2)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("actual_model"), "gemini-3.5-flash")
        self.assertFalse(plan.get("fallback_used"))
        self.assertEqual(
            plan.get("same_model_retry_events"),
            [{"model": "gemini-3.5-flash", "attempt": 1, "reason": "http_503"}],
        )

    def test_gemini_exact_model_retries_one_empty_response_without_fallback(self) -> None:
        empty = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": ""}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-3.1-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "Yeni cevap"}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemini-3.1-flash-lite:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[empty, ok],
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-3.1-flash-lite",
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client("E-ticaret insani yorar mi?")

        self.assertEqual(answer, "Yeni cevap")
        self.assertEqual(post_mock.call_count, 2)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("actual_model"), "gemini-3.1-flash-lite")
        self.assertFalse(plan.get("fallback_used"))
        self.assertEqual(
            plan.get("same_model_retry_events"),
            [
                {
                    "model": "gemini-3.1-flash-lite",
                    "attempt": 1,
                    "reason": "empty_response",
                }
            ],
        )

    def test_gemini_chat_falls_back_to_next_free_model_on_read_timeout(self) -> None:
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "Yedek Gemini cevabi."}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{cloud_runtime.GEMINI_VALIDATED_FREE_MODEL}:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(cloud_runtime.requests, "get", return_value=_FakeProviderResponse({"models": []})), patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[requests.ReadTimeout("provider timeout"), ok],
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-2.5-flash-lite",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Sadece cevap ver."), "Yedek Gemini cevabi.")

        self.assertEqual(len(post_mock.call_args_list), 2)
        self.assertEqual(getattr(client, "model_name", ""), cloud_runtime.GEMINI_VALIDATED_FREE_MODEL)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("actual_model"), cloud_runtime.GEMINI_VALIDATED_FREE_MODEL)
        self.assertTrue(plan.get("fallback_used"))

    def test_gemini_chat_extends_fallbacks_from_live_model_catalog(self) -> None:
        catalog = _FakeProviderResponse(
            {
                "models": [
                    {
                        "name": "models/gemma-4-31b-it",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            }
        )
        transient_errors = [
            _FakeProviderResponse(
                {},
                status_code=503,
                reason="Unavailable",
                url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=AIza-chat-secret",
            )
            for model in ("gemini-missing", *cloud_runtime.GEMINI_FALLBACK_MODELS)
        ]
        ok = _FakeProviderResponse(
            {"candidates": [{"content": {"parts": [{"text": "Katalog modeli calisti."}]}}]},
            url=(
                "https://generativelanguage.googleapis.com/v1beta/"
                "models/gemma-4-31b-it:generateContent?key=AIza-chat-secret"
            ),
        )

        with patch.object(cloud_runtime.requests, "get", return_value=catalog) as get_mock, patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[*transient_errors, ok],
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "gemini",
                    "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                    "api_key": "AIza-chat-secret",
                    "default_model": "gemini-missing",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client("Sadece OK yaz.")

        self.assertEqual(answer, "Katalog modeli calisti.")
        self.assertEqual(getattr(client, "model_name", ""), "gemma-4-31b-it")
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("requested_model"), "gemini-missing")
        self.assertEqual(plan.get("actual_model"), "gemma-4-31b-it")
        self.assertTrue(plan.get("fallback_used"))
        self.assertEqual(get_mock.call_args.kwargs.get("headers"), {"Accept": "application/json"})
        self.assertIn("models/gemma-4-31b-it:generateContent", str(post_mock.call_args_list[-1].args[0]))

    def test_set_ai_download_root_persists_in_custom_settings_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "ai_config.json"
            download_root = Path(tmp_dir) / "models"

            save_res = ai_pipeline.set_ai_download_root(
                str(download_root),
                settings_path=settings_path,
            )
            load_res = ai_pipeline.load_ai_settings(settings_path=settings_path)

            self.assertTrue(save_res.success, save_res.message)
            self.assertTrue(load_res.success, load_res.message)
            settings = (load_res.data or {}).get("settings") or {}
            self.assertEqual(str(download_root.resolve()), str(settings.get("download_root")))
            self.assertTrue(download_root.exists())

    def test_local_model_runtime_config_roundtrip_updates_resource_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "ai_config.json"
            model_path = Path(tmp_dir) / "gpt-oss-20b-q4_k_m.gguf"
            model_path.write_bytes(b"fake")
            record = {
                "repo_id": "openai/gpt-oss-20b",
                "filename": model_path.name,
                "local_path": str(model_path),
                "file_format": "GGUF",
            }

            save_res = ai_pipeline.save_local_model_runtime_config(
                record,
                {
                    "runtime_strategy": "auto",
                    "performance_preset": "eco",
                    "reasoning_effort": "low",
                    "num_ctx": 768,
                    "max_tokens": 96,
                    "num_thread": 2,
                    "num_batch": 16,
                    "num_gpu": 4,
                    "keep_alive": "0s",
                    "use_mmap": True,
                    "use_mlock": False,
                },
                settings_path=settings_path,
            )
            load_res = ai_pipeline.get_local_model_runtime_config(record, settings_path=settings_path)

            self.assertTrue(save_res.success, save_res.message)
            self.assertTrue(load_res.success, load_res.message)
            config = (load_res.data or {}).get("config") or {}
            plan = (load_res.data or {}).get("resource_plan") or {}
            self.assertEqual(config.get("runtime_strategy"), "llama_cpp")
            self.assertEqual(config.get("performance_preset"), "eco")
            self.assertEqual(config.get("reasoning_effort"), "low")
            self.assertLessEqual(plan.get("num_ctx"), 768)
            self.assertGreaterEqual(plan.get("max_tokens"), 256)
            self.assertEqual(plan.get("num_gpu"), 4)
            self.assertEqual(plan.get("runtime_strategy"), "llama_cpp")
            self.assertTrue(plan.get("use_mmap"))

    def test_get_hf_model_details_prioritizes_preferred_model_files(self) -> None:
        api_payload = {
            "id": "openai/gpt-oss-20b",
            "downloads": 123,
            "likes": 45,
            "lastModified": "2026-03-13T10:00:00.000Z",
            "pipeline_tag": "text-generation",
            "tags": ["gguf", "text-generation"],
            "cardData": {"summary": "Local coding model."},
            "siblings": [
                {"rfilename": "model-fp16.safetensors", "size": 300},
                {"rfilename": "model-q5_k_m.gguf", "size": 200},
                {"rfilename": "model-q4_k_m.gguf", "size": 100},
                {"rfilename": "README.md", "size": 10},
            ],
        }

        with patch.object(
            ai_pipeline,
            "load_ai_settings",
            return_value=Result.ok(
                close_dialog=False,
                data={"settings": {"prefer_extensions": [".gguf", ".safetensors", ".bin"]}},
            ),
        ), patch.object(
            ai_pipeline,
            "fetch_model_details",
            return_value=Result.ok(close_dialog=False, data={"json": api_payload}),
        ):
            result = ai_pipeline.get_hf_model_details("openai/gpt-oss-20b")

        self.assertTrue(result.success, result.message)
        detail = (result.data or {}).get("detail") or {}
        files = detail.get("files") or []
        self.assertEqual([row.get("filename") for row in files], [
            "model-q4_k_m.gguf",
            "model-q5_k_m.gguf",
        ])
        self.assertEqual(str(detail.get("description")), "Local coding model.")

    def test_download_hf_model_file_saves_file_and_registers_db_record(self) -> None:
        body = b"fake-model-binary"
        response = _FakeDownloadResponse(
            body,
            headers={
                "Content-Length": str(len(body)),
                "ETag": "etag-123",
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            ai_pipeline.requests,
            "get",
            return_value=response,
        ):
            result = ai_pipeline.download_hf_model_file(
                repo_id="openai/gpt-oss-20b",
                filename="gpt-oss-20b-q4_k_m.gguf",
                download_root=tmp_dir,
                db_name=self.db_path,
            )
            library_res = ai_pipeline.list_installed_models(db_name=self.db_path)

            self.assertTrue(result.success, result.message)
            record = (result.data or {}).get("record") or {}
            local_path = Path(str(record.get("local_path") or ""))
            self.assertTrue(local_path.exists())
            self.assertEqual(local_path.read_bytes(), body)
            self.assertTrue(library_res.success, library_res.message)
            records = (library_res.data or {}).get("records") or []
            self.assertEqual(len(records), 1)
            self.assertEqual(str(records[0].get("repo_id")), "openai/gpt-oss-20b")
            self.assertEqual(str(records[0].get("quantization")), "Q4_K_M")

    def test_local_model_registry_recovers_complete_gguf_files_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "models"
            repo_dir = root / "Qwen" / "Qwen3-4B-GGUF"
            repo_dir.mkdir(parents=True)
            complete = repo_dir / "Qwen3-4B-Q4_K_M.gguf"
            complete.write_bytes(b"complete-model")
            (repo_dir / "Qwen3-4B-Q8_0.gguf.part").write_bytes(b"partial-model")

            first = ai_pipeline.reconcile_installed_models(
                download_root=root,
                db_name=self.db_path,
            )
            second = ai_pipeline.reconcile_installed_models(
                download_root=root,
                db_name=self.db_path,
            )
            listed = ai_pipeline.list_installed_models(
                download_root=root,
                db_name=self.db_path,
            )

            self.assertTrue(first.success, first.message)
            self.assertTrue(second.success, second.message)
            self.assertEqual((first.data or {}).get("discovered_count"), 1)
            records = list((listed.data or {}).get("records") or [])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].get("repo_id"), "Qwen/Qwen3-4B-GGUF")
            self.assertEqual(records[0].get("filename"), complete.name)
            self.assertEqual(records[0].get("quantization"), "Q4_K_M")
            self.assertTrue(records[0].get("exists_on_disk"))

    def test_local_model_registry_retains_but_marks_missing_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "models"
            repo_dir = root / "orderscout" / "temporary-model"
            repo_dir.mkdir(parents=True)
            model_path = repo_dir / "temporary-Q4_K_M.gguf"
            model_path.write_bytes(b"temporary")
            ai_pipeline.reconcile_installed_models(download_root=root, db_name=self.db_path)
            model_path.unlink()

            reconciled = ai_pipeline.reconcile_installed_models(
                download_root=root,
                db_name=self.db_path,
            )
            listed = ai_pipeline.list_installed_models(
                download_root=root,
                db_name=self.db_path,
                reconcile_disk=False,
            )

            self.assertTrue(reconciled.success, reconciled.message)
            self.assertEqual((reconciled.data or {}).get("missing_count"), 1)
            records = list((listed.data or {}).get("records") or [])
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0].get("exists_on_disk"))

    def test_download_can_pause_with_partial_file_and_resume_from_http_range(self) -> None:
        chunk_size = 1024 * 1024
        first_chunk = b"a" * chunk_size
        second_chunk = b"b" * chunk_size
        first_response = _FakeDownloadResponse(
            first_chunk + second_chunk,
            headers={"Content-Length": str(chunk_size * 2)},
        )
        resume_response = _FakeDownloadResponse(
            second_chunk,
            headers={"Content-Length": str(chunk_size)},
            status_code=206,
        )
        pause = {"requested": False}

        def progress(_current: int, _total: int, _label: str) -> None:
            pause["requested"] = True

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            ai_pipeline.requests,
            "get",
            side_effect=[first_response, resume_response],
        ) as get_mock:
            paused = ai_pipeline.download_hf_model_file(
                repo_id="orderscout/pause-model",
                filename="pause-model-q4_k_m.gguf",
                download_root=tmp_dir,
                progress_callback=progress,
                pause_requested=lambda: pause["requested"],
                db_name=self.db_path,
            )

            self.assertTrue(paused.success, paused.message)
            self.assertTrue((paused.data or {}).get("paused"))
            partial_path = Path(str((paused.data or {}).get("partial_path") or ""))
            self.assertTrue(partial_path.exists())
            self.assertEqual(partial_path.read_bytes(), first_chunk)
            self.assertEqual(len((ai_pipeline.list_installed_models(db_name=self.db_path).data or {}).get("records") or []), 0)

            resumed = ai_pipeline.download_hf_model_file(
                repo_id="orderscout/pause-model",
                filename="pause-model-q4_k_m.gguf",
                download_root=tmp_dir,
                db_name=self.db_path,
            )

            self.assertTrue(resumed.success, resumed.message)
            record = dict((resumed.data or {}).get("record") or {})
            self.assertEqual(Path(record["local_path"]).read_bytes(), first_chunk + second_chunk)
            self.assertEqual(
                get_mock.call_args_list[1].kwargs.get("headers"),
                {"Range": f"bytes={chunk_size}-"},
            )

    def test_delete_installed_model_removes_safe_file_db_record_and_runtime_config(self) -> None:
        body = b"deletable-local-model"
        response = _FakeDownloadResponse(
            body,
            headers={"Content-Length": str(len(body))},
        )
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            ai_pipeline.requests,
            "get",
            return_value=response,
        ):
            downloaded = ai_pipeline.download_hf_model_file(
                repo_id="orderscout/delete-model",
                filename="delete-model-q4_k_m.gguf",
                download_root=tmp_dir,
                db_name=self.db_path,
            )
            record = dict((downloaded.data or {}).get("record") or {})
            settings_path = Path(tmp_dir) / "ai-settings.json"
            saved = ai_pipeline.save_local_model_runtime_config(
                record,
                {"num_ctx": 1024},
                settings_path=settings_path,
            )
            config_key = str(((saved.data or {}).get("config") or {}).get("config_key") or "")

            deleted = ai_pipeline.delete_installed_model(
                int(record["id"]),
                settings_path=settings_path,
                db_name=self.db_path,
            )

            self.assertTrue(deleted.success, deleted.message)
            self.assertFalse(Path(record["local_path"]).exists())
            records = (ai_pipeline.list_installed_models(db_name=self.db_path).data or {}).get("records") or []
            self.assertEqual(records, [])
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertNotIn(config_key, settings.get("model_runtime_configs") or {})

    def test_delete_installed_model_refuses_file_outside_recorded_download_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            download_root = base / "models"
            download_root.mkdir()
            outside_file = base / "outside-model.gguf"
            outside_file.write_bytes(b"must-stay")
            record = ai_pipeline._upsert_installed_model(
                repo_id="orderscout/outside-model",
                filename=outside_file.name,
                local_path=str(outside_file),
                download_root=str(download_root),
                file_format="GGUF",
                quantization="Q4_K_M",
                size_bytes=outside_file.stat().st_size,
                source_url="https://example.test/outside-model.gguf",
                db_name=self.db_path,
            )

            result = ai_pipeline.delete_installed_model(
                int(record["id"]),
                db_name=self.db_path,
            )

            self.assertFalse(result.success)
            self.assertIn("Güvenlik sınırı", result.message)
            self.assertTrue(outside_file.exists())
            records = (ai_pipeline.list_installed_models(db_name=self.db_path).data or {}).get("records") or []
            self.assertEqual(len(records), 1)

    def test_gpt_oss_20b_resource_plan_uses_tight_safe_limits(self) -> None:
        snapshot = ResourceSnapshot(
            total_ram_bytes=16 * GIB,
            available_ram_bytes=10 * GIB,
            cpu_count=12,
            gpu_names=("RTX 3050 Laptop",),
            gpu_total_vram_bytes=4 * GIB,
            gpu_free_vram_bytes=3 * GIB,
            disk_free_bytes=80 * GIB,
        )

        plan = build_local_resource_plan(
            {"repo_id": "openai/gpt-oss-20b", "filename": "gpt-oss-20b.gguf"},
            model_hint="gpt-oss:20b",
            snapshot=snapshot,
        )

        self.assertTrue(plan.safe_to_run)
        self.assertIn(plan.profile, {"disk_guarded_large_model", "survival_mmap_large_model"})
        self.assertLessEqual(plan.num_ctx, 512)
        self.assertLessEqual(plan.max_tokens, 256)
        self.assertGreater(plan.num_gpu, 0)
        self.assertEqual(plan.keep_alive, "0s")
        self.assertIn(plan.process_priority, {"below_normal", "idle"})
        self.assertTrue(plan.trim_working_set)
        self.assertGreaterEqual(plan.startup_timeout_seconds, 180)

    def test_gpt_oss_20b_resource_plan_blocks_emergency_low_memory(self) -> None:
        snapshot = ResourceSnapshot(
            total_ram_bytes=16 * GIB,
            available_ram_bytes=2 * GIB,
            cpu_count=12,
            gpu_names=("RTX 3050 Laptop",),
            gpu_total_vram_bytes=4 * GIB,
            gpu_free_vram_bytes=512 * 1024 * 1024,
            disk_free_bytes=80 * GIB,
        )

        plan = build_local_resource_plan(
            {"repo_id": "openai/gpt-oss-20b", "filename": "gpt-oss-20b.gguf"},
            model_hint="gpt-oss:20b",
            snapshot=snapshot,
        )

        self.assertFalse(plan.safe_to_run)
        self.assertEqual(plan.profile, "blocked_insufficient_memory")
        self.assertEqual(plan.process_priority, "idle")
        self.assertTrue(plan.trim_working_set)

    def test_agent_llm_decision_selects_order_count_tool(self) -> None:
        def fake_planner(prompt: str) -> str:
            self.assertIn("orders.summary", prompt)
            self.assertIn("mode", prompt)
            self.assertNotIn("SELECT", prompt.upper())
            return '{"mode": "tool", "tool": "orders.summary", "arguments": {"period": "today"}}'

        result = choose_tool("Bugün kaç tane siparişim var?", planner_client=fake_planner)

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", None), "orders.summary")
        self.assertEqual(getattr(decision, "source", None), "llm")

    def test_agent_llm_decision_can_answer_without_tool(self) -> None:
        result = choose_action(
            "Nasılsın kral?",
            planner_client=lambda _prompt: '{"mode": "answer", "response": "İyiyim kral, buradayım."}',
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "mode", None), "answer")
        self.assertIn("buradayim", str(getattr(decision, "response", "")).casefold())
        self.assertFalse(getattr(decision, "tool_name", ""))

    def test_agent_llm_decision_supports_sanitized_multi_tool_plan(self) -> None:
        def fake_planner(_prompt: str) -> str:
            return (
                '{"mode": "tools", "calls": ['
                '{"tool": "orders.summary", "arguments": {"period": "bugun", "sql": "drop table orders"}},'
                '{"tool": "stock.low_stock", "arguments": {"limit": 999, "ignored": true}}'
                "]} "
            )

        result = choose_action("Bugun siparis ve stok durumunu ozetle", planner_client=fake_planner)

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "mode", None), "tools")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        self.assertEqual([call.tool_name for call in calls], ["orders.summary", "stock.low_stock"])
        self.assertEqual(calls[0].arguments, {"period": "today"})
        self.assertEqual(calls[1].arguments, {"limit": 50})

    def test_agent_fallback_routes_profit_and_domain_questions(self) -> None:
        profit_res = choose_tool("Bugunku ciro ve kar tahmini nedir?")
        listing_res = choose_tool("Ilan durumunu ozetle")
        logistics_res = choose_tool("Kargo tarifelerimi goster")
        marketplace_res = choose_tool("Pazaryeri hesaplarini ozetle")
        ready_res = choose_tool("Bugun kargolanacak kac siparisim var?")
        stock_res = choose_tool("Stok genel ozetini ver")
        diacritic_res = choose_tool("Bug\u00fcn ka\u00e7 sipari\u015fim var?")

        self.assertTrue(profit_res.success, profit_res.message)
        self.assertEqual(self._decision_tool_names(profit_res), ["orders.revenue_total", "finance.profit_amount"])
        self.assertTrue(listing_res.success, listing_res.message)
        self.assertEqual(self._decision_tool_names(listing_res), ["listing.counts"])
        self.assertTrue(logistics_res.success, logistics_res.message)
        self.assertEqual(self._decision_tool_names(logistics_res), ["logistics.tariff_count"])
        self.assertTrue(marketplace_res.success, marketplace_res.message)
        self.assertEqual(self._decision_tool_names(marketplace_res), ["marketplaces.account_count"])
        self.assertTrue(ready_res.success, ready_res.message)
        self.assertEqual(self._decision_tool_names(ready_res), ["orders.ready_to_ship_count"])
        self.assertTrue(stock_res.success, stock_res.message)
        self.assertEqual(self._decision_tool_names(stock_res), ["stock.inventory_overview"])
        self.assertTrue(diacritic_res.success, diacritic_res.message)
        self.assertEqual(self._decision_tool_names(diacritic_res), ["orders.count"])

    def test_atomic_tool_registry_covers_domains(self) -> None:
        registry = available_tools()
        expected = {
            "orders.count",
            "orders.status_counts",
            "orders.revenue_total",
            "orders.ready_to_ship_count",
            "orders.lookup",
            "returns.count",
            "returns.status_counts",
            "returns.waiting_action_count",
            "returns.lookup",
            "finance.profit_amount",
            "finance.cashflow_net",
            "finance.cost_item_lookup",
            "stock.low_stock_count",
            "stock.item_count",
            "stock.items_list",
            "stock.search",
            "listing.counts",
            "listing.search",
            "listing.attention_count",
            "listing.price_lookup",
            "listing.title_lookup",
            "listing.detail_lookup",
            "listing.stock_lookup",
            "listing.status_lookup",
            "listing.url_lookup",
            "marketplaces.catalog",
            "marketplaces.account_count",
            "marketplaces.account_lookup",
            "accounts.invalid_token_count",
            "logistics.tariff_count",
            "logistics.tariff_lookup",
        }

        self.assertTrue(expected.issubset(set(registry)))
        for name in expected:
            tool = registry[name]
            self.assertTrue(tool.read_only)
            self.assertFalse(tool.destructive)
            self.assertIn(".", name)

    def test_prompt_categories_route_to_atomic_tools(self) -> None:
        cases = [
            ("easy", "Bugun kac siparisim var?", ["orders.count"]),
            ("medium", "Bugun siparis ve stok sayilarini ozetle", ["orders.count", "stock.low_stock_count"]),
            (
                "hard",
                "Bugun ciro, kar, iade, kargoya hazir ve risk sayilarini beraber kontrol et",
                [
                    "orders.revenue_total",
                    "finance.profit_amount",
                    "returns.count",
                    "orders.ready_to_ship_count",
                    "orders.fulfillment_risk_count",
                ],
            ),
            (
                "extreme",
                "Bugun siparis, ciro, kar, stok, ilan, pazaryeri, token, kargo tarife ve maliyet kalemi durumunu tek raporda toparla",
                [
                    "orders.count",
                    "orders.revenue_total",
                    "finance.profit_amount",
                    "stock.low_stock_count",
                ],
            ),
        ]

        for _label, prompt, expected_prefix in cases:
            result = choose_action(prompt)
            self.assertTrue(result.success, result.message)
            actual = self._decision_tool_names(result)
            self.assertGreaterEqual(len(actual), min(len(expected_prefix), 1))
            self.assertTrue(set(expected_prefix).issubset(set(actual)), f"{_label}: {actual}")

    def test_agent_llm_decision_prefers_atomic_tools_and_sanitizes_multi_tool_plan(self) -> None:
        def fake_planner(_prompt: str) -> str:
            return (
                '{"mode": "tools", "calls": ['
                '{"tool": "orders.count", "arguments": {"period": "bugun", "sql": "drop table orders"}},'
                '{"tool": "orders.revenue_total", "arguments": {"period": "today"}},'
                '{"tool": "stock.low_stock_count", "arguments": {"limit": 999}}'
                "]} "
            )

        result = choose_action("Bugun siparis, ciro ve stok sayisini ver", planner_client=fake_planner)

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        self.assertEqual([call.tool_name for call in calls], ["orders.count", "orders.revenue_total", "stock.low_stock_count"])
        self.assertEqual(calls[0].arguments, {"period": "today"})
        self.assertEqual(calls[2].arguments, {})

    def test_agent_repairs_single_tool_period_from_custom_last_days(self) -> None:
        result = choose_action(
            "Son 8 gunde kac siparisim var?",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.count","arguments":{"period":"today"}}',
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "orders.count")
        self.assertEqual((getattr(decision, "arguments", {}) or {}).get("period"), "last_8_days")

    def test_agent_repairs_multi_tool_period_from_custom_last_days(self) -> None:
        def fake_planner(_prompt: str) -> str:
            return (
                '{"mode":"tools","calls":['
                '{"tool":"orders.count","arguments":{"period":"today"}},'
                '{"tool":"orders.revenue_total","arguments":{"period":"today"}},'
                '{"tool":"stock.low_stock_count","arguments":{}}'
                "]} "
            )

        result = choose_action("Son 8 gunde siparis, ciro ve stok riskini ozetle", planner_client=fake_planner)

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        call_args = {call.tool_name: call.arguments or {} for call in calls}
        self.assertEqual(call_args.get("orders.count", {}).get("period"), "last_8_days")
        self.assertEqual(call_args.get("orders.revenue_total", {}).get("period"), "last_8_days")
        self.assertEqual(call_args.get("stock.low_stock_count"), {})

    def test_agent_explicit_yesterday_target_outranks_today_exclusion_phrase(self) -> None:
        def fake_planner(_prompt: str) -> str:
            return (
                '{"mode":"tools","calls":['
                '{"tool":"orders.count","arguments":{"period":"today"}},'
                '{"tool":"orders.revenue_total","arguments":{"period":"today"}}'
                "]} "
            )

        result = choose_action(
            "Dun icin de ayni iki metrigi ver ve bugunle karistirma.",
            planner_client=fake_planner,
            history=[
                {
                    "role": "assistant",
                    "content": "Bugun 3 siparis ve 2400 TRY ciro var.",
                    "context": {
                        "kind": "orders_metric_scope",
                        "source_tool": "orders.count",
                        "period": "today",
                        "period_label": "2026-07-16",
                        "order_count": 3,
                    },
                }
            ],
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        self.assertEqual(
            [(call.tool_name, (call.arguments or {}).get("period")) for call in calls],
            [
                ("orders.count", "yesterday"),
                ("orders.revenue_total", "yesterday"),
            ],
        )

    def test_agent_compares_two_historical_metric_scopes_without_new_tools(self) -> None:
        planner_calls = 0

        def fake_planner(_prompt: str) -> str:
            nonlocal planner_calls
            planner_calls += 1
            return '{"mode":"tools","calls":[{"tool":"orders.count","arguments":{"period":"this_month"}}]}'

        history = [
            {
                "role": "assistant",
                "content": "Bugun 3 siparis var ve toplam cironuz 2400.0 TL.",
                "context": {
                    "kind": "orders_metric_scope",
                    "source_tool": "orders.count",
                    "period": "today",
                    "period_label": "2026-07-16",
                    "order_count": 3,
                },
            },
            {
                "role": "assistant",
                "content": "Dun 8 siparis var ve toplam cirosu 30100.0 TL.",
                "context": {
                    "kind": "orders_metric_scope",
                    "source_tool": "orders.count",
                    "period": "yesterday",
                    "period_label": "2026-07-15",
                    "order_count": 8,
                },
            },
        ]

        result = run_agent_turn(
            "Bu iki gunu siparis adedi ve ciro acisindan kisa karsilastir; yeni arac cagirma.",
            planner_client=fake_planner,
            chat_client=fake_planner,
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(planner_calls, 0)
        self.assertEqual((result.data or {}).get("tool_calls"), [])
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("2026-07-15: 8 sipariş, 30100 TL ciro.", answer)
        self.assertIn("2026-07-16: 3 sipariş, 2400 TL ciro.", answer)
        self.assertIn("5 daha fazla", answer)
        self.assertIn("27700 TL daha yüksek", answer)

    def test_agent_contextual_same_month_carries_scope_across_domains(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Bu ay 263 siparis ve 35304154.37 TL ciro var.",
                "context": {
                    "kind": "orders_metric_scope",
                    "source_tool": "orders.count",
                    "period": "this_month",
                    "period_label": "2026-07-01..2026-07-16",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-16",
                    "order_count": 263,
                    "revenue_total": 35304154.37,
                },
            }
        ]

        result = choose_action(
            (
                "Ayni ay kapsami icin iade claim sayisini ve toplam iade "
                "tutarini ver; siparis metriklerini tekrar etme."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":['
                '{"tool":"returns.count","arguments":{"period":"all"}},'
                '{"tool":"returns.amount_total","arguments":{"period":"all"}}'
                "]} "
            ),
            history=history,
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        self.assertEqual(
            [(call.tool_name, call.arguments) for call in calls],
            [
                (
                    "returns.count",
                    {
                        "start_date": "2026-07-01",
                        "end_date": "2026-07-16",
                    },
                ),
                (
                    "returns.amount_total",
                    {
                        "start_date": "2026-07-01",
                        "end_date": "2026-07-16",
                    },
                ),
            ],
        )

    def test_negative_profit_repeat_does_not_override_return_count_and_amount(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Bugun 3 siparis ve 2400 TL ciro var.",
                "context": {
                    "kind": "orders_metric_scope",
                    "source_tool": "orders.count",
                    "period": "today",
                    "period_label": "2026-07-16",
                    "order_count": 3,
                    "revenue_total": 2400.0,
                },
            }
        ]

        result = choose_action(
            (
                "Ayni gun kapsami icin iade claim sayisini ve toplam iade "
                "tutarini ver; siparis ve kar metriklerini tekrar etme."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"finance.profit_amount",'
                '"arguments":{"period":"today"}}'
            ),
            history=history,
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        calls = list(getattr(decision, "tool_calls", ()) or [])
        self.assertEqual(
            [(call.tool_name, call.arguments) for call in calls],
            [
                ("returns.count", {"period": "today"}),
                ("returns.amount_total", {"period": "today"}),
            ],
        )
        self.assertFalse(
            ai_agent._profit_intent_requested(
                ai_agent._normalized_match_text(
                    "siparis ve kar metriklerini tekrar etme"
                )
            )
        )

    def test_return_count_and_amount_create_structured_conversation_context(self) -> None:
        context = ai_agent._conversation_context_from_tool_results(
            [
                {
                    "tool": "returns.count",
                    "arguments": {"period": "today"},
                    "data": {
                        "period": "today",
                        "period_label": "2026-07-16",
                        "count": 0,
                    },
                },
                {
                    "tool": "returns.amount_total",
                    "arguments": {"period": "today"},
                    "data": {
                        "period": "today",
                        "period_label": "2026-07-16",
                        "total_amount": 0.0,
                        "currency": "TRY",
                    },
                },
            ]
        )

        self.assertEqual(
            context,
            {
                "kind": "return_metric_scope",
                "source_tool": "returns.count",
                "period": "today",
                "period_label": "2026-07-16",
                "claim_count": 0,
                "total_amount": 0.0,
                "currency": "TRY",
            },
        )

    def test_stock_scalar_count_creates_safe_authoritative_conversation_context(self) -> None:
        answer = (
            "Sıfır veya negatif stok bakiyesine sahip toplam 2 adet ürün bulunmaktadır."
        )
        context = ai_agent._conversation_context_from_tool_results(
            [
                {
                    "tool": "stock.zero_or_negative_count",
                    "arguments": {},
                    "message": answer,
                    "data": {"count": 2, "private_rows": [{"customer": "hidden"}]},
                }
            ]
        )

        self.assertEqual(
            context,
            {
                "kind": "scalar_tool_result",
                "active_domain": "stock",
                "source_tool": "stock.zero_or_negative_count",
                "scalar_facts": {"count": 2},
                "authoritative_answer": answer,
            },
        )
        self.assertNotIn("private_rows", context)

    def test_agent_recalls_return_metrics_after_model_switch_without_new_tool(self) -> None:
        planner_calls = 0

        def fail_if_called(_prompt: str) -> str:
            nonlocal planner_calls
            planner_calls += 1
            raise AssertionError("No-tool history recall must not call the model.")

        history = [
            {
                "role": "assistant",
                "content": (
                    "2026-07-16 doneminde 0 iade/claim var. "
                    "2026-07-16 donemi tahmini iade tutari 0.00 TRY."
                ),
                "context": {
                    "kind": "return_metric_scope",
                    "source_tool": "returns.count",
                    "period": "today",
                    "period_label": "2026-07-16",
                    "claim_count": 0,
                    "total_amount": 0.0,
                    "currency": "TRY",
                },
            }
        ]

        result = run_agent_turn(
            (
                "Model degisti ama ayni state devam ediyor: az onceki ayni gun "
                "iade sonucunu yeni arac cagirmadan yalniz donem, claim sayisi "
                "ve toplam tutar olarak tekrar et."
            ),
            planner_client=fail_if_called,
            chat_client=fail_if_called,
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(planner_calls, 0)
        self.assertEqual((result.data or {}).get("tool_calls"), [])
        self.assertEqual(
            (result.data or {}).get("answer"),
            "2026-07-16: 0 claim, toplam iade tutari 0 TRY.",
        )
        self.assertEqual(
            (result.data or {}).get("decision_path"),
            "explicit_no_tool_guard",
        )

    def test_return_approval_prepare_creates_pending_action_context(self) -> None:
        context = ai_agent._conversation_context_from_tool_results(
            [
                {
                    "tool": "returns.approve.prepare",
                    "data": {
                        "action": {
                            "approval_required": True,
                            "status": "pending_approval",
                            "action_type": "orders.approve_return_claim",
                            "action_id": "ACTION-1",
                            "risk_level": "high",
                            "execute_enabled": True,
                            "external_write": True,
                            "api_call_performed": False,
                            "db_write_performed": False,
                            "selected_record_count": 1,
                            "preview_item_count": 1,
                            "execute_input_count": 1,
                            "rows": [
                                {
                                    "claim_id": "4ec0b24c-d6a2-4713-913f-ffa77d6bfc55",
                                    "order_number": "1341575886",
                                }
                            ],
                        }
                    },
                }
            ]
        )

        self.assertEqual(context.get("kind"), "pending_action")
        self.assertEqual(
            context.get("action_type"),
            "orders.approve_return_claim",
        )
        self.assertEqual(
            context.get("claim_ids"),
            ["4ec0b24c-d6a2-4713-913f-ffa77d6bfc55"],
        )
        self.assertEqual(context.get("order_numbers"), ["1341575886"])
        self.assertFalse(context.get("api_call_performed"))
        self.assertFalse(context.get("db_write_performed"))

    def test_agent_recalls_cancelled_return_prepare_without_new_tool(self) -> None:
        client_calls = 0

        def fail_if_called(_prompt: str) -> str:
            nonlocal client_calls
            client_calls += 1
            raise AssertionError("Cancelled preparation recall must be deterministic.")

        history = [
            {
                "role": "assistant",
                "content": (
                    "Onay gerekiyor: 1 iade onaya hazirlaniyor. "
                    "Gercek API istegi veya DB yazimi yapilmadi. "
                    "Claim: 4ec0b24c-d6a2-4713-913f-ffa77d6bfc55 | "
                    "siparis: 1341575886"
                ),
                "context": {
                    "kind": "pending_action",
                    "action_type": "orders.approve_return_claim",
                    "approval_required": True,
                    "claim_ids": ["4ec0b24c-d6a2-4713-913f-ffa77d6bfc55"],
                    "order_numbers": ["1341575886"],
                    "api_call_performed": False,
                    "db_write_performed": False,
                },
            },
            {
                "role": "assistant",
                "content": (
                    "Tamam, bu islemi calistirmiyorum. Onay vermedigin icin "
                    "gercek API istegi, DB yazimi veya dosya/cikti uretimi yapilmadi."
                ),
            },
        ]

        result = run_agent_turn(
            (
                "Az once iptal ettigimiz iade onay hazirliginin claim ve siparis "
                "kimligini, sonra da yan etki olusup olusmadigini yeni arac "
                "cagirmadan kisa ozetle."
            ),
            planner_client=fail_if_called,
            chat_client=fail_if_called,
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(client_calls, 0)
        self.assertEqual((result.data or {}).get("tool_calls"), [])
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("4ec0b24c-d6a2-4713-913f-ffa77d6bfc55", answer)
        self.assertIn("1341575886", answer)
        self.assertIn("API istegi", answer)
        self.assertIn("veritabani yazimi", answer)
        self.assertIn("yapilmadi", answer)

    def test_cancelled_label_prepare_recall_uses_history_without_tool_or_model(self) -> None:
        client_calls = 0

        def fail_if_called(_prompt: str) -> str:
            nonlocal client_calls
            client_calls += 1
            raise AssertionError("Canceled label recall must not call a model.")

        history = [
            {
                "role": "assistant",
                "content": (
                    "Onay gerekiyor: 1 siparis icin etiket olusturma hazirlaniyor.\n"
                    "Gercek API istegi, DB yazimi, dosya veya yazici ciktisi "
                    "olusturulmadi.\n"
                    "Sablon: TANEX 2610.\n"
                    "1. Siparis etiketi olusturma onayi | siparis: 1238656253"
                ),
                "context": {
                    "kind": "pending_action",
                    "action_type": "labels.action_create_labels_from_selected_orders",
                    "approval_required": True,
                    "order_numbers": ["1238656253"],
                    "api_call_performed": False,
                    "db_write_performed": False,
                },
            },
            {
                "role": "assistant",
                "content": (
                    "Tamam, bu islemi calistirmiyorum. Onay vermedigin icin "
                    "gercek API istegi, DB yazimi veya dosya/cikti uretimi yapilmadi."
                ),
            },
        ]

        result = run_agent_turn(
            (
                "Az once iptal ettigimiz etiket hazirliginda hangi siparis ve "
                "hangi sablon vardi, yan etki oldu mu? Yeni arac cagirma."
            ),
            planner_client=fail_if_called,
            chat_client=fail_if_called,
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(client_calls, 0)
        self.assertEqual((result.data or {}).get("tool_calls"), [])
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("1238656253", answer)
        self.assertIn("TANEX 2610", answer)
        self.assertIn("API istegi", answer)
        self.assertIn("DB yazimi", answer)
        self.assertIn("dosya veya yazici ciktisi olusturulmadi", answer)

    def test_sevke_hazir_real_count_is_not_misread_as_history_pronoun(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Onceki secimde 2 siparis listelendi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.query",
                    "order_numbers": ["ORD-1", "ORD-2"],
                    "listed_count": 2,
                    "total_count": 2,
                    "truncated": False,
                },
            }
        ]

        result = choose_action(
            (
                "Tum donemde sevke hazir gercek siparis sayisi kac? "
                "Simulasyonlari dahil etme."
            ),
            planner_client=lambda _prompt: (_ for _ in ()).throw(
                RuntimeError("provider unavailable")
            ),
            history=history,
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "orders.ready_to_ship_count",
        )
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"period": "all"},
        )

    def test_ready_count_scope_respects_explicit_followup_list_limit(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Tum donemde kargoya hazir 199 siparis var.",
                "context": {
                    "kind": "orders_ready_to_ship_scope",
                    "source_tool": "orders.ready_to_ship_count",
                    "period": "all",
                    "total_count": 199,
                    "simulated_excluded": 0,
                },
            }
        ]

        result = choose_action(
            (
                "Bunlardan en yeni ilk 5 sevke hazir siparisi siparis "
                "numarasi, durum, kargo ve tutarla listele."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.ready_to_ship",'
                '"arguments":{"period":"all","limit":199}}'
            ),
            history=history,
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "orders.ready_to_ship",
        )
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"period": "all", "limit": 5},
        )

    def test_selected_ready_subset_cargo_distribution_stays_on_subset(self) -> None:
        order_numbers = [f"ORD-SELECTED-{index}" for index in range(1, 6)]
        history = [
            {
                "role": "assistant",
                "content": "199 kayittan secilen ilk 5 siparis listelendi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.ready_to_ship",
                    "period": "all",
                    "order_numbers": order_numbers,
                    "listed_count": 5,
                    "total_count": 199,
                    "truncated": True,
                },
            }
        ]

        decision = ai_agent._intent_override_decision(
            (
                "Bu secili 5 siparis hangi kargo firmalarina dagiliyor? "
                "Yalniz firma ve adet olarak ver."
            ),
            history=history,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(getattr(decision, "tool_name", ""), "orders.ready_to_ship")
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"period": "all", "limit": 5},
        )

    def test_zero_or_negative_stock_count_ignores_excluded_low_stock_metric(self) -> None:
        result = choose_action(
            (
                "Stok adedi sifir veya eksi olan kayit sayisini ver; "
                "dusuk stok esigini tekrar etme."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":['
                '{"tool":"stock.inventory_overview","arguments":{"limit":20}},'
                '{"tool":"stock.low_stock_count","arguments":{}}'
                "]}"
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "stock.zero_or_negative_count",
        )
        self.assertEqual(getattr(decision, "arguments", {}), {})
        self.assertEqual(
            [call.tool_name for call in getattr(decision, "tool_calls", ())],
            ["stock.zero_or_negative_count"],
        )

    def test_listing_multi_status_distribution_outranks_attention_list(self) -> None:
        result = choose_action(
            "Ilanlarin satista, satis disi, kilitli ve arsiv durum dagilimini ver.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"listing.attention",'
                '"arguments":{"limit":10}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "listing.counts",
        )
        self.assertEqual(getattr(decision, "arguments", {}), {})

    def test_listing_aggregate_metrics_without_distribution_word_use_counts(self) -> None:
        result = choose_action(
            (
                "Ilan genel metriklerini toplam, aktif, satista, satis disi, "
                "arsiv ve stoksuz adetleriyle ver; kayit listeleme."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"listing.attention_count",'
                '"arguments":{}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "listing.counts")
        self.assertEqual(getattr(decision, "arguments", {}), {})
        self.assertEqual(
            [call.tool_name for call in getattr(decision, "tool_calls", ())],
            ["listing.counts"],
        )

    def test_marketplace_catalog_summary_respects_no_row_list_instruction(self) -> None:
        prompt = (
            "Pazaryeri katalog ozetini toplam, aktif, kabul edilmis ve "
            "bekleyen onerilen adetleriyle ver; kayit listeleme."
        )
        answer = ai_agent._deterministic_tool_answer(
            prompt,
            [
                {
                    "tool": "marketplaces.catalog",
                    "message": "1 pazaryeri kaydi bulundu.",
                    "data": {
                        "total": 1,
                        "active": 1,
                        "accepted": 1,
                        "pending": 0,
                        "records": [
                            {
                                "code": "TRENDYOL",
                                "label": "Trendyol",
                                "is_active": True,
                                "is_accepted": True,
                                "source": "Kullanima Alinmis",
                            }
                        ],
                    },
                }
            ],
        )

        self.assertEqual(
            answer,
            (
                "Toplam 1 kayit; aktif 1, kabul edilmis/kayitli 1, "
                "bekleyen onerilen 0."
            ),
        )
        self.assertNotIn("TRENDYOL", answer)

    def test_explicit_cross_domain_priority_report_keeps_all_requested_metrics(self) -> None:
        prompt = (
            "Bugunku operasyon onceliklerimi siparis sayisi, kargoya hazir, "
            "fulfillment riski, WaitingInAction iade, sifir veya eksi stok, "
            "dikkat isteyen ilan ve token sorunu metrikleriyle tek kisa "
            "raporda sirala; kar yorumu yapma."
        )
        result = choose_action(
            prompt,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.fulfillment_risk_count",'
                '"arguments":{"period":"today"}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            [call.tool_name for call in getattr(decision, "tool_calls", ())],
            [
                "orders.count",
                "orders.ready_to_ship_count",
                "orders.fulfillment_risk_count",
                "returns.waiting_action_count",
                "stock.zero_or_negative_count",
                "listing.attention_count",
                "accounts.invalid_token_count",
            ],
        )

        answer = ai_agent._deterministic_tool_answer(
            prompt,
            [
                {"tool": "orders.count", "data": {"count": 3}},
                {"tool": "orders.ready_to_ship_count", "data": {"count": 199}},
                {
                    "tool": "orders.fulfillment_risk_count",
                    "data": {"risk_count": 0},
                },
                {
                    "tool": "returns.waiting_action_count",
                    "data": {"count": 7},
                },
                {
                    "tool": "stock.zero_or_negative_count",
                    "data": {"count": 2},
                },
                {
                    "tool": "listing.attention_count",
                    "data": {"count": 14},
                },
                {
                    "tool": "accounts.invalid_token_count",
                    "data": {"count": 1},
                },
            ],
        )
        for expected in (
            "Bugun siparis: 3",
            "Kargoya hazir: 199",
            "Fulfillment riski: 0",
            "WaitingInAction iade: 7",
            "Sifir/eksi stok: 2",
            "Dikkat isteyen ilan: 14",
            "Token sorunu: 1",
            "Oncelik sirasi:",
        ):
            self.assertIn(expected, answer)
        self.assertNotIn("tahmini kar", answer.casefold())
        self.assertNotIn("karli", answer.casefold())
        self.assertNotIn("kar yorumu", answer.casefold())

    def test_operational_closing_check_is_a_cross_domain_priority_report(self) -> None:
        result = choose_action(
            (
                "Bugunku operasyon kapanis kontrolunu kargoya hazir paket, "
                "fulfillment riski, WaitingInAction iade, sifir veya eksi "
                "stok, dikkat isteyen ilan ve gecersiz token sayilariyla ver. "
                "Yalnizca salt okuma yap."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.fulfillment_risk_count",'
                '"arguments":{"period":"today"}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            [call.tool_name for call in getattr(decision, "tool_calls", ())],
            [
                "orders.ready_to_ship_count",
                "orders.fulfillment_risk_count",
                "returns.waiting_action_count",
                "stock.zero_or_negative_count",
                "listing.attention_count",
                "accounts.invalid_token_count",
            ],
        )

    def test_latest_three_orders_outrank_stale_ordinal_selection(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Onceki secimde bir siparis acildi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.lookup",
                    "order_numbers": ["STALE-ORDER-1"],
                    "listed_count": 1,
                    "total_count": 1,
                    "truncated": False,
                },
            }
        ]
        result = choose_action(
            (
                "Tum donemdeki en son 3 siparisi siparis numarasi, durum, "
                "tarih ve tutarla listele."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.lookup",'
                '"arguments":{"order_numbers":["STALE-ORDER-1"],"limit":1}}'
            ),
            history=history,
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "orders.recent")
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"period": "all", "limit": 3},
        )
        answer = ai_agent._deterministic_tool_answer(
            (
                "Tum donemdeki en son 3 siparisi siparis numarasi, durum, "
                "tarih ve tutarla listele."
            ),
            [
                {
                    "tool": "orders.recent",
                    "message": "Son 3 siparis getirildi.",
                    "data": {
                        "orders": [
                            {
                                "order_number": "ORDER-3",
                                "status": "Picking",
                                "order_date": "2026-07-16 14:24",
                                "total_price": 800,
                                "customer": "Gereksiz musteri",
                            },
                            {
                                "order_number": "ORDER-2",
                                "status": "Picking",
                                "order_date": "2026-07-16 14:04",
                                "total_price": 700,
                            },
                            {
                                "order_number": "ORDER-1",
                                "status": "Created",
                                "order_date": "2026-07-16 08:04",
                                "total_price": 600,
                            },
                        ]
                    },
                }
            ],
        )
        self.assertIn("ORDER-3", answer)
        self.assertIn("tarih: 2026-07-16 14:24", answer)
        self.assertIn("tutar: 800 TL", answer)
        self.assertNotIn("Gereksiz musteri", answer)

    def test_listing_counts_exposes_full_status_distribution(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=970,
                    account_id="listing-status-seller",
                    comp_name="Listing Status Seller",
                    platform="trendyol",
                )
            )
            session.add_all(
                [
                    ListingProduct(
                        api_account_id=970,
                        product_id="LISTING-STATUS-1",
                        approved=True,
                        archived=False,
                        on_sale=True,
                        locked=False,
                    ),
                    ListingProduct(
                        api_account_id=970,
                        product_id="LISTING-STATUS-2",
                        approved=True,
                        archived=False,
                        on_sale=False,
                        locked=True,
                    ),
                    ListingProduct(
                        api_account_id=970,
                        product_id="LISTING-STATUS-3",
                        approved=False,
                        archived=False,
                        on_sale=False,
                        locked=False,
                    ),
                    ListingProduct(
                        api_account_id=970,
                        product_id="LISTING-STATUS-4",
                        approved=True,
                        archived=True,
                        on_sale=True,
                        locked=False,
                    ),
                ]
            )
            session.commit()

        result = available_tools()["listing.counts"].handler(
            db_name=self.db_path
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("total"), 4)
        self.assertEqual(data.get("active"), 3)
        self.assertEqual(data.get("on_sale"), 1)
        self.assertEqual(data.get("not_on_sale"), 2)
        self.assertEqual(data.get("locked"), 1)
        self.assertEqual(data.get("archived"), 1)
        self.assertEqual(data.get("approved"), 2)
        self.assertEqual(data.get("unapproved"), 1)
        answer = ai_agent._deterministic_tool_answer(
            "Ilan durum dagilimini ver.",
            [
                {
                    "tool": "listing.counts",
                    "data": dict(data),
                    "message": result.message,
                }
            ],
        )
        self.assertIn("satista 1", answer)
        self.assertIn("satis disi 2", answer)
        self.assertIn("kilitli 1", answer)
        self.assertIn("arsiv 1", answer)

    def test_marketplace_account_platform_distribution_is_single_domain_tool(self) -> None:
        result = choose_action(
            "Kac pazaryeri entegrasyon hesabi var ve platform dagilimi ne?",
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":['
                '{"tool":"orders.status_counts","arguments":{"period":"today"}},'
                '{"tool":"marketplaces.account_count","arguments":{}}'
                "]}"
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "marketplaces.account_count",
        )
        self.assertEqual(getattr(decision, "arguments", {}), {})
        self.assertEqual(
            [call.tool_name for call in getattr(decision, "tool_calls", ())],
            ["marketplaces.account_count"],
        )

        answer = ai_agent._deterministic_tool_answer(
            "Kac pazaryeri entegrasyon hesabi var ve platform dagilimi ne?",
            [
                {
                    "tool": "marketplaces.account_count",
                    "data": {
                        "total": 1,
                        "active": 1,
                        "by_platform": {"TRENDYOL": 1},
                    },
                    "message": "1 aktif pazaryeri hesabi var.",
                }
            ],
        )
        self.assertIn("toplam 1 pazaryeri hesabi", answer)
        self.assertIn("aktif 1", answer)
        self.assertIn("Platform dagilimi: TRENDYOL: 1.", answer)

    def test_logistics_provider_tariff_distribution_uses_profile_not_catalog_search(self) -> None:
        result = choose_action(
            (
                "Lojistik profilini ozetle: kac kargo firmasi ve kac aktif "
                "tarife var, platform dagilimini da ver."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"logistics.provider_catalog",'
                '"arguments":{"query":"lojistik profilini ozetle",'
                '"platform_code":"","limit":20}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "logistics.profile")
        self.assertEqual(getattr(decision, "arguments", {}), {"limit": 8})

        answer = ai_agent._deterministic_tool_answer(
            (
                "Lojistik profilini ozetle: kac kargo firmasi ve kac aktif "
                "tarife var, platform dagilimini da ver."
            ),
            [
                {
                    "tool": "logistics.profile",
                    "message": "11 kargo firmasi ve 4224 aktif tarife var.",
                    "data": {
                        "cargo_providers": 11,
                        "active_tariffs": 4224,
                        "providers_by_platform": {"TRENDYOL": 11},
                        "tariffs_by_platform": {"TRENDYOL": 4224},
                        "cheapest_tariffs": [
                            {
                                "name": "Tarife detayi gosterilmemeli",
                                "provider": "Ornek",
                                "platform": "TRENDYOL",
                                "amount": 1,
                                "currency": "TRY",
                            }
                        ],
                    },
                }
            ],
        )
        self.assertIn("11 kargo firmasi", answer)
        self.assertIn("4224 aktif kargo tarifesi", answer)
        self.assertIn("Firma dagilimi: TRENDYOL: 11.", answer)
        self.assertIn("Tarife dagilimi: TRENDYOL: 4224.", answer)
        self.assertNotIn("En dusuk ucretli", answer)
        self.assertNotIn("Tarife detayi gosterilmemeli", answer)

    def test_cashflow_breakdown_outranks_negative_profit_guard_text(self) -> None:
        prompt = (
            "Bu ayin nakit akis ozetini gelir, gider ve net tutarla ver; "
            "ciroyu kar diye sunma."
        )
        result = choose_action(
            prompt,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"finance.profit_amount",'
                '"arguments":{"period":"this_month"}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "finance.cashflow_summary",
        )
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"period": "this_month"},
        )

        answer = ai_agent._deterministic_tool_answer(
            prompt,
            [
                {
                    "tool": "finance.cashflow_summary",
                    "message": "Bu ay net nakit 70 TRY.",
                    "data": {
                        "period": "this_month",
                        "period_label": "2026-07-01..2026-07-16",
                        "marketplace_credit": 100,
                        "marketplace_debt": 40,
                        "manual_in": 20,
                        "manual_out": 10,
                        "combined_net": 70,
                    },
                }
            ],
        )
        self.assertIn("Gelir/alacak: 120 TRY", answer)
        self.assertIn("Gider/borc: 50 TRY", answer)
        self.assertIn("Net nakit: 70 TRY", answer)
        self.assertIn("ciro veya net kar", answer)

    def test_order_and_return_status_counts_render_visible_distribution(self) -> None:
        order_answer = ai_agent._deterministic_tool_answer(
            "Bugunku siparislerin durum dagilimini adetleriyle ver.",
            [
                {
                    "tool": "orders.status_counts",
                    "message": "Siparis durum dagilimi hazir.",
                    "data": {
                        "period_label": "2026-07-16",
                        "status_counts": {"Picking": 3},
                        "simulated_excluded": 0,
                    },
                }
            ],
        )
        self.assertIn("toplam 3", order_answer)
        self.assertIn("- Picking: 3", order_answer)

        return_answer = ai_agent._deterministic_tool_answer(
            "Bu ayki iadelerin durum dagilimini ver.",
            [
                {
                    "tool": "returns.status_counts",
                    "message": "Iade durum dagilimi hazir.",
                    "data": {
                        "period_label": "2026-07-01..2026-07-16",
                        "status_counts": {
                            "Accepted": 4,
                            "WaitingInAction": 2,
                        },
                    },
                }
            ],
        )
        self.assertIn("toplam 6", return_answer)
        self.assertIn("- Accepted: 4", return_answer)
        self.assertIn("- WaitingInAction: 2", return_answer)

    def test_stock_multi_metric_overview_outranks_zero_only_count(self) -> None:
        prompt = (
            "Stok envanter genel gorunumunu aktif kart sayisi, toplam bakiye "
            "ve sifir veya eksi stok adediyle ozetle."
        )
        result = choose_action(
            prompt,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"stock.zero_or_negative_count",'
                '"arguments":{}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "stock.inventory_overview",
        )
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"limit": 20},
        )

        answer = ai_agent._deterministic_tool_answer(
            prompt,
            [
                {
                    "tool": "stock.inventory_overview",
                    "message": "10 aktif stok karti var.",
                    "data": {
                        "active_items": 10,
                        "total_balance": 42,
                        "zero_or_negative": 2,
                        "top_balances": [
                            {"name": "Gereksiz detay", "balance": 40}
                        ],
                    },
                }
            ],
        )
        self.assertIn("aktif stok karti 10", answer)
        self.assertIn("toplam bakiye 42", answer)
        self.assertIn("sifir/eksi stok karti 2", answer)
        self.assertNotIn("Gereksiz detay", answer)

    def test_agent_answers_today_order_count_via_safe_tool(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        yesterday = today - timedelta(days=1)
        yesterday_start = int(datetime.combine(yesterday, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)

        self._insert_order_snapshot("ORD-TODAY-1", today_start + 1_000, package_id=101)
        self._insert_order_snapshot("ORD-TODAY-1", today_start + 2_000, package_id=102)
        self._insert_order_snapshot("ORD-TODAY-2", today_start + 3_000, package_id=103)
        self._insert_order_snapshot("ORD-YESTERDAY", yesterday_start + 1_000, package_id=201)

        result = run_agent_turn(
            "Bugün kaç tane siparişim var?",
            model_record={"repo_id": "mradermacher/gemma-3n-E4B-it-GGUF"},
            planner_client=lambda prompt: (
                '{"mode": "tool", "tool": "orders.summary", "arguments": {"period": "today"}}'
                if "Cikti yalnizca JSON olsun" in prompt
                else "Bugün lokal kayda göre 2 sipariş görünüyor."
            ),
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("answer"), "Bugün lokal kayda göre 2 sipariş görünüyor.")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "orders.summary")
        self.assertTrue((result.data or {}).get("trace"))

    def test_agent_handles_consecutive_chat_then_tool_turns(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-THREAD-1", today_start + 1_000, package_id=901)
        self._insert_order_snapshot("ORD-THREAD-2", today_start + 2_000, package_id=902)

        def fake_planner(prompt: str) -> str:
            if "Cikti yalnizca JSON olsun" in prompt:
                current = prompt.rsplit("Kullanici mesaji:", 1)[-1].strip()
                if "Bugun kac siparisim var" in current:
                    return '{"mode": "tool", "tool": "orders.count", "arguments": {"period": "today"}}'
                if "sagol" in current.casefold() or "sa\u011fol" in current.casefold():
                    return '{"mode": "answer", "response": "Rica ederim."}'
                return '{"mode": "answer", "response": "Buradayim."}'
            return "Bugun lokal kayda gore 2 siparis var."

        history: list[dict[str, str]] = []
        first = run_agent_turn("Ne yapiyorsun?", planner_client=fake_planner, chat_client=fake_planner, db_name=self.db_path, history=history)
        self.assertTrue(first.success, first.message)
        self.assertEqual((first.data or {}).get("mode"), "answer")
        history.extend([
            {"role": "user", "content": "Ne yapiyorsun?"},
            {"role": "assistant", "content": str((first.data or {}).get("answer") or "")},
        ])

        second = run_agent_turn("sagol", planner_client=fake_planner, chat_client=fake_planner, db_name=self.db_path, history=history)
        self.assertTrue(second.success, second.message)
        self.assertEqual((second.data or {}).get("mode"), "answer")
        history.extend([
            {"role": "user", "content": "sagol"},
            {"role": "assistant", "content": str((second.data or {}).get("answer") or "")},
        ])

        third = run_agent_turn(
            "Bugun kac siparisim var?",
            planner_client=fake_planner,
            chat_client=fake_planner,
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(third.success, third.message)
        self.assertEqual((third.data or {}).get("mode"), "tool")
        self.assertEqual(((third.data or {}).get("tool_call") or {}).get("tool"), "orders.count")
        self.assertEqual(((third.data or {}).get("tool_result") or {}).get("count"), 2)
        self.assertEqual((third.data or {}).get("answer"), "Bugun lokal kayda gore 2 siparis var.")

    def test_tight_local_context_bypasses_llm_planning_and_survives_http_failure(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-TIGHT-1", today_start + 1_000, package_id=1001)

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        result = run_agent_turn(
            "Bugun kac siparisim var?",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "tool")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "orders.count")
        self.assertEqual(((result.data or {}).get("tool_result") or {}).get("count"), 1)
        self.assertIn("1 siparis", str((result.data or {}).get("answer") or ""))

    def test_ready_to_ship_without_date_uses_current_queue_not_today_only(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        yesterday = today - timedelta(days=1)
        yesterday_start = int(datetime.combine(yesterday, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-QUEUE-TODAY", today_start + 1_000, package_id=1101, status="ReadyToShip")
        self._insert_order_snapshot("ORD-QUEUE-OLD", yesterday_start + 1_000, package_id=1102, status="ReadyToShip")

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        queue_res = run_agent_turn(
            "Kargolamam gereken kac siparis var?",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
        )
        today_res = run_agent_turn(
            "Bugun kargolamam gereken kac siparis var?",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
        )

        self.assertTrue(queue_res.success, queue_res.message)
        self.assertEqual(((queue_res.data or {}).get("tool_call") or {}).get("tool"), "orders.ready_to_ship_count")
        self.assertEqual(((queue_res.data or {}).get("tool_call") or {}).get("arguments"), {"period": "all"})
        self.assertEqual(((queue_res.data or {}).get("tool_result") or {}).get("count"), 2)
        self.assertTrue(today_res.success, today_res.message)
        self.assertEqual(((today_res.data or {}).get("tool_call") or {}).get("arguments"), {"period": "today"})
        self.assertEqual(((today_res.data or {}).get("tool_result") or {}).get("count"), 1)

    def test_latest_five_orders_is_not_reinterpreted_from_capability_ready_text(self) -> None:
        message = "tamam o zaman son gelen 5 siparisi getir"
        decision = ai_agent._intent_override_decision(
            message,
            history=[
                {
                    "role": "assistant",
                    "content": (
                        "Siparisleri listelemek ve kargoya hazir paketleri okumak "
                        "salt okuma yeteneklerim arasinda."
                    ),
                },
                {"role": "user", "content": message},
            ],
        )

        self.assertEqual(decision.tool_name, "orders.recent")
        self.assertEqual(decision.arguments, {"period": "all", "limit": 5})

    def test_latest_orders_accepts_stage_qualifier_before_order_noun(self) -> None:
        message = (
            "Bugunku son 3 Stage siparisini yalniz sira, siparis numarasi "
            "ve kargo firmasiyla listele."
        )
        result = choose_action(
            message,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.ready_to_ship",'
                '"arguments":{"period":"today","limit":199}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(decision.tool_name, "orders.recent")
        self.assertEqual(decision.arguments, {"period": "today", "limit": 3})

    def test_latest_orders_explicit_cargo_field_uses_shared_order_read_row(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=2,
                    account_id="fixture-stage",
                    comp_name="Fixture Stage",
                    platform="TRENDYOL",
                    extra_config={"environment": "stage"},
                )
            )
            session.commit()
        today = datetime.now(TZ_GMT3).date()
        today_start = int(
            datetime.combine(
                today,
                datetime.min.time(),
                tzinfo=TZ_GMT3,
            ).timestamp()
            * 1000
        )
        self._insert_order_snapshot(
            "ORD-RECENT-CARGO-1",
            today_start + 1_000,
            package_id=1191,
            cargo_provider_name="Provider One",
            api_account_id=2,
        )
        self._insert_order_snapshot(
            "ORD-RECENT-CARGO-2",
            today_start + 2_000,
            package_id=1192,
            cargo_provider_name="Provider Two",
            api_account_id=2,
        )
        message = (
            "Bugunku son 2 Stage siparisini yalniz sira, siparis numarasi "
            "ve kargo firmasiyla listele."
        )

        result = run_agent_turn(
            message,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.ready_to_ship",'
                '"arguments":{"period":"today","limit":199}}'
            ),
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(
            ((result.data or {}).get("tool_call") or {}).get("tool"),
            "orders.recent",
        )
        self.assertEqual(
            (result.data or {}).get("answer"),
            (
                "1. ORD-RECENT-CARGO-2 | kargo: Provider Two\n"
                "2. ORD-RECENT-CARGO-1 | kargo: Provider One"
            ),
        )

    def test_short_waiting_orders_count_is_deterministically_ready_queue(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(
            datetime.combine(
                today,
                datetime.min.time(),
                tzinfo=TZ_GMT3,
            ).timestamp()
            * 1000
        )
        self._insert_order_snapshot(
            "ORD-WAITING-READY",
            today_start,
            package_id=1181,
            status="ReadyToShip",
        )
        self._insert_order_snapshot(
            "ORD-WAITING-DELIVERED",
            today_start + 1,
            package_id=1182,
            status="Delivered",
        )

        result = run_agent_turn(
            "iyidir kaç bekleyen sipariş var toplamda",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count",'
                '"arguments":{"period":"all"}}'
            ),
            chat_client=lambda _prompt: "Toplam iki siparis var.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(
            ((result.data or {}).get("tool_call") or {}).get("tool"),
            "orders.ready_to_ship_count",
        )
        self.assertEqual(
            ((result.data or {}).get("tool_call") or {}).get("arguments"),
            {"period": "all"},
        )
        self.assertEqual(
            ((result.data or {}).get("tool_result") or {}).get("count"),
            1,
        )

    def test_ready_selection_survives_ordinal_and_conversational_interludes(self) -> None:
        order_numbers = [str(11300000000 + index) for index in range(1, 22)]
        complete_context = {
            "kind": "order_selection",
            "source_tool": "orders.ready_to_ship",
            "order_numbers": order_numbers,
            "listed_count": 21,
            "total_count": 21,
            "truncated": False,
            "period": "all",
        }
        single_context = {
            "kind": "order_selection",
            "source_tool": "orders.lookup",
            "order_numbers": [order_numbers[-1]],
            "listed_count": 1,
            "total_count": 1,
            "truncated": False,
            "period": "all",
        }
        history = [
            {"role": "assistant", "content": "21 siparis", "context": complete_context},
            {"role": "assistant", "content": "son siparis", "context": single_context},
        ]

        first_message = "bu 21 siparisin listedeki ilki hangisiydi?"
        first = ai_agent._intent_override_decision(
            first_message,
            history=[*history, {"role": "user", "content": first_message}],
        )
        last_message = "peki sonuncusu hangisiydi?"
        last = ai_agent._intent_override_decision(
            last_message,
            history=[*history, {"role": "user", "content": last_message}],
        )
        self.assertEqual(first.tool_name, "orders.lookup")
        self.assertEqual(first.arguments.get("order_numbers"), [order_numbers[0]])
        self.assertEqual(last.tool_name, "orders.lookup")
        self.assertEqual(last.arguments.get("order_numbers"), [order_numbers[-1]])
        first_amount_message = "ana listedeki ilk siparisin tutari neydi?"
        first_amount = ai_agent._intent_override_decision(
            first_amount_message,
            history=[
                *history,
                {"role": "user", "content": first_amount_message},
            ],
        )
        self.assertEqual(first_amount.tool_name, "orders.lookup")
        self.assertEqual(
            first_amount.arguments.get("order_numbers"),
            [order_numbers[0]],
        )
        last_carrier_message = (
            "ana listedeki son siparisin kargo firmasi neydi?"
        )
        last_carrier = ai_agent._intent_override_decision(
            last_carrier_message,
            history=[
                *history,
                {"role": "user", "content": last_carrier_message},
            ],
        )
        self.assertEqual(last_carrier.tool_name, "orders.lookup")
        self.assertEqual(
            last_carrier.arguments.get("order_numbers"),
            [order_numbers[-1]],
        )

        label_message = (
            "az onceki 21 hazir siparisin etiketlerini hazirla "
            "ama onay vermeden calistirma"
        )
        label = ai_agent._label_create_decision(
            label_message,
            ai_agent._normalized_match_text(label_message),
            [*history, {"role": "user", "content": label_message}],
            source="test",
        )
        self.assertEqual(label.tool_name, "labels.create_from_orders.prepare")
        self.assertEqual(label.arguments.get("order_numbers"), order_numbers)
        self.assertEqual(label.arguments.get("limit"), 21)

        first_four_message = "Bu listedeki ilk 4 siparis icin kargo etiketlerini DOCX olarak hazirla."
        first_four = ai_agent._label_create_decision(
            first_four_message,
            ai_agent._normalized_match_text(first_four_message),
            [*history, {"role": "user", "content": first_four_message}],
            source="test",
        )
        self.assertEqual(first_four.tool_name, "labels.create_from_orders.prepare")
        self.assertEqual(first_four.arguments.get("order_numbers"), order_numbers[:4])
        self.assertEqual(first_four.arguments.get("limit"), 20)

        tanex_2610_message = (
            "Bu yeni listenin ikinci siparisi icin TANEX 2610 etiketini "
            "olusturmayi onaya hazirla; execute etme ve dosya uretme."
        )
        tanex_2610 = ai_agent._label_create_decision(
            tanex_2610_message,
            ai_agent._normalized_match_text(tanex_2610_message),
            [*history, {"role": "user", "content": tanex_2610_message}],
            source="test",
        )
        self.assertEqual(
            tanex_2610.arguments.get("order_numbers"),
            [order_numbers[1]],
        )
        self.assertEqual(tanex_2610.arguments.get("brand_code"), "TANEX")
        self.assertEqual(tanex_2610.arguments.get("model_code"), "TANEX_2610")

        unknown_model_message = (
            "Bu listenin ilk siparisi icin TANEX 9999 etiketini onaya hazirla."
        )
        unknown_model = ai_agent._label_create_decision(
            unknown_model_message,
            ai_agent._normalized_match_text(unknown_model_message),
            [*history, {"role": "user", "content": unknown_model_message}],
            source="test",
        )
        self.assertEqual(unknown_model.mode, "answer")
        self.assertFalse(unknown_model.tool_name)
        self.assertIn(
            "varsayilan sablona dusmuyorum",
            ai_agent._normalized_match_text(unknown_model.response),
        )

        implicit_label_message = "peki etiket yazdirabilir misin"
        implicit_label_history = [
            *history,
            {
                "role": "user",
                "content": "yani ana listemizin kapsami kac siparisti?",
            },
            {
                "role": "assistant",
                "content": "Ana dogrulanmis listemizin kapsami 21 siparisti.",
            },
            {"role": "user", "content": implicit_label_message},
        ]
        implicit_label = ai_agent._label_create_decision(
            implicit_label_message,
            ai_agent._normalized_match_text(implicit_label_message),
            implicit_label_history,
            source="test",
        )
        self.assertEqual(
            implicit_label.arguments.get("order_numbers"),
            order_numbers,
        )

        plural_label_message = (
            "az oncekilerin etiketini hazirla ama calistirma"
        )
        plural_label_history = [
            *history,
            *[
                {"role": "user", "content": f"ara mesaj {index}"}
                for index in range(1, 10)
            ],
            {"role": "user", "content": plural_label_message},
        ]
        plural_label = ai_agent._label_create_decision(
            plural_label_message,
            ai_agent._normalized_match_text(plural_label_message),
            plural_label_history,
            source="test",
        )
        self.assertEqual(
            plural_label.arguments.get("order_numbers"),
            order_numbers,
        )
        self.assertFalse(
            ai_agent._pending_action_cancel_requested(
                ai_agent._normalized_match_text(plural_label_message)
            )
        )
        historical_cancel_summary = (
            "Az once iptal ettigimiz etiket hazirliginin siparis numarasini "
            "ve etiket modelini yeni arac cagirmadan ozetle."
        )
        self.assertFalse(
            ai_agent._pending_action_cancel_requested(
                ai_agent._normalized_match_text(historical_cancel_summary)
            )
        )
        self.assertTrue(
            ai_agent._pending_action_cancel_requested(
                ai_agent._normalized_match_text(
                    "Az once iptal ettigimiz etiket hazirligini tekrar iptal et."
                )
            )
        )
        orphan_approval = ai_agent._intent_override_decision(
            "onayla",
            history=[
                {
                    "role": "assistant",
                    "content": "Riskli islem iptal edildi.",
                },
                {"role": "user", "content": "onayla"},
            ],
        )
        self.assertEqual(orphan_approval.mode, "answer")
        self.assertFalse(orphan_approval.tool_name)
        self.assertIn(
            "onay bekleyen guncel bir islem yok",
            ai_agent._normalized_match_text(orphan_approval.response),
        )

        scope_message = "ana listemizin kapsami kac siparisti?"
        scope = ai_agent._intent_override_decision(
            scope_message,
            history=[*history, {"role": "user", "content": scope_message}],
        )
        self.assertEqual(scope.mode, "answer")
        self.assertIn("21 siparisti", ai_agent._normalized_match_text(scope.response))

        exclusion_instruction_message = (
            "production veride kargoya hazir kac siparis var; "
            "simulasyonlari dahil etme"
        )
        exclusion_instruction = ai_agent._intent_override_decision(
            exclusion_instruction_message,
            history=[
                *history,
                {"role": "user", "content": exclusion_instruction_message},
            ],
        )
        self.assertEqual(
            exclusion_instruction.tool_name,
            "orders.ready_to_ship_count",
        )
        self.assertEqual(exclusion_instruction.arguments, {"period": "all"})
        exclusion_scope_message = (
            "production veride simulasyonlar haric gercek kargoya hazir "
            "siparis sayisini ver"
        )
        exclusion_scope = ai_agent._intent_override_decision(
            exclusion_scope_message,
            history=[
                *history,
                {"role": "user", "content": exclusion_scope_message},
            ],
        )
        self.assertEqual(
            exclusion_scope.tool_name,
            "orders.ready_to_ship_count",
        )
        self.assertEqual(exclusion_scope.arguments, {"period": "all"})

        prepare_without_execute_message = (
            "bu dogrulanmis 21'li listenin ilk uc siparisi icin kargo "
            "etiketini yalniz onaya hazirla; execute etme, dosya uretme"
        )
        prepare_without_execute = ai_agent._intent_override_decision(
            prepare_without_execute_message,
            history=[
                *history,
                {"role": "user", "content": prepare_without_execute_message},
            ],
        )
        self.assertEqual(
            prepare_without_execute.tool_name,
            "labels.create_from_orders.prepare",
        )
        self.assertEqual(
            len(prepare_without_execute.arguments.get("order_numbers") or []),
            3,
        )

        no_write_message = "simdilik yeni bir dosya uretme, sadece konusuyoruz"
        no_write = ai_agent._intent_override_decision(
            no_write_message,
            history=[*history, {"role": "user", "content": no_write_message}],
        )
        self.assertEqual(no_write.mode, "answer")
        self.assertFalse(no_write.tool_name)

        distribution_message = "bu 21 hazir siparis hangi kargo firmalarina dagiliyor?"
        distribution = ai_agent._intent_override_decision(
            distribution_message,
            history=[*history, {"role": "user", "content": distribution_message}],
        )
        self.assertEqual(distribution.tool_name, "orders.ready_to_ship")
        self.assertEqual(distribution.arguments, {"period": "all", "limit": 21})
        contextual_distribution_message = (
            "bu ana listede kac farkli kargo firmasi var?"
        )
        contextual_distribution = ai_agent._intent_override_decision(
            contextual_distribution_message,
            history=[
                *history,
                {"role": "user", "content": contextual_distribution_message},
            ],
        )
        self.assertEqual(
            contextual_distribution.tool_name,
            "orders.ready_to_ship",
        )
        self.assertEqual(
            contextual_distribution.arguments,
            {"period": "all", "limit": 21},
        )

        count_scope_distribution_message = (
            "Bu 3 siparis hangi kargo firmalarina dagiliyor? "
            "Yalniz firma ve adet olarak ver."
        )
        count_scope_distribution = ai_agent._intent_override_decision(
            count_scope_distribution_message,
            history=[
                {
                    "role": "assistant",
                    "content": "Eski tekil siparis.",
                    "context": {
                        "kind": "order_selection",
                        "source_tool": "orders.lookup",
                        "order_numbers": [order_numbers[0]],
                        "listed_count": 1,
                        "total_count": 1,
                        "truncated": False,
                    },
                },
                {
                    "role": "assistant",
                    "content": "Bugun kargoya hazir 3 siparis var.",
                    "context": {
                        "kind": "orders_ready_to_ship_scope",
                        "source_tool": "orders.ready_to_ship_count",
                        "period": "today",
                        "total_count": 3,
                    },
                },
                {
                    "role": "user",
                    "content": count_scope_distribution_message,
                },
            ],
        )
        self.assertEqual(
            count_scope_distribution.tool_name,
            "orders.ready_to_ship",
        )
        self.assertEqual(
            count_scope_distribution.arguments,
            {"period": "today", "limit": 3},
        )
        self.assertEqual(
            ai_agent._format_ready_cargo_distribution(
                [
                    {
                        "order_number": "ORD-1",
                        "cargo_provider": "Aras",
                    },
                    {
                        "order_number": "ORD-2",
                        "cargo_provider": "Aras",
                    },
                    {
                        "order_number": "ORD-3",
                        "cargo_provider": "Trendyol Express",
                    },
                ],
                user_message=count_scope_distribution_message,
            ),
            "Aras: 2\nTrendyol Express: 1",
        )

        stale_return_history = [
            *history,
            {
                "role": "assistant",
                "content": "177 claim neden dagilimi.",
                "context": {
                    "kind": "return_analysis",
                    "source_tool": "returns.reason_summary",
                    "period": "all",
                    "total_claims": 177,
                    "top_reasons": [{"reason": "Begenmedim", "claim_count": 39}],
                },
            },
        ]
        stale_context_distribution_message = (
            "Az onceki 21 hazir siparisin kargo firmalarina gore dagilimi ne?"
        )
        stale_context_distribution = ai_agent._intent_override_decision(
            stale_context_distribution_message,
            history=[
                *stale_return_history,
                {"role": "user", "content": stale_context_distribution_message},
            ],
        )
        self.assertEqual(
            stale_context_distribution.tool_name,
            "orders.ready_to_ship",
        )
        self.assertEqual(
            stale_context_distribution.arguments,
            {"period": "all", "limit": 21},
        )

        total_correction = ai_agent._ready_scope_recovery_prefix(
            ai_agent._normalized_match_text(
                "hic mi bekleyen yok, toplamda bekleyen bir seyler var"
            ),
            history=[{"role": "assistant", "content": "21 siparis", "context": complete_context}],
        )
        self.assertIn(
            "onceki cevap zaten",
            ai_agent._normalized_match_text(total_correction),
        )
        narrowed_context = {
            **complete_context,
            "source_tool": "orders.ready_to_ship_count",
            "period": "today",
        }
        narrowed_correction = ai_agent._ready_scope_recovery_prefix(
            ai_agent._normalized_match_text(
                "hic mi bekleyen yok, toplamda bekleyen bir seyler var"
            ),
            history=[{"role": "assistant", "content": "0 siparis", "context": narrowed_context}],
        )
        self.assertIn(
            "bugun",
            ai_agent._normalized_match_text(narrowed_correction),
        )
        grounded_identity = ai_agent._ready_scope_recovery_prefix(
            ai_agent._normalized_match_text(
                "bunlar nasil siparis numarasi, boyle siparis no mu olur"
            ),
            history=[{"role": "assistant", "content": "21 siparis", "context": complete_context}],
        )
        grounded_identity_normalized = ai_agent._normalized_match_text(
            grounded_identity
        )
        self.assertIn("order number", grounded_identity_normalized.replace("_", " "))
        self.assertNotIn("geri al", grounded_identity_normalized)
        unsupported_identity = ai_agent._ready_scope_recovery_prefix(
            ai_agent._normalized_match_text(
                "bunlar nasil siparis numarasi, boyle siparis no mu olur"
            ),
            history=[],
        )
        self.assertIn(
            "geri al",
            ai_agent._normalized_match_text(unsupported_identity),
        )
        self.assertTrue(
            ai_agent._should_use_deterministic_answer(
                (
                    "Evet, kargoya hazir 21 siparis var. "
                    "Not: 5 simulasyon siparisi kapsam disinda. "
                    "Kayitli herhangi bir risk bulunmamaktadir."
                ),
                [
                    {
                        "tool": "orders.ready_to_ship_count",
                        "data": {
                            "count": 21,
                            "simulated_excluded": 5,
                        },
                    }
                ],
            )
        )
        self.assertTrue(
            ai_agent._should_use_deterministic_answer(
                (
                    "Production ortaminda kargoya hazir 2 siparis var: "
                    "ORD-COUNT-LEAK-1, ORD-COUNT-LEAK-2"
                ),
                [
                    {
                        "tool": "orders.ready_to_ship_count",
                        "data": {
                            "count": 2,
                            "account_by_order": {
                                "ORD-COUNT-LEAK-1": "1",
                                "ORD-COUNT-LEAK-2": "1",
                            },
                        },
                    }
                ],
            )
        )

    def test_historical_ordinal_order_read_obeys_explicit_field_scope(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        order_numbers = [f"ORD-HISTORY-{index}" for index in range(1, 6)]
        for index, order_number in enumerate(order_numbers):
            self._insert_order_snapshot(
                order_number,
                now_ms + index,
                package_id=1700 + index,
                status="Picking",
            )
        history = [
            {
                "role": "assistant",
                "content": "Bes siparislik tarihsel liste.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.recent",
                    "order_numbers": order_numbers,
                    "listed_count": 5,
                    "total_count": 5,
                    "truncated": False,
                    "period": "all",
                },
            },
            {
                "role": "assistant",
                "content": "Daha yeni baska bir siparis secimi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.lookup",
                    "order_numbers": ["ORD-NEWER-ONLY"],
                    "listed_count": 1,
                    "total_count": 1,
                    "truncated": False,
                },
            },
        ]
        result = run_agent_turn(
            (
                "Konusmanin basinda getirdigin 5 siparislik tarihsel listedeki "
                "ucuncu siparis hangisiydi? Yalniz numara ve durumunu soyle."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.lookup",'
                '"arguments":{"query":"ORD-NEWER-ONLY","limit":1}}'
            ),
            chat_client=lambda _prompt: (
                "Musteri, kargo, takip ve tutar dahil tum ayrintilar."
            ),
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        call = (result.data or {}).get("tool_call") or {}
        self.assertEqual(call.get("tool"), "orders.lookup")
        self.assertEqual(
            (call.get("arguments") or {}).get("order_numbers"),
            [order_numbers[2]],
        )
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn(order_numbers[2], answer)
        self.assertIn("durum: Picking", answer)
        self.assertNotIn("musteri:", answer.casefold())
        self.assertNotIn("kargo:", answer.casefold())
        self.assertNotIn("takip:", answer.casefold())
        self.assertNotIn("tutar:", answer.casefold())

        amount_followup = run_agent_turn(
            "Bu tarihsel siparisin toplam tutari neydi?",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.query",'
                '"arguments":{"period":"all","sort":"total_price_desc",'
                '"limit":1,"mode":"top"}}'
            ),
            chat_client=lambda _prompt: "En pahali siparis budur.",
            db_name=self.db_path,
            history=[
                *history,
                {
                    "role": "assistant",
                    "content": f"1. {order_numbers[2]} | durum: Picking",
                    "context": {
                        "kind": "order_selection",
                        "source_tool": "orders.lookup",
                        "order_numbers": [order_numbers[2]],
                        "listed_count": 1,
                        "total_count": 1,
                        "truncated": False,
                    },
                },
            ],
        )
        self.assertTrue(amount_followup.success, amount_followup.message)
        amount_call = (amount_followup.data or {}).get("tool_call") or {}
        self.assertEqual(amount_call.get("tool"), "orders.lookup")
        self.assertEqual(
            (amount_call.get("arguments") or {}).get("order_numbers"),
            [order_numbers[2]],
        )
        self.assertIn(
            order_numbers[2],
            str((amount_followup.data or {}).get("answer") or ""),
        )
        cargo_only = ai_agent._format_order_rows(
            [
                {
                    "order_number": order_numbers[2],
                    "status": "Picking",
                    "customer": "Private Customer",
                    "cargo_provider": "Trendyol Express Marketplace",
                    "cargo_tracking_number": "TRACK-3",
                    "total_price": 800.0,
                }
            ],
            user_message=(
                "Ayni siparisin kargo bilgisini yalniz firma ve takip "
                "numarasi olarak ver."
            ),
        )
        self.assertEqual(
            cargo_only,
            "kargo: Trendyol Express Marketplace | takip: TRACK-3",
        )

    def test_ready_count_followup_and_label_prepare_keep_all_199_orders(self) -> None:
        order_numbers = [f"STAGE-READY-{index:03d}" for index in range(1, 200)]
        count_context = {
            "kind": "orders_ready_to_ship_scope",
            "source_tool": "orders.ready_to_ship_count",
            "period": "all",
            "total_count": len(order_numbers),
        }
        count_history = [
            {
                "role": "assistant",
                "content": "Kargoya hazir 199 siparis var.",
                "context": count_context,
            }
        ]
        list_message = "peki hepsini listele"
        list_decision = ai_agent._intent_override_decision(
            list_message,
            history=[*count_history, {"role": "user", "content": list_message}],
        )

        self.assertEqual(list_decision.tool_name, "orders.ready_to_ship")
        self.assertEqual(
            list_decision.arguments,
            {"period": "all", "limit": 199},
        )

        selection_context = {
            "kind": "order_selection",
            "source_tool": "orders.ready_to_ship",
            "period": "all",
            "order_numbers": order_numbers,
            "listed_count": 199,
            "total_count": 199,
            "truncated": False,
        }
        label_message = "bu listenin tum siparisleri icin etiketleri onaya hazirla"
        label_decision = ai_agent._label_create_decision(
            label_message,
            ai_agent._normalized_match_text(label_message),
            [
                *count_history,
                {
                    "role": "assistant",
                    "content": "199 siparis listelendi.",
                    "context": selection_context,
                },
                {"role": "user", "content": label_message},
            ],
            source="test",
        )

        self.assertEqual(
            label_decision.tool_name,
            "labels.create_from_orders.prepare",
        )
        self.assertEqual(label_decision.arguments.get("order_numbers"), order_numbers)
        self.assertEqual(label_decision.arguments.get("limit"), 199)

        priority_message = "tamam sorun degil, sence bugun neye oncelik vermeliyim"
        priority_decision = ai_agent._intent_override_decision(
            priority_message,
            history=[
                *count_history,
                {
                    "role": "assistant",
                    "content": "199 siparis listelendi.",
                    "context": selection_context,
                },
                {
                    "role": "assistant",
                    "content": "Etiket hazirligi iptal edildi; hicbir islem yapilmadi.",
                },
                {"role": "user", "content": priority_message},
            ],
        )

        self.assertEqual(priority_decision.mode, "answer")
        self.assertFalse(priority_decision.tool_name)
        priority_answer = ai_agent._normalized_match_text(priority_decision.response)
        self.assertIn("199 kargoya hazir siparis", priority_answer)
        self.assertIn("etiket", priority_answer)
        self.assertIn("iade", priority_answer)

    def test_complete_ready_list_can_render_all_199_rows(self) -> None:
        self.assertEqual(
            ai_agent._visible_row_limit(
                "o 199 siparisin hepsini listele",
                row_count=199,
            ),
            199,
        )
        rows = [
            {
                "order_number": str(900000000 + index),
                "status": "Picking",
                "cargo_provider_name": "Stage Cargo",
            }
            for index in range(1, 200)
        ]
        answer = ai_agent._deterministic_tool_answer(
            "o 199 siparisin hepsini listele",
            [
                {
                    "tool": "orders.ready_to_ship",
                    "data": {"orders": rows, "total_count": 199},
                    "message": "199 siparis bulundu.",
                }
            ],
        )

        self.assertIn(rows[-1]["order_number"], answer)
        self.assertNotIn("kayit daha var", answer)

    def test_exact_stage_order_detail_wins_over_old_ready_queue_scope(self) -> None:
        order_numbers = [str(900000000 + index) for index in range(1, 200)]
        target = order_numbers[0]
        message = (
            f"sekiz mesaj once siparis numarasi {target} olan kaydi ayirmistik ya, "
            "onun kalemlerini tekrar goster"
        )
        decision = ai_agent._intent_override_decision(
            message,
            history=[
                {
                    "role": "assistant",
                    "content": "199 siparis listelendi.",
                    "context": {
                        "kind": "order_selection",
                        "source_tool": "orders.ready_to_ship",
                        "period": "all",
                        "order_numbers": order_numbers,
                        "listed_count": 199,
                        "total_count": 199,
                        "truncated": False,
                    },
                },
                {"role": "user", "content": message},
            ],
        )

        self.assertEqual(decision.tool_name, "orders.full_context")
        self.assertEqual(decision.arguments, {"query": target, "limit": 1})

    def test_negative_finance_field_exclusion_does_not_become_write_intent(self) -> None:
        message = (
            "Bu taze uclunun ikinci siparisinin kalemlerini, kargo firmasini, "
            "takip numarasini ve iade durumunu getir; musteri ve finans bilgisi ekleme."
        )
        decision = ai_agent._intent_override_decision(
            message,
            history=[
                {
                    "role": "assistant",
                    "content": "Uc siparis listelendi.",
                    "context": {
                        "kind": "order_selection",
                        "source_tool": "orders.recent",
                        "period": "today",
                        "order_numbers": ["111", "222", "333"],
                        "listed_count": 3,
                        "total_count": 3,
                        "truncated": False,
                    },
                },
                {"role": "user", "content": message},
            ],
        )

        self.assertFalse(
            ai_agent._write_intent_requested(
                ai_agent._normalized_match_text(message)
            )
        )
        self.assertEqual(decision.tool_name, "orders.full_context")
        self.assertEqual(decision.arguments, {"query": "222", "limit": 1})

    def test_selected_single_order_label_prepare_keeps_exact_selection(self) -> None:
        message = (
            "Bu secili siparis icin TANEX 2610 etiketini onaya hazirla; "
            "execute etme, dosya uretme ve DB yazimi yapma."
        )
        decision = ai_agent._intent_override_decision(
            message,
            history=[
                {
                    "role": "assistant",
                    "content": "222 numarali siparisin tam baglami.",
                    "context": {
                        "kind": "order_selection",
                        "source_tool": "orders.full_context",
                        "period": "all",
                        "order_numbers": ["222"],
                        "listed_count": 1,
                        "total_count": 1,
                        "truncated": False,
                    },
                },
                {"role": "user", "content": message},
            ],
        )

        self.assertEqual(
            decision.tool_name,
            "labels.create_from_orders.prepare",
        )
        self.assertEqual(decision.arguments.get("order_numbers"), ["222"])
        self.assertEqual(decision.arguments.get("query"), "")
        self.assertEqual(decision.arguments.get("brand_code"), "TANEX")
        self.assertEqual(decision.arguments.get("model_code"), "TANEX_2610")

    def test_label_prepare_visible_answer_can_show_all_199_approval_rows(self) -> None:
        order_numbers = [str(900000000 + index) for index in range(1, 200)]
        action = {
            "approval_required": True,
            "execute_enabled": True,
            "action_type": "labels.action_create_labels_from_selected_orders",
            "summary": "199 siparis icin etiket olusturma hazirlaniyor.",
            "title": "Siparis etiketi olusturma onayi",
            "arguments": {
                "payload": {
                    "order_numbers": order_numbers,
                    "brand_code": "TANEX",
                    "model_code": "TANEX_2610",
                }
            },
            "rows": [
                {
                    "title": "Siparis etiketi olusturma onayi",
                    "order_number": order_number,
                }
                for order_number in order_numbers
            ],
        }
        answer = ai_agent._deterministic_tool_answer(
            "bu 199 siparisin tamamini etikete yazdirmaya hazirla",
            [{"tool": "labels.create_from_orders.prepare", "data": {"action": action}}],
        )

        self.assertIn(order_numbers[-1], answer)
        self.assertNotIn("kayit daha onay kapsaminda", answer)
        self.assertIn("Sablon: TANEX 2610.", answer)
        self.assertIn("dosya veya yazici ciktisi olusturulmadi", answer)
        context = ai_agent._conversation_context_from_tool_results(
            [
                {
                    "tool": "labels.create_from_orders.prepare",
                    "data": {"action": action},
                }
            ]
        )
        self.assertEqual(context.get("brand_code"), "TANEX")
        self.assertEqual(context.get("model_code"), "TANEX_2610")

    def test_label_execution_followups_do_not_route_to_unrelated_order_tools(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Onay gerekiyor: 21 siparis icin etiket olusturma hazirlaniyor.",
            },
            {
                "role": "assistant",
                "content": (
                    "Onayli aksiyon calistirildi. verify: dogrulandi. "
                    "kanit: payload_and_docx_content. cikti: C:/tmp/labels.docx"
                ),
            },
        ]
        result_message = (
            "dosya gercekten olustu mu, icinde kac siparis etiketi var "
            "ve bunu nasil dogruladin?"
        )
        result = ai_agent._intent_override_decision(
            result_message,
            history=[*history, {"role": "user", "content": result_message}],
        )
        external_message = "bu islem Trendyol'a herhangi bir istek gonderdi mi?"
        external = ai_agent._intent_override_decision(
            external_message,
            history=[*history, {"role": "user", "content": external_message}],
        )
        self.assertEqual(result.mode, "answer")
        self.assertFalse(result.tool_name)
        self.assertIn("21 siparis etiketi", ai_agent._normalized_match_text(result.response))
        self.assertEqual(external.mode, "answer")
        self.assertFalse(external.tool_name)
        self.assertIn("dis api", ai_agent._normalized_match_text(external.response))

    def test_listing_price_question_uses_price_lookup_tool(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-PRICE-1",
                    title="Test Silikon Firca",
                    barcode="BAR-PRICE-1",
                    stock_code="STK-PRICE-1",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=4,
                    list_price=129.99,
                    sale_price=119.99,
                )
            )
            session.commit()

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        result = run_agent_turn(
            "BAR-PRICE-1 barkodlu ilanin fiyati kac?",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.price_lookup")
        prices = ((result.data or {}).get("tool_result") or {}).get("prices") or []
        self.assertEqual(prices[0].get("sale_price"), 119.99)

    def test_listing_content_quality_and_seo_intents_do_not_degrade_to_search(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-SEO-1",
                    title="Kisa Baslik",
                    barcode="BAR-SEO-1",
                    stock_code="STK-SEO-1",
                    brand="DemoBrand",
                    category_name="Ev Gerecleri",
                    description="Kisa.",
                    images=[],
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=4,
                    list_price=129.99,
                    sale_price=119.99,
                )
            )
            session.commit()

        prepare = run_agent_turn(
            "Ilan basliklarimi seo uyumlu yap",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"listing.search","arguments":{"query":"seo"}}',
            chat_client=lambda _prompt: "Arama yaptim.",
            db_name=self.db_path,
        )
        audit = run_agent_turn(
            "Tum ilanlari kontrol et fiyat stok baslik gorsel sorunlarini raporla",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"listing.search","arguments":{"query":"gorsel"}}',
            chat_client=lambda _prompt: "Arama yaptim.",
            db_name=self.db_path,
        )

        self.assertTrue(prepare.success, prepare.message)
        self.assertEqual(((prepare.data or {}).get("tool_call") or {}).get("tool"), "listing.content_optimize.prepare")
        self.assertFalse((prepare.data or {}).get("approval_required"))
        prepare_result = (prepare.data or {}).get("tool_result") or {}
        self.assertFalse(prepare_result.get("api_call_performed", True))
        self.assertFalse(prepare_result.get("db_write_performed", True))
        self.assertEqual(prepare_result.get("tool"), "listing.content_optimize.prepare")
        self.assertFalse(bool((prepare_result.get("action") or {}).get("execute_enabled")))

        self.assertTrue(audit.success, audit.message)
        self.assertEqual(((audit.data or {}).get("tool_call") or {}).get("tool"), "listing.quality_audit")
        self.assertFalse(bool((audit.data or {}).get("approval_required")))
        audit_result = (audit.data or {}).get("tool_result") or {}
        self.assertGreaterEqual(int(audit_result.get("needs_improvement") or 0), 1)
        self.assertEqual(audit_result.get("tool"), "listing.quality_audit")

    def test_listing_sales_growth_question_uses_listing_signals_not_empty_search_answer(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-GROWTH-1",
                    title="Dogal At Kili Fircasi",
                    barcode="BAR-GROWTH-1",
                    stock_code="STK-GROWTH-1",
                    brand="DemoBrand",
                    category_name="Temizlik",
                    description="Kisa.",
                    images=[],
                    approved=True,
                    archived=False,
                    on_sale=True,
                    locked=False,
                    quantity=3,
                    list_price=159.99,
                    sale_price=149.99,
                )
            )
            session.commit()

        result = run_agent_turn(
            "at k?l? f?r?as? ?r?n?n?n sat???n? nas?l art?rabiliriz",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"listing.search","arguments":{"query":"at"}}',
            chat_client=lambda _prompt: "Lokal kayitta ilan bulunamadi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        actual_tools = [row.get("tool") for row in ((result.data or {}).get("tool_calls") or [])]
        self.assertEqual(actual_tools, ["listing.search", "listing.quality_audit"])
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("Satis artirma yorumu", answer)
        self.assertIn("Dogal At Kili Fircasi", answer)
        self.assertIn("weak_description", answer)
        self.assertIn("Aksiyon sirasi", answer)
        self.assertNotEqual(answer, "Lokal kayitta ilan bulunamadi.")

    def test_listing_sales_growth_question_without_match_still_returns_action_plan(self) -> None:
        result = run_agent_turn(
            "olmayan urunun satisini nasil artirabiliriz",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"listing.search","arguments":{"query":"olmayan"}}',
            chat_client=lambda _prompt: "Lokal kayitta olmayan icin ilan bulunamadi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        actual_tools = [row.get("tool") for row in ((result.data or {}).get("tool_calls") or [])]
        self.assertEqual(actual_tools, ["listing.search", "listing.quality_audit"])
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("uygulanabilir plan", answer)
        self.assertIn("Basligi arama niyetine gore kur", answer)
        self.assertIn("barkod, stok kodu veya tam ilan basligi", answer)
        self.assertNotEqual(answer, "Lokal kayitta olmayan icin ilan bulunamadi.")

    def test_listing_capability_and_read_questions_do_not_degrade_to_order_lookup_or_thin_answer(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-LISTING-READ-1",
                    title="Agent At Kili Firca",
                    barcode="AGENT-LIST-001",
                    stock_code="agent.at.kili",
                    sale_price=99.9,
                    list_price=129.9,
                    quantity=4,
                    approved=True,
                    on_sale=True,
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-LISTING-READ-2",
                    title="Agent Dikkat Isteyen Ilan",
                    barcode="AGENT-LIST-002",
                    stock_code="agent.problem",
                    sale_price=149.9,
                    list_price=149.9,
                    quantity=0,
                    approved=False,
                    on_sale=False,
                )
            )
            session.commit()

        bad_planner = lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"ilanlar tarafinda neler yapabiliyorsun","limit":10}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        capability = run_agent_turn(
            "ilanlar tarafinda neler yapabiliyorsun",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(capability.success, capability.message)
        capability_data = capability.data or {}
        self.assertEqual(capability_data.get("mode"), "answer")
        self.assertIsNone(capability_data.get("tool_call"))
        capability_answer = str(capability_data.get("answer") or "")
        self.assertIn("Ilanlar/listing tarafinda", capability_answer)
        self.assertIn("fiyat", capability_answer)
        self.assertIn("stok", capability_answer)
        self.assertNotEqual(capability_answer, "Cloud cevabi.")

        cases = [
            ("Agent At Kili Firca ilanlarini listele", "listing.search", ("Agent At Kili Firca", "99.9")),
            ("Agent At Kili Firca fiyatlarini ver", "listing.price_lookup", ("Agent At Kili Firca", "99.9")),
            ("dikkat isteyen ilan sayisi kac", "listing.attention_count", ("ilan dikkat istiyor",)),
            ("Agent At Kili Firca ilanini satis artirmak icin yorumla", "listing.search", ("Satis artirma yorumu", "Agent At Kili Firca")),
        ]
        for prompt, expected_primary_tool, answer_fragments in cases:
            result = run_agent_turn(
                prompt,
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            data = result.data or {}
            tools = [str(row.get("tool")) for row in data.get("tool_calls") or []]
            self.assertTrue(tools, prompt)
            self.assertEqual(tools[0], expected_primary_tool, prompt)
            self.assertNotIn("orders.lookup", tools, prompt)
            answer = str(data.get("answer") or "")
            for fragment in answer_fragments:
                self.assertIn(fragment, answer, prompt)
            self.assertNotEqual(answer, "Cloud cevabi.", prompt)

    def test_listing_content_optimize_approval_cannot_execute_without_adapter(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-SEO-EXEC-1",
                    title="Kisa Baslik",
                    barcode="BAR-SEO-EXEC-1",
                    stock_code="STK-SEO-EXEC-1",
                    brand="DemoBrand",
                    category_name="Ev Gerecleri",
                    description="Kisa.",
                    images=[],
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=4,
                    list_price=129.99,
                    sale_price=119.99,
                )
            )
            session.commit()

        prepared = run_agent_turn(
            "Ilan basliklarimi seo uyumlu yap",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"listing.search","arguments":{"query":"seo"}}',
            chat_client=lambda _prompt: "Hazir.",
            db_name=self.db_path,
        )
        self.assertTrue(prepared.success, prepared.message)
        self.assertFalse(bool((prepared.data or {}).get("approval_required")))
        action = ((prepared.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "listing.content_optimize")
        self.assertFalse(bool(action.get("execute_enabled")))

        verified = operation_runtime.verify_approved_operation(action)
        executed = operation_runtime.execute_approved_operation(action, approved_by="tester")

        self.assertFalse(verified.success)
        self.assertFalse(executed.success)
        self.assertIn("execute adapter henuz bagli degil", verified.message)
        self.assertIn("execute adapter henuz bagli degil", executed.message)
        self.assertFalse(bool((executed.data or {}).get("api_call_performed", True)))
        self.assertFalse(bool((executed.data or {}).get("db_write_performed", True)))

    def test_listing_detail_questions_use_dedicated_lookup_tools(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-DETAIL-1",
                    product_code="PC-DETAIL-1",
                    title="Mavi Silikon Kapak Seti",
                    barcode="BAR-DETAIL-1",
                    stock_code="STK-DETAIL-1",
                    brand="DemoBrand",
                    category_name="Mutfak",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    locked=False,
                    quantity=12,
                    list_price=159.99,
                    sale_price=149.99,
                    product_url="https://example.test/listing/LP-DETAIL-1",
                )
            )
            session.commit()

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        cases = [
            ("BAR-DETAIL-1 barkodlu ilanin adi ne?", "listing.title_lookup", "titles", "title", "Mavi Silikon Kapak Seti"),
            ("STK-DETAIL-1 stok kodlu ilanin detayini getir", "listing.detail_lookup", "details", "brand", "DemoBrand"),
            ("BAR-DETAIL-1 barkodlu ilanin stogu kac?", "listing.stock_lookup", "stocks", "quantity", 12.0),
            ("BAR-DETAIL-1 barkodlu ilanin durumu nedir?", "listing.status_lookup", "statuses", "approved", True),
            ("BAR-DETAIL-1 barkodlu ilanin linki nedir?", "listing.url_lookup", "urls", "product_url", "https://example.test/listing/LP-DETAIL-1"),
        ]

        for prompt, tool_name, collection_key, field, expected in cases:
            result = run_agent_turn(
                prompt,
                planner_client=failing_local_client,
                chat_client=failing_local_client,
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), tool_name)
            rows = ((result.data or {}).get("tool_result") or {}).get(collection_key) or []
            self.assertEqual(rows[0].get(field), expected)
            self.assertNotEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.counts")

    def test_listing_search_question_uses_search_tool_not_count_tool(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-SEARCH-1",
                    product_code="PC-SEARCH-1",
                    title="At Kili Temizlik Fircasi",
                    barcode="BAR-SEARCH-1",
                    stock_code="STK-SEARCH-1",
                    brand="DemoBrand",
                    category_name="Temizlik",
                    quantity=7,
                    sale_price=149.9,
                    approved=True,
                    archived=False,
                    on_sale=True,
                )
            )
            session.commit()

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        for prompt in ("ilan bul bana at kili firca", "at kili firca ilanini bul"):
            result = run_agent_turn(
                prompt,
                planner_client=failing_local_client,
                chat_client=failing_local_client,
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.search")
            rows = ((result.data or {}).get("tool_result") or {}).get("results") or []
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(rows[0].get("title"), "At Kili Temizlik Fircasi")

    def test_listing_multi_price_answer_lists_rows_not_only_count(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-HORSE-1",
                    title="At Kili Yuz Temizleme Fircasi",
                    barcode="BAR-HORSE-1",
                    stock_code="STK-HORSE-1",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=6,
                    list_price=199.9,
                    sale_price=179.9,
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-HORSE-2",
                    title="Dogal At Kili Banyo Fircasi",
                    barcode="BAR-HORSE-2",
                    stock_code="STK-HORSE-2",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=3,
                    list_price=249.0,
                    sale_price=219.0,
                )
            )
            session.commit()

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        result = run_agent_turn(
            "at kili firca urunlerini ad ve fiyat seklinde listele",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertIn(((result.data or {}).get("tool_call") or {}).get("tool"), {"listing.search", "listing.price_lookup"})
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("At Kili Yuz Temizleme Fircasi", answer)
        self.assertIn("Dogal At Kili Banyo Fircasi", answer)
        self.assertIn("179.9 TL", answer)
        self.assertIn("219 TL", answer)
        self.assertNotEqual(answer.strip(), "2 ilan fiyat kaydi bulundu.")

    def test_listing_followup_reuses_previous_query_for_prices(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-HORSE-FOLLOW",
                    title="At Kili Profesyonel Fircasi",
                    barcode="BAR-HORSE-FOLLOW",
                    stock_code="STK-HORSE-FOLLOW",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=8,
                    list_price=349.0,
                    sale_price=299.0,
                )
            )
            session.commit()

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        result = run_agent_turn(
            "tamam dayi ver o ilan fiyat vs",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
            history=[
                {"role": "user", "content": "at kili firca urunlerini listele"},
                {"role": "assistant", "content": "1 ilan bulundu."},
            ],
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.price_lookup")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("arguments"), {"query": "at kili firca", "limit": 5})
        self.assertIn("At Kili Profesyonel Fircasi", str((result.data or {}).get("answer") or ""))
        self.assertIn("299 TL", str((result.data or {}).get("answer") or ""))

    def test_listing_generic_llm_answer_is_replaced_with_rows(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-GENERIC-1",
                    title="At Kili Premium Fircasi",
                    barcode="BAR-GENERIC-1",
                    stock_code="STK-GENERIC-1",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=2,
                    list_price=399.0,
                    sale_price=329.0,
                )
            )
            session.commit()

        def generic_llm(prompt: str) -> str:
            if "Cikti yalnizca JSON olsun" in prompt:
                return '{"mode":"tool","tool":"listing.price_lookup","arguments":{"query":"at kili firca","limit":5}}'
            return "1 ilan fiyat kaydi bulundu."

        result = run_agent_turn(
            "at kili firca fiyatlarini listele",
            planner_client=generic_llm,
            chat_client=generic_llm,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("At Kili Premium Fircasi", answer)
        self.assertIn("329 TL", answer)
        self.assertNotEqual(answer.strip(), "1 ilan fiyat kaydi bulundu.")

    def test_order_generic_llm_answer_is_replaced_with_order_rows(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot(
            "ORD-AGENT-LOOKUP",
            today_start + 1_000,
            package_id=901,
            status="Delivered",
        )

        def generic_llm(prompt: str) -> str:
            if "Cikti yalnizca JSON olsun" in prompt:
                return '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"ORD-AGENT-LOOKUP","limit":5}}'
            return "1 siparis bulundu."

        result = run_agent_turn(
            "ORD-AGENT-LOOKUP siparisini bul",
            planner_client=generic_llm,
            chat_client=generic_llm,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("ORD-AGENT-LOOKUP", answer)
        self.assertIn("Delivered", answer)
        self.assertNotEqual(answer.strip(), "1 siparis bulundu.")

    def test_orders_query_returns_highest_priced_order_without_llm_ranking(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-CHEAP", today_start + 1_000, package_id=101, total_price=99.0)
        self._insert_order_snapshot("ORD-EXPENSIVE", today_start + 2_000, package_id=102, total_price=1299.0)
        self._insert_order_snapshot("ORD-MID", today_start + 3_000, package_id=103, total_price=499.0)

        tool = available_tools()["orders.query"]
        result = tool.handler(
            db_name=self.db_path,
            period="today",
            sort="total_price_desc",
            limit=1,
            mode="top",
            filters={"exclude_cancelled": True},
        )

        self.assertTrue(result.success, result.message)
        orders = (result.data or {}).get("orders") or []
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].get("order_number"), "ORD-EXPENSIVE")
        self.assertEqual(orders[0].get("total_price"), 1299.0)

    def test_period_range_last_n_days_are_inclusive(self) -> None:
        base_day = datetime(2026, 6, 26, tzinfo=TZ_GMT3).date()

        _start_7, _end_7, label_7 = ai_tools._period_range("last_7_days", today=base_day)
        _start_8, _end_8, label_8 = ai_tools._period_range("last_8_days", today=base_day)
        _start_14, _end_14, label_14 = ai_tools._period_range("last_14_days", today=base_day)

        self.assertEqual(label_7, "2026-06-20..2026-06-26")
        self.assertEqual(label_8, "2026-06-19..2026-06-26")
        self.assertEqual(label_14, "2026-06-13..2026-06-26")

    def test_internal_all_period_is_humanized_in_tool_messages(self) -> None:
        self.assertEqual(ai_tools._period_in_message("all"), "Tüm dönemlerde")
        self.assertEqual(
            ai_tools._period_in_message("2026-06-20..2026-06-26"),
            "2026-06-20..2026-06-26 döneminde",
        )

    def test_orders_query_materializes_all_exact_ids_when_limit_is_omitted(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        order_numbers = [
            f"ORD-EXACT-NO-LIMIT-{index:02d}"
            for index in range(1, 12)
        ]
        for index, order_number in enumerate(order_numbers, start=1):
            self._insert_order_snapshot(
                order_number,
                now_ms + index,
                package_id=91_000 + index,
                status="ReadyToShip",
            )

        result = ai_tools.orders_query(
            db_name=self.db_path,
            period="all",
            order_numbers=order_numbers,
            mode="list",
        )

        self.assertTrue(result.success, result.message)
        data = dict(result.data or {})
        self.assertEqual(data.get("count"), 11)
        self.assertEqual(data.get("listed_count"), 11)
        self.assertEqual(len(data.get("orders") or []), 11)
        self.assertEqual(
            set(data.get("returned_order_numbers") or []),
            set(order_numbers),
        )
        self.assertEqual(
            set(data.get("order_numbers") or []),
            set(order_numbers),
        )
        self.assertEqual(
            set(data.get("requested_order_numbers") or []),
            set(order_numbers),
        )
        self.assertEqual((data.get("pagination") or {}).get("limit"), 11)
        self.assertFalse(data.get("truncated"))

    def test_orders_query_exposes_actual_selection_when_input_ids_are_empty(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot(
            "ORD-QUERY-SELECTION-1",
            now_ms,
            package_id=91_101,
            status="Picking",
        )

        result = ai_tools.orders_query(
            db_name=self.db_path,
            period="all",
            filters={"status": "Picking"},
            sort="order_date_desc",
            limit=1,
            mode="list",
        )

        self.assertTrue(result.success, result.message)
        data = dict(result.data or {})
        self.assertEqual(data.get("requested_order_numbers"), [])
        self.assertEqual(data.get("order_numbers"), ["ORD-QUERY-SELECTION-1"])
        self.assertEqual(
            data.get("returned_order_numbers"),
            ["ORD-QUERY-SELECTION-1"],
        )

    def test_highest_priced_order_question_uses_orders_query_not_lookup(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-LOW-RANK", today_start + 1_000, package_id=201, total_price=120.0)
        self._insert_order_snapshot("ORD-HIGH-RANK", today_start + 2_000, package_id=202, total_price=980.0)

        result = run_agent_turn(
            "Bugun en yuksek fiyatli siparisimi getir",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"siparis","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "orders.query")
        tool_result = (result.data or {}).get("tool_result") or {}
        orders = tool_result.get("orders") or []
        self.assertEqual(orders[0].get("order_number"), "ORD-HIGH-RANK")
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("ORD-HIGH-RANK", answer)
        self.assertIn("980 TL", answer)

    def test_non_listing_generic_llm_answers_are_replaced_with_domain_rows(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol", token_valid=False))
            session.add(
                ReturnClaim(
                    claimId="CLAIM-AGENT-1",
                    orderNumber="ORD-RETURN-1",
                    claimDate=now_ms,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    claimItemStatus="WaitingInAction",
                    claimReason="Hasarli urun",
                    totalPrice=88.0,
                    itemCount=2,
                )
            )
            session.add(StockItem(sku="SKU-AGENT-1", name="At Kili Stok Fircasi", barcode="BAR-STOCK-1", brand="DemoBrand"))
            session.add(
                FinanceCostItem(
                    costKey="packing-agent",
                    name="Paketleme Agent Gideri",
                    valueType="fixed",
                    defaultAmount=12.5,
                    currency="TRY",
                    createdAt="2026-01-01T00:00:00",
                    updatedAt="2026-01-01T00:00:00",
                )
            )
            session.add(
                LogisticsCargoTariff(
                    tariffKey="aras-agent",
                    name="Aras Agent Tarife",
                    cargoProviderName="Aras",
                    amount=49.9,
                    currency="TRY",
                )
            )
            session.commit()

        cases = [
            (
                "CLAIM-AGENT-1 iadesini bul",
                '{"mode":"tool","tool":"returns.lookup","arguments":{"query":"CLAIM-AGENT-1","limit":5}}',
                ("CLAIM-AGENT-1", "ORD-RETURN-1", "WaitingInAction"),
            ),
            (
                "At Kili Stok Fircasi stok urununu bul",
                '{"mode":"tool","tool":"stock.search","arguments":{"query":"At Kili Stok Fircasi","limit":5}}',
                ("At Kili Stok Fircasi", "SKU-AGENT-1"),
            ),
            (
                "Paketleme Agent Gideri maliyet kalemini bul",
                '{"mode":"tool","tool":"finance.cost_item_lookup","arguments":{"query":"Paketleme Agent Gideri","limit":5}}',
                ("Paketleme Agent Gideri", "packing-agent", "12.5"),
            ),
            (
                "Aras Agent Tarife kargo tarifesini bul",
                '{"mode":"tool","tool":"logistics.tariff_lookup","arguments":{"query":"Aras Agent Tarife","limit":5}}',
                ("Aras Agent Tarife", "Aras", "49.9"),
            ),
            (
                "Demo Seller pazaryeri hesabini getir",
                '{"mode":"tool","tool":"marketplaces.account_lookup","arguments":{"query":"Demo Seller","limit":5}}',
                ("Demo Seller", "seller-1", "False"),
            ),
        ]

        for prompt, planner_payload, expected_values in cases:
            def generic_llm(llm_prompt: str, payload: str = planner_payload) -> str:
                if "Cikti yalnizca JSON olsun" in llm_prompt:
                    return payload
                return "1 kayit bulundu."

            result = run_agent_turn(
                prompt,
                planner_client=generic_llm,
                chat_client=generic_llm,
                db_name=self.db_path,
            )

            self.assertTrue(result.success, result.message)
            answer = str((result.data or {}).get("answer") or "")
            for expected in expected_values:
                self.assertIn(expected, answer, prompt)
            self.assertNotEqual(answer.strip(), "1 kayit bulundu.")

    def test_stock_capability_and_read_questions_do_not_degrade_to_order_lookup_or_thin_answer(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(StockItem(sku="SKU-STOCK-AGENT-1", name="Agent Stok Fircasi", barcode="BAR-STOCK-AGENT-1", brand="DemoBrand"))
            session.add(StockItem(sku="JLYN-PRTK", name="Agent Tiresiz SKU Urunu"))
            session.add(StockItem(sku="APPROVE-1", name="Agent Onay Urunu"))
            session.commit()

        bad_planner = lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"stok tarafinda neler yapabiliyorsun","limit":10}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        capability = run_agent_turn(
            "stok tarafinda neler yapabiliyorsun",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(capability.success, capability.message)
        capability_data = capability.data or {}
        self.assertEqual(capability_data.get("mode"), "answer")
        self.assertIsNone(capability_data.get("tool_call"))
        capability_answer = str(capability_data.get("answer") or "")
        self.assertIn("Stok/envanter tarafinda", capability_answer)
        self.assertIn("dusuk", capability_answer)
        self.assertIn("execute/verify/audit", capability_answer)
        self.assertNotEqual(capability_answer, "Cloud cevabi.")

        cases = [
            ("stok genel ozetini ver", "stock.inventory_overview", ("stok karti", "bakiye")),
            ("dusuk stok sayisi kac", "stock.low_stock_count", ("dusuk", "stok")),
            (
                "dusuk stok urunlerini listele; sifir eksi ile ayni kavrammis gibi anlatma",
                "stock.low_stock",
                ("Kapsam notu", "ayni tanim degildir", "ortusur"),
            ),
            (
                "stokta sifir veya eksi bakiyeli kac kart var; listeleme yapma ve dusuk stok esigiyle ayni tanim olmadigini belirt",
                "stock.zero_or_negative_count",
                ("sifir/eksi", "esik kuralidir", "Ayni tanim degildirler"),
            ),
            ("stoktaki urunleri listele", "stock.items_list", ("stok urunu", "SKU")),
            (
                "stoktaki urun kartlarindan ilk 5 tanesini listele; her satirda yalniz SKU ad ve mevcut bakiye olsun",
                "stock.items_list",
                ("SKU", "bakiye"),
            ),
            ("Agent Stok Fircasi stok urununu bul", "stock.search", ("Agent Stok Fircasi", "SKU-STOCK-AGENT-1")),
            (
                "SKU'su JLYN-PRTK olan stok kartini tam eslesmeyle bul",
                "stock.search",
                ("Agent Tiresiz SKU Urunu", "JLYN-PRTK"),
            ),
            ("stokta biten urun sayisi kac", "stock.zero_or_negative_count", ("sifir", "stok")),
        ]
        for prompt, expected_tool, answer_fragments in cases:
            result = run_agent_turn(
                prompt,
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            data = result.data or {}
            tools = [str(row.get("tool")) for row in data.get("tool_calls") or []]
            self.assertEqual(tools, [expected_tool], prompt)
            answer = str(data.get("answer") or "")
            for fragment in answer_fragments:
                self.assertIn(fragment, answer, prompt)
            if prompt.startswith("stoktaki urun kartlarindan"):
                self.assertNotIn("barkod:", answer, prompt)
                self.assertNotIn("marka:", answer, prompt)
            self.assertNotIn("siparis bulunamadi", answer.casefold(), prompt)
            self.assertNotEqual(answer, "Cloud cevabi.", prompt)

        overview = run_agent_turn(
            "Stok durumumu genel olarak ozetle; aktif urun karti, toplam bakiye, dusuk/kritik ve sifir/eksi stok sayilarini ayri ayri ver.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(overview.success, overview.message)
        self.assertEqual(
            [str(row.get("tool")) for row in (overview.data or {}).get("tool_calls") or []],
            ["stock.inventory_overview", "stock.low_stock_count"],
        )

        update_prepare = run_agent_turn(
            "APPROVE-1 SKU'lu urunun adini 'Matrix Onay Testi' yapmayi hazirla; calistirma.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(update_prepare.success, update_prepare.message)
        update_data = update_prepare.data or {}
        self.assertEqual((update_data.get("tool_call") or {}).get("tool"), "stock.item_update.prepare")
        self.assertTrue(update_data.get("approval_required"))
        update_action = (update_data.get("tool_result") or {}).get("action") or {}
        self.assertEqual((update_action.get("arguments") or {}).get("query"), "APPROVE-1")
        self.assertEqual((update_action.get("arguments") or {}).get("name"), "Matrix Onay Testi")
        self.assertFalse(update_action.get("db_write_performed"))

        warehouse_prepare = run_agent_turn(
            "'Matrix Gemini Deposu' adli yeni depo olusturmayi hazirla; calistirma.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(warehouse_prepare.success, warehouse_prepare.message)
        warehouse_data = warehouse_prepare.data or {}
        self.assertEqual((warehouse_data.get("tool_call") or {}).get("tool"), "operations.manual_action.route")
        self.assertTrue(warehouse_data.get("approval_required"))
        warehouse_result = warehouse_data.get("tool_result") or {}
        self.assertEqual(warehouse_result.get("route_status"), "approval_prepared")
        self.assertEqual((warehouse_result.get("match") or {}).get("capability_id"), "stock.action_create_warehouse")
        self.assertEqual(
            (((warehouse_result.get("action") or {}).get("arguments") or {}).get("payload") or {}).get("name"),
            "Matrix Gemini Deposu",
        )

        omitted_stock_row = run_agent_turn(
            "dusuk veya kritik stoktaki urunlerin tamamini listele",
            planner_client=bad_planner,
            chat_client=lambda _prompt: "Dusuk stokta yalniz SKU-STOCK-AGENT-1 var.",
            db_name=self.db_path,
        )
        self.assertTrue(omitted_stock_row.success, omitted_stock_row.message)
        omitted_data = omitted_stock_row.data or {}
        self.assertEqual((omitted_data.get("tool_call") or {}).get("tool"), "stock.low_stock")
        returned_skus = [
            str(row.get("sku") or "")
            for row in ((omitted_data.get("tool_result") or {}).get("items") or [])
            if str(row.get("sku") or "")
        ]
        self.assertGreaterEqual(len(returned_skus), 2)
        recovered_answer = str(omitted_data.get("answer") or "")
        for sku in returned_skus:
            self.assertIn(sku, recovered_answer)
        self.assertNotEqual(recovered_answer, "Dusuk stokta yalniz SKU-STOCK-AGENT-1 var.")

        wrong_stock_semantics = run_agent_turn(
            "bakiyesi sifir veya eksi olan kac stok karti var; yalniz sayiyi ve bunun dusuk stoktan farkini soyle, listeleme yapma",
            planner_client=bad_planner,
            chat_client=lambda _prompt: (
                "Sifir veya eksi stok 3. Dusuk stokta ise mutlaka hala urun bulunur."
            ),
            db_name=self.db_path,
        )
        self.assertTrue(wrong_stock_semantics.success, wrong_stock_semantics.message)
        semantic_answer = str((wrong_stock_semantics.data or {}).get("answer") or "")
        self.assertIn("eşik kuralıdır", semantic_answer)
        self.assertIn("Aynı tanım değildirler", semantic_answer)
        self.assertNotIn("mutlaka hala urun", semantic_answer)

        strict_scalar = run_agent_turn(
            "dusuk veya kritik stok karti sayisini yalniz sayi olarak ver",
            planner_client=bad_planner,
            chat_client=lambda _prompt: "3 dusuk/kritik stok kaydi var.",
            db_name=self.db_path,
        )
        self.assertTrue(strict_scalar.success, strict_scalar.message)
        self.assertEqual(
            ((strict_scalar.data or {}).get("tool_call") or {}).get("tool"),
            "stock.low_stock_count",
        )
        self.assertEqual(str((strict_scalar.data or {}).get("answer") or ""), "3")

        exact_sku_projection = run_agent_turn(
            "JLYN-PRTK stok kartini exact SKU ile bul; ad, bakiye ve birimini goster.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"stock.items_list","arguments":{"limit":50}}'
            ),
            chat_client=lambda _prompt: "Sekiz stok kartinin tamamini listeledim.",
            db_name=self.db_path,
        )
        self.assertTrue(exact_sku_projection.success, exact_sku_projection.message)
        projection_data = exact_sku_projection.data or {}
        self.assertEqual((projection_data.get("tool_call") or {}).get("tool"), "stock.search")
        self.assertEqual(
            (projection_data.get("tool_call") or {}).get("arguments"),
            {"query": "JLYN-PRTK", "limit": 1},
        )
        self.assertEqual(len((projection_data.get("tool_result") or {}).get("items") or []), 1)
        projection_answer = str(projection_data.get("answer") or "")
        self.assertIn("Agent Tiresiz SKU Urunu", projection_answer)
        self.assertIn("bakiye:", projection_answer)
        self.assertNotIn("barkod:", projection_answer)
        self.assertNotIn("marka:", projection_answer)
        self.assertNotIn("Sekiz stok kartinin", projection_answer)

        for shorthand_prompt in (
            "Yalniz JLYN-PRTK exact SKU kaydini getir; sadece ad, bakiye ve birim olsun.",
            "Hafizadaki ozeti kullanma; JLYN-PRTK icin authoritative stok kaydini exact SKU ile yeniden oku ve yalniz ad, bakiye, birim ver.",
            "SKU sorgu anahtariydi, cikti alani degildi; ayni JLYN-PRTK kaydini yeniden oku ve satirda yalniz ad, bakiye, birim goster.",
        ):
            exact_shorthand = run_agent_turn(
                shorthand_prompt,
                planner_client=lambda _prompt: (
                    '{"mode":"tool","tool":"stock.inventory_overview","arguments":{"limit":20}}'
                ),
                chat_client=lambda _prompt: "Genel envanter ozetini kullandim.",
                db_name=self.db_path,
            )
            self.assertTrue(exact_shorthand.success, exact_shorthand.message)
            shorthand_data = exact_shorthand.data or {}
            self.assertEqual((shorthand_data.get("tool_call") or {}).get("tool"), "stock.search")
            self.assertEqual(
                (shorthand_data.get("tool_call") or {}).get("arguments"),
                {"query": "JLYN-PRTK", "limit": 1},
            )
            shorthand_answer = str(shorthand_data.get("answer") or "")
            self.assertNotIn("Genel envanter", shorthand_answer)
            self.assertNotIn("SKU:", shorthand_answer)
            self.assertNotIn("stok urunu buldum", shorthand_answer)
            self.assertNotIn("JLYN-PRTK", shorthand_answer)

        exact_context = dict(projection_data.get("conversation_context") or {})
        self.assertEqual(exact_context.get("kind"), "stock_exact_lookup")
        self.assertEqual(exact_context.get("query"), "JLYN-PRTK")
        deictic_reread = run_agent_turn(
            "Bu satırı otoritatif kaynaktan yeniden oku; aynı JLYN kaydı, "
            "yine sadece ad, bakiye ve birim.",
            planner_client=lambda _prompt: '{"mode":"answer","response":"hafizadan"}',
            chat_client=lambda _prompt: "hafizadan",
            db_name=self.db_path,
            history=[
                {
                    "role": "assistant",
                    "content": str(projection_data.get("answer") or ""),
                    "context": exact_context,
                }
            ],
        )
        self.assertTrue(deictic_reread.success, deictic_reread.message)
        deictic_data = deictic_reread.data or {}
        self.assertEqual(
            (deictic_data.get("tool_call") or {}).get("tool"),
            "stock.search",
        )
        self.assertEqual(
            (deictic_data.get("tool_call") or {}).get("arguments"),
            {"query": "JLYN-PRTK", "limit": 1},
        )
        self.assertNotIn("hafizadan", str(deictic_data.get("answer") or ""))

        exact_sku_misplanned = run_agent_turn(
            "SKU'su JLYN-PRTK olan stok kartini yeniden tam eslesmeyle bul",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"stock.inventory_overview","arguments":{"limit":20}}'
            ),
            chat_client=lambda _prompt: "Genel stok tablosu.",
            db_name=self.db_path,
        )
        self.assertTrue(exact_sku_misplanned.success, exact_sku_misplanned.message)
        exact_data = exact_sku_misplanned.data or {}
        self.assertEqual((exact_data.get("tool_call") or {}).get("tool"), "stock.search")
        self.assertEqual((exact_data.get("tool_call") or {}).get("arguments", {}).get("query"), "JLYN-PRTK")
        self.assertIn("JLYN-PRTK", str(exact_data.get("answer") or ""))

        def tight_local_planner(_prompt):
            return '{"mode":"tool","tool":"stock.inventory_overview","arguments":{"limit":20}}'

        tight_local_planner.resource_plan = {
            "profile": "local_model",
            "num_ctx": 1024,
        }
        tight_local_exact = run_agent_turn(
            "SKU'su JLYN-PRTK olan stok kartini yeniden tam eslesmeyle bul",
            planner_client=tight_local_planner,
            chat_client=tight_local_planner,
            db_name=self.db_path,
        )
        self.assertTrue(tight_local_exact.success, tight_local_exact.message)
        tight_data = tight_local_exact.data or {}
        self.assertEqual((tight_data.get("tool_call") or {}).get("tool"), "stock.search")
        self.assertEqual((tight_data.get("tool_call") or {}).get("arguments", {}).get("query"), "JLYN-PRTK")
        self.assertIn("JLYN-PRTK", str(tight_data.get("answer") or ""))

    def test_finance_capability_and_read_questions_do_not_degrade_to_order_lookup_or_thin_answer(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                FinanceCostItem(
                    costKey="packing-agent-finance",
                    name="Paketleme Agent Finans Gideri",
                    valueType="fixed",
                    defaultAmount=12.5,
                    currency="TRY",
                    createdAt="2026-01-01T00:00:00",
                    updatedAt="2026-01-01T00:00:00",
                )
            )
            session.add(
                OrderHeader(
                    orderNumber="ORD-FINANCE-AGENT-1",
                    orderDate=now_ms,
                    status="Delivered",
                    packageTotalPrice=250.0,
                    totalPrice=250.0,
                )
            )
            session.commit()

        bad_planner = lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"finans tarafinda neler yapabiliyorsun","limit":10}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        capability = run_agent_turn(
            "finans tarafinda neler yapabiliyorsun",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(capability.success, capability.message)
        capability_data = capability.data or {}
        self.assertEqual(capability_data.get("mode"), "answer")
        self.assertIsNone(capability_data.get("tool_call"))
        capability_answer = str(capability_data.get("answer") or "")
        self.assertIn("Finans tarafinda", capability_answer)
        self.assertIn("nakit", capability_answer)
        self.assertIn("prepare/execute/verify/audit", capability_answer)
        self.assertNotEqual(capability_answer, "Cloud cevabi.")

        guarded_capability = run_agent_turn(
            "Finance tarafinda bana hangi guvenli okumalari ve hangi onayli "
            "islemleri yaptirabilirsin?",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(guarded_capability.success, guarded_capability.message)
        guarded_data = guarded_capability.data or {}
        self.assertEqual(guarded_data.get("mode"), "answer")
        self.assertEqual(guarded_data.get("tool_calls"), [])
        guarded_answer = str(guarded_data.get("answer") or "")
        self.assertIn("Finans tarafinda", guarded_answer)
        self.assertIn("onaydan once", guarded_answer)
        self.assertNotIn("Finans hareketleri:", guarded_answer)

        cases = [
            ("bugunku karim ne kadar", ["finance.profit_amount"], ("karli oldugumuzu soyleyemem", "maliyet")),
            ("bu ay nakit akisi ne", ["finance.cashflow_summary"], ("net nakit hareketi", "TRY")),
            (
                "Bu ay nakit akisini gelir, gider ve net olarak ayri ayri ozetle.",
                ["finance.cashflow_summary"],
                ("Gelir/alacak", "Gider/borc", "Net nakit"),
            ),
            ("bu ay net nakit akisi ne", ["finance.cashflow_net"], ("net nakit", "TRY")),
            (
                "Nakit akisi ile tahmini kar ayni sey mi? Bu ayki dogrulanmis veriye gore ayir.",
                ["finance.profit_amount", "finance.cashflow_summary"],
                ("kar hesabina", "net nakit hareketi"),
            ),
            (
                "Bu ay ciro ile tahmini kari birlikte ver; ciroyu kar sayma.",
                ["orders.revenue_total", "finance.profit_amount"],
                ("ciro", "kar hesabina"),
            ),
            (
                "Bu ay kar tahminini detayli hesapla ve neden hazir olmadigini ozetle.",
                ["finance.profit_estimate"],
                ("kar hesabina", "maliyet"),
            ),
            ("maliyet kalemlerini listele", ["finance.cost_catalog"], ("aktif finans maliyet kalemi", "Paketleme Agent Finans Gideri")),
            ("Paketleme Agent Finans Gideri maliyet kalemini bul", ["finance.cost_item_lookup"], ("Paketleme Agent Finans Gideri", "12.5")),
            ("maliyet kalemi sayisi kac", ["finance.cost_item_count"], ("aktif maliyet kalemi",)),
            (
                "finans ozetini ver",
                ["finance.profit_amount", "finance.cashflow_net", "finance.cost_item_count"],
                ("karli oldugumuzu soyleyemem", "net nakit", "aktif maliyet kalemi"),
            ),
        ]
        for prompt, expected_tools, answer_fragments in cases:
            result = run_agent_turn(
                prompt,
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            data = result.data or {}
            tools = [str(row.get("tool")) for row in data.get("tool_calls") or []]
            self.assertEqual(tools, expected_tools, prompt)
            answer = str(data.get("answer") or "")
            for fragment in answer_fragments:
                self.assertIn(fragment, answer, prompt)
            self.assertNotIn("siparis bulunamadi", answer.casefold(), prompt)
            self.assertNotEqual(answer, "Cloud cevabi.", prompt)

    def test_finance_verified_facts_exact_lookup_and_strict_projection_are_authoritative(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add_all(
                [
                    FinanceCostItem(
                        costKey="paketleme",
                        name="Paketleme",
                        valueType="numeric",
                        defaultAmount=3.5,
                        currency="TRY",
                        createdAt="2026-01-01T00:00:00",
                        updatedAt="2026-01-01T00:00:00",
                    ),
                    FinanceCostItem(
                        costKey="kargo",
                        name="Kargo",
                        valueType="numeric",
                        defaultAmount=49.9,
                        currency="TRY",
                        createdAt="2026-01-01T00:00:00",
                        updatedAt="2026-01-01T00:00:00",
                    ),
                    OrderHeader(
                        orderNumber="ORD-FINANCE-PRIVATE-1",
                        orderDate=now_ms,
                        status="Delivered",
                        packageTotalPrice=250.0,
                        totalPrice=250.0,
                    ),
                ]
            )
            session.commit()

        bad_planner = lambda _prompt: '{"mode":"answer","response":"wrong"}'
        bad_chat = lambda _prompt: "wrong"

        cashflow = run_agent_turn(
            "Bu ay net nakit akisi ne?",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(cashflow.success, cashflow.message)
        self.assertEqual([row.get("tool") for row in (cashflow.data or {}).get("tool_calls") or []], ["finance.cashflow_net"])
        self.assertIn("net nakit 0 TRY", str((cashflow.data or {}).get("answer") or ""))
        self.assertNotEqual(str((cashflow.data or {}).get("answer") or ""), "wrong")

        count = run_agent_turn(
            "Aktif maliyet kalemi sayisi kac?",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(count.success, count.message)
        self.assertIn("2 aktif maliyet kalemi", str((count.data or {}).get("answer") or ""))

        catalog = run_agent_turn(
            "Aktif maliyet kalemlerini listele; sadece ad, tip, varsayilan tutar ve para birimi.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(catalog.success, catalog.message)
        catalog_answer = str((catalog.data or {}).get("answer") or "")
        self.assertIn("Paketleme | hesaplama tipi: numeric | varsayilan tutar: 3.5 | para birimi: TRY", catalog_answer)
        self.assertIn("Kargo | hesaplama tipi: numeric | varsayilan tutar: 49.9 | para birimi: TRY", catalog_answer)
        self.assertNotIn("kod:", catalog_answer)
        self.assertNotIn("aktif:", catalog_answer)
        self.assertNotIn("toplam kayit", catalog_answer)

        lookup = run_agent_turn(
            "Paketleme maliyet kalemini bul; sadece ad, tutar ve para birimi.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(lookup.success, lookup.message)
        lookup_data = lookup.data or {}
        self.assertEqual((lookup_data.get("tool_call") or {}).get("arguments", {}).get("query"), "paketleme")
        rows = (lookup_data.get("tool_result") or {}).get("cost_items") or []
        self.assertEqual([row.get("name") for row in rows], ["Paketleme"])
        lookup_answer = str(lookup_data.get("answer") or "")
        self.assertIn("Paketleme | varsayilan tutar: 3.5 | para birimi: TRY", lookup_answer)
        self.assertNotIn("Kargo", lookup_answer)
        self.assertNotIn("hesaplama tipi", lookup_answer)
        self.assertNotIn("KDV", lookup_answer)

        read_named_kabul = run_agent_turn(
            "Olmayan Finance Kabul maliyet kalemini bul; sadece ad ve tutar.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(read_named_kabul.success, read_named_kabul.message)
        named_data = read_named_kabul.data or {}
        self.assertEqual(
            [row.get("tool") for row in named_data.get("tool_calls") or []],
            ["finance.cost_item_lookup"],
        )
        self.assertNotEqual(
            ((named_data.get("tool_result") or {}).get("match") or {}).get("capability_id"),
            "finance.accept_finance_cost_item",
        )

        profit = run_agent_turn(
            "Bu ay tahmini kar tutarini yalniz sayi ve para birimiyle ver.",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(profit.success, profit.message)
        profit_answer = str((profit.data or {}).get("answer") or "")
        self.assertIn("kar hesabina girecek siparis ve ciro bulunmadi", profit_answer)
        self.assertNotIn("ORD-FINANCE-PRIVATE-1", profit_answer)
        self.assertNotIn("Eksik veri ornekleri", profit_answer)

        missing_cost_answer = ai_agent._deterministic_single_tool_answer(
            "finance.profit_amount",
            {
                "period_label": "2026-07-01..2026-07-19",
                "amount": None,
                "currency": "TRY",
                "estimated_profit_ready": False,
                "complete_order_count": 0,
                "incomplete_order_count": 1,
                "revenue": 250.0,
                "missing_reasons": [
                    "ORD-FINANCE-PRIVATE-1: Musteri ve urun adi ile maliyet eksik"
                ],
            },
            "",
            user_message="Tahmini kar tutarini yalniz sayi ve para birimiyle ver.",
        )
        self.assertIn("tahmini kar hesaplanamiyor", missing_cost_answer)
        self.assertIn("1 sipariste maliyet kapsami eksik", missing_cost_answer)
        self.assertNotIn("ORD-FINANCE-PRIVATE-1", missing_cost_answer)
        self.assertNotIn("Musteri", missing_cost_answer)

    def test_finance_metric_context_repeats_verified_result_without_tool_or_model(self) -> None:
        first = run_agent_turn(
            "Bu ay net nakit akisi ne?",
            planner_client=lambda _prompt: '{"mode":"answer","response":"wrong"}',
            chat_client=lambda _prompt: "wrong",
            db_name=self.db_path,
        )
        self.assertTrue(first.success, first.message)
        first_data = first.data or {}
        context = dict(first_data.get("conversation_context") or {})
        self.assertEqual(context.get("kind"), "finance_metric_result")
        self.assertEqual(context.get("source_tool"), "finance.cashflow_net")
        self.assertEqual(float(context.get("amount")), 0.0)

        def fail_client(_prompt: str) -> str:
            raise AssertionError("Finance metric recall must not invoke a model")

        recalled = run_agent_turn(
            "sadece sonucu tekrar soyle",
            planner_client=fail_client,
            chat_client=fail_client,
            history=[
                {"role": "user", "content": "Bu ay net nakit akisi ne?"},
                {
                    "role": "assistant",
                    "content": str(first_data.get("answer") or ""),
                    "context": context,
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(recalled.success, recalled.message)
        recalled_data = recalled.data or {}
        self.assertEqual(recalled_data.get("answer"), "0 TRY")
        self.assertEqual(recalled_data.get("decision_path"), "contextual_finance_metric_recall_guard")
        self.assertFalse(bool(recalled_data.get("model_invoked")))
        self.assertEqual(recalled_data.get("tool_calls"), [])

    def test_explicit_finance_metric_with_number_only_format_does_not_recall_old_cost_count(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Lokal kayda gore 5 aktif maliyet kalemi var.",
                "context": {
                    "kind": "scalar_tool_result",
                    "active_domain": "finance",
                    "source_tool": "finance.cost_item_count",
                    "scalar_facts": {"count": 5},
                    "authoritative_answer": "Lokal kayda gore 5 aktif maliyet kalemi var.",
                },
            }
        ]
        result = run_agent_turn(
            "Bu ay tahmini kar tutarini yalniz sayi ve para birimiyle ver.",
            planner_client=lambda _prompt: '{"mode":"answer","response":"wrong"}',
            chat_client=lambda _prompt: "wrong",
            history=history,
            db_name=self.db_path,
        )
        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual([row.get("tool") for row in data.get("tool_calls") or []], ["finance.profit_amount"])
        self.assertNotEqual(str(data.get("answer") or "").strip(), "5")
        self.assertNotEqual(data.get("decision_path"), "contextual_scalar_recall_guard")

    def test_finance_save_inflection_prepares_save_not_accept_without_writing(self) -> None:
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)
        with Session(get_engine(self.db_path)) as session:
            before_count = len(session.exec(select(FinanceCostItem)).all())

        result = run_agent_turn(
            "Trendyol icin Codex Finance Kabul maliyet kalemini 7.25 TL tutarla "
            "kaydetmeye hazirla, onay olmadan calistirma.",
            planner_client=lambda _prompt: '{"mode":"answer","response":"wrong"}',
            chat_client=lambda _prompt: "wrong",
            db_name=self.db_path,
        )
        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("mode"), "approval_required")
        tool_result = data.get("tool_result") or {}
        self.assertEqual(
            (tool_result.get("match") or {}).get("capability_id"),
            "finance.save_finance_cost_item",
        )
        cost_payload = (tool_result.get("payload") or {}).get("cost_payload") or {}
        self.assertEqual(cost_payload.get("name"), "Codex Finance Kabul")
        self.assertEqual(float(cost_payload.get("defaultAmount")), 7.25)
        self.assertFalse(bool(tool_result.get("api_call_performed")))
        self.assertFalse(bool(tool_result.get("db_write_performed")))
        context = dict(data.get("conversation_context") or {})
        self.assertEqual(context.get("kind"), "pending_action")
        safe_payload = dict(context.get("safe_payload") or {})
        self.assertEqual(safe_payload.get("name"), "Codex Finance Kabul")
        self.assertEqual(float(safe_payload.get("default_amount")), 7.25)
        self.assertEqual(safe_payload.get("currency"), "TRY")
        self.assertEqual(safe_payload.get("supported_platforms"), ["TRENDYOL"])

        def fail_client(_prompt: str) -> str:
            raise AssertionError("Pending Finance scope read must not invoke a model")

        scope = run_agent_turn(
            "Bu onay tam olarak neyi kaydedecek, tutari ve platformu ne? "
            "Tek cumlede soyle, henuz calistirma.",
            planner_client=fail_client,
            chat_client=fail_client,
            history=[
                {"role": "user", "content": "maliyet kalemini kaydetmeye hazirla"},
                {
                    "role": "assistant",
                    "content": str(data.get("answer") or ""),
                    "context": context,
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(scope.success, scope.message)
        scope_data = scope.data or {}
        scope_answer = str(scope_data.get("answer") or "")
        self.assertIn("Codex Finance Kabul", scope_answer)
        self.assertIn("7.25 TRY", scope_answer)
        self.assertIn("TRENDYOL", scope_answer)
        self.assertIn("API", scope_answer)
        self.assertIn("DB", scope_answer)
        self.assertIn("; risk seviyesi medium;", scope_answer)
        self.assertNotIn(". Risk seviyesi:", scope_answer)
        self.assertFalse(bool(scope_data.get("model_invoked")))
        self.assertEqual(scope_data.get("tool_calls"), [])
        with Session(get_engine(self.db_path)) as session:
            after_count = len(session.exec(select(FinanceCostItem)).all())
        self.assertEqual(after_count, before_count)

    def test_risky_price_update_prepare_requires_approval_without_writing(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-1",
                    comp_name="Demo Seller",
                    platform="trendyol",
                    api_key="api-key",
                    api_secret="api-secret",
                    extra_config={"environment": "stage"},
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-RISK-PRICE",
                    title="At Kili Riskli Fiyat Fircasi",
                    barcode="BAR-RISK-PRICE",
                    stock_code="STK-RISK-PRICE",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=4,
                    list_price=120.0,
                    sale_price=100.0,
                )
            )
            session.commit()

        result = run_agent_turn("At Kili Riskli Fiyat Fircasi fiyatini 89.99 yap", db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "tool")
        self.assertFalse((result.data or {}).get("approval_required"))
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.update_price.prepare")
        proposal = ((result.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertEqual(proposal.get("action_type"), "listing.update_price")
        self.assertFalse(bool(proposal.get("execute_enabled")))
        self.assertFalse(proposal.get("api_call_performed", True))
        rows = proposal.get("rows") or []
        self.assertEqual(rows[0].get("current_sale_price"), 100.0)
        self.assertEqual(rows[0].get("requested_sale_price"), 89.99)
        staging_action = proposal.get("staging_action") or {}
        self.assertEqual(staging_action.get("action_type"), "listing.action_update_price_inventory_for_account")
        staging_payload = ((staging_action.get("arguments") or {}).get("payload") or {})
        self.assertEqual(staging_payload.get("api_account_id"), 1)
        self.assertEqual(staging_payload.get("items"), [{"barcode": "BAR-RISK-PRICE", "quantity": 4, "salePrice": 89.99, "listPrice": 120.0}])
        self.assertNotIn("api_key", staging_payload)
        self.assertNotIn("api_secret", staging_payload)
        with Session(get_engine(self.db_path)) as session:
            row = session.exec(select(ListingProduct).where(ListingProduct.product_id == "LP-RISK-PRICE")).one()
            self.assertEqual(row.sale_price, 100.0)

    def test_explicit_stock_manual_movement_bypasses_model_planner(self) -> None:
        planner_calls: list[str] = []

        result = choose_action(
            "APPROVE-1 için varsayılan depoda 3 adet manuel stok girişi hazırla; çalıştırma.",
            planner_client=lambda prompt: planner_calls.append(prompt) or "yanlış",
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        decision = data.get("decision")
        self.assertEqual(
            getattr(decision, "tool_name", ""),
            "operations.manual_action.route",
        )
        self.assertEqual(data.get("decision_path"), "stock_manual_action_guard")
        self.assertFalse(data.get("model_invoked"))
        self.assertEqual(planner_calls, [])

    def test_manual_action_prepare_summary_keeps_required_qty_after_secret_filtering(self) -> None:
        payload = {
            "item_id": 8,
            "warehouse_id": 2,
            "currency": "TRY",
            "note": "Agent dogal dil stok islemi",
            "db_name": "must-not-be-visible.db",
            "qty": 3.0,
        }

        answer = ai_agent._deterministic_tool_answer(
            "APPROVE-1 icin 3 adet manuel stok girisi hazirla; calistirma.",
            [
                {
                    "data": {
                        "action": {
                            "approval_required": True,
                            "execute_enabled": True,
                            "action_type": "stock.action_manual_in",
                            "title": "Manuel pipeline aksiyonu onayi",
                            "summary": "stock.action_manual_in icin agentic prepare hazirlandi.",
                            "arguments": {"payload": payload},
                            "rows": [{"payload": payload}],
                        }
                    }
                }
            ],
        )

        self.assertIn("qty=3.0", answer)
        self.assertNotIn("db_name", answer)
        self.assertNotIn("must-not-be-visible", answer)

    def test_command_like_exact_sku_is_opaque_read_identifier(self) -> None:
        planner_calls: list[str] = []

        result = choose_action(
            "APPROVE-1 exact SKU stok kaydını yeniden oku; sadece SKU ve bakiye ver.",
            planner_client=lambda prompt: planner_calls.append(prompt) or (
                '{"mode":"tool","tool":"listing.update_stock.prepare",'
                '"arguments":{"query":"APPROVE-1","new_quantity":1}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        decision = data.get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "stock.search")
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {"query": "APPROVE-1", "limit": 1},
        )
        self.assertEqual(data.get("decision_path"), "stock_exact_lookup_guard")
        self.assertFalse(data.get("model_invoked"))
        self.assertEqual(planner_calls, [])

    def test_total_stock_item_wording_routes_to_item_count(self) -> None:
        result = choose_action(
            "Toplam stok ürünü sayısını getir.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"stock.search",'
                '"arguments":{"query":"toplam sayisini","limit":10}}'
            ),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "stock.item_count")
        self.assertEqual(
            [call.tool_name for call in getattr(decision, "tool_calls", ())],
            ["stock.item_count"],
        )

    def test_pending_action_scope_question_with_do_not_run_is_not_cancel(self) -> None:
        planner_calls: list[str] = []
        result = choose_action(
            "Şu an onay bekleyen işlem tam olarak neyi değiştirecek? Çalıştırma.",
            planner_client=lambda prompt: planner_calls.append(prompt) or "yanlış",
            history=[
                {
                    "role": "assistant",
                    "content": "Onay gerekiyor.",
                    "context": {
                        "kind": "pending_action",
                        "action_type": "stock.action_manual_in",
                        "risk_level": "medium",
                        "approval_required": True,
                        "safe_payload": {
                            "item_id": 8,
                            "warehouse_id": 2,
                            "qty": 3.0,
                        },
                    },
                }
            ],
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        decision = data.get("decision")
        self.assertEqual(getattr(decision, "mode", ""), "answer")
        self.assertIn("item_id=8", getattr(decision, "response", ""))
        self.assertIn("3.0 adet manuel giriş", getattr(decision, "response", ""))
        self.assertEqual(data.get("decision_path"), "pending_action_scope_read_guard")
        self.assertFalse(data.get("model_invoked"))
        self.assertEqual(planner_calls, [])

    def test_pending_label_scope_and_file_question_reads_without_superseding(self) -> None:
        planner_calls: list[str] = []
        result = choose_action(
            "Bu hazırlık hangi sipariş kümesine ve hangi şablona bağlı, "
            "herhangi bir dosya üretildi mi?",
            planner_client=lambda prompt: planner_calls.append(prompt) or "yanlış",
            history=[
                {
                    "role": "assistant",
                    "content": "Onay gerekiyor.",
                    "context": {
                        "kind": "pending_action",
                        "action_type": "labels.action_create_labels_from_selected_orders",
                        "risk_level": "medium",
                        "approval_required": True,
                        "safe_payload": {
                            "brand_code": "TANEX",
                            "model_code": "TANEX_2610",
                        },
                        "order_numbers": ["ORD-PENDING-1", "ORD-PENDING-2"],
                    },
                }
            ],
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        decision = data.get("decision")
        answer = getattr(decision, "response", "")
        self.assertEqual(getattr(decision, "mode", ""), "answer")
        self.assertIn("2 sipariş", answer)
        self.assertIn("TANEX 2610", answer)
        self.assertIn("ORD-PENDING-1", answer)
        self.assertIn("ORD-PENDING-2", answer)
        self.assertIn("dosya/çıktı üretimi", answer)
        self.assertEqual(data.get("decision_path"), "pending_action_scope_read_guard")
        self.assertFalse(data.get("model_invoked"))
        self.assertEqual(planner_calls, [])

    def test_risky_stock_update_prepare_requires_approval_without_writing(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-RISK-STOCK",
                    title="At Kili Riskli Stok Fircasi",
                    barcode="BAR-RISK-STOCK",
                    stock_code="STK-RISK-STOCK",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=8,
                    list_price=150.0,
                    sale_price=130.0,
                )
            )
            session.commit()

        result = run_agent_turn("At Kili Riskli Stok Fircasi stok miktarini 2 yap", db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "tool")
        self.assertFalse((result.data or {}).get("approval_required"))
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.update_stock.prepare")
        proposal = ((result.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertEqual(proposal.get("action_type"), "listing.update_stock")
        self.assertFalse(bool(proposal.get("execute_enabled")))
        self.assertFalse(proposal.get("api_call_performed", True))
        answer = str((result.data or {}).get("answer") or "").casefold()
        self.assertIn("onay taslagi hazir", answer)
        self.assertNotIn("hazirlanamadi", answer)
        self.assertIn("stok: 8 -> 2", answer)
        self.assertNotIn("fiyat:", answer)
        rows = proposal.get("rows") or []
        self.assertEqual(rows[0].get("current_quantity"), 8.0)
        self.assertEqual(rows[0].get("requested_quantity"), 2)
        with Session(get_engine(self.db_path)) as session:
            row = session.exec(select(ListingProduct).where(ListingProduct.product_id == "LP-RISK-STOCK")).one()
            self.assertEqual(row.quantity, 8)

    def test_listing_price_prepare_bridges_to_staging_marketplace_action_only(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-listing-stage",
                    comp_name="Listing Stage Seller",
                    platform="trendyol",
                    api_key="stage-api-key",
                    api_secret="stage-api-secret",
                    extra_config={"environment": "stage"},
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-STAGING-PRICE",
                    title="Staging At Kili Fircasi",
                    barcode="BAR-STAGING-PRICE",
                    stock_code="STK-STAGING-PRICE",
                    approved=True,
                    archived=False,
                    on_sale=True,
                    quantity=5,
                    list_price=120.0,
                    sale_price=100.0,
                )
            )
            session.commit()

        prepared = run_agent_turn("Staging At Kili Fircasi fiyatini 110 yap", db_name=self.db_path)
        self.assertTrue(prepared.success, prepared.message)
        self.assertFalse(bool((prepared.data or {}).get("approval_required")))
        action = ((prepared.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "listing.update_price")
        staging_action = action.get("staging_action") or {}
        self.assertEqual(staging_action.get("action_type"), "listing.action_update_price_inventory_for_account")

        direct = operation_runtime.execute_approved_operation(action)
        self.assertFalse(direct.success)
        self.assertTrue(((direct.data or {}).get("staging_action_available")))

        from Listing.views import actions as listing_actions

        calls: list[dict[str, Any]] = []

        def _fake_update_price_inventory_for_account(**kwargs) -> Result:
            calls.append(dict(kwargs))
            return Result.ok(
                "Staging listing fake tamam.",
                close_dialog=False,
                data={"batch_request_id": "BATCH-LISTING-STAGE", "items": kwargs.get("items") or []},
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "listing-staging-audit.jsonl"
            evidence_path = Path(tmp_dir) / "listing-staging-evidence.json"
            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: ""}, clear=False), patch.object(
                listing_actions,
                "action_update_price_inventory_for_account",
                _fake_update_price_inventory_for_account,
            ):
                blocked = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="listing-staging-test",
                    staging_reason="controlled staging listing price proof",
                    staging_account_id="seller-listing-stage",
                    audit_path=audit_path,
                )
            self.assertFalse(blocked.success)
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False), patch.object(
                listing_actions,
                "action_update_price_inventory_for_account",
                _fake_update_price_inventory_for_account,
            ):
                missing_key = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="listing-staging-test",
                    staging_reason="controlled staging listing price proof",
                    staging_account_id="seller-listing-stage",
                    audit_path=audit_path,
                )
                missing_account = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="listing-staging-test",
                    idempotency_key="listing-staging-price-missing-account",
                    staging_reason="controlled staging listing price proof",
                    audit_path=audit_path,
                )
                mismatched_account = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="listing-staging-test",
                    idempotency_key="listing-staging-price-mismatch",
                    staging_reason="controlled staging listing price proof",
                    staging_account_id="seller-production",
                    audit_path=audit_path,
                )
            self.assertFalse(missing_key.success)
            self.assertEqual((missing_key.data or {}).get("missing"), "idempotency_key")
            self.assertFalse(missing_account.success)
            self.assertEqual((missing_account.data or {}).get("missing"), "staging_account_id")
            self.assertFalse(mismatched_account.success)
            self.assertEqual((mismatched_account.data or {}).get("target_account_ids"), ["seller-listing-stage"])
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False):
                preflight = operation_runtime.preflight_staging_marketplace_operation(
                    action,
                    idempotency_key="listing-staging-price-proof",
                    staging_reason="controlled staging listing price proof",
                    staging_account_id="seller-listing-stage",
                )
            self.assertTrue(preflight.success, preflight.message)
            self.assertEqual(((preflight.data or {}).get("staging_proof") or {}).get("target_account_ids"), ["seller-listing-stage"])
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False), patch.object(
                listing_actions,
                "action_update_price_inventory_for_account",
                _fake_update_price_inventory_for_account,
            ):
                executed = operation_runtime.execute_staging_marketplace_evidence_run(
                    action,
                    approved_by="listing-staging-test",
                    idempotency_key="listing-staging-price-proof",
                    staging_reason="controlled staging listing price proof",
                    staging_account_id="seller-listing-stage",
                    audit_path=audit_path,
                    evidence_path=evidence_path,
                )

            self.assertTrue(executed.success, executed.message)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["api_key"], "stage-api-key")
            self.assertEqual(calls[0]["api_secret"], "stage-api-secret")
            self.assertEqual(calls[0]["seller_id"], "seller-listing-stage")
            self.assertEqual(calls[0]["items"], [{"barcode": "BAR-STAGING-PRICE", "quantity": 5, "salePrice": 110.0, "listPrice": 120.0}])
            proof = (executed.data or {}).get("staging_proof") or {}
            self.assertEqual(proof.get("mode"), "staging_marketplace_mutation")
            self.assertEqual(proof.get("target_account_ids"), ["seller-listing-stage"])
            self.assertEqual(proof.get("idempotency_key"), "listing-staging-price-proof")
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "listing.action_update_price_inventory_for_account"', audit_text)
            self.assertIn('"staging_proof"', audit_text)
            self.assertNotIn("stage-api-secret", audit_text)
            self.assertTrue(evidence_path.exists())
            evidence_text = evidence_path.read_text(encoding="utf-8")
            self.assertIn('"artifact_type": "orders_staging_marketplace_evidence"', evidence_text)
            self.assertIn('"execute_success": true', evidence_text)
            self.assertNotIn("stage-api-secret", evidence_text)

    def test_listing_explicit_content_update_prepares_exact_stage_action_and_verifies_batch(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-content-stage",
                    comp_name="Content Stage Seller",
                    platform="trendyol",
                    api_key="credential://marketplaces/content-stage-test",
                    api_secret=None,
                    extra_config={"environment": "stage", "acceptLanguage": "tr-TR"},
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-CONTENT-1",
                    product_content_id=9001,
                    title="Eski Başlık",
                    description="Eski açıklama",
                    images=[{"url": "https://cdn.example.com/old.jpg"}],
                    barcode="BAR-CONTENT-1",
                    stock_code="STK-CONTENT-1",
                    approved=True,
                    archived=False,
                    on_sale=True,
                )
            )
            session.commit()

        prepared = run_agent_turn(
            'BAR-CONTENT-1 barkodlu ilanın başlığını "Yeni Başlık" yap',
            db_name=self.db_path,
        )
        self.assertTrue(prepared.success, prepared.message)
        self.assertEqual(((prepared.data or {}).get("tool_call") or {}).get("tool"), "listing.content_update.prepare")
        action = ((prepared.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "listing.content_update")
        self.assertFalse(action.get("execute_enabled"))
        staging_action = action.get("staging_action") or {}
        self.assertEqual(staging_action.get("action_type"), "listing.action_update_approved_content_for_account")
        payload = ((staging_action.get("arguments") or {}).get("payload") or {})
        self.assertEqual(payload.get("api_account_id"), 1)
        self.assertEqual(payload.get("content_id"), 9001)
        self.assertEqual(payload.get("items"), [{"contentId": 9001, "title": "Yeni Başlık"}])
        self.assertNotIn("api_key", payload)
        self.assertNotIn("api_secret", payload)

        direct_outer = operation_runtime.execute_approved_operation(action)
        direct_inner = operation_runtime.execute_approved_operation(staging_action)
        self.assertFalse(direct_outer.success)
        self.assertFalse(direct_inner.success)
        self.assertFalse((direct_inner.data or {}).get("api_call_performed", True))
        tampered_action = copy.deepcopy(action)
        tampered_payload = (((tampered_action.get("staging_action") or {}).get("arguments") or {}).get("payload") or {})
        tampered_payload["wait_result"] = False
        with patch.dict(
            os.environ,
            {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"},
            clear=False,
        ):
            tampered_preflight = operation_runtime.preflight_staging_marketplace_operation(
                tampered_action,
                idempotency_key="content-stage-tampered-1",
                staging_reason="controlled staging content tamper proof",
                staging_account_id="seller-content-stage",
            )
        self.assertFalse(tampered_preflight.success)
        self.assertIn("content_batch_verify_scope", (tampered_preflight.data or {}).get("problems") or [])

        from Listing.views import actions as listing_actions

        calls: list[dict[str, Any]] = []

        def fake_content_update(**kwargs) -> Result:
            calls.append(dict(kwargs))
            return Result.ok(
                "verified",
                close_dialog=False,
                data={
                    "verified": True,
                    "batch_request_id": "BATCH-CONTENT-STAGE",
                    "content_id": kwargs.get("content_id"),
                    "item_status": "SUCCESS",
                },
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "content-stage-audit.jsonl"
            with patch.dict(
                os.environ,
                {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"},
                clear=False,
            ), patch.object(
                listing_actions,
                "action_update_approved_content_for_account",
                fake_content_update,
            ):
                executed = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="content-stage-test",
                    idempotency_key="content-stage-proof-1",
                    staging_reason="controlled staging approved content proof",
                    staging_account_id="seller-content-stage",
                    audit_path=audit_path,
                )

            self.assertTrue(executed.success, executed.message)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["environment"], "stage")
            self.assertEqual(calls[0]["accept_language"], "tr-TR")
            self.assertEqual(
                calls[0]["credential_reference"],
                "credential://marketplaces/content-stage-test",
            )
            self.assertEqual(calls[0]["api_key"], "")
            self.assertEqual(calls[0]["api_secret"], "")
            self.assertEqual(calls[0]["seller_id"], "seller-content-stage")
            self.assertEqual(calls[0]["items"], [{"contentId": 9001, "title": "Yeni Başlık"}])
            self.assertEqual(((executed.data or {}).get("verify") or {}).get("verified_by"), "trendyol_batch_result")
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "listing.action_update_approved_content_for_account"', audit_text)
            self.assertNotIn("credential://marketplaces/content-stage-test", audit_text)

    def test_listing_content_update_rejects_ambiguous_scope_and_keeps_seo_suggestion_unbound(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Seller 1", platform="trendyol"))
            session.add(ApiAccount(pk=2, account_id="seller-2", comp_name="Seller 2", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LP-SAME-1",
                    product_content_id=1001,
                    title="Ortak Ürün Başlığı",
                    barcode="BAR-SAME-1",
                    approved=True,
                    archived=False,
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=2,
                    product_id="LP-SAME-2",
                    product_content_id=1002,
                    title="Ortak Ürün Başlığı",
                    barcode="BAR-SAME-2",
                    approved=True,
                    archived=False,
                )
            )
            session.commit()

        ambiguous = ai_tools.listing_prepare_content_update(
            db_name=self.db_path,
            query="Ortak Ürün Başlığı",
            title="Yeni Ortak Başlık",
        )
        self.assertFalse(ambiguous.success)
        self.assertEqual((ambiguous.data or {}).get("matched_target_count"), 2)

        suggestion = ai_tools.listing_prepare_content_optimize(
            db_name=self.db_path,
            query="BAR-SAME-1",
            scope="seo",
            limit=5,
        )
        self.assertTrue(suggestion.success, suggestion.message)
        suggestion_action = (suggestion.data or {}).get("action") or {}
        self.assertEqual(suggestion_action.get("action_type"), "listing.content_optimize")
        self.assertFalse(suggestion_action.get("execute_enabled"))
        self.assertNotIn("staging_action", suggestion_action)
        self.assertFalse(operation_runtime.execute_approved_operation(suggestion_action).success)

    def test_listing_explicit_content_update_parser_requires_user_values(self) -> None:
        title_args = ai_agent._listing_explicit_content_update_arguments(
            'BAR-1 barkodlu ilanın başlığını "Yeni Başlık" yap'
        )
        description_args = ai_agent._listing_explicit_content_update_arguments(
            'BAR-2 barkodlu ilanın açıklamasını "Yeni açıklama" güncelle'
        )
        image_args = ai_agent._listing_explicit_content_update_arguments(
            "BAR-3 barkodlu ilanın görsellerini https://cdn.example.com/1.jpg, https://cdn.example.com/2.jpg ile değiştir"
        )

        self.assertEqual(title_args, {"query": "BAR-1", "title": "Yeni Başlık"})
        self.assertEqual(description_args, {"query": "BAR-2", "description": "Yeni açıklama"})
        self.assertEqual(
            image_args,
            {
                "query": "BAR-3",
                "image_urls": [
                    "https://cdn.example.com/1.jpg",
                    "https://cdn.example.com/2.jpg",
                ],
            },
        )
        self.assertIsNone(
            ai_agent._listing_explicit_content_update_arguments(
                "BAR-4 barkodlu ilanın başlığını SEO uyumlu yap"
            )
        )

    def test_stock_item_create_prepare_requires_approval_without_writing(self) -> None:
        result = run_agent_turn(
            "SKU-AGENT-1 sku ile 'AI Hazir Stok Karti' adinda yeni stok karti olustur",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "stock.item_create.prepare")
        proposal = (result.data or {}).get("action_proposal") or {}
        self.assertEqual(proposal.get("action_type"), "stock.item_create")
        self.assertFalse(proposal.get("db_write_performed", True))
        self.assertFalse(proposal.get("api_call_performed", True))
        row = (proposal.get("rows") or [{}])[0]
        self.assertEqual((row.get("after") or {}).get("sku"), "SKU-AGENT-1")
        self.assertEqual((row.get("after") or {}).get("name"), "AI Hazir Stok Karti")
        with Session(get_engine(self.db_path)) as session:
            created = session.exec(select(StockItem).where(StockItem.sku == "SKU-AGENT-1")).first()
            self.assertIsNone(created)

    def test_stock_item_update_prepare_reports_changes_without_writing(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(StockItem(sku="STK-OLD-1", name="Eski Stok Karti", unit="adet", is_active=True))
            session.commit()

        planner_payload = (
            '{"mode":"tool","tool":"stock.item_update.prepare",'
            '"arguments":{"query":"STK-OLD-1","name":"Yeni SEO Stok Karti","limit":5}}'
        )

        def planner(prompt: str) -> str:
            if "Cikti yalnizca JSON olsun" in prompt:
                return planner_payload
            return "Hazir."

        result = run_agent_turn(
            "STK-OLD-1 stok kartinin adini Yeni SEO Stok Karti yap",
            planner_client=planner,
            chat_client=planner,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "stock.item_update.prepare")
        proposal = (result.data or {}).get("action_proposal") or {}
        self.assertEqual(proposal.get("action_type"), "stock.item_update")
        self.assertFalse(proposal.get("db_write_performed", True))
        row = (proposal.get("rows") or [{}])[0]
        self.assertEqual(((row.get("changes") or {}).get("name") or {}).get("before"), "Eski Stok Karti")
        self.assertEqual(((row.get("changes") or {}).get("name") or {}).get("after"), "Yeni SEO Stok Karti")
        with Session(get_engine(self.db_path)) as session:
            saved = session.exec(select(StockItem).where(StockItem.sku == "STK-OLD-1")).one()
            self.assertEqual(saved.name, "Eski Stok Karti")

    def test_operations_capability_catalog_inventories_manual_action_surface(self) -> None:
        registry = available_tools()
        result = registry["operations.capability_catalog"].handler(domain="stock", mode="write", limit=200)

        self.assertTrue(result.success, result.message)
        capabilities = (result.data or {}).get("capabilities") or []
        ids = {row.get("capability_id") for row in capabilities}
        self.assertIn("stock.action_create_item", ids)
        self.assertIn("stock.action_update_item", ids)
        self.assertIn("stock.action_delete_item", ids)
        summary = (result.data or {}).get("summary") or {}
        self.assertGreater(int(summary.get("write_total") or 0), 20)
        ai_result = registry["operations.capability_catalog"].handler(domain="ai", limit=50)
        self.assertTrue(ai_result.success, ai_result.message)
        ai_ids = {row.get("capability_id") for row in ((ai_result.data or {}).get("capabilities") or [])}
        self.assertIn("ai.action_save_provider_account", ai_ids)
        self.assertIn("ai.action_download_hf_model", ai_ids)
        ai_download = next(row for row in ((ai_result.data or {}).get("capabilities") or []) if row.get("capability_id") == "ai.action_download_hf_model")
        self.assertEqual(ai_download.get("mode"), "write")
        self.assertTrue(ai_download.get("requires_approval"))
        self.assertTrue(ai_download.get("external_write"))

    def test_manual_capability_inventory_covers_view_action_functions(self) -> None:
        from AI.processors.manual_capabilities import list_manual_capabilities

        desktop_root = Path(__file__).resolve().parents[2]
        expected: set[str] = set()
        excluded = {"update_records", "update_progress"}
        for path in desktop_root.glob("*/views/actions.py"):
            domain = path.parts[-3].casefold()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_") or node.name in excluded:
                    continue
                if re.match(r"^(action_|get_|list_|save_|update_|delete_|approve_|fetch_|export_)", node.name):
                    expected.add(f"{domain}.{node.name}")

        actual = {capability.capability_id for capability in list_manual_capabilities()}
        self.assertEqual(sorted(expected - actual), [])

    def test_operations_manual_action_prepare_wraps_pipeline_capability_without_writing(self) -> None:
        registry = available_tools()
        result = registry["operations.manual_action.prepare"].handler(
            capability_id="stock.action_update_item",
            payload={"pk": 123, "update_data": {"name": "Yeni Ad"}},
            reason="Agent stok karti adini degistirmek istiyor.",
        )

        self.assertTrue(result.success, result.message)
        self.assertTrue((result.data or {}).get("approval_required"))
        self.assertFalse((result.data or {}).get("db_write_performed", True))
        action = (result.data or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "stock.action_update_item")
        self.assertEqual(action.get("status"), "pending_approval")
        row = (action.get("rows") or [{}])[0]
        self.assertEqual((row.get("capability") or {}).get("module_path"), "Stock.views.actions")
        self.assertEqual((row.get("payload") or {}).get("pk"), 123)

    def test_operations_manual_action_prepare_rejects_missing_required_payload(self) -> None:
        registry = available_tools()
        result = registry["operations.manual_action.prepare"].handler(
            capability_id="stock.action_create_warehouse",
            payload={},
            reason="Eksik payload ile onay action uretmemeli.",
        )

        self.assertFalse(result.success)
        self.assertEqual((result.data or {}).get("missing_parameters"), ["name"])
        self.assertFalse((result.data or {}).get("approval_required", True))
        self.assertFalse((result.data or {}).get("db_write_performed", True))
        self.assertNotIn("action", result.data or {})

    def test_stock_item_create_execute_uses_pipeline_verifies_and_audits_idempotently(self) -> None:
        registry = available_tools()
        prepare = registry["stock.item_create.prepare"].handler(
            db_name=self.db_path,
            sku="STK-EXEC-1",
            name="Execute Stok Karti",
            unit="adet",
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(operation_runtime.stock_pipeline, "DB_NAME", self.db_path), patch.object(
                operation_runtime.stock_pipeline, "_ENGINE", None
            ), patch.object(operation_runtime.stock_pipeline, "_ENGINE_DB_NAME", None):
                result = operation_runtime.execute_stock_item_create(
                    action,
                    approved_by="test-user",
                    idempotency_key="stock-create-test",
                    audit_path=audit_path,
                )
                second = operation_runtime.execute_stock_item_create(
                    action,
                    approved_by="test-user",
                    idempotency_key="stock-create-test",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(result.success, result.message)
        self.assertFalse((result.data or {}).get("idempotent", False))
        self.assertTrue(second.success, second.message)
        self.assertTrue((second.data or {}).get("idempotent"))
        with Session(get_engine(self.db_path)) as session:
            rows = session.exec(select(StockItem).where(StockItem.sku == "STK-EXEC-1")).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "Execute Stok Karti")
        self.assertIn('"operation": "stock.item_create"', audit_text)

    def test_stock_item_update_execute_uses_pipeline_and_verify(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(StockItem(sku="STK-EXEC-UPD", name="Eski Execute Ad", unit="adet", is_active=True))
            session.commit()

        registry = available_tools()
        prepare = registry["stock.item_update.prepare"].handler(
            db_name=self.db_path,
            query="STK-EXEC-UPD",
            name="Yeni Execute Ad",
            limit=5,
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(operation_runtime.stock_pipeline, "DB_NAME", self.db_path), patch.object(
                operation_runtime.stock_pipeline, "_ENGINE", None
            ), patch.object(operation_runtime.stock_pipeline, "_ENGINE_DB_NAME", None):
                result = operation_runtime.execute_stock_item_update(
                    action,
                    approved_by="test-user",
                    idempotency_key="stock-update-test",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(result.success, result.message)
        with Session(get_engine(self.db_path)) as session:
            row = session.exec(select(StockItem).where(StockItem.sku == "STK-EXEC-UPD")).one()
            self.assertEqual(row.name, "Yeni Execute Ad")
        verify = (result.data or {}).get("verify") or {}
        self.assertTrue(verify.get("verified"))
        self.assertIn('"operation": "stock.item_update"', audit_text)

    def test_stock_manual_movements_adjust_export_and_warehouse_execute_verify_audit(self) -> None:
        registry = available_tools()
        with Session(get_engine(self.db_path)) as session:
            item = StockItem(sku="SKU-STOCK-AGENT", name="Agent Stok Urunu", unit="adet", vat_rate=20.0)
            warehouse = Warehouse(name="Agent Ana Depo", code="AGENT-WH")
            delete_warehouse = Warehouse(name="Agent Silinecek Depo", code="AGENT-DEL")
            session.add(item)
            session.add(warehouse)
            session.add(delete_warehouse)
            session.commit()
            session.refresh(item)
            session.refresh(warehouse)
            session.refresh(delete_warehouse)
            item_pk = int(item.pk or 0)
            warehouse_pk = int(warehouse.pk or 0)
            delete_warehouse_pk = int(delete_warehouse.pk or 0)

        def _prepare(capability_id: str, payload: dict[str, Any]):
            prepared = registry["operations.manual_action.prepare"].handler(
                capability_id=capability_id,
                payload={**payload, "db_name": self.db_path},
                reason=f"{capability_id} agentic execute verify testi.",
            )
            self.assertTrue(prepared.success, prepared.message)
            action = (prepared.data or {}).get("action") or {}
            self.assertTrue(action.get("approval_required"), action)
            self.assertTrue(action.get("execute_enabled"), action)
            return action

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "stock-manual-audit.jsonl"
            manual_in = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_manual_in",
                    {
                        "item_id": item_pk,
                        "warehouse_id": warehouse_pk,
                        "qty": 10,
                        "unit_cost": 15.0,
                        "unit_cost_input_mode": "gross",
                        "currency": "TRY",
                        "note": "Agent stok giris",
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-manual-in-agentic",
                audit_path=audit_path,
            )
            manual_out = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_manual_out",
                    {
                        "item_id": item_pk,
                        "warehouse_id": warehouse_pk,
                        "qty": 3,
                        "currency": "TRY",
                        "note": "Agent stok cikis",
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-manual-out-agentic",
                audit_path=audit_path,
            )
            adjust = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_adjust_item_stock_to",
                    {
                        "item_id": item_pk,
                        "warehouse_id": warehouse_pk,
                        "target_qty": 20,
                        "unit_cost": 12.0,
                        "unit_cost_input_mode": "gross",
                        "currency": "TRY",
                        "note": "Agent stok hedef duzeltme",
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-adjust-agentic",
                audit_path=audit_path,
            )

            with Session(get_engine(self.db_path)) as session:
                tx_rows = session.exec(select(StockTx).where(StockTx.item_id == item_pk).order_by(StockTx.pk.asc())).all()
                tx_ids = [int(row.pk or 0) for row in tx_rows]
            export_path = Path(tmp_dir) / "stock-agent-txs.xlsx"
            export = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_export_txs_excel",
                    {
                        "tx_ids": tx_ids,
                        "output_path": str(export_path),
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-export-agentic",
                audit_path=audit_path,
            )
            warehouse_update = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_update_warehouse",
                    {
                        "pk": warehouse_pk,
                        "update_data": {"note": "Agent depo guncel", "code": "AGENT-WH-2"},
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-warehouse-update-agentic",
                audit_path=audit_path,
            )
            warehouse_delete = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_delete_warehouse",
                    {"pk": delete_warehouse_pk},
                ),
                approved_by="test-user",
                idempotency_key="stock-warehouse-delete-agentic",
                audit_path=audit_path,
            )
            export_size = export_path.stat().st_size if export_path.exists() else 0
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        for name, result in (
            ("manual_in", manual_in),
            ("manual_out", manual_out),
            ("adjust", adjust),
            ("export", export),
            ("warehouse_update", warehouse_update),
            ("warehouse_delete", warehouse_delete),
        ):
            with self.subTest(operation=name):
                self.assertTrue(result.success, f"{name}: {result.message} | {result.data}")
        self.assertEqual(((manual_in.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((manual_out.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((adjust.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((export.data or {}).get("verify") or {}).get("verified_by"), "filesystem")
        self.assertEqual(((warehouse_update.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((warehouse_delete.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertGreater(export_size, 0)
        with Session(get_engine(self.db_path)) as session:
            rows = session.exec(select(StockTx).where(StockTx.item_id == item_pk)).all()
            balance = sum(float(row.qty or 0) if str(row.direction.value).casefold() == "in" else -float(row.qty or 0) for row in rows)
            updated_warehouse = session.get(Warehouse, warehouse_pk)
            deleted_warehouse = session.get(Warehouse, delete_warehouse_pk)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(balance, 20.0)
        self.assertIsNotNone(updated_warehouse)
        self.assertEqual(getattr(updated_warehouse, "code", ""), "AGENT-WH-2")
        self.assertIsNone(deleted_warehouse)
        for operation in (
            "stock.action_manual_in",
            "stock.action_manual_out",
            "stock.action_adjust_item_stock_to",
            "stock.action_export_txs_excel",
            "stock.action_update_warehouse",
            "stock.action_delete_warehouse",
        ):
            self.assertIn(f'"operation": "{operation}"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        self.assertIn('"verified_by": "filesystem"', audit_text)

    def test_stock_manual_natural_prompts_prepare_execute_and_verify_with_db_payload(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            item = StockItem(sku="SKU-STOCK-LIVE", name="Agent Canli Stok Urunu", unit="adet", vat_rate=20.0)
            warehouse = Warehouse(name="Agent Ana Depo", code="AGENT-WH-LIVE")
            session.add(item)
            session.add(warehouse)
            session.commit()
            session.refresh(item)
            session.refresh(warehouse)
            item_pk = int(item.pk or 0)
            warehouse_pk = int(warehouse.pk or 0)

        bad_planner = lambda _prompt: (
            '{"mode":"tool","tool":"listing.update_stock.prepare",'
            '"arguments":{"query":"SKU-STOCK-LIVE","new_quantity":1}}'
        )
        bad_chat = lambda _prompt: "tamam"
        prompts = [
            (
                "SKU-STOCK-LIVE urunune Agent Ana Depo icin 10 adet stok giris yap birim maliyet 15 TL",
                "stock.action_manual_in",
                "qty",
                10,
                "stock-natural-in",
            ),
            (
                "SKU-STOCK-LIVE urununden Agent Ana Depo icin 3 adet stok cikis yap",
                "stock.action_manual_out",
                "qty",
                3,
                "stock-natural-out",
            ),
            (
                "SKU-STOCK-LIVE stok miktarini Agent Ana Depoda 20 adede duzelt birim maliyet 12 TL",
                "stock.action_adjust_item_stock_to",
                "target_qty",
                20,
                "stock-natural-adjust",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "stock-natural-audit.jsonl"
            results = []
            for prompt, capability_id, qty_key, qty_value, idem in prompts:
                turn = run_agent_turn(
                    prompt,
                    planner_client=bad_planner,
                    chat_client=bad_chat,
                    db_name=self.db_path,
                )
                self.assertTrue(turn.success, turn.message)
                self.assertEqual((turn.data or {}).get("mode"), "approval_required")
                self.assertEqual(((turn.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.prepare")
                action = (turn.data or {}).get("action_proposal") or {}
                self.assertEqual(action.get("action_type"), capability_id)
                payload = ((action.get("arguments") or {}).get("payload") or {})
                self.assertEqual(payload.get("item_id"), item_pk)
                self.assertEqual(payload.get("warehouse_id"), warehouse_pk)
                self.assertEqual(float(payload.get(qty_key)), float(qty_value))
                self.assertEqual(payload.get("db_name"), self.db_path)
                result = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="test-user",
                    idempotency_key=idem,
                    audit_path=audit_path,
                )
                self.assertTrue(result.success, result.message)
                verify = (result.data or {}).get("verify") or {}
                self.assertTrue(verify.get("verified"), verify)
                self.assertEqual(verify.get("verified_by"), "db")
                results.append(result)
            export_path = Path(tmp_dir) / "stock-natural-export.xlsx"
            export_turn = run_agent_turn(
                f"SKU-STOCK-LIVE stok hareketlerini {export_path} dosyasina Excel olarak aktar",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(export_turn.success, export_turn.message)
            self.assertEqual((export_turn.data or {}).get("mode"), "approval_required")
            self.assertEqual(((export_turn.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.prepare")
            export_action = (export_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(export_action.get("action_type"), "stock.action_export_txs_excel")
            export_payload = ((export_action.get("arguments") or {}).get("payload") or {})
            self.assertEqual(export_payload.get("output_path"), str(export_path))
            self.assertEqual(export_payload.get("db_name"), self.db_path)
            self.assertEqual(len(export_payload.get("tx_ids") or []), 3)
            export_result = operation_runtime.execute_approved_operation(
                export_action,
                approved_by="test-user",
                idempotency_key="stock-natural-export",
                audit_path=audit_path,
            )
            self.assertTrue(export_result.success, export_result.message)
            export_verify = (export_result.data or {}).get("verify") or {}
            self.assertTrue(export_verify.get("verified"), export_verify)
            self.assertEqual(export_verify.get("verified_by"), "filesystem")
            self.assertTrue(export_path.exists())
            self.assertGreater(export_path.stat().st_size, 0)
            results.append(export_result)
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertEqual(len(results), 4)
        with Session(get_engine(self.db_path)) as session:
            tx_rows = session.exec(select(StockTx).where(StockTx.item_id == item_pk)).all()
        self.assertEqual(len(tx_rows), 3)
        balance = 0.0
        for tx in tx_rows:
            direction = str(getattr(tx.direction, "value", tx.direction)).casefold()
            qty = float(tx.qty or 0)
            balance += -qty if direction.endswith("out") else qty
        self.assertEqual(balance, 20.0)
        self.assertIn('"operation": "stock.action_manual_in"', audit_text)
        self.assertIn('"operation": "stock.action_manual_out"', audit_text)
        self.assertIn('"operation": "stock.action_adjust_item_stock_to"', audit_text)
        self.assertIn('"operation": "stock.action_export_txs_excel"', audit_text)

    def test_stock_remaining_db_writes_execute_verify_and_audit(self) -> None:
        registry = available_tools()
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-stock-auto", comp_name="Stock Auto Seller", platform="trendyol"))
            item = StockItem(
                sku="SKU-STOCK-REMAIN",
                name="Agent Kalan Stok Urunu",
                unit="adet",
                vat_rate=20.0,
                allow_negative_stock=False,
            )
            delete_item = StockItem(
                sku="SKU-STOCK-DELETE",
                name="Agent Silinecek Stok",
                unit="adet",
                vat_rate=20.0,
                allow_negative_stock=False,
            )
            warehouse = Warehouse(name="Agent Kalan Depo", code="AGENT-REM-WH")
            session.add(item)
            session.add(delete_item)
            session.add(warehouse)
            session.commit()
            session.refresh(item)
            session.refresh(delete_item)
            session.refresh(warehouse)
            item_pk = int(item.pk or 0)
            delete_item_pk = int(delete_item.pk or 0)
            warehouse_pk = int(warehouse.pk or 0)
            listing = ListingProduct(
                api_account_id=1,
                product_id="LP-STOCK-AUTO",
                product_code="PC-STOCK-AUTO",
                barcode="BAR-STOCK-AUTO",
                stock_code="SKU-STOCK-REMAIN",
                title="Agent Auto Stok Listing",
                stock_item_id=item_pk,
                quantity=10,
                updated_at=datetime.now(),
            )
            session.add(listing)
            session.add(OrderHeader(orderNumber="ORD-STOCK-AUTO", api_account_id=1))
            session.add(
                OrderItem(
                    orderNumber="ORD-STOCK-AUTO",
                    api_account_id=1,
                    quantity=2,
                    productCode=111222,
                    barcode="BAR-STOCK-AUTO",
                    merchantSku="SKU-STOCK-REMAIN",
                    sku="SKU-STOCK-REMAIN",
                    orderLineItemStatusName="Created",
                )
            )
            session.commit()
            session.refresh(listing)
            session.add(ListingProductStockSnapshot(listing_id=int(listing.pk or 0), stock_item_id=item_pk, qty=1))
            session.commit()

        def _prepare(capability_id: str, payload: dict[str, Any]):
            prepared = registry["operations.manual_action.prepare"].handler(
                db_name=self.db_path,
                capability_id=capability_id,
                payload=payload,
                reason=f"{capability_id} kalan stock agentic verify testi.",
            )
            self.assertTrue(prepared.success, prepared.message)
            action = (prepared.data or {}).get("action") or {}
            self.assertTrue(action.get("execute_enabled"), action)
            return action

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "stock-remaining-audit.jsonl"
            manual_in = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_manual_in",
                    {
                        "item_id": item_pk,
                        "warehouse_id": warehouse_pk,
                        "qty": 10,
                        "unit_cost": 20.0,
                        "unit_cost_input_mode": "gross",
                        "currency": "TRY",
                        "note": "Auto deduct oncesi stok",
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-remain-manual-in",
                audit_path=audit_path,
            )
            self.assertTrue(manual_in.success, manual_in.message)
            tx_id = int(((manual_in.data or {}).get("result") or {}).get("tx_id") or 0)
            self.assertGreater(tx_id, 0)

            attachments = operation_runtime.execute_approved_operation(
                _prepare("stock.action_update_tx_attachments", {"tx_id": tx_id, "attachments": "irsaliye:AGENT-001"}),
                approved_by="test-user",
                idempotency_key="stock-remain-attachments",
                audit_path=audit_path,
            )
            edit_fields = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_update_tx_edit_fields",
                    {
                        "tx_id": tx_id,
                        "attachments": "irsaliye:AGENT-002",
                        "unit_cost_input_mode": "gross",
                        "unit_cost_vat_rate": 20.0,
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-remain-edit-fields",
                audit_path=audit_path,
            )
            auto_deduct = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_auto_deduct_order_items",
                    {
                        "order_item_list": [
                            {
                                "orderNumber": "ORD-STOCK-AUTO",
                                "api_account_id": 1,
                                "quantity": 2,
                                "productCode": 111222,
                                "barcode": "BAR-STOCK-AUTO",
                                "merchantSku": "SKU-STOCK-REMAIN",
                                "sku": "SKU-STOCK-REMAIN",
                                "orderLineItemStatusName": "Created",
                            }
                        ],
                        "created_by": "agentic-test",
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-remain-auto-deduct",
                audit_path=audit_path,
            )
            delete_seed = operation_runtime.execute_approved_operation(
                _prepare(
                    "stock.action_manual_in",
                    {
                        "item_id": delete_item_pk,
                        "warehouse_id": warehouse_pk,
                        "qty": 1,
                        "unit_cost": 5.0,
                        "unit_cost_input_mode": "gross",
                        "currency": "TRY",
                        "note": "Delete cascade seed",
                    },
                ),
                approved_by="test-user",
                idempotency_key="stock-remain-delete-seed",
                audit_path=audit_path,
            )
            self.assertTrue(delete_seed.success, delete_seed.message)
            delete_stock_item = operation_runtime.execute_approved_operation(
                _prepare("stock.action_delete_item", {"pk": delete_item_pk, "cascade": True}),
                approved_by="test-user",
                idempotency_key="stock-remain-delete-item",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        for name, result, verified_by in (
            ("attachments", attachments, "db"),
            ("edit_fields", edit_fields, "db"),
            ("auto_deduct", auto_deduct, "db"),
            ("delete_stock_item", delete_stock_item, "db"),
        ):
            with self.subTest(operation=name):
                self.assertTrue(result.success, f"{name}: {result.message} | {result.data}")
                verify = (result.data or {}).get("verify") or {}
                self.assertTrue(verify.get("verified"), verify)
                self.assertEqual(verify.get("verified_by"), verified_by)

        with Session(get_engine(self.db_path)) as session:
            edited_tx = session.get(StockTx, tx_id)
            delete_row = session.get(StockItem, delete_item_pk)
            delete_txs = session.exec(select(StockTx).where(StockTx.item_id == delete_item_pk)).all()
            item_txs = session.exec(select(StockTx).where(StockTx.item_id == item_pk)).all()
        self.assertIsNotNone(edited_tx)
        self.assertEqual(getattr(edited_tx, "attachments", ""), "irsaliye:AGENT-002")
        self.assertIsNone(delete_row)
        self.assertEqual(delete_txs, [])
        order_out_rows = [
            tx for tx in item_txs
            if str(getattr(getattr(tx, "reason", ""), "value", getattr(tx, "reason", ""))).casefold() == "order_out"
        ]
        self.assertEqual(len(order_out_rows), 1)
        self.assertEqual(float(order_out_rows[0].qty or 0), 2.0)
        for operation in (
            "stock.action_update_tx_attachments",
            "stock.action_update_tx_edit_fields",
            "stock.action_auto_deduct_order_items",
            "stock.action_delete_item",
        ):
            self.assertIn(f'"operation": "{operation}"', audit_text)

    def test_stock_group_catalog_writes_execute_verify_with_isolated_files(self) -> None:
        from Stock.processors import catalog as stock_catalog

        registry = available_tools()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            default_upper = tmp_path / "default-upper.json"
            default_sub = tmp_path / "default-sub.json"
            user_upper = tmp_path / "user-upper.json"
            user_sub = tmp_path / "user-sub.json"
            item_types = tmp_path / "item-types.json"
            default_upper.write_text('["Default Ust"]', encoding="utf-8")
            default_sub.write_text('{"Default Ust": [{"name": "Default Alt"}]}', encoding="utf-8")
            item_types.write_text('[{"label":"Fiziksel","value":"physical"}]', encoding="utf-8")

            def _prepare(capability_id: str, payload: dict[str, Any]):
                prepared = registry["operations.manual_action.prepare"].handler(
                    db_name=self.db_path,
                    capability_id=capability_id,
                    payload=payload,
                    reason=f"{capability_id} izole catalog verify testi.",
                )
                self.assertTrue(prepared.success, prepared.message)
                action = (prepared.data or {}).get("action") or {}
                self.assertTrue(action.get("execute_enabled"), action)
                return action

            with patch.object(stock_catalog, "DEFAULT_UPPER_GROUPS_FILE", default_upper), patch.object(
                stock_catalog, "DEFAULT_SUB_GROUPS_FILE", default_sub
            ), patch.object(stock_catalog, "USER_UPPER_GROUPS_FILE", user_upper), patch.object(
                stock_catalog, "USER_SUB_GROUPS_FILE", user_sub
            ), patch.object(stock_catalog, "ITEM_TYPE_OPTIONS_FILE", item_types), patch.object(
                stock_catalog, "ensure_constants_paths", lambda: None
            ):
                stock_catalog._invalidate_catalog_cache()
                audit_path = tmp_path / "stock-catalog-audit.jsonl"
                create_upper = operation_runtime.execute_approved_operation(
                    _prepare("stock.action_create_upper_group", {"name": "Agent Ust Grup"}),
                    approved_by="test-user",
                    idempotency_key="stock-catalog-create-upper",
                    audit_path=audit_path,
                )
                upper_pk = int((((create_upper.data or {}).get("verify") or {}).get("pk")) or 0)
                update_upper = operation_runtime.execute_approved_operation(
                    _prepare("stock.action_update_upper_group", {"pk": upper_pk, "update_data": {"name": "Agent Ust Grup Yeni"}}),
                    approved_by="test-user",
                    idempotency_key="stock-catalog-update-upper",
                    audit_path=audit_path,
                )
                create_sub = operation_runtime.execute_approved_operation(
                    _prepare("stock.action_create_sub_group", {"category": "Agent Ust Grup Yeni", "name": "Agent Alt Grup"}),
                    approved_by="test-user",
                    idempotency_key="stock-catalog-create-sub",
                    audit_path=audit_path,
                )
                sub_pk = int((((create_sub.data or {}).get("verify") or {}).get("pk")) or 0)
                update_sub = operation_runtime.execute_approved_operation(
                    _prepare(
                        "stock.action_update_sub_group",
                        {
                            "pk": sub_pk,
                            "update_data": {"category": "Agent Ust Grup Yeni", "name": "Agent Alt Grup Yeni", "is_active": True},
                        },
                    ),
                    approved_by="test-user",
                    idempotency_key="stock-catalog-update-sub",
                    audit_path=audit_path,
                )
                delete_sub = operation_runtime.execute_approved_operation(
                    _prepare("stock.action_delete_sub_group", {"pk": sub_pk}),
                    approved_by="test-user",
                    idempotency_key="stock-catalog-delete-sub",
                    audit_path=audit_path,
                )
                delete_upper = operation_runtime.execute_approved_operation(
                    _prepare("stock.action_delete_upper_group", {"pk": upper_pk}),
                    approved_by="test-user",
                    idempotency_key="stock-catalog-delete-upper",
                    audit_path=audit_path,
                )
                audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
                stock_catalog._invalidate_catalog_cache()

        for name, result in (
            ("create_upper", create_upper),
            ("update_upper", update_upper),
            ("create_sub", create_sub),
            ("update_sub", update_sub),
            ("delete_sub", delete_sub),
            ("delete_upper", delete_upper),
        ):
            with self.subTest(operation=name):
                self.assertTrue(result.success, f"{name}: {result.message} | {result.data}")
                verify = (result.data or {}).get("verify") or {}
                self.assertTrue(verify.get("verified"), verify)
                self.assertEqual(verify.get("verified_by"), "catalog")
        for operation in (
            "stock.action_create_upper_group",
            "stock.action_update_upper_group",
            "stock.action_create_sub_group",
            "stock.action_update_sub_group",
            "stock.action_delete_sub_group",
            "stock.action_delete_upper_group",
        ):
            self.assertIn(f'"operation": "{operation}"', audit_text)

    def test_stock_brand_company_wrappers_execute_verify_and_audit(self) -> None:
        registry = available_tools()

        def _prepare(capability_id: str, payload: dict[str, Any]):
            prepared = registry["operations.manual_action.prepare"].handler(
                db_name=self.db_path,
                capability_id=capability_id,
                payload=payload,
                reason=f"{capability_id} stock finance-backed wrapper verify testi.",
            )
            self.assertTrue(prepared.success, prepared.message)
            action = (prepared.data or {}).get("action") or {}
            self.assertTrue(action.get("execute_enabled"), action)
            return action

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "stock-brand-company-audit.jsonl"
            create_brand = operation_runtime.execute_approved_operation(
                _prepare("stock.action_create_brand", {"name": "Agent Stock Marka", "code": "AG-STK-BRAND"}),
                approved_by="test-user",
                idempotency_key="stock-brand-create",
                audit_path=audit_path,
            )
            with Session(get_engine(self.db_path)) as session:
                brand = session.exec(select(Brand).where(Brand.name == "Agent Stock Marka")).one()
                brand_pk = int(brand.pk or 0)
            update_brand = operation_runtime.execute_approved_operation(
                _prepare("stock.action_update_brand", {"pk": brand_pk, "update_data": {"note": "Agent marka notu"}}),
                approved_by="test-user",
                idempotency_key="stock-brand-update",
                audit_path=audit_path,
            )
            delete_brand = operation_runtime.execute_approved_operation(
                _prepare("stock.action_delete_brand", {"pk": brand_pk}),
                approved_by="test-user",
                idempotency_key="stock-brand-delete",
                audit_path=audit_path,
            )
            create_company = operation_runtime.execute_approved_operation(
                _prepare("stock.action_create_company", {"name": "Agent Stock Sirket", "tax_no": "1234567890"}),
                approved_by="test-user",
                idempotency_key="stock-company-create",
                audit_path=audit_path,
            )
            with Session(get_engine(self.db_path)) as session:
                company = session.exec(select(Company).where(Company.name == "Agent Stock Sirket")).one()
                company_pk = int(company.pk or 0)
            update_company = operation_runtime.execute_approved_operation(
                _prepare("stock.action_update_company", {"pk": company_pk, "update_data": {"note": "Agent sirket notu"}}),
                approved_by="test-user",
                idempotency_key="stock-company-update",
                audit_path=audit_path,
            )
            delete_company = operation_runtime.execute_approved_operation(
                _prepare("stock.action_delete_company", {"pk": company_pk}),
                approved_by="test-user",
                idempotency_key="stock-company-delete",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        for name, result in (
            ("create_brand", create_brand),
            ("update_brand", update_brand),
            ("delete_brand", delete_brand),
            ("create_company", create_company),
            ("update_company", update_company),
            ("delete_company", delete_company),
        ):
            with self.subTest(operation=name):
                self.assertTrue(result.success, f"{name}: {result.message} | {result.data}")
                verify = (result.data or {}).get("verify") or {}
                self.assertTrue(verify.get("verified"), verify)
                self.assertEqual(verify.get("verified_by"), "db")
        with Session(get_engine(self.db_path)) as session:
            self.assertIsNone(session.get(Brand, brand_pk))
            self.assertIsNone(session.get(Company, company_pk))
        for operation in (
            "stock.action_create_brand",
            "stock.action_update_brand",
            "stock.action_delete_brand",
            "stock.action_create_company",
            "stock.action_update_company",
            "stock.action_delete_company",
        ):
            self.assertIn(f'"operation": "{operation}"', audit_text)

    def test_execute_approved_operation_dispatches_generic_manual_action_with_audit(self) -> None:
        registry = available_tools()
        prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="stock.action_create_warehouse",
            payload={"name": "Agent Depo", "code": "AGENT-WH"},
            reason="Agent depo karti olusturacak.",
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            # Execution and independent read-back must share the isolated DB;
            # patching only the writer leaves verification on the user's DB.
            with patch.object(operation_runtime, "DB_NAME", self.db_path), patch.object(
                operation_runtime.stock_pipeline, "DB_NAME", self.db_path
            ), patch.object(
                operation_runtime.stock_pipeline, "_ENGINE", None
            ), patch.object(operation_runtime.stock_pipeline, "_ENGINE_DB_NAME", None):
                result = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="test-user",
                    idempotency_key="manual-warehouse-test",
                    audit_path=audit_path,
                )
                second = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="test-user",
                    idempotency_key="manual-warehouse-test",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(result.success, result.message)
        self.assertTrue(second.success, second.message)
        self.assertTrue((second.data or {}).get("idempotent"))
        with Session(get_engine(self.db_path)) as session:
            row = session.exec(select(Warehouse).where(Warehouse.code == "AGENT-WH")).one()
            self.assertEqual(row.name, "Agent Depo")
        self.assertIn('"operation": "stock.action_create_warehouse"', audit_text)

    def test_execute_approved_operation_rejects_unknown_or_disabled_action(self) -> None:
        unknown = operation_runtime.execute_approved_operation(
            {
                "approval_required": True,
                "action_type": "unknown.action",
                "execute_enabled": True,
                "warnings": [],
            }
        )
        self.assertFalse(unknown.success)

        registry = available_tools()
        prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="stock.action_create_warehouse",
            payload={"name": "Disabled Depo"},
            reason="Execute flag kapali aksiyon calismamali.",
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        action["execute_enabled"] = False
        blocked = operation_runtime.execute_approved_operation(action)
        self.assertFalse(blocked.success)

        prepare_required = registry["operations.manual_action.prepare"].handler(
            capability_id="stock.action_create_warehouse",
            payload={"name": "Tamper Depo"},
            reason="Runtime eksik payload'i reddetmeli.",
        )
        self.assertTrue(prepare_required.success, prepare_required.message)
        tampered = dict((prepare_required.data or {}).get("action") or {})
        tampered["arguments"] = dict(tampered.get("arguments") or {})
        tampered["arguments"]["payload"] = {}
        tampered_execute = operation_runtime.execute_approved_operation(tampered)
        tampered_verify = operation_runtime.verify_approved_operation(tampered)
        self.assertFalse(tampered_execute.success)
        self.assertEqual((tampered_execute.data or {}).get("missing_parameters"), ["name"])
        self.assertFalse(tampered_verify.success)
        self.assertEqual((tampered_verify.data or {}).get("missing_parameters"), ["name"])

    def test_execute_approved_operation_runs_async_manual_action_through_runtime(self) -> None:
        from Finance.views import actions as finance_actions

        async def _fake_sync_finance_for_accounts(**kwargs):
            return Result.ok(
                "Async finans sync fake tamam.",
                close_dialog=False,
                data={
                    "received": dict(kwargs),
                    "counts": {"transactions": 1, "cargo_items": 0, "cargo_invoices": 0},
                    "db_counts": {"transactions": 1, "cargo_items": 0},
                    "changed": True,
                    "errors": [],
                    "job_count": 1,
                    "successful_job_count": 1,
                },
            )

        registry = available_tools()
        prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="finance.action_sync_finance_for_accounts",
            payload={"accounts": [{"seller_id": "123", "api_key": "api-key", "api_secret": "api-secret"}], "max_pages": 1},
            reason="Agent finans sync calistiracak.",
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(finance_actions, "action_sync_finance_for_accounts", _fake_sync_finance_for_accounts):
                result = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="test-user",
                    idempotency_key="async-finance-test",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(result.success, result.message)
        received = (((result.data or {}).get("result") or {}).get("received") or {})
        self.assertEqual(received.get("max_pages"), 1)
        self.assertEqual(((result.data or {}).get("verify") or {}).get("verified_by"), "result_db_counts")
        self.assertIn('"operation": "finance.action_sync_finance_for_accounts"', audit_text)

    def test_finance_sync_accounts_adapter_resolves_db_credentials_without_secret_audit(self) -> None:
        from Finance.views import actions as finance_actions

        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-finance",
                    comp_name="Finance Sync Seller",
                    platform="trendyol",
                    api_key="finance-sync-api-key",
                    api_secret="finance-sync-api-secret",
                )
            )
            session.commit()

        captured_accounts: list[dict[str, Any]] = []

        async def _fake_sync_finance_for_accounts(accounts, **kwargs):
            captured_accounts.extend([dict(row) for row in accounts])
            return Result.ok(
                "Finans sync fake DB yazdi.",
                close_dialog=False,
                data={
                    "counts": {"transactions": 2, "cargo_items": 1, "cargo_invoices": 0},
                    "db_counts": {"transactions": 2, "cargo_items": 1},
                    "changed": True,
                    "errors": [],
                    "account_summaries": [{"api_account_id": 1, "transactions": 2}],
                    "job_count": 1,
                    "successful_job_count": 1,
                    "kwargs": dict(kwargs),
                },
            )

        registry = available_tools()
        prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="finance.action_sync_finance_for_accounts",
            payload={"api_account_ids": [1], "db_name": self.db_path, "max_pages": 1},
            reason="Agent finans sync hesabi id ile calistiracak.",
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-sync-audit.jsonl"
            with patch.object(finance_actions, "action_sync_finance_for_accounts", _fake_sync_finance_for_accounts):
                result = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="finance-sync-test",
                    idempotency_key="finance-sync-api-account-id",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8")

        self.assertTrue(result.success, result.message)
        self.assertEqual(
            captured_accounts,
            [
                {
                    "pk": 1,
                    "api_key": "finance-sync-api-key",
                    "api_secret": "finance-sync-api-secret",
                    "seller_id": "seller-finance",
                    "comp_name": "Finance Sync Seller",
                }
            ],
        )
        self.assertEqual(((result.data or {}).get("verify") or {}).get("verified_by"), "result_db_counts")
        self.assertEqual(((result.data or {}).get("verify") or {}).get("db_counts"), {"transactions": 2, "cargo_items": 1})
        self.assertIn('"operation": "finance.action_sync_finance_for_accounts"', audit_text)
        self.assertNotIn("finance-sync-api-key", audit_text)
        self.assertNotIn("finance-sync-api-secret", audit_text)

    def test_finance_sync_accounts_adapter_preserves_stage_credential_reference_without_audit_leak(self) -> None:
        from Finance.views import actions as finance_actions

        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="2738",
                    comp_name="Stage Finance Seller",
                    platform="trendyol",
                    api_key="credential://marketplaces/finance-stage-test",
                    api_secret=None,
                    extra_config={"environment": "stage"},
                )
            )
            session.commit()

        captured_accounts: list[dict[str, Any]] = []

        async def _fake_sync_finance_for_accounts(accounts, **_kwargs):
            captured_accounts.extend([dict(row) for row in accounts])
            return Result.ok(
                "Stage finance sync fake DB read-back.",
                close_dialog=False,
                data={
                    "counts": {"transactions": 1, "cargo_items": 0, "cargo_invoices": 0},
                    "db_counts": {"transactions": 1, "cargo_items": 0},
                    "changed": True,
                    "errors": [],
                    "job_count": 1,
                    "successful_job_count": 1,
                },
            )

        registry = available_tools()
        prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="finance.action_sync_finance_for_accounts",
            payload={"api_account_ids": [1], "db_name": self.db_path, "max_pages": 1},
            reason="Stage finance account scope test.",
        )
        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-stage-sync-audit.jsonl"
            with patch.object(
                finance_actions,
                "action_sync_finance_for_accounts",
                _fake_sync_finance_for_accounts,
            ):
                result = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="finance-stage-test",
                    idempotency_key="finance-stage-account-scope",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8")

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(captured_accounts), 1)
        self.assertEqual(captured_accounts[0].get("seller_id"), "2738")
        self.assertEqual(
            captured_accounts[0].get("api_key"),
            "credential://marketplaces/finance-stage-test",
        )
        self.assertEqual(captured_accounts[0].get("api_secret"), "")
        self.assertEqual(
            captured_accounts[0].get("extra_config"),
            {"environment": "stage"},
        )
        self.assertNotIn("credential://marketplaces/finance-stage-test", audit_text)
        self.assertNotIn('"api_secret": "', audit_text)

    def test_execute_approved_operation_covers_ui_and_proxy_manual_adapters(self) -> None:
        from Account.processors import pipeline as account_pipeline
        from Finance.views import actions as finance_actions
        from Labels.processors import pipeline as labels_pipeline
        from Orders.processors.trendyol import pipeline as orders_pipeline

        async def _fake_sync_for_company_pks(selected_company_pks, **kwargs):
            return Result.ok(
                "Selected company sync fake tamam.",
                close_dialog=False,
                data={
                    "selected_company_pks": list(selected_company_pks),
                    "kwargs": dict(kwargs),
                    "counts": {"transactions": 1, "cargo_items": 0, "cargo_invoices": 0},
                    "db_counts": {"transactions": 1, "cargo_items": 0},
                    "changed": True,
                    "errors": [],
                    "job_count": 1,
                    "successful_job_count": 1,
                },
            )

        def _fake_label_from_orders(order_numbers, *, brand_code="TANEX", model_code="TANEX_2736"):
            return Result.ok(
                "Label fake tamam.",
                close_dialog=False,
                data={"order_numbers": list(order_numbers), "brand_code": brand_code, "model_code": model_code},
            )

        def _fake_save_return_claims(result, db_name=None):
            return Result.ok(
                "Return claims fake kaydedildi.",
                close_dialog=False,
                data={"rows": list((result.data or {}).get("return_claim_list") or []), "db_name": db_name},
            )

        async def _fake_fetch_orders_all(**kwargs):
            return Result.ok(
                "Orders fake cekildi.",
                close_dialog=False,
                data={"order_data_list": [{"orderNumber": "ORD-SYNC-1"}], "order_item_list": [], "kwargs": dict(kwargs)},
            )

        def _fake_save_orders(result, db_name=None):
            return Result.ok(
                "Orders fake kaydedildi.",
                close_dialog=False,
                data={"rows": list((result.data or {}).get("order_data_list") or []), "db_name": db_name},
            )

        def _fake_update_last_used(accounts, db_name=None, safety_minutes=0):
            _fake_update_last_used.calls.append(
                {"accounts": list(accounts or []), "db_name": db_name, "safety_minutes": safety_minutes}
            )

        _fake_update_last_used.calls = []

        registry = available_tools()
        with Session(get_engine(self.db_path)) as session:
            account = ApiAccount(
                account_id="agent-delete-account",
                comp_name="Agent Delete Firma",
                platform="trendyol",
                api_key="key",
                api_secret="secret",
            )
            session.add(account)
            last_used_account = ApiAccount(
                account_id="agent-last-used-account",
                comp_name="Agent Last Used Firma",
                platform="trendyol",
                api_key="api-key-last-used-adapter",
                api_secret="api-secret-last-used-adapter",
            )
            session.add(last_used_account)
            session.commit()
            account_pk = int(account.pk or 0)
            last_used_account_pk = int(last_used_account.pk or 0)

        account_delete_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="account.delete_company_and_refresh",
            payload={"pk": account_pk},
            reason="UI tablo refresh gerektiren firma silme aksiyonu agent payload ile calissin.",
        )
        finance_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="finance.action_sync_finance_for_selected_companies",
            payload={"selected_company_pks": [10, 20], "max_pages": 1},
            reason="UI secili sirket sync aksiyonu agent payload ile calissin.",
        )
        label_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="labels.action_create_labels_from_selected_orders",
            payload={"order_numbers": ["ORD-1", "ORD-2"], "brand_code": "TANEX", "model_code": "TANEX_2736"},
            reason="UI secili siparis label aksiyonu agent payload ile calissin.",
        )
        return_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="orders.save_return_claims_to_db",
            payload={"return_claim_list": [{"claimId": "CLAIM-1", "orderNumber": "ORD-1"}], "db_name": self.db_path},
            reason="Proxy iade kaydetme aksiyonu agent payload ile calissin.",
        )
        order_sync_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="orders.get_orders_from_companies",
            payload={
                "accounts": [[1, "api-key", "api-secret", "seller"]],
                "status_list": ["Created"],
                "start_ep_time": 1,
                "final_ep_time": 2,
                "db_name": self.db_path,
            },
            reason="UI secili sirket siparis sync aksiyonu agent payload ile calissin.",
        )
        last_used_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="orders.update_last_used_at_for_accounts",
            payload={"api_account_ids": [last_used_account_pk], "db_name": self.db_path, "safety_minutes": 5},
            reason="Siparis cekimi sonrasi hesap kullanim zamanini agent payload ile guncelle.",
        )

        for prepare in (account_delete_prepare, finance_prepare, label_prepare, return_prepare, order_sync_prepare, last_used_prepare):
            self.assertTrue(prepare.success, prepare.message)
            self.assertTrue(((prepare.data or {}).get("action") or {}).get("execute_enabled"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(account_pipeline, "DB_NAME", self.db_path), patch.object(
                finance_actions, "action_sync_finance_for_company_pks", _fake_sync_for_company_pks
            ), patch.object(
                labels_pipeline, "create_order_label_from_orders", _fake_label_from_orders
            ), patch.object(orders_pipeline, "save_return_claims_to_db", _fake_save_return_claims), patch.object(
                orders_pipeline, "fetch_orders_all", _fake_fetch_orders_all
            ), patch.object(
                orders_pipeline, "update_last_used_at_for_accounts", _fake_update_last_used
            ), patch.object(orders_pipeline, "save_orders_to_db", _fake_save_orders):
                account_delete_result = operation_runtime.execute_approved_operation(
                    (account_delete_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-account-delete",
                    audit_path=audit_path,
                )
                finance_result = operation_runtime.execute_approved_operation(
                    (finance_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-finance",
                    audit_path=audit_path,
                )
                label_result = operation_runtime.execute_approved_operation(
                    (label_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-label",
                    audit_path=audit_path,
                )
                label_idempotent_result = operation_runtime.execute_approved_operation(
                    (label_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-label",
                    audit_path=audit_path,
                )
                return_result = operation_runtime.execute_approved_operation(
                    (return_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-return",
                    audit_path=audit_path,
                )
                order_sync_result = operation_runtime.execute_approved_operation(
                    (order_sync_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-order-sync",
                    audit_path=audit_path,
                )
                last_used_result = operation_runtime.execute_approved_operation(
                    (last_used_prepare.data or {}).get("action") or {},
                    idempotency_key="adapter-last-used",
                    audit_path=audit_path,
                )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(account_delete_result.success, account_delete_result.message)
        with Session(get_engine(self.db_path)) as session:
            self.assertIsNone(session.get(ApiAccount, account_pk))
        self.assertTrue(finance_result.success, finance_result.message)
        self.assertEqual(((finance_result.data or {}).get("result") or {}).get("selected_company_pks"), [10, 20])
        self.assertTrue(label_result.success, label_result.message)
        self.assertEqual(((label_result.data or {}).get("result") or {}).get("order_numbers"), ["ORD-1", "ORD-2"])
        self.assertTrue(label_idempotent_result.success, label_idempotent_result.message)
        self.assertTrue((label_idempotent_result.data or {}).get("idempotent"))
        self.assertEqual(
            (label_idempotent_result.data or {}).get("verify"),
            (label_result.data or {}).get("verify"),
        )
        self.assertEqual(
            ((label_idempotent_result.data or {}).get("result") or {}).get("order_numbers"),
            ["ORD-1", "ORD-2"],
        )
        self.assertTrue(return_result.success, return_result.message)
        self.assertEqual(len(((return_result.data or {}).get("result") or {}).get("rows") or []), 1)
        self.assertTrue(order_sync_result.success, order_sync_result.message)
        self.assertEqual(len((((order_sync_result.data or {}).get("result") or {}).get("save") or {}).get("rows") or []), 1)
        self.assertTrue(last_used_result.success, last_used_result.message)
        # Fetch/save updates last-used once; the explicitly prepared last-used
        # capability is a second, independent operation.
        self.assertEqual(len(_fake_update_last_used.calls), 2)
        explicit_last_used_call = _fake_update_last_used.calls[1]
        self.assertEqual([row[0] for row in (explicit_last_used_call.get("accounts") or [])], [last_used_account_pk])
        self.assertEqual(explicit_last_used_call.get("db_name"), self.db_path)
        self.assertEqual(explicit_last_used_call.get("safety_minutes"), 5)
        self.assertIn('"operation": "account.delete_company_and_refresh"', audit_text)
        self.assertIn('"operation": "finance.action_sync_finance_for_selected_companies"', audit_text)
        self.assertIn('"operation": "labels.action_create_labels_from_selected_orders"', audit_text)
        self.assertIn('"operation": "orders.save_return_claims_to_db"', audit_text)
        self.assertIn('"operation": "orders.get_orders_from_companies"', audit_text)
        self.assertIn('"operation": "orders.update_last_used_at_for_accounts"', audit_text)
        self.assertNotIn("api-key-last-used-adapter", audit_text)
        self.assertNotIn("api-secret-last-used-adapter", audit_text)

    def test_marketplaces_manual_actions_execute_with_db_verify_and_audit(self) -> None:
        registry = available_tools()

        accept_prepare = registry["operations.manual_action.prepare"].handler(
            capability_id="marketplaces.accept_marketplace_record",
            payload={"code": "TRENDYOL", "db_name": self.db_path},
            reason="Agent Trendyol pazaryerini kullanima alacak.",
        )
        self.assertTrue(accept_prepare.success, accept_prepare.message)
        accept_action = (accept_prepare.data or {}).get("action") or {}
        self.assertTrue(accept_action.get("execute_enabled"), accept_action)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "marketplaces-audit.jsonl"
            accept_result = operation_runtime.execute_approved_operation(
                accept_action,
                approved_by="test-user",
                idempotency_key="marketplace-accept",
                audit_path=audit_path,
            )

            save_prepare = registry["operations.manual_action.prepare"].handler(
                capability_id="marketplaces.save_marketplace",
                payload={
                    "payload": {
                        "code": "TRENDYOL",
                        "label": "Trendyol Agentic",
                        "description": "Agentic verify kaydi",
                        "isActive": True,
                    },
                    "db_name": self.db_path,
                },
                reason="Agent kabul edilmis pazaryeri etiketini guncelleyecek.",
            )
            self.assertTrue(save_prepare.success, save_prepare.message)
            save_result = operation_runtime.execute_approved_operation(
                (save_prepare.data or {}).get("action") or {},
                approved_by="test-user",
                idempotency_key="marketplace-save",
                audit_path=audit_path,
            )

            inactive_prepare = registry["operations.manual_action.prepare"].handler(
                capability_id="marketplaces.set_marketplaces_active_state",
                payload={"codes": ["TRENDYOL"], "is_active": False, "db_name": self.db_path},
                reason="Agent pazaryerini pasif yapacak.",
            )
            self.assertTrue(inactive_prepare.success, inactive_prepare.message)
            inactive_result = operation_runtime.execute_approved_operation(
                (inactive_prepare.data or {}).get("action") or {},
                approved_by="test-user",
                idempotency_key="marketplace-inactive",
                audit_path=audit_path,
            )

            delete_prepare = registry["operations.manual_action.prepare"].handler(
                capability_id="marketplaces.delete_marketplace",
                payload={"code": "TRENDYOL", "db_name": self.db_path},
                reason="Agent test pazaryeri kaydini silecek.",
            )
            self.assertTrue(delete_prepare.success, delete_prepare.message)
            delete_result = operation_runtime.execute_approved_operation(
                (delete_prepare.data or {}).get("action") or {},
                approved_by="test-user",
                idempotency_key="marketplace-delete",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(accept_result.success, accept_result.message)
        self.assertEqual(((accept_result.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertTrue(save_result.success, save_result.message)
        save_verify = (save_result.data or {}).get("verify") or {}
        self.assertEqual(save_verify.get("verified_by"), "db")
        self.assertEqual(((save_verify.get("row") or {}).get("label")), "Trendyol Agentic")
        self.assertTrue(inactive_result.success, inactive_result.message)
        inactive_verify = (inactive_result.data or {}).get("verify") or {}
        self.assertEqual(inactive_verify.get("verified_by"), "db")
        self.assertEqual(inactive_verify.get("is_active"), False)
        self.assertTrue(delete_result.success, delete_result.message)
        self.assertEqual(((delete_result.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "marketplaces.accept_marketplace_record"', audit_text)
        self.assertIn('"operation": "marketplaces.save_marketplace"', audit_text)
        self.assertIn('"operation": "marketplaces.set_marketplaces_active_state"', audit_text)
        self.assertIn('"operation": "marketplaces.delete_marketplace"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)

    def test_finance_cost_item_prompt_prepares_executes_and_verifies_save_delete(self) -> None:
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        save_turn = run_agent_turn(
            "Trendyol icin Agent Finans Paketleme maliyet kalemini 12.5 TL tutarla kaydet",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"maliyet kalemi kaydet","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(save_turn.success, save_turn.message)
        self.assertEqual((save_turn.data or {}).get("mode"), "approval_required")
        save_tool_result = (save_turn.data or {}).get("tool_result") or {}
        self.assertEqual((save_tool_result.get("match") or {}).get("capability_id"), "finance.save_finance_cost_item")
        save_payload = save_tool_result.get("payload") or {}
        self.assertEqual(save_payload.get("db_name"), self.db_path)
        cost_payload = save_payload.get("cost_payload") or {}
        self.assertEqual(cost_payload.get("name"), "Agent Finans Paketleme")
        self.assertEqual(float(cost_payload.get("defaultAmount")), 12.5)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-cost-audit.jsonl"
            save_execute = operation_runtime.execute_approved_operation(
                save_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cost-save-agentic",
                audit_path=audit_path,
            )
            audit_text_after_save = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

            self.assertTrue(save_execute.success, save_execute.message)
            save_verify = (save_execute.data or {}).get("verify") or {}
            self.assertEqual(save_verify.get("verified_by"), "db")
            saved_row = save_verify.get("row") or {}
            item_pk = int(saved_row.get("pk") or 0)
            self.assertGreater(item_pk, 0)
            self.assertEqual(saved_row.get("name"), "Agent Finans Paketleme")
            self.assertEqual(float(saved_row.get("default_amount")), 12.5)
            self.assertIn('"operation": "finance.save_finance_cost_item"', audit_text_after_save)

            delete_turn = run_agent_turn(
                "Agent Finans Paketleme maliyet kalemini sil",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam sildim."}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            self.assertEqual((delete_turn.data or {}).get("mode"), "approval_required")
            delete_tool_result = (delete_turn.data or {}).get("tool_result") or {}
            self.assertEqual((delete_tool_result.get("match") or {}).get("capability_id"), "finance.delete_finance_cost_item")
            delete_payload = delete_tool_result.get("payload") or {}
            self.assertEqual(delete_payload.get("item_pk"), item_pk)
            self.assertEqual(delete_payload.get("db_name"), self.db_path)

            delete_execute = operation_runtime.execute_approved_operation(
                delete_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cost-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(delete_execute.success, delete_execute.message)
        self.assertEqual(((delete_execute.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "finance.delete_finance_cost_item"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            deleted_row = session.get(FinanceCostItem, item_pk)
            self.assertTrue(deleted_row is None or bool(getattr(deleted_row, "isDeleted", False)))

    def test_finance_cost_item_prompt_prepares_executes_accept_and_bulk_delete(self) -> None:
        from Finance.views.actions import save_finance_cost_item
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        accept_turn = run_agent_turn(
            "Komisyon bedeli maliyet kalemini kullanima al",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"maliyet kalemi kullanima al","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(accept_turn.success, accept_turn.message)
        self.assertEqual((accept_turn.data or {}).get("mode"), "approval_required")
        accept_tool_result = (accept_turn.data or {}).get("tool_result") or {}
        self.assertEqual((accept_tool_result.get("match") or {}).get("capability_id"), "finance.accept_finance_cost_item")
        accept_payload = accept_tool_result.get("payload") or {}
        self.assertGreater(int(accept_payload.get("item_pk") or 0), 0)
        self.assertEqual(accept_payload.get("db_name"), self.db_path)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-cost-accept-bulk-delete-audit.jsonl"
            accept_execute = operation_runtime.execute_approved_operation(
                accept_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cost-accept-agentic",
                audit_path=audit_path,
            )
            self.assertTrue(accept_execute.success, accept_execute.message)
            accept_verify = (accept_execute.data or {}).get("verify") or {}
            self.assertEqual(accept_verify.get("verified_by"), "db")
            accepted_row = accept_verify.get("row") or {}
            self.assertEqual(accepted_row.get("cost_key"), "komisyon")
            self.assertFalse(bool(accepted_row.get("is_deleted")))

            created_pks: list[int] = []
            for name, amount in (("Agent Bulk Paketleme A", 3.25), ("Agent Bulk Paketleme B", 4.75)):
                save_res = save_finance_cost_item(
                    {
                        "name": name,
                        "description": "Agentic bulk delete test",
                        "valueType": "numeric",
                        "defaultAmount": amount,
                        "currency": "TRY",
                        "supportedPlatforms": ["TRENDYOL"],
                        "isVatIncluded": True,
                        "vatRate": 20,
                        "isActive": True,
                    },
                    db_name=self.db_path,
                )
                self.assertTrue(save_res.success, save_res.message)
                created_pks.append(int(((save_res.data or {}).get("record") or {}).get("pk") or 0))
            self.assertEqual(len([pk for pk in created_pks if pk > 0]), 2)

            delete_turn = run_agent_turn(
                "Agent Bulk Paketleme maliyet kalemlerini toplu sil",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam sildim."}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            self.assertEqual((delete_turn.data or {}).get("mode"), "approval_required")
            delete_tool_result = (delete_turn.data or {}).get("tool_result") or {}
            self.assertEqual((delete_tool_result.get("match") or {}).get("capability_id"), "finance.delete_finance_cost_items")
            delete_payload = delete_tool_result.get("payload") or {}
            self.assertEqual(sorted(delete_payload.get("item_pks") or []), sorted(created_pks))
            self.assertEqual(delete_payload.get("db_name"), self.db_path)

            delete_execute = operation_runtime.execute_approved_operation(
                delete_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cost-bulk-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(delete_execute.success, delete_execute.message)
        self.assertEqual(((delete_execute.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "finance.accept_finance_cost_item"', audit_text)
        self.assertIn('"operation": "finance.delete_finance_cost_items"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            deleted_rows = [session.get(FinanceCostItem, pk) for pk in created_pks]
            self.assertTrue(all(row is None or bool(getattr(row, "isDeleted", False)) for row in deleted_rows))

    def test_finance_brand_company_prompts_prepare_execute_verify_crud(self) -> None:
        def _turn(query: str):
            result = run_agent_turn(
                query,
                planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"yanlis domain","limit":10}}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            self.assertEqual((result.data or {}).get("mode"), "approval_required")
            return (result.data or {}).get("tool_result") or {}

        brand_create = _turn("Agent Finans Marka adinda finans markasi olustur kodu AFM")
        self.assertEqual((brand_create.get("match") or {}).get("capability_id"), "finance.action_create_brand")
        self.assertEqual((brand_create.get("payload") or {}).get("name"), "Agent Finans Marka")
        self.assertEqual((brand_create.get("payload") or {}).get("code"), "AFM")

        company_create = _turn("Agent Finans Sirket adinda finans sirketi olustur vergi no 1234567890")
        self.assertEqual((company_create.get("match") or {}).get("capability_id"), "finance.action_create_company")
        self.assertEqual((company_create.get("payload") or {}).get("name"), "Agent Finans Sirket")
        self.assertEqual((company_create.get("payload") or {}).get("tax_no"), "1234567890")

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-brand-company-audit.jsonl"
            brand_create_exec = operation_runtime.execute_approved_operation(
                brand_create.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-brand-create-agentic",
                audit_path=audit_path,
            )
            company_create_exec = operation_runtime.execute_approved_operation(
                company_create.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-company-create-agentic",
                audit_path=audit_path,
            )
            self.assertTrue(brand_create_exec.success, brand_create_exec.message)
            self.assertEqual(((brand_create_exec.data or {}).get("verify") or {}).get("verified_by"), "db")
            self.assertTrue(company_create_exec.success, company_create_exec.message)
            self.assertEqual(((company_create_exec.data or {}).get("verify") or {}).get("verified_by"), "db")

            brand_row = ((brand_create_exec.data or {}).get("verify") or {}).get("row") or {}
            company_row = ((company_create_exec.data or {}).get("verify") or {}).get("row") or {}
            brand_pk = int(brand_row.get("pk") or 0)
            company_pk = int(company_row.get("pk") or 0)
            self.assertGreater(brand_pk, 0)
            self.assertGreater(company_pk, 0)

            brand_update = _turn("Agent Finans Marka finans markasinin notunu Brand guncel yap")
            self.assertEqual((brand_update.get("match") or {}).get("capability_id"), "finance.action_update_brand")
            self.assertEqual((brand_update.get("payload") or {}).get("pk"), brand_pk)
            self.assertEqual(((brand_update.get("payload") or {}).get("update_data") or {}).get("note"), "Brand guncel")

            company_update = _turn("Agent Finans Sirket finans sirketinin notunu Sirket guncel yap")
            self.assertEqual((company_update.get("match") or {}).get("capability_id"), "finance.action_update_company")
            self.assertEqual((company_update.get("payload") or {}).get("pk"), company_pk)
            self.assertEqual(((company_update.get("payload") or {}).get("update_data") or {}).get("note"), "Sirket guncel")

            brand_update_exec = operation_runtime.execute_approved_operation(
                brand_update.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-brand-update-agentic",
                audit_path=audit_path,
            )
            company_update_exec = operation_runtime.execute_approved_operation(
                company_update.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-company-update-agentic",
                audit_path=audit_path,
            )
            self.assertTrue(brand_update_exec.success, brand_update_exec.message)
            self.assertEqual(((brand_update_exec.data or {}).get("verify") or {}).get("verified_by"), "db")
            self.assertTrue(company_update_exec.success, company_update_exec.message)
            self.assertEqual(((company_update_exec.data or {}).get("verify") or {}).get("verified_by"), "db")

            brand_delete = _turn("Agent Finans Marka finans markasini sil")
            self.assertEqual((brand_delete.get("match") or {}).get("capability_id"), "finance.action_delete_brand")
            self.assertEqual((brand_delete.get("payload") or {}).get("pk"), brand_pk)

            company_delete = _turn("Agent Finans Sirket finans sirketini sil")
            self.assertEqual((company_delete.get("match") or {}).get("capability_id"), "finance.action_delete_company")
            self.assertEqual((company_delete.get("payload") or {}).get("pk"), company_pk)

            brand_delete_exec = operation_runtime.execute_approved_operation(
                brand_delete.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-brand-delete-agentic",
                audit_path=audit_path,
            )
            company_delete_exec = operation_runtime.execute_approved_operation(
                company_delete.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-company-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(brand_delete_exec.success, brand_delete_exec.message)
        self.assertEqual(((brand_delete_exec.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertTrue(company_delete_exec.success, company_delete_exec.message)
        self.assertEqual(((company_delete_exec.data or {}).get("verify") or {}).get("verified_by"), "db")
        for operation in (
            "finance.action_create_brand",
            "finance.action_update_brand",
            "finance.action_delete_brand",
            "finance.action_create_company",
            "finance.action_update_company",
            "finance.action_delete_company",
        ):
            self.assertIn(f'"operation": "{operation}"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            self.assertIsNone(session.get(Brand, brand_pk))
            self.assertIsNone(session.get(Company, company_pk))

    def test_finance_manual_transaction_prompt_prepares_executes_and_verifies_save_delete(self) -> None:
        save_turn = run_agent_turn(
            "Agent Ofis Kira giderini 2500 TL manuel finans hareketi olarak kaydet",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"manuel finans gideri kaydet","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(save_turn.success, save_turn.message)
        self.assertEqual((save_turn.data or {}).get("mode"), "approval_required")
        save_tool_result = (save_turn.data or {}).get("tool_result") or {}
        self.assertEqual((save_tool_result.get("match") or {}).get("capability_id"), "finance.save_manual_finance_transaction")
        save_payload = save_tool_result.get("payload") or {}
        self.assertEqual(save_payload.get("db_name"), self.db_path)
        tx_payload = save_payload.get("payload") or {}
        self.assertEqual(tx_payload.get("direction"), "expense")
        self.assertEqual(tx_payload.get("categoryName"), "Agent Ofis Kira")
        self.assertEqual(float(tx_payload.get("amount")), 2500.0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-manual-tx-audit.jsonl"
            save_execute = operation_runtime.execute_approved_operation(
                save_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-manual-tx-save-agentic",
                audit_path=audit_path,
            )
            audit_text_after_save = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

            self.assertTrue(save_execute.success, save_execute.message)
            save_verify = (save_execute.data or {}).get("verify") or {}
            self.assertEqual(save_verify.get("verified_by"), "db")
            saved_row = save_verify.get("row") or {}
            tx_pk = int(saved_row.get("pk") or 0)
            self.assertGreater(tx_pk, 0)
            self.assertEqual(saved_row.get("direction"), "expense")
            self.assertEqual(saved_row.get("category_name"), "Agent Ofis Kira")
            self.assertEqual(float(saved_row.get("amount")), 2500.0)
            self.assertIn('"operation": "finance.save_manual_finance_transaction"', audit_text_after_save)

            delete_turn = run_agent_turn(
                "Agent Ofis Kira manuel finans hareketini sil",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam sildim."}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            self.assertEqual((delete_turn.data or {}).get("mode"), "approval_required")
            delete_tool_result = (delete_turn.data or {}).get("tool_result") or {}
            self.assertEqual((delete_tool_result.get("match") or {}).get("capability_id"), "finance.delete_manual_finance_transaction")
            delete_payload = delete_tool_result.get("payload") or {}
            self.assertEqual(delete_payload.get("tx_pk"), tx_pk)
            self.assertEqual(delete_payload.get("db_name"), self.db_path)

            delete_execute = operation_runtime.execute_approved_operation(
                delete_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-manual-tx-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(delete_execute.success, delete_execute.message)
        self.assertEqual(((delete_execute.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "finance.delete_manual_finance_transaction"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            deleted_row = session.get(FinanceManualTransaction, tx_pk)
            self.assertIsNotNone(deleted_row)
            self.assertTrue(bool(getattr(deleted_row, "isDeleted", False)))

    def test_finance_invoice_document_prompt_prepares_executes_and_verifies_save_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            invoice_file = Path(tmp_dir) / "agent-invoice.pdf"
            invoice_file.write_bytes(b"%PDF-1.4\n%agent invoice\n")

            save_turn = run_agent_turn(
                f'INV-AGENT-0001 numarali 1250.5 TL gider faturasini "{invoice_file}" dosyasiyla kaydet',
                planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"fatura dokumani kaydet","limit":10}}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(save_turn.success, save_turn.message)
            self.assertEqual((save_turn.data or {}).get("mode"), "approval_required")
            save_tool_result = (save_turn.data or {}).get("tool_result") or {}
            self.assertEqual((save_tool_result.get("match") or {}).get("capability_id"), "finance.save_finance_invoice_document")
            save_payload = save_tool_result.get("payload") or {}
            self.assertEqual(save_payload.get("db_name"), self.db_path)
            invoice_payload = save_payload.get("payload") or {}
            self.assertEqual(invoice_payload.get("invoiceNumber"), "INV-AGENT-0001")
            self.assertEqual(invoice_payload.get("invoiceType"), "expense")
            self.assertEqual(float(invoice_payload.get("totalAmount")), 1250.5)
            self.assertEqual(Path(invoice_payload.get("filePath")).resolve(), invoice_file.resolve())

            audit_path = Path(tmp_dir) / "finance-invoice-audit.jsonl"
            save_execute = operation_runtime.execute_approved_operation(
                save_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-invoice-save-agentic",
                audit_path=audit_path,
            )
            audit_text_after_save = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

            self.assertTrue(save_execute.success, save_execute.message)
            save_verify = (save_execute.data or {}).get("verify") or {}
            self.assertEqual(save_verify.get("verified_by"), "db")
            saved_row = save_verify.get("row") or {}
            invoice_pk = int(saved_row.get("pk") or 0)
            self.assertGreater(invoice_pk, 0)
            self.assertEqual(saved_row.get("invoice_number"), "INV-AGENT-0001")
            self.assertEqual(saved_row.get("invoice_type"), "expense")
            self.assertEqual(float(saved_row.get("total_amount")), 1250.5)
            self.assertIn('"operation": "finance.save_finance_invoice_document"', audit_text_after_save)

            delete_turn = run_agent_turn(
                "INV-AGENT-0001 fatura dokumanini sil",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam sildim."}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            self.assertEqual((delete_turn.data or {}).get("mode"), "approval_required")
            delete_tool_result = (delete_turn.data or {}).get("tool_result") or {}
            self.assertEqual((delete_tool_result.get("match") or {}).get("capability_id"), "finance.delete_finance_invoice_document")
            delete_payload = delete_tool_result.get("payload") or {}
            self.assertEqual(delete_payload.get("invoice_pk"), invoice_pk)
            self.assertEqual(delete_payload.get("db_name"), self.db_path)

            delete_execute = operation_runtime.execute_approved_operation(
                delete_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-invoice-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(delete_execute.success, delete_execute.message)
        self.assertEqual(((delete_execute.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "finance.delete_finance_invoice_document"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            deleted_row = session.get(FinanceInvoiceDocument, invoice_pk)
            self.assertIsNotNone(deleted_row)
            self.assertTrue(bool(getattr(deleted_row, "isDeleted", False)))

    def test_finance_dashboard_transaction_invoice_read_prompts_execute_and_answer_with_records(self) -> None:
        from Finance.processors.trendyol.pipeline import save_finance_cargo_items_to_db, save_finance_transactions_to_db
        from Finance.views.actions import save_finance_invoice_document, save_manual_finance_transaction

        with Session(get_engine(self.db_path)) as session:
            account = ApiAccount(
                account_id="784195",
                comp_name="Agent Magaza",
                platform="trendyol",
                api_key="key",
                api_secret="secret",
                is_active=True,
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            account_pk = int(account.pk or 0)

        marketplace_res = save_finance_transactions_to_db(
            [
                {
                    "_finance_service": "settlements",
                    "_api_account_id": account_pk,
                    "_seller_id": "784195",
                    "id": "agent-dashboard-tx-1",
                    "transactionType": "Sale",
                    "description": "Agent Marketplace Satis",
                    "transactionDate": 1_700_000_000_000,
                    "credit": 300.0,
                    "debt": 0.0,
                    "currency": "TRY",
                },
                {
                    "_finance_service": "otherfinancials",
                    "_api_account_id": account_pk,
                    "_seller_id": "784195",
                    "id": "agent-cargo-tx-1",
                    "transactionType": "Kargo Fatura",
                    "description": "Agent Kargo Fatura",
                    "transactionDate": 1_700_000_100_000,
                    "debt": 42.75,
                    "credit": 0.0,
                    "commissionInvoiceSerialNumber": "DDF2026AGENTREAD001",
                    "currency": "TRY",
                },
            ],
            db_name=self.db_path,
        )
        self.assertTrue(marketplace_res.success, marketplace_res.message)
        cargo_items_res = save_finance_cargo_items_to_db(
            [
                {
                    "_api_account_id": account_pk,
                    "_seller_id": "784195",
                    "_invoice_serial_number": "DDF2026AGENTREAD001",
                    "parcelUniqueId": 555001,
                    "orderNumber": "11300000001",
                    "shipmentPackageType": "Box",
                    "amount": 42.75,
                    "desi": 3.0,
                }
            ],
            db_name=self.db_path,
        )
        self.assertTrue(cargo_items_res.success, cargo_items_res.message)
        manual_res = save_manual_finance_transaction(
            {
                "direction": "expense",
                "transactionDate": 1_700_000_200_000,
                "amount": 2500,
                "currency": "TRY",
                "categoryName": "Agent Ofis Kira",
                "description": "Agent Ofis Kira",
                "referenceNo": "KIRA-AGENT-READ",
            },
            db_name=self.db_path,
        )
        self.assertTrue(manual_res.success, manual_res.message)
        with tempfile.TemporaryDirectory() as tmp_dir:
            invoice_file = Path(tmp_dir) / "agent-read-invoice.pdf"
            invoice_file.write_bytes(b"%PDF-1.4\n%agent read invoice\n")
            invoice_res = save_finance_invoice_document(
                {
                    "invoiceNumber": "INV-AGENT-READ-0001",
                    "invoiceType": "expense",
                    "invoiceDate": 1_700_000_300_000,
                    "totalAmount": 1250.5,
                    "currency": "TRY",
                    "counterparty": "Agent Tedarikci",
                    "filePath": str(invoice_file),
                },
                db_name=self.db_path,
            )
            self.assertTrue(invoice_res.success, invoice_res.message)

            bad_planner = lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"yanlis domain","limit":10}}'
            chat_client = lambda _prompt: "Cloud cevabi."
            cases = [
                (
                    "manuel finans hareketlerini getir",
                    "finance.get_manual_finance_transactions_from_db",
                    "Agent Ofis Kira",
                    None,
                ),
                (
                    "Agent Ofis Kira finans hareketini goster",
                    "finance.load_finance_transactions_from_db",
                    "Agent Ofis Kira",
                    "Agent Ofis Kira",
                ),
                (
                    "fatura dokumanlarini listele",
                    "finance.load_finance_invoice_documents_from_db",
                    "INV-AGENT-READ-0001",
                    None,
                ),
                (
                    "INV-AGENT-READ-0001 fatura dokumanini goster",
                    "finance.load_finance_invoice_documents_from_db",
                    "Agent Tedarikci",
                    "INV-AGENT-READ-0001",
                ),
                (
                    "kargo faturalarini listele",
                    "finance.load_finance_cargo_invoices_from_db",
                    "DDF2026AGENTREAD001",
                    None,
                ),
                (
                    "finans dashboard panelini ver",
                    "finance.load_finance_dashboard_from_db",
                    "Kayit:",
                    None,
                ),
            ]
            for prompt, capability_id, expected_answer, expected_search in cases:
                with self.subTest(prompt=prompt):
                    turn = run_agent_turn(
                        prompt,
                        planner_client=bad_planner,
                        chat_client=chat_client,
                        db_name=self.db_path,
                    )
                    self.assertTrue(turn.success, turn.message)
                    data = turn.data or {}
                    self.assertEqual(data.get("mode"), "tool")
                    self.assertEqual(((data.get("tool_call") or {}).get("tool")), "operations.manual_action.read")
                    tool_result = data.get("tool_result") or {}
                    self.assertEqual((tool_result.get("capability") or {}).get("capability_id"), capability_id)
                    answer = data.get("answer") or ""
                    self.assertIn(expected_answer, answer)
                    self.assertNotIn("yanlis domain", answer)
                    payload = ((data.get("tool_call") or {}).get("arguments") or {}).get("payload") or {}
                    if expected_search is None:
                        self.assertNotIn("search_text", payload)
                    else:
                        self.assertEqual(payload.get("search_text"), expected_search)

    def test_finance_cargo_tariff_prompt_prepares_executes_and_verifies_save_delete(self) -> None:
        from Logistics.views.actions import accept_logistics_cargo_provider_record, load_logistics_cargo_providers
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)
        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(provider)
        provider_accept = accept_logistics_cargo_provider_record(dict(provider or {}), db_name=self.db_path)
        self.assertTrue(provider_accept.success, provider_accept.message)

        save_turn = run_agent_turn(
            "Agent Finans TEXMP 0-5 Desi isimli finans kargo tarifesini 54.9 TL olarak kaydet",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"kargo tarifesi kaydet","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(save_turn.success, save_turn.message)
        self.assertEqual((save_turn.data or {}).get("mode"), "approval_required")
        save_tool_result = (save_turn.data or {}).get("tool_result") or {}
        self.assertEqual((save_tool_result.get("match") or {}).get("capability_id"), "finance.save_finance_cargo_tariff")
        save_payload = save_tool_result.get("payload") or {}
        self.assertEqual(save_payload.get("db_name"), self.db_path)
        tariff_payload = save_payload.get("tariff_payload") or {}
        self.assertEqual(tariff_payload.get("name"), "Agent Finans TEXMP 0-5 Desi")
        self.assertEqual(tariff_payload.get("platformCode"), "TRENDYOL")
        self.assertEqual(tariff_payload.get("cargoProviderCode"), "TEXMP")
        self.assertEqual(float(tariff_payload.get("minDesi")), 0.0)
        self.assertEqual(float(tariff_payload.get("maxDesi")), 5.0)
        self.assertEqual(float(tariff_payload.get("amount")), 54.9)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-cargo-tariff-audit.jsonl"
            save_execute = operation_runtime.execute_approved_operation(
                save_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cargo-tariff-save-agentic",
                audit_path=audit_path,
            )
            audit_text_after_save = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

            self.assertTrue(save_execute.success, save_execute.message)
            save_verify = (save_execute.data or {}).get("verify") or {}
            self.assertEqual(save_verify.get("verified_by"), "db")
            saved_row = save_verify.get("row") or {}
            item_pk = int(saved_row.get("pk") or 0)
            self.assertGreater(item_pk, 0)
            self.assertEqual(saved_row.get("name"), "Agent Finans TEXMP 0-5 Desi")
            self.assertEqual(saved_row.get("cargo_provider_code"), "TEXMP")
            self.assertEqual(float(saved_row.get("amount")), 54.9)
            self.assertIn('"operation": "finance.save_finance_cargo_tariff"', audit_text_after_save)

            delete_turn = run_agent_turn(
                "Agent Finans TEXMP 0-5 Desi finans kargo tarifesini sil",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam sildim."}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            self.assertEqual((delete_turn.data or {}).get("mode"), "approval_required")
            delete_tool_result = (delete_turn.data or {}).get("tool_result") or {}
            self.assertEqual((delete_tool_result.get("match") or {}).get("capability_id"), "finance.delete_finance_cargo_tariff")
            delete_payload = delete_tool_result.get("payload") or {}
            self.assertEqual(delete_payload.get("item_pk"), item_pk)
            self.assertEqual(delete_payload.get("db_name"), self.db_path)

            delete_execute = operation_runtime.execute_approved_operation(
                delete_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cargo-tariff-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(delete_execute.success, delete_execute.message)
        self.assertEqual(((delete_execute.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "finance.delete_finance_cargo_tariff"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            deleted_row = session.get(LogisticsCargoTariff, item_pk)
            self.assertIsNotNone(deleted_row)
            self.assertTrue(bool(getattr(deleted_row, "isDeleted", False)))

    def test_finance_cargo_tariff_prompt_prepares_executes_accept_and_bulk_delete(self) -> None:
        from Finance.views.actions import accept_finance_cargo_tariff, load_finance_cargo_tariffs
        from Logistics.views.actions import accept_logistics_cargo_provider_record, load_logistics_cargo_providers
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)
        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(provider)
        provider_accept = accept_logistics_cargo_provider_record(dict(provider or {}), db_name=self.db_path)
        self.assertTrue(provider_accept.success, provider_accept.message)

        pending = load_finance_cargo_tariffs(db_name=self.db_path, source_state="pending")
        self.assertTrue(pending.success, pending.message)
        pending_rows = list((pending.data or {}).get("records") or [])
        zero_desi = next(row for row in pending_rows if row.get("cargoProviderCode") == "TEXMP" and row.get("name") == "Trendyol Trendyol Express 0 Desi")
        one_desi = next(row for row in pending_rows if row.get("cargoProviderCode") == "TEXMP" and row.get("name") == "Trendyol Trendyol Express 1 Desi")

        accept_turn = run_agent_turn(
            "Trendyol Express 0 Desi finans kargo tarifesini kullanima al",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"kargo tarifesi kullanima al","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(accept_turn.success, accept_turn.message)
        self.assertEqual((accept_turn.data or {}).get("mode"), "approval_required")
        accept_tool_result = (accept_turn.data or {}).get("tool_result") or {}
        self.assertEqual((accept_tool_result.get("match") or {}).get("capability_id"), "finance.accept_finance_cargo_tariff")
        accept_payload = accept_tool_result.get("payload") or {}
        self.assertEqual(accept_payload.get("item_pk"), zero_desi.get("pk"))
        self.assertEqual(accept_payload.get("db_name"), self.db_path)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-cargo-tariff-accept-bulk-delete-audit.jsonl"
            accept_execute = operation_runtime.execute_approved_operation(
                accept_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cargo-tariff-accept-agentic",
                audit_path=audit_path,
            )
            self.assertTrue(accept_execute.success, accept_execute.message)
            accept_verify = (accept_execute.data or {}).get("verify") or {}
            self.assertEqual(accept_verify.get("verified_by"), "db")
            accepted_row = accept_verify.get("row") or {}
            zero_pk = int(accepted_row.get("pk") or 0)
            self.assertGreater(zero_pk, 0)
            self.assertEqual(accepted_row.get("cargo_provider_code"), "TEXMP")
            self.assertFalse(bool(accepted_row.get("is_deleted")))

            second_accept = accept_finance_cargo_tariff(int(one_desi.get("pk") or 0), db_name=self.db_path)
            self.assertTrue(second_accept.success, second_accept.message)
            second_pk = int(((second_accept.data or {}).get("record") or {}).get("pk") or 0)
            self.assertGreater(second_pk, 0)

            delete_turn = run_agent_turn(
                "Trendyol Express 0 Desi ve Trendyol Express 1 Desi finans kargo tarifelerini toplu sil",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam sildim."}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            self.assertEqual((delete_turn.data or {}).get("mode"), "approval_required")
            delete_tool_result = (delete_turn.data or {}).get("tool_result") or {}
            self.assertEqual((delete_tool_result.get("match") or {}).get("capability_id"), "finance.delete_finance_cargo_tariffs")
            delete_payload = delete_tool_result.get("payload") or {}
            self.assertEqual(sorted(delete_payload.get("item_pks") or []), sorted([zero_pk, second_pk]))
            self.assertEqual(delete_payload.get("db_name"), self.db_path)

            delete_execute = operation_runtime.execute_approved_operation(
                delete_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cargo-tariff-bulk-delete-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(delete_execute.success, delete_execute.message)
        self.assertEqual(((delete_execute.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertIn('"operation": "finance.accept_finance_cargo_tariff"', audit_text)
        self.assertIn('"operation": "finance.delete_finance_cargo_tariffs"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            deleted_rows = [session.get(LogisticsCargoTariff, pk) for pk in (zero_pk, second_pk)]
            self.assertTrue(all(row is not None and bool(getattr(row, "isDeleted", False)) for row in deleted_rows))

    def test_finance_cargo_tariff_prompt_prepares_executes_bulk_accept(self) -> None:
        from Finance.views.actions import load_finance_cargo_tariffs
        from Logistics.views.actions import accept_logistics_cargo_provider_record, load_logistics_cargo_providers
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)
        provider_rows = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=self.db_path)
        self.assertTrue(provider_rows.success, provider_rows.message)
        provider = next(
            (
                row
                for row in list((provider_rows.data or {}).get("records") or [])
                if str(row.get("cargoProviderCode") or "") == "TEXMP"
            ),
            None,
        )
        self.assertIsNotNone(provider)
        provider_accept = accept_logistics_cargo_provider_record(dict(provider or {}), db_name=self.db_path)
        self.assertTrue(provider_accept.success, provider_accept.message)

        pending = load_finance_cargo_tariffs(db_name=self.db_path, source_state="pending")
        self.assertTrue(pending.success, pending.message)
        pending_rows = list((pending.data or {}).get("records") or [])
        zero_desi = next(row for row in pending_rows if row.get("cargoProviderCode") == "TEXMP" and row.get("name") == "Trendyol Trendyol Express 0 Desi")
        one_desi = next(row for row in pending_rows if row.get("cargoProviderCode") == "TEXMP" and row.get("name") == "Trendyol Trendyol Express 1 Desi")
        requested_pks = [int(zero_desi.get("pk") or 0), int(one_desi.get("pk") or 0)]
        self.assertEqual(len([pk for pk in requested_pks if pk > 0]), 2)

        accept_turn = run_agent_turn(
            "Trendyol Express ilk 2 finans kargo tarifelerini toplu kullanima al",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"kargo tarifelerini kullanima al","limit":10}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(accept_turn.success, accept_turn.message)
        self.assertEqual((accept_turn.data or {}).get("mode"), "approval_required")
        accept_tool_result = (accept_turn.data or {}).get("tool_result") or {}
        self.assertEqual((accept_tool_result.get("match") or {}).get("capability_id"), "finance.accept_finance_cargo_tariffs")
        accept_payload = accept_tool_result.get("payload") or {}
        self.assertEqual(sorted(accept_payload.get("item_pks") or []), sorted(requested_pks))
        self.assertEqual(accept_payload.get("db_name"), self.db_path)

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "finance-cargo-tariff-bulk-accept-audit.jsonl"
            accept_execute = operation_runtime.execute_approved_operation(
                accept_tool_result.get("action") or {},
                approved_by="test-user",
                idempotency_key="finance-cargo-tariff-bulk-accept-agentic",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(accept_execute.success, accept_execute.message)
        verify = (accept_execute.data or {}).get("verify") or {}
        self.assertEqual(verify.get("verified_by"), "db")
        self.assertEqual(sorted(verify.get("item_pks") or []), sorted(requested_pks))
        self.assertIn('"operation": "finance.accept_finance_cargo_tariffs"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)
        with Session(get_engine(self.db_path)) as session:
            accepted_rows = [session.get(LogisticsCargoTariff, pk) for pk in requested_pks]
            self.assertTrue(all(row is not None and not bool(getattr(row, "isDeleted", False)) for row in accepted_rows))
            self.assertTrue(all(row is not None and bool(getattr(row, "isActive", True)) for row in accepted_rows))

    def test_logistics_provider_catalog_question_uses_logistics_records_and_visible_answer(self) -> None:
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        result = run_agent_turn(
            "Trendyol kargo firmalarini listele",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.cargo_provider_options","arguments":{}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(((data.get("tool_call") or {}).get("tool")), "logistics.provider_catalog")
        self.assertEqual((((data.get("tool_call") or {}).get("arguments") or {}).get("platform_code")), "TRENDYOL")
        self.assertEqual((((data.get("tool_call") or {}).get("arguments") or {}).get("query")), "")
        answer = str(data.get("answer") or "")
        self.assertIn("kargo firma kaydi", answer)
        self.assertIn("TEXMP", answer)
        self.assertNotEqual(answer, "Cloud cevabi.")

    def test_logistics_capability_help_does_not_degrade_to_order_lookup_or_orders_help(self) -> None:
        bad_planner = lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"lojistikte neler yapabiliyorsun","limit":10}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        for prompt in (
            "lojistik tarafinda hangi islemleri yapabiliyorsun",
            "kargo tarafinda neler yapabiliriz",
            "Trendyol Express tarifeleriyle ilgili neler yapabilirsin",
            "kargo firmalari ve tarifeler icin bana secenekleri anlat",
        ):
            result = run_agent_turn(
                prompt,
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )

            self.assertTrue(result.success, result.message)
            data = result.data or {}
            self.assertEqual(data.get("mode"), "answer", prompt)
            self.assertIsNone(data.get("tool_call"), prompt)
            answer = str(data.get("answer") or "")
            self.assertIn("Kargo/lojistik tarafinda", answer, prompt)
            self.assertIn("tarife", answer, prompt)
            self.assertIn("kargo firma", answer, prompt)
            self.assertNotIn("Siparisler tarafinda", answer, prompt)
            self.assertNotEqual(answer, "Cloud cevabi.", prompt)

    def test_logistics_tariff_read_summary_records_and_count_do_not_degrade_to_order_lookup(self) -> None:
        bad_planner = lambda _prompt: '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"kargo tarifeleri","limit":10}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        cases = [
            ("kargo tarifelerimi ozetle", ["logistics.profile"], ("aktif kargo tarifesi", "kargo firmasi")),
            ("aktif kargo tarife sayisi kac", ["logistics.tariff_count"], ("aktif kargo tarifesi", "kargo firmasi")),
            ("kargo tarife kayitlarini listele", ["logistics.tariff_lookup"], ("kargo tarifesi",)),
            ("Kargo tarifelerimi goster", ["logistics.tariff_count"], ("aktif kargo tarifesi",)),
            (
                "kargo tarife kayitlari ve ozetini goster",
                ["logistics.profile", "logistics.tariff_lookup"],
                ("aktif kargo tarifesi", "kargo tarifesi"),
            ),
        ]

        for prompt, expected_tools, answer_fragments in cases:
            result = run_agent_turn(
                prompt,
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )

            self.assertTrue(result.success, result.message)
            data = result.data or {}
            actual_tools = [str(row.get("tool")) for row in (data.get("tool_calls") or [])]
            self.assertEqual(actual_tools, expected_tools, prompt)
            answer = str(data.get("answer") or "")
            for fragment in answer_fragments:
                self.assertIn(fragment, answer, prompt)
            self.assertNotIn("siparis buldum", answer, prompt)
            self.assertNotEqual(answer, "Cloud cevabi.", prompt)

    def test_logistics_provider_manual_actions_execute_with_db_verify_and_audit(self) -> None:
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)

        bad_planner = lambda _prompt: '{"mode":"tool","tool":"logistics.tariff_count","arguments":{}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "logistics-provider-audit.jsonl"

            accept_turn = run_agent_turn(
                "Trendyol Express kargo firmasini kullanima al",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(accept_turn.success, accept_turn.message)
            accept_action = (accept_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(accept_action.get("action_type"), "logistics.accept_logistics_cargo_provider_record")
            accept_payload = ((accept_action.get("arguments") or {}).get("payload") or {}).get("provider_payload") or {}
            self.assertEqual(accept_payload.get("cargoProviderCode"), "TEXMP")
            accept_result = operation_runtime.execute_approved_operation(
                accept_action,
                approved_by="test-user",
                idempotency_key="logistics-provider-accept",
                audit_path=audit_path,
            )

            save_turn = run_agent_turn(
                "Trendyol icin Agent Kargo adinda kargo firmasi kaydet kodu AGENTKARGO",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(save_turn.success, save_turn.message)
            save_action = (save_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(save_action.get("action_type"), "logistics.save_logistics_cargo_provider_record")
            save_payload = ((save_action.get("arguments") or {}).get("payload") or {}).get("provider_payload") or {}
            self.assertEqual(save_payload.get("cargoProviderCode"), "AGENTKARGO")
            self.assertEqual(save_payload.get("cargoProviderName"), "Agent Kargo")
            save_result = operation_runtime.execute_approved_operation(
                save_action,
                approved_by="test-user",
                idempotency_key="logistics-provider-save",
                audit_path=audit_path,
            )

            delete_turn = run_agent_turn(
                "Agent Kargo kargo firmasini sil",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            delete_action = (delete_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(delete_action.get("action_type"), "logistics.delete_logistics_cargo_provider_record")
            delete_payload = ((delete_action.get("arguments") or {}).get("payload") or {}).get("provider_payload") or {}
            self.assertEqual(delete_payload.get("cargoProviderCode"), "AGENTKARGO")
            self.assertTrue(delete_payload.get("pk") or delete_payload.get("dbPk"))
            delete_result = operation_runtime.execute_approved_operation(
                delete_action,
                approved_by="test-user",
                idempotency_key="logistics-provider-delete",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(accept_result.success, accept_result.message)
        self.assertEqual(((accept_result.data or {}).get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((accept_result.data or {}).get("verify") or {}).get("cargo_provider_code"), "TEXMP")
        self.assertTrue(save_result.success, save_result.message)
        save_verify = (save_result.data or {}).get("verify") or {}
        self.assertEqual(save_verify.get("verified_by"), "db")
        self.assertEqual(((save_verify.get("row") or {}).get("cargo_provider_name")), "Agent Kargo")
        self.assertTrue(delete_result.success, delete_result.message)
        delete_verify = (delete_result.data or {}).get("verify") or {}
        self.assertEqual(delete_verify.get("verified_by"), "db")
        self.assertEqual(delete_verify.get("cargo_provider_code"), "AGENTKARGO")
        self.assertIn('"operation": "logistics.accept_logistics_cargo_provider_record"', audit_text)
        self.assertIn('"operation": "logistics.save_logistics_cargo_provider_record"', audit_text)
        self.assertIn('"operation": "logistics.delete_logistics_cargo_provider_record"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)

    def test_logistics_tariff_manual_actions_execute_with_db_verify_and_audit(self) -> None:
        from Logistics.views.actions import (
            accept_logistics_cargo_provider_record,
            load_logistics_cargo_providers,
            load_logistics_cargo_tariffs,
        )
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)
        provider_rows = (
            load_logistics_cargo_providers(
                platform_code="TRENDYOL",
                search="TEXMP",
                source_filter="pending",
                db_name=self.db_path,
            ).data
            or {}
        ).get("records") or []
        self.assertTrue(provider_rows)
        provider_accept = accept_logistics_cargo_provider_record(dict(provider_rows[0]), db_name=self.db_path)
        self.assertTrue(provider_accept.success, provider_accept.message)

        bad_planner = lambda _prompt: '{"mode":"tool","tool":"logistics.tariff_count","arguments":{}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "logistics-tariff-audit.jsonl"

            save_turn = run_agent_turn(
                "Trendyol icin Agent Tarife adinda kargo tarife kaydet, Trendyol Express, 0-1 desi, 44.5 TL, onay hazirla",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(save_turn.success, save_turn.message)
            save_action = (save_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(save_action.get("action_type"), "logistics.save_logistics_cargo_tariff")
            save_payload = ((save_action.get("arguments") or {}).get("payload") or {}).get("tariff_payload") or {}
            self.assertEqual(save_payload.get("name"), "Agent Tarife")
            self.assertEqual(save_payload.get("cargoProviderCode"), "TEXMP")
            self.assertEqual(float(save_payload.get("amount") or 0), 44.5)
            save_result = operation_runtime.execute_approved_operation(
                save_action,
                approved_by="test-user",
                idempotency_key="logistics-tariff-save",
                audit_path=audit_path,
            )

            delete_turn = run_agent_turn(
                "Agent Tarife kargo tarifesini sil, onay hazirla",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            delete_action = (delete_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(delete_action.get("action_type"), "logistics.delete_logistics_cargo_tariff")
            self.assertTrue(((delete_action.get("arguments") or {}).get("payload") or {}).get("item_pk"))
            delete_result = operation_runtime.execute_approved_operation(
                delete_action,
                approved_by="test-user",
                idempotency_key="logistics-tariff-delete",
                audit_path=audit_path,
            )

            accept_turn = run_agent_turn(
                "Trendyol Express 0 Desi kargo tarifesini kullanima al, onay hazirla",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(accept_turn.success, accept_turn.message)
            accept_action = (accept_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(accept_action.get("action_type"), "logistics.accept_logistics_cargo_tariff")
            self.assertTrue(((accept_action.get("arguments") or {}).get("payload") or {}).get("item_pk"))
            accept_result = operation_runtime.execute_approved_operation(
                accept_action,
                approved_by="test-user",
                idempotency_key="logistics-tariff-accept",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(save_result.success, save_result.message)
        save_verify = (save_result.data or {}).get("verify") or {}
        self.assertEqual(save_verify.get("verified_by"), "db")
        self.assertEqual(save_verify.get("name"), "Agent Tarife")
        self.assertTrue(delete_result.success, delete_result.message)
        self.assertEqual(((delete_result.data or {}).get("verify") or {}).get("verified_by"), "db")
        after_delete = load_logistics_cargo_tariffs(search_text="Agent Tarife", db_name=self.db_path)
        self.assertTrue(after_delete.success, after_delete.message)
        self.assertEqual((after_delete.data or {}).get("records") or [], [])
        self.assertTrue(accept_result.success, accept_result.message)
        accept_verify = (accept_result.data or {}).get("verify") or {}
        self.assertEqual(accept_verify.get("verified_by"), "db")
        self.assertIn("Trendyol Express 0 Desi", str(accept_verify.get("name") or ""))
        self.assertIn('"operation": "logistics.save_logistics_cargo_tariff"', audit_text)
        self.assertIn('"operation": "logistics.delete_logistics_cargo_tariff"', audit_text)
        self.assertIn('"operation": "logistics.accept_logistics_cargo_tariff"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)

    def test_logistics_bulk_tariff_manual_actions_execute_with_db_verify_and_audit(self) -> None:
        from Logistics.views.actions import (
            accept_logistics_cargo_provider_record,
            load_logistics_cargo_providers,
            load_logistics_cargo_tariffs,
        )
        from Marketplaces.views.actions import accept_marketplace_record

        accepted = accept_marketplace_record(code="TRENDYOL", db_name=self.db_path)
        self.assertTrue(accepted.success, accepted.message)
        provider_rows = (
            load_logistics_cargo_providers(
                platform_code="TRENDYOL",
                search="TEXMP",
                source_filter="pending",
                db_name=self.db_path,
            ).data
            or {}
        ).get("records") or []
        self.assertTrue(provider_rows)
        provider_accept = accept_logistics_cargo_provider_record(dict(provider_rows[0]), db_name=self.db_path)
        self.assertTrue(provider_accept.success, provider_accept.message)

        bad_planner = lambda _prompt: '{"mode":"tool","tool":"logistics.tariff_count","arguments":{}}'
        bad_chat = lambda _prompt: "Cloud cevabi."

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "logistics-bulk-tariff-audit.jsonl"

            accept_turn = run_agent_turn(
                "Trendyol Express ilk 2 kargo tarifelerini kullanima al, onay hazirla",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(accept_turn.success, accept_turn.message)
            accept_action = (accept_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(accept_action.get("action_type"), "logistics.accept_logistics_cargo_tariffs")
            accept_pks = ((accept_action.get("arguments") or {}).get("payload") or {}).get("item_pks") or []
            self.assertEqual(len(accept_pks), 2)
            accept_result = operation_runtime.execute_approved_operation(
                accept_action,
                approved_by="test-user",
                idempotency_key="logistics-bulk-tariff-accept",
                audit_path=audit_path,
            )

            for index, prompt in enumerate(
                (
                    "Trendyol icin Bulk Tarife 1 adinda kargo tarife kaydet, Trendyol Express, 0-1 desi, 11.11 TL, onay hazirla",
                    "Trendyol icin Bulk Tarife 2 adinda kargo tarife kaydet, Trendyol Express, 1-2 desi, 22.22 TL, onay hazirla",
                ),
                start=1,
            ):
                save_turn = run_agent_turn(
                    prompt,
                    planner_client=bad_planner,
                    chat_client=bad_chat,
                    db_name=self.db_path,
                )
                self.assertTrue(save_turn.success, save_turn.message)
                save_action = (save_turn.data or {}).get("action_proposal") or {}
                self.assertEqual(save_action.get("action_type"), "logistics.save_logistics_cargo_tariff")
                save_result = operation_runtime.execute_approved_operation(
                    save_action,
                    approved_by="test-user",
                    idempotency_key=f"logistics-bulk-tariff-save-{index}",
                    audit_path=audit_path,
                )
                self.assertTrue(save_result.success, save_result.message)
                self.assertEqual(((save_result.data or {}).get("verify") or {}).get("verified_by"), "db")

            before_delete = load_logistics_cargo_tariffs(search_text="Bulk Tarife", source_state="saved", db_name=self.db_path)
            self.assertTrue(before_delete.success, before_delete.message)
            self.assertEqual(len((before_delete.data or {}).get("records") or []), 2)

            delete_turn = run_agent_turn(
                "Bulk Tarife kargo tarifelerini sil, onay hazirla",
                planner_client=bad_planner,
                chat_client=bad_chat,
                db_name=self.db_path,
            )
            self.assertTrue(delete_turn.success, delete_turn.message)
            delete_action = (delete_turn.data or {}).get("action_proposal") or {}
            self.assertEqual(delete_action.get("action_type"), "logistics.delete_logistics_cargo_tariffs")
            delete_pks = ((delete_action.get("arguments") or {}).get("payload") or {}).get("item_pks") or []
            self.assertEqual(len(delete_pks), 2)
            delete_result = operation_runtime.execute_approved_operation(
                delete_action,
                approved_by="test-user",
                idempotency_key="logistics-bulk-tariff-delete",
                audit_path=audit_path,
            )
            audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

        self.assertTrue(accept_result.success, accept_result.message)
        accept_verify = (accept_result.data or {}).get("verify") or {}
        self.assertEqual(accept_verify.get("verified_by"), "db")
        self.assertEqual(accept_verify.get("tariff_pks"), accept_pks)
        self.assertTrue(delete_result.success, delete_result.message)
        delete_verify = (delete_result.data or {}).get("verify") or {}
        self.assertEqual(delete_verify.get("verified_by"), "db")
        self.assertEqual(delete_verify.get("tariff_pks"), delete_pks)
        after_delete = load_logistics_cargo_tariffs(search_text="Bulk Tarife", source_state="saved", db_name=self.db_path)
        self.assertTrue(after_delete.success, after_delete.message)
        self.assertEqual((after_delete.data or {}).get("records") or [], [])
        self.assertIn('"operation": "logistics.accept_logistics_cargo_tariffs"', audit_text)
        self.assertIn('"operation": "logistics.delete_logistics_cargo_tariffs"', audit_text)
        self.assertIn('"verified_by": "db"', audit_text)

    def test_order_cargo_provider_prepare_and_execute_wraps_manual_function(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-cargo",
                    comp_name="Cargo Test Seller",
                    platform="trendyol",
                    api_key="api-key",
                    api_secret="api-secret",
                )
            )
            session.add(OrderHeader(orderNumber="ORD-CARGO-1", api_account_id=1))
            session.add(
                OrderData(
                    orderNumber="ORD-CARGO-1",
                    id=987654,
                    shipmentPackageId=987654,
                    api_account_id=1,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    shipmentPackageStatus="ReadyToShip",
                    cargoProviderName="Aras Kargo",
                    cargoTrackingNumber="TRK-CARGO-1",
                )
            )
            session.commit()

        registry = available_tools()
        prepare = registry["orders.change_cargo_provider.prepare"].handler(
            db_name=self.db_path,
            query="ORD-CARGO-1",
            cargo_provider="Yurtici",
        )

        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)
        self.assertTrue(action.get("external_write"))
        self.assertEqual(action.get("action_type"), "orders.change_order_cargo_provider")
        self.assertEqual(((action.get("rows") or [])[0].get("payload") or {}).get("cargo_provider_code"), "YKMP")

        routed = run_agent_turn(
            "ORD-CARGO-1 siparisinin kargosunu Yurtici yap",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"operations.manual_action.route","arguments":{"query":"kargo degistir","mode":"write"}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )
        self.assertTrue(routed.success, routed.message)
        self.assertEqual(((routed.data or {}).get("tool_call") or {}).get("tool"), "orders.change_cargo_provider.prepare")
        self.assertTrue((routed.data or {}).get("approval_required"))

        from Orders.views import actions as orders_actions

        calls: list[dict[str, str]] = []

        def _fake_change_order_cargo_provider(order, *, cargo_provider_code: str) -> Result:
            expected_provider = str(((action.get("rows") or [{}])[0].get("after") or {}).get("cargo_provider") or "").strip()
            with Session(get_engine(self.db_path)) as session:
                record = session.exec(select(OrderData).where(OrderData.orderNumber == "ORD-CARGO-1")).first()
                if record is not None:
                    record.cargoProviderName = expected_provider or "Yurtici Kargo Marketplace"
                    session.add(record)
                    session.commit()
            calls.append(
                {
                    "order_number": str(getattr(order, "orderNumber", "")),
                    "package_id": str(getattr(order, "id", "")),
                    "api_account": str(getattr(getattr(order, "api_account", None), "account_id", "")),
                    "cargo_provider_code": cargo_provider_code,
                }
            )
            return Result.ok(
                "Cargo fake guncellendi.",
                close_dialog=False,
                data={"package_id": getattr(order, "id", None), "cargo_provider_code": cargo_provider_code},
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(orders_actions, "change_order_cargo_provider", _fake_change_order_cargo_provider):
                executed = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="tester",
                    idempotency_key="cargo-provider-change",
                    audit_path=audit_path,
                )
                second = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="tester",
                    idempotency_key="cargo-provider-change",
                    audit_path=audit_path,
                )

            self.assertTrue(executed.success, executed.message)
            self.assertTrue(second.success, second.message)
            self.assertTrue((second.data or {}).get("idempotent"))
            self.assertEqual(
                calls,
                [
                    {
                        "order_number": "ORD-CARGO-1",
                        "package_id": "987654",
                        "api_account": "seller-cargo",
                        "cargo_provider_code": "YKMP",
                    }
                ],
            )
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "orders.change_order_cargo_provider"', audit_text)

    def test_staging_private_payload_scan_ignores_opaque_control_identifiers(
        self,
    ) -> None:
        payload = {
            "action_id": "1234-5678-9012",
            "selection_id": "9988-7766-5544",
            "prepare_fingerprint": "1122-3344-5566",
            "source_snapshot_hash": "7788-9900-1122",
            "record_refs": [
                {
                    "record_id": "4455-6677-8899",
                    "order_number": "ORD-STAGE-1",
                }
            ],
        }

        findings = (
            operation_runtime._staging_marketplace_action_private_payload_findings(
                payload
            )
        )
        private_findings = (
            operation_runtime._staging_marketplace_action_private_payload_findings(
                {
                    **payload,
                    "customer_phone": "0555 111 22 33",
                }
            )
        )

        self.assertEqual(findings, [])
        self.assertIn("action.customer_phone:private_key", private_findings)
        self.assertIn("action.customer_phone:phone", private_findings)

    def test_staging_marketplace_execute_requires_env_and_writes_staging_audit(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-staging-cargo",
                    comp_name="Staging Cargo Seller",
                    platform="trendyol",
                    api_key="api-key",
                    api_secret="api-secret",
                    extra_config={"environment": "stage"},
                )
            )
            session.add(OrderHeader(orderNumber="ORD-STAGING-CARGO-1", api_account_id=1))
            session.add(
                OrderData(
                    orderNumber="ORD-STAGING-CARGO-1",
                    id=778899,
                    shipmentPackageId=778899,
                    api_account_id=1,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    shipmentPackageStatus="ReadyToShip",
                    cargoProviderName="Trendyol Express",
                    cargoTrackingNumber="TRK-STAGING-CARGO-1",
                )
            )
            session.commit()

        prepared = available_tools()["orders.change_cargo_provider.prepare"].handler(
            db_name=self.db_path,
            query="ORD-STAGING-CARGO-1",
            cargo_provider="Aras",
        )
        self.assertTrue(prepared.success, prepared.message)
        action = (prepared.data or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "orders.change_order_cargo_provider")

        from Orders.views import actions as orders_actions

        calls: list[dict[str, str]] = []

        def _fake_change_order_cargo_provider(order, *, cargo_provider_code: str) -> Result:
            with Session(get_engine(self.db_path)) as session:
                record = session.exec(select(OrderData).where(OrderData.orderNumber == "ORD-STAGING-CARGO-1")).first()
                if record is not None:
                    record.cargoProviderName = "Aras Kargo Marketplace"
                    session.add(record)
                    session.commit()
            calls.append({"order_number": str(getattr(order, "orderNumber", "")), "cargo_provider_code": cargo_provider_code})
            return Result.ok("Staging cargo fake tamam.", close_dialog=False, data={"order_number": "ORD-STAGING-CARGO-1"})

        class _FakeStageReadbackApi:
            async def get_order_by_number(self, order_number: str, page: int = 0, size: int = 50) -> Result:
                return Result.ok(
                    "Stage read-back tamam.",
                    close_dialog=False,
                    data={
                        "content": [
                            {
                                "orderNumber": order_number,
                                "id": 778899,
                                "shipmentPackageId": 778899,
                                "cargoProviderName": "Aras Kargo Marketplace",
                            }
                        ],
                        "page": page,
                        "totalPages": 1,
                        "totalElements": 1,
                    },
                )

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "staging-audit.jsonl"
            evidence_path = Path(tmp_dir) / "staging-evidence.json"
            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: ""}, clear=False), patch.object(
                orders_actions,
                "change_order_cargo_provider",
                _fake_change_order_cargo_provider,
            ):
                blocked = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="staging-test",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                    audit_path=audit_path,
                )
            self.assertFalse(blocked.success)
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False), patch.object(
                orders_actions,
                "change_order_cargo_provider",
                _fake_change_order_cargo_provider,
            ), patch.object(
                orders_actions,
                "_trendyol_api_for_account",
                return_value=_FakeStageReadbackApi(),
            ):
                missing_key = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="staging-test",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                    audit_path=audit_path,
                )
                missing_account = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="staging-test",
                    idempotency_key="staging-cargo-missing-account",
                    staging_reason="controlled staging cargo proof",
                    audit_path=audit_path,
                )
                mismatched_account = operation_runtime.execute_staging_marketplace_operation(
                    action,
                    approved_by="staging-test",
                    idempotency_key="staging-cargo-mismatch",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-production",
                    audit_path=audit_path,
                )
            self.assertFalse(missing_key.success)
            self.assertEqual((missing_key.data or {}).get("missing"), "idempotency_key")
            self.assertFalse(missing_account.success)
            self.assertEqual((missing_account.data or {}).get("missing"), "staging_account_id")
            self.assertFalse(mismatched_account.success)
            self.assertEqual((mismatched_account.data or {}).get("target_account_ids"), ["seller-staging-cargo"])
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            private_action = copy.deepcopy(action)
            private_action.setdefault("payload", {})["customer_email"] = "mahmut@example.com"
            secret_action = copy.deepcopy(action)
            secret_action.setdefault("payload", {})["api_key"] = "should-not-be-in-action"
            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False):
                private_payload_blocked = operation_runtime.preflight_staging_marketplace_operation(
                    private_action,
                    idempotency_key="staging-cargo-private-payload",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                )
                secret_payload_blocked = operation_runtime.preflight_staging_marketplace_operation(
                    secret_action,
                    idempotency_key="staging-cargo-secret-payload",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                )
            self.assertFalse(private_payload_blocked.success)
            self.assertIn("action_private_payload", (private_payload_blocked.data or {}).get("problems") or [])
            self.assertFalse((private_payload_blocked.data or {}).get("api_call_performed"))
            self.assertFalse((private_payload_blocked.data or {}).get("db_write_performed"))
            self.assertFalse(secret_payload_blocked.success)
            self.assertIn("action_secretish_payload", (secret_payload_blocked.data or {}).get("problems") or [])
            self.assertFalse((secret_payload_blocked.data or {}).get("api_call_performed"))
            self.assertFalse((secret_payload_blocked.data or {}).get("db_write_performed"))
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False):
                preflight = operation_runtime.preflight_staging_marketplace_operation(
                    action,
                    idempotency_key="staging-cargo-proof",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                )
            self.assertTrue(preflight.success, preflight.message)
            self.assertEqual(((preflight.data or {}).get("staging_proof") or {}).get("target_account_ids"), ["seller-staging-cargo"])
            self.assertEqual(((preflight.data or {}).get("staging_proof") or {}).get("verified_references"), ["ORD-STAGING-CARGO-1", "778899"])
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch("sys.stdout", new_callable=io.StringIO) as stdout, patch.dict(
                os.environ,
                {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: ""},
                clear=False,
            ):
                doctor_blocked_exit = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "doctor",
                        "--action-json",
                        json.dumps(action, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-cli-doctor",
                        "--staging-reason",
                        "controlled staging cargo doctor",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            doctor_blocked_payload = json.loads(stdout.getvalue())
            self.assertEqual(doctor_blocked_exit, 2)
            self.assertFalse(doctor_blocked_payload.get("success"))
            doctor_blocked_data = doctor_blocked_payload.get("data") or {}
            self.assertFalse(doctor_blocked_data.get("ready_for_execute"))
            self.assertIn("env", doctor_blocked_data.get("problems") or [])
            self.assertTrue(doctor_blocked_data.get("target_account_verified"))
            self.assertFalse(doctor_blocked_data.get("api_call_performed"))
            self.assertFalse(doctor_blocked_data.get("db_write_performed"))
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch("sys.stdout", new_callable=io.StringIO) as stdout, patch.dict(
                os.environ,
                {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"},
                clear=False,
            ):
                doctor_ready_exit = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "doctor",
                        "--action-json",
                        json.dumps(action, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-cli-doctor",
                        "--staging-reason",
                        "controlled staging cargo doctor",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            doctor_ready_payload = json.loads(stdout.getvalue())
            self.assertEqual(doctor_ready_exit, 0)
            self.assertTrue(doctor_ready_payload.get("success"))
            doctor_ready_data = doctor_ready_payload.get("data") or {}
            self.assertTrue(doctor_ready_data.get("ready_for_execute"))
            self.assertEqual(doctor_ready_data.get("problems"), [])
            self.assertTrue(doctor_ready_data.get("target_account_verified"))
            self.assertEqual(doctor_ready_data.get("target_account_ids"), ["seller-staging-cargo"])
            self.assertEqual(doctor_ready_data.get("verified_references_count"), 2)
            self.assertFalse(doctor_ready_data.get("api_call_performed"))
            self.assertFalse(doctor_ready_data.get("db_write_performed"))
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch("sys.stdout", new_callable=io.StringIO) as stdout, patch.dict(
                os.environ,
                {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: ""},
                clear=False,
            ):
                exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "preflight",
                        "--action-json",
                        json.dumps(action, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-cli-preflight",
                        "--staging-reason",
                        "controlled staging cargo cli preflight",
                        "--staging-account-id",
                        "seller-staging-cargo",
                        "--allow-preflight-without-env",
                    ]
                )
            cli_payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(cli_payload.get("success"))
            cli_data = cli_payload.get("data") or {}
            self.assertFalse(cli_data.get("api_call_performed"))
            self.assertFalse(cli_data.get("db_write_performed"))
            self.assertEqual((cli_data.get("staging_proof") or {}).get("target_account_ids"), ["seller-staging-cargo"])
            self.assertEqual(calls, [])
            self.assertFalse(audit_path.exists())

            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False), patch.object(
                orders_actions,
                "change_order_cargo_provider",
                _fake_change_order_cargo_provider,
            ), patch.object(
                orders_actions,
                "_trendyol_api_for_account",
                return_value=_FakeStageReadbackApi(),
            ):
                executed = operation_runtime.execute_staging_marketplace_evidence_run(
                    action,
                    approved_by="staging-test",
                    idempotency_key="staging-cargo-proof",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                    audit_path=audit_path,
                    evidence_path=evidence_path,
                )

            self.assertTrue(executed.success, executed.message)
            self.assertEqual(calls, [{"order_number": "ORD-STAGING-CARGO-1", "cargo_provider_code": "ARASMP"}])
            proof = (executed.data or {}).get("staging_proof") or {}
            self.assertEqual(proof.get("mode"), "staging_marketplace_mutation")
            self.assertEqual(proof.get("marketplace"), "trendyol")
            self.assertEqual(proof.get("staging_account_id"), "seller-staging-cargo")
            self.assertEqual(proof.get("target_account_ids"), ["seller-staging-cargo"])
            self.assertEqual(proof.get("verified_references"), ["ORD-STAGING-CARGO-1", "778899"])
            self.assertEqual(proof.get("idempotency_key"), "staging-cargo-proof")
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "orders.change_order_cargo_provider"', audit_text)
            self.assertIn('"staging_proof"', audit_text)
            self.assertIn('"staging_account_id": "seller-staging-cargo"', audit_text)
            self.assertNotIn("ORD-STAGING-CARGO-1", audit_text)
            self.assertNotIn("TRK-STAGING-CARGO-1", audit_text)
            self.assertNotIn("778899", audit_text)
            self.assertTrue(evidence_path.exists())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence_text = evidence_path.read_text(encoding="utf-8")
            self.assertEqual(evidence.get("artifact_type"), "orders_staging_marketplace_evidence")
            self.assertTrue(evidence.get("preflight_success"))
            self.assertTrue(evidence.get("execute_success"))
            self.assertEqual((evidence.get("result") or {}).get("staging_proof", {}).get("target_account_ids"), ["seller-staging-cargo"])
            self.assertTrue((evidence.get("result") or {}).get("staging_proof", {}).get("verified_references_redacted"))
            self.assertEqual((evidence.get("result") or {}).get("staging_proof", {}).get("verified_references_count"), 2)
            self.assertNotIn("ORD-STAGING-CARGO-1", evidence_text)
            self.assertNotIn("TRK-STAGING-CARGO-1", evidence_text)
            self.assertNotIn("778899", evidence_text)
            with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False):
                duplicate_evidence_path = operation_runtime.execute_staging_marketplace_evidence_run(
                    action,
                    approved_by="staging-test",
                    idempotency_key="staging-cargo-proof",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                    audit_path=audit_path,
                    evidence_path=evidence_path,
                )
                duplicate_idempotency = operation_runtime.execute_staging_marketplace_evidence_run(
                    action,
                    approved_by="staging-test",
                    idempotency_key="staging-cargo-proof",
                    staging_reason="controlled staging cargo proof",
                    staging_account_id="seller-staging-cargo",
                    audit_path=audit_path,
                    evidence_path=Path(tmp_dir) / "staging-evidence-new-path.json",
                )
            self.assertFalse(duplicate_evidence_path.success)
            self.assertIn("evidence_path_exists", (duplicate_evidence_path.data or {}).get("problems") or [])
            self.assertFalse((duplicate_evidence_path.data or {}).get("api_call_performed"))
            self.assertFalse((duplicate_evidence_path.data or {}).get("db_write_performed"))
            self.assertFalse(duplicate_idempotency.success)
            self.assertIn("idempotency_already_executed", (duplicate_idempotency.data or {}).get("problems") or [])
            self.assertFalse((duplicate_idempotency.data or {}).get("api_call_performed"))
            self.assertFalse((duplicate_idempotency.data or {}).get("db_write_performed"))
            self.assertEqual(calls, [{"order_number": "ORD-STAGING-CARGO-1", "cargo_provider_code": "ARASMP"}])
            existing_manifest_path = Path(tmp_dir) / "existing-staging-evidence.manifest.json"
            existing_manifest_path.write_text(json.dumps({"artifact_type": "orders_staging_marketplace_evidence_manifest"}, ensure_ascii=False), encoding="utf-8")
            existing_proof_template_path = Path(tmp_dir) / "existing-external-proof-template.json"
            existing_proof_template_path.write_text(
                json.dumps({"verified": False, "checked_by": ""}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("sys.stdout", new_callable=io.StringIO) as stdout, patch.dict(
                os.environ,
                {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"},
                clear=False,
            ):
                doctor_existing_exit = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "doctor",
                        "--action-json",
                        json.dumps(action, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-reason",
                        "controlled staging cargo doctor",
                        "--staging-account-id",
                        "seller-staging-cargo",
                        "--audit-path",
                        str(audit_path),
                        "--evidence-path",
                        str(evidence_path),
                        "--manifest-path",
                        str(existing_manifest_path),
                        "--proof-template-path",
                        str(existing_proof_template_path),
                    ]
                )
            doctor_existing_payload = json.loads(stdout.getvalue())
            self.assertEqual(doctor_existing_exit, 2)
            doctor_existing_data = doctor_existing_payload.get("data") or {}
            self.assertFalse(doctor_existing_data.get("ready_for_execute"))
            self.assertIn("idempotency_already_executed", doctor_existing_data.get("problems") or [])
            self.assertIn("evidence_path_exists", doctor_existing_data.get("problems") or [])
            self.assertIn("manifest_path_exists", doctor_existing_data.get("problems") or [])
            self.assertIn("proof_template_path_exists", doctor_existing_data.get("problems") or [])
            self.assertTrue(doctor_existing_data.get("manifest_path_exists"))
            self.assertTrue(doctor_existing_data.get("proof_template_path_exists"))
            self.assertEqual(doctor_existing_data.get("proof_template_path"), str(existing_proof_template_path))
            self.assertFalse(doctor_existing_data.get("api_call_performed"))
            self.assertFalse(doctor_existing_data.get("db_write_performed"))
            self.assertEqual(calls, [{"order_number": "ORD-STAGING-CARGO-1", "cargo_provider_code": "ARASMP"}])

            default_manifest_evidence_path = Path(tmp_dir) / "default-manifest-evidence.json"
            default_manifest_path = default_manifest_evidence_path.with_suffix(".manifest.json")
            default_manifest_path.write_text(
                json.dumps({"artifact_type": "orders_staging_marketplace_evidence_manifest"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch("sys.stdout", new_callable=io.StringIO) as stdout, patch.dict(
                os.environ,
                {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"},
                clear=False,
            ):
                doctor_default_manifest_exit = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "doctor",
                        "--action-json",
                        json.dumps(action, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-default-manifest-proof",
                        "--staging-reason",
                        "controlled staging cargo doctor",
                        "--staging-account-id",
                        "seller-staging-cargo",
                        "--audit-path",
                        str(Path(tmp_dir) / "default-manifest.audit.jsonl"),
                        "--evidence-path",
                        str(default_manifest_evidence_path),
                    ]
                )
            doctor_default_manifest_payload = json.loads(stdout.getvalue())
            self.assertEqual(doctor_default_manifest_exit, 2)
            doctor_default_manifest_data = doctor_default_manifest_payload.get("data") or {}
            self.assertFalse(doctor_default_manifest_data.get("ready_for_execute"))
            self.assertTrue(doctor_default_manifest_data.get("manifest_path_defaulted"))
            self.assertEqual(doctor_default_manifest_data.get("manifest_path"), str(default_manifest_path))
            self.assertIn("manifest_path_exists", doctor_default_manifest_data.get("problems") or [])
            self.assertTrue(doctor_default_manifest_data.get("manifest_path_exists"))
            self.assertFalse(doctor_default_manifest_data.get("api_call_performed"))
            self.assertFalse(doctor_default_manifest_data.get("db_write_performed"))

            unproven_evidence = operation_runtime.verify_staging_marketplace_evidence_artifact(
                evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(unproven_evidence.success)
            self.assertIn("external_verification", (unproven_evidence.data or {}).get("problems") or [])

            template_result = operation_runtime.staging_marketplace_external_proof_template(
                evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertTrue(template_result.success, template_result.message)
            template = (template_result.data or {}).get("template") or {}
            self.assertFalse(template.get("verified"))
            self.assertEqual(template.get("idempotency_key"), "staging-cargo-proof")
            self.assertEqual(template.get("staging_account_id"), "seller-staging-cargo")
            self.assertEqual(operation_runtime._external_verification_private_findings(template), [])
            self.assertNotIn("ORD-STAGING-CARGO-1", json.dumps(template, ensure_ascii=False))
            self.assertNotIn("TRK-STAGING-CARGO-1", json.dumps(template, ensure_ascii=False))
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                template_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "proof-template",
                        "--evidence-path",
                        str(evidence_path),
                        "--proof-template-path",
                        str(Path(tmp_dir) / "external-proof-template.json"),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            template_payload = json.loads(stdout.getvalue())
            self.assertEqual(template_exit_code, 0)
            self.assertTrue(template_payload.get("success"))
            written_template_path = Path(((template_payload.get("data") or {}).get("proof_template_path")))
            self.assertTrue(written_template_path.exists())
            original_template_text = written_template_path.read_text(encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                duplicate_template_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "proof-template",
                        "--evidence-path",
                        str(evidence_path),
                        "--proof-template-path",
                        str(written_template_path),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            duplicate_template_payload = json.loads(stdout.getvalue())
            self.assertEqual(duplicate_template_exit_code, 2)
            self.assertFalse(duplicate_template_payload.get("success"))
            self.assertIn("proof_template_path_exists", (duplicate_template_payload.get("data") or {}).get("problems") or [])
            self.assertEqual(written_template_path.read_text(encoding="utf-8"), original_template_text)
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                overwrite_template_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "proof-template",
                        "--evidence-path",
                        str(evidence_path),
                        "--proof-template-path",
                        str(written_template_path),
                        "--overwrite-proof-template",
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            overwrite_template_payload = json.loads(stdout.getvalue())
            self.assertEqual(overwrite_template_exit_code, 0, overwrite_template_payload)
            self.assertTrue(overwrite_template_payload.get("success"))
            template_attach = operation_runtime.attach_staging_marketplace_external_proof(
                evidence_path,
                json.loads(written_template_path.read_text(encoding="utf-8")),
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(template_attach.success)
            self.assertIn("external_verification.verified", (template_attach.data or {}).get("problems") or [])
            unchanged_after_template_attach = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertNotIn("external_verification", unchanged_after_template_attach)

            external_proof = {
                "verified": True,
                "marketplace_state_checked": True,
                "operation_matches": True,
                "staging_account_only": True,
                "staging_account_id": "seller-staging-cargo",
                "idempotency_key": "staging-cargo-proof",
                "checked_at": "2026-06-17T10:00:00+00:00",
                "checked_by": "staging-test-operator",
                "mutation_summary": "Cargo provider visible as ARASMP for the controlled staging order.",
            }
            invalid_base_evidence_path = Path(tmp_dir) / "staging-evidence-invalid-base.json"
            invalid_base_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            invalid_base_evidence["execute_success"] = False
            invalid_base_evidence_path.write_text(json.dumps(invalid_base_evidence, ensure_ascii=False), encoding="utf-8")
            invalid_base_attach = operation_runtime.attach_staging_marketplace_external_proof(
                invalid_base_evidence_path,
                external_proof,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(invalid_base_attach.success)
            self.assertIn("execute_success", (invalid_base_attach.data or {}).get("problems") or [])
            unchanged_invalid_base = json.loads(invalid_base_evidence_path.read_text(encoding="utf-8"))
            self.assertNotIn("external_verification", unchanged_invalid_base)

            private_external_proof = {
                **external_proof,
                "mutation_summary": "Cargo provider visible for ORD-STAGING-CARGO-1 with tracking TRK-STAGING-CARGO-1.",
            }
            private_attach = operation_runtime.attach_staging_marketplace_external_proof(
                evidence_path,
                private_external_proof,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(private_attach.success)
            self.assertIn("external_verification.private_identifiers", (private_attach.data or {}).get("problems") or [])
            written_template_path.write_text(json.dumps(external_proof, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                attach_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "attach-external-proof",
                        "--evidence-path",
                        str(evidence_path),
                        "--external-proof-json",
                        json.dumps(external_proof, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            attach_payload = json.loads(stdout.getvalue())
            self.assertEqual(attach_exit_code, 0, attach_payload)
            self.assertTrue(attach_payload.get("success"))

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue((evidence.get("external_verification") or {}).get("marketplace_state_checked"))
            duplicate_attach = operation_runtime.attach_staging_marketplace_external_proof(
                evidence_path,
                external_proof,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(duplicate_attach.success)
            self.assertIn("external_verification_exists", (duplicate_attach.data or {}).get("problems") or [])
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                overwrite_attach_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "attach-external-proof",
                        "--evidence-path",
                        str(evidence_path),
                        "--external-proof-json",
                        json.dumps(external_proof, ensure_ascii=False),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                        "--overwrite-external-proof",
                    ]
                )
            overwrite_attach_payload = json.loads(stdout.getvalue())
            self.assertEqual(overwrite_attach_exit_code, 0, overwrite_attach_payload)
            self.assertTrue(overwrite_attach_payload.get("success"))
            verified_evidence = operation_runtime.verify_staging_marketplace_evidence_artifact(
                evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertTrue(verified_evidence.success, verified_evidence.message)
            self.assertTrue((verified_evidence.data or {}).get("audit_verified"))
            self.assertTrue((verified_evidence.data or {}).get("external_verified"))
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                validate_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "validate",
                        "--evidence-path",
                        str(evidence_path),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            validate_payload = json.loads(stdout.getvalue())
            self.assertEqual(validate_exit_code, 0)
            self.assertTrue(validate_payload.get("success"))
            self.assertTrue(((validate_payload.get("data") or {}).get("verified")))

            missing_external_proof_manifest = operation_runtime.staging_marketplace_evidence_manifest(
                evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(missing_external_proof_manifest.success)
            self.assertIn("external_proof_path", (missing_external_proof_manifest.data or {}).get("problems") or [])

            mismatched_external_proof_file = Path(tmp_dir) / "mismatched-manifest-external-proof.json"
            mismatched_external_proof_file.write_text(
                json.dumps({**external_proof, "checked_by": "different-staging-operator"}, ensure_ascii=False),
                encoding="utf-8",
            )
            mismatched_external_proof_manifest_result = operation_runtime.staging_marketplace_evidence_manifest(
                evidence_path,
                external_proof_path=mismatched_external_proof_file,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(mismatched_external_proof_manifest_result.success)
            self.assertIn("external_proof.content_mismatch", (mismatched_external_proof_manifest_result.data or {}).get("problems") or [])

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                manifest_path = Path(tmp_dir) / "staging-evidence.manifest.json"
                manifest_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "manifest",
                        "--evidence-path",
                        str(evidence_path),
                        "--external-proof-file",
                        str(written_template_path),
                        "--manifest-path",
                        str(manifest_path),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            manifest_payload = json.loads(stdout.getvalue())
            self.assertEqual(manifest_exit_code, 0, manifest_payload)
            self.assertTrue(manifest_payload.get("success"))
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("artifact_type"), "orders_staging_marketplace_evidence_manifest")
            self.assertEqual(manifest.get("idempotency_key"), "staging-cargo-proof")
            manifest_files = {row.get("label"): row for row in manifest.get("files") or []}
            self.assertIn("evidence", manifest_files)
            self.assertIn("audit", manifest_files)
            self.assertIn("external_proof", manifest_files)
            self.assertEqual(manifest_files["evidence"].get("sha256"), hashlib.sha256(evidence_path.read_bytes()).hexdigest())
            self.assertEqual(manifest_files["audit"].get("sha256"), hashlib.sha256(audit_path.read_bytes()).hexdigest())
            self.assertEqual(manifest_files["external_proof"].get("sha256"), hashlib.sha256(written_template_path.read_bytes()).hexdigest())
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                verify_manifest_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "verify-manifest",
                        "--manifest-path",
                        str(manifest_path),
                        "--evidence-path",
                        str(evidence_path),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                    ]
                )
            verify_manifest_payload = json.loads(stdout.getvalue())
            self.assertEqual(verify_manifest_exit_code, 0, verify_manifest_payload)
            self.assertTrue(verify_manifest_payload.get("success"))
            self.assertTrue(((verify_manifest_payload.get("data") or {}).get("verified")))
            dotted_evidence_path = evidence_path.parent / "." / evidence_path.name
            dotted_manifest_verify = operation_runtime.verify_staging_marketplace_evidence_manifest(
                manifest_path,
                evidence_path=dotted_evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertTrue(dotted_manifest_verify.success, dotted_manifest_verify.data)

            duplicate_manifest = operation_runtime.staging_marketplace_evidence_manifest(
                evidence_path,
                manifest_path=manifest_path,
                external_proof_path=written_template_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(duplicate_manifest.success)
            self.assertIn("manifest_path_exists", (duplicate_manifest.data or {}).get("problems") or [])
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                overwrite_manifest_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "manifest",
                        "--evidence-path",
                        str(evidence_path),
                        "--external-proof-file",
                        str(written_template_path),
                        "--manifest-path",
                        str(manifest_path),
                        "--idempotency-key",
                        "staging-cargo-proof",
                        "--staging-account-id",
                        "seller-staging-cargo",
                        "--overwrite-manifest",
                    ]
                )
            overwrite_manifest_payload = json.loads(stdout.getvalue())
            self.assertEqual(overwrite_manifest_exit_code, 0, overwrite_manifest_payload)
            self.assertTrue(overwrite_manifest_payload.get("success"))

            tampered_manifest = dict(manifest)
            tampered_manifest["files"] = [
                {**row, "sha256": "0" * 64} if row.get("label") == "evidence" else row
                for row in manifest.get("files") or []
            ]
            tampered_manifest_path = Path(tmp_dir) / "staging-evidence-tampered.manifest.json"
            tampered_manifest_path.write_text(json.dumps(tampered_manifest, ensure_ascii=False), encoding="utf-8")
            tampered_manifest_verify = operation_runtime.verify_staging_marketplace_evidence_manifest(
                tampered_manifest_path,
                evidence_path=evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(tampered_manifest_verify.success)
            self.assertIn("files.evidence.sha256", (tampered_manifest_verify.data or {}).get("problems") or [])

            mismatched_evidence_row_manifest = dict(manifest)
            alternate_evidence_path = Path(tmp_dir) / "alternate-staging-evidence.json"
            alternate_evidence_path.write_text(evidence_path.read_text(encoding="utf-8"), encoding="utf-8")
            alternate_evidence_bytes = alternate_evidence_path.read_bytes()
            mismatched_evidence_row_manifest["files"] = [
                {
                    **row,
                    "path": str(alternate_evidence_path),
                    "sha256": hashlib.sha256(alternate_evidence_bytes).hexdigest(),
                    "bytes": len(alternate_evidence_bytes),
                }
                if row.get("label") == "evidence"
                else row
                for row in manifest.get("files") or []
            ]
            mismatched_evidence_row_manifest_path = Path(tmp_dir) / "staging-evidence-mismatched-row.manifest.json"
            mismatched_evidence_row_manifest_path.write_text(json.dumps(mismatched_evidence_row_manifest, ensure_ascii=False), encoding="utf-8")
            mismatched_evidence_row_verify = operation_runtime.verify_staging_marketplace_evidence_manifest(
                mismatched_evidence_row_manifest_path,
                evidence_path=evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(mismatched_evidence_row_verify.success)
            self.assertIn("files.evidence.path_mismatch", (mismatched_evidence_row_verify.data or {}).get("problems") or [])

            mismatched_external_proof_manifest = dict(manifest)
            mismatched_external_proof_path = Path(tmp_dir) / "mismatched-external-proof.json"
            mismatched_external_proof = {**external_proof, "checked_by": "different-staging-operator"}
            mismatched_external_proof_path.write_text(json.dumps(mismatched_external_proof, ensure_ascii=False), encoding="utf-8")
            mismatched_external_proof_bytes = mismatched_external_proof_path.read_bytes()
            mismatched_external_proof_manifest["files"] = [
                {
                    **row,
                    "path": str(mismatched_external_proof_path),
                    "sha256": hashlib.sha256(mismatched_external_proof_bytes).hexdigest(),
                    "bytes": len(mismatched_external_proof_bytes),
                }
                if row.get("label") == "external_proof"
                else row
                for row in manifest.get("files") or []
            ]
            mismatched_external_proof_manifest_path = Path(tmp_dir) / "staging-evidence-mismatched-proof.manifest.json"
            mismatched_external_proof_manifest_path.write_text(json.dumps(mismatched_external_proof_manifest, ensure_ascii=False), encoding="utf-8")
            mismatched_external_proof_verify = operation_runtime.verify_staging_marketplace_evidence_manifest(
                mismatched_external_proof_manifest_path,
                evidence_path=evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(mismatched_external_proof_verify.success)
            self.assertIn("files.external_proof.content_mismatch", (mismatched_external_proof_verify.data or {}).get("problems") or [])

            bad_execute_path = Path(tmp_dir) / "staging-evidence-bad-execute.json"
            bad_execute = dict(evidence)
            bad_execute["execute_success"] = False
            bad_execute_path.write_text(json.dumps(bad_execute, ensure_ascii=False), encoding="utf-8")
            bad_execute_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                bad_execute_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(bad_execute_verify.success)
            self.assertIn("execute_success", (bad_execute_verify.data or {}).get("problems") or [])
            bad_manifest = operation_runtime.staging_marketplace_evidence_manifest(
                bad_execute_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(bad_manifest.success)
            self.assertFalse(((bad_manifest.data or {}).get("validation") or {}).get("verified"))

            bad_account_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                evidence_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-production",
            )
            self.assertFalse(bad_account_verify.success)
            self.assertIn("staging_account_id", (bad_account_verify.data or {}).get("problems") or [])

            missing_key_path = Path(tmp_dir) / "staging-evidence-missing-key.json"
            missing_key = dict(evidence)
            missing_key["idempotency_key"] = ""
            missing_key_path.write_text(json.dumps(missing_key, ensure_ascii=False), encoding="utf-8")
            missing_key_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                missing_key_path,
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(missing_key_verify.success)
            self.assertIn("idempotency_key", (missing_key_verify.data or {}).get("problems") or [])

            missing_staging_account_path = Path(tmp_dir) / "staging-evidence-missing-account.json"
            missing_staging_account = dict(evidence)
            missing_staging_account["staging_account_id"] = ""
            missing_staging_account_path.write_text(json.dumps(missing_staging_account, ensure_ascii=False), encoding="utf-8")
            missing_staging_account_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                missing_staging_account_path,
                idempotency_key="staging-cargo-proof",
            )
            self.assertFalse(missing_staging_account_verify.success)
            self.assertIn("staging_account_id", (missing_staging_account_verify.data or {}).get("problems") or [])

            bad_external_path = Path(tmp_dir) / "staging-evidence-bad-external.json"
            bad_external = dict(evidence)
            bad_external["external_verification"] = {**dict(bad_external.get("external_verification") or {}), "staging_account_only": False}
            bad_external_path.write_text(json.dumps(bad_external, ensure_ascii=False), encoding="utf-8")
            bad_external_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                bad_external_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(bad_external_verify.success)
            self.assertIn("external_verification.staging_account_only", (bad_external_verify.data or {}).get("problems") or [])

            bad_private_external_path = Path(tmp_dir) / "staging-evidence-bad-private-external.json"
            bad_private_external = dict(evidence)
            bad_private_external["external_verification"] = {
                **dict(bad_private_external.get("external_verification") or {}),
                "mutation_summary": "Verified order ORD-STAGING-CARGO-1 with package 778899.",
            }
            bad_private_external_path.write_text(json.dumps(bad_private_external, ensure_ascii=False), encoding="utf-8")
            bad_private_external_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                bad_private_external_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(bad_private_external_verify.success)
            self.assertIn("external_verification.private_identifiers", (bad_private_external_verify.data or {}).get("problems") or [])

            secret_leak_path = Path(tmp_dir) / "staging-evidence-secret-leak.json"
            secret_leak = dict(evidence)
            secret_leak["result"] = {**dict(secret_leak.get("result") or {}), "api_secret": "should-not-appear"}
            secret_leak_path.write_text(json.dumps(secret_leak, ensure_ascii=False), encoding="utf-8")
            secret_leak_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                secret_leak_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(secret_leak_verify.success)
            self.assertIn("secretish_keys", (secret_leak_verify.data or {}).get("problems") or [])

            private_value_leak_path = Path(tmp_dir) / "staging-evidence-private-value-leak.json"
            private_value_leak = dict(evidence)
            private_value_leak["result"] = {
                **dict(private_value_leak.get("result") or {}),
                "leaked_note": "Order ORD-STAGING-CARGO-1 remained visible.",
            }
            private_value_leak_path.write_text(json.dumps(private_value_leak, ensure_ascii=False), encoding="utf-8")
            private_value_leak_verify = operation_runtime.verify_staging_marketplace_evidence_artifact(
                private_value_leak_path,
                idempotency_key="staging-cargo-proof",
                staging_account_id="seller-staging-cargo",
            )
            self.assertFalse(private_value_leak_verify.success)
            self.assertIn("staging_private_identifiers", (private_value_leak_verify.data or {}).get("problems") or [])

    def test_staging_preflight_rejects_non_stage_account_environment(self) -> None:
        action = {
            "action_type": "orders.change_order_cargo_provider",
            "approval_required": True,
            "execute_enabled": True,
            "warnings": [],
            "arguments": {
                "payload": {
                    "order": "ORDER-SCOPE",
                    "api_account_id": 7,
                    "cargo_provider_code": "ARASMP",
                    "db_name": self.db_path,
                }
            },
            "rows": [
                {
                    "order_number": "ORDER-SCOPE",
                    "api_account_id": 7,
                    "before": {"order_number": "ORDER-SCOPE", "api_account_id": 7},
                    "after": {"order_number": "ORDER-SCOPE", "api_account_id": 7, "cargo_provider": "Aras Kargo Marketplace"},
                }
            ],
        }
        target = Result.ok(
            "target",
            close_dialog=False,
            data={
                "target_account_ids": ["seller-scope"],
                "target_environments": ["production"],
                "verified_references": ["ORDER-SCOPE"],
            },
        )
        with patch.object(operation_runtime, "_staging_order_target_account_ids", return_value=target):
            result = operation_runtime.preflight_staging_marketplace_operation(
                action,
                idempotency_key="non-stage-environment-proof",
                staging_reason="verify explicit stage environment guard",
                staging_account_id="seller-scope",
                require_env=False,
            )
        self.assertFalse(result.success)
        self.assertEqual((result.data or {}).get("target_environments"), ["production"])
        self.assertFalse((result.data or {}).get("api_call_performed"))

    def test_failed_external_write_attempt_blocks_same_idempotency_replay(self) -> None:
        action = {
            "action_type": "orders.change_order_cargo_provider",
            "approval_required": True,
            "execute_enabled": True,
            "warnings": [],
            "arguments": {
                "payload": {
                    "order": "ORDER-REPLAY",
                    "api_account_id": 1,
                    "cargo_provider_code": "ARASMP",
                    "db_name": self.db_path,
                }
            },
            "rows": [],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "attempt-audit.jsonl"
            audit_path.write_text(
                json.dumps(
                    {
                        "idempotency_key": "external-attempt-replay",
                        "operation": "orders.change_order_cargo_provider",
                        "status": "failed",
                        "execute_success": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(operation_runtime, "_execute_manual_adapter") as adapter:
                result = operation_runtime.execute_manual_action(
                    action,
                    idempotency_key="external-attempt-replay",
                    audit_path=audit_path,
                )
        self.assertFalse(result.success)
        self.assertTrue((result.data or {}).get("replay_blocked"))
        adapter.assert_not_called()

    def test_staging_marketplace_execute_rejects_non_marketplace_actions(self) -> None:
        action = {
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "warnings": [],
            "arguments": {"payload": {"order_numbers": ["ORD-NOT-MARKETPLACE"]}},
        }
        with patch.dict(os.environ, {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV: "1"}, clear=False):
            result = operation_runtime.execute_staging_marketplace_operation(
                action,
                staging_reason="controlled staging proof",
                staging_account_id="seller-staging",
        )
        self.assertFalse(result.success)
        self.assertFalse((result.data or {}).get("api_call_performed"))

    def test_web_search_tool_blocks_private_order_identifiers_without_calling_search(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_search(query: str, limit: int) -> list[dict[str, str]]:
            calls.append((query, limit))
            return [{"title": "Should not run", "url": "https://example.invalid"}]

        tool = available_tools()["web.search"]
        result = tool.handler(
            query="ORD-PRIVATE-12345678 Mahmut musteri takip no TRK-SECRET-123 kargo durumu webde ara",
            limit=5,
            search_client=fake_search,
        )

        self.assertFalse(result.success)
        self.assertEqual(calls, [])
        self.assertTrue((result.data or {}).get("blocked_private_data"))
        self.assertFalse((result.data or {}).get("query_sent"))
        findings = set((result.data or {}).get("privacy_findings") or [])
        self.assertIn("order_or_claim_id", findings)
        self.assertIn("customer_private_context", findings)

    def test_public_marketplace_rule_question_routes_to_web_search(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_search(query: str, *, limit: int) -> list[dict[str, str]]:
            calls.append((query, limit))
            return [
                {
                    "title": "Trendyol iade kargo kurallari",
                    "url": "https://partner.trendyol.com/docs/iade-kargo",
                    "snippet": "Guncel pazaryeri dokumani.",
                }
            ]

        with patch("AI.processors.tools._public_web_search", side_effect=fake_search):
            result = run_agent_turn(
                "Trendyol iade kargo kurallarini guncel webde ara",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Bilmiyorum."}',
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "web.search")
        self.assertEqual(len(calls), 1)
        self.assertIn("Trendyol", calls[0][0])
        self.assertNotIn("ORD-", calls[0][0])
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Trendyol iade kargo kurallari", answer)
        self.assertIn("partner.trendyol.com", answer)

    def test_public_web_search_falls_back_to_bing_rss_when_duckduckgo_is_empty(self) -> None:
        with patch("AI.processors.tools._duckduckgo_search", return_value=[]) as duck_mock, patch(
            "AI.processors.tools._yahoo_search", return_value=[]
        ) as yahoo_mock, patch("AI.processors.tools._brave_search", return_value=[]) as brave_mock, patch(
            "AI.processors.tools._bing_rss_search",
            return_value=[
                {
                    "title": "2026 e-ticaret trendleri raporu",
                    "url": "https://example.test/e-ticaret-2026",
                    "snippet": "Guncel pazar ve lojistik egilimleri.",
                }
            ],
        ) as bing_mock:
            result = available_tools()["web.search"].handler(
                query="2026 Turkiye e-ticaret trendlerini webde ara",
                limit=5,
            )

        self.assertTrue(result.success, result.message)
        self.assertGreaterEqual(duck_mock.call_count, 1)
        self.assertGreaterEqual(yahoo_mock.call_count, 1)
        self.assertGreaterEqual(brave_mock.call_count, 1)
        self.assertGreaterEqual(bing_mock.call_count, 1)
        self.assertTrue((result.data or {}).get("query_sent"))
        self.assertFalse((result.data or {}).get("blocked_private_data"))
        rows = (result.data or {}).get("results") or []
        self.assertEqual(rows[0].get("title"), "2026 e-ticaret trendleri raporu")
        self.assertEqual(rows[0].get("snippet"), "Guncel pazar ve lojistik egilimleri.")

    def test_public_web_search_rejects_off_topic_provider_results(self) -> None:
        off_topic = [
            {
                "title": "2025 resmi tatil gunleri",
                "url": "https://example.test/takvim",
                "snippet": "Bayram ve tatil tarihleri.",
            }
        ]
        relevant = [
            {
                "title": "Turkiye e-ticaret gorunumu raporu",
                "url": "https://ticaret.gov.tr/e-ticaret-raporu",
                "snippet": "E-ticaret hacmi ve sektorel egilimler.",
            }
        ]
        with patch("AI.processors.tools._yahoo_search", return_value=off_topic), patch(
            "AI.processors.tools._duckduckgo_search", return_value=relevant
        ) as duck_mock, patch("AI.processors.tools._enrich_web_rows", side_effect=lambda rows, **_kwargs: rows):
            rows = ai_tools._public_web_search(
                "2025 Turkiye e-ticaret gorunumu raporundaki ana egilimleri arastir",
                limit=5,
            )

        self.assertGreaterEqual(duck_mock.call_count, 1)
        self.assertEqual(rows[0].get("url"), "https://ticaret.gov.tr/e-ticaret-raporu")
        self.assertTrue(rows[0].get("official"))

    def test_public_web_search_retries_with_concise_topic_query(self) -> None:
        calls: list[str] = []

        def yahoo_search(query: str, *, limit: int) -> list[dict[str, str]]:
            del limit
            calls.append(query)
            if query == "2025 turkiye e-ticaret gorunumu rapor egilimleri":
                return [
                    {
                        "title": "Turkiye e-ticaret gorunumu raporu",
                        "url": "https://ticaret.gov.tr/e-ticaret-raporu",
                        "snippet": "E-ticaret hacmi ve sektorel egilimler.",
                    }
                ]
            return []

        with patch("AI.processors.tools._yahoo_search", side_effect=yahoo_search), patch(
            "AI.processors.tools._duckduckgo_search", return_value=[]
        ), patch("AI.processors.tools._brave_search", return_value=[]), patch(
            "AI.processors.tools._bing_rss_search", return_value=[]
        ):
            rows = ai_tools._public_web_search(
                "2025 Turkiye e-ticaret gorunumu raporundaki ana egilimleri guncel web kaynaklariyla arastir ve kaynaklariyla acikla",
                limit=5,
            )

        self.assertEqual(calls[-1], "2025 turkiye e-ticaret gorunumu rapor egilimleri")
        self.assertEqual(rows[0].get("url"), "https://ticaret.gov.tr/e-ticaret-raporu")

    def test_profit_calculation_web_query_removes_conversation_noise(self) -> None:
        variants = ai_tools._web_search_query_variants(
            "nette bi arastirma yapmani istiyorum kar nasil hesaplanir"
        )

        self.assertIn(
            "e-ticaret net kar hesaplama urun maliyeti pazaryeri komisyon kargo vergi iade",
            variants,
        )
        self.assertIn("pazaryeri net kar marji nasil hesaplanir", variants)
        self.assertIn("kar nasil hesaplanir", variants)
        self.assertFalse(any("nette" in variant or "istiyorum" in variant for variant in variants))

        mojibake_variants = ai_tools._web_search_query_variants(
            "nette bi ara?t?rma yapman? istiyorum k?r nas?l hesaplan?r"
        )
        self.assertIn("kar nasil hesaplanir", mojibake_variants)
        self.assertFalse(any("rma yapman" in variant for variant in mojibake_variants))

    def test_web_search_marks_public_only_profit_sources_with_authority_warning(self) -> None:
        result = available_tools()["web.search"].handler(
            query="nette bi arastirma yapmani istiyorum kar nasil hesaplanir",
            limit=5,
            search_client=lambda _query, _limit: [
                {
                    "title": "Net kar hesaplama",
                    "url": "https://example.test/net-kar",
                    "snippet": "Net kar, gelirden maliyet ve giderlerin dusulmesiyle hesaplanir.",
                }
            ],
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("result_quality"), "public_sources_only")
        self.assertEqual(data.get("official_result_count"), 0)
        self.assertIn("Resmi/otoriter kaynak bulunamadi", data.get("authority_warning") or "")
        self.assertIn(
            "e-ticaret net kar hesaplama urun maliyeti pazaryeri komisyon kargo vergi iade",
            data.get("query_variants") or [],
        )

    def test_web_synthesis_prompt_blocks_unsourced_volatile_commerce_claims(self) -> None:
        prompt = ai_agent._web_synthesis_prompt(
            user_message="kar nasil hesaplanir nette arastir",
            tool_results=[
                {
                    "tool": "web.search",
                    "data": {
                        "query": "kar nasil hesaplanir nette arastir",
                        "query_variants": ["e-ticaret net kar hesaplama urun maliyeti pazaryeri komisyon kargo vergi iade"],
                        "count": 1,
                        "official_result_count": 0,
                        "result_quality": "public_sources_only",
                        "authority_warning": "Resmi/otoriter kaynak bulunamadi; cevap yalnizca genel public kaynaklardan sinirli yorumlanmali.",
                        "results": [
                            {
                                "title": "Net kar hesaplama",
                                "url": "https://example.test/net-kar",
                                "snippet": "Net kar, gelirden maliyet ve giderlerin dusulmesiyle hesaplanir.",
                                "content_excerpt": "",
                            }
                        ]
                    },
                }
            ],
        )

        self.assertIn("Snippet veya content_excerpt alaninda olmayan sayi", prompt)
        self.assertIn("Komisyon, ucret, vergi, ceza, oran, benchmark", prompt)
        self.assertIn("resmi/guncel kaynakta acikca yoksa", prompt)
        self.assertIn("authority_warning", prompt)
        self.assertIn("Resmi/otoriter kaynak bulunamadi", prompt)

    def test_trendyol_web_search_variants_prioritize_official_developer_sources(self) -> None:
        variants = ai_tools._web_search_query_variants("Trendyol satici iade kargo kurallari guncel dokuman")

        self.assertTrue(variants[0].startswith("site:developers.trendyol.com"))
        self.assertTrue(variants[1].startswith("site:partner.trendyol.com"))
        self.assertIn("Trendyol satici iade kargo kurallari guncel dokuman", variants)
        self.assertTrue(ai_tools._official_web_source("https://developers.trendyol.com/docs/getclaims"))
        self.assertTrue(ai_tools._official_web_source("https://partner.trendyol.com/seller-information"))

    def test_general_current_information_questions_route_to_web_search(self) -> None:
        scenarios = (
            "Python en son surumu ve resmi dokumani nedir?",
            "Bugunku teknoloji haberlerini kaynaklariyla ozetle",
            "Yururlukteki e-ticaret yonetmeligini resmi kaynaklardan arastir",
            "Guncel TCMB politika faizi nedir?",
            "OpenAI API en son dokumantasyon degisikliklerini webden arastir",
        )
        for prompt in scenarios:
            with self.subTest(prompt=prompt), patch(
                "AI.processors.tools._public_web_search",
                return_value=[
                    {
                        "title": "Official current source",
                        "url": "https://example.gov/current",
                        "snippet": "Current verified information.",
                    }
                ],
            ):
                result = run_agent_turn(
                    prompt,
                    planner_client=lambda _prompt: '{"mode":"answer","response":"Bilmiyorum."}',
                    chat_client=lambda _prompt: "Guncel bilgi resmi kaynakta yer aliyor.",
                    db_name=self.db_path,
                )

            self.assertTrue(result.success, result.message)
            self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "web.search")

    def test_latest_non_order_question_is_not_repaired_to_recent_orders(self) -> None:
        with patch(
            "AI.processors.tools._public_web_search",
            return_value=[{"title": "Python docs", "url": "https://docs.python.org/3/", "snippet": "Official docs."}],
        ):
            result = run_agent_turn(
                "Python en son kararli surumu nedir, resmi release notlariyla acikla",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Bilmiyorum."}',
                chat_client=lambda _prompt: "Resmi Python dokumani kullanildi.",
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "web.search")

    def test_product_comparison_with_technical_sources_routes_to_web_search(self) -> None:
        with patch(
            "AI.processors.tools._public_web_search",
            return_value=[{"title": "Printer specs", "url": "https://zebra.com/specs", "snippet": "Official specs."}],
        ):
            result = run_agent_turn(
                "Zebra Brother ve TSC arasinda termal etiket yazici secerken teknik kaynaklarla karsilastirma yap",
                planner_client=lambda _prompt: '{"mode":"answer","response":"Bilmiyorum."}',
                chat_client=lambda _prompt: "Teknik kaynaklara gore karsilastirma.",
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "web.search")

    def test_local_write_questions_do_not_route_to_web_search(self) -> None:
        result = run_agent_turn(
            "ORD-LOCAL-WRITE-1 siparisinin kargo firmasini Aras yap",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam."}',
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertNotEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "web.search")

    def test_general_official_query_variants_cover_docs_law_and_economy(self) -> None:
        python_variants = ai_tools._web_search_query_variants("Python en son surumu resmi dokumani")
        law_variants = ai_tools._web_search_query_variants("Guncel e-ticaret yonetmeligi resmi gazete")
        economy_variants = ai_tools._web_search_query_variants("Guncel TCMB politika faizi")

        self.assertTrue(python_variants[0].startswith("site:docs.python.org"))
        self.assertTrue(any(value.startswith("site:resmigazete.gov.tr") for value in law_variants))
        self.assertTrue(economy_variants[0].startswith("site:tcmb.gov.tr"))

    def test_product_comparison_variants_include_manufacturer_spec_sources(self) -> None:
        variants = ai_tools._web_search_query_variants(
            "2026 en iyi termal etiket yazici karsilastirmasi Zebra Brother TSC"
        )

        self.assertIn("site:zebra.com thermal label printer specifications", variants)
        self.assertIn("site:brother.com thermal label printer specifications", variants)
        self.assertIn("site:tscprinters.com desktop thermal label printer specifications", variants)

    def test_web_result_freshness_boosts_recent_results_for_current_queries(self) -> None:
        current_year = datetime.now().year
        recent = {
            "title": f"Current release June 24 {current_year}",
            "url": "https://docs.python.org/release",
            "snippet": f"24 June {current_year} latest release notes.",
        }
        old = {
            "title": "Current release archive",
            "url": "https://example.test/archive",
            "snippet": "1 January 2020 old release notes.",
        }
        ranked = ai_tools._normalize_ranked_web_rows("Python en guncel surum latest release", [old, recent])

        self.assertEqual(ranked[0].get("url"), "https://docs.python.org/release")
        self.assertEqual(ranked[0].get("published_date"), f"{current_year}-06-24")
        self.assertGreater(ranked[0].get("relevance_score"), ranked[1].get("relevance_score"))

    def test_relevance_filter_rejects_same_brand_wrong_product_category(self) -> None:
        rows = ai_tools._relevant_web_rows(
            "termal etiket yazici karsilastirmasi Zebra Brother TSC",
            [
                {
                    "title": "Mono lazer yazici Brother",
                    "url": "https://support.brother.com/mono",
                    "snippet": "Ofis lazer yazicilari.",
                },
                {
                    "title": "Brother termal etiket yazicisi QL serisi",
                    "url": "https://support.brother.com/label",
                    "snippet": "Termal etiket yazici teknik ozellikleri.",
                },
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("/label", rows[0].get("url"))

    def test_web_result_diversity_selects_distinct_domains_before_duplicates(self) -> None:
        rows = [
            {"url": "https://zebra.com/a", "title": "Zebra A"},
            {"url": "https://zebra.com/b", "title": "Zebra B"},
            {"url": "https://brother.com/a", "title": "Brother A"},
            {"url": "https://tscprinters.com/a", "title": "TSC A"},
        ]

        selected = ai_tools._diversify_web_rows(rows, limit=3)

        self.assertEqual(
            [ai_tools.urllib.parse.urlsplit(row.get("url")).hostname for row in selected],
            ["zebra.com", "brother.com", "tscprinters.com"],
        )

    def test_web_result_diversity_keeps_multiple_critical_official_documents_first(self) -> None:
        rows = [
            {"url": "https://resmigazete.gov.tr/original", "title": "Original", "official": True},
            {"url": "https://resmigazete.gov.tr/amendment", "title": "Amendment", "official": True},
            {"url": "https://tr.wikipedia.org/wiki/Test", "title": "Wikipedia", "official": False},
        ]

        selected = ai_tools._diversify_web_rows(rows, limit=3)

        self.assertEqual([row.get("title") for row in selected[:2]], ["Original", "Amendment"])

    def test_web_provider_resilience_retries_transient_429_then_caches_success(self) -> None:
        provider = "test-retry-provider"
        query = "unique retry query 991"
        ai_tools._WEB_PROVIDER_BACKOFF_UNTIL.pop(provider, None)
        failed = ai_tools.urllib.error.HTTPError(
            "https://search.test",
            429,
            "Too Many Requests",
            {},
            None,
        )
        search = unittest.mock.MagicMock(
            side_effect=[
                failed,
                [{"title": "Recovered", "url": "https://example.test/recovered"}],
            ]
        )
        with patch("AI.processors.tools.time_module.sleep"):
            first = ai_tools._search_provider_with_resilience(provider, search, query, limit=5)
            second = ai_tools._search_provider_with_resilience(provider, search, query, limit=5)

        self.assertEqual(search.call_count, 2)
        self.assertEqual(first, second)
        self.assertEqual(first[0].get("title"), "Recovered")

    def test_web_provider_resilience_opens_circuit_after_repeated_429(self) -> None:
        provider = "test-backoff-provider"
        query = "unique backoff query 992"
        ai_tools._WEB_PROVIDER_BACKOFF_UNTIL.pop(provider, None)
        failed = ai_tools.urllib.error.HTTPError(
            "https://search.test",
            429,
            "Too Many Requests",
            {},
            None,
        )
        search = unittest.mock.MagicMock(side_effect=failed)
        with patch("AI.processors.tools.time_module.sleep"):
            with self.assertRaises(ai_tools.urllib.error.HTTPError):
                ai_tools._search_provider_with_resilience(provider, search, query, limit=5)
            second = ai_tools._search_provider_with_resilience(provider, search, query, limit=5)

        self.assertEqual(search.call_count, 2)
        self.assertEqual(second, [])

    def test_official_seed_rows_keep_known_documentation_available_during_provider_failure(self) -> None:
        with patch(
            "AI.processors.tools._yahoo_search",
            side_effect=ai_tools.urllib.error.HTTPError("x", 429, "rate", {}, None),
        ), patch(
            "AI.processors.tools._duckduckgo_search", return_value=[]
        ), patch("AI.processors.tools._brave_search", return_value=[]), patch(
            "AI.processors.tools._bing_rss_search", return_value=[]
        ), patch("AI.processors.tools._enrich_web_rows", side_effect=lambda rows, **_kwargs: rows), patch(
            "AI.processors.tools.time_module.sleep"
        ):
            rows = ai_tools._public_web_search("Python en son surumu resmi dokuman", limit=5)

        self.assertTrue(rows)
        self.assertTrue(any("docs.python.org" in row.get("url", "") for row in rows))
        self.assertTrue(all(row.get("official") for row in rows))

    def test_product_official_seeds_cover_requested_manufacturers(self) -> None:
        rows = ai_tools._official_seed_rows(
            "Zebra Brother TSC termal etiket yazici teknik karsilastirma"
        )
        domains = {
            ai_tools.urllib.parse.urlsplit(row.get("url", "")).hostname
            for row in rows
        }

        self.assertIn("www.zebra.com", domains)
        self.assertIn("support.brother.com", domains)
        self.assertIn("emea.tscprinters.com", domains)

    def test_law_and_tcmb_official_seeds_survive_search_provider_outage(self) -> None:
        law_rows = ai_tools._official_seed_rows(
            "Turkiye e-ticaret araci hizmet saglayici yonetmeligi resmi metin"
        )
        tcmb_rows = ai_tools._official_seed_rows("Guncel TCMB politika faizi")

        self.assertTrue(any("resmigazete.gov.tr" in row.get("url", "") for row in law_rows))
        self.assertTrue(any("/PPK/" in row.get("url", "") for row in tcmb_rows))
        self.assertTrue(any("faiz-oranlari" in row.get("url", "") for row in tcmb_rows))

    def test_google_news_rss_parser_keeps_source_and_published_date(self) -> None:
        body = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
          <title>AI news - Example News</title>
          <link>https://news.google.com/rss/articles/example</link>
          <pubDate>Wed, 24 Jun 2026 12:00:00 GMT</pubDate>
          <source>Example News</source>
        </item></channel></rss>"""

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return body

        with patch("AI.processors.tools.urllib.request.urlopen", return_value=FakeResponse()):
            rows = ai_tools._google_news_rss_search("AI news", limit=5)

        self.assertEqual(rows[0].get("source"), "Example News")
        self.assertEqual(rows[0].get("published_date"), "2026-06-24")
        self.assertIn("Example News", rows[0].get("snippet"))

    def test_wikipedia_api_fallback_builds_canonical_article_urls(self) -> None:
        payload = {
            "query": {
                "search": [
                    {
                        "title": "Yapay zeka",
                        "snippet": "<span>Bilgisayar bilimi</span> alani.",
                    }
                ]
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with patch("AI.processors.tools.urllib.request.urlopen", return_value=FakeResponse()):
            rows = ai_tools._wikipedia_search("Yapay zeka", limit=5)

        self.assertEqual(rows[0].get("url"), "https://tr.wikipedia.org/wiki/Yapay_zeka")
        self.assertEqual(rows[0].get("snippet"), "Bilgisayar bilimi alani.")

    def test_web_result_ranking_deduplicates_tracking_urls_and_prioritizes_official_sources(self) -> None:
        rows = ai_tools._normalize_ranked_web_rows(
            "2025 Turkiye e-ticaret gorunumu raporu",
            [
                {
                    "title": "E-ticaret raporu ozeti",
                    "url": "https://blog.example/ecommerce?utm_source=test",
                    "snippet": "Turkiye e-ticaret gorunumu.",
                },
                {
                    "title": "E-ticaret raporu ozeti tekrar",
                    "url": "https://blog.example/ecommerce?utm_source=other#section",
                    "snippet": "Ayni kaynagin kopyasi.",
                },
                {
                    "title": "Turkiye'de E-Ticaretin Gorunumu Raporu 2025",
                    "url": "https://ticaret.gov.tr/rapor?utm_campaign=mail",
                    "snippet": "Resmi e-ticaret raporu.",
                },
            ],
            provider="test",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].get("url"), "https://ticaret.gov.tr/rapor")
        self.assertTrue(rows[0].get("official"))
        self.assertGreater(rows[0].get("relevance_score"), rows[1].get("relevance_score"))
        self.assertEqual(rows[1].get("url"), "https://blog.example/ecommerce")

    def test_public_page_excerpt_blocks_private_network_targets(self) -> None:
        with patch("AI.processors.tools.socket.getaddrinfo") as dns_mock, patch(
            "AI.processors.tools.urllib.request.build_opener"
        ) as open_mock:
            excerpt = ai_tools._fetch_public_page_excerpt("http://127.0.0.1/private")

        self.assertEqual(excerpt, "")
        dns_mock.assert_not_called()
        open_mock.assert_not_called()

    def test_public_page_excerpt_extracts_text_after_public_dns_validation(self) -> None:
        class FakeResponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def geturl(self):
                return "https://ticaret.gov.tr/rapor"

            def read(self, _size):
                return (
                    b"<html><style>hidden</style><script>bad()</script>"
                    b"<body><h1>Official Report</h1><p>Ecommerce volume increased.</p></body></html>"
                )

        public_dns = [(ai_tools.socket.AF_INET, ai_tools.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        fake_opener = unittest.mock.MagicMock()
        fake_opener.open.return_value = FakeResponse()
        with patch("AI.processors.tools.socket.getaddrinfo", return_value=public_dns), patch(
            "AI.processors.tools.urllib.request.build_opener", return_value=fake_opener
        ):
            excerpt = ai_tools._fetch_public_page_excerpt("https://ticaret.gov.tr/rapor")

        self.assertIn("Official Report", excerpt)
        self.assertIn("Ecommerce volume increased", excerpt)
        self.assertNotIn("hidden", excerpt)
        self.assertNotIn("bad()", excerpt)

    def test_public_redirect_handler_blocks_private_redirect_before_request(self) -> None:
        handler = ai_tools._PublicOnlyRedirectHandler()

        with self.assertRaises(ai_tools.urllib.error.HTTPError):
            handler.redirect_request(
                unittest.mock.MagicMock(),
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/private",
            )

    def test_brave_search_parser_extracts_result_title_url_and_description(self) -> None:
        body = """
        <div class="snippet result" data-pos="0" data-type="web">
          <a href="https://ticaret.gov.tr/rapor" class="site-link"><span>Ticaret Bakanligi</span></a>
          <a href="https://ticaret.gov.tr/rapor" class="result-title">
            <div class="title">Turkiye'de E-Ticaretin Gorunumu Raporu</div>
          </a>
          <div class="snippet-description">2025 yili resmi e-ticaret verileri.</div>
        </div>
        """

        rows = ai_tools._parse_brave_search_results(body, limit=5)

        self.assertEqual(
            rows,
            [
                {
                    "title": "Turkiye'de E-Ticaretin Gorunumu Raporu",
                    "url": "https://ticaret.gov.tr/rapor",
                    "snippet": "2025 yili resmi e-ticaret verileri.",
                }
            ],
        )

    def test_yahoo_search_parser_decodes_original_result_url(self) -> None:
        body = """
        <div class="compTitle options-toggle">
          <a href="https://r.search.yahoo.com/x/RU=https%3a%2f%2fticaret.gov.tr%2frapor%2520.pdf/RK=2/RS=x">
            <h3 class="title"><span>IN TURKIYE REPORT 2025</span></h3>
          </a>
        </div>
        <div class="compText aAbs">
          <p>E-Commerce Outlook in Turkiye 2025 official report.</p>
        </div>
        """

        rows = ai_tools._parse_yahoo_search_results(body, limit=5)

        self.assertEqual(
            rows,
            [
                {
                    "title": "IN TURKIYE REPORT 2025",
                    "url": "https://ticaret.gov.tr/rapor .pdf",
                    "snippet": "E-Commerce Outlook in Turkiye 2025 official report.",
                }
            ],
        )

    def test_web_search_visible_answer_includes_real_source_urls(self) -> None:
        with patch(
            "AI.processors.tools._public_web_search",
            return_value=[
                {
                    "title": "Official ecommerce report",
                    "url": "https://ticaret.gov.tr/report",
                    "snippet": "Official 2025 figures.",
                    "official": True,
                }
            ],
        ):
            result = run_agent_turn(
                "2025 e-ticaret raporunu guncel web kaynaklariyla arastir",
                planner_client=lambda _prompt: '{"mode":"tool","tool":"web.search","arguments":{"query":"2025 e-ticaret raporu","limit":5}}',
                chat_client=lambda _prompt: "Raporda e-ticaret hacminin buyudugu belirtiliyor.",
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Raporda e-ticaret hacminin buyudugu", answer)
        self.assertIn("Kaynaklar:", answer)
        self.assertIn("https://ticaret.gov.tr/report", answer)

    def test_web_search_retries_compact_synthesis_when_primary_answer_is_empty(self) -> None:
        chat_answers = iter(
            [
                "",
                (
                    "Rapora gore e-ticaret hacmi buyuyor ve sektorel donusum hizlaniyor. "
                    "Resmi rapor ayrintili pazar gostergeleri sunuyor.\n"
                    "Kaynak: https://ticaret.gov.tr/report"
                ),
            ]
        )
        with patch(
            "AI.processors.tools._public_web_search",
            return_value=[
                {
                    "title": "Official ecommerce report",
                    "url": "https://ticaret.gov.tr/report",
                    "snippet": "E-ticaret hacmi buyudu ve sektorel donusum hizlandi.",
                    "official": True,
                }
            ],
        ):
            result = run_agent_turn(
                "2025 e-ticaret raporundaki egilimleri webden acikla",
                planner_client=lambda _prompt: '{"mode":"tool","tool":"web.search","arguments":{"query":"2025 e-ticaret raporu","limit":5}}',
                chat_client=lambda _prompt: next(chat_answers),
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("e-ticaret hacmi buyuyor", answer)
        self.assertIn("https://ticaret.gov.tr/report", answer)

    def test_profit_web_search_rejects_thin_synthesis_and_explains_formula(self) -> None:
        calls: list[str] = []

        def chat_client(prompt: str) -> str:
            calls.append(prompt)
            return (
                "E-ticarette net kar hesaplamasi birden fazla gider kalemini "
                "dikkate alan kapsamli bir surectir."
            )

        with patch(
            "AI.processors.tools._public_web_search",
            return_value=[
                {
                    "title": "E-ticaret net kar rehberi",
                    "url": "https://example.com/net-kar",
                    "snippet": (
                        "Net kar icin urun maliyeti, pazaryeri komisyonu, "
                        "kargo, vergi, reklam ve iade giderleri dusulur."
                    ),
                    "official": False,
                    "relevance_score": 12,
                }
            ],
        ):
            result = run_agent_turn(
                "internette arastir: e-ticarette net kar nasil hesaplanir",
                planner_client=lambda _prompt: (
                    '{"mode":"tool","tool":"web.search",'
                    '"arguments":{"query":"e-ticarette net kar nasil hesaplanir","limit":5}}'
                ),
                chat_client=chat_client,
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertGreaterEqual(len(calls), 2)
        answer = str((result.data or {}).get("answer") or "")
        for term in ("urun maliyeti", "pazaryeri komisyonu", "kargo", "vergi"):
            self.assertIn(term, answer)
        self.assertIn("Kar marji", answer)
        self.assertIn("Resmi/otoriter kaynak bulunamadi", answer)
        self.assertIn("https://example.com/net-kar", answer)
        self.assertNotIn("Web arama sonucu:", answer)

    def test_trendyol_cargo_web_fallback_synthesizes_official_steps(self) -> None:
        answer = ai_agent._format_deterministic_web_answer(
            "Trendyol kargo firmasi degisikligi resmi API dokumaninda nasil yapiliyor",
            {
                "results": [
                    {
                        "title": "Paket Kargo Firmasi Degistirme",
                        "url": "https://developers.trendyol.com/reference/changecargoprovider",
                        "snippet": (
                            "Kargo firmasi changeCargoProvider ile degistirilir. "
                            "Bir paket icin 5 dakikada bir kez cagrilabilir ve paket "
                            "siparis servisinden yeniden cekilmelidir."
                        ),
                        "official": True,
                    }
                ]
            },
        )

        self.assertIn("changeCargoProvider", answer)
        self.assertIn("5 dakika", answer)
        self.assertIn("yeniden cekilerek", answer)
        self.assertIn("read-back", answer)
        self.assertIn(
            "https://developers.trendyol.com/reference/changecargoprovider",
            answer,
        )

    def test_web_search_retries_when_llm_invents_unsupported_numbers(self) -> None:
        prompts: list[str] = []
        answers = iter(
            [
                "Rapora gore hacim yuzde 99 artti ve 12 trilyon TL oldu.",
                (
                    "Rapora gore e-ticaret hacmi yuzde 52,2 artarak 4,57 trilyon TL oldu.\n"
                    "Kaynak: https://ticaret.gov.tr/report"
                ),
            ]
        )

        def chat_client(prompt: str) -> str:
            prompts.append(prompt)
            return next(answers)

        with patch(
            "AI.processors.tools._public_web_search",
            return_value=[
                {
                    "title": "Official ecommerce report 2025",
                    "url": "https://ticaret.gov.tr/report",
                    "snippet": "E-ticaret hacmi yuzde 52,2 artarak 4,57 trilyon TL oldu.",
                    "official": True,
                    "relevance_score": 20,
                }
            ],
        ):
            result = run_agent_turn(
                "2025 e-ticaret raporundaki sayisal egilimleri webden acikla",
                planner_client=lambda _prompt: '{"mode":"tool","tool":"web.search","arguments":{"query":"2025 e-ticaret raporu","limit":5}}',
                chat_client=chat_client,
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertGreaterEqual(len(prompts), 2)
        answer = str((result.data or {}).get("answer") or "")
        self.assertNotIn("yuzde 99", answer)
        self.assertNotIn("12 trilyon", answer)
        self.assertIn("52,2", answer)
        self.assertIn("4,57", answer)

    def test_web_answer_grounding_normalizes_decimal_comma_and_rejects_new_numbers(self) -> None:
        tool_results = [
            {
                "tool": "web.search",
                "data": {
                    "results": [
                        {
                            "title": "Official report 2025",
                            "snippet": "Hacim %52,2 artarak 4,57 trilyon TL oldu.",
                            "content_excerpt": "",
                        }
                    ]
                },
            }
        ]

        self.assertTrue(
            ai_agent._web_answer_grounded(
                "2025 raporunda:\n1. Hacim %52.2 artarak 4.57 trilyon TL oldu.\n2. Buyume surdu.",
                tool_results,
            )
        )
        self.assertFalse(
            ai_agent._web_answer_grounded(
                "2025 raporunda hacim %71 artarak 8 trilyon TL oldu.",
                tool_results,
            )
        )

    def test_news_web_grounding_accepts_published_dates_and_source_names(self) -> None:
        tool_results = [
            {
                "tool": "web.search",
                "data": {
                    "results": [
                        {
                            "title": "Yapay zeka haberi",
                            "url": "https://news.google.com/article",
                            "snippet": "Haber kaynagi: Example News",
                            "source": "Example News",
                            "published_date": "2026-06-24",
                        }
                    ]
                },
            }
        ]

        self.assertTrue(
            ai_agent._web_answer_grounded(
                "24 Haziran 2026 tarihinde Example News yapay zeka gelismesini duyurdu.",
                tool_results,
            )
        )

    def test_web_grounding_allows_numbers_explicitly_supplied_by_user(self) -> None:
        tool_results = [
            {
                "tool": "web.search",
                "data": {
                    "results": [
                        {
                            "title": "Official printer catalog",
                            "snippet": "Termal etiket yazici katalogu.",
                        }
                    ]
                },
            }
        ]

        self.assertTrue(
            ai_agent._web_answer_grounded(
                "2026 icin termal etiket yazici secenekleri bunlardir.",
                tool_results,
                user_message="2026 icin termal etiket yazici karsilastirmasi yap",
            )
        )

    def test_llm_web_search_private_query_is_repaired_before_network(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_search(query: str, *, limit: int) -> list[dict[str, str]]:
            calls.append((query, limit))
            return [{"title": "Should not run", "url": "https://example.invalid"}]

        with patch("AI.processors.tools._public_web_search", side_effect=fake_search):
            result = run_agent_turn(
                "Trendyol iade kargo kurallarini guncel webde ara",
                planner_client=lambda _prompt: (
                    '{"mode":"tool","tool":"web.search","arguments":{"query":"CLAIM-PRIVATE-12345678 Mahmut musteri iadesi webde ara","limit":5}}'
                ),
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "web.search")
        self.assertEqual(len(calls), 1)
        self.assertIn("Trendyol", calls[0][0])
        self.assertNotIn("CLAIM-PRIVATE-12345678", calls[0][0])
        self.assertNotIn("Mahmut", calls[0][0])

    def test_bulk_cargo_and_label_prepare_tools_execute_through_manual_adapters(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-bulk",
                    comp_name="Bulk Test Seller",
                    platform="trendyol",
                    api_key="api-key",
                    api_secret="api-secret",
                )
            )
            for index in range(2):
                order_no = f"ORD-BULK-{index + 1}"
                session.add(OrderHeader(orderNumber=order_no, api_account_id=1))
                session.add(
                    OrderData(
                        orderNumber=order_no,
                        id=910000 + index,
                        shipmentPackageId=910000 + index,
                        api_account_id=1,
                        orderDate=now_ms + index,
                        lastModifiedDate=now_ms + index,
                        shipmentPackageStatus="ReadyToShip",
                        cargoProviderName="Aras Kargo",
                    )
                )
            session.commit()

        registry = available_tools()
        bulk_prepare = registry["orders.change_cargo_provider_bulk.prepare"].handler(
            db_name=self.db_path,
            query="ORD-BULK",
            cargo_provider="Aras",
        )
        label_prepare = registry["labels.create_from_orders.prepare"].handler(
            db_name=self.db_path,
            query="ORD-BULK",
        )

        self.assertTrue(bulk_prepare.success, bulk_prepare.message)
        self.assertTrue(label_prepare.success, label_prepare.message)
        bulk_action = (bulk_prepare.data or {}).get("action") or {}
        label_action = (label_prepare.data or {}).get("action") or {}
        self.assertTrue(bulk_action.get("execute_enabled"), bulk_action)
        self.assertTrue(label_action.get("execute_enabled"), label_action)
        self.assertEqual(bulk_action.get("action_type"), "orders.change_orders_cargo_provider_bulk")
        self.assertEqual(label_action.get("action_type"), "labels.action_create_labels_from_selected_orders")

        from Labels.processors import pipeline as labels_pipeline
        from Orders.views import actions as orders_actions

        bulk_calls: list[dict[str, object]] = []
        label_calls: list[dict[str, object]] = []

        def _fake_bulk_change(orders, *, cargo_provider_code: str) -> Result:
            expected_provider = str(((bulk_action.get("rows") or [{}])[0].get("after") or {}).get("cargo_provider") or "").strip() or "Aras"
            with Session(get_engine(self.db_path)) as session:
                for order in orders:
                    record = session.exec(select(OrderData).where(OrderData.orderNumber == getattr(order, "orderNumber", ""))).first()
                    if record is not None:
                        record.cargoProviderName = expected_provider
                        session.add(record)
                session.commit()
            bulk_calls.append({"orders": [getattr(order, "orderNumber", "") for order in orders], "cargo_provider_code": cargo_provider_code})
            return Result.ok("Bulk cargo fake tamam.", close_dialog=False, data={"count": len(orders), "cargo_provider_code": cargo_provider_code})

        def _fake_labels(
            order_numbers,
            *,
            brand_code="TANEX",
            model_code="TANEX_2736",
            db_name=None,
        ) -> Result:
            label_calls.append(
                {
                    "order_numbers": list(order_numbers),
                    "brand_code": brand_code,
                    "model_code": model_code,
                    "db_name": db_name,
                }
            )
            return Result.ok("Labels fake tamam.", close_dialog=False, data={"order_numbers": list(order_numbers)})

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(orders_actions, "change_orders_cargo_provider_bulk", _fake_bulk_change), patch.object(
                labels_pipeline, "create_order_label_from_orders", _fake_labels
            ):
                bulk_result = operation_runtime.execute_approved_operation(bulk_action, idempotency_key="bulk-cargo", audit_path=audit_path)
                label_result = operation_runtime.execute_approved_operation(label_action, idempotency_key="label-create", audit_path=audit_path)

            self.assertTrue(bulk_result.success, bulk_result.message)
            self.assertTrue(label_result.success, label_result.message)
            self.assertEqual(label_calls[0].get("db_name"), self.db_path)
            self.assertEqual(bulk_calls, [{"orders": ["ORD-BULK-1", "ORD-BULK-2"], "cargo_provider_code": "ARASMP"}])
            self.assertEqual(
                label_calls,
                [
                    {
                        "order_numbers": ["ORD-BULK-1", "ORD-BULK-2"],
                        "brand_code": "TANEX",
                        "model_code": "TANEX_2736",
                        "db_name": self.db_path,
                    }
                ],
            )
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "orders.change_orders_cargo_provider_bulk"', audit_text)
            self.assertIn('"operation": "labels.action_create_labels_from_selected_orders"', audit_text)

    def test_label_execute_exports_word_file_when_payload_is_available(self) -> None:
        from Orders.processors.trendyol import pipeline as orders_pipeline

        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        order_numbers = ["ORD-REAL-LABEL-1", "ORD-REAL-LABEL-2"]
        for index, order_number in enumerate(order_numbers, start=1):
            package_id = 81_000 + index
            self._insert_order_snapshot(
                order_number,
                now_ms + index,
                package_id=package_id,
                status="ReadyToShip",
                cargo_tracking_number=f"TRK-REAL-LABEL-{index}",
                cargo_provider_name="Trendyol Express",
                total_price=100.0 + index,
            )
            with Session(get_engine(self.db_path)) as session:
                header = session.exec(select(OrderHeader).where(OrderHeader.orderNumber == order_number)).one()
                snapshot = session.exec(select(OrderData).where(OrderData.orderNumber == order_number)).one()
                snapshot.customerFirstName = "Gercek"
                snapshot.customerLastName = f"Etiket {index}"
                snapshot.shipmentAddress = {
                    "fullAddress": f"Test Mahallesi {index}. Sokak No:{index}",
                    "district": "Kadikoy",
                    "city": "Istanbul",
                    "postalCode": "34710",
                }
                snapshot.agreedDeliveryDate = now_ms + 86_400_000
                session.add(snapshot)
                session.add(
                    OrderItem(
                        order_header_id=header.pk,
                        orderNumber=order_number,
                        order_data_pk=snapshot.pk,
                        order_data_id=package_id,
                        snapshotLastModifiedDate=snapshot.lastModifiedDate,
                        quantity=index,
                        merchantSku=f"GERCEK-URUN-{index}",
                        productName=f"Gercek Etiket Urunu {index}",
                        barcode=f"86900000000{index}",
                        orderLineItemStatusName="Created",
                        lineId=91_000 + index,
                    )
                )
                session.commit()

        registry = available_tools()
        prepared = registry["labels.create_from_orders.prepare"].handler(
            db_name=self.db_path,
            order_numbers=order_numbers,
        )
        self.assertTrue(prepared.success, prepared.message)
        action = (prepared.data or {}).get("action") or {}
        action["warnings"] = []
        action["execute_enabled"] = True
        action["arguments"] = {
            "payload": {
                "order_numbers": order_numbers,
                "brand_code": "TANEX",
                "model_code": "TANEX_2736",
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            orders_pipeline,
            "DB_NAME",
            self.db_path,
        ):
            orders_pipeline._ENGINE = None
            orders_pipeline._ENGINE_DB_NAME = None
            output_path = Path(tmp_dir) / "agent-labels.docx"
            action["arguments"]["payload"]["output_path"] = str(output_path)
            executed = operation_runtime.execute_approved_operation(
                action,
                idempotency_key="label-export-file",
                audit_path=Path(tmp_dir) / "audit.jsonl",
            )
            self.assertTrue(executed.success, executed.message)
            result_data = (executed.data or {}).get("result") or {}
            verify = (executed.data or {}).get("verify") or {}
            self.assertEqual(result_data.get("output_path"), str(output_path))
            self.assertTrue(verify.get("verified"), executed.data)
            self.assertEqual(verify.get("verified_by"), "payload_and_docx_content")
            self.assertTrue(verify.get("docx_order_numbers_verified"))
            self.assertEqual(verify.get("order_numbers"), order_numbers)
            self.assertGreater(int(verify.get("size_bytes") or 0), 1_000)
            self.assertTrue(zipfile.is_zipfile(output_path))
            with zipfile.ZipFile(output_path) as archive:
                self.assertIn("word/document.xml", archive.namelist())
                document_xml = archive.read("word/document.xml").decode("utf-8")
            for order_number in order_numbers:
                self.assertIn(order_number, document_xml)
            audit_text = (Path(tmp_dir) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("labels.action_create_labels_from_selected_orders", audit_text)

    def test_label_execute_verifies_all_selected_orders_above_twenty_in_docx(self) -> None:
        order_numbers = [f"ORD-BULK-LABEL-{index:02d}" for index in range(1, 23)]
        create_calls: list[dict[str, Any]] = []
        export_calls: list[dict[str, Any]] = []

        def _fake_create_order_label_from_orders(order_numbers_arg, *, brand_code="TANEX", model_code="TANEX_2736", db_name=None):
            selected = list(order_numbers_arg)
            create_calls.append({"order_numbers": selected, "brand_code": brand_code, "model_code": model_code})
            return Result.ok(
                "Labels fake tamam.",
                close_dialog=False,
                data={
                    "order_numbers": selected,
                    "label_payload": {
                        "labels": [{"order_number": order_number} for order_number in selected],
                    },
                },
            )

        def _fake_export_labels_to_word(*, label_payload, brand_code="TANEX", model_code="TANEX_2736", output_path):
            selected = [str(row.get("order_number")) for row in list(label_payload.get("labels") or [])]
            export_calls.append({"order_numbers": selected, "brand_code": brand_code, "model_code": model_code})
            with zipfile.ZipFile(output_path, "w") as archive:
                archive.writestr("word/document.xml", "<w:document>" + " ".join(selected) + "</w:document>")
            return Result.ok("Word fake tamam.", close_dialog=False, data={"output_path": str(output_path)})

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            labels_pipeline,
            "create_order_label_from_orders",
            _fake_create_order_label_from_orders,
        ), patch.object(labels_pipeline, "export_labels_to_word", _fake_export_labels_to_word):
            output_path = Path(tmp_dir) / "bulk-labels.docx"
            action = {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "approval_required": True,
                "execute_enabled": True,
                "warnings": [],
                "arguments": {
                    "payload": {
                        "order_numbers": order_numbers,
                        "brand_code": "TANEX",
                        "model_code": "TANEX_2736",
                        "output_path": str(output_path),
                    }
                },
            }
            executed = operation_runtime.execute_approved_operation(
                action,
                idempotency_key="bulk-label-export-file",
                audit_path=Path(tmp_dir) / "audit.jsonl",
            )

            self.assertTrue(executed.success, executed.message)
            verify = (executed.data or {}).get("verify") or {}
            self.assertEqual(create_calls, [{"order_numbers": order_numbers, "brand_code": "TANEX", "model_code": "TANEX_2736"}])
            self.assertEqual(export_calls, [{"order_numbers": order_numbers, "brand_code": "TANEX", "model_code": "TANEX_2736"}])
            self.assertEqual(verify.get("order_numbers"), order_numbers)
            self.assertEqual(verify.get("verified_by"), "payload_and_docx_content")
            self.assertTrue(verify.get("docx_order_numbers_verified"))

    def test_label_verify_rejects_docx_missing_expected_order_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "labels-missing-order.docx"
            with zipfile.ZipFile(output_path, "w") as archive:
                archive.writestr("word/document.xml", "<w:document>ORD-DOCX-1</w:document>")
            action = {
                "arguments": {
                    "payload": {
                        "order_numbers": ["ORD-DOCX-1", "ORD-DOCX-2"],
                        "output_path": str(output_path),
                    }
                }
            }

            verified = operation_runtime.verify_labels_create(action)

            self.assertFalse(verified.success)
            self.assertIn("docx icinde", verified.message)
            self.assertEqual((verified.data or {}).get("missing_order_numbers"), ["ORD-DOCX-2"])

    def test_return_approve_prepare_executes_manual_approval_adapter(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-return",
                    comp_name="Return Test Seller",
                    platform="trendyol",
                    api_key="api-key",
                    api_secret="api-secret",
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-APPROVE-1",
                    orderNumber="ORD-APPROVE-1",
                    api_account_id=1,
                    claimDate=now_ms,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    claimItemStatus="WaitingInAction",
                    totalPrice=123.0,
                    itemCount=1,
                    waitingClaimLineItemIds=["line-approve-1"],
                )
            )
            session.commit()

        registry = available_tools()
        prepare = registry["returns.approve.prepare"].handler(db_name=self.db_path, query="CLAIM-APPROVE-1")

        self.assertTrue(prepare.success, prepare.message)
        action = (prepare.data or {}).get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)
        self.assertTrue(action.get("external_write"))
        self.assertTrue(action.get("destructive"))
        self.assertEqual(action.get("action_type"), "orders.approve_return_claim")

        from Orders.views import actions as orders_actions

        calls: list[dict[str, object]] = []

        def _fake_approve_return_claim(order, *, date_from=None, date_to=None) -> Result:
            with Session(get_engine(self.db_path)) as session:
                record = session.exec(select(ReturnClaim).where(ReturnClaim.claimId == "CLAIM-APPROVE-1")).first()
                if record is not None:
                    record.claimItemStatus = "Accepted"
                    record.waitingClaimLineItemIds = []
                    session.add(record)
                    session.commit()
            calls.append(
                {
                    "claim_id": getattr(order, "claimId", ""),
                    "api_account": getattr(getattr(order, "api_account", None), "account_id", ""),
                    "waiting": list(getattr(order, "waitingClaimLineItemIds", []) or []),
                }
            )
            return Result.ok("Return approve fake tamam.", close_dialog=False, data={"claim_id": getattr(order, "claimId", "")})

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            with patch.object(orders_actions, "approve_return_claim", _fake_approve_return_claim):
                executed = operation_runtime.execute_approved_operation(action, idempotency_key="return-approve", audit_path=audit_path)

            self.assertTrue(executed.success, executed.message)
            self.assertEqual(calls, [{"claim_id": "CLAIM-APPROVE-1", "api_account": "seller-return", "waiting": ["line-approve-1"]}])
            self.assertIn('"operation": "orders.approve_return_claim"', audit_path.read_text(encoding="utf-8"))

    def test_restore_stale_return_claim_executes_and_verifies_active_latest(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-stale", comp_name="Stale Seller", platform="trendyol"))
            session.add(
                ReturnClaim(
                    claimId="CLAIM-RESTORE-1",
                    orderNumber="ORD-RESTORE-1",
                    api_account_id=1,
                    claimDate=now_ms,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    claimItemStatus="WaitingInAction",
                    sync_deleted_at="2026-01-01T00:00:00+03:00",
                )
            )
            session.commit()

        action = {
            "action_type": "orders.restore_return_claims_from_stale",
            "approval_required": True,
            "execute_enabled": True,
            "arguments": {
                "payload": {
                    "claim_ids": ["CLAIM-RESTORE-1"],
                    "api_account_ids": [1],
                    "db_name": self.db_path,
                    "reason": "agent restore verify test",
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "restore-audit.jsonl"
            executed = operation_runtime.execute_approved_operation(
                action,
                approved_by="restore-test",
                idempotency_key="restore-stale-claim",
                audit_path=audit_path,
            )

            self.assertTrue(executed.success, executed.message)
            verify = (executed.data or {}).get("verify") or {}
            self.assertTrue(verify.get("verified"))
            self.assertEqual(verify.get("active_claim_ids"), ["CLAIM-RESTORE-1"])
            self.assertIn('"operation": "orders.restore_return_claims_from_stale"', audit_path.read_text(encoding="utf-8"))

    def test_operation_coverage_report_tracks_manual_write_execute_surface(self) -> None:
        report = operation_runtime.operation_coverage_report()
        expected_orders_read_ids = {
            "orders.action_list_item_balances",
            "orders.action_list_items",
            "orders.fetch_orders_all",
            "orders.get_latest_order_items_by_numbers",
            "orders.get_latest_orders",
            "orders.get_latest_orders_filtered",
            "orders.get_latest_ready_to_ship_orders",
            "orders.get_latest_return_claims",
            "orders.get_latest_return_claims_filtered",
            "orders.get_listings_from_db",
            "orders.get_nonfinal_order_numbers",
            "orders.get_order_date",
            "orders.get_stale_return_claims",
            "orders.list_changeable_cargo_providers",
            "orders.load_finance_cost_items",
            "orders.load_logistics_cargo_tariffs",
            "orders.load_order_items_for_order_number",
            "orders.load_order_items_for_order_numbers",
            "orders.load_order_profit_catalog",
            "orders.load_orders_by_numbers",
            "orders.load_orders_for_source_filters",
            "orders.load_orders_for_status_filter",
            "orders.load_ready_to_ship_orders",
            "orders.load_returns_claims",
            "orders.load_returns_for_source_filters",
            "orders.load_returns_from_db",
        }
        expected_orders_write_ids = {
            "orders.action_export_report_snapshot_xlsx",
            "orders.action_export_order_profit_excel",
            "orders.approve_return_claim",
            "orders.change_order_cargo_provider",
            "orders.change_orders_cargo_provider_bulk",
            "orders.get_orders_from_companies",
            "orders.mark_return_claims_stale",
            "orders.restore_return_claims_from_stale",
            "orders.save_return_claims_to_db",
            "orders.update_last_used_at_for_accounts",
        }

        self.assertGreater(int(report.get("manual_write_total") or 0), 20)
        self.assertGreater(int(report.get("generic_execute_safe_total") or 0), 10)
        self.assertEqual(int(report.get("generic_execute_blocked_total")), 0)
        self.assertEqual(int(report.get("generic_read_blocked_total")), 1)
        self.assertEqual(int(report.get("manual_execute_adapter_total") or 0), 14)
        self.assertIn("stock.item_create", report.get("specialized_execute_action_types") or {})
        safe_ids = {row.get("capability_id") for row in report.get("generic_execute_safe") or []}
        self.assertIn("account.delete_company_and_refresh", safe_ids)
        self.assertIn("stock.action_create_warehouse", safe_ids)
        self.assertIn("stock.action_create_company", safe_ids)
        self.assertIn("stock.action_manual_in", safe_ids)
        self.assertIn("stock.action_manual_out", safe_ids)
        self.assertIn("stock.action_export_txs_excel", safe_ids)
        self.assertIn("finance.action_sync_finance_for_accounts", safe_ids)
        self.assertIn("finance.action_sync_finance_for_selected_companies", safe_ids)
        self.assertIn("labels.action_create_labels_from_selected_orders", safe_ids)
        self.assertIn("labels.mark_orders_extracted_from_label_result", safe_ids)
        self.assertIn("listing.action_fetch_listings", safe_ids)
        self.assertIn("listing.action_update_approved_content_for_account", safe_ids)
        self.assertIn("listing.action_update_price_inventory_for_account", safe_ids)
        self.assertIn("orders.get_orders_from_companies", safe_ids)
        self.assertIn("orders.save_return_claims_to_db", safe_ids)
        self.assertIn("orders.mark_return_claims_stale", safe_ids)
        self.assertIn("orders.restore_return_claims_from_stale", safe_ids)
        self.assertIn("orders.update_last_used_at_for_accounts", safe_ids)
        self.assertIn("orders.action_export_order_profit_excel", safe_ids)
        self.assertIn("orders.change_order_cargo_provider", safe_ids)
        self.assertIn("orders.change_orders_cargo_provider_bulk", safe_ids)
        orders_domain = (report.get("domains") or {}).get("orders") or {}
        listing_domain = (report.get("domains") or {}).get("listing") or {}
        self.assertEqual(set(orders_domain.get("read_capability_ids") or []), expected_orders_read_ids)
        self.assertEqual(set(orders_domain.get("write_capability_ids") or []), expected_orders_write_ids)
        self.assertEqual(set(orders_domain.get("generic_execute_safe_ids") or []), expected_orders_write_ids)
        self.assertEqual(set(orders_domain.get("generic_execute_blocked_ids") or []), set())
        self.assertEqual(set(orders_domain.get("generic_read_blocked_ids") or []), {"orders.fetch_orders_all"})
        listing_writes = {
            row.get("capability_id"): row
            for row in report.get("generic_execute_safe") or []
            if str(row.get("capability_id") or "").startswith("listing.")
        }
        self.assertTrue(listing_writes["listing.action_fetch_listings"].get("external_write"))
        self.assertTrue(listing_writes["listing.action_update_approved_content_for_account"].get("external_write"))
        self.assertTrue(listing_writes["listing.action_update_price_inventory_for_account"].get("external_write"))
        self.assertIn(
            "listing.action_fetch_listings",
            set(listing_domain.get("generic_execute_safe_ids") or []),
        )
        self.assertIn(
            "listing.action_update_approved_content_for_account",
            set(listing_domain.get("generic_execute_safe_ids") or []),
        )
        self.assertIn(
            "listing.action_update_price_inventory_for_account",
            set(listing_domain.get("generic_execute_safe_ids") or []),
        )
        blocked_ids = {row.get("capability_id") for row in report.get("generic_execute_blocked") or []}
        self.assertEqual(blocked_ids, set())
        read_ids = {row.get("capability_id") for row in report.get("generic_read_safe") or []}
        self.assertIn("account.get_platform_enabled_fields", read_ids)
        self.assertNotIn("orders.fetch_orders_all", read_ids)
        self.assertNotIn("stock.action_manual_in", read_ids)

    def test_listing_fetch_execute_saves_verifies_db_without_secret_audit(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ApiAccount(
                    pk=1,
                    account_id="seller-fetch",
                    comp_name="Listing Fetch Seller",
                    platform="trendyol",
                    api_key="listing-fetch-api-key",
                    api_secret="listing-fetch-api-secret",
                    extra_config={"acceptLanguage": "tr-TR"},
                )
            )
            session.commit()

        captured_accounts: list[list[Any]] = []

        async def fake_fetch_listings(comp_api_account_list: list, **kwargs: Any) -> Result:
            captured_accounts.extend([list(row) for row in comp_api_account_list])
            return Result.ok(
                "Fake listing fetch ok.",
                close_dialog=False,
                data={
                    "items": [
                        {
                            "api_account_id": 1,
                            "productId": "LISTING-FETCH-1",
                            "productCode": "PC-FETCH-1",
                            "title": "Agent Fetch Ilani",
                            "barcode": "BAR-FETCH-1",
                            "stockCode": "STK-FETCH-1",
                            "brand": {"name": "AgentBrand"},
                            "category": {"name": "Mutfak"},
                            "quantity": 4,
                            "listPrice": 199.9,
                            "salePrice": 179.9,
                            "approved": True,
                            "archived": False,
                            "onSale": True,
                        }
                    ],
                    "api_account_ids": [1],
                    "total_items": 1,
                    "kwargs": kwargs,
                },
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "listing-fetch-audit.jsonl"
            action = {
                "action_type": "listing.action_fetch_listings",
                "approval_required": True,
                "execute_enabled": True,
                "warnings": [],
                "arguments": {
                    "payload": {
                        "api_account_ids": [1],
                        "db_name": self.db_path,
                        "page": 0,
                        "size": 1000,
                        "fetch_all_pages": True,
                    }
                },
            }

            with patch("Listing.views.actions.action_fetch_listings", fake_fetch_listings):
                result = operation_runtime.execute_approved_operation(
                    action,
                    approved_by="listing-fetch-test",
                    idempotency_key="listing-fetch-save-verify",
                    audit_path=audit_path,
                )

            self.assertTrue(result.success, result.message)
            self.assertEqual(
                captured_accounts,
                [[1, "listing-fetch-api-key", "listing-fetch-api-secret", "seller-fetch", "tr-TR", "production"]],
            )
            self.assertEqual(((result.data or {}).get("verify") or {}).get("verified_by"), "db")
            self.assertEqual(((result.data or {}).get("verify") or {}).get("product_ids"), ["LISTING-FETCH-1"])

            with Session(get_engine(self.db_path)) as session:
                listing = session.exec(
                    select(ListingProduct).where(ListingProduct.product_id == "LISTING-FETCH-1")
                ).first()
                self.assertIsNotNone(listing)
                self.assertEqual(listing.title, "Agent Fetch Ilani")
                self.assertEqual(float(listing.quantity or 0), 4.0)
                self.assertEqual(float(listing.sale_price or 0), 179.9)

            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "listing.action_fetch_listings"', audit_text)
            self.assertIn('"verified_by": "db"', audit_text)
            self.assertNotIn("listing-fetch-api-key", audit_text)
            self.assertNotIn("listing-fetch-api-secret", audit_text)

    def test_listing_local_writes_execute_verify_with_db_and_audit(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-listing", comp_name="Listing Seller", platform="trendyol"))
            stock_item = StockItem(sku="SKU-LISTING-AGENT", name="Agent Listing Stock", barcode="BAR-LISTING-STOCK")
            session.add(stock_item)
            session.add(
                FinanceCostItem(
                    pk=401,
                    costKey="paketleme",
                    name="Paketleme",
                    valueType="numeric",
                    createdAt="2026-06-15T10:00:00",
                    updatedAt="2026-06-15T10:00:00",
                )
            )
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LISTING-AGENT-1",
                    title="Agent Listing Urunu",
                    barcode="BAR-LISTING-1",
                    stock_code="STK-LISTING-1",
                    brand="AgentBrand",
                    quantity=3.0,
                    approved=True,
                    archived=False,
                    on_sale=True,
                    list_price=120.0,
                    sale_price=99.0,
                )
            )
            session.commit()
            stock_item_pk = int(stock_item.pk or 0)

        def _action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "action_type": action_type,
                "approval_required": True,
                "execute_enabled": True,
                "warnings": [],
                "arguments": {"payload": {**payload, "db_name": self.db_path}},
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "listing-local-writes-audit.jsonl"

            cache = operation_runtime.execute_approved_operation(
                _action(
                    "listing.action_update_listing_price_inventory_cache",
                    {
                        "api_account_id": 1,
                        "product_id": "LISTING-AGENT-1",
                        "quantity": 8.0,
                        "list_price": 155.0,
                        "sale_price": 144.0,
                    },
                ),
                approved_by="listing-test",
                idempotency_key="listing-cache-write",
                audit_path=audit_path,
            )
            self.assertTrue(cache.success, cache.message)
            self.assertEqual(((cache.data or {}).get("verify") or {}).get("verified_by"), "db")

            stock_link = operation_runtime.execute_approved_operation(
                _action(
                    "listing.action_set_listing_stock_items",
                    {
                        "api_account_id": 1,
                        "product_id": "LISTING-AGENT-1",
                        "stock_items": [{"stock_item_id": stock_item_pk, "qty": 2}],
                    },
                ),
                approved_by="listing-test",
                idempotency_key="listing-stock-link",
                audit_path=audit_path,
            )
            self.assertTrue(stock_link.success, stock_link.message)
            self.assertEqual(((stock_link.data or {}).get("verify") or {}).get("verified_by"), "db")

            cost_link = operation_runtime.execute_approved_operation(
                _action(
                    "listing.action_set_listing_cost_items",
                    {
                        "api_account_id": 1,
                        "product_id": "LISTING-AGENT-1",
                        "cost_items": [
                            {
                                "cost_key": "paketleme",
                                "source_type": "manual_value",
                                "source_config": {"amount": 7.5},
                                "amount": 7.5,
                            }
                        ],
                    },
                ),
                approved_by="listing-test",
                idempotency_key="listing-cost-link",
                audit_path=audit_path,
            )
            self.assertTrue(cost_link.success, cost_link.message)
            self.assertEqual(((cost_link.data or {}).get("verify") or {}).get("verified_by"), "db")

            cost_sync = operation_runtime.execute_approved_operation(
                _action(
                    "listing.action_sync_listing_cost_snapshots_for_item",
                    {
                        "item": {
                            "api_account_id": 1,
                            "productId": "LISTING-AGENT-1",
                            "cost_items": [
                                {
                                    "cost_key": "paketleme",
                                    "source_type": "manual_value",
                                    "source_config": {"amount": 7.5},
                                    "amount": 7.5,
                                }
                            ],
                        },
                        "estimation": {
                            "estimated_profit_detail": {
                                "applied_costs": [
                                    {
                                        "key": "paketleme",
                                        "source_type": "manual_value",
                                        "gross": 7.5,
                                        "net": 6.25,
                                        "vat": 1.25,
                                        "note": "manual",
                                        "source_trace": {"sourceConfig": {"amount": 7.5}},
                                    }
                                ]
                            }
                        },
                    },
                ),
                approved_by="listing-test",
                idempotency_key="listing-cost-sync",
                audit_path=audit_path,
            )
            self.assertTrue(cost_sync.success, cost_sync.message)
            self.assertEqual(((cost_sync.data or {}).get("verify") or {}).get("verified_by"), "db")

            with Session(get_engine(self.db_path)) as session:
                listing = session.exec(
                    select(ListingProduct).where(ListingProduct.product_id == "LISTING-AGENT-1")
                ).first()
                self.assertIsNotNone(listing)
                self.assertEqual(float(listing.quantity or 0), 8.0)
                self.assertEqual(float(listing.list_price or 0), 155.0)
                self.assertEqual(float(listing.sale_price or 0), 144.0)
                stock_rows = session.exec(
                    select(ListingProductStockSnapshot).where(ListingProductStockSnapshot.listing_id == listing.pk)
                ).all()
                self.assertTrue(any(int(row.stock_item_id) == stock_item_pk and float(row.qty) == 2.0 for row in stock_rows))
                cost_rows = session.exec(
                    select(ListingProductCostSnapshot).where(ListingProductCostSnapshot.listing_id == listing.pk)
                ).all()
                self.assertTrue(any(str(row.cost_key).casefold() == "paketleme" for row in cost_rows))
                self.assertTrue(any(float(row.resolved_amount or 0.0) == 7.5 for row in cost_rows))

            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn('"operation": "listing.action_update_listing_price_inventory_cache"', audit_text)
            self.assertIn('"operation": "listing.action_set_listing_stock_items"', audit_text)
            self.assertIn('"operation": "listing.action_set_listing_cost_items"', audit_text)
            self.assertIn('"operation": "listing.action_sync_listing_cost_snapshots_for_item"', audit_text)

    def test_raw_orders_fetch_helper_is_not_generic_read_executable(self) -> None:
        result = operation_runtime.execute_manual_read_action(
            capability_id="orders.fetch_orders_all",
            payload={},
            db_name=self.db_path,
        )

        self.assertFalse(result.success)
        self.assertIn("orders.get_orders_from_companies", result.message)

    def test_orders_ui_click_handlers_are_classified_in_agentic_parity_matrix(self) -> None:
        root = Path(__file__).resolve().parents[2]
        view_files = (
            Path("Orders/views/views.py"),
            Path("Orders/views/orders_manager_window.py"),
            Path("Orders/views/returns_manager_window.py"),
        )
        binding_re = re.compile(
            r"(?P<sender>(?:self\.)?[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)"
            r"\.clicked\.connect\((?P<target>[^\n]+?)\)"
        )

        actual: set[tuple[str, str, str]] = set()
        for rel_path in view_files:
            source = (root / rel_path).read_text(encoding="utf-8")
            for match in binding_re.finditer(source):
                actual.add(
                    (
                        rel_path.as_posix(),
                        match.group("sender").strip(),
                        match.group("target").strip(),
                    )
                )

        operational = {
            ("Orders/views/views.py", "self.fetch_button", "self.get_orders"): "Veri Cek",
            ("Orders/views/orders_manager_window.py", "export_excel", "self._export_to_excel"): "Order profit Excel export",
            (
                "Orders/views/orders_manager_window.py",
                "self.btn_change_cargo_provider",
                "self._on_change_cargo_provider_clicked",
            ): "Detail cargo change",
            (
                "Orders/views/orders_manager_window.py",
                "self.btn_detail_print",
                "self._on_action_button_clicked",
            ): "Detail/bulk print labels",
            (
                "Orders/views/orders_manager_window.py",
                "self.btn_approve_return",
                "self._on_approve_return_clicked",
            ): "Approve return",
            (
                "Orders/views/orders_manager_window.py",
                "self.btn_bulk_change_cargo_provider",
                "self._on_change_bulk_cargo_provider_clicked",
            ): "Bulk cargo change",
            (
                "Orders/views/orders_manager_window.py",
                "self.btn_bulk_print",
                "self._on_action_button_clicked",
            ): "Detail/bulk print labels",
            (
                "Orders/views/returns_manager_window.py",
                "self.btn_approve_return",
                "self._on_approve_return_clicked",
            ): "Approve return",
            (
                "Orders/views/returns_manager_window.py",
                "self.btn_show_stale_returns",
                "self._on_show_stale_returns_clicked",
            ): "Review stale returns",
            (
                "Orders/views/returns_manager_window.py",
                "self.btn_restore_stale_return",
                "self._on_restore_stale_return_clicked",
            ): "Restore stale returns",
        }
        ui_only = {
            ("Orders/views/views.py", "hero.action_button", "self.open_orders_window"),
            ("Orders/views/views.py", "self.btn_add_company", "self._open_company_manager_from_fetch_panel"),
            ("Orders/views/views.py", "self.auto_fetch_toggle", "self._toggle_auto_fetch"),
            ("Orders/views/views.py", "self.order_btn", "self.open_orders_window"),
            ("Orders/views/views.py", "self.return_btn", "self.open_returns_window"),
            ("Orders/views/orders_manager_window.py", "self.detail_btn", "self.detailRequested.emit"),
            ("Orders/views/orders_manager_window.py", "self.btn_export", "self._toggle_export_drawer"),
            ("Orders/views/orders_manager_window.py", "self.profit_panel", "self._toggle_summary_expanded"),
            ("Orders/views/orders_manager_window.py", "self.missing_panel", "self._toggle_missing_expanded"),
            ("Orders/views/orders_manager_window.py", "self.btn_close", "self.close"),
            ("Orders/views/orders_manager_window.py", "self.btn_clear_filters", "self._clear_filters_and_apply"),
            ("Orders/views/returns_manager_window.py", "self.btn_change_cargo_provider", "self._on_change_cargo_provider_clicked"),
            ("Orders/views/returns_manager_window.py", "self.btn_detail_print", "self._on_action_button_clicked"),
            (
                "Orders/views/returns_manager_window.py",
                "self.btn_bulk_change_cargo_provider",
                "self._on_change_bulk_cargo_provider_clicked",
            ),
            ("Orders/views/returns_manager_window.py", "self.btn_bulk_print", "self._on_action_button_clicked"),
            ("Orders/views/returns_manager_window.py", "self.btn_clear_filters", "self._clear_filters_and_apply"),
        }

        def _is_dynamic_ui_only(binding: tuple[str, str, str]) -> bool:
            _rel_path, sender, target = binding
            return (
                sender == "self"
                or target.startswith("lambda")
                or "_change_detail_page" in target
                or "_change_missing_page" in target
                or "_toggle_detail_tab" in target
                or "_schedule_workspace_editor_refresh" in target
            )

        expected = set(operational) | ui_only
        self.assertEqual(set(operational) - actual, set())
        unknown = {binding for binding in actual - expected if not _is_dynamic_ui_only(binding)}
        self.assertEqual(unknown, set())

        parity_doc = (root / "AI/docs/orders_agentic_parity_matrix.md").read_text(encoding="utf-8")
        for marker in set(operational.values()):
            self.assertIn(marker, parity_doc)
        for marker in (
            "UI-Only Orders Controls",
            "Auto fetch toggle",
            "Navigation and drawer controls",
            "Clear filters and pagination",
            "Returns-mode inherited order controls",
        ):
            self.assertIn(marker, parity_doc)

    def test_operations_manual_action_read_runs_read_only_capability(self) -> None:
        registry = available_tools()
        tool = registry["operations.manual_action.read"]
        self.assertTrue(tool.read_only)
        self.assertFalse(tool.destructive)
        self.assertFalse(tool.requires_approval)

        result = tool.handler(
            capability_id="account.get_platform_enabled_fields",
            payload={"platform": "trendyol"},
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("capability") or {}).get("mode"), "read")
        returned = ((result.data or {}).get("result") or {}).get("return_value")
        self.assertTrue(returned)

    def test_operations_capability_match_maps_natural_language_to_manual_actions(self) -> None:
        registry = available_tools()
        tool = registry["operations.capability_match"]
        self.assertTrue(tool.read_only)
        self.assertFalse(tool.destructive)

        cases = [
            ("depo olustur", "stock.action_create_warehouse", "operations.manual_action.prepare"),
            (
                "depo olusturmak icin hangi capability kullanilir",
                "stock.action_create_warehouse",
                "operations.manual_action.prepare",
            ),
            (
                "depo olu?turmak i?in hangi capability kullan?l?r",
                "stock.action_create_warehouse",
                "operations.manual_action.prepare",
            ),
            ("stok giris yap", "stock.action_manual_in", "operations.manual_action.prepare"),
            ("stok cikis yap", "stock.action_manual_out", "operations.manual_action.prepare"),
            ("barkod uret", "stock.action_generate_unique_barcode", "operations.manual_action.read"),
            (
                "barkod uretmek icin hangi capability kullanilir",
                "stock.action_generate_unique_barcode",
                "operations.manual_action.read",
            ),
            (
                "stok markasi olusturmak icin hangi capability kullanilir",
                "stock.action_create_brand",
                "operations.manual_action.prepare",
            ),
            ("etiket olustur", "labels.action_create_labels_from_selected_orders", "operations.manual_action.prepare"),
            ("hf model indir", "ai.action_download_hf_model", "operations.manual_action.prepare"),
            ("maliyet kalemi kaydet", "finance.save_finance_cost_item", "operations.manual_action.prepare"),
            ("kargo tarife kaydet", "logistics.save_logistics_cargo_tariff", "operations.manual_action.prepare"),
            ("Trendyol Express kargo tarifesini kullanima al", "logistics.accept_logistics_cargo_tariff", "operations.manual_action.prepare"),
            ("Trendyol Express ilk 2 kargo tarifelerini kullanima al", "logistics.accept_logistics_cargo_tariffs", "operations.manual_action.prepare"),
            ("kargo tarife sil", "logistics.delete_logistics_cargo_tariff", "operations.manual_action.prepare"),
            ("Yurtici kargo tarifesini sil", "logistics.delete_logistics_cargo_tariff", "operations.manual_action.prepare"),
            ("Bulk Tarife kargo tarifelerini sil", "logistics.delete_logistics_cargo_tariffs", "operations.manual_action.prepare"),
            ("pazaryeri kaydet", "marketplaces.save_marketplace", "operations.manual_action.prepare"),
            ("Trendyol pazaryerini kaydet", "marketplaces.save_marketplace", "operations.manual_action.prepare"),
            ("Ana Depo icin stok giris hareketi yap", "stock.action_manual_in", "operations.manual_action.prepare"),
            ("test siparis simule et", "testing.action_simulate_orders", "operations.manual_action.prepare"),
            ("firma last used guncelle", "orders.update_last_used_at_for_accounts", "operations.manual_action.prepare"),
            (
                "Aktif pazaryeri hesaplarinin son kullanim zamanini simdi guncelle",
                "orders.update_last_used_at_for_accounts",
                "operations.manual_action.prepare",
            ),
            ("iade claim kaydet", "orders.save_return_claims_to_db", "operations.manual_action.prepare"),
            ("stale iade kaydini isaretle", "orders.mark_return_claims_stale", "operations.manual_action.prepare"),
        ]

        for query, expected_capability, expected_tool in cases:
            result = tool.handler(query=query, limit=5)
            self.assertTrue(result.success, result.message)
            matches = (result.data or {}).get("matches") or []
            self.assertGreater(len(matches), 0, query)
            self.assertEqual(matches[0].get("capability_id"), expected_capability, query)
            self.assertEqual(matches[0].get("suggested_tool"), expected_tool, query)

    def test_agent_fallback_routes_unknown_manual_operation_to_capability_match(self) -> None:
        for prompt, expected_mode in (
            ("depo olustur", "write"),
            ("barkod uret", "read"),
            ("hf model indir", "write"),
            ("maliyet kalemi kaydet", "write"),
            ("kargo tarife sil", "write"),
            ("pazaryeri kaydet", "write"),
            ("test siparis simule et", "write"),
            ("firma last used guncelle", "write"),
            ("iade claim kaydet", "write"),
        ):
            result = choose_tool(prompt)
            self.assertTrue(result.success, result.message)
            decision = (result.data or {}).get("decision")
            self.assertEqual(getattr(decision, "tool_name", None), "operations.manual_action.route")
            self.assertEqual((getattr(decision, "arguments", None) or {}).get("mode"), expected_mode)

    def test_agent_explains_capability_match_next_tool_and_payload(self) -> None:
        result = run_agent_turn("depo olustur", db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.route")
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("stock.action_create_warehouse", answer)
        self.assertIn("operations.manual_action.prepare", answer)
        self.assertIn("name", answer)

    def test_operations_manual_action_route_prepares_write_or_runs_read(self) -> None:
        registry = available_tools()
        tool = registry["operations.manual_action.route"]
        self.assertTrue(tool.read_only)
        self.assertFalse(tool.destructive)

        missing = tool.handler(query="depo olustur")
        self.assertTrue(missing.success, missing.message)
        self.assertEqual((missing.data or {}).get("route_status"), "needs_payload")
        self.assertEqual(((missing.data or {}).get("match") or {}).get("capability_id"), "stock.action_create_warehouse")
        self.assertEqual((missing.data or {}).get("missing_parameters"), ["name"])

        prepared = tool.handler(query="depo olustur", payload={"name": "Agent Depo"})
        self.assertTrue(prepared.success, prepared.message)
        self.assertEqual((prepared.data or {}).get("route_status"), "approval_prepared")
        self.assertTrue((prepared.data or {}).get("approval_required"))
        action = (prepared.data or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "stock.action_create_warehouse")
        self.assertFalse((prepared.data or {}).get("db_write_performed", True))

        inferred = tool.handler(query="Ana Depo adinda depo olustur")
        self.assertTrue(inferred.success, inferred.message)
        self.assertEqual((inferred.data or {}).get("route_status"), "approval_prepared")
        inferred_action = (inferred.data or {}).get("action") or {}
        inferred_args = inferred_action.get("arguments") or {}
        self.assertEqual((inferred_args.get("payload") or {}).get("name"), "Ana Depo")
        self.assertEqual((inferred.data or {}).get("inferred_payload_fields"), ["name"])
        self.assertFalse((inferred.data or {}).get("db_write_performed", True))

        read = tool.handler(db_name=self.db_path, query="barkod uret", payload={"prefix": "869"})
        self.assertTrue(read.success, read.message)
        self.assertEqual((read.data or {}).get("route_status"), "read_executed")
        self.assertEqual(((read.data or {}).get("match") or {}).get("capability_id"), "stock.action_generate_unique_barcode")
        self.assertTrue(((read.data or {}).get("result") or {}).get("barcode"))

        inferred_read = tool.handler(db_name=self.db_path, query="869 prefix ile barkod uret")
        self.assertTrue(inferred_read.success, inferred_read.message)
        self.assertEqual((inferred_read.data or {}).get("route_status"), "read_executed")
        self.assertEqual((inferred_read.data or {}).get("payload"), {"prefix": "869"})
        self.assertEqual((inferred_read.data or {}).get("inferred_payload_fields"), ["prefix"])

        ai_download = tool.handler(query="openai/gpt-oss-20b model-q4_k_m.gguf indir")
        self.assertTrue(ai_download.success, ai_download.message)
        self.assertEqual((ai_download.data or {}).get("route_status"), "approval_prepared")
        self.assertEqual(((ai_download.data or {}).get("match") or {}).get("capability_id"), "ai.action_download_hf_model")
        self.assertEqual(
            (ai_download.data or {}).get("payload"),
            {"repo_id": "openai/gpt-oss-20b", "filename": "model-q4_k_m.gguf"},
        )

        ai_root = tool.handler(query="C:/Models klasorunu ai model indirme klasoru yap")
        self.assertTrue(ai_root.success, ai_root.message)
        self.assertEqual((ai_root.data or {}).get("route_status"), "approval_prepared")
        self.assertEqual(((ai_root.data or {}).get("match") or {}).get("capability_id"), "ai.action_set_ai_download_root")
        self.assertEqual((ai_root.data or {}).get("payload"), {"download_root": "C:/Models"})

        provider = tool.handler(query="Gemini Free adinda openai provider hesabi ekle")
        self.assertTrue(provider.success, provider.message)
        self.assertEqual((provider.data or {}).get("route_status"), "needs_payload")
        self.assertEqual(((provider.data or {}).get("match") or {}).get("capability_id"), "ai.action_save_provider_account")
        self.assertEqual((provider.data or {}).get("payload"), {"provider_code": "openai", "label": "Gemini Free"})
        self.assertEqual((provider.data or {}).get("missing_parameters"), ["api_key"])

    def test_agent_routes_named_manual_write_to_approval_prepare(self) -> None:
        result = run_agent_turn("Ana Depo adinda depo olustur", db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.route")
        tool_result = (result.data or {}).get("tool_result") or {}
        self.assertEqual(tool_result.get("route_status"), "approval_prepared")
        action = tool_result.get("action") or {}
        self.assertEqual(action.get("action_type"), "stock.action_create_warehouse")
        self.assertEqual(((action.get("arguments") or {}).get("payload") or {}).get("name"), "Ana Depo")
        self.assertTrue(tool_result.get("approval_required"))
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertTrue((result.data or {}).get("approval_required"))
        runtime_tool_result = ((result.data or {}).get("tool_results") or [{}])[0]
        self.assertTrue(runtime_tool_result.get("requires_approval"))
        self.assertEqual(runtime_tool_result.get("action_type"), "prepare_write")
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("stock.action_create_warehouse", answer)
        self.assertIn("payload: name=Ana Depo", answer)
        self.assertFalse(tool_result.get("db_write_performed", True))

    def test_model_capability_profile_blocks_chat_only_prepare_but_keeps_reads(self) -> None:
        def chat_only_client(_prompt: str) -> str:
            return '{"mode":"answer","response":"ok"}'

        chat_only_client.resource_plan = {
            "capability_profile": {
                "provider_code": "future",
                "model_id": "chat-only-model",
                "degradation_mode": "chat_only",
                "prepare_write_allowed": False,
                "external_write_planning_allowed": False,
            }
        }

        blocked = run_agent_turn(
            "Ana Depo adinda depo olustur",
            planner_client=chat_only_client,
            chat_client=chat_only_client,
            db_name=self.db_path,
        )
        read = run_agent_turn(
            "bugünkü sipariş sayısını söyle",
            planner_client=chat_only_client,
            chat_client=chat_only_client,
            db_name=self.db_path,
        )

        self.assertTrue(blocked.success, blocked.message)
        self.assertEqual((blocked.data or {}).get("mode"), "capability_limited")
        self.assertTrue((blocked.data or {}).get("capability_limited"))
        self.assertFalse((blocked.data or {}).get("approval_required", True))
        self.assertIsNone((blocked.data or {}).get("action_proposal"))
        self.assertEqual(
            ((blocked.data or {}).get("capability_guard") or {}).get("code"),
            "prepare_write_disabled",
        )
        self.assertTrue(read.success, read.message)
        self.assertEqual(((read.data or {}).get("tool_call") or {}).get("tool"), "orders.count")

    def test_text_guarded_profile_uses_deterministic_prepare_path(self) -> None:
        def text_guarded_client(_prompt: str) -> str:
            return '{"mode":"answer","response":"ok"}'

        text_guarded_client.resource_plan = {
            "capability_profile": {
                "provider_code": "local",
                "model_id": "guarded.gguf",
                "degradation_mode": "text_guarded",
                "prepare_write_allowed": True,
                "external_write_planning_allowed": False,
            }
        }

        result = run_agent_turn(
            "Ana Depo adinda depo olustur",
            planner_client=text_guarded_client,
            chat_client=text_guarded_client,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertEqual(
            ((result.data or {}).get("action_proposal") or {}).get("action_type"),
            "stock.action_create_warehouse",
        )
        self.assertFalse(
            ((result.data or {}).get("capability_profile") or {}).get(
                "external_write_planning_allowed"
            )
        )

    def test_llm_manual_write_capability_match_is_repaired_to_route_prepare(self) -> None:
        result = run_agent_turn(
            "Ana Depo adinda depo olustur",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool_name":"operations.capability_match",'
                '"arguments":{"query":"depo olustur","domain":"inventory","mode":"write"}}'
            ),
            chat_client=lambda _prompt: "Hazir.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertTrue((result.data or {}).get("approval_required"))
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.route")
        tool_result = (result.data or {}).get("tool_result") or {}
        self.assertEqual(tool_result.get("route_status"), "approval_prepared")
        action = tool_result.get("action") or {}
        self.assertEqual(action.get("action_type"), "stock.action_create_warehouse")
        self.assertEqual(((action.get("arguments") or {}).get("payload") or {}).get("name"), "Ana Depo")

    def test_llm_manual_write_multi_capability_match_is_repaired_to_route_prepare(self) -> None:
        result = run_agent_turn(
            "Ana Depo adinda depo olustur",
            planner_client=lambda _prompt: (
                '{"mode":"tools","tool_calls":['
                '{"tool_name":"operations.capability_match",'
                '"arguments":{"query":"depo olustur","domain":"inventory","mode":"write"}},'
                '{"tool_name":"stock.inventory_overview","arguments":{}}'
                ']}'
            ),
            chat_client=lambda _prompt: "Hazir.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.route")
        action = ((result.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertEqual(action.get("action_type"), "stock.action_create_warehouse")
        self.assertEqual(((action.get("arguments") or {}).get("payload") or {}).get("name"), "Ana Depo")

    def test_llm_manual_write_invalid_prepare_capability_is_repaired_to_route_prepare(self) -> None:
        for capability_id in ("create_warehouse", "depot.create"):
            result = run_agent_turn(
                "Ana Depo adinda depo olustur",
                planner_client=lambda _prompt, capability_id=capability_id: (
                    '{"mode":"tool","tool_name":"operations.manual_action.prepare",'
                    f'"arguments":{{"capability_id":"{capability_id}","payload":{{"name":"Ana Depo"}}}}}}'
                ),
                chat_client=lambda _prompt: "Hazir.",
                db_name=self.db_path,
            )

            self.assertTrue(result.success, result.message)
            self.assertEqual((result.data or {}).get("mode"), "approval_required")
            self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.route")
            action = ((result.data or {}).get("tool_result") or {}).get("action") or {}
            self.assertEqual(action.get("action_type"), "stock.action_create_warehouse")
            self.assertEqual(((action.get("arguments") or {}).get("payload") or {}).get("name"), "Ana Depo")

    def test_approval_required_turn_uses_deterministic_no_write_answer(self) -> None:
        result = run_agent_turn(
            "Ana Depo adinda depo olustur",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool_name":"operations.manual_action.prepare",'
                '"arguments":{"capability_id":"depot.create","payload":{"name":"Ana Depo"}}}'
            ),
            chat_client=lambda _prompt: "Talebiniz kaydedildi ve depo olusturuldu.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("Onay gerekiyor", answer)
        self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", answer)
        self.assertNotIn("olusturuldu", answer.casefold())

    def test_approval_required_turn_uses_deterministic_answer_even_when_llm_is_natural(self) -> None:
        natural_answer = (
            "Ana Depo icin olusturma islemini hazirladim. "
            "Onay verirsen kaydi olusturma adimina gececegim."
        )
        result = run_agent_turn(
            "Ana Depo adinda depo olustur",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool_name":"operations.manual_action.prepare",'
                '"arguments":{"capability_id":"depot.create","payload":{"name":"Ana Depo"}}}'
            ),
            chat_client=lambda _prompt: natural_answer,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        answer = (result.data or {}).get("answer") or ""
        self.assertFalse(answer.startswith(natural_answer), answer)
        self.assertIn("Onay gerekiyor", answer)
        self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", answer)
        self.assertNotIn("operations.", answer)

    def test_approval_required_turn_deduplicates_semantic_no_write_notice(self) -> None:
        natural_answer = (
            "CLAIM-1 iadesini onaylamak icin onayiniz gerekiyor. Onayliyor musunuz?\n\n"
            "Onay gerekiyor. Gercek API istegi veya veritabani yazimi yapilmadi."
        )
        repaired = ai_agent._approval_answer_with_safety_footer(
            natural_answer,
            "deterministic fallback",
        )

        self.assertIn("CLAIM-1", repaired)
        self.assertEqual(repaired.count("Onay gerekiyor."), 1)
        self.assertEqual(repaired.count("Gercek API istegi veya DB yazimi yapilmadi."), 1)

    def test_approval_answer_accepts_completed_preparation_but_rejects_completed_action(self) -> None:
        self.assertTrue(
            ai_agent._safe_natural_approval_answer(
                "Kargo degisikligi icin hazirliklar tamamlandi. Degisikligi onayliyor musunuz?"
            )
        )
        self.assertFalse(
            ai_agent._safe_natural_approval_answer(
                "Kargo degisikligi tamamlandi ve siparis guncellendi. Onayliyor musunuz?"
            )
        )

    def test_llm_history_payload_preserves_more_than_four_conversation_turns(self) -> None:
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
            for index in range(20)
        ]

        payload = ai_agent._history_payload_for_llm(history)

        self.assertEqual(len(payload), 20)
        self.assertEqual(payload[0]["content"], "turn-0")
        self.assertEqual(payload[-1]["content"], "turn-19")

    def test_llm_history_payload_retrieves_distant_structured_selection(self) -> None:
        history = [
            {
                "role": "user",
                "content": "Stage magazamizdaki son gelen 5 siparisi getir.",
            },
            {
                "role": "assistant",
                "content": (
                    "Lokal kayda gore 5 siparis buldum: "
                    "1. 111 | durum: Picking "
                    "2. 222 | durum: Picking "
                    "3. 333 | durum: Picking"
                ),
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.recent",
                    "listed_count": 5,
                    "order_numbers": ["111", "222", "333", "444", "555"],
                },
            },
            {
                "role": "user",
                "content": (
                    "Listedeki ucuncu siparisin kargosunu ve takibini goster."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "333 | durum: Picking | kargo: Trendyol Express Marketplace "
                    "| takip: 7330000000000333"
                ),
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.full_context",
                    "listed_count": 1,
                    "order_numbers": ["333"],
                },
            },
        ]
        history.extend(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"unrelated-recent-turn-{index}",
            }
            for index in range(40)
        )

        payload = ai_agent._history_payload_for_llm(
            history,
            query=(
                "Konusmanin basindaki 5 siparislik listenin ucuncu "
                "siparisini kargo ve takip alanlariyla ver."
            ),
        )
        payload_text = json.dumps(payload, ensure_ascii=False)

        self.assertLessEqual(len(payload), 24)
        self.assertLessEqual(
            sum(
                len(str(row.get("role") or ""))
                + len(str(row.get("content") or ""))
                for row in payload
            ),
            16_000,
        )
        self.assertIn("333", payload_text)
        self.assertIn("7330000000000333", payload_text)
        self.assertIn("listed_count", payload_text)
        self.assertIn("unrelated-recent-turn-39", payload_text)

    def test_historical_order_field_recall_stays_tool_free_after_long_history(self) -> None:
        client_calls = 0

        def fail_if_called(_prompt: str) -> str:
            nonlocal client_calls
            client_calls += 1
            raise AssertionError("Historical no-tool recall must be deterministic.")

        history = [
            {
                "role": "assistant",
                "content": (
                    "1. 111 | durum: Picking\n"
                    "2. 222 | durum: Picking\n"
                    "3. 333 | durum: Picking\n"
                    "4. 444 | durum: Picking\n"
                    "5. 555 | durum: Picking"
                ),
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.recent",
                    "listed_count": 5,
                    "order_numbers": ["111", "222", "333", "444", "555"],
                },
            },
            {
                "role": "assistant",
                "content": (
                    "1. 333 | durum: Picking | kargo: Trendyol Express "
                    "| takip: 7330000000000333"
                ),
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.full_context",
                    "listed_count": 1,
                    "order_numbers": ["333"],
                },
            },
            *[
                {
                    "role": "user" if index % 2 == 0 else "assistant",
                    "content": f"unrelated-long-turn-{index}",
                }
                for index in range(80)
            ],
        ]

        result = run_agent_turn(
            (
                "Konusmanin basindaki 5 siparislik listenin ucuncu kaydini "
                "yeni arac cagirmadan yalniz siparis, durum, kargo ve takip "
                "olarak tekrar et."
            ),
            planner_client=fail_if_called,
            chat_client=fail_if_called,
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(client_calls, 0)
        self.assertEqual((result.data or {}).get("tool_calls"), [])
        answer = str((result.data or {}).get("answer") or "")
        self.assertEqual(
            answer,
            (
                "siparis: 333 | durum: Picking | kargo: Trendyol Express "
                "| takip: 7330000000000333"
            ),
        )

    def test_llm_write_answer_is_repaired_to_fallback_tool(self) -> None:
        result = run_agent_turn(
            "At kili firca stok adedini 12 yap",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Bu islem icin tool yok."}',
            chat_client=lambda _prompt: "Bu islem icin tool yok.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "tool")
        self.assertFalse((result.data or {}).get("approval_required"))
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.update_stock.prepare")

    def test_high_confidence_read_intents_override_weak_cloud_tool_choices(self) -> None:
        cases = [
            ("Son 5 siparisi musteri ve tutarla listele", ["orders.recent"]),
            ("100000001 numarali siparisi bul", ["orders.lookup"]),
            ("Kargoya hazir siparisleri ve yazdirma durumunu listele", ["orders.ready_to_ship"]),
            ("Kargo takip veya firma eksigi olan riskli siparisleri goster", ["orders.fulfillment_risk"]),
            ("Bu ay iade ozetini ve iade tutarini ver", ["returns.summary"]),
            ("Kargo tarife profilini ve en ucuz ornekleri goster", ["logistics.profile"]),
            ("Dikkat isteyen ilanlari nedenleriyle listele", ["listing.attention"]),
            ("Stok envanter ozetini ve sifir bakiyeleri goster", ["stock.inventory_overview"]),
            ("At kili firca stok kartini bul", ["stock.search"]),
            ("Dusuk stok urunlerini listele", ["stock.low_stock"]),
            ("Bu ay tahmini kar ve ciroyu birlikte ver", ["orders.revenue_total", "finance.profit_amount"]),
        ]

        for prompt, expected_tools in cases:
            result = run_agent_turn(
                prompt,
                planner_client=lambda _prompt: '{"mode":"tool","tool_name":"orders.count","arguments":{"period":"today"}}',
                chat_client=lambda _prompt: "Yanlis zayif cevap.",
                db_name=self.db_path,
            )

            self.assertTrue(result.success, f"{prompt}: {result.message}")
            actual = [row.get("tool") for row in ((result.data or {}).get("tool_results") or [])]
            self.assertTrue(set(expected_tools).issubset(set(actual)), f"{prompt}: {actual}")

    def test_question_mark_mojibake_intents_do_not_fall_back_to_chat(self) -> None:
        cases = [
            ("Bug?n ka? sipari?im var?", "orders.count", False),
            ("Kargoya haz?r sipari?leri ve yazd?rma durumunu g?ster", "orders.ready_to_ship", False),
            ("Stokta biten ?r?n say?s? ka??", "stock.zero_or_negative_count", False),
            ("D???k stoklu ?r?nleri listele", "stock.low_stock", False),
            ("Ana Depo ad?nda depo olu?tur", "operations.manual_action.route", True),
            ("?lan ba?l?klar?m? seo uyumlu yap", "listing.content_optimize.prepare", False),
            ("T?m ilanlar? kontrol et fiyat stok ba?l?k g?rsel sorunlar?n? raporla", "listing.quality_audit", False),
        ]

        for prompt, expected_tool, approval_required in cases:
            result = run_agent_turn(
                prompt,
                planner_client=lambda _prompt: '{"mode":"answer","response":"Buradayim. Ne yapalim?"}',
                chat_client=lambda _prompt: "Buradayim. Ne yapalim?",
                db_name=self.db_path,
            )

            self.assertTrue(result.success, f"{prompt}: {result.message}")
            self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), expected_tool, prompt)
            self.assertEqual(bool((result.data or {}).get("approval_required")), approval_required, prompt)

    def test_stock_brand_create_routes_to_brand_capability_not_stock_item(self) -> None:
        result = run_agent_turn(
            "Agent Marka adinda stok markasi olustur",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool_name":"stock.item_create.prepare",'
                '"arguments":{"sku":"AGENT-MARKA","name":"Agent Marka"}}'
            ),
            chat_client=lambda _prompt: "Hazir.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "approval_required")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.manual_action.route")
        proposal = (result.data or {}).get("action_proposal") or {}
        self.assertEqual(proposal.get("action_type"), "stock.action_create_brand")
        self.assertEqual(((proposal.get("arguments") or {}).get("payload") or {}).get("name"), "Agent Marka")

    def test_manual_operation_intents_override_weak_cloud_answers(self) -> None:
        cases = [
            ("Gemini Free adinda gemini provider hesabi ekle", "ai.action_save_provider_account", False),
            (
                "Gemini Free adinda gemini provider hesabi ekle api_key test-key default_model gemini-2.5-flash-lite",
                "ai.action_save_provider_account",
                True,
            ),
            ("openai/gpt-oss-20b model-q4_k_m.gguf indir", "ai.action_download_hf_model", True),
            ("869 prefix ile barkod uret", "stock.action_generate_unique_barcode", False),
            ("ORD-1001 icin kargo etiketi olustur", "labels.create_from_orders.prepare", False),
        ]

        for prompt, expected_capability, approval_required in cases:
            result = run_agent_turn(
                prompt,
                planner_client=lambda _prompt: '{"mode":"answer","response":"Bu istek icin yetenek yok."}',
                chat_client=lambda _prompt: "Bu istek icin yetenek yok.",
                db_name=self.db_path,
            )

            self.assertTrue(result.success, f"{prompt}: {result.message}")
            actual_tool = ((result.data or {}).get("tool_call") or {}).get("tool")
            if expected_capability == "labels.create_from_orders.prepare":
                self.assertEqual(actual_tool, expected_capability)
                self.assertEqual(bool((result.data or {}).get("approval_required")), approval_required, prompt)
                continue
            self.assertEqual(actual_tool, "operations.manual_action.route")
            self.assertEqual(bool((result.data or {}).get("approval_required")), approval_required, prompt)
            answer = (result.data or {}).get("answer") or result.message
            proposal = (result.data or {}).get("action_proposal") or {}
            self.assertIn(
                expected_capability,
                f"{answer} {proposal}",
                prompt,
            )

    def test_return_approval_intents_without_target_route_to_safe_prepare_surface(self) -> None:
        prompts = [
            "Bekleyen iadeleri onayla",
            "Trendyol iadeyi onaylat",
        ]

        for prompt in prompts:
            result = run_agent_turn(
                prompt,
                planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam onayladim."}',
                chat_client=lambda _prompt: "Tamam onayladim.",
                db_name=self.db_path,
            )

            self.assertTrue(result.success, f"{prompt}: {result.message}")
            self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "returns.approve.prepare", prompt)
            tool_result = (result.data or {}).get("tool_result") or {}
            action = tool_result.get("action") or {}
            self.assertFalse(bool(action.get("execute_enabled")), prompt)
            self.assertFalse(bool(action.get("approval_required")), prompt)
            self.assertFalse(bool((result.data or {}).get("approval_required")), prompt)
            self.assertFalse(bool(tool_result.get("valid")), prompt)
            self.assertTrue(list(tool_result.get("warnings") or []), prompt)
            self.assertNotIn("onayland", ((result.data or {}).get("answer") or "").casefold(), prompt)

    def test_live_exam_regressions_repair_weak_cloud_tool_choices(self) -> None:
        cases = [
            (
                "Bugunku siparis status dagilimini goster",
                '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"status"}}',
                "orders.status_counts",
            ),
            (
                "11162233554 siparisinin iade kaydini bul",
                '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"11162233554"}}',
                "returns.lookup",
            ),
            (
                "11162233554 siparisinin iadesini onaylat",
                '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"11162233554"}}',
                "returns.approve.prepare",
            ),
            (
                "Silikon Firca Matara Emzik Biberon Temizleyici 2 Adet ilanini bul",
                '{"mode":"tool","tool":"listing.stock_lookup","arguments":{"query":"silikon firca"}}',
                "listing.search",
            ),
            (
                "Silikon Firca Matara Emzik Biberon Temizleyici linkini getir",
                '{"mode":"tool","tool":"listing.search","arguments":{"query":"silikon firca"}}',
                "listing.url_lookup",
            ),
            (
                "Silikon Firca Matara Emzik Biberon Temizleyici detay bilgilerini getir",
                '{"mode":"tool","tool":"operations.capability_match","arguments":{"query":"detay bilgilerini getir"}}',
                "listing.detail_lookup",
            ),
            (
                "Silikon Firca Matara Emzik Biberon Temizleyici stok adedi kac?",
                '{"mode":"tool","tool":"stock.search","arguments":{"query":"silikon firca"}}',
                "listing.stock_lookup",
            ),
            (
                "Geciken takip numarasi veya kargo firmasi eksik siparisleri listele",
                '{"mode":"tool","tool":"orders.lookup","arguments":{"query":"takip eksik"}}',
                "orders.fulfillment_risk",
            ),
            (
                "Iade status dagilimini tum zamanlar goster",
                '{"mode":"tool","tool":"returns.lookup","arguments":{"query":"status"}}',
                "returns.status_counts",
            ),
            (
                "Stoktaki urunleri listele",
                '{"mode":"tool","tool":"listing.search","arguments":{"query":"stok"}}',
                "stock.items_list",
            ),
            (
                "Trendyol pazaryeri hesabini bul",
                '{"mode":"tool","tool":"logistics.tariff_lookup","arguments":{"query":"trendyol"}}',
                "marketplaces.account_lookup",
            ),
            (
                "Kargo paket gider kalemini bul",
                '{"mode":"tool","tool":"orders.ready_to_ship_count","arguments":{"period":"today"}}',
                "finance.cost_item_lookup",
            ),
            (
                "Karim ne kadar?",
                '{"mode":"tool","tool":"orders.count","arguments":{"period":"today"}}',
                "finance.profit_amount",
            ),
            (
                "Kar?m ne kadar?",
                '{"mode":"tool","tool":"orders.count","arguments":{"period":"today"}}',
                "finance.profit_amount",
            ),
            (
                "Kazancim ne kadar?",
                '{"mode":"tool","tool":"listing.price_lookup","arguments":{"query":"kazanc"}}',
                "finance.profit_amount",
            ),
            (
                "Stoksuz veya kilitli ilan sayisi kac?",
                '{"mode":"tool","tool":"listing.attention","arguments":{"limit":20}}',
                "listing.attention_count",
            ),
            (
                "Kargoya hazir yazdirilmamis paketleri listele",
                '{"mode":"tool","tool":"orders.ready_to_ship_count","arguments":{"period":"all"}}',
                "orders.ready_to_ship",
            ),
            (
                "Stogu sifir veya negatif olan kac stok karti var?",
                '{"mode":"tool","tool":"listing.stock_lookup","arguments":{"query":"stok"}}',
                "stock.zero_or_negative_count",
            ),
            (
                "Silikon Firca Matara Emzik Biberon Temizleyici listing name bilgisini ver",
                '{"mode":"tool","tool":"listing.search","arguments":{"query":"silikon firca"}}',
                "listing.title_lookup",
            ),
            (
                "Bugun siparis, ciro, kar, stok, ilan, pazaryeri, token, kargo tarife ve maliyet kalemi durumunu tek raporda toparla",
                '{"mode":"tools","calls":[{"tool":"orders.summary","arguments":{"period":"today"}},{"tool":"finance.profit_amount","arguments":{"period":"today"}},{"tool":"stock.low_stock_count","arguments":{}},{"tool":"listing.counts","arguments":{}},{"tool":"marketplaces.account_count","arguments":{}},{"tool":"accounts.invalid_token_count","arguments":{}},{"tool":"logistics.tariff_count","arguments":{}},{"tool":"finance.cost_item_count","arguments":{}}]}',
                "orders.count",
            ),
            (
                "Trendyol Aras 0 Desi ucretini getir",
                '{"mode":"tool","tool":"listing.price_lookup","arguments":{"query":"trendyol aras"}}',
                "logistics.tariff_lookup",
            ),
            (
                "Token sagligi problemli hesap sayisi kac",
                '{"mode":"tool","tool":"accounts.health","arguments":{}}',
                "accounts.invalid_token_count",
            ),
            (
                "Ilan durum ozetini ver",
                '{"mode":"tool","tool":"listing.summary","arguments":{"limit":8}}',
                "listing.counts",
            ),
            (
                "depo olusturmak icin hangi capability kullanilir",
                '{"mode":"tool","tool":"operations.manual_action.route","arguments":{"query":"depo olusturmak icin hangi capability kullanilir"}}',
                "operations.capability_match",
            ),
            (
                "Yeni stok karti olustur: ad Test Urun AI, stok kodu TEST-AI-001, barkod 8690000000011",
                '{"mode":"tools","calls":[{"tool":"listing.update_stock.prepare","arguments":{"query":"Test Urun AI","new_quantity":1}},{"tool":"listing.title_lookup","arguments":{"query":"Test Urun AI"}}]}',
                "stock.item_create.prepare",
            ),
        ]
        for prompt, planner_payload, expected_tool in cases:
            result = run_agent_turn(
                prompt,
                planner_client=lambda _prompt, payload=planner_payload: payload,
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(result.success, f"{prompt}: {result.message}")
            tool_calls = (result.data or {}).get("tool_calls") or []
            actual_tools = [row.get("tool") for row in tool_calls if isinstance(row, dict)]
            if not actual_tools:
                actual_tools = [((result.data or {}).get("tool_call") or {}).get("tool")]
            self.assertIn(expected_tool, actual_tools, prompt)
            if expected_tool == "returns.lookup":
                self.assertEqual(((result.data or {}).get("tool_call") or {}).get("arguments", {}).get("query"), "11162233554")
            if expected_tool == "stock.item_create.prepare":
                args = ((result.data or {}).get("tool_call") or {}).get("arguments", {})
                self.assertEqual(args.get("sku"), "TEST-AI-001")
                self.assertEqual(args.get("name"), "Test Urun AI")

    def test_hard_live_exam_prompt_routing_cases(self) -> None:
        cases = [
            ("Bugun operasyonel olarak once neye bakmaliyim?", {"orders.ready_to_ship_count", "orders.fulfillment_risk_count", "returns.waiting_action_count"}),
            ("bugun once hangi operasyona bakayim", {"orders.ready_to_ship_count", "orders.fulfillment_risk_count", "returns.waiting_action_count"}),
            ("Toplam aktif stok karti sayim kac?", {"stock.item_count"}),
            ("ABC123 barkodlu yeni stok karti olustur", {"stock.item_create.prepare"}),
            ("BICAK BILEYICI APARAT stok kartinin adini Test Agent Yeni Ad yap", {"stock.item_update.prepare"}),
            ("Silikon Firca ilan basligini getir", {"listing.title_lookup"}),
            ("Silikon F?r?a ilan ba?l???n? getir", {"listing.title_lookup"}),
            ("Silikon Firca Matara Emzik Biberon Temizleyici linkini getir", {"listing.url_lookup"}),
            ("Silikon Firca Matara Emzik Biberon Temizleyici detay bilgilerini getir", {"listing.detail_lookup"}),
            ("Tum ilanlarimin basliklarini seo uyumlu hale getirmek icin taslak hazirla", {"listing.content_optimize.prepare"}),
            ("hesap token sa?l??? ?zeti ver", {"accounts.health"}),
            ("Token saglik durumunu ozetle", {"accounts.health"}),
            ("Kargo tarife profilini goster", {"logistics.profile"}),
            ("Kargoya hazir yazdirilmamis paketleri listele", {"orders.ready_to_ship"}),
            ("Stoksuz veya kilitli ilan sayisi kac?", {"listing.attention_count"}),
            ("Trendyol pazaryeri hesabini bul", {"marketplaces.account_lookup"}),
            ("Kargo paket gider kalemini bul", {"finance.cost_item_lookup"}),
            ("barkod ?ret", {"operations.manual_action.route"}),
            ("bugunku siparis ozetini ver", {"orders.summary"}),
            ("bugunku iptal siparis ozetini ver", {"orders.cancellations"}),
            ("bu ay iade ozetini ver", {"returns.summary"}),
            ("ilan urun ozetini ver", {"listing.summary"}),
            ("Ilan durum ozetini ver", {"listing.counts"}),
            ("Karim ne kadar?", {"finance.profit_amount"}),
            ("Kar?m ne kadar?", {"finance.profit_amount"}),
            ("Kazancim ne kadar?", {"finance.profit_amount"}),
            ("bu ay kar tahminini detayli hesapla", {"finance.profit_estimate"}),
            ("maliyet kalemi katalogunu listele", {"finance.cost_catalog"}),
            ("pazaryeri entegrasyon ozetini ver", {"marketplaces.summary"}),
            ("hangi pazaryerleri var", {"marketplaces.catalog"}),
            ("onerilen pazaryerlerini listele", {"marketplaces.catalog"}),
            ("kayitli pazaryerlerini goster", {"marketplaces.catalog"}),
            ("Trendyol pazaryerini pasif yap", {"operations.manual_action.route"}),
            ("Trendyol pazaryerini sil", {"operations.manual_action.route"}),
            ("Trendyol pazaryerini kullanima al", {"operations.manual_action.route"}),
            ("depo olusturmak icin hangi capability kullanilir", {"operations.capability_match"}),
            ("stok markasi olusturmak icin hangi capability kullanilir", {"operations.capability_match"}),
            ("barkod uretmek icin hangi capability kullanilir", {"operations.capability_match"}),
            ("platform enabled fields getir", {"operations.manual_action.route"}),
        ]

        for prompt, expected_tools in cases:
            result = choose_action(prompt)
            self.assertTrue(result.success, result.message)
            decision = (result.data or {}).get("decision")
            actual = {call.tool_name for call in (getattr(decision, "tool_calls", ()) or [])}
            if not actual and getattr(decision, "tool_name", None):
                actual = {getattr(decision, "tool_name")}
            self.assertTrue(expected_tools.issubset(actual), f"{prompt}: {actual}")

    def test_marketplace_catalog_question_lists_marketplace_records_not_accounts(self) -> None:
        result = run_agent_turn("Hangi pazaryerleri var, onerilenleri listele", db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "marketplaces.catalog")
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Pazaryeri katalog", answer)
        self.assertIn("TRENDYOL", answer)
        self.assertNotIn("pazaryeri hesabi bulunamadi", answer)

    def test_marketplace_catalog_question_repairs_bad_order_planner_tool(self) -> None:
        result = run_agent_turn(
            "Hangi pazaryerleri var, onerilenleri listele ve hesaplarla karistirma.",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"orders.recent","arguments":{"limit":5}}',
            chat_client=lambda _prompt: "Cloud cevabi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "marketplaces.catalog")
        answer = str((result.data or {}).get("answer") or "")
        self.assertNotIn("siparis buldum", answer)

    def test_marketplace_write_prompts_infer_payload_and_prepare_approval(self) -> None:
        cases = [
            ("Trendyol pazaryerini pasif yap", "marketplaces.set_marketplaces_active_state", {"codes": ["TRENDYOL"], "is_active": False}),
            ("Trendyol pazaryerini kullanima al", "marketplaces.accept_marketplace_record", {"code": "TRENDYOL"}),
            ("Trendyol pazaryerini sil", "marketplaces.delete_marketplace", {"code": "TRENDYOL"}),
            (
                "Trendyol pazaryeri adini Trendyol Agentic yap",
                "marketplaces.save_marketplace",
                {"payload": {"code": "TRENDYOL", "label": "Trendyol Agentic"}},
            ),
            (
                "Trendyol pazaryeri adini Trendyol Agentic yap, onay hazirla",
                "marketplaces.save_marketplace",
                {"payload": {"code": "TRENDYOL", "label": "Trendyol Agentic"}},
            ),
            (
                "Trendyol pazaryerini Trendyol Agentic etiketiyle kaydet",
                "marketplaces.save_marketplace",
                {"payload": {"code": "TRENDYOL", "label": "Trendyol Agentic"}},
            ),
        ]
        for prompt, capability_id, expected_payload in cases:
            result = run_agent_turn(
                prompt,
                planner_client=lambda _prompt: '{"mode":"tool","tool":"marketplaces.account_count","arguments":{}}',
                chat_client=lambda _prompt: "Cloud cevabi.",
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            self.assertEqual((result.data or {}).get("mode"), "approval_required", prompt)
            tool_result = (result.data or {}).get("tool_result") or {}
            self.assertEqual((tool_result.get("match") or {}).get("capability_id"), capability_id, prompt)
            payload = tool_result.get("payload") or {}
            for key, value in expected_payload.items():
                self.assertEqual(payload.get(key), value, prompt)
            self.assertEqual(payload.get("db_name"), self.db_path)

    def test_price_update_uses_requested_value_not_product_title_count(self) -> None:
        with Session(get_engine(self.db_path)) as session:
            session.add(ApiAccount(pk=1, account_id="seller-1", comp_name="Demo Seller", platform="trendyol"))
            session.add(
                ListingProduct(
                    api_account_id=1,
                    product_id="LIST-PRICE-2",
                    title="Silikon Firca 2 Adet",
                    barcode="LIST-PRICE-2",
                    product_main_id="LIST-PRICE-2",
                    product_code="LIST-PRICE-2",
                    sale_price=69.99,
                    quantity=10,
                    approved=True,
                    archived=False,
                    locked=False,
                    on_sale=True,
                )
            )
            session.commit()

        result = run_agent_turn(
            "Silikon Firca 2 Adet fiyatini 199.90 yap",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Hazir."}',
            chat_client=lambda _prompt: "Hazir.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.update_price.prepare")
        proposal = ((result.data or {}).get("tool_result") or {}).get("action") or {}
        rows = proposal.get("rows") or []
        self.assertEqual(float((rows[0] or {}).get("requested_sale_price")), 199.90)

    def test_return_approval_with_order_number_prepares_approval_payload(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-ORDER-NUMBER-APPROVAL",
                    orderNumber="11162233554",
                    claimDate=now_ms,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    claimItemStatus="WaitingInAction",
                    waitingClaimLineItemIds=["line-order-number-approval"],
                    totalPrice=100.0,
                    itemCount=1,
                )
            )
            session.commit()

        result = run_agent_turn(
            "11162233554 iadesini onayla",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Tamam onayladim."}',
            chat_client=lambda _prompt: "Tamam onayladim.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "returns.approve.prepare")
        self.assertTrue((result.data or {}).get("approval_required"))
        tool_result = (result.data or {}).get("tool_result") or {}
        action = tool_result.get("action") or {}
        self.assertEqual(action.get("action_type"), "orders.approve_return_claim")
        self.assertTrue(bool(action.get("execute_enabled")))
        self.assertEqual(
            (((action.get("arguments") or {}).get("payload") or {}).get("order")),
            "CLAIM-ORDER-NUMBER-APPROVAL",
        )
        self.assertFalse((result.data or {}).get("execute_performed", False))

    def test_operations_coverage_report_tool_and_fallback_route_are_read_only(self) -> None:
        registry = available_tools()
        tool = registry["operations.coverage_report"]
        self.assertTrue(tool.read_only)
        self.assertFalse(tool.destructive)

        result = run_agent_turn("agentic kapsam raporunu goster", db_name=self.db_path)

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "operations.coverage_report")
        report = (((result.data or {}).get("tool_result") or {}).get("report") or {})
        self.assertGreater(int(report.get("manual_write_total") or 0), 20)

    def test_risky_prepare_tools_are_marked_by_registry_metadata(self) -> None:
        registry = available_tools()
        for name in (
            "listing.update_price.prepare",
            "listing.update_stock.prepare",
            "stock.item_create.prepare",
            "stock.item_update.prepare",
            "operations.manual_action.prepare",
        ):
            tool = registry[name]
            self.assertTrue(tool.read_only)
            self.assertFalse(tool.destructive)
            self.assertTrue(tool.requires_approval)
            self.assertIn(tool.risk_level, {"medium", "high"})
            self.assertEqual(tool.action_type, "prepare_write")

    def test_agent_eval_prompt_suite_covers_read_and_risky_routes(self) -> None:
        cases = [
            ("Bugun kac siparisim var?", "orders.count", "tool"),
            ("Kargolamam gereken kac siparis var?", "orders.ready_to_ship_count", "tool"),
            ("Toplam onay bekleyen iade sayisi kac?", "returns.waiting_action_count", "tool"),
            ("At kili firca ilanlarini listele", "listing.search", "tool"),
            ("At kili firca fiyatlarini ver", "listing.price_lookup", "tool"),
            ("Karim ne kadar?", "finance.profit_amount", "tool"),
            ("Kar?m ne kadar?", "finance.profit_amount", "tool"),
            ("Kazancim ne kadar?", "finance.profit_amount", "tool"),
            ("Stok genel ozetini ver", "stock.inventory_overview", "tool"),
            ("Pazaryeri hesaplarini listele", "marketplaces.account_lookup", "tool"),
            ("Kargo tarifelerimi goster", "logistics.tariff_count", "tool"),
            ("At kili firca fiyatini 89.99 yap", "listing.update_price.prepare", "tool"),
            ("At kili firca stok miktarini 2 yap", "listing.update_stock.prepare", "tool"),
        ]

        for prompt, expected_tool, expected_mode in cases:
            result = choose_action(prompt)
            self.assertTrue(result.success, result.message)
            decision = (result.data or {}).get("decision")
            self.assertEqual(getattr(decision, "mode", None), expected_mode, prompt)
            self.assertEqual(getattr(decision, "tool_name", None), expected_tool, prompt)

    def test_agent_500_hard_ecommerce_prompt_eval_routes_to_expected_tools(self) -> None:
        products = [
            "at kili firca",
            "silikon kapak seti",
            "biberon temizleme fircasi",
            "lavabo suzgeci",
            "sac taragi",
            "derz temizleme fircasi",
            "matara fircasi",
            "banyo gider kapatici",
            "cam sise fircasi",
            "pratik tarak aparati",
        ]
        order_refs = ["ORD-1001", "PKT-7788", "TRK-5544", "Ayse Yilmaz", "ReadyToShip"]
        return_refs = ["CLAIM-1001", "ORD-2002", "WaitingInAction", "Accepted", "iade takip"]
        cost_terms = ["komisyon", "paketleme", "reklam", "kargo farki", "manuel gider"]
        tariff_terms = ["aras", "yurtici", "mng", "surat", "trendyol express"]

        cases: list[tuple[str, str | set[str]]] = []

        def add_variants(expected: str | set[str], templates: list[str], values: list[str] | None = None, target: int = 20) -> None:
            source_values = values or [""]
            for index in range(target):
                template = templates[index % len(templates)]
                value = source_values[index % len(source_values)]
                cases.append((template.format(value=value, n=index + 1), expected))

        add_variants(
            "orders.count",
            [
                "Bugun toplam kac siparis var detayli kontrol et",
                "Bugunku siparis adedini net soyle",
                "Siparis sayisini bugun icin say",
                "Bugun order count kac gorunuyor",
                "Toplam bugun siparis adedi nedir",
            ],
            target=20,
        )
        add_variants(
            "orders.ready_to_ship_count",
            [
                "Kargolamam gereken kac siparis var operasyon icin bak",
                "Kargoya hazir paketleri say",
                "Ready to ship siparis adedini bul",
                "Paketleyecegim siparis sayisi kac",
                "Kargolanacak siparisler toplam kac adet",
            ],
            target=20,
        )
        add_variants(
            "orders.fulfillment_risk_count",
            [
                "Fulfillment risk sayisini kontrol et",
                "Takip no eksik riskli siparis sayisi kac",
                "Geciken kargo riski kac kayit",
                "Tracking problemi olan siparis adedini ver",
                "Kargo firma veya takip riski ozetini say",
            ],
            target=20,
        )
        add_variants(
            "orders.lookup",
            [
                "{value} siparisini bul ve detayina bak",
                "{value} order kaydini getir",
                "{value} takip numarali siparisi ara",
                "{value} paket numarasini sipariste bul",
                "{value} musteri veya paket bilgisinden siparis ara",
            ],
            values=order_refs,
            target=20,
        )
        add_variants(
            "returns.waiting_action_count",
            [
                "Toplam onay bekleyen iade sayisi kac",
                "Aksiyon bekleyen iadeleri say",
                "WaitingInAction claim toplam kac",
                "Onay bekleyen return adedi nedir",
                "Iadelerde bekleyen aksiyon sayisini ver",
            ],
            target=20,
        )
        add_variants(
            "returns.lookup",
            [
                "{value} iadesini bul",
                "{value} claim kaydini getir",
                "{value} return detayini ara",
                "{value} iadeyi takip bilgisiyle listele",
                "{value} iade kaydini detayli goster",
            ],
            values=return_refs,
            target=20,
        )
        add_variants(
            "listing.search",
            [
                "{value} ilanlarini listele",
                "{value} ilan bul bana",
                "{value} listing kayitlarini getir",
                "{value} urun ilanlarini ara",
                "{value} icin ilan sonucunu goster",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "listing.price_lookup",
            [
                "{value} fiyatlarini ver",
                "{value} satis fiyati kac",
                "{value} ilan fiyati ne",
                "{value} price bilgisini getir",
                "{value} urunun fiyat listesini goster",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "listing.stock_lookup",
            [
                "{value} ilan stogu kac",
                "{value} pazaryeri stok adedini getir",
                "{value} listing quantity bilgisini ver",
                "{value} stoku kac gorunuyor",
                "{value} stok adedi detayina bak",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "listing.status_lookup",
            [
                "{value} ilan durumu nedir",
                "{value} onay ve satista durumunu goster",
                "{value} kilitli mi arsivde mi bak",
                "{value} status bilgisini getir",
                "{value} satis disi mi kontrol et",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "listing.title_lookup",
            [
                "{value} ilanin adi ne",
                "{value} basligini getir",
                "{value} title kaydini goster",
                "{value} urun adini soyle",
                "{value} listing name bilgisini ver",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "listing.attention_count",
            [
                "Ilan problem sayisi kac",
                "Dikkat isteyen ilan adedi nedir",
                "Kilitli onaysiz stoksuz ilan riski kac",
                "Listing attention isteyen kayit sayisini ver",
                "Ilan risk kayitlarini say",
            ],
            target=20,
        )
        add_variants(
            "listing.update_price.prepare",
            [
                "{value} fiyatini 89.99 yap ama once onaylat",
                "{value} satis fiyatini 129.50 olarak ayarla",
                "{value} fiyat guncellemesini 74.90 TL yap",
                "{value} price update 199.99 hazirla",
                "{value} ilan fiyatini 59.99 yap",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "listing.update_stock.prepare",
            [
                "{value} stok miktarini 2 yap ama onay iste",
                "{value} pazaryeri stok adedini 0 olarak ayarla",
                "{value} listing quantity 12 yap",
                "{value} stok guncellemesini 5 adet hazirla",
                "{value} ilanin stok adedini 8 yap",
            ],
            values=products,
            target=20,
        )
        add_variants(
            "stock.inventory_overview",
            [
                "Stok genel ozetini detayli ver",
                "Envanter genel durumuna bak",
                "Inventory overview cikart",
                "Stok kartlari ve bakiye ozetini getir",
                "Depodaki stok genel tablosunu ozetle",
            ],
            target=20,
        )
        add_variants(
            "stock.low_stock_count",
            [
                "Dusuk stok sayisi kac",
                "Kritik stok adedini ver",
                "Low stock toplam kac kayit",
                "Azalan stoklari say",
                "Kritik envanter sayisini kontrol et",
            ],
            target=20,
        )
        add_variants(
            "stock.zero_or_negative_count",
            [
                "Sifir stoklu urun sayisi kac",
                "Negatif stok kaydi var mi say",
                "Zero stock toplam adedi nedir",
                "Stogu olmayan urunleri say",
                "Eksi stok problem sayisini ver",
            ],
            target=20,
        )
        add_variants(
            "finance.profit_amount",
            [
                "Bugunku tahmini kar kac",
                "Kar tahmini bugun icin ne",
                "Kazanc tutarini bugun hesapla",
                "Tahmini kar miktarini soyle",
                "Bugun net kazanc tahmini nedir",
            ],
            target=20,
        )
        add_variants(
            "orders.revenue_total",
            [
                "Bugunku ciro toplam kac",
                "Revenue bugun ne kadar",
                "Satis tutari toplam bugun kac TL",
                "Paket toplam cirosunu bugun ver",
                "Gelir bugun kac gorunuyor",
            ],
            target=20,
        )
        add_variants(
            "finance.cashflow_net",
            [
                "Bu ay net nakit hareketi ne",
                "Cashflow net tutarini ver",
                "Odeme borc alacak netini hesapla",
                "Finans nakit akisi net kac",
                "Bu ay alacak borc net sonucunu soyle",
            ],
            target=20,
        )
        add_variants(
            "finance.cost_item_lookup",
            [
                "{value} maliyet kalemini bul",
                "{value} gider kalemini getir",
                "{value} cost kaydini ara",
                "{value} maliyet detayini listele",
                "{value} gider detayini goster",
            ],
            values=cost_terms,
            target=20,
        )
        add_variants(
            "marketplaces.account_lookup",
            [
                "Pazaryeri hesaplarini listele",
                "Marketplace hesaplarini getir",
                "Entegrasyon hesaplarini goster",
                "Bagli hesaplari listele",
                "Pazaryeri account kayitlarini getir",
            ],
            target=20,
        )
        add_variants(
            "accounts.invalid_token_count",
            [
                "Token sagligi problemli hesap sayisi kac",
                "Baglanti saglik problemi kac hesapta var",
                "Gecersiz token sayisini ver",
                "Hesap saglik kontrolunde sorunlu kac hesap var",
                "API token hatali hesap adedi nedir",
            ],
            target=20,
        )
        add_variants(
            "logistics.tariff_count",
            [
                "Kargo tarifelerimi say",
                "Lojistik tarife toplam kac",
                "Aktif kargo tarife adedi nedir",
                "Tarife sayisini ver",
                "Kargo profilinde kac tarife var",
            ],
            target=20,
        )
        add_variants(
            "logistics.tariff_lookup",
            [
                "{value} kargo tarifesini bul",
                "{value} lojistik tarife detayini getir",
                "{value} tarife kaydini ara",
                "{value} kargo fiyat profilini listele",
                "{value} tarife sonucunu goster",
            ],
            values=tariff_terms,
            target=20,
        )

        self.assertEqual(len(cases), 500)
        registry = available_tools()
        failures: list[str] = []
        approval_count = 0
        for prompt, expected in cases:
            result = choose_action(prompt, tools=registry)
            if not result.success:
                failures.append(f"{prompt}: {result.message}")
                continue
            decision = (result.data or {}).get("decision")
            actual = getattr(decision, "tool_name", "")
            if isinstance(expected, set):
                ok = actual in expected
            else:
                ok = actual == expected
            if not ok:
                failures.append(f"{prompt}: expected {expected}, got {actual}")
            tool = registry.get(actual)
            if tool is not None and tool.requires_approval:
                approval_count += 1
                self.assertTrue(tool.read_only, prompt)
                self.assertFalse(tool.destructive, prompt)
                self.assertEqual(tool.action_type, "prepare_write", prompt)

        self.assertEqual(failures, [])
        self.assertEqual(approval_count, 40)

    def test_waiting_return_question_uses_waiting_action_tool(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-WAIT-1",
                    orderNumber="ORD-WAIT-1",
                    claimDate=today_start + 1_000,
                    orderDate=today_start + 1_000,
                    lastModifiedDate=today_start + 2_000,
                    claimItemStatus="WaitingInAction",
                    totalPrice=99.0,
                    itemCount=1,
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-OK-1",
                    orderNumber="ORD-OK-1",
                    claimDate=today_start + 3_000,
                    orderDate=today_start + 3_000,
                    lastModifiedDate=today_start + 4_000,
                    claimItemStatus="Accepted",
                    totalPrice=49.0,
                    itemCount=1,
                )
            )
            session.commit()

        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        result = run_agent_turn(
            "Toplam onay bekleyen iade sayisi kac?",
            planner_client=failing_local_client,
            chat_client=failing_local_client,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "returns.waiting_action_count")
        self.assertEqual(((result.data or {}).get("tool_result") or {}).get("count"), 1)

    def test_returns_query_lists_only_waiting_action_claims(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-WAIT-LIST-1",
                    orderNumber="ORD-WAIT-LIST-1",
                    claimDate=today_start + 1_000,
                    orderDate=today_start + 1_000,
                    lastModifiedDate=today_start + 2_000,
                    claimItemStatus="WaitingInAction",
                    claimReason="Hasarli urun",
                    totalPrice=199.0,
                    itemCount=1,
                    waitingClaimLineItemIds=["line-wait-1"],
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-ACCEPTED-LIST-1",
                    orderNumber="ORD-ACCEPTED-LIST-1",
                    claimDate=today_start + 3_000,
                    orderDate=today_start + 3_000,
                    lastModifiedDate=today_start + 4_000,
                    claimItemStatus="Accepted",
                    claimReason="Hasarli urun",
                    totalPrice=299.0,
                    itemCount=1,
                )
            )
            session.commit()

        tool = available_tools()["returns.query"]
        result = tool.handler(
            db_name=self.db_path,
            period="all",
            filters={"status": "WaitingInAction"},
            sort="claim_date_desc",
            limit=10,
        )

        self.assertTrue(result.success, result.message)
        returns = (result.data or {}).get("returns") or []
        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].get("claim_id"), "CLAIM-WAIT-LIST-1")
        self.assertEqual(returns[0].get("status"), "WaitingInAction")
        self.assertEqual(returns[0].get("waiting_line_item_ids"), ["line-wait-1"])

    def test_new_waiting_return_list_overrides_old_selection_and_projects_fields(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(
            datetime.combine(
                today,
                datetime.min.time(),
                tzinfo=TZ_GMT3,
            ).timestamp()
            * 1000
        )
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-WAIT-PROJECT-1",
                    orderNumber="ORD-WAIT-PROJECT-1",
                    claimDate=today_start + 1_000,
                    orderDate=today_start + 1_000,
                    lastModifiedDate=today_start + 1_000,
                    claimItemStatus="WaitingInAction",
                    claimReason="Hasarli urun",
                    customerFirstName="Hidden",
                    customerLastName="Customer",
                    totalPrice=100.0,
                    itemCount=1,
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-WAIT-PROJECT-2",
                    orderNumber="ORD-WAIT-PROJECT-2",
                    claimDate=today_start + 2_000,
                    orderDate=today_start + 2_000,
                    lastModifiedDate=today_start + 2_000,
                    claimItemStatus="WaitingInAction",
                    claimReason="Vazgectim",
                    customerFirstName="Hidden",
                    customerLastName="Customer",
                    totalPrice=200.0,
                    itemCount=2,
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-ACCEPTED-PROJECT",
                    orderNumber="ORD-ACCEPTED-PROJECT",
                    claimDate=today_start + 3_000,
                    orderDate=today_start + 3_000,
                    lastModifiedDate=today_start + 3_000,
                    claimItemStatus="Accepted",
                    claimReason="Vazgectim",
                    totalPrice=300.0,
                    itemCount=1,
                )
            )
            session.commit()

        message = (
            "Bu ay islem bekleyen en yeni 2 iadeyi yalniz claim, siparis, "
            "durum ve tutar alanlariyla listele."
        )
        result = run_agent_turn(
            message,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.query","arguments":{'
                '"period":"all","filters":{},"sort":"claim_date_desc",'
                '"limit":2,"mode":"list"}}'
            ),
            chat_client=lambda _prompt: (
                "İstediğin kayıtlar aşağıdadır: CLAIM-WAIT-PROJECT-2 ve "
                "CLAIM-WAIT-PROJECT-1 durumları WaitingInAction."
            ),
            db_name=self.db_path,
            history=[
                {
                    "role": "assistant",
                    "content": "Eski iade secimi.",
                    "context": {
                        "kind": "return_selection",
                        "source_tool": "returns.lookup",
                        "claim_ids": ["CLAIM-OLD"],
                        "period": "all",
                        "filters": {},
                        "sort": "claim_date_desc",
                    },
                }
            ],
        )

        self.assertTrue(result.success, result.message)
        call = (result.data or {}).get("tool_call") or {}
        self.assertEqual(call.get("tool"), "returns.query")
        self.assertEqual(
            (call.get("arguments") or {}).get("filters"),
            {"status": "WaitingInAction"},
        )
        self.assertEqual(
            (result.data or {}).get("answer"),
            (
                "1. CLAIM-WAIT-PROJECT-2 | siparis: ORD-WAIT-PROJECT-2 | "
                "durum: WaitingInAction | tutar: 200 TL\n"
                "2. CLAIM-WAIT-PROJECT-1 | siparis: ORD-WAIT-PROJECT-1 | "
                "durum: WaitingInAction | tutar: 100 TL"
            ),
        )

    def test_cancelled_return_prepare_keeps_ordinal_claim_read_scope(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-KEEP-SCOPE-1",
                    orderNumber="ORD-RETURN-PARENT-1",
                    claimDate=now_ms,
                    orderDate=now_ms,
                    lastModifiedDate=now_ms,
                    claimItemStatus="WaitingInAction",
                    claimReason="Teslim edilemeyen gonderi",
                    totalPrice=1054.56,
                    itemCount=2,
                    waitingClaimLineItemIds=["line-1", "line-2"],
                )
            )
            session.commit()

        history = [
            {
                "role": "assistant",
                "content": "Eski siparis listesi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.recent",
                    "order_numbers": ["ORD-OLD-1", "ORD-OLD-2"],
                    "listed_count": 2,
                    "total_count": 2,
                    "truncated": False,
                },
            },
            {
                "role": "assistant",
                "content": "Onay bekleyen iadeler.",
                "context": {
                    "kind": "return_selection",
                    "source_tool": "returns.query",
                    "claim_ids": ["CLAIM-KEEP-SCOPE-1", "CLAIM-OTHER-2"],
                    "period": "all",
                    "filters": {"status": "WaitingInAction"},
                    "sort": "claim_date_desc",
                },
            },
            {
                "role": "assistant",
                "content": "Tamam, iade onayini iptal ettim; islem yapilmadi.",
            },
        ]
        result = run_agent_turn(
            (
                "Iptal ettigimiz listedeki ilk iadenin tutarini, durumunu ve "
                "onay bekleyen kalem sayisini tekrar dogrula."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.full_context",'
                '"arguments":{"query":"ORD-OLD-1","limit":1}}'
            ),
            chat_client=lambda _prompt: "Eski siparisin ayrintilari.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        call = (result.data or {}).get("tool_call") or {}
        self.assertEqual(call.get("tool"), "returns.lookup")
        self.assertEqual(
            (call.get("arguments") or {}).get("query"),
            "CLAIM-KEEP-SCOPE-1",
        )
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("durum: WaitingInAction", answer)
        self.assertIn("onay bekleyen kalem: 2", answer)
        self.assertIn("tutar: 1054.56 TL", answer)
        self.assertNotIn("bu islemi calistirmiyorum", answer.casefold())
        self.assertNotIn("ORD-OLD-1", answer)

    def test_returns_reason_summary_aggregates_complete_claim_set_with_explicit_denominators(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        reasons = (
            "Yanlış ürün gönderildi",
            "Beğenmedim | Yanlış ürün gönderildi",
            "Beğenmedim",
            "",
        )
        with Session(get_engine(self.db_path)) as session:
            for index, reason in enumerate(reasons, start=1):
                session.add(
                    ReturnClaim(
                        claimId=f"CLAIM-REASON-{index}",
                        orderNumber=f"ORD-REASON-{index}",
                        claimDate=now_ms + index,
                        orderDate=now_ms + index,
                        lastModifiedDate=now_ms + index,
                        claimItemStatus="Created",
                        claimReason=reason,
                        totalPrice=50.0,
                        itemCount=1,
                    )
                )
            session.commit()

        result = available_tools()["returns.reason_summary"].handler(
            db_name=self.db_path,
            period="all",
            top_n=10,
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("total_claims"), 4)
        self.assertEqual(data.get("claims_with_reason"), 3)
        self.assertEqual(data.get("claims_without_reason"), 1)
        self.assertEqual(data.get("multi_reason_claims"), 1)
        self.assertEqual(data.get("reason_occurrence_count"), 4)
        self.assertEqual(data.get("selected_claim_occurrence_sum"), 4)
        self.assertEqual(data.get("selected_unique_claim_count"), 3)
        self.assertEqual(data.get("selected_overlap_claims"), 1)
        self.assertEqual(data.get("selected_percent_of_all_claims"), 75.0)
        by_reason = {
            row.get("normalized_reason"): row
            for row in data.get("reasons") or []
        }
        self.assertEqual(by_reason["yanlis urun gonderildi"].get("claim_count"), 2)
        self.assertEqual(by_reason["begenmedim"].get("claim_count"), 2)
        self.assertEqual(
            by_reason["yanlis urun gonderildi"].get("percent_of_all_claims"),
            50.0,
        )

    def test_contextual_reason_summary_keeps_waiting_return_scope(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        rows = (
            ("CLAIM-WAIT-REASON-1", "WaitingInAction", "Hasarli urun"),
            ("CLAIM-WAIT-REASON-2", "WaitingInAction", "Vazgectim"),
            ("CLAIM-ACCEPT-REASON-1", "Accepted", "Vazgectim"),
        )
        with Session(get_engine(self.db_path)) as session:
            for index, (claim_id, status, reason) in enumerate(rows, start=1):
                session.add(
                    ReturnClaim(
                        claimId=claim_id,
                        orderNumber=f"ORD-CTX-REASON-{index}",
                        claimDate=now_ms + index,
                        orderDate=now_ms + index,
                        lastModifiedDate=now_ms + index,
                        claimItemStatus=status,
                        claimReason=reason,
                        totalPrice=50.0,
                        itemCount=1,
                    )
                )
            session.commit()

        history = [
            {
                "role": "assistant",
                "content": "Stage kaydinda iki iade islem bekliyor.",
                "context": {
                    "kind": "returns_waiting_action_scope",
                    "source_tool": "returns.waiting_action_count",
                    "period": "all",
                    "total_count": 2,
                },
            }
        ]
        result = run_agent_turn(
            "Bu iadelerin neden dagilimini ozetle; en sik nedeni de soyle.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.reason_summary",'
                '"arguments":{"period":"all","top_n":10}}'
            ),
            chat_client=lambda _prompt: "Tum uc iadenin ozeti.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        call = (result.data or {}).get("tool_call") or {}
        self.assertEqual(call.get("tool"), "returns.reason_summary")
        self.assertTrue((call.get("arguments") or {}).get("waiting_action_only"))
        data = (result.data or {}).get("tool_result") or {}
        self.assertEqual(data.get("total_claims"), 2)
        self.assertTrue(data.get("waiting_action_only"))
        self.assertIn(
            "islem bekleyen kapsamindaki 2 iade/claim",
            str((result.data or {}).get("answer") or ""),
        )

    def test_full_history_return_reason_request_repairs_list_or_count_planner(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            for index, reason in enumerate(
                ("Yanlış ürün gönderildi", "Beğenmedim", "Yanlış ürün gönderildi"),
                start=1,
            ):
                session.add(
                    ReturnClaim(
                        claimId=f"CLAIM-AGG-{index}",
                        orderNumber=f"ORD-AGG-{index}",
                        claimDate=now_ms + index,
                        orderDate=now_ms + index,
                        lastModifiedDate=now_ms + index,
                        claimItemStatus="Accepted",
                        claimReason=reason,
                        totalPrice=80.0,
                        itemCount=1,
                    )
                )
            session.commit()

        prompt = "genelde niye iade almışız bütün iadelere bak şu ana kadar gelen"
        first = run_agent_turn(
            prompt,
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.query",'
                '"arguments":{"period":"all","limit":100}}'
            ),
            chat_client=lambda _prompt: "100 iade var.",
            db_name=self.db_path,
        )

        self.assertTrue(first.success, first.message)
        self.assertEqual(
            ((first.data or {}).get("tool_call") or {}).get("tool"),
            "returns.reason_summary",
        )
        self.assertEqual(
            ((first.data or {}).get("tool_call") or {}).get("arguments"),
            {"period": "all", "top_n": 10},
        )
        first_data = (first.data or {}).get("tool_result") or {}
        self.assertEqual(first_data.get("total_claims"), 3)
        self.assertEqual(
            ((first.data or {}).get("conversation_context") or {}).get("kind"),
            "return_analysis",
        )
        first_answer = str((first.data or {}).get("answer") or "")
        self.assertIn("3 iade/claim'in neden dagilimi", first_answer)
        self.assertIn("Yanlış ürün gönderildi: 2 claim", first_answer)

        history = [
            {"role": "user", "content": prompt},
            {
                "role": "assistant",
                "content": first_answer,
                "context": (first.data or {}).get("conversation_context") or {},
            },
            {
                "role": "user",
                "content": "tamam genel olarak neen iade atmış insanlar onu soruyorum",
            },
        ]
        recovery = run_agent_turn(
            "tamam genel olarak neen iade atmış insanlar onu soruyorum",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.count",'
                '"arguments":{"period":"all"}}'
            ),
            chat_client=lambda _prompt: "3 claim var.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(recovery.success, recovery.message)
        self.assertEqual(
            ((recovery.data or {}).get("tool_call") or {}).get("tool"),
            "returns.reason_summary",
        )
        self.assertIn(
            "neden dagilimi",
            str((recovery.data or {}).get("answer") or ""),
        )

        coverage_history = [
            *history,
            {
                "role": "assistant",
                "content": str((recovery.data or {}).get("answer") or ""),
                "context": (recovery.data or {}).get("conversation_context") or {},
            },
        ]
        coverage = run_agent_turn(
            "bu analiz 100 kayıtla kesilmedi değil mi, 3'ünün tamamı hesaba girdi mi",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count",'
                '"arguments":{"period":"today"}}'
            ),
            chat_client=lambda _prompt: "Bugun siparis yok.",
            db_name=self.db_path,
            history=coverage_history,
        )
        self.assertTrue(coverage.success, coverage.message)
        self.assertEqual(
            ((coverage.data or {}).get("tool_call") or {}).get("tool"),
            "returns.reason_summary",
        )
        self.assertEqual(
            ((coverage.data or {}).get("tool_result") or {}).get("total_claims"),
            3,
        )

        top_two = run_agent_turn(
            "iade analizine dönelim, en çok hangi iki nedenle iade olmuş ve toplam claimlerin yüzde kaçı",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.count",'
                '"arguments":{"period":"all"}}'
            ),
            chat_client=lambda _prompt: "Uc claim var.",
            db_name=self.db_path,
            history=coverage_history,
        )
        self.assertTrue(top_two.success, top_two.message)
        top_two_call = (top_two.data or {}).get("tool_call") or {}
        self.assertEqual(top_two_call.get("tool"), "returns.reason_summary")
        self.assertEqual((top_two_call.get("arguments") or {}).get("top_n"), 2)
        self.assertEqual(
            len(((top_two.data or {}).get("tool_result") or {}).get("reasons") or []),
            2,
        )
        combined_history = [
            *coverage_history,
            {
                "role": "assistant",
                "content": str((top_two.data or {}).get("answer") or ""),
                "context": (top_two.data or {}).get("conversation_context") or {},
            },
        ]
        combined = run_agent_turn(
            "bu iki neden birlikte tüm claimlerin yüzde kaçına denk geliyor? "
            "hesabı da açıkça göster",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count",'
                '"arguments":{"period":"today"}}'
            ),
            chat_client=lambda _prompt: "Bugun siparis yok.",
            db_name=self.db_path,
            history=combined_history,
        )
        self.assertTrue(combined.success, combined.message)
        self.assertEqual(
            ((combined.data or {}).get("tool_call") or {}).get("tool"),
            "returns.reason_summary",
        )
        combined_answer = str((combined.data or {}).get("answer") or "")
        self.assertIn("2 + 1 = 3 benzersiz claim", combined_answer)
        self.assertIn("3 / 3 x 100 = 100%", combined_answer)

    def test_return_reason_table_advice_with_no_action_boundary_stays_answer(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": (
                    "all kapsamindaki 154 iade/claim'in neden dagilimi: "
                    "1. Begenmedim: 35 claim 2. Teslim edilemeyen gonderi: 27 claim"
                ),
                "context": {
                    "kind": "return_analysis",
                    "source_tool": "returns.reason_summary",
                    "period": "all",
                    "total_claims": 154,
                    "claims_with_reason": 154,
                    "claims_without_reason": 0,
                    "top_reasons": [
                        {
                            "reason": "Begenmedim",
                            "claim_count": 35,
                            "percent_of_all_claims": 22.73,
                        },
                        {
                            "reason": "Teslim edilemeyen gonderi",
                            "claim_count": 27,
                            "percent_of_all_claims": 17.53,
                        },
                    ],
                },
            }
        ]

        result = run_agent_turn(
            "bu tabloya bakinca sence operasyon tarafinda en hizli iyilestirecegimiz alan ne? islem yapma",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count",'
                '"arguments":{"period":"today"}}'
            ),
            chat_client=lambda _prompt: "Tamam, bu islemi calistirmiyorum.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        self.assertFalse((result.data or {}).get("tool_call"))
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Begenmedim", answer)
        self.assertIn("154 claim", answer)
        self.assertIn("İşlem başlatmadan", answer)
        self.assertNotIn("calistirmiyorum", answer)

        explicit_distribution_advice = run_agent_turn(
            "Iade neden dagilimina gore en hizli iyilestirme tavsiyen ne? Islem yapma.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.reason_summary",'
                '"arguments":{"period":"all","top_n":2}}'
            ),
            chat_client=lambda _prompt: "Neden tablosu.",
            db_name=self.db_path,
            history=history,
        )
        self.assertTrue(explicit_distribution_advice.success, explicit_distribution_advice.message)
        self.assertEqual((explicit_distribution_advice.data or {}).get("mode"), "answer")
        self.assertFalse((explicit_distribution_advice.data or {}).get("tool_call"))
        self.assertIn(
            "Begenmedim",
            str((explicit_distribution_advice.data or {}).get("answer") or ""),
        )

    def test_delivery_failure_reason_advice_targets_delivery_operations(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Yedi bekleyen iadenin nedeni teslim edilemeyen gonderi.",
                "context": {
                    "kind": "return_analysis",
                    "source_tool": "returns.reason_summary",
                    "period": "all",
                    "waiting_action_only": True,
                    "total_claims": 7,
                    "top_reasons": [
                        {
                            "reason": "Teslim edilemeyen gönderi",
                            "claim_count": 7,
                            "percent_of_all_claims": 100.0,
                        }
                    ],
                },
            }
        ]

        result = run_agent_turn(
            "Bu dagilima gore ilk operasyonel iyilestirme ne olmali? Islem yapma.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.reason_summary",'
                '"arguments":{"period":"all"}}'
            ),
            chat_client=lambda _prompt: "Urun kalitesini artir.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        self.assertFalse((result.data or {}).get("tool_call"))
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("adres ve telefon doğrulamasını", answer)
        self.assertIn("etiket okunabilirliğini", answer)
        self.assertNotIn("ürün beklentisi/kalite", answer)

        explicit_no_tool = run_agent_turn(
            (
                "Bu dagilima gore ilk iyilestirme adimimiz ne olmali? Yeni tool "
                "calistirma; yalniz az onceki analize dayan."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"answer","response":"Once neye karar verecegimizi "'
                '"netlestirelim."}'
            ),
            chat_client=lambda _prompt: "Once neye karar verecegimizi netlestirelim.",
            db_name=self.db_path,
            history=history,
        )
        self.assertTrue(explicit_no_tool.success, explicit_no_tool.message)
        self.assertEqual((explicit_no_tool.data or {}).get("tool_calls"), [])
        self.assertEqual(
            (explicit_no_tool.data or {}).get("decision_path"),
            "explicit_no_tool_guard",
        )
        no_tool_answer = str((explicit_no_tool.data or {}).get("answer") or "")
        self.assertIn("adres ve telefon", no_tool_answer)
        self.assertIn("etiket okunabilir", no_tool_answer)
        self.assertNotIn("karar verecegimizi netlestirelim", no_tool_answer)

    def test_read_only_qualifier_keeps_newest_return_list_query(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            for index in range(1, 13):
                session.add(
                    ReturnClaim(
                        claimId=f"CLAIM-LATEST-{index:02d}",
                        orderNumber=f"ORD-LATEST-{index:02d}",
                        claimDate=now_ms + index,
                        orderDate=now_ms + index,
                        lastModifiedDate=now_ms + index,
                        claimItemStatus="Accepted",
                        claimReason="Beğenmedim",
                        totalPrice=30.0,
                        itemCount=1,
                    )
                )
            session.commit()

        result = run_agent_turn(
            "şimdilik işlem yapma, son gelen 10 iadeyi listele bakayım",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"returns.lookup",'
                '"arguments":{"query":"son gelen bakayim","limit":10}}'
            ),
            chat_client=lambda _prompt: "Arama sonucu.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        call = (result.data or {}).get("tool_call") or {}
        self.assertEqual(call.get("tool"), "returns.query")
        self.assertEqual((call.get("arguments") or {}).get("period"), "all")
        self.assertEqual((call.get("arguments") or {}).get("limit"), 10)
        data = (result.data or {}).get("tool_result") or {}
        self.assertEqual(data.get("count"), 12)
        self.assertEqual((data.get("pagination") or {}).get("returned"), 10)
        self.assertEqual(len(data.get("returns") or []), 10)
        self.assertFalse(bool((result.data or {}).get("approval_required")))

        newest_claim_wording = run_agent_turn(
            "Simdi tum zamanlardaki en yeni 10 iade talebini getir; sadece oku, islem yapma.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.lookup",'
                '"arguments":{"query":"en yeni 10 iade talebi","limit":10}}'
            ),
            chat_client=lambda _prompt: "Siparis listesi.",
            db_name=self.db_path,
        )
        self.assertTrue(newest_claim_wording.success, newest_claim_wording.message)
        self.assertEqual(
            ((newest_claim_wording.data or {}).get("tool_call") or {}).get("tool"),
            "returns.query",
        )
        self.assertEqual(
            (((newest_claim_wording.data or {}).get("tool_call") or {}).get("arguments") or {}).get("limit"),
            10,
        )

    def test_selected_ready_orders_delay_question_uses_domain_deadline_analysis(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        order_numbers = [
            f"ORD-DELAY-{index:02d}"
            for index in range(1, 22)
        ]
        for index, order_number in enumerate(order_numbers, start=1):
            self._insert_order_snapshot(
                order_number,
                now_ms - (index + 2) * 3_600_000,
                package_id=9900 + index,
                status="ReadyToShip",
                agreed_delivery_date=now_ms - index * 3_600_000,
            )
        history = [
            {
                "role": "assistant",
                "content": "21 kargoya hazir siparis listelendi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.ready_to_ship",
                    "order_numbers": order_numbers,
                    "listed_count": 21,
                    "total_count": 21,
                    "truncated": False,
                    "period": "all",
                },
            }
        ]

        result = run_agent_turn(
            "tamam bu listedeki 21 sipariş gecikmiş gözüküyor sanki, tek tek kaç gün gecikmişler",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.fulfillment_risk_count",'
                '"arguments":{"period":"last_7_days"}}'
            ),
            chat_client=lambda _prompt: "Gecikme yok.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(result.success, result.message)
        tool_call = (result.data or {}).get("tool_call") or {}
        self.assertEqual(tool_call.get("tool"), "orders.shipping_deadline_analysis")
        self.assertEqual(tool_call.get("arguments"), {"order_numbers": order_numbers})
        tool_result = (result.data or {}).get("tool_result") or {}
        self.assertEqual(tool_result.get("requested_count"), 21)
        self.assertEqual(tool_result.get("matched_count"), 21)
        self.assertEqual(tool_result.get("measurable_count"), 21)
        self.assertEqual(tool_result.get("overdue_count"), 21)
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Secili 21 siparisin kargolama son tarihi analizi", answer)
        self.assertIn("agreedDeliveryDate", answer)
        self.assertNotIn("son 7", answer.casefold())
        deadline_context = (result.data or {}).get("conversation_context") or {}
        self.assertEqual(deadline_context.get("kind"), "order_deadline_analysis")
        self.assertEqual(deadline_context.get("requested_count"), 21)
        self.assertEqual(deadline_context.get("overdue_count"), 21)

        source_ui_wording = run_agent_turn(
            "Dosya olustu. Simdi bu listedeki 21 siparisin her birinin kargoya verilme suresini tek tek soyle; desteklenen veriden gecikme gununu hesapla, veri yoksa uydurma.",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Veri yok."}',
            chat_client=lambda _prompt: "Veri yok.",
            db_name=self.db_path,
            history=history,
        )
        self.assertTrue(source_ui_wording.success, source_ui_wording.message)
        self.assertEqual(
            ((source_ui_wording.data or {}).get("tool_call") or {}).get("tool"),
            "orders.shipping_deadline_analysis",
        )
        self.assertEqual(
            ((source_ui_wording.data or {}).get("tool_call") or {}).get("arguments"),
            {"order_numbers": order_numbers},
        )

        three_order_history = [
            {
                "role": "assistant",
                "content": "Uc Stage siparisi listelendi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.ready_to_ship",
                    "order_numbers": order_numbers[:3],
                    "listed_count": 3,
                    "total_count": 21,
                    "truncated": True,
                    "period": "all",
                },
            }
        ]
        natural_risk_wording = run_agent_turn(
            (
                "Bu secili 3 Stage siparisinin anlasmali teslim ve kargoya "
                "verme sure riskini analiz et; yalniz bu uc siparisi kullan, "
                "herhangi bir degisiklik yapma."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":['
                '{"tool":"orders.count","arguments":{"period":"today"}},'
                '{"tool":"orders.fulfillment_risk_count",'
                '"arguments":{"period":"last_7_days"}},'
                '{"tool":"logistics.tariff_count","arguments":{}}]}'
            ),
            chat_client=lambda _prompt: "Genel operasyon analizi.",
            db_name=self.db_path,
            history=three_order_history,
        )
        self.assertTrue(natural_risk_wording.success, natural_risk_wording.message)
        self.assertEqual(
            (natural_risk_wording.data or {}).get("decision_path"),
            "selected_order_deadline_guard",
        )
        natural_call = (natural_risk_wording.data or {}).get("tool_call") or {}
        self.assertEqual(natural_call.get("tool"), "orders.shipping_deadline_analysis")
        self.assertEqual(
            natural_call.get("arguments"),
            {"order_numbers": order_numbers[:3]},
        )

        unmeasurable_advice = run_agent_turn(
            (
                "Bu üç sipariş için ilk operasyonel hamlem ne olmalı? Yeni tool "
                "çalıştırma; yalnız az önceki deadline analizine dayan."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":['
                '{"tool":"orders.count","arguments":{"period":"today"}},'
                '{"tool":"logistics.tariff_count","arguments":{}}]}'
            ),
            chat_client=lambda _prompt: "Önce neye karar vereceğimizi netleştirelim.",
            db_name=self.db_path,
            history=[
                {
                    "role": "assistant",
                    "content": "Üç siparişin deadline verisi ölçülemedi.",
                    "context": {
                        "kind": "order_deadline_analysis",
                        "source_tool": "orders.shipping_deadline_analysis",
                        "order_numbers": order_numbers[:3],
                        "requested_count": 3,
                        "matched_count": 3,
                        "measurable_count": 0,
                        "unmeasurable_count": 3,
                        "overdue_count": 0,
                    },
                }
            ],
        )
        self.assertTrue(unmeasurable_advice.success, unmeasurable_advice.message)
        self.assertEqual((unmeasurable_advice.data or {}).get("tool_calls"), [])
        self.assertEqual(
            (unmeasurable_advice.data or {}).get("decision_path"),
            "explicit_no_tool_guard",
        )
        unmeasurable_answer = str(
            (unmeasurable_advice.data or {}).get("answer") or ""
        )
        self.assertIn("hiçbirinde ölçülebilir agreedDeliveryDate", unmeasurable_answer)
        self.assertIn("3 kayıt ölçülemiyor", unmeasurable_answer)
        self.assertIn("uyduramam", unmeasurable_answer)

        same_authoritative_wording = run_agent_turn(
            "Ayni authoritative 21 siparisin kargoya verilme suresi ve gecikme gunlerini analiz et; listeyi kisaltma.",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count","arguments":{"period":"all"}}'
            ),
            chat_client=lambda _prompt: "Genel analiz.",
            db_name=self.db_path,
            history=history,
        )
        self.assertTrue(same_authoritative_wording.success, same_authoritative_wording.message)
        self.assertEqual(
            ((same_authoritative_wording.data or {}).get("tool_call") or {}).get("tool"),
            "orders.shipping_deadline_analysis",
        )
        self.assertEqual(
            ((same_authoritative_wording.data or {}).get("tool_call") or {}).get("arguments"),
            {"order_numbers": order_numbers},
        )

        advice_history = [
            {
                "role": "assistant",
                "content": answer,
                "context": deadline_context,
            }
        ]
        advice = run_agent_turn(
            "tamam dosyayı gördüm, bu kadar gecikmiş siparişte sence ilk operasyonel hamlem ne olmalı",
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":['
                '{"tool":"orders.count","arguments":{"period":"today"}},'
                '{"tool":"returns.count","arguments":{"period":"today"}}]}'
            ),
            chat_client=lambda _prompt: "Genel analiz yapalim.",
            db_name=self.db_path,
            history=advice_history,
        )
        self.assertTrue(advice.success, advice.message)
        self.assertEqual((advice.data or {}).get("mode"), "answer")
        self.assertFalse((advice.data or {}).get("tool_call"))
        advice_answer = str((advice.data or {}).get("answer") or "")
        self.assertIn("21/21", advice_answer)
        self.assertIn("agreedDeliveryDate", advice_answer)

        no_overdue_context = dict(deadline_context)
        no_overdue_context["overdue_count"] = 0
        no_overdue_advice = run_agent_turn(
            "Bu 21 siparis icin sence ilk operasyonel hamlem ne olmali? Islem baslatma.",
            planner_client=lambda _prompt: (
                '{"mode":"tools","calls":[{"tool":"orders.count","arguments":{"period":"all"}}]}'
            ),
            chat_client=lambda _prompt: "Genel analiz yapalim.",
            db_name=self.db_path,
            history=[{"role": "assistant", "content": "Deadline analizi.", "context": no_overdue_context}],
        )
        self.assertTrue(no_overdue_advice.success, no_overdue_advice.message)
        self.assertEqual((no_overdue_advice.data or {}).get("mode"), "answer")
        self.assertFalse((no_overdue_advice.data or {}).get("tool_call"))
        self.assertIn("0/21", str((no_overdue_advice.data or {}).get("answer") or ""))

        long_history = [
            *advice_history,
            {
                "role": "assistant",
                "content": "154 claim nedeni analiz edildi.",
                "context": {
                    "kind": "return_analysis",
                    "source_tool": "returns.reason_summary",
                    "period": "all",
                    "total_claims": 154,
                },
            },
        ]
        repeated = run_agent_turn(
            "az önceki 21 siparişin gecikme analizini tekrar kontrol et, iade kayıtlarını bu kapsama karıştırma",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count",'
                '"arguments":{"period":"today"}}'
            ),
            chat_client=lambda _prompt: "Magaza analizi.",
            db_name=self.db_path,
            history=long_history,
        )
        self.assertTrue(repeated.success, repeated.message)
        self.assertEqual(
            ((repeated.data or {}).get("tool_call") or {}).get("tool"),
            "orders.shipping_deadline_analysis",
        )
        self.assertEqual(
            ((repeated.data or {}).get("tool_call") or {}).get("arguments"),
            {"order_numbers": order_numbers},
        )

        extremes = run_agent_turn(
            "bu 21 sipariş içinde en fazla geciken kaç gün gecikmiş, en az geciken de kaç gün",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.fulfillment_risk_count",'
                '"arguments":{"period":"last_7_days"}}'
            ),
            chat_client=lambda _prompt: "Genel risk sayimi.",
            db_name=self.db_path,
            history=advice_history,
        )
        self.assertTrue(extremes.success, extremes.message)
        self.assertEqual(
            ((extremes.data or {}).get("tool_call") or {}).get("tool"),
            "orders.shipping_deadline_analysis",
        )
        extremes_answer = str((extremes.data or {}).get("answer") or "")
        self.assertIn("Dogru cevap: en fazla geciken", extremes_answer)
        self.assertIn("; en az geciken", extremes_answer)

    def test_customer_experience_speed_vs_accuracy_gets_direct_opinion(self) -> None:
        result = run_agent_turn(
            "bu arada sence müşteri deneyiminde en kritik şey hız mı doğruluk mu",
            planner_client=lambda _prompt: (
                '{"mode":"answer","response":"Bence once neye karar verecegimizi netlestirelim."}'
            ),
            chat_client=lambda _prompt: "Bence once neye karar verecegimizi netlestirelim.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Doğruluk temel", answer)
        self.assertIn("hız", answer)

    def test_general_speed_vs_accuracy_gets_direct_opinion_in_long_context(self) -> None:
        result = run_agent_turn(
            "genel olarak bu işte hız mı daha önemli doğruluk mu, "
            "sen olsan nasıl denge kurardın?",
            planner_client=lambda _prompt: (
                '{"mode":"answer","response":"Iyiyim, buradayim."}'
            ),
            chat_client=lambda _prompt: "Iyiyim, buradayim.",
            db_name=self.db_path,
            history=[
                {"role": "user", "content": "Kargoya hazir siparisleri listele."},
                {
                    "role": "assistant",
                    "content": "Kargoya hazir 21 siparis var.",
                },
            ],
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Doğruluk temel", answer)
        self.assertIn("tutarlı hız", answer)
        self.assertNotIn("Iyiyim, buradayim", answer)

    def test_local_model_speed_accuracy_opinion_is_not_replaced_by_generic_ecommerce_fallback(self) -> None:
        prompt = (
            "Yerel Qwen modeliyle calisirken hiz ve dogruluk arasinda nasil "
            "denge kurardin? E-ticaret verisi okuma; hicbir tool calistirma."
        )
        result = run_agent_turn(
            prompt,
            planner_client=lambda _prompt: (
                '{"mode":"answer","response":"E-ticaret iyi bir alan."}'
            ),
            chat_client=lambda _prompt: "E-ticaret iyi bir alan.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        self.assertEqual((result.data or {}).get("tool_calls"), [])
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("Doğruluk temel", answer)
        self.assertIn("tutarlı hız", answer)
        self.assertNotEqual(answer, "E-ticaret iyi bir alan.")

    def test_general_knowledge_escapes_stale_orders_context_and_invokes_model(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "21 siparis listelendi.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.ready_to_ship",
                    "order_numbers": ["ORD-CONTEXT-1"],
                    "listed_count": 1,
                    "total_count": 1,
                    "truncated": False,
                },
            }
        ]

        def planner(_prompt: str) -> str:
            return '{"mode":"answer","response":"Kuantum dolanikligi iki parcacigin durumlarinin uzaktan baglantili olmasidir."}'

        for prompt in (
            "Kuantum dolanikligini teknik olmayan birine iki cumlede anlat.",
            "Hayir, bu bir siparis sorgusu degil. Genel bilgi sorusuydu: kuantum dolanikligini anlat.",
        ):
            with self.subTest(prompt=prompt):
                result = run_agent_turn(
                    prompt,
                    planner_client=planner,
                    chat_client=planner,
                    db_name=self.db_path,
                    history=history,
                )
                self.assertTrue(result.success, result.message)
                self.assertEqual((result.data or {}).get("mode"), "answer")
                self.assertFalse((result.data or {}).get("tool_call"))
                self.assertTrue((result.data or {}).get("model_invoked"))
                self.assertIn("Kuantum", str((result.data or {}).get("answer") or ""))

        risk_testing = run_agent_turn(
            "Risk tabanli yazilim testini teknik olmayan birine tek paragrafta acikla.",
            planner_client=lambda _prompt: (
                '{"mode":"answer","response":"Risk tabanli test, en kritik alanlara once bakar."}'
            ),
            chat_client=lambda _prompt: "Risk tabanli test, en kritik alanlara once bakar.",
            db_name=self.db_path,
            history=history,
        )
        self.assertTrue(risk_testing.success, risk_testing.message)
        self.assertEqual((risk_testing.data or {}).get("mode"), "answer")
        self.assertFalse((risk_testing.data or {}).get("tool_call"))
        self.assertTrue((risk_testing.data or {}).get("model_invoked"))

    def test_today_conversation_self_assessment_never_routes_to_listing_tool(self) -> None:
        result = run_agent_turn(
            "bugünkü bu konuşmayı tek cümleyle değerlendir, nerede daha dikkatli olmalısın?",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"listing.attention_count","arguments":{}}'
            ),
            chat_client=lambda _prompt: "14 ilan dikkat istiyor.",
            db_name=self.db_path,
            history=[
                {"role": "assistant", "content": "Kargoya hazir 21 siparis var."},
                {"role": "assistant", "content": "154 claim nedeni analiz edildi."},
            ],
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        self.assertFalse((result.data or {}).get("tool_call"))
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("en dikkatli olmam gereken yer", answer)
        self.assertLessEqual(answer.count("\n"), 1)
        self.assertNotIn("ilan dikkat", answer)

    def test_conversation_how_did_you_find_it_is_retrospective_not_generic_chat(self) -> None:
        result = run_agent_turn(
            "bugunku sohbetimizi bir cumleyle nasil buldun?",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"listing.attention_count","arguments":{}}'
            ),
            chat_client=lambda _prompt: "Genel ve baglamsiz cevap.",
            db_name=self.db_path,
            history=[
                {"role": "assistant", "content": "Kargoya hazir 199 siparis var."},
                {"role": "assistant", "content": "Etiketler yalniz onaya hazirlandi."},
            ],
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "answer")
        self.assertFalse((result.data or {}).get("tool_call"))
        answer = str((result.data or {}).get("answer") or "")
        normalized_answer = ai_agent._normalized_match_text(answer)
        self.assertIn("siparis", normalized_answer)
        self.assertIn("etiket", normalized_answer)
        self.assertNotIn("Genel ve baglamsiz", answer)

    def test_simulation_explanation_plus_ready_list_restores_all_scope_with_evidence(self) -> None:
        now_ms = int(datetime.now(TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot(
            "ORD-REAL-READY-1",
            now_ms,
            package_id=9801,
            status="ReadyToShip",
        )
        self._insert_order_snapshot(
            "ORD-REAL-READY-2",
            now_ms + 1,
            package_id=9802,
            status="ReadyToShip",
        )
        self._insert_order_snapshot(
            "SIM-READY-1",
            now_ms + 2,
            package_id=9803,
            status="ReadyToShip",
        )
        count = run_agent_turn(
            "kaç bekleyen sipariş var toplamda",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.ready_to_ship_count",'
                '"arguments":{"period":"all"}}'
            ),
            db_name=self.db_path,
        )
        self.assertTrue(count.success, count.message)
        context = (count.data or {}).get("conversation_context") or {}
        self.assertEqual(context.get("total_count"), 2)
        self.assertEqual(context.get("simulated_excluded"), 1)

        history = [
            {
                "role": "assistant",
                "content": str((count.data or {}).get("answer") or ""),
                "context": context,
            }
        ]
        listed = run_agent_turn(
            "simülasyonlar niye dahil edilmedi, sonra bu 2 siparişi listele",
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.count",'
                '"arguments":{"period":"today"}}'
            ),
            chat_client=lambda _prompt: "Bugun sifir siparis var.",
            db_name=self.db_path,
            history=history,
        )

        self.assertTrue(listed.success, listed.message)
        self.assertEqual(
            ((listed.data or {}).get("tool_call") or {}).get("tool"),
            "orders.ready_to_ship",
        )
        self.assertEqual(
            ((listed.data or {}).get("tool_call") or {}).get("arguments"),
            {"period": "all", "limit": 2},
        )
        listed_data = (listed.data or {}).get("tool_result") or {}
        self.assertEqual(listed_data.get("ready_to_ship"), 2)
        answer = str((listed.data or {}).get("answer") or "")
        self.assertIn("ORD-REAL-READY-1", answer)
        self.assertIn("ORD-REAL-READY-2", answer)
        self.assertNotIn("SIM-READY-1", answer)
        self.assertIn("orderNumber", answer)
        self.assertIn("Simulated", answer)

    def test_explicit_waiting_return_projection_overrides_stale_order_selection(self) -> None:
        history = [
            {
                "role": "assistant",
                "content": "Secili siparis ORD-STALE-1.",
                "context": {
                    "kind": "order_selection",
                    "source_tool": "orders.full_context",
                    "order_numbers": ["ORD-STALE-1"],
                    "listed_count": 1,
                    "total_count": 1,
                    "truncated": False,
                },
            }
        ]

        result = choose_action(
            (
                "WaitingInAction durumundaki en son 2 iade claimini siparis "
                "numarasi, claim kimligi, durum ve tutarla listele."
            ),
            planner_client=lambda _prompt: (
                '{"mode":"tool","tool":"orders.full_context",'
                '"arguments":{"query":"ORD-STALE-1","limit":1}}'
            ),
            history=history,
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(getattr(decision, "tool_name", ""), "returns.query")
        self.assertEqual(
            getattr(decision, "arguments", {}),
            {
                "period": "all",
                "filters": {"status": "WaitingInAction"},
                "sort": "claim_date_desc",
                "limit": 2,
                "mode": "list",
                "page": 1,
                "page_size": 2,
            },
        )

    def test_waiting_return_list_question_uses_returns_query_not_count(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-WAIT-AGENT-1",
                    orderNumber="ORD-WAIT-AGENT-1",
                    claimDate=today_start + 1_000,
                    orderDate=today_start + 1_000,
                    lastModifiedDate=today_start + 2_000,
                    claimItemStatus="WaitingInAction",
                    totalPrice=88.0,
                    itemCount=2,
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-ACCEPTED-AGENT-1",
                    orderNumber="ORD-ACCEPTED-AGENT-1",
                    claimDate=today_start + 3_000,
                    orderDate=today_start + 3_000,
                    lastModifiedDate=today_start + 4_000,
                    claimItemStatus="Accepted",
                    totalPrice=55.0,
                    itemCount=1,
                )
            )
            session.commit()

        chat_prompts: list[str] = []

        def chat_client(prompt: str) -> str:
            chat_prompts.append(prompt)
            return "Cloud cevabi."

        result = run_agent_turn(
            "Onay bekleyen iadeleri listele",
            planner_client=lambda _prompt: '{"mode":"tool","tool":"returns.waiting_action_count","arguments":{"period":"all"}}',
            chat_client=chat_client,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "returns.query")
        tool_result = (result.data or {}).get("tool_result") or {}
        returns = tool_result.get("returns") or []
        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].get("claim_id"), "CLAIM-WAIT-AGENT-1")
        self.assertIn("claim_date_ms", returns[0])
        self.assertIn("claim_date", returns[0])
        self.assertTrue(chat_prompts)
        self.assertIn('"claim_date"', chat_prompts[-1])
        self.assertNotIn("claim_date_ms", chat_prompts[-1])
        self.assertNotIn(str(today_start + 1_000), chat_prompts[-1])
        answer = str((result.data or {}).get("answer") or "")
        self.assertIn("CLAIM-WAIT-AGENT-1", answer)
        self.assertIn("WaitingInAction", answer)

    def test_prompt_categories_survive_tight_local_context_without_llm_planner(self) -> None:
        def failing_local_client(_prompt: str) -> str:
            raise RuntimeError("HTTP istegi basarisiz.")

        setattr(failing_local_client, "runtime_name", "llama_cpp_server")
        setattr(failing_local_client, "resource_plan", {"num_ctx": 768, "max_tokens": 192})

        cases = [
            ("Bugun kac siparisim var?", ["orders.count"]),
            ("Bugun siparis ve stok sayilarini ozetle", ["orders.count", "stock.low_stock_count"]),
            (
                "Bugun ciro, kar, iade, kargoya hazir ve risk sayilarini beraber kontrol et",
                [
                    "orders.revenue_total",
                    "finance.profit_amount",
                    "returns.count",
                    "orders.ready_to_ship_count",
                    "orders.fulfillment_risk_count",
                ],
            ),
            (
                "Bugun siparis, ciro, kar, stok, ilan, pazaryeri, token, kargo tarife ve maliyet kalemi durumunu tek raporda toparla",
                [
                    "orders.count",
                    "orders.revenue_total",
                    "finance.profit_amount",
                    "stock.low_stock_count",
                    "listing.counts",
                    "accounts.invalid_token_count",
                    "logistics.tariff_count",
                    "finance.cost_item_count",
                ],
            ),
        ]

        for prompt, expected in cases:
            result = run_agent_turn(
                prompt,
                planner_client=failing_local_client,
                chat_client=failing_local_client,
                db_name=self.db_path,
            )
            self.assertTrue(result.success, result.message)
            actual = [row.get("tool") for row in ((result.data or {}).get("tool_calls") or [])]
            self.assertTrue(set(expected).issubset(set(actual)), f"{prompt}: {actual}")

    def test_store_overview_request_uses_multi_tool_plan_not_plain_answer(self) -> None:
        expected = {
            "orders.count",
            "orders.revenue_total",
            "finance.profit_amount",
            "returns.count",
            "stock.low_stock_count",
            "listing.counts",
            "marketplaces.account_count",
        }
        for prompt in (
            "Mağazam hakkında genel yorum yap",
            "MaÄŸazam hakkÄ±nda genel yorum yap",
            "Ma??azam hakk??nda genel yorum yap",
            "ben-genel olarak mağaza hakkında yorum yap",
            "mağazamı hoca gibi değerlendir",
            "mağaza sağlığı nasıl",
            "ma?azam? hoca gibi de?erlendir",
            "ma?aza sa?l??? nas?l",
        ):
            decision_res = choose_action(prompt)
            self.assertTrue(decision_res.success, decision_res.message)
            decision = (decision_res.data or {}).get("decision")
            self.assertEqual(getattr(decision, "mode", None), "tools")
            tool_names = [call.tool_name for call in (getattr(decision, "tool_calls", ()) or [])]
            self.assertTrue(expected.issubset(set(tool_names)), tool_names)

        result = run_agent_turn(
            "Mağazam hakkında genel yorum yap",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Bu verilere erisemiyorum."}',
            chat_client=lambda _prompt: "Bu verilere erisemiyorum.",
            db_name=self.db_path,
        )
        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "tools")
        answer = (result.data or {}).get("answer") or ""
        self.assertNotIn("erisemiyorum", answer.casefold())
        self.assertIn("Magaza genel yorumu", answer)
        self.assertNotIn("Bugun siparis", answer)
        self.assertIn("tum zamanlar", answer)
        actual_tools = [row.get("tool") for row in ((result.data or {}).get("tool_calls") or [])]
        self.assertTrue(expected.issubset(set(actual_tools)), actual_tools)

    def test_store_overview_rejects_llm_period_contradiction(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot(
            "ORD-PERIOD-GUARD-1",
            today_start + 1_000,
            package_id=3911,
            status="ReadyToShip",
            total_price=100.0,
        )
        with Session(get_engine(self.db_path)) as session:
            session.add(
                ReturnClaim(
                    claimId="CLAIM-PERIOD-GUARD-1",
                    orderNumber="ORD-PERIOD-GUARD-1",
                    claimDate=today_start + 2_000,
                    orderDate=today_start + 1_000,
                    lastModifiedDate=today_start + 3_000,
                    claimItemStatus="WaitingInAction",
                    totalPrice=55.0,
                    itemCount=1,
                )
            )
            session.commit()

        result = run_agent_turn(
            "siparislerim nasil sence",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Dun itibariyla 1 iade var."}',
            chat_client=lambda _prompt: "Dun itibariyla 1 iade var.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        answer = str((result.data or {}).get("answer") or "")
        self.assertNotIn("Dun itibariyla", answer)
        self.assertIn("Siparis", answer)
        self.assertIn("1", answer)
        self.assertIn("Iade", answer)

    def test_llm_stock_quantity_write_is_repaired_to_listing_stock_prepare(self) -> None:
        result = run_agent_turn(
            "At kili firca stok adedini 12 yap",
            planner_client=lambda prompt: (
                '{"mode":"tool","tool":"stock.item_update.prepare","arguments":{"query":"at kili firca"}}'
                if "Cikti yalnizca JSON olsun" in prompt
                else "Stok guncelleme hazirlandi."
            ),
            chat_client=lambda _prompt: "Stok guncelleme hazirlandi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.update_stock.prepare")
        self.assertFalse((result.data or {}).get("approval_required"))
        proposal = ((result.data or {}).get("tool_result") or {}).get("action") or {}
        self.assertFalse(bool(proposal.get("execute_enabled")))

    def test_ready_to_ship_scalar_question_uses_count_tool(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot(
            "ORD-READY-1",
            today_start + 1_000,
            package_id=401,
            status="ReadyToShip",
            printed=True,
        )
        self._insert_order_snapshot(
            "ORD-READY-2",
            today_start + 2_000,
            package_id=402,
            status="ReadyToShip",
        )

        result = run_agent_turn(
            "Bugun kargolanacak kac siparisim var?",
            planner_client=lambda prompt: (
                '{"mode": "tool", "tool": "orders.ready_to_ship", "arguments": {"period": "today", "limit": 5}}'
                if "Cikti yalnizca JSON olsun" in prompt
                else "Bugun kargoya hazir 2 siparis var; 1 tanesi yazdirilmamis."
            ),
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "orders.ready_to_ship_count")
        tool_result = (result.data or {}).get("tool_result") or {}
        self.assertEqual(tool_result.get("count"), 2)

    def test_generic_print_orders_prepares_labels_for_ready_unprinted_orders(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot(
            "ORD-PRINTED-READY",
            today_start + 1_000,
            package_id=601,
            status="ReadyToShip",
            printed=True,
        )
        self._insert_order_snapshot(
            "ORD-UNPRINTED-READY",
            today_start + 2_000,
            package_id=602,
            status="ReadyToShip",
            printed=False,
        )
        self._insert_order_snapshot(
            "ORD-DELIVERED-NO-PRINT",
            today_start + 3_000,
            package_id=603,
            status="Delivered",
            printed=False,
        )

        result = run_agent_turn(
            "Siparisleri yazdir",
            planner_client=lambda _prompt: '{"mode":"answer","response":"Siparis bulunamadi."}',
            chat_client=lambda _prompt: "Siparis bulunamadi.",
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "labels.create_from_orders.prepare")
        self.assertTrue((result.data or {}).get("approval_required"))
        tool_result = (result.data or {}).get("tool_result") or {}
        self.assertEqual(tool_result.get("order_numbers"), ["ORD-UNPRINTED-READY"])
        action = tool_result.get("action") or {}
        self.assertTrue(action.get("execute_enabled"), action)
        self.assertNotIn("Siparis bulunamadi", str((result.data or {}).get("answer") or ""))

    def test_orders_agentic_question_matrix_repairs_bad_planner_outputs(self) -> None:
        now = datetime.now(TZ_GMT3)
        today_start = int(datetime.combine(now.date(), datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        old_ready_ms = int((now - timedelta(hours=30)).timestamp() * 1000)
        self._insert_order_snapshot("ORD-MATRIX-CHEAP", today_start + 1_000, package_id=701, total_price=89.0)
        self._insert_order_snapshot("ORD-MATRIX-HIGH", today_start + 2_000, package_id=702, total_price=1499.0)
        self._insert_order_snapshot(
            "ORD-MATRIX-READY",
            today_start + 3_000,
            package_id=703,
            status="ReadyToShip",
            printed=False,
            cargo_provider_name="Aras Kargo",
            cargo_tracking_number="TRK-MATRIX-READY",
            total_price=320.0,
        )
        self._insert_order_snapshot(
            "ORD-MATRIX-RISK",
            old_ready_ms,
            package_id=704,
            status="ReadyToShip",
            cargo_provider_name="",
            cargo_tracking_number="",
            total_price=410.0,
        )

        bad_planner = lambda _prompt: '{"mode":"answer","response":"Bu veriye erisemiyorum."}'
        bad_chat = lambda _prompt: "Bu veriye erisemiyorum."

        highest = run_agent_turn(
            "En yuksek fiyatli siparisimi getir",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(highest.success, highest.message)
        self.assertEqual(((highest.data or {}).get("tool_call") or {}).get("tool"), "orders.query")
        highest_rows = ((highest.data or {}).get("tool_result") or {}).get("orders") or []
        self.assertEqual(highest_rows[0].get("order_number"), "ORD-MATRIX-HIGH")
        self.assertIn("ORD-MATRIX-HIGH", str((highest.data or {}).get("answer") or ""))
        self.assertNotIn("erisemiyorum", str((highest.data or {}).get("answer") or "").casefold())

        ready = run_agent_turn(
            "Kargoya hazir yazdirilmamis paketleri listele",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(ready.success, ready.message)
        self.assertEqual(((ready.data or {}).get("tool_call") or {}).get("tool"), "orders.ready_to_ship")
        ready_result = (ready.data or {}).get("tool_result") or {}
        self.assertGreaterEqual(int(ready_result.get("not_printed") or 0), 1)
        ready_numbers = {row.get("order_number") for row in (ready_result.get("orders") or [])}
        self.assertIn("ORD-MATRIX-READY", ready_numbers)

        risk = run_agent_turn(
            "Kargo takip veya firma eksigi olan riskli siparisleri goster",
            planner_client=bad_planner,
            chat_client=bad_chat,
            db_name=self.db_path,
        )
        self.assertTrue(risk.success, risk.message)
        self.assertEqual(((risk.data or {}).get("tool_call") or {}).get("tool"), "orders.fulfillment_risk")
        risk_rows = ((risk.data or {}).get("tool_result") or {}).get("orders") or []
        risk_by_number = {row.get("order_number"): row for row in risk_rows}
        self.assertIn("ORD-MATRIX-RISK", risk_by_number)
        self.assertIn("cargo_provider_missing", risk_by_number["ORD-MATRIX-RISK"].get("reasons") or [])
        self.assertIn("tracking_missing", risk_by_number["ORD-MATRIX-RISK"].get("reasons") or [])

    def test_agent_runs_multi_tool_turn_and_keeps_trace(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-MULTI-1", today_start + 1_000, package_id=501)

        result = run_agent_turn(
            "Bugun siparis ve iade durumunu birlikte ozetle",
            planner_client=lambda prompt: (
                '{"mode": "tools", "calls": ['
                '{"tool": "orders.summary", "arguments": {"period": "today"}},'
                '{"tool": "returns.summary", "arguments": {"period": "today"}}'
                "]}"
                if "Cikti yalnizca JSON olsun" in prompt
                else "Bugun lokal kayda gore 1 siparis var; iade kaydi gorunmuyor."
            ),
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("mode"), "tools")
        self.assertEqual((result.data or {}).get("answer"), "Bugun lokal kayda gore 1 siparis var; iade kaydi gorunmuyor.")
        self.assertEqual(
            [row.get("tool") for row in ((result.data or {}).get("tool_calls") or [])],
            ["orders.summary", "returns.summary"],
        )
        tool_result = (result.data or {}).get("tool_result") or {}
        self.assertEqual(len(tool_result.get("tools") or []), 2)
        self.assertTrue((result.data or {}).get("trace"))

    def test_agent_keeps_natural_order_list_answer_when_exact_ids_are_present(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-NATURAL-1", today_start + 1_000, package_id=801, total_price=125.0)
        self._insert_order_snapshot("ORD-NATURAL-2", today_start + 2_000, package_id=802, total_price=75.0)
        prompts: list[str] = []

        def natural_llm(prompt: str) -> str:
            prompts.append(prompt)
            if "Cikti yalnizca JSON olsun" in prompt:
                return '{"mode":"tool","tool":"orders.recent","arguments":{"period":"today","limit":2}}'
            return (
                "Son iki siparisin bunlar: ORD-NATURAL-2 su an Created durumda ve tutari 75 TL. "
                "ORD-NATURAL-1 de Created durumda, tutari 125 TL."
            )

        result = run_agent_turn(
            "son gelen 2 siparisi soyle",
            planner_client=natural_llm,
            chat_client=natural_llm,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("Son iki siparisin bunlar", answer)
        self.assertIn("ORD-NATURAL-2", answer)
        self.assertIn("ORD-NATURAL-1", answer)
        synthesis_prompt = prompts[-1]
        self.assertIn("exact order_number", synthesis_prompt)
        self.assertIn("exact siparis/iade id'sini atlama", synthesis_prompt)

    def test_agent_replaces_json_like_local_synthesis_with_tool_message(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-JSONISH-1", today_start + 1_000, package_id=701)

        def jsonish_llm(prompt: str) -> str:
            if "Cikti yalnizca JSON olsun" in prompt:
                return '{"mode":"tool","tool":"orders.count","arguments":{"period":"today"}}'
            return '{"period":"today","period_label":"'

        result = run_agent_turn(
            "Bugun kac siparisim var?",
            planner_client=jsonish_llm,
            chat_client=jsonish_llm,
            db_name=self.db_path,
        )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("answer"), f"{today.isoformat()} doneminde 1 siparis var.")
        self.assertEqual(((result.data or {}).get("tool_result") or {}).get("count"), 1)

    def test_openai_compatible_provider_client_can_drive_agent_turn(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        self._insert_order_snapshot("ORD-CLOUD-1", today_start + 1_000, package_id=301)

        calls: list[dict] = []

        def fake_post(url, headers=None, json=None, timeout=0):
            calls.append({"url": url, "headers": dict(headers or {}), "json": dict(json or {})})
            prompt = str(((json or {}).get("messages") or [{}])[0].get("content") or "")
            if "Cikti yalnizca JSON olsun" in prompt:
                content = '{"mode": "tool", "tool": "orders.summary", "arguments": {"period": "today"}}'
            else:
                content = "Cloud modele gore bugun lokal kayitta 1 siparis var."
            return _FakeProviderResponse({"choices": [{"message": {"content": content}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=fake_post):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openai",
                    "endpoint_url": "https://api.example.test/v1",
                    "api_key": "sk-test",
                    "default_model": "test-model",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(getattr(client, "runtime_name", None), "openai_chat")
            self.assertEqual(getattr(client, "model_name", None), "test-model")
            self.assertEqual((getattr(client, "resource_plan", {}) or {}).get("profile"), "cloud_provider")
            result = run_agent_turn(
                "Bugun kac siparisim var?",
                model_record={"provider_code": "openai", "default_model": "test-model"},
                planner_client=client,
                chat_client=client,
                db_name=self.db_path,
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("answer"), "Cloud modele gore bugun lokal kayitta 1 siparis var.")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "orders.summary")
        self.assertEqual(calls[0]["url"], "https://api.example.test/v1/chat/completions")
        self.assertEqual(calls[0]["headers"].get("Authorization"), "Bearer sk-test")
        self.assertEqual(calls[0]["json"].get("model"), "test-model")
        self.assertGreaterEqual(calls[0]["json"].get("max_tokens"), 2048)

    def test_cloud_provider_client_allows_larger_output_budget_overrides(self) -> None:
        calls: list[dict] = []

        def fake_post(_url, headers=None, json=None, timeout=0):
            calls.append(dict(json or {}))
            return _FakeProviderResponse({"choices": [{"message": {"content": "OK"}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=fake_post):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openai",
                    "endpoint_url": "https://api.example.test/v1",
                    "api_key": "sk-test",
                    "default_model": "test-model",
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Merhaba"), "OK")

        self.assertEqual(calls[0].get("max_tokens"), 4096)
        self.assertEqual(calls[0].get("temperature"), 0.2)

    def test_openrouter_client_does_not_force_reasoning_for_unsupported_model(self) -> None:
        calls: list[dict] = []

        def fake_post(_url, headers=None, json=None, timeout=0):
            calls.append(dict(json or {}))
            return _FakeProviderResponse({"choices": [{"message": {"content": "Temiz cevap."}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=fake_post):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "free-test-model",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Merhaba"), "Temiz cevap.")

        self.assertNotIn("reasoning", calls[0])

    def test_openrouter_client_sends_selected_reasoning_effort_for_supported_model(self) -> None:
        calls: list[dict] = []

        def fake_post(_url, headers=None, json=None, timeout=0):
            calls.append(dict(json or {}))
            return _FakeProviderResponse({"choices": [{"message": {"content": "Dusunerek cevap."}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=fake_post):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "openai/gpt-oss-120b:free",
                    "reasoning_effort": "high",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Merhaba"), "Dusunerek cevap.")

        self.assertEqual(calls[0].get("reasoning"), {"effort": "high", "exclude": True})
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("reasoning_effort"), "high")
        self.assertTrue((plan.get("reasoning_capabilities") or {}).get("supported"))

    def test_openrouter_guarded_json_planner_gets_larger_budget_and_disables_optional_reasoning(self) -> None:
        calls: list[dict] = []

        def fake_post(_url, headers=None, json=None, timeout=0):
            calls.append(dict(json or {}))
            return _FakeProviderResponse(
                {"choices": [{"message": {"content": '{"steps":[]}'}}]}
            )

        with patch.object(cloud_runtime.requests, "post", side_effect=fake_post):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "nvidia/nemotron-3-super-120b-a12b:free",
                    "reasoning_effort": "auto",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = provider_adapters.invoke_provider_planner(
                client,
                "JSON plan dondur",
                response_schema={"type": "object"},
            )

        self.assertEqual(json.loads(answer), {"steps": []})
        self.assertGreaterEqual(
            calls[0].get("max_tokens"),
            cloud_runtime.DEFAULT_STRUCTURED_OUTPUT_MAX_TOKENS,
        )
        self.assertEqual(
            calls[0].get("reasoning"),
            {"effort": "none", "exclude": True},
        )
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("last_invocation_contract"), "json_text_guarded")
        self.assertIn(
            "json_text_guarded",
            plan.get("invocation_contract_history") or [],
        )

    def test_openrouter_client_preserves_explicit_reasoning_configuration(self) -> None:
        calls: list[dict] = []

        def fake_post(_url, headers=None, json=None, timeout=0):
            calls.append(dict(json or {}))
            return _FakeProviderResponse({"choices": [{"message": {"content": "OK"}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=fake_post):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "free-test-model",
                    "reasoning": {"effort": "low", "exclude": True},
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Merhaba"), "OK")

        self.assertEqual(calls[0].get("reasoning"), {"effort": "low", "exclude": True})

    def test_openrouter_client_falls_back_to_validated_free_model_on_transient_failure(self) -> None:
        failed = _FakeProviderResponse(
            {"error": {"message": "model rate limit reached"}},
            status_code=429,
            reason="Too Many Requests",
            url="https://openrouter.ai/api/v1/chat/completions",
        )
        ok = _FakeProviderResponse({"choices": [{"message": {"content": "Yedek model cevabi."}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=[failed, ok]) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "weak-free-model:free",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Merhaba"), "Yedek model cevabi.")

        models = [call.kwargs["json"]["model"] for call in post_mock.call_args_list]
        self.assertEqual(models, ["weak-free-model:free", cloud_runtime.OPENROUTER_VALIDATED_FREE_MODEL])
        self.assertEqual(getattr(client, "model_name", ""), cloud_runtime.OPENROUTER_VALIDATED_FREE_MODEL)
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("requested_model"), "weak-free-model:free")
        self.assertEqual(plan.get("actual_model"), cloud_runtime.OPENROUTER_VALIDATED_FREE_MODEL)
        self.assertTrue(plan.get("fallback_used"))

    def test_openrouter_client_retries_fallback_when_model_returns_empty_content(self) -> None:
        empty = _FakeProviderResponse({"choices": [{"message": {"content": ""}}]})
        ok = _FakeProviderResponse({"choices": [{"message": {"content": "Bos olmayan yedek cevap."}}]})

        with patch.object(cloud_runtime.requests, "post", side_effect=[empty, empty, ok]) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "weak-free-model:free",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            self.assertEqual(client("Merhaba"), "Bos olmayan yedek cevap.")

        models = [call.kwargs["json"]["model"] for call in post_mock.call_args_list]
        self.assertEqual(
            models,
            [
                "weak-free-model:free",
                cloud_runtime.OPENROUTER_VALIDATED_FREE_MODEL,
                "openai/gpt-oss-120b:free",
            ],
        )
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(plan.get("actual_model"), "openai/gpt-oss-120b:free")
        self.assertEqual(
            plan.get("fallback_attempts"),
            [
                {"model": "weak-free-model:free", "reason": "empty_response"},
                {"model": cloud_runtime.OPENROUTER_VALIDATED_FREE_MODEL, "reason": "empty_response"},
            ],
        )

    def test_openrouter_exact_model_retries_one_empty_response_without_fallback(
        self,
    ) -> None:
        empty = _FakeProviderResponse(
            {"choices": [{"message": {"content": ""}}]}
        )
        ok = _FakeProviderResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"mode":"inspect","domain":"orders"}'
                            )
                        }
                    }
                ]
            }
        )

        with patch.object(
            cloud_runtime.requests,
            "post",
            side_effect=[empty, ok],
        ) as post_mock:
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": (
                        "nvidia/nemotron-3-ultra-550b-a55b:free"
                    ),
                    "allow_model_fallback": False,
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            answer = client.invoke_json_text(
                "Typed JSON dondur",
                schema={"type": "object"},
            )

        self.assertIn('"mode":"inspect"', answer)
        models = [
            call.kwargs["json"]["model"]
            for call in post_mock.call_args_list
        ]
        self.assertEqual(
            models,
            [
                "nvidia/nemotron-3-ultra-550b-a55b:free",
                "nvidia/nemotron-3-ultra-550b-a55b:free",
            ],
        )
        plan = getattr(client, "resource_plan", {}) or {}
        self.assertEqual(
            plan.get("actual_model"),
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        self.assertFalse(plan.get("fallback_used"))
        self.assertEqual(
            plan.get("same_model_empty_retries"),
            [
                {
                    "model": (
                        "nvidia/nemotron-3-ultra-550b-a55b:free"
                    ),
                    "reason": "empty_response",
                    "attempt": 1,
                    "invocation_contract": "json_text_guarded",
                    "prompt_sha256": hashlib.sha256(
                        post_mock.call_args_list[0].kwargs["json"]["messages"][0]["content"].encode("utf-8")
                    ).hexdigest(),
                }
            ],
        )

    def test_openrouter_client_raises_when_every_fallback_returns_empty_content(self) -> None:
        empty_responses = [
            _FakeProviderResponse({"choices": [{"message": {"content": "  "}}]})
            for _candidate in (
                "weak-free-model:free",
                *cloud_runtime.OPENROUTER_FALLBACK_MODELS,
            )
        ]
        with patch.object(cloud_runtime.requests, "post", side_effect=empty_responses):
            client = cloud_runtime.build_provider_chat_client(
                {
                    "provider_code": "openrouter",
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-test",
                    "default_model": "weak-free-model:free",
                    "is_enabled": True,
                }
            )
            self.assertIsNotNone(client)
            with self.assertRaisesRegex(RuntimeError, "bos cevap"):
                client("Merhaba")

    def test_llama_cpp_server_client_uses_bundled_runtime_and_resource_plan(self) -> None:
        snapshot = ResourceSnapshot(
            total_ram_bytes=32 * GIB,
            available_ram_bytes=20 * GIB,
            cpu_count=12,
            disk_free_bytes=80 * GIB,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "Gemma-4-E4B-it-Q4_K_M.gguf"
            model_path.write_bytes(b"fake")
            plan = build_local_resource_plan(
                {"repo_id": "jc-builds/Gemma-4-E4B-it-GGUF", "local_path": str(model_path)},
                model_hint=str(model_path),
                snapshot=snapshot,
            )

            class _Server:
                key = "test-server-key"
                base_url = "http://127.0.0.1:39111"

            def fake_start_server(*, executable, model_path, plan, startup_timeout=0):
                self.assertGreaterEqual(startup_timeout, getattr(plan, "startup_timeout_seconds", 45))
                return _Server()

            def fake_builder(*, base_url, api_key, model, timeout=0, extra_headers=None, request_options=None):
                self.assertEqual(base_url, "http://127.0.0.1:39111/v1")
                self.assertEqual(model, model_path.name)
                self.assertGreaterEqual((request_options or {}).get("max_tokens"), 128)

                def _client(_prompt: str) -> str:
                    return '{"mode":"tool","tool":"orders.summary","arguments":{"period":"today"}}'

                return _client

            with patch("AI.processors.local_runtime.find_bundled_llama_server", return_value=str(Path(tmp_dir) / "llama-server.exe")), patch(
                "AI.processors.local_runtime.build_local_resource_plan",
                return_value=plan,
            ), patch(
                "AI.processors.local_runtime._start_managed_llama_server",
                side_effect=fake_start_server,
            ), patch(
                "AI.processors.local_runtime.build_openai_compatible_client",
                side_effect=fake_builder,
            ):
                planner = local_runtime.build_local_planner_client(
                    {"repo_id": "jc-builds/Gemma-4-E4B-it-GGUF", "local_path": str(model_path)},
                )

            self.assertIsNotNone(planner)
            self.assertEqual(planner("prompt"), '{"mode":"tool","tool":"orders.summary","arguments":{"period":"today"}}')
            self.assertEqual(getattr(planner, "runtime_name", ""), "llama_cpp_server")
            self.assertEqual(getattr(planner, "model_name", ""), str(model_path))

    def test_local_prompt_compaction_keeps_instructions_and_latest_tail_in_context(self) -> None:
        prompt = (
            "SYSTEM-KURALLARI\n"
            "<history>"
            + json.dumps(
                [
                    {"role": "user", "content": f"eski-{index}-" + ("x" * 800)}
                    for index in range(30)
                ],
                ensure_ascii=False,
            )
            + "</history>\n"
            "<user>GUNCEL-ISTEK</user>\n"
            "<tool>GUNCEL-ARAC-SONUCU</tool>"
        )

        compacted, metadata = local_runtime._compact_local_prompt(
            prompt,
            num_ctx=4096,
            max_tokens=384,
        )

        self.assertTrue(metadata.get("prompt_compacted"))
        self.assertLessEqual(len(compacted), metadata.get("prompt_max_input_chars"))
        self.assertIn("SYSTEM-KURALLARI", compacted)
        self.assertIn("GUNCEL-ISTEK", compacted)
        self.assertIn("GUNCEL-ARAC-SONUCU", compacted)
        self.assertIn("eski-29", compacted)
        self.assertNotIn("eski-0-", compacted)

    def test_agent_tool_registry_exposes_only_local_read_tools(self) -> None:
        registry = available_tools()

        self.assertIn("orders.summary", registry)
        self.assertIn("returns.summary", registry)
        self.assertIn("finance.profit_estimate", registry)
        self.assertIn("finance.cashflow_summary", registry)
        self.assertIn("orders.ready_to_ship", registry)
        self.assertIn("orders.fulfillment_risk", registry)
        self.assertIn("stock.low_stock", registry)
        self.assertIn("stock.inventory_overview", registry)
        self.assertIn("listing.summary", registry)
        self.assertIn("listing.attention", registry)
        self.assertIn("marketplaces.summary", registry)
        self.assertIn("accounts.health", registry)
        self.assertIn("logistics.profile", registry)
        for name, tool in registry.items():
            self.assertTrue(tool.read_only)
            self.assertFalse(tool.destructive)
            if getattr(tool, "action_type", "") == "prepare_write":
                continue
            lowered = f"{name} {tool.description} {getattr(tool.handler, '__name__', '')}".casefold()
            self.assertNotIn("fetch", lowered)
            self.assertNotIn("api", lowered)
            self.assertNotIn("delete", lowered)
            self.assertNotIn("update_price", lowered)
            self.assertNotIn("write", lowered)


if __name__ == "__main__":
    unittest.main()
