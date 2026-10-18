from __future__ import annotations

import hashlib
import json
import io
import os
import re
import tempfile
import unicodedata
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

from sqlmodel import Session

from AI.processors.cloud_runtime import build_provider_chat_client
from AI.processors.local_runtime import build_local_planner_client, shutdown_managed_llama_servers
from AI.processors.agent import run_agent_turn
from AI.processors import (
    architecture_boundary,
    operation_runtime,
    orders_goal_closure_cli,
    orders_live_long_conversation_recheck_cli,
    orders_live_lookup_recheck_cli,
    orders_live_returns_recheck_cli,
    orders_live_source_recheck_cli,
    orders_source_ui_human_recheck_cli,
    staging_marketplace_evidence_cli,
)
from AI.processors.live_evidence import redact_live_evidence, write_live_evidence_file
from AI.processors.pipeline import get_provider_account, list_installed_models, list_provider_accounts, list_provider_models
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from Orders.constants import TZ_GMT3
from Orders.models.trendyol.models import OrderData, OrderHeader, ReturnClaim
from tests.support.db_case import IsolatedDbTestCase


class TestSourceUiAcceptanceArtifact(unittest.TestCase):
    def test_capture_preserves_direct_canonical_tool_evidence(self) -> None:
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "Siparişlerde neler yapabilirsin?"},
                {"role": "assistant", "content": "Canonical yetenek özeti."},
            ],
            _agent_state={"status": "running", "pending_action": None},
            _superseded_actions=[],
            transcript=SimpleNamespace(toPlainText=lambda: "Canonical yetenek özeti."),
        )
        result = Result.ok(
            "Canonical yetenek özeti.",
            close_dialog=False,
            data={
                "answer": "Canonical yetenek özeti.",
                "decision_path": "typed_capability_catalog_grounded",
                "turn_interpretation": {
                    "mode": "explain",
                    "domain": "orders",
                    "intent_kind": "capability_overview",
                    "valid": True,
                },
                "direct_tool_calls": [
                    {
                        "tool": "operations.capability_catalog",
                        "arguments": {"domain": "orders"},
                    }
                ],
                "direct_tool_results": [
                    {
                        "tool": "operations.capability_catalog",
                        "success": True,
                        "data": {"domain": "orders"},
                    }
                ],
            },
        )

        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="Siparişlerde neler yapabilirsin?",
            review_previous={"assessment": "pass", "read_confirmed": True},
            capture={"turn_result": result},
            started_at="2026-07-27T13:00:00+00:00",
            completed_at="2026-07-27T13:00:01+00:00",
            duration_seconds=1.0,
        )

        self.assertEqual(
            [row.get("tool") for row in turn["tool_calls"]],
            ["operations.capability_catalog"],
        )
        self.assertEqual(
            [row.get("tool") for row in turn["direct_tool_results"]],
            ["operations.capability_catalog"],
        )
        self.assertEqual(
            turn["turn_interpretation"].get("intent_kind"),
            "capability_overview",
        )

    def test_capture_failed_turn_uses_current_error_not_previous_assistant_answer(self) -> None:
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "adin neydi"},
                {"role": "assistant", "content": "Ben OrderScout."},
                {"role": "user", "content": "e-ticaret insani yorar mi"},
            ],
            _agent_state={"status": "running", "pending_action": None},
            _superseded_actions=[],
            transcript=SimpleNamespace(
                toPlainText=lambda: (
                    "Ben OrderScout.\nSohbet modeli bos cevap dondurdu."
                )
            ),
        )
        result = Result.fail(
            "Sohbet modeli bos cevap dondurdu.",
            close_dialog=False,
            data={
                "runtime": {
                    "model_invoked": True,
                    "invocation_error_reason": "empty_response",
                    "resource_plan": {
                        "requested_model": "gemini-3.1-flash-lite",
                        "actual_model": "gemini-3.1-flash-lite",
                        "model_invocation_attempted": True,
                        "invocation_error_reason": "empty_response",
                        "same_model_retry_events": [
                            {
                                "model": "gemini-3.1-flash-lite",
                                "attempt": 1,
                                "reason": "empty_response",
                            }
                        ],
                        "request_prompt_hashes": [
                            {
                                "model": "gemini-3.1-flash-lite",
                                "prompt_sha256": "a" * 64,
                                "attempt": 1,
                            },
                            {
                                "model": "gemini-3.1-flash-lite",
                                "prompt_sha256": "a" * 64,
                                "attempt": 2,
                            },
                        ],
                    },
                }
            },
        )

        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="e-ticaret insani yorar mi",
            review_previous={"assessment": "pass", "read_confirmed": True},
            capture={"turn_result": result},
            started_at="2026-07-28T11:35:31+00:00",
            completed_at="2026-07-28T11:35:32+00:00",
            duration_seconds=1.0,
        )

        self.assertFalse(turn["success"])
        self.assertEqual(turn["turn_outcome"], "failed")
        self.assertEqual(turn["answer"], "Sohbet modeli bos cevap dondurdu.")
        self.assertEqual(
            turn["runtime"]["same_model_retry_events"],
            [
                {
                    "model": "gemini-3.1-flash-lite",
                    "attempt": 1,
                    "reason": "empty_response",
                }
            ],
        )
        self.assertEqual(
            [row["attempt"] for row in turn["runtime"]["request_prompt_hashes"]],
            [1, 2],
        )

    def test_timeout_turn_is_explicit_and_never_reuses_stale_assistant_answer(self) -> None:
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "önceki soru"},
                {"role": "assistant", "content": "Önceki başarılı cevabım."},
                {"role": "user", "content": "güncel siparişleri getir"},
            ],
            transcript=SimpleNamespace(
                toPlainText=lambda: "Önceki başarılı cevabım.\nİstek analiz ediliyor."
            ),
        )

        turn = orders_source_ui_human_recheck_cli._capture_timeout_turn(
            tab,
            prompt="güncel siparişleri getir",
            review_previous={"assessment": "pass", "read_confirmed": True},
            requested_model="gemma-4-31b-it",
            provider_code="gemini",
            started_at="2026-07-28T12:00:00+00:00",
            completed_at="2026-07-28T12:05:00+00:00",
            duration_seconds=300.0,
            timeout_seconds=300.0,
        )

        self.assertEqual(turn["turn"], 2)
        self.assertFalse(turn["success"])
        self.assertEqual(turn["turn_outcome"], "source_ui_timeout")
        self.assertNotEqual(turn["answer"], "Önceki başarılı cevabım.")
        self.assertFalse(turn["runtime"]["accepted_semantic_output"])
        self.assertIsNone(turn["runtime"]["model_invoked"])
        self.assertEqual(
            turn["runtime"]["model_observation_state"],
            "unknown_due_to_timeout",
        )
        self.assertEqual(turn["execute"]["success"], None)
        self.assertFalse(turn["response_synthesis"]["final_projection_verified"])

    def test_timeout_closes_acceptance_artifact_as_failed_and_requires_restart(self) -> None:
        artifact = {
            "artifact_type": "real_source_ui_human_directed",
            "evidence_contract_version": 6,
            "fallback_allowed": False,
            "final_status": "open",
            "turns": [],
        }
        turn = {
            "turn": 1,
            "success": False,
            "turn_outcome": "source_ui_timeout",
            "answer": "Source UI turu zaman aşımına uğradı.",
            "selection_reason": "focused timeout contract",
        }

        orders_source_ui_human_recheck_cli._close_artifact_after_timeout(
            artifact,
            turn=turn,
            timeout_seconds=300.0,
            minimum_turns=22,
        )

        self.assertEqual(artifact["final_status"], "failed")
        self.assertEqual(artifact["terminal_reason"], "source_ui_turn_timeout")
        self.assertTrue(artifact["restart_required"])
        self.assertEqual(artifact["turns"], [turn])
        self.assertFalse(artifact["acceptance_validation"]["accepted"])
        self.assertIn(
            "source_ui_turn_timeout",
            artifact["acceptance_validation"]["problems"],
        )

    def test_capture_treats_effects_free_stale_action_rejection_as_expected_control_outcome(self) -> None:
        active_id = "2b690dec6d4edbc98264ae27fb642da7"
        stale_id = "0a461f4c7c6adef0369cfa633fb955a7"
        pending = {
            "action_id": active_id,
            "status": "pending_approval",
            "action_type": "labels.action_create_labels_from_selected_orders",
        }
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": f"eski action_id {stale_id} onayla"},
                {
                    "role": "assistant",
                    "content": "Eski action_id reddedildi; hiçbir işlem çalıştırılmadı.",
                },
            ],
            _agent_state={"status": "approval_required", "pending_action": pending},
            _superseded_actions=[
                {"action_id": stale_id, "status": "superseded"}
            ],
            transcript=SimpleNamespace(
                toPlainText=lambda: "Eski action_id reddedildi; hiçbir işlem çalıştırılmadı."
            ),
        )
        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt=f"eski action_id {stale_id} onayla",
            review_previous={"assessment": "pass", "read_confirmed": True},
            capture={
                "execute_result": Result.fail(
                    "Eski action_id reddedildi; işlem çalıştırılmadı.",
                    close_dialog=False,
                    data={
                        "stale_approval": True,
                        "action_id": stale_id,
                        "active_pending_action_id": active_id,
                    },
                )
            },
            started_at="2026-07-27T13:00:00+00:00",
            completed_at="2026-07-27T13:00:01+00:00",
            duration_seconds=1.0,
        )

        self.assertTrue(turn["success"])
        self.assertEqual(turn["turn_outcome"], "stale_action_rejected")
        self.assertFalse(turn["execute"]["success"])
        self.assertTrue(turn["execute"]["data"]["stale_approval"])
        self.assertEqual(turn["pending_action"]["action_id"], active_id)

    def test_source_ui_jsonl_driver_forces_utf8_on_all_pipe_boundaries(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []

        class _FakeStream:
            def __init__(self, name: str) -> None:
                self.name = name

            def reconfigure(self, **kwargs: str) -> None:
                calls.append((self.name, dict(kwargs)))

        with (
            patch.object(
                orders_source_ui_human_recheck_cli.sys,
                "stdin",
                _FakeStream("stdin"),
            ),
            patch.object(
                orders_source_ui_human_recheck_cli.sys,
                "stdout",
                _FakeStream("stdout"),
            ),
            patch.object(
                orders_source_ui_human_recheck_cli.sys,
                "stderr",
                _FakeStream("stderr"),
            ),
        ):
            orders_source_ui_human_recheck_cli._configure_interactive_utf8_stdio()

        self.assertEqual(
            calls,
            [
                ("stdin", {"encoding": "utf-8", "errors": "strict"}),
                (
                    "stdout",
                    {"encoding": "utf-8", "errors": "backslashreplace"},
                ),
                (
                    "stderr",
                    {"encoding": "utf-8", "errors": "backslashreplace"},
                ),
            ],
        )

    def test_source_ui_jsonl_driver_accepts_windows_utf8_bom(self) -> None:
        command = orders_source_ui_human_recheck_cli._parse_jsonl_command(
            '\ufeff{"action":"turn","prompt":"sipariş özeti"}'
        )

        self.assertEqual(command.get("action"), "turn")
        self.assertEqual(command.get("prompt"), "sipariş özeti")

    def test_r402_source_ui_writer_preserves_verified_public_product_url(self) -> None:
        public_url = (
            "https://www.n11.com/urun/super-guclu-cerceve-askisi-"
            "4-adet-120003880"
        )
        private_order = "12345678901"
        payload = {
            "order_number": private_order,
            "tool_result": {
                "tool": "web.open",
                "web_observation": {"url": public_url},
            },
            "answer": f"Kaynak: [{public_url}]({public_url})",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_path = Path(temp_dir) / "source-ui-public-url.json"
            orders_source_ui_human_recheck_cli._write_artifact(
                artifact_path,
                payload,
            )
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

        joined = json.dumps(artifact, ensure_ascii=False)
        self.assertEqual(
            artifact["tool_result"]["web_observation"]["url"],
            public_url,
        )
        self.assertIn(public_url, artifact["answer"])
        self.assertNotIn(private_order, joined)
        self.assertEqual(
            artifact["privacy_redaction"]["verified_public_urls_preserved"],
            1,
        )

    def test_source_ui_driver_resolves_live_model_metadata_for_real_ui_parity(self) -> None:
        account = SimpleNamespace(
            success=True,
            message="ok",
            data={
                "record": {
                    "endpoint_url": "https://openrouter.ai/api/v1",
                    "api_key": "secret-not-returned",
                }
            },
        )
        catalog = SimpleNamespace(
            success=True,
            message="ok",
            data={
                "records": [
                    {
                        "id": "nvidia/nemotron-3-super-120b-a12b:free",
                        "supported_parameters": ["tools", "tool_choice", "response_format"],
                    }
                ],
                "free_model_test_route": {
                    "model_ids": ["nvidia/nemotron-3-super-120b-a12b:free"]
                },
            },
        )
        with (
            patch("AI.processors.pipeline.get_provider_account", return_value=account),
            patch("AI.processors.pipeline.list_provider_models", return_value=catalog) as list_models,
        ):
            metadata, route = orders_source_ui_human_recheck_cli._resolve_provider_model_selection(
                provider_id=1,
                provider_code="openrouter",
                model="nvidia/nemotron-3-super-120b-a12b:free",
            )

        self.assertIn("tools", metadata["supported_parameters"])
        self.assertEqual(
            route["model_ids"],
            ["nvidia/nemotron-3-super-120b-a12b:free"],
        )
        list_models.assert_called_once_with(
            provider_code="openrouter",
            endpoint_url="https://openrouter.ai/api/v1",
            api_key="secret-not-returned",
            free_only=False,
            limit=500,
        )

    def test_capture_records_effective_provider_invocation_contract(self) -> None:
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "bekleyen siparis sayisi kac"},
                {"role": "assistant", "content": "8 siparis var."},
            ],
            _agent_state={},
            _superseded_actions=[],
            transcript=SimpleNamespace(toPlainText=lambda: "8 siparis var."),
        )
        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="bekleyen siparis sayisi kac",
            review_previous={},
            capture={
                "turn_result": SimpleNamespace(
                    success=True,
                    data={
                        "answer": "8 siparis var.",
                        "accepted_semantic_output": True,
                        "final_response_source": "verified_model_candidate",
                        "runtime": {
                            "source": "cloud",
                            "runtime_name": "gemini_chat",
                            "model_name": "gemini-3.1-flash-lite",
                            "model_invoked": True,
                            "resource_plan": {
                                "requested_model": "gemini-3.1-flash-lite",
                                "actual_model": "gemini-3.1-flash-lite",
                                "model_invocation_attempted": True,
                                "model_response_count": 2,
                                "any_model_response_received": True,
                                "final_model_response_received": True,
                                "last_successful_actual_model": "gemini-3.1-flash-lite",
                                "any_model_fallback_used": False,
                                "last_invocation_contract": "text",
                                "invocation_contract_history": [
                                    "native_tools",
                                    "text",
                                ],
                                "invocation_outcome_history": [
                                    {
                                        "contract": "native_tools",
                                        "requested_model": "gemini-3.1-flash-lite",
                                        "actual_model": "gemini-3.1-flash-lite",
                                        "response_received": True,
                                        "error_reason": "",
                                        "fallback_used": False,
                                    },
                                    {
                                        "contract": "text",
                                        "requested_model": "gemini-3.1-flash-lite",
                                        "actual_model": "gemini-3.1-flash-lite",
                                        "response_received": True,
                                        "error_reason": "",
                                        "fallback_used": False,
                                    },
                                ],
                                "degradation_mode": "native_tools",
                                "capability_profile": {
                                    "native_tool_calling_available": True,
                                    "native_tool_runtime_enabled": True,
                                    "structured_output_available": True,
                                    "structured_output_runtime_enabled": True,
                                },
                            },
                        },
                    },
                    message="",
                )
            },
            started_at="2026-07-17T00:00:00+00:00",
            completed_at="2026-07-17T00:00:01+00:00",
            duration_seconds=1.0,
        )

        runtime = turn["runtime"]
        self.assertEqual(runtime["last_invocation_contract"], "text")
        self.assertEqual(
            runtime["invocation_contract_history"],
            ["native_tools", "text"],
        )
        self.assertEqual(runtime["degradation_mode"], "native_tools")
        self.assertEqual(runtime["model_response_count"], 2)
        self.assertTrue(runtime["any_model_response_received"])
        self.assertTrue(runtime["final_model_response_received"])
        self.assertTrue(runtime["accepted_semantic_output"])
        self.assertEqual(
            [row["contract"] for row in runtime["invocation_outcome_history"]],
            ["native_tools", "text"],
        )
        self.assertTrue(
            runtime["capability_profile"]["native_tool_runtime_enabled"]
        )
        self.assertTrue(
            runtime["capability_profile"]["structured_output_runtime_enabled"]
        )

    def test_capture_accepts_model_authored_prepare_only_with_verified_projection(
        self,
    ) -> None:
        model = "nvidia/nemotron-3-ultra-550b-a55b:free"
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "TANEX 2610 hazırlığını oluştur"},
                {
                    "role": "assistant",
                    "content": "Onay gerekiyor: 11 sipariş hazırlandı.",
                },
            ],
            _agent_state={},
            _superseded_actions=[],
            transcript=SimpleNamespace(
                toPlainText=lambda: "Onay gerekiyor: 11 sipariş hazırlandı."
            ),
        )
        state = {
            "active_entities": {
                "task_plan": {
                    "source": "llm_direct",
                    "planner_invoked": True,
                    "llm_step_ids": ["step_1"],
                    "deterministic_business_steps_inserted": False,
                    "semantic_inserted_step_ids": [],
                    "step_specs": [
                        {
                            "id": "step_1",
                            "operation_id": "labels.create_from_orders.prepare",
                        }
                    ],
                },
                "response_synthesis": {
                    "final_projection_verified": True,
                    "final_source": "deterministic_verified_projection",
                },
            }
        }

        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="TANEX 2610 hazırlığını oluştur",
            review_previous={},
            capture={
                "turn_result": SimpleNamespace(
                    success=True,
                    data={
                        "answer": "Onay gerekiyor: 11 sipariş hazırlandı.",
                        "tool_call": {
                            "tool": "labels.create_from_orders.prepare"
                        },
                        "tool_calls": [
                            {
                                "tool": "labels.create_from_orders.prepare"
                            }
                        ],
                        "tool_result": {"state": state},
                        "runtime": {
                            "source": "cloud",
                            "runtime_name": "openrouter_chat",
                            "model_name": model,
                            "model_invoked": True,
                            "final_response_source": "deterministic_verified_projection",
                            "resource_plan": {
                                "requested_model": model,
                                "actual_model": model,
                                "model_invocation_attempted": True,
                                "invocation_contract_history": [
                                    "json_text_guarded"
                                ],
                                "invocation_outcome_history": [
                                    {
                                        "contract": "json_text_guarded",
                                        "requested_model": model,
                                        "actual_model": model,
                                        "response_received": True,
                                        "error_reason": "",
                                        "fallback_used": False,
                                    }
                                ],
                            },
                        },
                    },
                    message="",
                )
            },
            started_at="2026-07-27T00:00:00+00:00",
            completed_at="2026-07-27T00:00:01+00:00",
            duration_seconds=1.0,
        )

        self.assertTrue(turn["runtime"]["accepted_semantic_output"])
        self.assertEqual(
            turn["runtime"]["accepted_semantic_output_source"],
            "model_authored_verified_projection",
        )

    def test_capture_preserves_verified_non_business_fallback_provenance(
        self,
    ) -> None:
        model = "deepseek/deepseek-v4-flash"
        safe_answer = (
            "İyiyim başkan, hazırım. Sipariş tarafında nereden başlayalım?"
        )
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "Başkan selam, naber?"},
                {"role": "assistant", "content": safe_answer},
            ],
            _agent_state={},
            _superseded_actions=[],
            transcript=SimpleNamespace(toPlainText=lambda: safe_answer),
        )
        synthesis = {
            "model_invoked": True,
            "candidate_received": True,
            "candidate_accepted": False,
            "candidate_projection_reason_codes": [
                "unsupported_non_business_operational_state_claim"
            ],
            "final_projection_verified": True,
            "final_source": (
                "deterministic_verified_non_business_fallback"
            ),
        }
        result = Result.ok(
            safe_answer,
            close_dialog=False,
            data={
                "answer": safe_answer,
                "decision_path": "typed_model_non_business_turn",
                "response_synthesis": synthesis,
                "runtime": {
                    "source": "cloud",
                    "runtime_name": "openrouter_chat",
                    "model_name": model,
                    "model_invoked": True,
                    "final_model_response_received": True,
                    "resource_plan": {
                        "requested_model": model,
                        "actual_model": model,
                        "model_invocation_attempted": True,
                        "invocation_contract_history": ["text"],
                        "invocation_outcome_history": [
                            {
                                "contract": "text",
                                "requested_model": model,
                                "actual_model": model,
                                "response_received": True,
                                "error_reason": "",
                                "fallback_used": False,
                            }
                        ],
                    },
                },
            },
        )

        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="Başkan selam, naber?",
            review_previous={},
            capture={"turn_result": result},
            started_at="2026-08-12T00:00:00+00:00",
            completed_at="2026-08-12T00:00:01+00:00",
            duration_seconds=1.0,
        )

        self.assertEqual(turn["response_synthesis"], synthesis)
        self.assertTrue(turn["runtime"]["accepted_semantic_output"])
        self.assertEqual(
            turn["runtime"]["accepted_semantic_output_source"],
            "deterministic_verified_non_business_fallback",
        )
        self.assertEqual(
            turn["runtime"]["final_response_source"],
            "deterministic_verified_non_business_fallback",
        )

    def test_capture_treats_confirmed_zero_effect_cancel_as_successful_turn(self) -> None:
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "vazgeç, şimdilik çekme"},
                {
                    "role": "assistant",
                    "content": "Riskli islem iptal edildi. Gercek API istegi veya DB yazimi yapilmadi.",
                },
            ],
            _agent_state={},
            _superseded_actions=[],
            transcript=SimpleNamespace(toPlainText=lambda: "Riskli islem iptal edildi."),
        )
        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="vazgeç, şimdilik çekme",
            review_previous={},
            capture={
                "turn_result": SimpleNamespace(
                    success=False,
                    data={},
                    message="Riskli islem iptal edildi. Gercek API istegi veya DB yazimi yapilmadi.",
                )
            },
            started_at="2026-07-17T00:00:00+00:00",
            completed_at="2026-07-17T00:00:01+00:00",
            duration_seconds=1.0,
        )

        self.assertTrue(turn["success"])
        self.assertEqual(turn["turn_outcome"], "cancelled")

    def test_capture_marks_provider_unavailable_as_non_accepted_turn(self) -> None:
        answer = (
            "Seçili cloud model provider kota/rate-limit sınırına takıldı. "
            "Hiçbir business tool çalıştırılmadı."
        )
        tab = SimpleNamespace(
            _chat_history=[
                {"role": "user", "content": "kaç sipariş var bekleyen"},
                {"role": "assistant", "content": answer},
            ],
            _agent_state={
                "status": "provider_unavailable",
                "detail": answer,
                "tools": [],
                "pending_action": None,
                "action_history": [],
            },
            _superseded_actions=[],
            transcript=SimpleNamespace(toPlainText=lambda: answer),
        )

        turn = orders_source_ui_human_recheck_cli._capture_turn(
            tab,
            prompt="kaç sipariş var bekleyen",
            review_previous={},
            capture={
                "turn_result": SimpleNamespace(
                    success=True,
                    data={
                        "answer": answer,
                        "mode": "provider_unavailable",
                        "provider_unavailable": True,
                        "runtime": {
                            "source": "cloud",
                            "model_invoked": False,
                            "resource_plan": {
                                "requested_model": "gemini-3.5-flash",
                                "actual_model": "",
                                "model_invocation_attempted": True,
                                "invocation_error_reason": "http_429",
                            },
                        },
                    },
                    message=answer,
                )
            },
            started_at="2026-07-26T00:00:00+00:00",
            completed_at="2026-07-26T00:00:01+00:00",
            duration_seconds=1.0,
        )

        self.assertFalse(turn["success"])
        self.assertEqual(
            turn["turn_outcome"],
            "provider_unavailable",
        )
        self.assertEqual(
            turn["agent_state"].get("status"),
            "provider_unavailable",
        )
        self.assertEqual(turn["tool_calls"], [])

    def test_atomic_dry_boundary_rejects_direct_domain_model_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            thin_wrapper = root / "thin_wrapper.py"
            thin_wrapper.write_text(
                "from Orders.processors.trendyol.pipeline import get_latest_orders\n",
                encoding="utf-8",
            )
            duplicate_logic = root / "duplicate_logic.py"
            duplicate_logic.write_text(
                "from Orders.models.trendyol.models import OrderData\n",
                encoding="utf-8",
            )

            clean = architecture_boundary.audit_ai_domain_model_imports([thin_wrapper])
            invalid = architecture_boundary.audit_ai_domain_model_imports([duplicate_logic])

        self.assertTrue(clean.get("valid"))
        self.assertFalse(invalid.get("valid"))
        self.assertEqual(invalid.get("violation_count"), 1)
        self.assertEqual((invalid.get("violations") or [])[0].get("module"), "Orders.models.trendyol.models")

    def test_core_ai_runtime_has_no_direct_domain_model_imports(self) -> None:
        ai_root = Path(__file__).resolve().parents[2] / "AI"
        audit = architecture_boundary.audit_ai_domain_model_imports(
            [
                ai_root / "processors" / "tools.py",
                ai_root / "processors" / "operation_runtime.py",
            ]
        )

        self.assertTrue(audit.get("valid"), audit)
        self.assertEqual(audit.get("violation_count"), 0)

    def test_full_core_dry_architecture_audit_is_binding_and_green(self) -> None:
        root = Path(__file__).resolve().parents[2]

        audit = architecture_boundary.audit_core_dry_architecture(root)

        self.assertTrue(audit.get("valid"), audit)
        self.assertEqual(audit.get("violation_count"), 0)
        self.assertGreaterEqual(int(audit.get("product_python_file_count") or 0), 250)
        self.assertEqual(
            set(audit.get("agentic_repository_files") or []),
            {
                "Account/processors/agentic_repository.py",
                "Finance/processors/agentic_repository.py",
                "Listing/processors/agentic_repository.py",
                "Logistics/processors/agentic_repository.py",
                "Marketplaces/processors/agentic_repository.py",
                "Orders/processors/agentic_repository.py",
                "Stock/processors/agentic_repository.py",
            },
        )
        self.assertTrue(
            all(bool(row.get("valid")) for row in (audit.get("checks") or {}).values()),
            audit,
        )

    def test_core_dry_audit_rejects_copied_logic_and_ui_owned_provider_origin(self) -> None:
        copied = """\
def duplicated_business_rule(value):
    clean = str(value or '').strip()
    if not clean:
        return ''
    normalized = clean.casefold()
    return normalized
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for relative in (
                "Finance/processors/pipeline.py",
                "Stock/processors/pipeline.py",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(copied, encoding="utf-8")
            runtime = root / "AI/processors/cloud_runtime.py"
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.write_text(
                'BASE = "https://api.openai.com/v1"\n',
                encoding="utf-8",
            )
            dialog = root / "AI/views/dialog.py"
            dialog.parent.mkdir(parents=True, exist_ok=True)
            dialog.write_text(
                'BASE = "https://api.openai.com/v1"\n',
                encoding="utf-8",
            )

            duplicate_audit = architecture_boundary.audit_duplicate_public_implementations(root)
            endpoint_audit = architecture_boundary.audit_endpoint_catalog_ownership(root)

        self.assertFalse(duplicate_audit.get("valid"), duplicate_audit)
        self.assertEqual(duplicate_audit.get("duplicate_group_count"), 1)
        self.assertFalse(endpoint_audit.get("valid"), endpoint_audit)
        self.assertIn(
            "provider_api_origin_outside_catalog_owner",
            {row.get("reason") for row in endpoint_audit.get("violations") or []},
        )

    @staticmethod
    def _valid_payload() -> dict[str, Any]:
        turns: list[dict[str, Any]] = []
        for turn_number in range(1, 21):
            row: dict[str, Any] = {
                "turn": turn_number,
                "prompt": f"Insan tarafindan secilen istem {turn_number}",
                "answer": f"Onceki sonuc okunup degerlendirildikten sonra alinan cevap {turn_number}.",
                "success": True,
                "selection_reason": "Onceki cevaptaki sonucu derinlestirmek icin secildi.",
                "runtime": {
                    "model_invoked": turn_number == 1,
                    "actual_model": "gemini-2.5-flash",
                    "fallback_used": False,
                },
            }
            if turn_number > 1:
                row["review_previous"] = {
                    "turn": turn_number - 1,
                    "assessment": "pass",
                    "read_confirmed": True,
                    "review_seconds": 60.0,
                }
            turns.append(row)
        turns[9]["execute"] = {
            "success": True,
            "data": {
                "idempotent": False,
                "verify": {"verified": True},
            },
        }
        return {
            "artifact_type": "real_source_ui_human_directed",
            "evidence_contract_version": 3,
            "acceptance_run_id": "test-acceptance-run",
            "final_status": "passed",
            "fallback_allowed": False,
            "source_entrypoint": "desktop/main.py",
            "ui_mode": "full_source_app",
            "source_surface_constructed": True,
            "source_window_runtime_class": "Main_interface.views.views.MainInterface",
            "source_widget_runtime_class": "AI.views.chat_tab.AITab",
            "render_mode": "offscreen",
            "requested_model": "gemini-2.5-flash",
            "human_selects_each_next_prompt_after_reading_previous_turn": True,
            "fixed_prompt_list": False,
            "turns": turns,
            "final_review": {
                "turn": 20,
                "assessment": "pass",
                "read_confirmed": True,
                "review_seconds": 60.0,
            },
        }

    @staticmethod
    def _valid_v5_payload() -> dict[str, Any]:
        payload = TestSourceUiAcceptanceArtifact._valid_payload()
        payload.update(
            {
                "evidence_contract_version": 5,
                "runtime_source_fingerprint": "source-hash",
                "runtime_source_fingerprint_current": "source-hash",
                "runtime_source_files": [
                    {"path": "AI/processors/agent.py", "sha256": "abc"}
                ],
                "runtime_source_stale": False,
            }
        )
        payload["turns"] = payload["turns"][:4]
        payload["final_review"]["turn"] = 4
        for row in payload["turns"]:
            row.pop("execute", None)
            row["runtime"] = {
                "model_invoked": False,
                "model_invocation_attempted": False,
                "model_response_count": 0,
                "any_model_response_received": False,
                "final_model_response_received": False,
                "actual_model": "",
                "final_actual_model": "",
                "fallback_used": False,
                "any_model_fallback_used": False,
                "accepted_semantic_output": False,
                "invocation_contract_history": [],
                "invocation_outcome_history": [],
            }
        payload["turns"][0]["runtime"] = {
            "model_invoked": True,
            "model_invocation_attempted": True,
            "model_response_count": 2,
            "any_model_response_received": True,
            "final_model_response_received": True,
            "actual_model": "gemini-2.5-flash",
            "final_actual_model": "gemini-2.5-flash",
            "fallback_used": False,
            "any_model_fallback_used": False,
            "accepted_semantic_output": True,
            "final_response_source": "verified_model_candidate",
            "invocation_contract_history": ["structured_output", "text"],
            "invocation_outcome_history": [
                {
                    "contract": "structured_output",
                    "requested_model": "gemini-2.5-flash",
                    "actual_model": "gemini-2.5-flash",
                    "response_received": True,
                    "error_reason": "",
                    "fallback_used": False,
                },
                {
                    "contract": "text",
                    "requested_model": "gemini-2.5-flash",
                    "actual_model": "gemini-2.5-flash",
                    "response_received": True,
                    "error_reason": "",
                    "fallback_used": False,
                },
            ],
        }
        return payload

    def test_validator_accepts_independent_full_source_evidence(self) -> None:
        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            self._valid_payload()
        )

        self.assertEqual(problems, [])

    def test_v4_source_ui_evidence_rejects_process_started_before_runtime_edits(self) -> None:
        payload = self._valid_payload()
        payload.update(
            {
                "evidence_contract_version": 4,
                "runtime_source_fingerprint": "startup-hash",
                "runtime_source_fingerprint_current": "edited-hash",
                "runtime_source_files": [
                    {"path": "AI/processors/agent.py", "sha256": "abc"}
                ],
                "runtime_source_stale": True,
            }
        )

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload
        )

        self.assertIn("runtime_source_stale", problems)
        self.assertIn("runtime_source_changed", problems)

    def test_validator_accepts_task_runtime_nested_fresh_execute_evidence(self) -> None:
        payload = self._valid_payload()
        execute_data = payload["turns"][9]["execute"]["data"]
        execute_data["execute"] = {
            "idempotent": False,
            "verify": execute_data.pop("verify"),
        }
        execute_data.pop("idempotent")

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload
        )

        self.assertEqual(problems, [])

    def test_validator_allows_focused_read_only_regression_without_fresh_execute(self) -> None:
        payload = self._valid_payload()
        for turn in payload["turns"]:
            turn.pop("execute", None)

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload,
            require_fresh_execute=False,
        )

        self.assertEqual(problems, [])

    def test_validator_allows_explicit_four_turn_source_ui_regression_contract(self) -> None:
        payload = self._valid_payload()
        payload["turns"] = payload["turns"][:4]
        payload["final_review"]["turn"] = 4
        for turn in payload["turns"]:
            turn.pop("execute", None)

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload,
            require_fresh_execute=False,
            minimum_turns=4,
        )

        self.assertEqual(problems, [])

    def test_v5_validator_accepts_per_invocation_provenance_and_deterministic_turns(
        self,
    ) -> None:
        from AI.processors import acceptance_manifest

        payload = self._valid_v5_payload()
        source_problems = (
            orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
                payload,
                require_fresh_execute=False,
                minimum_turns=4,
            )
        )
        payload.update(
            {
                "acceptance_validation": {"accepted": True, "problems": []},
                "fresh_execute_required": False,
                "privacy_redaction": {
                    "version": 3,
                    "redacted": True,
                    "original_values_persisted": False,
                },
            }
        )
        manifest_problems = acceptance_manifest._validate_source_ui_regression(
            payload,
            {
                "minimum_turn_count": 4,
                "requested_model": "gemini-2.5-flash",
                "fresh_execute_required": False,
                "minimum_privacy_version": 3,
                "minimum_evidence_contract_version": 5,
            },
        )

        self.assertEqual(source_problems, [])
        self.assertEqual(manifest_problems, [])

    def test_v5_validator_does_not_treat_prior_model_plan_plus_final_429_as_model_output(
        self,
    ) -> None:
        payload = self._valid_v5_payload()
        runtime = payload["turns"][0]["runtime"]
        runtime.update(
            {
                "model_response_count": 1,
                "final_model_response_received": False,
                "final_actual_model": "",
                "accepted_semantic_output": False,
                "final_response_source": "deterministic_verified_projection",
                "invocation_error_reason": "http_429",
            }
        )
        runtime["invocation_outcome_history"][-1].update(
            {
                "actual_model": "",
                "response_received": False,
                "error_reason": "http_429",
            }
        )

        problems = (
            orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
                payload,
                require_fresh_execute=False,
                minimum_turns=4,
            )
        )

        self.assertIn("model_semantic_output_not_proven", problems)
        self.assertFalse(
            any(
                value.startswith("turn_model_provenance:")
                for value in problems
            ),
            problems,
        )

    def test_manifest_validator_requires_proven_native_tool_then_text_sequence(self) -> None:
        from AI.processors import acceptance_manifest

        payload = self._valid_payload()
        payload.update(
            {
                "acceptance_validation": {"accepted": True, "problems": []},
                "fresh_execute_required": False,
                "privacy_redaction": {
                    "version": 3,
                    "redacted": True,
                    "original_values_persisted": False,
                },
            }
        )
        payload["turns"][0]["runtime"]["invocation_contract_history"] = [
            "native_tools",
            "text",
        ]
        expected = {
            "minimum_turn_count": 20,
            "requested_model": "gemini-2.5-flash",
            "fresh_execute_required": False,
            "minimum_privacy_version": 3,
            "required_invocation_contract_sequence": ["native_tools", "text"],
        }

        accepted = acceptance_manifest._validate_source_ui_regression(payload, expected)
        payload["turns"][0]["runtime"]["invocation_contract_history"] = ["text"]
        rejected = acceptance_manifest._validate_source_ui_regression(payload, expected)

        self.assertNotIn("invocation_contract_sequence", accepted)
        self.assertIn("invocation_contract_sequence", rejected)

    def test_manifest_validator_enforces_source_ui_turn_and_no_execute_contracts(self) -> None:
        from AI.processors import acceptance_manifest

        payload = self._valid_payload()
        payload.update(
            {
                "acceptance_validation": {"accepted": True, "problems": []},
                "fresh_execute_required": False,
                "privacy_redaction": {
                    "version": 3,
                    "redacted": True,
                    "original_values_persisted": False,
                },
            }
        )
        payload["turns"][0]["tool_calls"] = [{"tool": "stock.item_count"}]
        payload["turns"][0]["answer"] = "8"
        payload["turns"][1]["tool_calls"] = [
            {"tool": "operations.manual_action.prepare"}
        ]
        payload["turns"][1]["approval_required"] = True
        payload["turns"][1]["pending_action"] = {"status": "pending_approval"}
        payload["turns"][2]["turn_outcome"] = "cancelled"
        payload["turns"][9]["execute"]["success"] = None
        expected = {
            "minimum_turn_count": 20,
            "requested_model": "gemini-2.5-flash",
            "fresh_execute_required": False,
            "minimum_privacy_version": 3,
            "required_tool_names": ["stock.item_count", "operations.manual_action.prepare"],
            "minimum_prepare_count": 1,
            "minimum_cancelled_turn_count": 1,
            "require_no_execute_success": True,
            "required_turn_contracts": [
                {
                    "turn": 1,
                    "exact_tools": ["stock.item_count"],
                    "answer_contains": ["8"],
                    "answer_excludes": ["wrong wrapper"],
                },
                {
                    "turn": 2,
                    "exact_tools": ["operations.manual_action.prepare"],
                    "approval_required": True,
                    "pending_action_status": "pending_approval",
                },
            ],
        }

        accepted = acceptance_manifest._validate_source_ui_regression(payload, expected)
        payload["turns"][0]["tool_calls"] = [{"tool": "stock.inventory_overview"}]
        payload["turns"][0]["answer"] = "8 wrong wrapper"
        rejected = acceptance_manifest._validate_source_ui_regression(payload, expected)

        self.assertEqual(accepted, [])
        self.assertIn("required_tool_coverage", rejected)
        self.assertIn("turn_contract:1:tools", rejected)
        self.assertIn("turn_contract:1:answer_excludes", rejected)

    def test_validator_rejects_widget_only_self_declared_and_stale_execute_evidence(self) -> None:
        payload = self._valid_payload()
        payload["source_entrypoint"] = "AI.views.chat_tab.AITab"
        payload["ui_mode"] = "offscreen_widget"
        payload["human_selects_each_next_prompt_after_reading_previous_turn"] = False
        payload["fixed_prompt_list"] = True
        payload["turns"][0]["runtime"]["model_invoked"] = False
        payload["turns"][1]["review_previous"]["review_seconds"] = 0.01
        payload["turns"][9]["execute"]["data"]["idempotent"] = True

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(payload)

        self.assertTrue(
            {
                "source_entrypoint",
                "ui_mode",
                "human_review",
                "adaptive_human_selection",
                "fixed_prompt_list",
                "model_not_proven_invoked",
                "exact_model_not_proven",
                "fresh_verified_execute",
            }.issubset(set(problems))
        )

    def test_validator_accepts_explicit_review_failure_followed_by_correction(self) -> None:
        payload = self._valid_payload()
        payload["turns"][1]["review_previous"].update(
            {
                "assessment": "fail",
                "correction_requested": True,
                "notes": "Ilk cevap scope'u kaybetti; bu tur dogrudan duzeltiyor.",
            }
        )

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(payload)

        self.assertEqual(problems, [])

    def test_validator_rejects_review_failure_without_correction(self) -> None:
        payload = self._valid_payload()
        payload["turns"][1]["review_previous"].update(
            {
                "assessment": "fail",
                "correction_requested": False,
            }
        )

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(payload)

        self.assertIn("human_review", problems)

    def test_semantic_validator_rejects_generic_twenty_turn_artifact(self) -> None:
        payload = self._valid_payload()

        real_problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload,
            semantic_contract="source_ui_real_conversation_reproduction",
        )
        analysis_problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload,
            semantic_contract="source_ui_full_history_analysis_reproduction",
        )

        self.assertIn("semantic_exact_21_order_selection", real_problems)
        self.assertIn("semantic_fresh_21_label_docx_execute_verify", real_problems)
        self.assertIn("semantic_complete_full_history_reason_denominator", analysis_problems)
        self.assertIn("semantic_post_analysis_advice_no_task", analysis_problems)

    def test_semantic_validator_accepts_exact_real_conversation_contract(self) -> None:
        payload = self._valid_payload()
        order_numbers = [f"ORD-SEM-{index:02d}" for index in range(1, 22)]
        payload["turns"][0].update(
            {
                "tool_call": {"tool": "orders.ready_to_ship"},
                "tool_result": {
                    "listed_count": 21,
                    "order_numbers": order_numbers,
                    "truncated": False,
                },
            }
        )
        payload["turns"][1].update(
            {
                "tool_call": {"tool": "labels.create_from_orders.prepare"},
                "tool_result": {
                    "selected_record_count": 21,
                    "count": 21,
                    "order_numbers": order_numbers,
                    "scope_invariant_valid": True,
                },
                "approval_required": True,
            }
        )
        payload["turns"][2]["review_previous"].update(
            {"assessment": "fail", "correction_requested": True}
        )
        payload["turns"][2]["superseded_actions"] = [{"reason": "scope_revised"}]
        payload["turns"][3]["execute"] = {
            "success": True,
            "data": {
                "idempotent": False,
                "capability": {"capability_id": "labels.action_create_labels_from_selected_orders"},
                "verify": {
                    "verified": True,
                    "verified_by": "payload_and_docx_content",
                    "order_numbers": order_numbers,
                    "output_path": "C:/tmp/labels.docx",
                },
            },
        }

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload,
            semantic_contract="source_ui_real_conversation_reproduction",
        )

        self.assertEqual(problems, [])

    def test_semantic_validator_accepts_full_history_analysis_contract(self) -> None:
        payload = self._valid_payload()
        order_numbers = [f"ORD-SEM-{index:02d}" for index in range(1, 22)]
        deadline = {
            "requested_count": 21,
            "matched_count": 21,
            "truncated": False,
            "order_numbers": order_numbers,
        }
        payload["turns"][0].update(
            {"tool_call": {"tool": "orders.shipping_deadline_analysis"}, "tool_result": deadline}
        )
        payload["turns"][1].update(
            {
                "tool_call": {"tool": "returns.query"},
                "tool_result": {"pagination": {"returned": 10}, "sort": "claim_date_desc"},
                "approval_required": False,
            }
        )
        reason_result = {
            "period": "all",
            "total_claims": 177,
            "reason_counting_rule": "one normalized reason per claim",
            "multi_reason_claims": 2,
            "claims_without_reason": 0,
        }
        for index in (2, 3, 4):
            payload["turns"][index].update(
                {"tool_call": {"tool": "returns.reason_summary"}, "tool_result": dict(reason_result)}
            )
        payload["turns"][3]["review_previous"].update(
            {"assessment": "fail", "correction_requested": True}
        )
        payload["turns"][5].update(
            {"tool_call": {"tool": "orders.shipping_deadline_analysis"}, "tool_result": dict(deadline)}
        )
        payload["turns"][6].update(
            {
                "prompt": "Bu tabloya gore tavsiye ver, islem yapma.",
                "tool_call": {},
                "approval_required": False,
            }
        )

        problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
            payload,
            semantic_contract="source_ui_full_history_analysis_reproduction",
        )

        self.assertEqual(problems, [])


def _live_eval_enabled() -> bool:
    return str(os.environ.get("ORDERSCOUT_LIVE_LLM_EVAL") or "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _direct_env_record() -> tuple[dict[str, Any] | None, str, list[str]]:
    record = {
        "provider_code": _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_PROVIDER")),
        "endpoint_url": _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_ENDPOINT")),
        "api_key": _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_API_KEY")),
        "default_model": _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_MODEL")),
        "is_enabled": True,
    }
    env_names = {
        "provider_code": "ORDERSCOUT_LIVE_LLM_PROVIDER",
        "api_key": "ORDERSCOUT_LIVE_LLM_API_KEY",
        "default_model": "ORDERSCOUT_LIVE_LLM_MODEL",
    }
    missing = [env_names[key] for key in ("provider_code", "api_key", "default_model") if not record.get(key)]
    if len(missing) == 3 and not record.get("endpoint_url"):
        return None, "", []
    return (record if not missing else None), "direct_env", missing


def _app_provider_record() -> tuple[dict[str, Any] | None, str]:
    if not _truthy_env("ORDERSCOUT_LIVE_LLM_USE_APP_PROVIDER"):
        return None, ""
    provider_id = _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_PROVIDER_ID"))
    provider_label = _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_PROVIDER_LABEL")).casefold()
    if provider_id:
        res = get_provider_account(int(provider_id))
        record = dict((res.data or {}).get("record") or {}) if res.success else {}
        return (record or None), f"app_provider_id:{provider_id}"

    res = list_provider_accounts()
    records = list((res.data or {}).get("records") or []) if res.success else []
    selected: dict[str, Any] | None = None
    for row in records:
        record = dict(row or {})
        if provider_label and provider_label not in _compact_text(record.get("label")).casefold():
            continue
        if not bool(record.get("is_enabled")) or not _compact_text(record.get("default_model")):
            continue
        selected = record
        break
    if not selected:
        return None, "app_provider"
    provider_pk = int(selected.get("id") or 0)
    res = get_provider_account(provider_pk)
    record = dict((res.data or {}).get("record") or {}) if res.success else {}
    return (record or None), f"app_provider:{selected.get('label') or provider_pk}"


def _app_provider_by_code(provider_code: str) -> tuple[dict[str, Any] | None, str]:
    clean_provider = _compact_text(provider_code).casefold()
    if not clean_provider:
        return None, ""
    res = list_provider_accounts()
    records = list((res.data or {}).get("records") or []) if res.success else []
    selected: dict[str, Any] | None = None
    for row in records:
        record = dict(row or {})
        if _compact_text(record.get("provider_code")).casefold() != clean_provider:
            continue
        if not bool(record.get("is_enabled")) or not _compact_text(record.get("default_model")):
            continue
        selected = record
        break
    if not selected:
        return None, f"app_provider:{clean_provider}"
    provider_pk = int(selected.get("id") or 0)
    res = get_provider_account(provider_pk)
    record = dict((res.data or {}).get("record") or {}) if res.success else {}
    return (record or None), f"app_provider:{selected.get('label') or provider_pk}"


def _live_provider_record() -> tuple[dict[str, Any], str]:
    def _with_model_override(record: dict[str, Any], source: str) -> tuple[dict[str, Any], str]:
        override = _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_MODEL_OVERRIDE"))
        if not override:
            return record, source
        updated = dict(record)
        updated["default_model"] = override
        return updated, f"{source};model_override"

    env_record, env_source, missing = _direct_env_record()
    if env_record is not None:
        return _with_model_override(env_record, env_source)
    app_record, app_source = _app_provider_record()
    if app_record is not None:
        return _with_model_override(app_record, app_source)
    instructions = (
        "Set ORDERSCOUT_LIVE_LLM_PROVIDER, ORDERSCOUT_LIVE_LLM_API_KEY, "
        "ORDERSCOUT_LIVE_LLM_MODEL; or set ORDERSCOUT_LIVE_LLM_USE_APP_PROVIDER=1 "
        "with optional ORDERSCOUT_LIVE_LLM_PROVIDER_ID / ORDERSCOUT_LIVE_LLM_PROVIDER_LABEL."
    )
    if missing:
        raise AssertionError("Live LLM eval enabled but direct env is incomplete: " + ", ".join(missing) + ". " + instructions)
    raise AssertionError("Live LLM eval enabled but no cloud provider credentials were available. " + instructions)


def _safe_provider_label(record: dict[str, Any], source: str) -> str:
    return (
        f"source={source}; provider={_compact_text(record.get('provider_code')) or 'unknown'}; "
        f"model={_compact_text(record.get('default_model')) or 'unknown'}"
    )


def _live_artifact_dir() -> Path | None:
    raw = _compact_text(os.environ.get("ORDERSCOUT_LIVE_LLM_ARTIFACT_DIR"))
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _artifact_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", _compact_text(value)).strip("-._")
    return slug[:90] or "live-llm"


def _write_live_artifact(
    name: str,
    *,
    provider_label: str,
    transcript: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> Path | None:
    directory = _live_artifact_dir()
    if directory is None:
        return None
    payload = {
        "name": name,
        "provider": provider_label,
        "turn_count": len(transcript),
        "transcript": transcript,
        "extra": dict(extra or {}),
    }
    path = directory / f"{_artifact_slug(name)}.json"
    return write_live_evidence_file(path, payload)


class TestLiveEvalArtifactHelpers(unittest.TestCase):
    _REMOVED_HISTORICAL_FIXTURE_TESTS = {
        "test_completion_audit_references_current_live_evidence_and_open_gaps",
        "test_goals_contract_maps_to_orders_closure_scope_and_evidence",
        "test_current_free_model_catalog_and_long_human_artifacts_are_complete",
        "test_goal_closure_checklist_is_ready_after_real_source_ui_resolution",
        "test_goal_closure_cli_accepts_resolved_real_source_ui_regression",
        "test_staging_marketplace_runbook_requires_full_external_proof_match",
        "test_source_ui_marketplace_catalog_smoke_proves_current_app_chat",
        "test_source_ui_logistics_window_smoke_uses_current_main_py_not_packaged_exe",
        "test_persisted_chat_tab_ui_smoke_proves_visible_approval_execute_flow",
        "test_persisted_source_main_window_smoke_uses_current_code_not_packaged_exe",
        "test_labels_agentic_parity_matrix_covers_word_export_workflow",
        "test_stock_agentic_parity_matrix_covers_manual_surface_and_open_gaps",
        "test_finance_agentic_parity_matrix_covers_manual_surface_and_open_gaps",
        "test_logistics_agentic_parity_matrix_covers_manual_surface_and_open_gaps",
        "test_listing_agentic_parity_matrix_covers_manual_surface_and_open_gaps",
        "test_marketplaces_agentic_parity_matrix_covers_manual_surface_and_open_gaps",
    }

    def setUp(self) -> None:
        method_name = self._testMethodName
        uses_removed_fixture = (
            method_name.startswith("test_persisted_")
            or "_artifact_proves_" in method_name
            or method_name in self._REMOVED_HISTORICAL_FIXTURE_TESTS
        )
        if uses_removed_fixture:
            self.skipTest(
                "Historical live transcript fixture was intentionally removed during the "
                "user-requested workspace cleanup. Current SHA-verified evidence is covered "
                "by test_orders_goal_closure_latest_regression.py."
            )

    def _artifact_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/gemini-app-provider"

    def _openrouter_orders_artifact_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/openrouter-orders"

    def _openrouter_task_runtime_artifact_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/openrouter-task-runtime"

    def _local_best_artifact_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/local-best"

    def _gemini_web_artifact_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/gemini-web"

    def _source_db_recheck_artifact_root(self) -> Path:
        return Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts/source-db-live-recheck"

    def test_live_evidence_preserves_opaque_digest_fields_without_weakening_text_redaction(self) -> None:
        digest = "edfd0048a3cc92501ddbaa6dac3ed901de44f05550000000b3de2bf796b632f854"
        payload = {
            "prompt_sha256": digest,
            "session_state_hash": digest[:32],
            "history_state_hash_after_turn": digest[:32],
            "answer": "Telefon: 05550000000",
        }

        redacted, metadata = redact_live_evidence(payload)

        self.assertEqual(redacted["prompt_sha256"], digest)
        self.assertEqual(redacted["session_state_hash"], digest[:32])
        self.assertEqual(redacted["history_state_hash_after_turn"], digest[:32])
        self.assertNotIn("05550000000", redacted["answer"])
        self.assertTrue(metadata["redacted"])

    def test_live_evidence_customer_seed_redacts_unlabelled_answer_names(self) -> None:
        payload = {
            "return_seed": {"customer_names": ["Example Customer"]},
            "answer": "Example\u202fCustomer'a ait iade onay bekliyor.",
        }

        redacted, metadata = redact_live_evidence(payload)

        self.assertNotIn("Example Customer", json.dumps(redacted))
        self.assertEqual(
            redacted["return_seed"]["customer_names"],
            ["<customer-001>"],
        )
        self.assertIn("<customer-001>'a ait", redacted["answer"])
        self.assertTrue(metadata["redacted"])

    def test_live_evidence_preserves_verified_public_product_urls_without_leaking_private_ids(self) -> None:
        public_url = (
            "https://www.n11.com/urun/super-guclu-cerceve-askisi-"
            "4-adet-120003880"
        )
        private_order = "12345678901"
        payload = {
            "order_seed": {"order_number": private_order},
            "tool_result": {
                "tool": "web.open",
                "web_observation": {
                    "url": public_url,
                    "requested_url": public_url,
                },
            },
            "answer": (
                f"Kaynak: [{public_url}]({public_url}). "
                f"Özel sipariş: {private_order}."
            ),
        }

        redacted, metadata = redact_live_evidence(payload)
        joined = json.dumps(redacted, ensure_ascii=False)

        self.assertEqual(
            redacted["tool_result"]["web_observation"]["url"],
            public_url,
        )
        self.assertEqual(redacted["order_seed"]["order_number"], "<order-001>")
        self.assertIn(public_url, redacted["answer"])
        self.assertNotIn(private_order, joined)
        self.assertNotIn("order_partial", redacted["answer"])
        self.assertEqual(metadata["version"], 4)
        self.assertEqual(metadata["verified_public_urls_preserved"], 1)

    def test_live_evidence_does_not_preserve_secret_or_private_query_urls(self) -> None:
        private_order = "12345678901"
        payload = {
            "order_number": private_order,
            "url": f"https://example.com/search?token=secret&order={private_order}",
        }

        redacted, metadata = redact_live_evidence(payload)
        joined = json.dumps(redacted, ensure_ascii=False)

        self.assertNotIn(private_order, joined)
        self.assertNotIn("secret", joined)
        self.assertEqual(metadata["verified_public_urls_preserved"], 0)

    def test_live_evidence_redacts_stage_opaque_identifiers_by_schema_key(self) -> None:
        payload = {
            "order_seed": {
                "order_number": "987654321",
                "tracking_number": "STAGE-TRACK-ABC",
            },
            "return_seed": {"target_claim_id": "246813579"},
            "answer": (
                "Siparis 987654321, takip STAGE-TRACK-ABC ve claim 246813579 hazir."
            ),
        }

        redacted, metadata = redact_live_evidence(payload)
        joined = json.dumps(redacted, ensure_ascii=False)

        self.assertNotIn("987654321", joined)
        self.assertNotIn("STAGE-TRACK-ABC", joined)
        self.assertNotIn("246813579", joined)
        self.assertEqual(redacted["order_seed"]["order_number"], "<order-001>")
        self.assertEqual(redacted["order_seed"]["tracking_number"], "<tracking-001>")
        self.assertEqual(redacted["return_seed"]["target_claim_id"], "<claim-001>")
        self.assertEqual(metadata["alias_counts"], {"claim": 1, "order": 1, "tracking": 1})

    def test_live_evidence_redacts_opaque_identifiers_used_as_mapping_keys(self) -> None:
        payload = {
            "conversation_context": {
                "account_by_order": {
                    "<order-001>": "2",
                    "987654321": "2",
                    "STAGE-ORDER-OPAQUE": "2",
                },
                "account_by_claim": {"246813579": "2"},
            },
            "verification": {
                "db_cargo_provider_by_order": {
                    "987654321": "Aras Kargo",
                }
            },
        }

        redacted, metadata = redact_live_evidence(payload)
        joined = json.dumps(redacted, ensure_ascii=False)

        self.assertNotIn("987654321", joined)
        self.assertNotIn("STAGE-ORDER-OPAQUE", joined)
        self.assertNotIn("246813579", joined)
        account_by_order = redacted["conversation_context"]["account_by_order"]
        self.assertEqual(
            set(account_by_order),
            {"<order-001>", "<order-002>", "<order-003>"},
        )
        self.assertEqual(
            set(redacted["conversation_context"]["account_by_claim"]),
            {"<claim-001>"},
        )
        self.assertEqual(
            set(redacted["verification"]["db_cargo_provider_by_order"]),
            {"<order-002>"},
        )
        self.assertEqual(metadata["version"], 4)

    def test_live_evidence_keeps_generic_customer_label_and_prefers_claim_alias(self) -> None:
        payload = {
            "customer_name": "Müşteri",
            "buyer_name": "Example Buyer",
            "order_number": "246813579",
            "target_claim_id": "246813579",
            "answer": "Müşteri: Müşteri | Example Buyer | claim 246813579",
        }

        redacted, metadata = redact_live_evidence(payload)
        joined = json.dumps(redacted, ensure_ascii=False)

        self.assertEqual(redacted["customer_name"], "Müşteri")
        self.assertEqual(redacted["buyer_name"], "<customer-001>")
        self.assertNotIn("Example Buyer", joined)
        self.assertEqual(redacted["order_number"], "<claim-001>")
        self.assertEqual(redacted["target_claim_id"], "<claim-001>")
        self.assertIn("claim <claim-001>", redacted["answer"])
        self.assertEqual(metadata["alias_counts"].get("claim"), 1)
        self.assertNotIn("order", metadata["alias_counts"])

    def test_visible_answer_quality_rejects_replacement_character(self) -> None:
        self.assertTrue(
            orders_live_source_recheck_cli._visible_answer_has_mojibake(
                "Cevapta bozuk � karakter var."
            )
        )

    def test_long_campaign_uses_exact_order_when_customer_is_duplicated(self) -> None:
        prompt, reason = orders_live_long_conversation_recheck_cli._adaptive_prompt(
            "long_range_context_return",
            turns=[],
            order_seed={
                "order_number": "STAGE-ORDER-199",
                "customer_name": "Müşteri",
                "customer_is_unique_in_recent": False,
            },
            return_seed=None,
        )

        self.assertIn("STAGE-ORDER-199", prompt)
        self.assertNotIn("Müşteri icin", prompt)
        self.assertIn("exact authoritative order number", reason)

    def test_source_db_recheck_history_keeps_structured_order_scope(self) -> None:
        history: list[dict[str, Any]] = []
        orders_live_source_recheck_cli._append_history(
            history,
            user_message="listele",
            answer="22 siparis listelendi.",
            conversation_context={
                "kind": "order_selection",
                "order_numbers": [f"ORD-SCOPE-{index:02d}" for index in range(1, 23)],
                "total_count": 22,
            },
        )

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": "listele"})
        self.assertEqual(
            len((history[1].get("context") or {}).get("order_numbers") or []),
            22,
        )

    def test_source_db_recheck_checks_exact_prepare_scope_and_preview_remainder(self) -> None:
        order_numbers = [f"ORD-SCOPE-{index:02d}" for index in range(1, 23)]
        turns = [
            {
                "success": True,
                "tools": [
                    "orders.count",
                    "orders.revenue_total",
                    "finance.profit_amount",
                    "returns.count",
                    "returns.amount_total",
                    "orders.ready_to_ship_count",
                ],
                "answer": (
                    "Siparis analizi. " * 20
                    + " Kar hesaplanamiyor; maliyet verisi eksik."
                ),
                "profit_evidence": {
                    "amount": None,
                    "estimated_profit_ready": False,
                    "incomplete_order_count": 22,
                },
            },
            {
                "success": True,
                "tools": [
                    "orders.count",
                    "orders.revenue_total",
                    "orders.count",
                    "orders.revenue_total",
                ],
                "answer": (
                    "Onceki es donem ile karsilastirdim; "
                    "bu donem siparis adedi geride."
                ),
            },
            {
                "success": True,
                "tools": ["orders.ready_to_ship_count"],
                "answer": "Kargoya hazir 22 siparis var.",
                "conversation_context": {"total_count": 22},
            },
            {
                "success": True,
                "tools": ["orders.ready_to_ship"],
                "answer": (
                    "Lokal kayda gore 22 siparis buldum. "
                    "... 2 kayit daha var."
                ),
                "conversation_context": {"order_numbers": order_numbers},
            },
            {
                "success": True,
                "tools": ["labels.create_from_orders.prepare"],
                "answer": (
                    "Onay gerekiyor: 22 siparis icin etiket olusturma "
                    "hazirlaniyor. Gercek API istegi veya DB yazimi yapilmadi. "
                    "... 2 kayit daha onay kapsaminda."
                ),
                "approval_required": True,
                "action_execute_enabled": True,
                "prepared_order_numbers": order_numbers,
            },
        ]

        checks = orders_live_source_recheck_cli._provider_checks(
            turns,
            first_answer_grounded=True,
        )

        self.assertTrue(all(checks.values()), checks)

    def test_source_db_recheck_rejects_visible_scope_and_encoding_failures(self) -> None:
        order_numbers = [f"ORD-SCOPE-{index:02d}" for index in range(1, 23)]
        turns = [
            {
                "success": True,
                "tools": [
                    "orders.count",
                    "orders.revenue_total",
                    "finance.profit_amount",
                    "returns.count",
                    "returns.amount_total",
                    "orders.ready_to_ship_count",
                ],
                "answer": (
                    "Siparis analizi. " * 20
                    + " Kar hesaplanamiyor; maliyet verisi eksik."
                ),
                "profit_evidence": {
                    "amount": None,
                    "estimated_profit_ready": False,
                    "incomplete_order_count": 22,
                },
            },
            {
                "success": True,
                "tools": [
                    "orders.count",
                    "orders.revenue_total",
                    "orders.count",
                    "orders.revenue_total",
                ],
                "answer": "Bu ay iyi gidiyor.",
            },
            {
                "success": True,
                "tools": ["orders.ready_to_ship_count"],
                "answer": "Kargoya hazir 4 siparis var.",
                "conversation_context": {"total_count": 22},
            },
            {
                "success": True,
                "tools": ["orders.ready_to_ship"],
                "answer": "Lokal kayda gÃ¶re 10 siparis buldum.",
                "conversation_context": {"order_numbers": order_numbers},
            },
            {
                "success": True,
                "tools": ["labels.create_from_orders.prepare"],
                "answer": "Onay gerekiyor: 0 siparis.",
                "approval_required": True,
                "action_execute_enabled": True,
                "prepared_order_numbers": order_numbers,
            },
        ]

        checks = orders_live_source_recheck_cli._provider_checks(
            turns,
            first_answer_grounded=True,
        )

        self.assertFalse(checks["all_visible_answers_no_mojibake"], checks)
        self.assertFalse(checks["equivalent_period_answer_is_explicit"], checks)
        self.assertFalse(checks["ready_count_answer_matches_context"], checks)
        self.assertFalse(checks["ready_list_answer_matches_context"], checks)
        self.assertFalse(checks["label_prepare_answer_matches_scope"], checks)

    def test_source_db_lookup_recheck_requires_exact_identity_across_followups(self) -> None:
        order_number = "11357933201"
        recent_numbers = [
            order_number,
            "11357818999",
            "11357811157",
            "11357789341",
            "11357348078",
        ]
        seed = {
            "order_number": order_number,
            "tracking_number": "7330033757995470",
            "customer_name": "Canli Musteri",
            "recent_order_numbers": recent_numbers,
            "last_8_days_ready_order_numbers": recent_numbers[:3],
        }
        turns = [
            {
                "success": True,
                "tools": ["orders.recent"],
                "answer": "Son 5 siparis getirildi.",
                "tool_order_numbers": recent_numbers,
            },
            {
                "success": True,
                "tools": ["orders.full_context"],
                "answer": f"Siparis {order_number} tam baglami hazir.",
                "tool_order_numbers": [order_number],
            },
            {
                "success": True,
                "tools": ["orders.lookup"],
                "answer": f"Siparis {order_number} bulundu.",
                "tool_order_numbers": [order_number],
            },
            {
                "success": True,
                "tools": ["orders.lookup"],
                "answer": f"Siparis {order_number} bulundu.",
                "tool_order_numbers": [order_number],
            },
            {
                "success": True,
                "tools": ["orders.full_context"],
                "answer": f"Siparis {order_number} yeniden ozetlendi.",
                "tool_order_numbers": [order_number],
            },
            {
                "success": True,
                "tools": ["orders.ready_to_ship"],
                "tool_arguments": [
                    {
                        "tool": "orders.ready_to_ship",
                        "arguments": {
                            "period": "last_8_days",
                            "limit": 100,
                        },
                    }
                ],
                "answer": "Son 8 gunde kargoya hazir 3 siparis listelendi.",
                "tool_order_numbers": recent_numbers[:3],
            },
        ]

        checks = orders_live_lookup_recheck_cli._provider_checks(
            turns,
            seed=seed,
        )
        self.assertTrue(all(checks.values()), checks)

        turns[4] = {
            **turns[4],
            "answer": "Iki siparis yeniden ozetlendi.",
            "tool_order_numbers": [order_number, "11357818999"],
        }
        checks = orders_live_lookup_recheck_cli._provider_checks(
            turns,
            seed=seed,
        )
        self.assertFalse(checks["pronoun_followup_keeps_exact_seed"], checks)
        self.assertFalse(checks["visible_exact_answers_name_target_order"], checks)

    def test_source_db_returns_recheck_requires_exact_prepare_scope(self) -> None:
        target_claim = "75a7c1c0-73a2-49f7-bb8a-366dee971405"
        other_claim = "85a7c1c0-73a2-49f7-bb8a-366dee971406"
        seed = {
            "target_claim_id": target_claim,
            "target_order_number": "11357933201",
            "waiting_claim_ids": [target_claim, other_claim],
            "waiting_count": 2,
        }
        turns = [
            {
                "success": True,
                "tools": ["returns.query"],
                "tool_arguments": [
                    {
                        "tool": "returns.query",
                        "arguments": {
                            "period": "all",
                            "filters": {"status": "WaitingInAction"},
                            "limit": 20,
                            "mode": "list",
                        },
                    }
                ],
                "answer": "Onay bekleyen 2 iade listelendi.",
                "tool_claim_ids": [target_claim, other_claim],
                "conversation_context": {
                    "kind": "return_selection",
                    "claim_ids": [target_claim, other_claim],
                },
            },
            {
                "success": True,
                "tools": ["returns.lookup"],
                "answer": f"{target_claim} iade detayi.",
                "tool_claim_ids": [target_claim],
                "conversation_context": {
                    "kind": "return_selection",
                    "claim_ids": [target_claim],
                },
            },
            {
                "success": True,
                "tools": ["returns.approve.prepare"],
                "answer": (
                    f"Onay gerekiyor: {target_claim} iadesi. "
                    "Gercek API istegi veya DB yazimi yapilmadi."
                ),
                "approval_required": True,
                "action_execute_enabled": True,
                "action_type": "orders.approve_return_claim",
                "prepared_claim_ids": [target_claim],
            },
        ]

        checks = orders_live_returns_recheck_cli._provider_checks(
            turns,
            seed=seed,
        )
        self.assertTrue(all(checks.values()), checks)

        turns[-1] = {
            **turns[-1],
            "prepared_claim_ids": [target_claim, other_claim],
        }
        checks = orders_live_returns_recheck_cli._provider_checks(
            turns,
            seed=seed,
        )
        self.assertFalse(
            checks["approval_prepare_uses_exact_context_claim"],
            checks,
        )

    def test_persisted_source_db_provider_recheck_proves_grounded_exact_scope(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-provider-conversation-recheck-2026-06-30.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_provider_conversation_recheck",
        )
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        for key in (
            "computer_use_used",
            "packaged_exe_used",
            "marketplace_write_performed",
            "db_write_performed",
            "execute_performed",
        ):
            self.assertFalse(safety.get(key), (key, safety))
        self.assertTrue(safety.get("last_step_stops_at_prepare"), safety)

        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            for check_name in (
                "all_visible_answers_present",
                "all_visible_answers_no_mojibake",
                "equivalent_period_answer_is_explicit",
                "ready_count_answer_matches_context",
                "ready_list_answer_matches_context",
                "label_prepare_answer_matches_scope",
            ):
                self.assertTrue(checks.get(check_name), (check_name, provider))
            turns = list(provider.get("turns") or [])
            self.assertEqual(len(turns), 5)
            for turn in turns:
                visible_quality = dict(turn.get("visible_answer_quality") or {})
                self.assertTrue(visible_quality.get("present"), turn)
                self.assertTrue(visible_quality.get("no_mojibake"), turn)
            profit = dict(turns[0].get("profit_evidence") or {})
            self.assertIsNone(profit.get("amount"))
            self.assertFalse(profit.get("estimated_profit_ready"))
            self.assertGreater(int(profit.get("incomplete_order_count") or 0), 0)
            analysis_answer = _compact_text(turns[0].get("answer")).casefold()
            self.assertIn("maliyet", analysis_answer)
            self.assertIn("karliyiz", analysis_answer)
            self.assertIn("diyemem", analysis_answer)
            equal_period_answer = _compact_text(turns[1].get("answer")).casefold()
            self.assertIn("onceki es donem", equal_period_answer)
            self.assertNotIn("bu ay", equal_period_answer)
            ready_count_answer = _compact_text(turns[2].get("answer")).casefold()
            self.assertIn("kargoya hazir 22 siparis", ready_count_answer)
            self.assertIn("simulasyon", ready_count_answer)

            listed = list(
                dict(turns[3].get("conversation_context") or {}).get(
                    "order_numbers"
                )
                or []
            )
            prepared = list(turns[4].get("prepared_order_numbers") or [])
            self.assertEqual(len(listed), 22)
            self.assertEqual(set(prepared), set(listed))
            list_answer = _compact_text(turns[3].get("answer"))
            self.assertIn("Lokal kayda gore 22 siparis buldum", list_answer)
            self.assertIn("... 2 kayit daha var", list_answer)
            self.assertEqual(len(re.findall(r"<order-\d{3}>", list_answer)), 20)
            self.assertTrue(turns[4].get("approval_required"))
            approval_answer = _compact_text(turns[4].get("answer"))
            self.assertIn("Onay gerekiyor: 22 siparis", approval_answer)
            self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", approval_answer)
            self.assertIn("2 kayit daha onay kapsaminda", approval_answer)
            self.assertNotIn("0 siparis", approval_answer.casefold())
            self.assertEqual(len(re.findall(r"<order-\d{3}>", approval_answer)), 20)

        transcript_text = json.dumps(
            [
                turn
                for provider in providers
                for turn in list(provider.get("turns") or [])
            ],
            ensure_ascii=False,
        )
        self.assertNotRegex(
            transcript_text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        self.assertNotRegex(
            transcript_text,
            r"(?<![A-Za-z0-9])7\d{15}(?![A-Za-z0-9])",
        )
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)

    def test_persisted_source_db_lookup_recheck_proves_exact_identity_chain(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-lookup-conversation-recheck-2026-06-30.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_lookup_conversation_recheck",
        )
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertTrue(safety.get("read_only_conversation"), safety)
        for key in (
            "computer_use_used",
            "packaged_exe_used",
            "marketplace_write_performed",
            "db_write_performed",
            "execute_performed",
        ):
            self.assertFalse(safety.get(key), (key, safety))

        seed = dict(payload.get("seed") or {})
        self.assertEqual(seed.get("order_number"), "<order-001>")
        self.assertEqual(seed.get("tracking_number"), "<tracking-001>")
        self.assertEqual(seed.get("customer_name"), "<customer-001>")
        self.assertEqual(len(seed.get("recent_order_numbers") or []), 5)
        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            turns = list(provider.get("turns") or [])
            self.assertEqual(len(turns), 6)
            self.assertEqual(
                turns[0].get("tool_order_numbers"),
                seed.get("recent_order_numbers"),
            )
            for turn in turns[1:5]:
                self.assertEqual(
                    turn.get("tool_order_numbers"),
                    ["<order-001>"],
                )
                self.assertFalse(
                    turn.get("visible_answer_conflicts_with_tool_data"),
                    turn,
                )
                self.assertFalse(
                    turn.get("unsupported_full_context_risk_claim"),
                    turn,
                )
            self.assertEqual(
                set(turns[5].get("tool_order_numbers") or []),
                set(seed.get("last_8_days_ready_order_numbers") or []),
            )
            self.assertEqual(
                (turns[5].get("tools") or []),
                ["orders.ready_to_ship"],
            )
            self.assertEqual(
                (
                    ((turns[5].get("tool_arguments") or [{}])[0] or {})
                    .get("arguments", {})
                    .get("period")
                ),
                "last_8_days",
            )

        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])")
        self.assertNotRegex(text, r"(?<![A-Za-z0-9])7\d{15}(?![A-Za-z0-9])")
        self.assertNotIn("<customer-006>", text)
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)

    def test_persisted_source_db_returns_recheck_proves_safe_exact_prepare(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-returns-conversation-recheck-2026-06-30.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_returns_conversation_recheck",
        )
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertTrue(safety.get("last_step_stops_at_prepare"), safety)
        self.assertTrue(safety.get("db_state_unchanged"), safety)
        for key in (
            "computer_use_used",
            "packaged_exe_used",
            "marketplace_write_performed",
            "db_write_performed",
            "execute_performed",
        ):
            self.assertFalse(safety.get(key), (key, safety))

        seed = dict(payload.get("seed") or {})
        self.assertEqual(seed.get("target_claim_id"), "<claim-001>")
        self.assertEqual(seed.get("target_order_number"), "<order-001>")
        self.assertEqual(
            seed.get("waiting_claim_ids"),
            ["<claim-001>", "<claim-002>"],
        )
        self.assertEqual(
            seed.get("status_before"),
            {
                "<claim-001>": "WaitingInAction",
                "<claim-002>": "WaitingInAction",
            },
        )
        self.assertEqual(payload.get("status_after"), seed.get("status_before"))

        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            turns = list(provider.get("turns") or [])
            self.assertEqual(len(turns), 3)
            self.assertEqual(
                turns[0].get("tool_claim_ids"),
                seed.get("waiting_claim_ids"),
            )
            self.assertEqual(
                (turns[0].get("conversation_context") or {}).get(
                    "claim_ids"
                ),
                seed.get("waiting_claim_ids"),
            )
            self.assertEqual(turns[1].get("tool_claim_ids"), ["<claim-001>"])
            self.assertEqual(
                (turns[1].get("conversation_context") or {}).get(
                    "claim_ids"
                ),
                ["<claim-001>"],
            )
            self.assertEqual(
                turns[2].get("prepared_claim_ids"),
                ["<claim-001>"],
            )
            self.assertTrue(turns[2].get("approval_required"), turns[2])
            self.assertTrue(turns[2].get("action_execute_enabled"), turns[2])

        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(
            text,
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}",
        )
        self.assertNotRegex(
            text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)
        self.assertGreaterEqual(
            int((privacy.get("alias_counts") or {}).get("customer") or 0),
            2,
        )

    def test_persisted_source_db_profit_export_proves_real_execute_and_content(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-profit-export-recheck-2026-06-30.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_profit_export_execute_recheck",
        )
        self.assertEqual(payload.get("db"), "source-app-db")
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertTrue(safety.get("file_output_performed"), safety)
        self.assertTrue(
            safety.get("temporary_output_removed_after_verify"),
            safety,
        )
        for key in (
            "computer_use_used",
            "packaged_exe_used",
            "marketplace_write_performed",
            "db_write_performed",
        ):
            self.assertFalse(safety.get(key), (key, safety))

        seed = dict(payload.get("seed") or {})
        self.assertEqual(seed.get("order_number"), "<order-001>")
        self.assertGreater(int(seed.get("item_count") or 0), 0)
        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            prepare = dict(provider.get("prepare") or {})
            execute = dict(provider.get("execute") or {})
            self.assertEqual(
                prepare.get("action_type"),
                "orders.action_export_order_profit_excel",
            )
            self.assertEqual(prepare.get("order_number"), "<order-001>")
            self.assertTrue(prepare.get("file_absent_before_approval"))
            self.assertIn("<order-001>", _compact_text(prepare.get("answer")))
            self.assertNotIn(
                "Agent task runtime ara durumda durdu",
                _compact_text(prepare.get("answer")),
            )
            verify = dict(execute.get("verify") or {})
            workbook = dict(execute.get("workbook") or {})
            self.assertTrue(verify.get("verified"), verify)
            self.assertTrue(workbook.get("expected_sheets_present"), workbook)
            self.assertTrue(workbook.get("exact_order_number_present"), workbook)
            self.assertGreater(int(workbook.get("size_bytes") or 0), 0)
            self.assertEqual(len(_compact_text(workbook.get("sha256"))), 64)
            self.assertIn("<order-001>", _compact_text(execute.get("answer")))
            self.assertTrue(execute.get("audit_action_present"))
            self.assertTrue(execute.get("temporary_sensitive_files_removed"))
            self.assertTrue(
                {
                    "pending_approval",
                    "execute_started",
                    "execute_completed",
                    "completed",
                }.issubset(set(provider.get("progress_phases") or [])),
                provider,
            )

        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(
            text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)

    def test_persisted_source_db_extracted_write_is_verified_and_restored(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-extracted-recheck-2026-06-30.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_extracted_execute_recheck",
        )
        self.assertEqual(payload.get("db"), "source-app-db")
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertTrue(safety.get("db_write_performed"), safety)
        self.assertTrue(safety.get("db_write_was_reversible_test"), safety)
        self.assertTrue(safety.get("source_db_restored_exactly"), safety)
        self.assertFalse(safety.get("marketplace_write_performed"), safety)
        self.assertFalse(safety.get("computer_use_used"), safety)
        self.assertFalse(safety.get("packaged_exe_used"), safety)

        seed = dict(payload.get("seed") or {})
        self.assertEqual(seed.get("order_number"), "<order-001>")
        self.assertGreater(int(seed.get("header_count") or 0), 0)
        self.assertTrue(
            all(
                not bool(row.get("is_extracted"))
                for row in list(seed.get("state_before") or [])
            ),
            seed,
        )
        self.assertEqual(
            payload.get("final_state"),
            seed.get("state_before"),
        )
        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            prepare = dict(provider.get("prepare") or {})
            execute = dict(provider.get("execute") or {})
            cleanup = dict(provider.get("cleanup") or {})
            self.assertEqual(
                prepare.get("action_type"),
                "labels.mark_orders_extracted_from_label_result",
            )
            self.assertEqual(
                prepare.get("order_numbers"),
                ["<order-001>"],
            )
            self.assertTrue(prepare.get("db_state_unchanged"))
            self.assertIn("<order-001>", _compact_text(prepare.get("answer")))
            self.assertNotIn(
                "Agent task runtime ara durumda durdu",
                _compact_text(prepare.get("answer")),
            )
            verify = dict(execute.get("verify") or {})
            self.assertTrue(verify.get("verified"), verify)
            self.assertEqual(
                verify.get("verified_by"),
                "order_header_is_extracted",
            )
            self.assertTrue(
                all(
                    bool(row.get("is_extracted"))
                    for row in list(execute.get("db_readback") or [])
                ),
                execute,
            )
            self.assertIn("<order-001>", _compact_text(execute.get("answer")))
            self.assertNotIn(
                "Agent gorevi tamamlandi",
                _compact_text(execute.get("answer")),
            )
            self.assertTrue(execute.get("audit_action_present"))
            self.assertTrue(cleanup.get("source_db_restored_exactly"))
            self.assertTrue(cleanup.get("temporary_audit_removed"))

        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(
            text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)

    def test_persisted_source_db_stale_cycle_is_verified_and_restored(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-stale-cycle-recheck-2026-06-30.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_stale_mark_restore_execute_recheck",
        )
        self.assertEqual(payload.get("db"), "source-app-db")
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertTrue(safety.get("db_write_performed"), safety)
        self.assertTrue(safety.get("db_write_was_reversible_test"), safety)
        self.assertTrue(safety.get("source_db_restored_exactly"), safety)
        self.assertFalse(safety.get("waiting_in_action_claim_used"), safety)
        self.assertFalse(safety.get("marketplace_write_performed"), safety)
        self.assertFalse(safety.get("computer_use_used"), safety)
        self.assertFalse(safety.get("packaged_exe_used"), safety)

        seed = dict(payload.get("seed") or {})
        self.assertEqual(seed.get("claim_id"), "<claim-001>")
        self.assertEqual(seed.get("order_number"), "<order-001>")
        self.assertIn(seed.get("status"), {"Accepted", "Cancelled"})
        self.assertEqual(payload.get("final_state"), seed.get("state_before"))
        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            mark = dict(provider.get("mark") or {})
            restore = dict(provider.get("restore") or {})
            cleanup = dict(provider.get("cleanup") or {})
            self.assertEqual(
                mark.get("action_type"),
                "orders.mark_return_claims_stale",
            )
            self.assertEqual(mark.get("claim_ids"), ["<claim-001>"])
            self.assertTrue((mark.get("verify") or {}).get("verified"))
            self.assertTrue(
                all(
                    bool(row.get("sync_deleted_at"))
                    for row in list(mark.get("state_after_execute") or [])
                ),
                mark,
            )
            self.assertIn(
                "<claim-001>",
                _compact_text(mark.get("prepare_answer")),
            )
            self.assertIn(
                "<claim-001>",
                _compact_text(mark.get("final_answer")),
            )
            self.assertEqual(
                restore.get("action_type"),
                "orders.restore_return_claims_from_stale",
            )
            self.assertEqual(restore.get("claim_ids"), ["<claim-001>"])
            self.assertTrue(
                (restore.get("verify") or {}).get("verified")
            )
            self.assertEqual(
                restore.get("state_after_execute"),
                seed.get("state_before"),
            )
            self.assertIn(
                "<claim-001>",
                _compact_text(restore.get("prepare_answer")),
            )
            self.assertIn(
                "<claim-001>",
                _compact_text(restore.get("final_answer")),
            )
            self.assertTrue(mark.get("audit_action_present"))
            self.assertTrue(restore.get("audit_action_present"))
            self.assertTrue(cleanup.get("source_db_restored_exactly"))
            self.assertTrue(cleanup.get("temporary_audits_removed"))

        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(
            text,
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}",
        )
        self.assertNotRegex(
            text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)

    def test_persisted_source_db_fetch_proves_api_save_reconcile_and_last_used(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-source-db-fetch-recheck-2026-07-01.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            payload.get("artifact_type"),
            "orders_live_source_db_marketplace_fetch_execute_recheck",
        )
        self.assertEqual(payload.get("db"), "source-app-db")
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertTrue(safety.get("marketplace_read_performed"), safety)
        self.assertTrue(safety.get("source_db_upsert_performed"), safety)
        self.assertFalse(safety.get("marketplace_mutation_performed"), safety)
        self.assertFalse(safety.get("computer_use_used"), safety)
        self.assertFalse(safety.get("packaged_exe_used"), safety)

        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            checks = dict(provider.get("checks") or {})
            self.assertTrue(checks and all(checks.values()), provider)
            prepare = dict(provider.get("prepare") or {})
            execute = dict(provider.get("execute") or {})
            source_state = dict(provider.get("source_state") or {})
            self.assertEqual(
                prepare.get("action_type"),
                "orders.get_orders_from_companies",
            )
            prepare_payload = dict(prepare.get("payload") or {})
            self.assertTrue(prepare_payload.get("save_to_db"))
            self.assertTrue(prepare_payload.get("fetch_returns"))
            self.assertTrue(prepare_payload.get("save_returns_to_db"))
            self.assertTrue(
                prepare_payload.get("verify_return_reconciliation")
            )
            self.assertTrue(prepare.get("source_state_unchanged"))
            self.assertNotIn(
                "Agent task runtime ara durumda durdu",
                _compact_text(prepare.get("answer")),
            )

            fetch_counts = dict(execute.get("fetch_counts") or {})
            self.assertGreater(int(fetch_counts.get("orders") or 0), 0)
            self.assertGreater(int(fetch_counts.get("returns") or 0), 0)
            verify = dict(execute.get("verify") or {})
            self.assertTrue(verify.get("verified"), verify)
            reconciliation = dict(
                verify.get("return_reconciliation") or {}
            )
            self.assertEqual(
                reconciliation.get("period"),
                "exact_epoch_window",
            )
            self.assertEqual(
                reconciliation.get("window_field"),
                "lastModifiedDate",
            )
            self.assertTrue(reconciliation.get("snapshot_complete"))
            self.assertFalse(
                reconciliation.get("needs_remote_snapshot")
            )
            self.assertEqual(
                reconciliation.get("observed_count"),
                fetch_counts.get("returns"),
            )
            self.assertEqual(
                reconciliation.get("confirmed_count"),
                fetch_counts.get("returns"),
            )
            self.assertEqual(
                reconciliation.get("unexpected_remote_count"),
                0,
            )
            self.assertEqual(reconciliation.get("stale_count"), 0)
            last_used = dict(verify.get("last_used_update") or {})
            self.assertTrue(last_used.get("verified"), last_used)
            readback = dict(execute.get("db_readback") or {})
            self.assertTrue(readback.get("all_orders_found"), readback)
            self.assertTrue(readback.get("all_claims_found"), readback)
            self.assertTrue(execute.get("audit_action_present"))
            self.assertTrue(source_state.get("last_used_advanced"))
            self.assertIn(
                "dogrulan",
                _compact_text(execute.get("answer")).casefold(),
            )

        def _all_keys(value: Any) -> list[str]:
            if isinstance(value, dict):
                return [
                    str(key)
                    for key, item in value.items()
                ] + [
                    nested
                    for item in value.values()
                    for nested in _all_keys(item)
                ]
            if isinstance(value, list):
                return [
                    nested
                    for item in value
                    for nested in _all_keys(item)
                ]
            return []

        self.assertTrue(
            all("<customer-" not in key for key in _all_keys(payload))
        )
        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(
            text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        self.assertNotRegex(
            text,
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}",
        )
        privacy = dict(payload.get("privacy_redaction") or {})
        self.assertTrue(privacy.get("redacted"), privacy)
        self.assertFalse(privacy.get("original_values_persisted"), privacy)

    def test_persisted_reasoning_effort_recheck_proves_low_high_profiles(self) -> None:
        path = (
            self._source_db_recheck_artifact_root()
            / "live-reasoning-effort-provider-recheck-2026-06-29.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload.get("artifact_type"),
            "orders_reasoning_effort_provider_recheck",
        )
        self.assertTrue(payload.get("passed"), payload)
        safety = dict(payload.get("safety") or {})
        self.assertFalse(safety.get("computer_use_used"), safety)
        self.assertFalse(safety.get("packaged_exe_used"), safety)
        self.assertFalse(safety.get("write_performed"), safety)

        providers = list(payload.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            self.assertTrue(provider.get("passed"), provider)
            profiles = list(provider.get("profiles") or [])
            self.assertEqual(
                {row.get("reasoning_effort") for row in profiles},
                {"low", "high"},
            )
            for profile in profiles:
                self.assertTrue(
                    all(dict(profile.get("checks") or {}).values()),
                    profile,
                )
                runtime_plan = dict(profile.get("runtime_plan") or {})
                capabilities = dict(
                    runtime_plan.get("reasoning_capabilities") or {}
                )
                expected_control = (
                    "thinking_level"
                    if provider.get("provider_code") == "gemini"
                    else "reasoning_effort"
                )
                self.assertEqual(
                    capabilities.get("control"),
                    expected_control,
                )
                self.assertEqual(
                    runtime_plan.get("reasoning_effort"),
                    profile.get("reasoning_effort"),
                )
                self.assertTrue(profile.get("actual_model"), profile)
                profit = dict(profile.get("profit_evidence") or {})
                self.assertIsNone(profit.get("amount"))
                self.assertFalse(profit.get("estimated_profit_ready"))

    def test_persisted_gemma12b_source_db_conversation_proves_local_best_scope(self) -> None:
        path = (
            self._local_best_artifact_root()
            / "live-local-gemma12b-orders-conversation-2026-06-29.json"
        )
        self.assertTrue(path.exists(), path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload.get("artifact_type"),
            "orders_local_best_source_db_conversation",
        )
        self.assertTrue(payload.get("passed"), payload)
        self.assertIn(
            "gemma-4-12b",
            _compact_text((payload.get("model") or {}).get("repo_id")).casefold(),
        )
        plan = dict(payload.get("runtime_plan") or {})
        self.assertTrue(plan.get("safe_to_run"), plan)
        self.assertFalse(plan.get("allow_unsafe"), plan)
        self.assertEqual(plan.get("num_ctx"), 4096)
        self.assertEqual(plan.get("runtime_strategy"), "llama_cpp")

        turns = list(payload.get("turns") or [])
        self.assertEqual(len(turns), 5)
        self.assertEqual(turns[0].get("mode"), "answer")
        self.assertEqual(turns[0].get("tools"), [])
        self.assertGreater(len(_compact_text(turns[0].get("answer"))), 30)
        self.assertEqual(turns[1].get("mode"), "answer")
        for term in ("etiket", "kargo", "iade"):
            self.assertIn(
                term,
                _compact_text(turns[1].get("answer")).casefold(),
            )

        listed = list(
            dict(turns[3].get("conversation_context") or {}).get(
                "order_numbers"
            )
            or []
        )
        prepared = list(turns[4].get("prepared_order_numbers") or [])
        self.assertEqual(len(listed), 22)
        self.assertEqual(set(prepared), set(listed))
        self.assertTrue(turns[4].get("approval_required"))
        self.assertTrue(turns[4].get("action_execute_enabled"))
        self.assertTrue(all(dict(payload.get("checks") or {}).values()))

        transcript_text = json.dumps(turns, ensure_ascii=False)
        self.assertNotRegex(
            transcript_text,
            r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])",
        )
        self.assertNotRegex(
            transcript_text,
            r"(?<![A-Za-z0-9])7\d{15}(?![A-Za-z0-9])",
        )

    def test_live_artifact_writer_sanitizes_paths_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"ORDERSCOUT_LIVE_LLM_ARTIFACT_DIR": temp_dir},
        ):
            path = _write_live_artifact(
                "artifact helper test",
                provider_label="source=test; provider=gemini; model=free",
                transcript=[
                    {
                        "user": (
                            'Canli Musteri olanin raporunu '
                            '"C:/Users/demo/AppData/Local/OrderScout/_tmp/out.xlsx" '
                            "dosyasina aktar"
                        ),
                        "payload": {
                            "output_path": "C:\\Users\\demo\\AppData\\Local\\OrderScout\\_tmp\\out.xlsx",
                            "api_key": "AIza-secret",
                            "order_numbers": ["11357933201"],
                            "tracking_number": "7330033757995470",
                            "customer_name": "Canli Musteri",
                            "customer_first_name": "Es",
                            "present": True,
                            "payload_status": "present payload test",
                            "status_by_claim": {
                                "75a7c1c0-73a2-49f7-bb8a-366dee971405": (
                                    "WaitingInAction"
                                )
                            },
                        },
                        "answer": (
                            "db_name=test.sqlite3 api_secret=secret-token C:\\Users\\demo\\audit.jsonl "
                            "siparis 11357933201 takip 7330033757995470 musteri: Canli Musteri | "
                            "e-posta canli@example.com telefon 0532 111 22 33"
                        ),
                    }
                ],
            )

            self.assertIsNotNone(path)
            text = path.read_text(encoding="utf-8")

        self.assertIn("<local_path>/out.xlsx", text)
        self.assertIn("<local_path>/audit.jsonl", text)
        self.assertNotIn("C:/Users", text)
        self.assertNotIn("C:\\Users", text)
        self.assertNotIn("AIza-secret", text)
        self.assertNotIn("secret-token", text)
        self.assertNotIn("test.sqlite3", text)
        self.assertNotIn("11357933201", text)
        self.assertNotIn("7330033757995470", text)
        self.assertNotIn("Canli Musteri", text)
        self.assertNotIn(
            "75a7c1c0-73a2-49f7-bb8a-366dee971405",
            text,
        )
        self.assertNotIn("canli@example.com", text)
        self.assertNotIn("0532 111 22 33", text)
        self.assertGreaterEqual(text.count("<order-001>"), 2)
        self.assertGreaterEqual(text.count("<tracking-001>"), 2)
        self.assertGreaterEqual(text.count("<customer-001>"), 2)
        self.assertIn('"<claim-001>": "WaitingInAction"', text)
        self.assertIn("<customer-001> olanin raporunu", text)
        self.assertIn('"present": true', text)
        self.assertIn('"payload_status": "present payload test"', text)
        self.assertIn('"customer_first_name": "<customer-002>"', text)
        self.assertNotIn("pr<customer-", text)
        self.assertNotIn("p<customer-", text)
        payload = json.loads(text)
        redaction = payload.get("privacy_redaction") or {}
        self.assertTrue(redaction.get("redacted"), redaction)
        self.assertFalse(redaction.get("original_values_persisted"), redaction)

    def test_persisted_gemini_artifacts_prove_visible_answer_and_execute_quality(self) -> None:
        root = self._artifact_root()
        expected_files = {
            "live-action-followup-transcript-quality.json",
            "live-ai-goals-smoke-2026-06-23.json",
            "live-conversation-transcript-quality.json",
            "live-fetch-sync-transcript-quality.json",
            "live-gemini-recent-old-orders-followup-print-context.json",
            "live-openrouter-recent-old-orders-followup-print-context.json",
            "live-openrouter-chat-analysis-recovery.json",
            "live-orders-followup-context-recheck-2026-06-23.json",
            "live-profit-export-transcript-quality.json",
            "live-ready-all-followup-label-context-2026-06-26.json",
            "live-ready-count-list-label-context-2026-06-26.json",
            "live-equivalent-period-followup-analysis-2026-06-26.json",
            "live-source-db-ready-label-execute-docx-2026-06-26.json",
            "live-stale-return-restore-transcript-quality.json",
        }
        self.assertTrue(root.exists(), root)
        actual_files = {
            path.name
            for path in root.glob("*.json")
            if not path.name.startswith("live-task-runtime-")
            and path.name
            not in {
                "ui-chat-tab-approval-smoke.json",
                "live-gemini-model-probe.json",
                "live-openrouter-model-probe.json",
                "live-local-model-probe.json",
                "live-local-orders-tiered-eval.json",
                "source-main-window-smoke.json",
            }
        }
        self.assertEqual(actual_files, expected_files)

        artifacts = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in root.glob("*.json")
            if not path.name.startswith("live-task-runtime-") and path.name != "ui-chat-tab-approval-smoke.json"
        }
        joined = "\n".join(json.dumps(value, ensure_ascii=False) for value in artifacts.values())
        for forbidden in ("C:/Users", "C:\\Users", "AIza", "test.sqlite3", "db_name="):
            self.assertNotIn(forbidden, joined)

        leakage_markers = (
            "role:",
            "constraints:",
            "specific requirements:",
            "tool result:",
            "draft 1",
            "draft 2",
            "no raw json",
            "no hallucinated",
            "no fake numbers",
        )
        for artifact_name, artifact in artifacts.items():
            for row in artifact.get("transcript") or []:
                if not isinstance(row, dict) or row.get("phase") == "execute":
                    continue
                visible_answer = _compact_text(row.get("answer")).casefold()
                for marker in leakage_markers:
                    self.assertNotIn(marker, visible_answer, f"{artifact_name}: {visible_answer}")

        conversation = artifacts["live-conversation-transcript-quality.json"]["transcript"]
        self.assertEqual(conversation[0].get("tool"), None)
        self.assertEqual(conversation[1].get("tool"), None)
        self.assertEqual(conversation[2].get("tool"), None)
        self.assertEqual(conversation[3].get("answer"), (conversation[3].get("llm_responses") or [])[-1])
        self.assertNotIn("Siparis operasyon analizi:", conversation[3].get("answer") or "")
        analysis_answer = _compact_text(conversation[3].get("answer")).casefold().translate(
            str.maketrans("çğıöşüâîû", "cgiosuaiu")
        )
        for term in ("ciro", "kar", "iade", "kargoya hazir", "takip"):
            self.assertIn(term, analysis_answer)
        self.assertEqual(conversation[4].get("answer"), (conversation[4].get("llm_responses") or [])[-1])
        capability_answer = _compact_text(conversation[4].get("answer")).casefold().translate(
            str.maketrans("çğıöşüâîû", "cgiosuaiu")
        )
        for term in ("etiket", "kargo firmasi", "iade", "Trendyol"):
            self.assertIn(term.casefold(), capability_answer)
        self.assertEqual(conversation[-1].get("payload", {}).get("order_numbers"), ["ORD-AYSE-READY", "ORD-LIVE-CONVO-EXTRA"])

        action = artifacts["live-action-followup-transcript-quality.json"]["transcript"]
        action_executes = [row for row in action if row.get("phase") == "execute"]
        self.assertEqual(len(action_executes), 3)
        self.assertTrue(all((row.get("verify") or {}).get("verified") for row in action_executes), action_executes)
        self.assertEqual(action[3].get("payload", {}).get("order"), "ORD-MAHMUT-READY")
        self.assertEqual(action[6].get("payload", {}).get("order"), "CLAIM-MAHMUT-CONVO")
        self.assertEqual(action_executes[1].get("extra", {}).get("db_cargo_provider_by_order", {}).get("ORD-MAHMUT-READY"), "Aras")
        self.assertEqual(action_executes[2].get("extra", {}).get("db_return_status_by_claim", {}).get("CLAIM-MAHMUT-CONVO"), "Accepted")

        fetch = artifacts["live-fetch-sync-transcript-quality.json"]["transcript"]
        self.assertEqual(fetch[-1].get("phase"), "execute")
        self.assertTrue((fetch[-1].get("verify") or {}).get("verified"))
        self.assertEqual(fetch[-1].get("extra", {}).get("saved_order_numbers"), ["ORD-LIVE-FETCH-1"])

        profit = artifacts["live-profit-export-transcript-quality.json"]["transcript"]
        self.assertEqual(profit[-1].get("phase"), "execute")
        self.assertTrue((profit[-1].get("verify") or {}).get("verified"))
        self.assertTrue((profit[-1].get("extra") or {}).get("workbook_exists"))
        self.assertEqual(profit[-2].get("payload", {}).get("order_number"), "ORD-MAHMUT-READY")

        stale = artifacts["live-stale-return-restore-transcript-quality.json"]["transcript"]
        stale_executes = [row for row in stale if row.get("phase") == "execute"]
        self.assertEqual(len(stale_executes), 1)
        self.assertTrue((stale_executes[0].get("verify") or {}).get("verified"))
        self.assertEqual(stale_executes[0].get("extra", {}).get("db_sync_deleted_at", {}).get("CLAIM-LIVE-STALE-RESTORE"), None)

        openrouter_recovery = artifacts["live-openrouter-chat-analysis-recovery.json"]
        self.assertEqual((openrouter_recovery.get("provider") or {}).get("provider_code"), "openrouter")
        self.assertEqual((openrouter_recovery.get("provider") or {}).get("model"), "nvidia/nemotron-3-nano-30b-a3b:free")
        recovery_turns = openrouter_recovery.get("turns") or []
        self.assertEqual(len(recovery_turns), 2)
        self.assertTrue((recovery_turns[0].get("quality") or {}).get("natural_chat"))
        self.assertTrue((recovery_turns[0].get("quality") or {}).get("not_cold_dismissive"))
        self.assertEqual(recovery_turns[0].get("tool_calls"), [])
        self.assertIn("canini", recovery_turns[0].get("visible_answer") or "")
        self.assertNotIn("konusmak istemediginizi", recovery_turns[0].get("visible_answer") or "")
        self.assertIn("finance.profit_amount", recovery_turns[1].get("tool_calls") or [])
        self.assertIn("returns.amount_total", recovery_turns[1].get("tool_calls") or [])
        self.assertTrue((recovery_turns[1].get("quality") or {}).get("does_not_treat_revenue_as_profit"))
        self.assertTrue((recovery_turns[1].get("quality") or {}).get("not_today_zero_shortcut"))
        self.assertTrue((recovery_turns[1].get("quality") or {}).get("includes_clear_decision"))
        self.assertTrue((recovery_turns[1].get("quality") or {}).get("separates_confidence_and_risk"))
        self.assertTrue((recovery_turns[1].get("quality") or {}).get("includes_next_action"))
        self.assertTrue((recovery_turns[1].get("quality") or {}).get("no_mojibake"))
        analysis_excerpt = "\n".join(recovery_turns[1].get("visible_answer_excerpt") or [])
        self.assertIn("Once net karar", analysis_excerpt)
        self.assertIn("Guven veren taraf", analysis_excerpt)
        self.assertIn("Guven vermeyen taraf", analysis_excerpt)
        self.assertIn("Bir sonraki hamle", analysis_excerpt)
        provider_rechecks = openrouter_recovery.get("provider_diversity_recheck") or []
        provider_codes = {row.get("provider_code") for row in provider_rechecks}
        self.assertIn("openrouter", provider_codes)
        self.assertIn("gemini", provider_codes)
        self.assertTrue(all(row.get("api_key_logged") is False for row in provider_rechecks))
        self.assertFalse((openrouter_recovery.get("safety") or {}).get("api_key_logged"))
        self.assertEqual(openrouter_recovery.get("verdict"), "pass")

        local_tiered = artifacts["live-local-orders-tiered-eval.json"]
        self.assertEqual(local_tiered.get("turn_count"), 6)
        gates = (local_tiered.get("extra") or {}).get("quality_gates") or {}
        self.assertTrue(gates.get("best_natural_chat_tool_free"))
        self.assertTrue(gates.get("best_contextual_label_prepare"))
        self.assertTrue(gates.get("weak_exclusion_keeps_remaining_only"))
        self.assertTrue(gates.get("weak_remaining_cargo_prepare_safe"))
        local_turns = local_tiered.get("transcript") or []
        self.assertEqual(local_turns[0].get("mode"), "answer")
        self.assertIsNone(local_turns[0].get("tool"))
        self.assertEqual(local_turns[2].get("tool"), "labels.create_from_orders.prepare")
        self.assertEqual(set((local_turns[2].get("payload") or {}).get("order_numbers") or []), {"ORD-LOCAL-TIER-1", "ORD-LOCAL-TIER-2"})
        self.assertEqual(local_turns[4].get("tool"), "orders.lookup")
        self.assertIn("ORD-LOCAL-TIER-2", local_turns[4].get("answer") or "")
        self.assertNotIn("ORD-LOCAL-TIER-1", local_turns[4].get("answer") or "")
        self.assertEqual(local_turns[5].get("tool"), "orders.change_cargo_provider.prepare")
        self.assertIn("ORD-LOCAL-TIER-2", local_turns[5].get("answer") or "")
        self.assertNotIn("ORD-LOCAL-TIER-1", local_turns[5].get("answer") or "")

    def test_persisted_openrouter_conversation_proves_visible_quality_and_exact_followup_action(self) -> None:
        path = self._openrouter_orders_artifact_root() / "live-conversation-transcript-quality.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        provider = _compact_text(artifact.get("provider")).casefold()
        transcript = artifact.get("transcript") or []

        self.assertIn("provider=openrouter", provider)
        self.assertIn("model=openai/gpt-oss-120b:free", provider)
        self.assertEqual(artifact.get("turn_count"), 7)
        self.assertEqual(len(transcript), 7)

        forbidden_visible_markers = (
            '"reply"',
            "role:",
            "constraints:",
            "specific requirements:",
            "tool result:",
            "draft 1",
            "draft 2",
            "no raw json",
            "no hallucinated",
            "no fake numbers",
        )
        passive_markers = (
            "nasil yardimci olabilirim",
            "ne yapmak istersin",
            "detay verirseniz",
            "bilemiyorum",
            "bilemem",
            "maalesef",
            "yemek siparisi",
            "rota",
        )
        for row in transcript:
            visible = _compact_text(row.get("answer")).casefold()
            self.assertTrue(visible, row)
            for marker in forbidden_visible_markers:
                self.assertNotIn(marker, visible, row)

        for row in transcript[:3]:
            self.assertEqual(row.get("mode"), "answer", row)
            self.assertIsNone(row.get("tool"), row)
            self.assertEqual(row.get("tools"), [], row)
            self.assertGreater(len(_compact_text(row.get("answer"))), 20, row)
            visible = _compact_text(row.get("answer")).casefold()
            for marker in passive_markers:
                self.assertNotIn(marker, visible, row)
        self.assertFalse(_compact_text(transcript[2].get("answer")).lstrip().startswith("{"))

        analysis = transcript[3]
        analysis_tools = set(analysis.get("tools") or [])
        self.assertEqual(analysis.get("mode"), "tools")
        for tool_name in (
            "orders.count",
            "orders.revenue_total",
            "finance.profit_amount",
            "returns.count",
            "returns.amount_total",
            "orders.ready_to_ship_count",
            "orders.fulfillment_risk_count",
        ):
            self.assertIn(tool_name, analysis_tools, analysis)
        analysis_answer = _compact_text(analysis.get("answer")).casefold().translate(
            str.maketrans("çğıöşüâîû", "cgiosuaiu")
        )
        for term in ("ciro", "kar", "iade", "kargoya hazir"):
            self.assertIn(term, analysis_answer, analysis)
        self.assertEqual(
            _compact_text(analysis.get("answer")),
            _compact_text((analysis.get("llm_responses") or [""])[-1]),
            analysis,
        )

        capabilities = transcript[4]
        self.assertEqual(capabilities.get("mode"), "answer")
        self.assertIsNone(capabilities.get("tool"))
        for term in ("etiket", "iade", "kargo", "senkron"):
            self.assertIn(term, _compact_text(capabilities.get("answer")).casefold(), capabilities)
        self.assertEqual(
            _compact_text(capabilities.get("answer")),
            _compact_text((capabilities.get("llm_responses") or [""])[-1]),
            capabilities,
        )

        listed = transcript[5]
        self.assertEqual(listed.get("tool"), "orders.recent")
        for order_number in ("ORD-LIVE-CONVO-EXTRA", "ORD-AYSE-READY"):
            self.assertIn(order_number, _compact_text(listed.get("answer")), listed)

        prepared = transcript[6]
        self.assertEqual(prepared.get("mode"), "approval_required")
        self.assertTrue(prepared.get("approval_required"))
        self.assertEqual(prepared.get("tool"), "labels.create_from_orders.prepare")
        self.assertEqual(prepared.get("action_type"), "labels.action_create_labels_from_selected_orders")
        self.assertTrue(prepared.get("execute_enabled"))
        self.assertEqual(
            set((prepared.get("payload") or {}).get("order_numbers") or []),
            {"ORD-LIVE-CONVO-EXTRA", "ORD-AYSE-READY"},
        )

        joined = json.dumps(artifact, ensure_ascii=False)
        for forbidden in ("C:/Users", "C:\\Users", "AIza", "test.sqlite3", "db_name="):
            self.assertNotIn(forbidden, joined)

    def test_persisted_ready_all_followup_label_context_proves_unicode_scope(self) -> None:
        scenarios = (
            (
                self._artifact_root() / "live-ready-all-followup-label-context-2026-06-26.json",
                "gemini",
            ),
            (
                self._openrouter_orders_artifact_root() / "live-ready-all-followup-label-context-2026-06-26.json",
                "openrouter",
            ),
        )
        for path, provider_code in scenarios:
            with self.subTest(path=path.name, provider=provider_code):
                self.assertTrue(path.exists(), path)
                artifact = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(artifact.get("artifact_type"), "orders_live_ready_all_followup_label_context")
                self.assertEqual(artifact.get("provider"), provider_code)
                checks = artifact.get("checks") or {}
                self.assertTrue(checks.get("turn1_success"), checks)
                self.assertTrue(checks.get("turn2_success"), checks)
                self.assertEqual(checks.get("context_count"), 14, checks)
                self.assertEqual(checks.get("prepare_count"), 14, checks)
                self.assertTrue(checks.get("same_scope"), checks)
                self.assertFalse(checks.get("zero_prepare_bug"), checks)
                self.assertTrue(checks.get("answer_has_all_prepared_ids"), checks)
                self.assertFalse(checks.get("wrong_llm_id_present"), checks)
                self.assertTrue(checks.get("approval_required"), checks)

                transcript = artifact.get("transcript") or []
                self.assertEqual(len(transcript), 2, artifact)
                self.assertEqual(transcript[0].get("user"), "başkan kargoya hazır siparişleri listele")
                self.assertEqual(transcript[1].get("user"), "tamam şimdi bunları etikete yazdır")
                self.assertEqual(transcript[0].get("tools"), ["orders.ready_to_ship"])
                self.assertEqual(transcript[1].get("tools"), ["labels.create_from_orders.prepare"])
                self.assertEqual(transcript[1].get("mode"), "approval_required")
                self.assertEqual(transcript[1].get("action_type"), "labels.action_create_labels_from_selected_orders")
                expected = set(transcript[0].get("context_order_numbers") or [])
                prepared = set(transcript[1].get("prepared_order_numbers") or [])
                self.assertEqual(len(expected), 14)
                self.assertEqual(prepared, expected)
                answer = _compact_text(transcript[1].get("answer"))
                self.assertIn("Onay gerekiyor", answer)
                self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", answer)
                self.assertNotIn("11106942932", answer)
                for order_number in prepared:
                    self.assertIn(order_number, answer)

    def test_persisted_ready_count_list_label_context_proves_full_scope_above_twenty(self) -> None:
        path = self._artifact_root() / "live-ready-count-list-label-context-2026-06-26.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(artifact.get("passed"), artifact)
        attempts = artifact.get("attempts") or []
        self.assertGreaterEqual(len(attempts), 2, artifact)
        provider_codes = {_compact_text((row.get("provider") or {}).get("provider_code")) for row in attempts}
        self.assertIn("gemini", provider_codes)
        self.assertIn("openrouter", provider_codes)
        for row in attempts:
            with self.subTest(provider=(row.get("provider") or {}).get("provider_code")):
                self.assertTrue(row.get("success"), row)
                self.assertEqual(row.get("first_count"), 22, row)
                self.assertEqual(row.get("listed_order_count"), 22, row)
                self.assertEqual(row.get("prepared_order_count"), 22, row)
                self.assertTrue(row.get("more_than_twenty_proof"), row)
                self.assertTrue(row.get("no_execute_performed"), row)
                listed = set(row.get("listed_order_numbers") or [])
                prepared = set(row.get("prepared_order_numbers") or [])
                self.assertEqual(len(listed), 22, row)
                self.assertEqual(prepared, listed, row)
                self.assertEqual((row.get("first_tool") or {}).get("tool"), "orders.ready_to_ship_count")
                self.assertEqual((row.get("second_tool") or {}).get("tool"), "orders.ready_to_ship")
                self.assertEqual((row.get("third_tool") or {}).get("tool"), "labels.create_from_orders.prepare")
                self.assertEqual(row.get("third_mode"), "approval_required")

    def test_persisted_orders_live_evidence_redacts_private_commerce_identifiers(self) -> None:
        cases = (
            (
                self._artifact_root() / "live-ready-all-followup-label-context-2026-06-26.json",
                {"order": 14, "tracking": 14},
            ),
            (
                self._openrouter_orders_artifact_root() / "live-ready-all-followup-label-context-2026-06-26.json",
                {"order": 14, "tracking": 14},
            ),
            (
                self._artifact_root() / "live-ready-count-list-label-context-2026-06-26.json",
                {"order": 22, "tracking": 20},
            ),
            (
                self._artifact_root() / "live-equivalent-period-followup-analysis-2026-06-26.json",
                {"order": 4, "order_partial": 1},
            ),
        )
        for path, expected_counts in cases:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), path)
                artifact = json.loads(path.read_text(encoding="utf-8"))
                privacy = artifact.get("privacy_redaction") or {}
                self.assertTrue(privacy.get("redacted"), privacy)
                self.assertTrue(privacy.get("aliases_are_stable_within_artifact"), privacy)
                self.assertFalse(privacy.get("original_values_persisted"), privacy)
                self.assertEqual(privacy.get("alias_counts"), expected_counts)
                joined = json.dumps(artifact, ensure_ascii=False)
                self.assertIsNone(
                    re.search(r"(?<![A-Za-z0-9])1\d{8,10}(?![A-Za-z0-9])", joined),
                    path,
                )
                self.assertIsNone(
                    re.search(r"(?<![A-Za-z0-9])7\d{15}(?![A-Za-z0-9])", joined),
                    path,
                )

    def test_persisted_source_db_label_execute_docx_proves_content_verify(self) -> None:
        path = self._artifact_root() / "live-source-db-ready-label-execute-docx-2026-06-26.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(artifact.get("passed"), artifact)
        self.assertEqual(artifact.get("artifact_type"), "orders_live_source_db_label_execute_docx_content")
        self.assertEqual(artifact.get("db"), "source-app-db")
        self.assertEqual(artifact.get("ready_tool"), "orders.ready_to_ship")
        self.assertEqual(artifact.get("prepare_tool"), "labels.create_from_orders.prepare")
        self.assertEqual(artifact.get("execute_action_type"), "labels.action_create_labels_from_selected_orders")
        self.assertFalse(artifact.get("api_call_performed"), artifact)
        self.assertFalse(artifact.get("db_write_performed"), artifact)
        self.assertTrue(artifact.get("file_output_performed"), artifact)
        self.assertGreater(int(artifact.get("ready_count") or 0), 20)
        self.assertEqual(artifact.get("ready_count"), artifact.get("prepared_count"))
        self.assertEqual(artifact.get("prepared_count"), artifact.get("verified_count"))
        self.assertTrue(artifact.get("same_scope_ready_prepare_verify"), artifact)
        self.assertTrue(artifact.get("more_than_twenty_proof"), artifact)
        verify = artifact.get("execute_verify") or {}
        self.assertTrue(verify.get("verified"), artifact)
        self.assertEqual(verify.get("verified_by"), "payload_and_docx_content")
        self.assertTrue(verify.get("docx_order_numbers_verified"), verify)
        self.assertEqual(set(verify.get("order_numbers") or []), set(artifact.get("order_numbers") or []))
        order_aliases = list(artifact.get("order_numbers") or [])
        self.assertEqual(len(order_aliases), 22, artifact)
        self.assertEqual(
            order_aliases,
            [f"<source-ready-order-{index:02d}>" for index in range(1, 23)],
        )

        docx_info = artifact.get("docx") or {}
        docx_path = self._artifact_root() / _compact_text(docx_info.get("file_name"))
        self.assertFalse(bool(docx_info.get("retained")), docx_info)
        self.assertFalse(docx_path.exists(), docx_path)
        self.assertEqual(len(_compact_text(docx_info.get("sha256"))), 64)
        self.assertGreater(int(docx_info.get("size_bytes") or 0), 1_000)
        self.assertIn("shipping data", _compact_text(docx_info.get("retention_reason")))

        audit_info = artifact.get("audit") or {}
        audit_path = self._artifact_root() / _compact_text(audit_info.get("file_name"))
        self.assertTrue(audit_path.exists(), audit_path)
        self.assertEqual(hashlib.sha256(audit_path.read_bytes()).hexdigest(), audit_info.get("sha256"))
        self.assertTrue(audit_info.get("operation_present"), audit_info)
        self.assertTrue(audit_info.get("redacted"), audit_info)
        self.assertEqual(audit_info.get("redaction_scope"), "customer shipping data and real order numbers")
        self.assertEqual(audit_info.get("order_alias_pattern"), "<source-ready-order-NN>")

        joined = json.dumps(artifact, ensure_ascii=False)
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])", joined), joined)
        audit_text = audit_path.read_text(encoding="utf-8")
        self.assertIn("<source-ready-order-01>", audit_text)
        self.assertIn("<source-ready-order-22>", audit_text)
        self.assertIn("count, aliases", audit_text)
        self.assertIsNone(re.search(r"(?<![A-Za-z0-9])1\d{10}(?![A-Za-z0-9])", audit_text), audit_text)
        for forbidden in ("C:/Users", "C:\\Users", "AIza", "db_name=", ".sqlite3"):
            self.assertNotIn(forbidden, joined)

    def test_persisted_openrouter_task_runtime_proves_execute_verify_and_file_output(self) -> None:
        root = self._openrouter_task_runtime_artifact_root()
        expected_files = {
            "live-task-runtime-cargo-change.json",
            "live-task-runtime-label-ready-orders.json",
            "live-task-runtime-mark-extracted.json",
            "live-task-runtime-profit-export.json",
            "live-task-runtime-return-approval.json",
        }
        self.assertTrue(root.exists(), root)
        self.assertEqual({path.name for path in root.glob("*.json")}, expected_files)
        artifacts = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in root.glob("*.json")
        }

        for name, artifact in artifacts.items():
            provider = _compact_text(artifact.get("provider")).casefold()
            self.assertIn("provider=openrouter", provider, name)
            self.assertIn("model=openai/gpt-oss-120b:free", provider, name)
            self.assertEqual(artifact.get("turn_count"), 1, name)
            row = (artifact.get("transcript") or [None])[0]
            self.assertIsInstance(row, dict, name)
            plan = row.get("plan") or {}
            self.assertEqual(plan.get("source"), "llm", name)
            self.assertEqual(plan.get("step_ids"), plan.get("llm_step_ids"), name)
            self.assertEqual(row.get("resume_status"), "complete", name)
            self.assertTrue((row.get("execute_verify") or {}).get("verified"), name)
            self.assertGreaterEqual(len(row.get("llm_responses") or []), 2, name)

        returns_row = artifacts["live-task-runtime-return-approval.json"]["transcript"][0]
        self.assertEqual(
            (returns_row.get("plan") or {}).get("step_ids"),
            ["returns.waiting.list", "returns.approve.prepare"],
        )
        self.assertEqual(returns_row.get("pending_action_type"), "orders.approve_return_claim")
        self.assertEqual(returns_row.get("payload_order"), "CLAIM-LIVE-TASK-APPROVE")
        return_verify_rows = (returns_row.get("execute_verify") or {}).get("rows") or []
        self.assertEqual((return_verify_rows[0] or {}).get("status"), "Accepted")
        self.assertEqual((return_verify_rows[0] or {}).get("waiting_line_item_ids"), [])

        cargo_row = artifacts["live-task-runtime-cargo-change.json"]["transcript"][0]
        self.assertEqual(
            (cargo_row.get("plan") or {}).get("step_ids"),
            ["orders.ready_to_ship", "orders.cargo.change.prepare"],
        )
        self.assertEqual(cargo_row.get("pending_action_type"), "orders.change_order_cargo_provider")
        self.assertEqual((cargo_row.get("payload") or {}).get("order"), "ORD-LIVE-TASK-CARGO-MAHMUT")
        self.assertEqual((cargo_row.get("payload") or {}).get("cargo_provider_code"), "ARAS")
        cargo_verify_rows = (cargo_row.get("execute_verify") or {}).get("rows") or []
        self.assertEqual((cargo_verify_rows[0] or {}).get("cargo_provider"), "Aras")

        label_row = artifacts["live-task-runtime-label-ready-orders.json"]["transcript"][0]
        self.assertEqual(
            (label_row.get("plan") or {}).get("step_ids"),
            ["orders.ready_to_ship", "orders.labels.prepare"],
        )
        self.assertEqual(label_row.get("pending_action_type"), "labels.action_create_labels_from_selected_orders")
        self.assertEqual(
            set(label_row.get("payload_order_numbers") or []),
            {"ORD-LIVE-TASK-READY-1", "ORD-LIVE-TASK-READY-2"},
        )
        self.assertEqual(
            set((label_row.get("execute_verify") or {}).get("order_numbers") or []),
            {"ORD-LIVE-TASK-READY-1", "ORD-LIVE-TASK-READY-2"},
        )

        extracted_row = artifacts["live-task-runtime-mark-extracted.json"]["transcript"][0]
        self.assertEqual(
            (extracted_row.get("plan") or {}).get("step_ids"),
            ["orders.ready_to_ship", "orders.labels.extracted.prepare"],
        )
        self.assertEqual(extracted_row.get("pending_action_type"), "labels.mark_orders_extracted_from_label_result")
        self.assertEqual(
            set(extracted_row.get("payload_order_numbers") or []),
            {"ORD-LIVE-TASK-EXTRACTED-1", "ORD-LIVE-TASK-EXTRACTED-2"},
        )
        self.assertEqual((extracted_row.get("execute_verify") or {}).get("verified_by"), "order_header_is_extracted")

        export_row = artifacts["live-task-runtime-profit-export.json"]["transcript"][0]
        self.assertEqual(
            (export_row.get("plan") or {}).get("step_ids"),
            ["orders.ready_to_ship", "orders.profit.export.prepare"],
        )
        self.assertEqual(export_row.get("pending_action_type"), "orders.action_export_order_profit_excel")
        self.assertEqual(export_row.get("payload_order_number"), "ORD-LIVE-TASK-PROFIT-MAHMUT")
        export_verify = export_row.get("execute_verify") or {}
        self.assertEqual(export_verify.get("verified_by"), "filesystem")
        self.assertGreater(int(export_verify.get("size_bytes") or 0), 0)
        self.assertEqual(Path(_compact_text(export_verify.get("output_path"))).name, "mahmut-live-task-profit.xlsx")

        joined = json.dumps(artifacts, ensure_ascii=False)
        for forbidden in ("C:/Users", "C:\\Users", "AIza", "test.sqlite3", "db_name=", "live-task-fetch-key"):
            self.assertNotIn(forbidden, joined)

    def test_persisted_best_local_conversation_proves_raw_multi_turn_chat_quality(self) -> None:
        path = self._local_best_artifact_root() / "live-local-best-conversation-quality.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        provider = _compact_text(artifact.get("provider")).casefold()
        transcript = artifact.get("transcript") or []
        gates = (artifact.get("extra") or {}).get("quality_gates") or {}

        self.assertIn("provider=llama.cpp", provider)
        self.assertIn("model=jc-builds/gemma-4-e4b-it-gguf", provider)
        self.assertEqual(artifact.get("turn_count"), 4)
        self.assertEqual(len(transcript), 4)
        self.assertTrue(gates.get("all_turns_tool_free"))
        self.assertTrue(gates.get("all_casual_visible_answers_are_raw_model_answers"))
        self.assertTrue(gates.get("capability_covers_labels_returns_cargo"))

        for row in transcript:
            self.assertEqual(row.get("mode"), "answer", row)
            self.assertIsNone(row.get("tool"), row)
            self.assertGreater(len(_compact_text(row.get("answer"))), 20, row)
        for row in transcript[:3]:
            self.assertEqual(row.get("answer"), row.get("raw_llm_response"), row)
            self.assertTrue(row.get("answer_preserved_from_model"), row)

        def searchable(value: Any) -> str:
            text = unicodedata.normalize("NFKD", _compact_text(value).casefold())
            return "".join(char for char in text if not unicodedata.combining(char))

        ecommerce = searchable(transcript[2].get("answer"))
        self.assertTrue(any(term in ecommerce for term in ("rekabet", "musteri", "pazar")))
        capability = searchable(transcript[3].get("answer"))
        for term in ("etiket", "iade", "kargo"):
            self.assertIn(term, capability)

        joined = json.dumps(artifact, ensure_ascii=False)
        for forbidden in ("C:/Users", "C:\\Users", "D:\\OrderScoutAI", "test.sqlite3", "api_key", "api_secret"):
            self.assertNotIn(forbidden, joined)

    def test_persisted_gemini_web_search_proves_live_relevant_grounded_answer(self) -> None:
        path = self._gemini_web_artifact_root() / "live-public-web-search-quality.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        provider = _compact_text(artifact.get("provider")).casefold()
        transcript = artifact.get("transcript") or []
        gates = (artifact.get("extra") or {}).get("quality_gates") or {}

        self.assertIn("provider=gemini", provider)
        self.assertEqual(artifact.get("turn_count"), 1)
        self.assertEqual(len(transcript), 1)
        for gate in (
            "real_llm",
            "real_network_search",
            "private_data_not_sent",
            "has_results",
            "official_source_present",
            "visible_source_url",
            "topic_relevant",
            "substantive_answer",
        ):
            self.assertTrue(gates.get(gate), gate)

        row = transcript[0]
        self.assertEqual(row.get("tool"), "web.search")
        tool_result = row.get("tool_result") or {}
        self.assertTrue(tool_result.get("query_sent"))
        self.assertFalse(tool_result.get("blocked_private_data"))
        results = tool_result.get("results") or []
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue(any("ticaret.gov.tr" in _compact_text(result.get("url")) for result in results))
        answer = _compact_text(row.get("answer"))
        self.assertGreaterEqual(len(answer), 180)
        self.assertIn("Kaynaklar:", answer)
        self.assertTrue(any(_compact_text(result.get("url")) in answer for result in results))

        joined = json.dumps(artifact, ensure_ascii=False)
        for forbidden in ("C:/Users", "C:\\Users", "test.sqlite3", "api_key", "api_secret"):
            self.assertNotIn(forbidden, joined)

    def test_persisted_strengthened_web_search_proves_official_priority_and_synthesis(self) -> None:
        path = self._gemini_web_artifact_root() / "live-web-search-strengthened-quality.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        transcript = artifact.get("transcript") or []
        gates = (artifact.get("extra") or {}).get("quality_gates") or {}

        self.assertEqual(artifact.get("turn_count"), 2)
        self.assertEqual(len(transcript), 2)
        for gate in (
            "all_turns_passed",
            "official_source_priority",
            "privacy_guard",
            "visible_citations",
            "substantive_synthesis",
            "content_enrichment",
            "numeric_grounding",
            "public_only_redirects",
            "no_raw_result_dump",
        ):
            self.assertTrue(gates.get(gate), gate)

        for row in transcript:
            self.assertEqual(row.get("tool"), "web.search", row)
            quality = row.get("quality") or {}
            self.assertTrue(all(quality.values()), row)
            tool_result = row.get("tool_result") or {}
            self.assertTrue(tool_result.get("query_sent"), row)
            self.assertFalse(tool_result.get("blocked_private_data"), row)
            results = tool_result.get("results") or []
            self.assertGreaterEqual(len(results), 3, row)
            self.assertTrue((results[0] or {}).get("official"), row)
            self.assertTrue(any(_compact_text(result.get("url")) in _compact_text(row.get("answer")) for result in results), row)
            self.assertFalse(_compact_text(row.get("answer")).startswith("Web arama sonucu:"), row)

        trendyol = transcript[0]
        trendyol_answer = _compact_text(trendyol.get("answer"))
        for term in ("getClaims", "approveClaimLineItems", "developers.trendyol.com"):
            self.assertIn(term, trendyol_answer)
        report = transcript[1]
        report_answer = _compact_text(report.get("answer"))
        for term in ("%52,2", "4,57 trilyon", "ticaret.gov.tr"):
            self.assertIn(term, report_answer)

    def test_persisted_general_web_research_matrix_proves_cross_topic_strength(self) -> None:
        path = self._gemini_web_artifact_root() / "live-general-web-research-matrix.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        transcript = artifact.get("transcript") or []
        gates = (artifact.get("extra") or {}).get("quality_gates") or {}

        self.assertEqual(artifact.get("turn_count"), 6)
        self.assertEqual(
            {row.get("category") for row in transcript},
            {"law", "tcmb", "news", "python", "product", "openai"},
        )
        for gate in (
            "all_categories_passed",
            "automatic_web_routing",
            "official_sources_when_available",
            "specialized_news_provider",
            "wikipedia_fallback",
            "multi_domain_research",
            "visible_citations",
            "natural_synthesis",
            "numeric_grounding",
            "provider_resilience",
            "official_seed_fallback",
        ):
            self.assertTrue(gates.get(gate), gate)

        by_category = {row.get("category"): row for row in transcript}
        for category, row in by_category.items():
            self.assertTrue(row.get("success"), category)
            self.assertEqual(row.get("tool"), "web.search", category)
            self.assertTrue(all((row.get("quality") or {}).values()), category)
            self.assertFalse(_compact_text(row.get("answer")).startswith("Web arama sonucu:"), category)
            self.assertGreaterEqual(len(_compact_text(row.get("answer"))), 180, category)
        self.assertTrue(any("resmigazete.gov.tr" in domain for domain in by_category["law"].get("domains") or []))
        self.assertTrue(any("tcmb.gov.tr" in domain for domain in by_category["tcmb"].get("domains") or []))
        self.assertTrue(any("docs.python.org" in domain for domain in by_category["python"].get("domains") or []))
        self.assertTrue(any("platform.openai.com" in domain for domain in by_category["openai"].get("domains") or []))
        product_domains = set(by_category["product"].get("domains") or [])
        self.assertIn("www.zebra.com", product_domains)
        self.assertIn("support.brother.com", product_domains)
        self.assertIn("emea.tscprinters.com", product_domains)

    def test_persisted_web_provider_recheck_proves_answer_not_only_results(self) -> None:
        path = (
            self._gemini_web_artifact_root()
            / "live-web-provider-recheck-2026-06-29.json"
        )
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(artifact.get("passed"), artifact)
        safety = dict(artifact.get("safety") or {})
        self.assertFalse(safety.get("private_order_data_sent"), safety)
        self.assertFalse(safety.get("computer_use_used"), safety)
        self.assertFalse(safety.get("packaged_exe_used"), safety)

        providers = list(artifact.get("providers") or [])
        self.assertEqual(
            {row.get("provider_code") for row in providers},
            {"gemini", "openrouter"},
        )
        for provider in providers:
            self.assertTrue(provider.get("passed"), provider)
            turns = {row.get("topic"): row for row in provider.get("turns") or []}
            self.assertEqual(set(turns), {"profit", "trendyol_cargo"})
            for turn in turns.values():
                self.assertTrue(all(dict(turn.get("checks") or {}).values()), turn)
                self.assertEqual(turn.get("tools"), ["web.search"])
                self.assertFalse(
                    _compact_text(turn.get("answer"))
                    .casefold()
                    .startswith("web arama sonucu:")
                )

            profit_answer = unicodedata.normalize(
                "NFKD",
                _compact_text(turns["profit"].get("answer")).casefold(),
            )
            profit_answer = "".join(
                char for char in profit_answer if not unicodedata.combining(char)
            ).translate(str.maketrans({"ı": "i"}))
            for term in ("maliyet", "komisyon", "kargo", "kar marji"):
                self.assertIn(term, profit_answer)
            self.assertIn("resmi", profit_answer)

            cargo_answer = _compact_text(
                turns["trendyol_cargo"].get("answer")
            ).casefold()
            self.assertIn("changecargoprovider", cargo_answer)
            self.assertIn("developers.trendyol.com", cargo_answer)
            self.assertTrue(
                "yeniden" in cargo_answer or "tekrar" in cargo_answer
            )

    def test_persisted_contextual_task_runtime_preserves_exact_chat_scope(self) -> None:
        root = Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts"
        for folder, provider_code in (
            ("gemini-orders-continuation", "provider=gemini"),
            ("openrouter-orders-continuation", "provider=openrouter"),
        ):
            path = root / folder / "live-task-runtime-contextual-chat-scope.json"
            self.assertTrue(path.exists(), path)
            artifact = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(provider_code, _compact_text(artifact.get("provider")).casefold())
            transcript = artifact.get("transcript") or []
            self.assertEqual(len(transcript), 1)
            row = transcript[0]
            plan = row.get("plan") or {}
            self.assertTrue(plan.get("contextual_history_used"), plan)
            self.assertNotIn("orders.ready_to_ship", plan.get("step_ids") or [])
            self.assertEqual(
                set(row.get("payload_order_numbers") or []),
                {"ORD-LIVE-TASK-CHAT-1", "ORD-LIVE-TASK-CHAT-2"},
            )
            self.assertNotIn("ORD-LIVE-TASK-CHAT-UNRELATED", row.get("payload_order_numbers") or [])
            runtime_context = row.get("runtime_context") or {}
            self.assertEqual(runtime_context.get("source"), "cloud")
            self.assertGreater(int(runtime_context.get("provider_id") or 0), 0)
            self.assertTrue(_compact_text(runtime_context.get("model_name")))
            self.assertNotIn("api_key", runtime_context)
            self.assertEqual(row.get("pending_action_type"), "labels.action_create_labels_from_selected_orders")
            first_pending_answer = _compact_text(row.get("first_pending_answer"))
            self.assertIn("ORD-LIVE-TASK-CHAT-1", first_pending_answer)
            self.assertIn("ORD-LIVE-TASK-CHAT-2", first_pending_answer)
            self.assertNotIn("labels.action_create_labels_from_selected_orders", first_pending_answer)
            self.assertEqual(
                row.get("second_pending_action_type"),
                "labels.mark_orders_extracted_from_label_result",
            )
            second_pending_answer = _compact_text(row.get("second_pending_answer"))
            self.assertIn("ORD-LIVE-TASK-CHAT-1", second_pending_answer)
            self.assertIn("ORD-LIVE-TASK-CHAT-2", second_pending_answer)
            self.assertNotIn("labels.mark_orders_extracted_from_label_result", second_pending_answer)
            self.assertEqual(
                set(row.get("second_payload_order_numbers") or []),
                {"ORD-LIVE-TASK-CHAT-1", "ORD-LIVE-TASK-CHAT-2"},
            )
            self.assertEqual(row.get("final_status"), "complete")
            self.assertEqual(
                set(row.get("extracted_orders") or []),
                {"ORD-LIVE-TASK-CHAT-1", "ORD-LIVE-TASK-CHAT-2"},
            )
            final_answer = _compact_text(row.get("final_answer"))
            self.assertIn("ORD-LIVE-TASK-CHAT-1", final_answer)
            self.assertIn("ORD-LIVE-TASK-CHAT-2", final_answer)
            self.assertNotIn("onay gerekiyor", final_answer.casefold())
            self.assertNotIn("onay bekliyor", final_answer.casefold())
            self.assertNotIn("kritik bekleyen", final_answer.casefold())
            self.assertTrue(any(token in final_answer.casefold() for token in ("dogrulan", "doğrulan")))
            progress_events = row.get("progress_events") or []
            progress_phases = [event.get("phase") for event in progress_events]
            for phase in (
                "planned",
                "step_started",
                "step_completed",
                "pending_approval",
                "execute_started",
                "execute_completed",
                "completed",
            ):
                self.assertIn(phase, progress_phases)
            self.assertGreaterEqual(progress_phases.count("pending_approval"), 2)
            self.assertGreaterEqual(progress_phases.count("execute_started"), 2)
            progress_callbacks = row.get("progress_callbacks") or []
            self.assertTrue(any("Adim 1/" in _compact_text(event.get("message")) for event in progress_callbacks))
            self.assertTrue(any("dogrulandi" in _compact_text(event.get("message")) for event in progress_callbacks))

    def test_persisted_natural_compound_task_uses_recent_scope_and_completes(self) -> None:
        root = Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts"
        for folder, provider_code in (
            ("gemini-orders-continuation", "provider=gemini"),
            ("openrouter-orders-continuation", "provider=openrouter"),
        ):
            path = root / folder / "live-task-runtime-natural-compound-goal.json"
            self.assertTrue(path.exists(), path)
            artifact = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(provider_code, _compact_text(artifact.get("provider")).casefold())
            row = (artifact.get("transcript") or [])[0]
            self.assertEqual(
                (row.get("plan") or {}).get("step_ids"),
                [
                    "orders.recent",
                    "orders.labels.prepare",
                    "orders.labels.extracted.prepare",
                ],
            )
            selected = {"ORD-LIVE-NATURAL-RECENT-1", "ORD-LIVE-NATURAL-RECENT-2"}
            self.assertEqual(set(row.get("first_payload_order_numbers") or []), selected)
            self.assertEqual(set(row.get("second_payload_order_numbers") or []), selected)
            self.assertEqual(set(row.get("extracted_orders") or []), selected)
            self.assertEqual(row.get("final_status"), "complete")
            self.assertNotIn("ORD-LIVE-NATURAL-OLD", row.get("final_answer") or "")
            for order_number in selected:
                self.assertIn(order_number, row.get("first_pending_answer") or "")
                self.assertIn(order_number, row.get("second_pending_answer") or "")
                self.assertIn(order_number, row.get("final_answer") or "")

    def test_persisted_explicit_ids_task_never_broadens_scope(self) -> None:
        root = Path(__file__).resolve().parents[2] / "AI/docs/live_llm_transcripts"
        for folder, provider_code in (
            ("gemini-orders-continuation", "provider=gemini"),
            ("openrouter-orders-continuation", "provider=openrouter"),
        ):
            path = root / folder / "live-task-runtime-explicit-ids.json"
            self.assertTrue(path.exists(), path)
            artifact = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(provider_code, _compact_text(artifact.get("provider")).casefold())
            row = (artifact.get("transcript") or [])[0]
            self.assertEqual(
                (row.get("plan") or {}).get("step_ids"),
                ["orders.labels.prepare", "orders.labels.extracted.prepare"],
            )
            selected = {"ORD-LIVE-EXPLICIT-1", "ORD-LIVE-EXPLICIT-2"}
            self.assertEqual(set(row.get("first_payload_order_numbers") or []), selected)
            self.assertEqual(set(row.get("second_payload_order_numbers") or []), selected)
            self.assertEqual(set(row.get("extracted_orders") or []), selected)
            self.assertNotIn("ORD-LIVE-EXPLICIT-UNRELATED", row.get("final_answer") or "")
            for order_number in selected:
                self.assertIn(order_number, row.get("first_pending_answer") or "")
                self.assertIn(order_number, row.get("second_pending_answer") or "")

    def test_persisted_gemini_task_runtime_artifacts_prove_agentic_loop_quality(self) -> None:
        root = self._artifact_root()
        expected_files = {
            "live-task-runtime-bulk-cargo-change.json",
            "live-task-runtime-cargo-change.json",
            "live-task-runtime-label-ready-orders.json",
            "live-task-runtime-mark-extracted.json",
            "live-task-runtime-fetch-sync.json",
            "live-task-runtime-operation-overview.json",
            "live-task-runtime-profit-export.json",
            "live-task-runtime-ready-full-context.json",
            "live-task-runtime-return-approval.json",
            "live-task-runtime-stale-cleanup.json",
            "live-task-runtime-stale-restore.json",
        }
        actual_files = {path.name for path in root.glob("live-task-runtime-*.json")}
        self.assertEqual(actual_files, expected_files)
        artifacts = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in root.glob("live-task-runtime-*.json")}
        joined = "\n".join(json.dumps(value, ensure_ascii=False) for value in artifacts.values())
        for forbidden in ("C:/Users", "C:\\Users", "AIza", "test.sqlite3", "db_name="):
            self.assertNotIn(forbidden, joined)

        label = artifacts["live-task-runtime-label-ready-orders.json"]["transcript"][0]
        self.assertEqual((label.get("plan") or {}).get("step_ids"), ["orders.ready_to_ship", "orders.labels.prepare"])
        self.assertEqual(label.get("pending_action_type"), "labels.action_create_labels_from_selected_orders")
        self.assertEqual(set(label.get("payload_order_numbers") or []), {"ORD-LIVE-TASK-READY-1", "ORD-LIVE-TASK-READY-2"})
        self.assertEqual(label.get("resume_status"), "complete")
        self.assertTrue((label.get("execute_verify") or {}).get("verified"))

        extracted = artifacts["live-task-runtime-mark-extracted.json"]["transcript"][0]
        self.assertEqual((extracted.get("plan") or {}).get("step_ids"), ["orders.ready_to_ship", "orders.labels.extracted.prepare"])
        self.assertEqual(extracted.get("pending_action_type"), "labels.mark_orders_extracted_from_label_result")
        self.assertEqual(set(extracted.get("payload_order_numbers") or []), {"ORD-LIVE-TASK-EXTRACTED-1", "ORD-LIVE-TASK-EXTRACTED-2"})
        self.assertEqual(extracted.get("resume_status"), "complete")
        self.assertTrue((extracted.get("execute_verify") or {}).get("verified"))
        self.assertEqual((extracted.get("execute_verify") or {}).get("verified_by"), "order_header_is_extracted")

        fetch = artifacts["live-task-runtime-fetch-sync.json"]["transcript"][0]
        self.assertEqual((fetch.get("plan") or {}).get("step_ids"), ["orders.fetch.prepare"])
        self.assertEqual(fetch.get("pending_action_type"), "orders.get_orders_from_companies")
        self.assertEqual(fetch.get("payload_account_count"), 1)
        self.assertEqual(fetch.get("resume_status"), "complete")
        self.assertTrue((fetch.get("execute_verify") or {}).get("verified"))
        self.assertEqual((fetch.get("execute_verify") or {}).get("save_counts"), {"orders_upserted": 1})

        return_approval = artifacts["live-task-runtime-return-approval.json"]["transcript"][0]
        self.assertEqual((return_approval.get("plan") or {}).get("step_ids"), ["returns.waiting.list", "returns.approve.prepare"])
        self.assertEqual(return_approval.get("pending_action_type"), "orders.approve_return_claim")
        self.assertEqual(return_approval.get("payload_order"), "CLAIM-LIVE-TASK-APPROVE")
        self.assertEqual(return_approval.get("resume_status"), "complete")
        self.assertTrue((return_approval.get("execute_verify") or {}).get("verified"))

        stale_cleanup = artifacts["live-task-runtime-stale-cleanup.json"]["transcript"][0]
        self.assertEqual((stale_cleanup.get("plan") or {}).get("step_ids"), ["returns.stale.mark.prepare"])
        self.assertEqual(stale_cleanup.get("pending_action_type"), "orders.mark_return_claims_stale")
        self.assertEqual(stale_cleanup.get("payload_claim_ids"), ["CLAIM-LIVE-TASK-STALE-CLEANUP"])
        self.assertEqual(stale_cleanup.get("resume_status"), "complete")
        self.assertTrue((stale_cleanup.get("execute_verify") or {}).get("verified"))

        stale_restore = artifacts["live-task-runtime-stale-restore.json"]["transcript"][0]
        self.assertEqual((stale_restore.get("plan") or {}).get("step_ids"), ["returns.stale.restore.prepare"])
        self.assertEqual(stale_restore.get("pending_action_type"), "orders.restore_return_claims_from_stale")
        self.assertEqual(stale_restore.get("payload_claim_ids"), ["CLAIM-LIVE-TASK-STALE-RESTORE"])
        self.assertEqual(stale_restore.get("resume_status"), "complete")
        self.assertTrue((stale_restore.get("execute_verify") or {}).get("verified"))

        full_context = artifacts["live-task-runtime-ready-full-context.json"]["transcript"][0]
        self.assertEqual((full_context.get("plan") or {}).get("step_ids"), ["orders.ready_to_ship", "orders.full_context"])
        self.assertEqual(full_context.get("context_order_number"), "ORD-LIVE-TASK-CONTEXT-MAHMUT")
        full_context_joined = json.dumps(full_context.get("context_items") or [], ensure_ascii=False)
        self.assertIn("Mahmut Live Task Context Urunu", full_context_joined)
        self.assertNotIn("Ayse Live Task Context Urunu", full_context_joined)

        cargo = artifacts["live-task-runtime-cargo-change.json"]["transcript"][0]
        self.assertEqual((cargo.get("plan") or {}).get("step_ids"), ["orders.ready_to_ship", "orders.cargo.change.prepare"])
        self.assertEqual(cargo.get("pending_action_type"), "orders.change_order_cargo_provider")
        self.assertEqual((cargo.get("payload") or {}).get("order"), "ORD-LIVE-TASK-CARGO-MAHMUT")
        self.assertEqual((cargo.get("payload") or {}).get("cargo_provider_code"), "ARAS")
        self.assertEqual(cargo.get("resume_status"), "complete")
        self.assertTrue((cargo.get("execute_verify") or {}).get("verified"))

        bulk_cargo = artifacts["live-task-runtime-bulk-cargo-change.json"]["transcript"][0]
        self.assertEqual((bulk_cargo.get("plan") or {}).get("step_ids"), ["orders.ready_to_ship", "orders.cargo.bulk_change.prepare"])
        self.assertEqual(bulk_cargo.get("pending_action_type"), "orders.change_orders_cargo_provider_bulk")
        self.assertEqual(set(bulk_cargo.get("payload_orders") or []), {"ORD-LIVE-TASK-BULK-CARGO-1", "ORD-LIVE-TASK-BULK-CARGO-2"})
        self.assertEqual(bulk_cargo.get("resume_status"), "complete")
        self.assertTrue((bulk_cargo.get("execute_verify") or {}).get("verified"))

        overview = artifacts["live-task-runtime-operation-overview.json"]["transcript"][0]
        self.assertEqual(
            (overview.get("plan") or {}).get("step_ids"),
            ["orders.ready_to_ship", "orders.fulfillment_risk", "returns.waiting.list"],
        )
        final_answer = _compact_text(overview.get("final_answer")).casefold()
        self.assertIn("iade", final_answer)
        self.assertTrue(any(token in final_answer for token in ("kargo", "risk", "hazir", "hazır")), final_answer)
        self.assertNotIn("kritik bekleyen is gorunmuyor", final_answer)

        profit = artifacts["live-task-runtime-profit-export.json"]["transcript"][0]
        self.assertEqual((profit.get("plan") or {}).get("step_ids"), ["orders.ready_to_ship", "orders.profit.export.prepare"])
        self.assertEqual(profit.get("pending_action_type"), "orders.action_export_order_profit_excel")
        self.assertEqual(profit.get("payload_order_number"), "ORD-LIVE-TASK-PROFIT-MAHMUT")
        self.assertEqual(profit.get("output_name"), "mahmut-live-task-profit.xlsx")
        self.assertEqual(profit.get("resume_status"), "complete")
        self.assertTrue((profit.get("execute_verify") or {}).get("verified"))

    def historical_completion_audit_references_legacy_live_evidence(self) -> None:
        root = Path(__file__).resolve().parents[2]
        audit_path = root / "AI/docs/orders_agentic_completion_audit.md"
        self.assertTrue(audit_path.exists(), audit_path)
        audit = audit_path.read_text(encoding="utf-8")
        for required in (
            "live-conversation-transcript-quality.json",
            "live-openrouter-chat-analysis-recovery.json",
            "live-action-followup-transcript-quality.json",
            "live-task-runtime-label-ready-orders.json",
            "live-task-runtime-mark-extracted.json",
            "live-task-runtime-operation-overview.json",
            "live-task-runtime-return-approval.json",
            "live-task-runtime-stale-cleanup.json",
            "live-task-runtime-ready-full-context.json",
            "live-task-runtime-cargo-change.json",
            "live-gemini-recent-old-orders-followup-print-context.json",
            "live-openrouter-recent-old-orders-followup-print-context.json",
            "live-ready-all-followup-label-context-2026-06-26.json",
            "live-ready-count-list-label-context-2026-06-26.json",
            "openrouter-orders/live-ready-all-followup-label-context-2026-06-26.json",
            "source-db-live-recheck/live-source-db-provider-conversation-recheck-2026-06-29.json",
            "source-db-live-recheck/live-reasoning-effort-provider-recheck-2026-06-29.json",
            "orders_goal_closure_latest_report.json",
            "local-best/live-local-best-conversation-quality.json",
            "local-best/live-local-gemma12b-orders-conversation-2026-06-29.json",
            "gemini-web/live-public-web-search-quality.json",
            "gemini-web/live-web-search-strengthened-quality.json",
            "gemini-web/live-general-web-research-matrix.json",
            "gemini-web/live-web-provider-recheck-2026-06-29.json",
            "teacher_review.md",
            "test_orders_agentic_parity_matrix_matches_manual_capability_inventory",
            "read: 26",
            "write: 9",
            "total: 35",
            "test_persisted_gemini_artifacts_prove_visible_answer_and_execute_quality",
            "test_persisted_gemini_task_runtime_artifacts_prove_agentic_loop_quality",
            "test_persisted_best_local_conversation_proves_raw_multi_turn_chat_quality",
            "test_persisted_gemma12b_source_db_conversation_proves_local_best_scope",
            "test_persisted_source_db_provider_recheck_proves_grounded_exact_scope",
            "test_persisted_reasoning_effort_recheck_proves_low_high_profiles",
            "test_persisted_gemini_web_search_proves_live_relevant_grounded_answer",
            "test_persisted_strengthened_web_search_proves_official_priority_and_synthesis",
            "test_persisted_general_web_research_matrix_proves_cross_topic_strength",
            "test_persisted_web_provider_recheck_proves_answer_not_only_results",
            "test_persisted_ready_all_followup_label_context_proves_unicode_scope",
            "test_main_source_ai_builder_returns_current_clickable_chat_tab",
            "test_chat_surface_layout_contract_keeps_readable_messages_and_inline_approval",
            "test_inline_approval_card_click_executes_active_action",
            "test_inline_approval_card_click_cancels_without_execute_and_stale_card_is_inert",
            "execute_staging_marketplace_operation",
            "execute_staging_marketplace_evidence_run",
            "AI.processors.staging_marketplace_evidence_cli --mode plan",
            "staging_marketplace_external_proof_template",
            "proof-template",
            "attach_staging_marketplace_external_proof",
            "verify_staging_marketplace_evidence_artifact",
            "external_verification",
            "test_staging_marketplace_runbook_requires_full_external_proof_match",
            "AI.processors.staging_marketplace_evidence_cli",
            "orders_staging_marketplace_evidence_runbook.md",
            "staging-marketplace/README.md",
            "web.search",
            "test_public_marketplace_rule_question_routes_to_web_search",
            "test_web_search_tool_blocks_private_order_identifiers_without_calling_search",
            "ORDERSCOUT_ALLOW_STAGING_MARKETPLACE_MUTATION",
            "orders_agentic_goal_closure_checklist.json",
            "AI.processors.orders_goal_closure_cli",
            "staging_inputs",
            "next_actions",
            "--staging-evidence-dir",
            "--report-path",
            "test_orders_goal_closure_latest_regression.py",
            "labels_agentic_parity_matrix.md",
            "orders-ready-selection-followup-failure-2026-07-15.json",
            "orders_ready_selection_followup_2026_07_15",
            "test_label_execute_exports_word_file_when_payload_is_available",
            "test_label_execute_verifies_all_selected_orders_above_twenty_in_docx",
            "test_label_verify_rejects_docx_missing_expected_order_number",
            "live-source-db-ready-label-execute-docx-2026-06-26.json",
            "test_task_runtime_label_execute_keeps_docx_content_verify_details",
            "historical live task label artifact proves planning/exact-id approval resume only",
            "DOCX-content proof is the source-DB artifact and the task-runtime regression above",
            "selected reasoning/thinking profile",
            "test_cloud_orders_task_runtime_context_keeps_reasoning_effort",
            "test_gemini_25_chat_applies_thinking_budget_from_reasoning_effort",
            "test_openrouter_client_sends_selected_reasoning_effort_for_supported_model",
            "current_closure_evidence.method=source_offscreen_widget_tests",
            "visual automation fields as historical context",
            "Current closure scope is Orders-only",
            "Stock, Finance, Listing, Logistics, and Marketplaces evidence in this repository is historical or future-domain preparation",
            "without packaged exe or Computer Use",
            "Historical 22-Section Baseline",
            "orders-free-model-acceptance-catalog-2026-07-05.json",
            "Current status: **READY",
            "orders-source-ui-scope-failure-2026-07-06.md",
            "live-orders-source-ui-acceptance-2026-07-06.audit.json",
            "Gemini 2.5 Flash Lite",
            "Gemini 3.5 Flash",
            "OpenRouter GPT-OSS 120B",
            "ready_to_complete=true",
            "no unresolved blockers",
        ):
            self.assertIn(required, audit)

    def historical_goals_contract_maps_to_pre_reset_closure_scope(self) -> None:
        root = Path(__file__).resolve().parents[2]
        goals_path = root / "AI/docs/goals.md"
        checklist_path = root / "AI/docs/orders_agentic_goal_closure_checklist.json"
        self.assertTrue(goals_path.exists(), goals_path)
        self.assertTrue(checklist_path.exists(), checklist_path)

        goals = goals_path.read_text(encoding="utf-8")
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        headings = re.findall(r"^##\s+(\d+)\.\s+(.+)$", goals, flags=re.MULTILINE)
        self.assertEqual([int(number) for number, _ in headings], list(range(1, 22)))

        heading_text = "\n".join(title for _, title in headings)
        for required_heading in (
            "Ürün Vizyonu",
            "Değişmez Ürün İlkeleri",
            "Domain Sahipliği",
            "Tool ve Operasyon",
            "Agent Çalışma Döngüsü",
            "Structured Context",
            "Veri Doğruluğu",
            "Bütün LLM'lerle",
            "Web Search",
            "Güvenlik, Risk",
            "Trendyol Production",
            "AI Chat ve Model Hub",
            "İlk Tam Referans",
            "Bağlayıcı Orders Regresyonları",
            "Test ve Kanıt Stratejisi",
            "Güncel Durum",
            "Uygulama Sırası",
            "Orders Kilometre Taşı",
            "AI Domaininin Nihai",
            "Çalışma Disiplini",
        ):
            self.assertIn(required_heading, heading_text)

        current_scope = set(checklist.get("current_orders_scope_required_items") or [])
        items = {row.get("id"): row for row in checklist.get("required_items") or []}
        required_scope = {
            "natural_chat",
            "tool_gating",
            "autonomous_multi_step_routing",
            "orders_manual_parity",
            "context_preservation",
            "task_progress_visibility",
            "task_runtime_continuity",
            "approval_execute_verify_audit",
            "labels_agentic_parity",
            "live_llm_visible_quality",
            "local_model_tiered_eval",
            "inline_approval_ui",
            "source_ui",
            "source_ui_real_conversation_reproduction",
            "web_search_privacy",
            "goal_closure_gate",
            "source_data_risky_action_acceptance",
            "staging_marketplace_guard",
        }
        active_required_scope = required_scope - {"staging_marketplace_guard"}
        self.assertTrue(
            active_required_scope <= current_scope,
            sorted(active_required_scope - current_scope),
        )
        self.assertNotIn("staging_marketplace_guard", current_scope)
        self.assertEqual(
            items["staging_marketplace_guard"].get("status"),
            "deferred_external",
        )
        self.assertTrue(required_scope <= set(items), sorted(required_scope - set(items)))

        goal_section_map = {
            "natural chat": {"natural_chat", "tool_gating", "live_llm_visible_quality"},
            "codex task loop": {
                "autonomous_multi_step_routing",
                "task_progress_visibility",
                "task_runtime_continuity",
                "approval_execute_verify_audit",
            },
            "orders parity": {"orders_manual_parity", "labels_agentic_parity"},
            "context and selected records": {"context_preservation"},
            "deterministic grounding": {"context_preservation", "live_llm_visible_quality"},
            "atomic dry wrappers": {"orders_manual_parity", "labels_agentic_parity"},
            "risky action lifecycle": {"approval_execute_verify_audit", "inline_approval_ui"},
            "chat ui": {"source_ui", "inline_approval_ui"},
            "real source ui recovery": {"source_ui_real_conversation_reproduction"},
            "web search": {"web_search_privacy"},
            "providers and reasoning": {"task_runtime_continuity", "local_model_tiered_eval"},
            "live source data and human review": {
                "live_llm_visible_quality",
                "source_data_risky_action_acceptance",
                "goal_closure_gate",
            },
            "completion gate": {"goal_closure_gate"},
        }
        for label, expected_items in goal_section_map.items():
            missing = sorted(expected_items - current_scope)
            self.assertEqual(missing, [], label)
            for item_id in expected_items:
                self.assertIn(item_id, items, label)
                self.assertTrue(items[item_id].get("requirement"), item_id)
                self.assertTrue(items[item_id].get("evidence"), item_id)

        for non_order_item in (
            "stock_agentic_parity",
            "finance_agentic_parity",
            "logistics_agentic_parity",
            "listing_agentic_parity",
            "marketplaces_agentic_parity",
            "cross_domain_agentic_parity",
        ):
            self.assertNotIn(non_order_item, current_scope)

        closure_evidence = set(items["goal_closure_gate"].get("evidence") or [])
        self.assertIn("test_goals_contract_maps_to_orders_closure_scope_and_evidence", closure_evidence)
        self.assertEqual(checklist.get("overall_status"), "ready")
        self.assertEqual(checklist.get("current_focus"), "orders_only")
        self.assertEqual(items["staging_marketplace_guard"].get("status"), "deferred_external")
        self.assertNotIn("staging_marketplace_guard", checklist.get("blocking_items") or [])
        self.assertEqual(checklist.get("blocking_items") or [], [])
        self.assertEqual(items["long_adaptive_conversation"].get("status"), "proven")
        section_audit = checklist.get("goals_section_audit") or []
        self.assertTrue(checklist.get("goals_section_audit_required"))
        self.assertEqual([row.get("section") for row in section_audit], list(range(1, 22)))
        self.assertEqual(
            [row.get("title") for row in section_audit],
            [title for _, title in headings],
        )
        statuses_by_section = {row.get("section"): row.get("status") for row in section_audit}
        self.assertEqual(statuses_by_section[9], "proven_for_orders_scope")
        self.assertEqual(statuses_by_section[13], "proven_for_orders_scope")
        self.assertEqual(statuses_by_section[15], "proven_for_orders_scope")
        self.assertEqual(section_audit[20].get("status"), "proven_for_orders_scope")
        regression_section = next(row for row in section_audit if row.get("section") == 15)
        self.assertIn(
            "user-reproductions/orders-ready-selection-followup-failure-2026-07-15.json",
            regression_section.get("evidence") or [],
        )
        self.assertTrue(all(row.get("evidence") for row in section_audit))
        self.assertIn("2026-07-15 gerçek kullanıcı reprodüksiyonu", goals)
        self.assertIn("Tek başına aşağıdakiler tamamlanma kanıtı değildir", goals)
        self.assertIn("Tool'un doğru seçilmesi", goals)
        self.assertIn("50/60/100/200+", goals)

    def historical_free_model_catalog_and_long_human_artifacts(self) -> None:
        root = Path(__file__).resolve().parents[2]
        human_root = root / "AI/docs/live_llm_transcripts/human-directed"
        catalog_path = human_root / "orders-free-model-acceptance-catalog-2026-07-05.json"
        self.assertTrue(catalog_path.exists(), catalog_path)
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertFalse(catalog.get("secrets_included"))
        self.assertEqual(catalog.get("minimum_human_turns"), 20)

        providers = {
            row.get("provider_code"): row
            for row in catalog.get("providers") or []
        }
        self.assertEqual(set(providers), {"gemini", "openrouter"})
        self.assertEqual(
            {
                "gemini": {
                    "model_count": 39,
                    "chat_candidate_count": 20,
                    "long_human_passed_count": 9,
                    "currently_unavailable_or_quota_limited_count": 11,
                },
                "openrouter": {
                    "model_count": 23,
                    "chat_candidate_count": 22,
                    "long_human_passed_count": 3,
                    "currently_unavailable_or_quota_limited_count": 19,
                },
            },
            {
                code: {
                    "model_count": provider.get("model_count"),
                    "chat_candidate_count": provider.get("chat_candidate_count"),
                    "long_human_passed_count": provider.get("long_human_passed_count"),
                    "currently_unavailable_or_quota_limited_count": provider.get(
                        "currently_unavailable_or_quota_limited_count"
                    ),
                }
                for code, provider in providers.items()
            },
        )
        for provider in providers.values():
            self.assertTrue(provider.get("catalog_success"))
            self.assertTrue(provider.get("current_accessible_acceptance_complete"))
            self.assertEqual(provider.get("accessible_pending_long_human_count"), 0)
            chat_rows = [
                row
                for row in provider.get("models") or []
                if row.get("classification") != "excluded_specialized_non_chat"
            ]
            self.assertTrue(chat_rows)
            self.assertTrue(
                all(
                    row.get("acceptance_status")
                    in {"long_human_passed", "currently_unavailable_or_quota_limited"}
                    for row in chat_rows
                )
            )

        expected_cloud_models = {
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.5-flash",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemma-4-26b-a4b-it",
            "openai/gpt-oss-120b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        }
        cloud_pass_rows = [
            row
            for provider in providers.values()
            for row in provider.get("models") or []
            if row.get("acceptance_status") == "long_human_passed"
        ]
        self.assertEqual(
            {row.get("id") for row in cloud_pass_rows},
            expected_cloud_models,
        )

        artifact_names = {
            (row.get("human_evidence") or {}).get("artifact")
            for row in cloud_pass_rows
        }
        artifact_names.update(
            {
                "live-orders-human-local-gemma4-e4b-2026-07-05.json",
                "live-orders-human-local-llama3.2-1b-2026-07-05.json",
            }
        )
        self.assertNotIn(None, artifact_names)
        for artifact_name in sorted(artifact_names):
            artifact_path = human_root / artifact_name
            self.assertTrue(artifact_path.exists(), artifact_path)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            turn_count = int(artifact.get("turn_count") or 0)
            turns = list(artifact.get("turns") or [])
            review = dict(artifact.get("human_review") or {})
            contract = dict(artifact.get("evaluation_contract") or {})
            self.assertTrue(artifact.get("passed"), artifact_name)
            self.assertGreaterEqual(turn_count, 20, artifact_name)
            self.assertEqual(len(turns), turn_count, artifact_name)
            self.assertEqual(review.get("reviewed_turn_count"), turn_count, artifact_name)
            self.assertEqual(
                (review.get("final_assessment") or {}).get("status"),
                "pass",
                artifact_name,
            )
            self.assertTrue(
                contract.get("human_selects_each_next_prompt_after_reading_previous_turn"),
                artifact_name,
            )
            self.assertFalse(contract.get("fixed_prompt_list"), artifact_name)
            self.assertTrue(contract.get("continue_beyond_minimum_until_confident"), artifact_name)
            self.assertFalse(contract.get("production_marketplace_mutations_allowed"), artifact_name)
            self.assertTrue(
                all(turn.get("next_prompt_selection_reason") for turn in turns),
                artifact_name,
            )
            self.assertTrue(
                all((turn.get("human_review") or {}).get("status") for turn in turns),
                artifact_name,
            )
            self.assertTrue(
                any(turn.get("exact_model_responded") is True for turn in turns),
                artifact_name,
            )
            self.assertFalse(
                any((turn.get("runtime_plan") or {}).get("fallback_used") is True for turn in turns),
                artifact_name,
            )

    def historical_goal_closure_checklist_ready_before_phase8_reset(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/orders_agentic_goal_closure_checklist.json"
        self.assertTrue(path.exists(), path)
        checklist = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(checklist.get("overall_status"), "ready")
        self.assertEqual(checklist.get("current_focus"), "orders_only")
        self.assertIn("Orders", checklist.get("scope_note") or "")
        current_scope = set(checklist.get("current_orders_scope_required_items") or [])
        items = {row.get("id"): row for row in checklist.get("required_items") or []}
        self.assertIn("staging_marketplace_guard", items)
        self.assertIn("labels_agentic_parity", items)
        self.assertIn("orders_manual_parity", items)
        self.assertIn("task_runtime_continuity", items)
        self.assertIn("local_model_tiered_eval", items)
        self.assertIn("inline_approval_ui", items)
        self.assertIn("web_search_privacy", items)
        self.assertIn("goal_closure_gate", items)
        self.assertIn("source_data_risky_action_acceptance", items)
        self.assertIn("orders_manual_parity", current_scope)
        self.assertIn("approval_execute_verify_audit", current_scope)
        self.assertIn("source_ui", current_scope)
        self.assertIn("source_ui_real_conversation_reproduction", current_scope)
        self.assertIn("local_model_tiered_eval", current_scope)
        self.assertIn("inline_approval_ui", current_scope)
        self.assertIn("web_search_privacy", current_scope)
        self.assertIn("goal_closure_gate", current_scope)
        self.assertIn(
            "source_data_risky_action_acceptance",
            current_scope,
        )
        for non_order_item in (
            "stock_agentic_parity",
            "finance_agentic_parity",
            "logistics_agentic_parity",
            "listing_agentic_parity",
            "marketplaces_agentic_parity",
            "cross_domain_agentic_parity",
        ):
            self.assertNotIn(non_order_item, current_scope)
        self.assertEqual(items["staging_marketplace_guard"].get("status"), "deferred_external")
        self.assertIn("reasoning/thinking profile", items["task_runtime_continuity"].get("requirement") or "")
        continuity_evidence = set(items["task_runtime_continuity"].get("evidence") or [])
        self.assertIn("test_cloud_orders_task_runtime_context_keeps_reasoning_effort", continuity_evidence)
        self.assertIn("test_openrouter_client_sends_selected_reasoning_effort_for_supported_model", continuity_evidence)
        self.assertIn("test_gemini_25_chat_applies_thinking_budget_from_reasoning_effort", continuity_evidence)
        self.assertEqual(items["labels_agentic_parity"].get("status"), "proven")
        self.assertEqual(items["local_model_tiered_eval"].get("status"), "proven")
        self.assertEqual(items["inline_approval_ui"].get("status"), "proven")
        self.assertEqual(items["web_search_privacy"].get("status"), "proven")
        self.assertEqual(items["goal_closure_gate"].get("status"), "proven")
        self.assertEqual(
            items["source_data_risky_action_acceptance"].get("status"),
            "proven",
        )
        source_data_evidence = set(
            items["source_data_risky_action_acceptance"].get(
                "evidence"
            )
            or []
        )
        self.assertIn(
            "source-db-live-recheck/live-source-db-fetch-recheck-2026-07-01.json",
            source_data_evidence,
        )
        self.assertIn(
            "test_persisted_source_db_stale_cycle_is_verified_and_restored",
            source_data_evidence,
        )
        orders_manual_evidence = set(items["orders_manual_parity"].get("evidence") or [])
        self.assertIn("orders_agentic_parity_matrix.md", orders_manual_evidence)
        self.assertIn("test_orders_agentic_parity_matrix_matches_manual_capability_inventory", orders_manual_evidence)
        self.assertIn("operation_coverage_report", orders_manual_evidence)
        inline_ui_evidence = set(items["inline_approval_ui"].get("evidence") or [])
        self.assertIn("test_chat_surface_layout_contract_keeps_readable_messages_and_inline_approval", inline_ui_evidence)
        source_ui_evidence = set(items["source_ui"].get("evidence") or [])
        self.assertIn("test_chat_surface_layout_contract_keeps_readable_messages_and_inline_approval", source_ui_evidence)
        self.assertNotIn("staging_marketplace_guard", checklist.get("blocking_items") or [])
        self.assertNotIn("long_adaptive_conversation", checklist.get("blocking_items") or [])
        self.assertNotIn("local_model_tiered_eval", checklist.get("blocking_items") or [])
        self.assertNotIn("inline_approval_ui", checklist.get("blocking_items") or [])
        self.assertNotIn("cross_domain_agentic_parity", checklist.get("blocking_items") or [])
        self.assertEqual(set(checklist.get("blocking_items") or []), set())
        self.assertEqual(
            items["source_ui_real_conversation_reproduction"].get("status"),
            "proven",
        )
        self.assertEqual(
            items["source_ui_full_history_analysis_reproduction"].get("status"),
            "proven",
        )
        self.assertIn(
            "seven-record",
            items["source_ui_real_conversation_reproduction"].get("requirement") or "",
        )
        source_ui_reproduction_evidence = set(
            items["source_ui_real_conversation_reproduction"].get("evidence") or []
        )
        for artifact_name in (
            "user-reproductions/orders-ready-selection-followup-failure-2026-07-15.json",
            "user-reproductions/orders-ready-reacceptance-gemini-2.5-exact-2026-07-15.json",
            "human-directed/live-orders-human-gemini-3.5-flash-100msg-2026-07-15.json",
            "user-reproductions/orders-ready-reacceptance-openrouter-gemma4-2026-07-15.json",
            "user-reproductions/orders-ready-reacceptance-local-gemma4-e4b-2026-07-15.json",
            "user-reproductions/live-orders-source-ui-acceptance-attempt-13-gemini-2.5-flash-lite-2026-07-06.json",
            "user-reproductions/live-orders-source-ui-acceptance-gemini-3.5-flash-attempt-2-2026-07-06.json",
            "user-reproductions/live-orders-source-ui-acceptance-openrouter-gpt-oss-120b-2026-07-06.json",
            "user-reproductions/live-orders-source-ui-idempotent-docx-readback-gemini-2.5-flash-lite-2026-07-06.json",
            "user-reproductions/live-orders-source-ui-recovery-gemini-2.5-flash-lite-2026-07-06.docx-audit.json",
            "user-reproductions/live-orders-source-ui-acceptance-2026-07-06.audit.json",
            "offscreen-source-app/full-contract-gemini-2.5-flash-lite-attempt-4-2026-07-11.json",
            "offscreen-source-app/full-contract-gemini-2.5-flash-2026-07-12.json",
            "offscreen-source-app/full-contract-gemini-3.5-flash-2026-07-12.json",
            "offscreen-source-app/full-contract-openrouter-gpt-oss-120b-2026-07-12.json",
        ):
            self.assertIn(artifact_name, source_ui_reproduction_evidence)
        self.assertEqual(items["long_adaptive_conversation"].get("status"), "proven")
        self.assertIn("controlled Trendyol staging/sandbox account", items["staging_marketplace_guard"].get("missing_to_complete") or "")
        staging_evidence = set(items["staging_marketplace_guard"].get("evidence") or [])
        self.assertIn("execute_staging_marketplace_evidence_run", staging_evidence)
        self.assertIn("staging_marketplace_external_proof_template", staging_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli --mode proof-template", staging_evidence)
        self.assertIn("attach_staging_marketplace_external_proof", staging_evidence)
        self.assertIn("verify_staging_marketplace_evidence_artifact", staging_evidence)
        self.assertIn("external_verification", staging_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli", staging_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli --mode plan", staging_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli --mode doctor", staging_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli --mode manifest", staging_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli --mode verify-manifest", staging_evidence)
        self.assertIn("orders_staging_marketplace_evidence_runbook.md", staging_evidence)
        self.assertIn("staging-marketplace/README.md", staging_evidence)
        self.assertIn("full external_verification proof content mismatch rejection", staging_evidence)
        self.assertIn("placeholder input rejection", staging_evidence)
        self.assertIn("test_staging_marketplace_runbook_requires_full_external_proof_match", staging_evidence)
        self.assertIn("test_staging_marketplace_evidence_cli_rejects_placeholder_inputs", staging_evidence)
        web_evidence = set(items["web_search_privacy"].get("evidence") or [])
        self.assertIn("web.search", web_evidence)
        self.assertIn("test_public_marketplace_rule_question_routes_to_web_search", web_evidence)
        self.assertIn("test_web_search_tool_blocks_private_order_identifiers_without_calling_search", web_evidence)
        self.assertIn("test_profit_calculation_web_query_removes_conversation_noise", web_evidence)
        self.assertIn("test_web_search_marks_public_only_profit_sources_with_authority_warning", web_evidence)
        self.assertIn("test_web_synthesis_prompt_blocks_unsourced_volatile_commerce_claims", web_evidence)
        self.assertIn("gemini-web/live-public-web-search-quality.json", web_evidence)
        self.assertIn("test_persisted_gemini_web_search_proves_live_relevant_grounded_answer", web_evidence)
        self.assertIn("gemini-web/live-web-search-strengthened-quality.json", web_evidence)
        self.assertIn("test_persisted_strengthened_web_search_proves_official_priority_and_synthesis", web_evidence)
        self.assertIn("gemini-web/live-general-web-research-matrix.json", web_evidence)
        self.assertIn("test_persisted_general_web_research_matrix_proves_cross_topic_strength", web_evidence)
        self.assertIn("gemini-web/live-web-provider-recheck-2026-06-29.json", web_evidence)
        self.assertIn("test_persisted_web_provider_recheck_proves_answer_not_only_results", web_evidence)
        closure_evidence = set(items["goal_closure_gate"].get("evidence") or [])
        self.assertIn("AI.processors.orders_goal_closure_cli", closure_evidence)
        self.assertIn("AI.processors.orders_goal_closure_cli --require-complete", closure_evidence)
        self.assertIn("AI.processors.orders_goal_closure_cli --report-path", closure_evidence)
        self.assertIn("AI.processors.orders_goal_closure_cli --staging-evidence-dir", closure_evidence)
        self.assertIn("AI.processors.orders_goal_closure_cli --staging-manifest-path", closure_evidence)
        self.assertIn("AI.processors.orders_goal_closure_cli --apply-verified-staging-evidence", closure_evidence)
        self.assertIn("AI.processors.staging_marketplace_evidence_cli --mode plan", closure_evidence)
        self.assertIn("test_goal_closure_cli_accepts_resolved_real_source_ui_regression", closure_evidence)
        self.assertIn("test_staging_marketplace_evidence_cli_plan_outputs_safe_command_package", closure_evidence)
        self.assertIn("test_goal_closure_cli_can_turn_ready_with_verified_staging_evidence", closure_evidence)
        local_evidence = set(items["local_model_tiered_eval"].get("evidence") or [])
        self.assertIn("live-local-orders-tiered-eval.json", local_evidence)
        self.assertIn("local-best/live-local-gemma12b-orders-conversation-2026-06-29.json", local_evidence)
        self.assertIn("test_persisted_gemma12b_source_db_conversation_proves_local_best_scope", local_evidence)
        context_evidence = set(items["context_preservation"].get("evidence") or [])
        self.assertIn("live-gemini-recent-old-orders-followup-print-context.json", context_evidence)
        self.assertIn("live-openrouter-recent-old-orders-followup-print-context.json", context_evidence)
        self.assertIn("live-ready-all-followup-label-context-2026-06-26.json", context_evidence)
        self.assertIn("live-ready-count-list-label-context-2026-06-26.json", context_evidence)
        self.assertIn("openrouter-orders/live-ready-all-followup-label-context-2026-06-26.json", context_evidence)
        self.assertIn("source-db-live-recheck/live-source-db-provider-conversation-recheck-2026-06-29.json", context_evidence)
        self.assertIn("test_persisted_source_db_provider_recheck_proves_grounded_exact_scope", context_evidence)
        continuity_evidence = set(items["task_runtime_continuity"].get("evidence") or [])
        self.assertIn("source-db-live-recheck/live-reasoning-effort-provider-recheck-2026-06-29.json", continuity_evidence)
        self.assertIn("test_persisted_reasoning_effort_recheck_proves_low_high_profiles", continuity_evidence)
        visible_quality_evidence = set(items["live_llm_visible_quality"].get("evidence") or [])
        self.assertIn("live-gemini-recent-old-orders-followup-print-context.json", visible_quality_evidence)
        self.assertIn("live-openrouter-recent-old-orders-followup-print-context.json", visible_quality_evidence)
        self.assertIn("live-ready-all-followup-label-context-2026-06-26.json", visible_quality_evidence)
        self.assertIn("live-ready-count-list-label-context-2026-06-26.json", visible_quality_evidence)
        self.assertIn("source-db-live-recheck/live-source-db-provider-conversation-recheck-2026-06-29.json", visible_quality_evidence)
        self.assertIn("local-best/live-local-gemma12b-orders-conversation-2026-06-29.json", visible_quality_evidence)
        self.assertIn("test_persisted_source_db_provider_recheck_proves_grounded_exact_scope", visible_quality_evidence)
        self.assertIn("test_persisted_gemma12b_source_db_conversation_proves_local_best_scope", visible_quality_evidence)
        self.assertIn("openrouter-orders/live-ready-all-followup-label-context-2026-06-26.json", visible_quality_evidence)
        self.assertNotIn(
            "full_source_app acceptance",
            " ".join(checklist.get("next_evidence_needed") or []),
        )
        self.assertIn(
            "deferred_external",
            " ".join(checklist.get("next_evidence_needed") or []),
        )
        self.assertNotIn("local listing stock/cost/cache writes", items["listing_agentic_parity"].get("missing_to_complete") or "")
        self.assertNotIn("natural-language execute bridge", items["listing_agentic_parity"].get("missing_to_complete") or "")
        self.assertIn("controlled staging account", items["listing_agentic_parity"].get("missing_to_complete") or "")
        self.assertNotIn("missing_to_complete", items["marketplaces_agentic_parity"])
        self.assertNotIn("missing_to_complete", items["logistics_agentic_parity"])

        artifact_root = self._artifact_root()
        live_root = artifact_root.parent
        referenced_artifacts = {
            evidence
            for row in items.values()
            for evidence in list(row.get("evidence") or [])
            if str(evidence).endswith(".json")
        }
        missing = sorted(
            name
            for name in referenced_artifacts
            if not (artifact_root / name).exists() and not (live_root / name).exists()
        )
        self.assertEqual(missing, [])

        doc_root = root / "AI/docs"
        referenced_docs = {
            evidence
            for row in items.values()
            for evidence in list(row.get("evidence") or [])
            if str(evidence).endswith(".md")
        }
        missing_docs = sorted(
            name
            for name in referenced_docs
            if not (doc_root / name).exists() and not (artifact_root / name).exists() and not (live_root / name).exists()
        )
        self.assertEqual(missing_docs, [])

    def historical_goal_closure_cli_accepts_pre_reset_source_ui_regression(self) -> None:
        root = Path(__file__).resolve().parents[2]
        checklist_path = root / "AI/docs/orders_agentic_goal_closure_checklist.json"

        result = orders_goal_closure_cli.evaluate_orders_goal_closure(
            checklist_path=checklist_path
        )
        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertTrue(data.get("ready_to_complete"), data)
        self.assertEqual(data.get("overall_status"), "ready")
        self.assertEqual(data.get("unresolved_blockers") or [], [])
        self.assertEqual(data.get("problems") or [], [])
        regression_validation = data.get("real_user_regression_validation") or {}
        self.assertTrue(regression_validation.get("valid"), regression_validation)
        self.assertEqual(
            regression_validation.get("unresolved_ids"),
            [],
        )
        next_action_ids = {row.get("id") for row in data.get("next_actions") or []}
        self.assertNotIn("resolve_latest_real_user_regressions", next_action_ids)

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_path = Path(tmp_dir) / "closure-report.json"
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = orders_goal_closure_cli.main(
                    [
                        "--checklist-path",
                        str(checklist_path),
                        "--report-path",
                        str(report_path),
                        "--require-complete",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertTrue((payload.get("data") or {}).get("ready_to_complete"))
        self.assertTrue((report_payload.get("data") or {}).get("ready_to_complete"))
        report_text = json.dumps(report_payload, ensure_ascii=False)
        self.assertNotIn("11413670522", report_text)
        self.assertNotIn("7330034391471658", report_text)

    def test_staging_marketplace_evidence_cli_plan_outputs_safe_command_package(self) -> None:
        key = "orders-staging-cargo-plan-001"
        account_id = "123456789"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            action_path = tmp / "prepared-action.json"
            audit_path = tmp / f"{key}.audit.jsonl"
            evidence_path = tmp / f"{key}.json"
            plan_path = tmp / f"{key}.plan.json"
            proof_path = tmp / f"{key}.external-proof.json"
            manifest_path = tmp / f"{key}.manifest.json"
            action_path.write_text(
                json.dumps({"action_type": "orders.change_order_cargo_provider"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "plan",
                        "--plan-path",
                        str(plan_path),
                        "--action-file",
                        str(action_path),
                        "--idempotency-key",
                        key,
                        "--staging-reason",
                        "controlled staging cargo provider proof",
                        "--staging-account-id",
                        account_id,
                        "--audit-path",
                        str(audit_path),
                        "--evidence-path",
                        str(evidence_path),
                        "--proof-template-path",
                        str(proof_path),
                        "--manifest-path",
                        str(manifest_path),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload.get("success"), payload)
            data = payload.get("data") or {}
            self.assertEqual(data.get("mode"), "plan")
            self.assertFalse(data.get("api_call_performed"))
            self.assertFalse(data.get("db_write_performed"))
            self.assertEqual(data.get("plan_path"), str(plan_path))
            self.assertTrue(plan_path.exists())
            plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan_payload.get("artifact_type"), "orders_staging_marketplace_plan")
            plan_result = plan_payload.get("result") or {}
            self.assertTrue(plan_result.get("success"), plan_payload)
            self.assertEqual((plan_result.get("data") or {}).get("mode"), "plan")
            self.assertFalse((plan_result.get("data") or {}).get("api_call_performed"))
            self.assertFalse((plan_result.get("data") or {}).get("db_write_performed"))
            self.assertEqual((data.get("paths") or {}).get("evidence_path"), str(evidence_path))
            self.assertEqual((data.get("paths") or {}).get("external_proof_path"), str(proof_path))
            self.assertIn("Run execute only in a controlled staging shell.", data.get("safety_notes") or [])
            commands = {row.get("id"): row for row in data.get("commands") or []}
            self.assertEqual(
                set(commands),
                {
                    "doctor",
                    "preflight",
                    "execute",
                    "proof_template",
                    "attach_external_proof",
                    "validate",
                    "manifest",
                    "verify_manifest",
                    "apply_closure",
                },
            )
            self.assertTrue(commands["doctor"].get("requires_env"))
            self.assertEqual(commands["doctor"].get("env"), {"ORDERSCOUT_ALLOW_STAGING_MARKETPLACE_MUTATION": "1"})
            self.assertTrue(commands["execute"].get("requires_env"))
            self.assertEqual(commands["execute"].get("env"), {"ORDERSCOUT_ALLOW_STAGING_MARKETPLACE_MUTATION": "1"})
            execute_args = commands["execute"].get("python_args") or []
            self.assertIn("--mode", execute_args)
            self.assertIn("execute", execute_args)
            self.assertIn("--action-file", execute_args)
            self.assertIn(str(action_path), execute_args)
            self.assertIn("--audit-path", execute_args)
            self.assertIn(str(audit_path), execute_args)
            self.assertIn("--evidence-path", execute_args)
            self.assertIn(str(evidence_path), execute_args)
            manifest_args = commands["manifest"].get("python_args") or []
            self.assertIn("--external-proof-file", manifest_args)
            self.assertIn(str(proof_path), manifest_args)
            closure_args = commands["apply_closure"].get("python_args") or []
            self.assertIn("AI.processors.orders_goal_closure_cli", closure_args)
            self.assertIn("--staging-evidence-dir", closure_args)
            self.assertIn(str(evidence_path.parent), closure_args)
            self.assertNotIn("--staging-evidence-path", closure_args)
            self.assertNotIn("--staging-manifest-path", closure_args)
            self.assertNotIn("--idempotency-key", closure_args)
            self.assertIn("--apply-verified-staging-evidence", closure_args)
            doctor = data.get("doctor") or {}
            self.assertIn("preflight", ((doctor.get("data") or {}).get("problems") or []))

            with patch("sys.stdout", new_callable=io.StringIO) as collision_stdout:
                collision_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "plan",
                        "--plan-path",
                        str(plan_path),
                        "--action-file",
                        str(action_path),
                        "--idempotency-key",
                        key,
                        "--staging-reason",
                        "controlled staging cargo provider proof",
                        "--staging-account-id",
                        account_id,
                        "--audit-path",
                        str(audit_path),
                        "--evidence-path",
                        str(evidence_path),
                        "--proof-template-path",
                        str(proof_path),
                        "--manifest-path",
                        str(manifest_path),
                    ]
                )
            collision_payload = json.loads(collision_stdout.getvalue())
            self.assertEqual(collision_exit_code, 2)
            self.assertFalse(collision_payload.get("success"), collision_payload)
            collision_data = collision_payload.get("data") or {}
            self.assertFalse(collision_data.get("api_call_performed"))
            self.assertFalse(collision_data.get("db_write_performed"))
            self.assertIn("plan_path_exists", collision_data.get("problems") or [])

            with patch("sys.stdout", new_callable=io.StringIO) as overwrite_stdout:
                overwrite_exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "plan",
                        "--plan-path",
                        str(plan_path),
                        "--overwrite-plan",
                        "--action-file",
                        str(action_path),
                        "--idempotency-key",
                        key,
                        "--staging-reason",
                        "controlled staging cargo provider proof",
                        "--staging-account-id",
                        account_id,
                        "--audit-path",
                        str(audit_path),
                        "--evidence-path",
                        str(evidence_path),
                        "--proof-template-path",
                        str(proof_path),
                        "--manifest-path",
                        str(manifest_path),
                    ]
                )
            overwrite_payload = json.loads(overwrite_stdout.getvalue())
            self.assertEqual(overwrite_exit_code, 0)
            self.assertTrue(overwrite_payload.get("success"), overwrite_payload)

    def test_staging_marketplace_campaign_plan_covers_all_required_actions(self) -> None:
        account_id = "123456789"
        campaign_id = "orders-staging-20260702-001"
        with tempfile.TemporaryDirectory() as tmp_dir:
            campaign_dir = Path(tmp_dir)
            plan_path = campaign_dir / f"{campaign_id}.campaign-plan.json"
            for action_type, slug in staging_marketplace_evidence_cli.STAGING_CAMPAIGN_ACTION_SPECS:
                (campaign_dir / f"{slug}.prepared-action.json").write_text(
                    json.dumps({"action_type": action_type}, ensure_ascii=False),
                    encoding="utf-8",
                )

            def _ready_doctor(args: Any) -> Any:
                action = json.loads(Path(args.action_file).read_text(encoding="utf-8"))
                return staging_marketplace_evidence_cli.Result.ok(
                    "ready",
                    close_dialog=False,
                    data={
                        "ready_for_execute": True,
                        "action_type": action.get("action_type"),
                        "api_call_performed": False,
                        "db_write_performed": False,
                    },
                )

            with (
                patch.object(staging_marketplace_evidence_cli, "_doctor_result", side_effect=_ready_doctor),
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "campaign-plan",
                        "--campaign-id",
                        campaign_id,
                        "--campaign-dir",
                        str(campaign_dir),
                        "--plan-path",
                        str(plan_path),
                        "--staging-reason",
                        "controlled three action staging proof",
                        "--staging-account-id",
                        account_id,
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload.get("success"), payload)
            data = payload.get("data") or {}
            self.assertEqual(data.get("mode"), "campaign-plan")
            self.assertTrue(data.get("campaign_ready_for_execute"), data)
            self.assertFalse(data.get("api_call_performed"))
            self.assertFalse(data.get("db_write_performed"))
            self.assertEqual(data.get("problems"), [])
            action_rows = data.get("actions") or []
            self.assertEqual(len(action_rows), 3)
            self.assertEqual(
                [row.get("action_type") for row in action_rows],
                [action_type for action_type, _slug in staging_marketplace_evidence_cli.STAGING_CAMPAIGN_ACTION_SPECS],
            )
            self.assertEqual(len({row.get("idempotency_key") for row in action_rows}), 3)
            self.assertTrue(all(row.get("action_type_matches") for row in action_rows))
            self.assertTrue(all(row.get("ready_for_execute") for row in action_rows))
            self.assertTrue(
                all(
                    "apply_closure" not in {command.get("id") for command in row.get("commands") or []}
                    for row in action_rows
                )
            )
            closure_args = (data.get("closure_command") or {}).get("python_args") or []
            self.assertIn("--staging-evidence-dir", closure_args)
            self.assertIn(str(campaign_dir), closure_args)
            self.assertIn("--apply-verified-staging-evidence", closure_args)
            self.assertNotIn("--idempotency-key", closure_args)
            self.assertTrue(plan_path.exists())
            persisted = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted.get("artifact_type"), "orders_staging_marketplace_campaign_plan")

            wrong_action_path = campaign_dir / "return-approval.prepared-action.json"
            wrong_action_path.write_text(
                json.dumps({"action_type": "orders.change_order_cargo_provider"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                patch.object(staging_marketplace_evidence_cli, "_doctor_result", side_effect=_ready_doctor),
                patch("sys.stdout", new_callable=io.StringIO) as mismatch_stdout,
            ):
                mismatch_exit = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "campaign-plan",
                        "--campaign-id",
                        f"{campaign_id}-mismatch",
                        "--campaign-dir",
                        str(campaign_dir),
                        "--staging-reason",
                        "controlled three action staging proof",
                        "--staging-account-id",
                        account_id,
                    ]
                )
            mismatch_payload = json.loads(mismatch_stdout.getvalue())
            self.assertEqual(mismatch_exit, 0)
            mismatch_data = mismatch_payload.get("data") or {}
            self.assertFalse(mismatch_data.get("campaign_ready_for_execute"))
            self.assertIn("action_type_mismatch:return-approval", mismatch_data.get("problems") or [])

    def test_staging_marketplace_runbook_requires_full_external_proof_match(self) -> None:
        root = Path(__file__).resolve().parents[2]
        runbook_path = root / "AI/docs/orders_staging_marketplace_evidence_runbook.md"
        dropzone_path = root / "AI/docs/live_llm_transcripts/staging-marketplace/README.md"
        self.assertTrue(runbook_path.exists(), runbook_path)
        self.assertTrue(dropzone_path.exists(), dropzone_path)
        runbook = runbook_path.read_text(encoding="utf-8")
        dropzone = dropzone_path.read_text(encoding="utf-8")
        for text in (runbook, dropzone):
            self.assertIn("full embedded `external_verification` JSON", text)
            self.assertIn("mutation_summary", text)
        self.assertNotIn("embedded `external_verification` core fields", runbook)
        self.assertIn("--mode verify-manifest", dropzone)

    def test_staging_marketplace_evidence_cli_rejects_placeholder_inputs(self) -> None:
        placeholder_action = {
            "action_type": "listing.action_update_price_inventory_for_account",
            "approval_required": True,
            "execute_enabled": True,
            "arguments": {
                "payload": {
                    "seller_id": "<STAGING_SELLER_ID>",
                    "items": [{"barcode": "STAGING-BARCODE", "quantity": 1, "salePrice": 100}],
                }
            },
        }
        for field, kwargs in (
            (
                "staging_reason_placeholder",
                {
                    "idempotency_key": "orders-staging-placeholder-001",
                    "staging_reason": "<CONTROLLED_STAGING_REASON>",
                    "staging_account_id": "123456789",
                },
            ),
            (
                "idempotency_key_placeholder",
                {
                    "idempotency_key": "<IDEMPOTENCY_KEY>",
                    "staging_reason": "controlled staging placeholder rejection proof",
                    "staging_account_id": "123456789",
                },
            ),
            (
                "staging_account_id_placeholder",
                {
                    "idempotency_key": "orders-staging-placeholder-001",
                    "staging_reason": "controlled staging placeholder rejection proof",
                    "staging_account_id": "<STAGING_SELLER_ID>",
                },
            ),
        ):
            result = operation_runtime.preflight_staging_marketplace_operation(
                placeholder_action,
                marketplace="trendyol",
                require_env=False,
                **kwargs,
            )
            self.assertFalse(result.success, field)
            self.assertIn(field, (result.data or {}).get("problems") or [])
            self.assertFalse((result.data or {}).get("api_call_performed"))
            self.assertFalse((result.data or {}).get("db_write_performed"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            action_path = tmp / "prepared-action.json"
            action_path.write_text(json.dumps(placeholder_action, ensure_ascii=False), encoding="utf-8")

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                exit_code = staging_marketplace_evidence_cli.main(
                    [
                        "--mode",
                        "doctor",
                        "--action-file",
                        str(action_path),
                        "--idempotency-key",
                        "<IDEMPOTENCY_KEY>",
                        "--staging-reason",
                        "<CONTROLLED_STAGING_REASON>",
                        "--staging-account-id",
                        "<STAGING_SELLER_ID>",
                    ]
                )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(payload.get("success"), payload)
        data = payload.get("data") or {}
        self.assertFalse(data.get("api_call_performed"))
        self.assertFalse(data.get("db_write_performed"))
        self.assertEqual(data.get("preflight_skipped"), "staging_inputs_incomplete_or_placeholder")
        self.assertTrue(data.get("idempotency_key_placeholder"))
        self.assertTrue(data.get("staging_reason_placeholder"))
        self.assertTrue(data.get("staging_account_id_placeholder"))
        self.assertIn("idempotency_key_placeholder", data.get("problems") or [])
        self.assertIn("staging_reason_placeholder", data.get("problems") or [])
        self.assertIn("staging_account_id_placeholder", data.get("problems") or [])

    def test_goal_closure_cli_can_turn_ready_with_verified_staging_evidence(self) -> None:
        key = "orders-staging-cargo-20260617-001"
        account_id = "123456789"
        checklist = {
            "name": "orders-agentic-goal-closure-checklist",
            "overall_status": "ready",
            "current_focus": "orders_only",
            "current_orders_scope_required_items": ["natural_chat", "staging_marketplace_guard"],
            "required_items": [
                {"id": "natural_chat", "status": "proven", "evidence": ["conversation"]},
                {"id": "staging_marketplace_guard", "status": "proven", "evidence": ["verified staging evidence"]},
            ],
            "blocking_items": ["staging_marketplace_guard"],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            checklist_path = tmp / "closure.json"
            audit_path = tmp / "audit.jsonl"
            evidence_path = tmp / "evidence.json"
            bad_evidence_path = tmp / "bad-evidence.json"
            external_proof_path = tmp / f"{key}.external-proof.json"
            mismatched_external_proof_path = tmp / f"{key}.mismatch.external-proof.json"
            prepared_action_path = tmp / "prepared-action.json"
            unrelated_json_path = tmp / "notes.json"
            malformed_json_path = tmp / "malformed.json"
            checklist_path.write_text(json.dumps(checklist, ensure_ascii=False), encoding="utf-8")
            audit_path.write_text(
                json.dumps(
                    {
                        "idempotency_key": key,
                        "status": "success",
                        "staging_proof": {
                            "staging_account_id": account_id,
                            "target_account_ids": [account_id],
                            "idempotency_key": key,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            evidence_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "orders_staging_marketplace_evidence",
                        "idempotency_key": key,
                        "staging_account_id": account_id,
                        "preflight_success": True,
                        "execute_success": True,
                        "api_call_performed": True,
                        "db_write_performed": True,
                        "audit_path": str(audit_path),
                        "action": {"action_type": "orders.change_order_cargo_provider"},
                        "result": {
                            "staging_proof": {
                                "staging_account_id": account_id,
                                "target_account_ids": [account_id],
                                "idempotency_key": key,
                            },
                            "verify": {"verified": True},
                        },
                        "external_verification": {
                            "verified": True,
                            "marketplace_state_checked": True,
                            "operation_matches": True,
                            "staging_account_only": True,
                            "staging_account_id": account_id,
                            "idempotency_key": key,
                            "checked_at": "2026-06-17T10:00:00+00:00",
                            "checked_by": "staging-test-operator",
                            "mutation_summary": "Controlled staging marketplace state matched the requested cargo/provider mutation.",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            bad_evidence_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "orders_staging_marketplace_evidence",
                        "idempotency_key": key,
                        "staging_account_id": account_id,
                        "preflight_success": True,
                        "execute_success": False,
                        "api_call_performed": False,
                        "db_write_performed": False,
                        "audit_path": str(audit_path),
                        "action": {"action_type": "orders.change_order_cargo_provider"},
                        "result": {"verify": {"verified": False}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            external_proof_path.write_text(
                json.dumps(
                    {
                        "verified": True,
                        "marketplace_state_checked": True,
                        "operation_matches": True,
                        "staging_account_only": True,
                        "staging_account_id": account_id,
                        "idempotency_key": key,
                        "checked_at": "2026-06-17T10:00:00+00:00",
                        "checked_by": "staging-test-operator",
                        "mutation_summary": "Controlled staging marketplace state matched the requested cargo/provider mutation.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            mismatched_external_proof_path.write_text(
                json.dumps(
                    {
                        "verified": True,
                        "marketplace_state_checked": True,
                        "operation_matches": True,
                        "staging_account_only": True,
                        "staging_account_id": account_id,
                        "idempotency_key": key,
                        "checked_at": "2026-06-17T10:00:00+00:00",
                        "checked_by": "staging-test-operator",
                        "mutation_summary": "Different staging observation text should not match the attached proof.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            prepared_action_path.write_text(
                json.dumps({"action_type": "orders.change_order_cargo_provider"}, ensure_ascii=False),
                encoding="utf-8",
            )
            unrelated_json_path.write_text(json.dumps({"kind": "operator-note"}, ensure_ascii=False), encoding="utf-8")
            malformed_json_path.write_text("{not-json", encoding="utf-8")

            missing_manifest_result = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=checklist_path,
                staging_evidence_path=evidence_path,
                idempotency_key=key,
                staging_account_id=account_id,
            )
            self.assertTrue(missing_manifest_result.success, missing_manifest_result.message)
            missing_manifest_data = missing_manifest_result.data or {}
            self.assertFalse(missing_manifest_data.get("ready_to_complete"))
            self.assertTrue(missing_manifest_data.get("staging_evidence_verified"))
            self.assertFalse(missing_manifest_data.get("staging_manifest_verified"))
            self.assertIn("staging_manifest_invalid", missing_manifest_data.get("problems") or [])
            missing_manifest_inputs = missing_manifest_data.get("staging_inputs") or {}
            self.assertEqual(missing_manifest_inputs.get("idempotency_key"), key)
            self.assertEqual(missing_manifest_inputs.get("staging_account_id"), account_id)
            missing_manifest_actions = {row.get("id"): row for row in missing_manifest_data.get("next_actions") or []}
            self.assertIn("write_staging_evidence_manifest", missing_manifest_actions)
            write_manifest_action = missing_manifest_actions["write_staging_evidence_manifest"]
            self.assertEqual(write_manifest_action.get("evidence_path"), str(evidence_path))
            self.assertEqual(write_manifest_action.get("manifest_path"), str(evidence_path.with_suffix(".manifest.json")))
            self.assertEqual(write_manifest_action.get("external_proof_path_hint"), str(evidence_path.with_suffix(".external-proof.json")))
            self.assertFalse(write_manifest_action.get("external_proof_path_hint_exists"))
            self.assertEqual(
                write_manifest_action.get("manifest_cli_args"),
                [
                    "--mode",
                    "manifest",
                    "--evidence-path",
                    str(evidence_path),
                    "--external-proof-file",
                    str(evidence_path.with_suffix(".external-proof.json")),
                    "--manifest-path",
                    str(evidence_path.with_suffix(".manifest.json")),
                    "--idempotency-key",
                    key,
                    "--staging-account-id",
                    account_id,
                ],
            )
            self.assertEqual(
                write_manifest_action.get("verify_manifest_cli_args"),
                [
                    "--mode",
                    "verify-manifest",
                    "--manifest-path",
                    str(evidence_path.with_suffix(".manifest.json")),
                    "--evidence-path",
                    str(evidence_path),
                    "--idempotency-key",
                    key,
                    "--staging-account-id",
                    account_id,
                ],
            )

            wrong_manifest_result = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=checklist_path,
                staging_evidence_path=evidence_path,
                staging_manifest_path=external_proof_path,
                idempotency_key=key,
                staging_account_id=account_id,
            )
            self.assertTrue(wrong_manifest_result.success, wrong_manifest_result.message)
            wrong_manifest_data = wrong_manifest_result.data or {}
            self.assertFalse(wrong_manifest_data.get("ready_to_complete"))
            self.assertTrue(wrong_manifest_data.get("staging_evidence_verified"))
            self.assertFalse(wrong_manifest_data.get("staging_manifest_verified"))
            wrong_manifest_actions = {row.get("id"): row for row in wrong_manifest_data.get("next_actions") or []}
            self.assertIn("fix_staging_manifest_validation", wrong_manifest_actions)
            wrong_manifest_action = wrong_manifest_actions["fix_staging_manifest_validation"]
            self.assertIn("not an orders_staging_marketplace_evidence_manifest artifact", wrong_manifest_action.get("summary") or "")
            self.assertEqual((wrong_manifest_action.get("manifest_file") or {}).get("path"), str(external_proof_path))
            self.assertEqual((wrong_manifest_action.get("manifest_file") or {}).get("artifact_type"), "json_object_without_artifact_type")
            self.assertEqual(
                wrong_manifest_action.get("verify_manifest_cli_args"),
                [
                    "--mode",
                    "verify-manifest",
                    "--manifest-path",
                    str(external_proof_path),
                    "--evidence-path",
                    str(evidence_path),
                    "--idempotency-key",
                    key,
                    "--staging-account-id",
                    account_id,
                ],
            )

            manifest_result = operation_runtime.staging_marketplace_evidence_manifest(
                evidence_path,
                external_proof_path=external_proof_path,
                idempotency_key=key,
                staging_account_id=account_id,
            )
            self.assertTrue(manifest_result.success, manifest_result.message)
            mismatch_manifest_result = operation_runtime.staging_marketplace_evidence_manifest(
                evidence_path,
                manifest_path=tmp / "mismatched.manifest.json",
                external_proof_path=mismatched_external_proof_path,
                idempotency_key=key,
                staging_account_id=account_id,
            )
            self.assertFalse(mismatch_manifest_result.success)
            mismatch_manifest_data = mismatch_manifest_result.data or {}
            self.assertIn("external_proof.content_mismatch", mismatch_manifest_data.get("problems") or [])
            self.assertIn("mutation_summary", mismatch_manifest_data.get("mismatch_keys") or [])
            manifest_path = Path((manifest_result.data or {}).get("manifest_path") or "")
            self.assertTrue(manifest_path.exists())

            def _write_campaign_evidence(action_type: str, suffix: str) -> tuple[Path, Path]:
                campaign_key = f"orders-staging-{suffix}-20260617-001"
                campaign_audit_path = tmp / f"{suffix}.audit.jsonl"
                campaign_evidence_path = tmp / f"{suffix}.json"
                campaign_proof_path = tmp / f"{suffix}.external-proof.json"
                campaign_audit_path.write_text(
                    json.dumps(
                        {
                            "idempotency_key": campaign_key,
                            "status": "success",
                            "staging_proof": {
                                "staging_account_id": account_id,
                                "target_account_ids": [account_id],
                                "idempotency_key": campaign_key,
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                external_verification = {
                    "verified": True,
                    "marketplace_state_checked": True,
                    "operation_matches": True,
                    "staging_account_only": True,
                    "staging_account_id": account_id,
                    "idempotency_key": campaign_key,
                    "checked_at": "2026-06-17T10:00:00+00:00",
                    "checked_by": "staging-test-operator",
                    "mutation_summary": f"Controlled staging marketplace state matched {suffix}.",
                }
                campaign_evidence_path.write_text(
                    json.dumps(
                        {
                            "artifact_type": "orders_staging_marketplace_evidence",
                            "idempotency_key": campaign_key,
                            "staging_account_id": account_id,
                            "preflight_success": True,
                            "execute_success": True,
                            "api_call_performed": True,
                            "db_write_performed": True,
                            "audit_path": str(campaign_audit_path),
                            "action": {"action_type": action_type},
                            "result": {
                                "staging_proof": {
                                    "staging_account_id": account_id,
                                    "target_account_ids": [account_id],
                                    "idempotency_key": campaign_key,
                                },
                                "verify": {"verified": True},
                            },
                            "external_verification": external_verification,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                campaign_proof_path.write_text(
                    json.dumps(external_verification, ensure_ascii=False),
                    encoding="utf-8",
                )
                campaign_manifest = operation_runtime.staging_marketplace_evidence_manifest(
                    campaign_evidence_path,
                    external_proof_path=campaign_proof_path,
                    idempotency_key=campaign_key,
                    staging_account_id=account_id,
                )
                self.assertTrue(campaign_manifest.success, campaign_manifest.message)
                return campaign_evidence_path, Path((campaign_manifest.data or {}).get("manifest_path") or "")

            bulk_evidence_path, bulk_manifest_path = _write_campaign_evidence(
                "orders.change_orders_cargo_provider_bulk",
                "bulk-cargo",
            )
            two_action_result = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=checklist_path,
                staging_evidence_dir=tmp,
                staging_account_id=account_id,
            )
            self.assertTrue(two_action_result.success, two_action_result.message)
            two_action_data = two_action_result.data or {}
            self.assertFalse(two_action_data.get("ready_to_complete"), two_action_data)
            self.assertFalse(two_action_data.get("staging_campaign_verified"))
            self.assertEqual(
                two_action_data.get("missing_staging_action_types"),
                ["orders.approve_return_claim"],
            )
            return_evidence_path, return_manifest_path = _write_campaign_evidence(
                "orders.approve_return_claim",
                "return-approval",
            )
            newer_without_manifest_path = tmp / "newer-without-manifest.json"
            newer_without_manifest_path.write_text(evidence_path.read_text(encoding="utf-8"), encoding="utf-8")
            newer_mtime = manifest_path.stat().st_mtime + 10
            os.utime(newer_without_manifest_path, (newer_mtime, newer_mtime))

            result = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=checklist_path,
                staging_evidence_path=evidence_path,
                idempotency_key=key,
                staging_account_id=account_id,
            )
            self.assertTrue(result.success, result.message)
            data = result.data or {}
            self.assertFalse(data.get("ready_to_complete"), data)
            self.assertIn("staging_marketplace_guard", data.get("unresolved_blockers") or [])
            self.assertTrue(data.get("staging_evidence_verified"))
            self.assertTrue(data.get("staging_manifest_verified"))
            self.assertFalse(data.get("staging_campaign_verified"))
            self.assertEqual(
                data.get("missing_staging_action_types"),
                ["orders.change_orders_cargo_provider_bulk", "orders.approve_return_claim"],
            )
            self.assertIn("staging_action_evidence_incomplete", data.get("problems") or [])
            single_actions = {row.get("id"): row for row in data.get("next_actions") or []}
            self.assertIn("complete_staging_action_evidence_matrix", single_actions)
            staging_inputs = data.get("staging_inputs") or {}
            self.assertTrue(staging_inputs.get("staging_evidence_path_provided"))
            self.assertTrue(staging_inputs.get("staging_evidence_path_exists"))
            self.assertTrue(staging_inputs.get("staging_manifest_path_exists"))
            self.assertFalse(staging_inputs.get("staging_evidence_dir_provided"))
            self.assertTrue(staging_inputs.get("idempotency_key_provided"))
            self.assertTrue(staging_inputs.get("staging_account_id_provided"))

            dir_result = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=checklist_path,
                staging_evidence_dir=tmp,
                idempotency_key=key,
                staging_account_id=account_id,
            )
            self.assertTrue(dir_result.success, dir_result.message)
            dir_data = dir_result.data or {}
            self.assertTrue(dir_data.get("ready_to_complete"), dir_data)
            self.assertTrue(dir_data.get("staging_campaign_verified"), dir_data)
            self.assertEqual(
                dir_data.get("verified_staging_action_types"),
                list(orders_goal_closure_cli.REQUIRED_ORDERS_STAGING_ACTION_TYPES),
            )
            self.assertEqual(dir_data.get("next_actions"), [])
            dir_inputs = dir_data.get("staging_inputs") or {}
            self.assertFalse(dir_inputs.get("staging_evidence_path_provided"))
            self.assertTrue(dir_inputs.get("staging_evidence_dir_provided"))
            self.assertTrue(dir_inputs.get("staging_evidence_dir_exists"))
            self.assertEqual(dir_inputs.get("staging_evidence_candidate_count"), 5)
            self.assertIn(
                Path(dir_inputs.get("selected_staging_evidence_path") or "").name,
                {evidence_path.name, bulk_evidence_path.name, return_evidence_path.name},
            )
            self.assertTrue(dir_data.get("staging_evidence_candidates"))
            candidate_paths = {Path(row.get("path") or "").name for row in dir_data.get("staging_evidence_candidates") or []}
            self.assertIn(newer_without_manifest_path.name, candidate_paths)
            self.assertNotIn(external_proof_path.name, candidate_paths)
            self.assertNotIn(prepared_action_path.name, candidate_paths)
            self.assertNotIn(unrelated_json_path.name, candidate_paths)
            self.assertNotIn(malformed_json_path.name, candidate_paths)
            self.assertNotIn(manifest_path.name, candidate_paths)

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                report_path = tmp / "ready-report.json"
                exit_code = orders_goal_closure_cli.main(
                    [
                        "--checklist-path",
                        str(checklist_path),
                        "--staging-evidence-dir",
                        str(tmp),
                        "--idempotency-key",
                        key,
                        "--staging-account-id",
                        account_id,
                        "--report-path",
                        str(report_path),
                        "--require-complete",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report_path.exists())
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue((payload.get("data") or {}).get("ready_to_complete"))
            self.assertTrue((report_payload.get("data") or {}).get("ready_to_complete"))
            self.assertTrue(((report_payload.get("data") or {}).get("staging_inputs") or {}).get("staging_evidence_dir_exists"))

            readiness_checklist = {
                "name": "orders-agentic-goal-closure-checklist",
                "overall_status": "open",
                "current_focus": "orders_only",
                "current_orders_scope_required_items": ["natural_chat", "staging_marketplace_guard"],
                "required_items": [
                    {"id": "natural_chat", "status": "proven", "evidence": ["conversation"]},
                    {
                        "id": "staging_marketplace_guard",
                        "status": "proven_readiness_only",
                        "evidence": ["staging readiness gate"],
                        "missing_to_complete": "verified external staging evidence",
                    },
                ],
                "blocking_items": ["staging_marketplace_guard"],
                "next_evidence_needed": ["staging marketplace evidence still needed"],
            }
            readiness_checklist_path = tmp / "readiness-closure.json"
            readiness_checklist_path.write_text(json.dumps(readiness_checklist, ensure_ascii=False), encoding="utf-8")

            readiness_eval = orders_goal_closure_cli.evaluate_orders_goal_closure(
                checklist_path=readiness_checklist_path,
                staging_evidence_dir=tmp,
                staging_account_id=account_id,
            )
            self.assertTrue(readiness_eval.success, readiness_eval.message)
            readiness_eval_data = readiness_eval.data or {}
            self.assertFalse(readiness_eval_data.get("ready_to_complete"))
            readiness_actions = {row.get("id"): row for row in readiness_eval_data.get("next_actions") or []}
            self.assertIn("replace_readiness_only_with_verified_evidence", readiness_actions)
            self.assertEqual(
                readiness_actions["replace_readiness_only_with_verified_evidence"].get("apply_verified_staging_evidence_cli_args"),
                [
                    "--checklist-path",
                    str(readiness_checklist_path),
                    "--staging-evidence-dir",
                    str(tmp),
                    "--apply-verified-staging-evidence",
                    "--require-complete",
                    "--staging-account-id",
                    account_id,
                ],
            )

            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                apply_exit = orders_goal_closure_cli.main(
                    [
                        "--checklist-path",
                        str(readiness_checklist_path),
                        "--staging-evidence-dir",
                        str(tmp),
                        "--staging-account-id",
                        account_id,
                        "--apply-verified-staging-evidence",
                        "--require-complete",
                    ]
                )
            apply_payload = json.loads(stdout.getvalue())
            self.assertEqual(apply_exit, 0)
            self.assertTrue((apply_payload.get("data") or {}).get("checklist_applied"))
            self.assertTrue((apply_payload.get("data") or {}).get("ready_to_complete"), apply_payload)
            patched_checklist = json.loads(readiness_checklist_path.read_text(encoding="utf-8"))
            self.assertEqual(patched_checklist.get("overall_status"), "ready")
            self.assertEqual(patched_checklist.get("blocking_items"), [])
            patched_items = {row.get("id"): row for row in patched_checklist.get("required_items") or []}
            self.assertEqual(patched_items["staging_marketplace_guard"].get("status"), "proven")
            self.assertNotIn("missing_to_complete", patched_items["staging_marketplace_guard"])
            staging_guard_evidence = patched_items["staging_marketplace_guard"].get("evidence") or []
            for action_type, action_evidence_path, action_manifest_path in (
                ("orders.change_order_cargo_provider", evidence_path, manifest_path),
                ("orders.change_orders_cargo_provider_bulk", bulk_evidence_path, bulk_manifest_path),
                ("orders.approve_return_claim", return_evidence_path, return_manifest_path),
            ):
                self.assertIn(
                    f"verified staging evidence ({action_type}): {action_evidence_path}",
                    staging_guard_evidence,
                )
                self.assertIn(
                    f"verified staging manifest ({action_type}): {action_manifest_path}",
                    staging_guard_evidence,
                )
            self.assertIn(
                "AI.processors.staging_marketplace_evidence_cli --mode verify-manifest",
                patched_items["staging_marketplace_guard"].get("evidence") or [],
            )

            invalid_apply_checklist_path = tmp / "invalid-apply-closure.json"
            invalid_apply_checklist_path.write_text(json.dumps(readiness_checklist, ensure_ascii=False), encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                invalid_apply_exit = orders_goal_closure_cli.main(
                    [
                        "--checklist-path",
                        str(invalid_apply_checklist_path),
                        "--staging-evidence-path",
                        str(bad_evidence_path),
                        "--idempotency-key",
                        key,
                        "--staging-account-id",
                        account_id,
                        "--apply-verified-staging-evidence",
                    ]
                )
            invalid_apply_payload = json.loads(stdout.getvalue())
            self.assertEqual(invalid_apply_exit, 1)
            self.assertIn("evidence kampanyasi olmadan", invalid_apply_payload.get("message") or "")
            unpatched_checklist = json.loads(invalid_apply_checklist_path.read_text(encoding="utf-8"))
            self.assertEqual(unpatched_checklist.get("overall_status"), "open")
            unpatched_items = {row.get("id"): row for row in unpatched_checklist.get("required_items") or []}
            self.assertEqual(unpatched_items["staging_marketplace_guard"].get("status"), "proven_readiness_only")

    def test_orders_agentic_parity_matrix_matches_manual_capability_inventory(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/orders_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        report = operation_runtime.operation_coverage_report()
        orders = (report.get("domains") or {}).get("orders") or {}
        self.assertTrue(orders, report)
        self.assertIn(f"read: {orders.get('read_total')}", text)
        self.assertIn(f"write: {orders.get('write_total')}", text)
        self.assertIn(f"total: {orders.get('total')}", text)

        for capability_id in sorted(orders.get("capability_ids") or []):
            self.assertIn(capability_id, text)
        for capability_id in sorted(orders.get("write_capability_ids") or []):
            self.assertIn(capability_id, text)
        for capability_id in sorted(orders.get("generic_read_blocked_ids") or []):
            self.assertIn(capability_id, text)
            self.assertIn("intentionally blocked", text)

        for required_helper in (
            "orders.load_orders_by_numbers",
            "orders.load_orders_for_status_filter",
            "orders.load_orders_for_source_filters",
            "orders.load_ready_to_ship_orders",
            "orders.load_returns_from_db",
            "orders.load_returns_claims",
            "orders.load_returns_for_source_filters",
            "orders.load_order_items_for_order_number",
            "orders.load_order_items_for_order_numbers",
            "orders.load_order_profit_catalog",
            "orders.load_finance_cost_items",
            "orders.load_logistics_cargo_tariffs",
        ):
            self.assertIn(required_helper, text)

    def test_labels_agentic_parity_matrix_covers_word_export_workflow(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/labels_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        for required in (
            "LabelPrintManagerWindow._on_export_clicked",
            "Labels.processors.pipeline.create_order_label_from_orders",
            "Labels.processors.pipeline.export_labels_to_word",
            "labels.create_from_orders.prepare",
            "labels.action_create_labels_from_selected_orders",
            "verify_labels_create",
            "test_label_execute_exports_word_file_when_payload_is_available",
            "test_label_execute_verifies_all_selected_orders_above_twenty_in_docx",
            "test_label_verify_rejects_docx_missing_expected_order_number",
            "test_task_runtime_label_execute_keeps_docx_content_verify_details",
            "live-source-db-ready-label-execute-docx-2026-06-26.json",
            "live-task-runtime-label-ready-orders.json",
            "historical LLM task-runtime proof",
            "do not treat the historical task artifact alone as Word content proof",
            "Broader cross-domain parity still remains open",
        ):
            self.assertIn(required, text)

    def test_stock_agentic_parity_matrix_covers_manual_surface_and_open_gaps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/stock_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        for required in (
            "read: 14",
            "write: 25",
            "total: 39",
            "stock.action_create_item",
            "stock.action_update_item",
            "stock.action_manual_in",
            "stock.action_manual_out",
            "stock.action_export_txs_excel",
            "stock.item_create.prepare",
            "stock.item_update.prepare",
            "operations.manual_action.route",
            "operation_coverage_report",
            "Stock parity is proven for the currently discovered manual Stock surface",
            "live-stock-conversation-read-quality.json",
            "live-stock-manual-movement-adjust-export-execute.json",
            "live-stock-remaining-writes-execute.json",
            "test_stock_capability_and_read_questions_do_not_degrade_to_order_lookup_or_thin_answer",
            "test_gemini_stock_conversation_read_quality_artifact_proves_visible_quality",
            "test_stock_manual_natural_prompts_prepare_execute_and_verify_with_db_payload",
            "test_stock_manual_movements_adjust_export_and_warehouse_execute_verify_audit",
            "test_gemini_stock_manual_movement_adjust_export_execute_artifact_proves_visible_quality",
            "test_stock_remaining_db_writes_execute_verify_and_audit",
            "test_stock_group_catalog_writes_execute_verify_with_isolated_files",
            "test_stock_brand_company_wrappers_execute_verify_and_audit",
            "test_gemini_stock_remaining_writes_execute_artifact_proves_side_effects",
        ):
            self.assertIn(required, text)

    def test_finance_agentic_parity_matrix_covers_manual_surface_and_open_gaps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/finance_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        for required in (
            "read: 11",
            "write: 22",
            "total: 33",
            "external_write: 3 finance sync capabilities",
            "finance.accept_finance_cost_item",
            "finance.accept_finance_cargo_tariff",
            "finance.action_sync_finance_for_accounts",
            "finance.action_sync_finance_for_selected_companies",
            "finance.save_finance_cost_item",
            "finance.save_manual_finance_transaction",
            "finance.save_finance_invoice_document",
            "finance.profit_estimate",
            "finance.cashflow_summary",
            "operations.manual_action.prepare",
            "operation_coverage_report",
            "Finance parity is partial",
            "live LLM/UI artifacts",
            "live-finance-cost-item-save-delete-execute.json",
            "live-finance-cost-item-accept-bulk-delete-execute.json",
            "live-finance-manual-transaction-save-delete-execute.json",
            "live-finance-invoice-document-save-delete-execute.json",
            "live-finance-dashboard-transaction-invoice-read.json",
            "live-finance-cargo-tariff-save-delete-execute.json",
            "live-finance-cargo-tariff-accept-bulk-delete-execute.json",
            "live-finance-cargo-tariff-bulk-accept-execute.json",
            "live-finance-brand-company-crud-execute.json",
            "test_finance_cost_item_prompt_prepares_executes_and_verifies_save_delete",
            "test_finance_cost_item_prompt_prepares_executes_accept_and_bulk_delete",
            "test_finance_manual_transaction_prompt_prepares_executes_and_verifies_save_delete",
            "test_finance_invoice_document_prompt_prepares_executes_and_verifies_save_delete",
            "test_finance_dashboard_transaction_invoice_read_prompts_execute_and_answer_with_records",
            "test_finance_cargo_tariff_prompt_prepares_executes_and_verifies_save_delete",
            "test_finance_cargo_tariff_prompt_prepares_executes_accept_and_bulk_delete",
            "test_finance_cargo_tariff_prompt_prepares_executes_bulk_accept",
            "test_finance_brand_company_prompts_prepare_execute_verify_crud",
            "test_finance_sync_accounts_adapter_resolves_db_credentials_without_secret_audit",
            "test_gemini_finance_cost_item_save_delete_execute_artifact_proves_side_effects",
            "test_gemini_finance_cost_item_accept_bulk_delete_execute_artifact_proves_side_effects",
            "test_gemini_finance_manual_transaction_save_delete_execute_artifact_proves_side_effects",
            "test_gemini_finance_invoice_document_save_delete_execute_artifact_proves_side_effects",
            "test_gemini_finance_dashboard_transaction_invoice_read_artifact_proves_visible_quality",
            "test_gemini_finance_cargo_tariff_save_delete_execute_artifact_proves_side_effects",
            "test_gemini_finance_cargo_tariff_accept_bulk_delete_execute_artifact_proves_side_effects",
            "test_gemini_finance_cargo_tariff_bulk_accept_execute_artifact_proves_side_effects",
            "test_gemini_finance_brand_company_crud_execute_artifact_proves_side_effects",
        ):
            self.assertIn(required, text)

    def test_gemini_finance_cost_item_save_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-cost-item-save-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["save_cost_item", "delete_cost_item"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["finance.save_finance_cost_item", "finance.delete_finance_cost_item"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        cost_payload = ((turns[0].get("turn") or {}).get("payload") or {}).get("cost_payload") or {}
        self.assertEqual(cost_payload.get("name"), "Agent Finans Paketleme Live")
        self.assertEqual(float(cost_payload.get("defaultAmount") or 0), 12.5)
        self.assertEqual((turns[0].get("after") or {}).get("isDeleted"), False)
        self.assertEqual((turns[1].get("after") or {}).get("isDeleted"), True)
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_save"))
        self.assertTrue(audit.get("contains_delete"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_cost_item_accept_bulk_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-cost-item-accept-bulk-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["accept_cost_item", "bulk_delete_cost_items"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["finance.accept_finance_cost_item", "finance.delete_finance_cost_items"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("route_status"), "approval_prepared")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertEqual((turns[0].get("after") or {}).get("costKey"), "komisyon")
        self.assertEqual((turns[0].get("after") or {}).get("isDeleted"), False)
        created = turns[1].get("created_before_turn") or []
        item_pks = ((turns[1].get("turn") or {}).get("payload") or {}).get("item_pks") or []
        self.assertEqual(sorted(item_pks), sorted(row.get("pk") for row in created))
        self.assertTrue(all((row or {}).get("isDeleted") is True for row in (turns[1].get("after") or [])))
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_accept"))
        self.assertTrue(audit.get("contains_bulk_delete"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_brand_company_crud_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-brand-company-crud-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("D:\\\\SoftWareProjects", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        self.assertNotIn("AIza", raw_text)
        self.assertNotIn("sk-", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("step") for row in turns],
            ["create_brand", "create_company", "update_brand", "update_company", "delete_brand", "delete_company"],
        )
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            [
                "finance.action_create_brand",
                "finance.action_create_company",
                "finance.action_update_brand",
                "finance.action_update_company",
                "finance.action_delete_brand",
                "finance.action_delete_company",
            ],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("route_status"), "approval_prepared")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            self.assertFalse(turn.get("missing_parameters"), row)
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((turns[0].get("turn") or {}).get("payload") or {}).get("name"), "Agent Finans Marka Live")
        self.assertEqual(((turns[0].get("turn") or {}).get("payload") or {}).get("code"), "AFML")
        self.assertEqual(((turns[1].get("turn") or {}).get("payload") or {}).get("tax_no"), "1234567890")
        self.assertEqual((((turns[2].get("turn") or {}).get("payload") or {}).get("update_data") or {}).get("note"), "Brand live guncel")
        self.assertEqual((((turns[3].get("turn") or {}).get("payload") or {}).get("update_data") or {}).get("note"), "Sirket live guncel")
        self.assertEqual(artifact.get("after_delete"), {"brand": None, "company": None})
        audit = artifact.get("audit") or {}
        self.assertTrue(all(audit.values()), audit)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_manual_transaction_save_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-manual-transaction-save-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["save_manual_transaction", "delete_manual_transaction"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["finance.save_manual_finance_transaction", "finance.delete_manual_finance_transaction"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        tx_payload = ((turns[0].get("turn") or {}).get("payload") or {}).get("payload") or {}
        self.assertEqual(tx_payload.get("categoryName"), "Agent Ofis Kira Live")
        self.assertEqual(tx_payload.get("direction"), "expense")
        self.assertEqual(float(tx_payload.get("amount") or 0), 2500.0)
        self.assertEqual((turns[0].get("after") or {}).get("isDeleted"), False)
        self.assertEqual((turns[1].get("after") or {}).get("isDeleted"), True)
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_save"))
        self.assertTrue(audit.get("contains_delete"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_invoice_document_save_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-invoice-document-save-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["save_invoice_document", "delete_invoice_document"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["finance.save_finance_invoice_document", "finance.delete_finance_invoice_document"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertIn(turn.get("tool"), {"operations.manual_action.route", "operations.manual_action.prepare"})
            self.assertEqual(turn.get("route_status"), "approval_prepared")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        invoice_payload = ((turns[0].get("turn") or {}).get("payload") or {}).get("payload") or {}
        self.assertEqual(invoice_payload.get("invoiceNumber"), "INV-LIVE-AGENT-0001")
        self.assertEqual(invoice_payload.get("invoiceType"), "expense")
        self.assertEqual(float(invoice_payload.get("totalAmount") or 0), 1250.5)
        self.assertEqual(invoice_payload.get("filePath"), "<temp_invoice_pdf>")
        self.assertEqual((turns[0].get("after") or {}).get("isDeleted"), False)
        self.assertEqual((turns[1].get("after") or {}).get("isDeleted"), True)
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_save"))
        self.assertTrue(audit.get("contains_delete"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_dashboard_transaction_invoice_read_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-dashboard-transaction-invoice-read.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("D:\\\\SoftWareProjects", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        self.assertNotIn("AIza", raw_text)
        self.assertNotIn("sk-", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("step") for row in turns],
            [
                "manual_transactions",
                "named_transaction",
                "invoice_documents",
                "invoice_document_lookup",
                "cargo_invoices",
                "dashboard",
            ],
        )
        self.assertEqual(
            [row.get("capability") for row in turns],
            [
                "finance.get_manual_finance_transactions_from_db",
                "finance.load_finance_transactions_from_db",
                "finance.load_finance_invoice_documents_from_db",
                "finance.load_finance_invoice_documents_from_db",
                "finance.load_finance_cargo_invoices_from_db",
                "finance.load_finance_dashboard_from_db",
            ],
        )
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertEqual(row.get("tool"), "operations.manual_action.read")
            self.assertGreater(int(row.get("llm_calls") or 0), 0)
            quality = row.get("quality") or {}
            self.assertTrue(quality.get("capability_ok"), row)
            self.assertTrue(quality.get("answer_contains_marker"), row)
            self.assertTrue(quality.get("not_order_lookup"), row)
            self.assertTrue(quality.get("visible_not_empty"), row)
        self.assertEqual((turns[1].get("payload") or {}).get("search_text"), "Agent Ofis Kira Live")
        self.assertEqual((turns[3].get("payload") or {}).get("search_text"), "INV-LIVE-AGENT-READ-0001")
        self.assertEqual((turns[4].get("payload") or {}).get("page_size"), 10)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_cargo_tariff_save_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-cargo-tariff-save-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["save_cargo_tariff", "delete_cargo_tariff"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["finance.save_finance_cargo_tariff", "finance.delete_finance_cargo_tariff"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("route_status"), "approval_prepared")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        tariff_payload = ((turns[0].get("turn") or {}).get("payload") or {}).get("tariff_payload") or {}
        self.assertEqual(tariff_payload.get("name"), "Agent Finans TEXMP 0-5 Desi")
        self.assertEqual(tariff_payload.get("cargoProviderCode"), "TEXMP")
        self.assertEqual(float(tariff_payload.get("amount") or 0), 54.9)
        self.assertEqual((turns[0].get("after") or {}).get("isDeleted"), False)
        self.assertEqual((turns[1].get("after") or {}).get("isDeleted"), True)
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_save"))
        self.assertTrue(audit.get("contains_delete"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_cargo_tariff_accept_bulk_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-cargo-tariff-accept-bulk-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["accept_cargo_tariff", "bulk_delete_cargo_tariffs"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["finance.accept_finance_cargo_tariff", "finance.delete_finance_cargo_tariffs"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("route_status"), "approval_prepared")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertEqual((turns[0].get("after") or {}).get("cargoProviderCode"), "TEXMP")
        self.assertEqual((turns[0].get("after") or {}).get("isDeleted"), False)
        accepted = turns[1].get("accepted_before_turn") or []
        item_pks = ((turns[1].get("turn") or {}).get("payload") or {}).get("item_pks") or []
        self.assertEqual(sorted(item_pks), sorted(row.get("pk") for row in accepted))
        self.assertTrue(all((row or {}).get("isDeleted") is True for row in (turns[1].get("after") or [])))
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_accept"))
        self.assertTrue(audit.get("contains_bulk_delete"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_finance_cargo_tariff_bulk_accept_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-cargo-tariff-bulk-accept-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("D:\\\\SoftWareProjects", raw_text)
        self.assertNotIn("api_key", raw_text.casefold())
        self.assertNotIn("AIza", raw_text)
        self.assertNotIn("sk-", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["bulk_accept_cargo_tariffs"])
        turn = (turns[0].get("turn") or {}) if turns else {}
        self.assertTrue(turn.get("success"), turns)
        self.assertEqual(turn.get("capability"), "finance.accept_finance_cargo_tariffs")
        self.assertEqual(turn.get("route_status"), "approval_prepared")
        self.assertEqual(turn.get("mode"), "approval_required")
        self.assertTrue(turn.get("approval_required"))
        self.assertFalse(turn.get("missing_parameters"), turns)
        self.assertEqual(sorted((turn.get("payload") or {}).get("item_pks") or []), sorted(turns[0].get("requested_pks") or []))
        execute = turns[0].get("execute") or {}
        self.assertTrue(execute.get("success"), turns)
        self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(sorted((execute.get("verify") or {}).get("item_pks") or []), sorted(turns[0].get("requested_pks") or []))
        self.assertTrue(all((row or {}).get("isActive") is True and (row or {}).get("isDeleted") is False for row in turns[0].get("after") or []))
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertTrue(audit.get("contains_bulk_accept"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_logistics_agentic_parity_matrix_covers_manual_surface_and_open_gaps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/logistics_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        for required in (
            "read: 3",
            "write: 8",
            "total: 11",
            "generic_execute_blocked: 0",
            "logistics.accept_logistics_cargo_provider_record",
            "logistics.accept_logistics_cargo_tariff",
            "logistics.save_logistics_cargo_provider_record",
            "logistics.delete_logistics_cargo_provider_record",
            "logistics.save_logistics_cargo_tariff",
            "logistics.delete_logistics_cargo_tariff",
            "logistics.profile",
            "logistics.tariff_count",
            "logistics.tariff_lookup",
            "logistics.provider_catalog",
            "live-logistics-provider-accept-save-delete-execute.json",
            "live-logistics-tariff-save-delete-accept-execute.json",
            "live-logistics-bulk-tariff-accept-delete-execute.json",
            "live-logistics-conversation-capability-overview.json",
            "live-logistics-tariff-read-summary-records.json",
            "source-logistics-window-smoke.json",
            "test_logistics_provider_catalog_question_uses_logistics_records_and_visible_answer",
            "test_logistics_capability_help_does_not_degrade_to_order_lookup_or_orders_help",
            "test_logistics_tariff_read_summary_records_and_count_do_not_degrade_to_order_lookup",
            "test_gemini_logistics_tariff_read_summary_records_artifact_proves_visible_quality",
            "test_source_ui_logistics_window_smoke_uses_current_main_py_not_packaged_exe",
            "test_logistics_provider_manual_actions_execute_with_db_verify_and_audit",
            "test_logistics_tariff_manual_actions_execute_with_db_verify_and_audit",
            "test_logistics_bulk_tariff_manual_actions_execute_with_db_verify_and_audit",
            "operations.manual_action.prepare",
            "operation_coverage_report",
            "Logistics parity is proven",
            "generic tariff read repair",
        ):
            self.assertIn(required, text)

    def test_listing_agentic_parity_matrix_covers_manual_surface_and_open_gaps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/listing_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        for required in (
            "read: 9",
            "write: 6",
            "total: 15",
            "external_write: 3 listing marketplace/sync capabilities",
            "generic_execute_blocked: 0",
            "generic_read_blocked: 0",
            "listing.action_fetch_listings",
            "listing.action_update_price_inventory_for_account",
            "listing.action_update_listing_price_inventory_cache",
            "listing.action_set_listing_stock_items",
            "listing.action_set_listing_cost_items",
            "listing.search",
            "listing.price_lookup",
            "listing.update_price.prepare",
            "listing.update_stock.prepare",
            "listing.quality_audit",
            "listing.content_optimize.prepare",
            "operations.manual_action.prepare",
            "operation_coverage_report",
            "Listing parity is partial",
            "live-listing-conversation-read-quality.json",
            "test_listing_capability_and_read_questions_do_not_degrade_to_order_lookup_or_thin_answer",
            "test_gemini_listing_conversation_read_quality_artifact_proves_visible_quality",
            "test_listing_fetch_execute_saves_verifies_db_without_secret_audit",
            "test_listing_local_writes_execute_verify_with_db_and_audit",
            "test_listing_price_prepare_bridges_to_staging_marketplace_action_only",
            "DB verify/audit",
            "staging_action",
            "controlled staging/sandbox run",
        ):
            self.assertIn(required, text)

    def test_marketplaces_agentic_parity_matrix_covers_manual_surface_and_open_gaps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/marketplaces_agentic_parity_matrix.md"
        self.assertTrue(path.exists(), path)
        text = path.read_text(encoding="utf-8")
        for required in (
            "read: 1",
            "write: 4",
            "total: 5",
            "external_write: 0",
            "generic_execute_blocked: 0",
            "generic_read_blocked: 0",
            "marketplaces.load_marketplaces",
            "marketplaces.accept_marketplace_record",
            "marketplaces.save_marketplace",
            "marketplaces.delete_marketplace",
            "marketplaces.set_marketplaces_active_state",
            "marketplaces.account_count",
            "marketplaces.account_lookup",
            "marketplaces.catalog",
            "live-marketplaces-catalog-repair.json",
            "live-marketplace-set-inactive-execute.json",
            "live-marketplace-accept-save-delete-execute.json",
            "source-marketplace-catalog-chat-smoke.json",
            "test_marketplaces_manual_actions_execute_with_db_verify_and_audit",
            "operations.manual_action.prepare",
            "operation_coverage_report",
            "Marketplaces parity is proven",
        ):
            self.assertIn(required, text)

    def test_openrouter_marketplaces_catalog_repair_artifact_proves_visible_answer(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/openrouter-marketplaces/live-marketplaces-catalog-repair.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "openrouter")
        result = artifact.get("result") or {}
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("tool"), "marketplaces.catalog")
        answer = _compact_text(result.get("answer_preview"))
        self.assertIn("TRENDYOL", answer)
        self.assertNotIn("siparis buldum", answer.casefold())
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("visible_answer_quality"), "pass")
        self.assertEqual(review.get("tool_gating"), "pass")

    def test_openrouter_marketplace_set_inactive_execute_artifact_proves_side_effect(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/openrouter-marketplaces/live-marketplace-set-inactive-execute.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "openrouter")
        turn = artifact.get("turn") or {}
        self.assertTrue(turn.get("success"))
        self.assertEqual(turn.get("tool"), "operations.manual_action.route")
        self.assertEqual(turn.get("mode"), "approval_required")
        self.assertEqual(turn.get("capability"), "marketplaces.set_marketplaces_active_state")
        payload = turn.get("payload") or {}
        self.assertEqual(payload.get("codes"), ["TRENDYOL"])
        self.assertEqual(payload.get("is_active"), False)
        execute = artifact.get("execute") or {}
        self.assertTrue(execute.get("success"))
        self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertEqual((execute.get("verify") or {}).get("is_active"), False)
        self.assertEqual(execute.get("db_trendyol_active"), False)
        self.assertTrue(execute.get("audit_exists"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("final_side_effect"), "pass")

    def test_openrouter_marketplace_accept_save_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/openrouter-marketplaces/live-marketplace-accept-save-delete-execute.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "openrouter")
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["accept", "save", "delete"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            ["marketplaces.accept_marketplace_record", "marketplaces.save_marketplace", "marketplaces.delete_marketplace"],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertEqual(((turns[1].get("after") or {}).get("label")), "Trendyol Agentic")
        self.assertIsNone(turns[2].get("after"))
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_accept"))
        self.assertTrue(audit.get("contains_save"))
        self.assertTrue(audit.get("contains_delete"))
        self.assertTrue(audit.get("contains_db_verify"))
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("visible_answer_quality"), "pass")
        self.assertEqual(review.get("tool_gating"), "pass")
        self.assertEqual(review.get("final_side_effect"), "pass")

    def test_gemini_logistics_provider_accept_save_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-logistics/live-logistics-provider-accept-save-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["accept_provider", "save_provider", "delete_provider"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            [
                "logistics.accept_logistics_cargo_provider_record",
                "logistics.save_logistics_cargo_provider_record",
                "logistics.delete_logistics_cargo_provider_record",
            ],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        self.assertTrue(any((row or {}).get("cargoProviderCode") == "AGENTKARGO" for row in turns[1].get("after") or []))
        self.assertFalse(any((row or {}).get("cargoProviderCode") == "AGENTKARGO" for row in turns[2].get("after") or []))
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertGreaterEqual(int(audit.get("line_count") or 0), 3)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_logistics_tariff_save_delete_accept_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-logistics/live-logistics-tariff-save-delete-accept-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("step") for row in turns], ["save_tariff", "delete_tariff", "accept_builtin_tariff"])
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            [
                "logistics.save_logistics_cargo_tariff",
                "logistics.delete_logistics_cargo_tariff",
                "logistics.accept_logistics_cargo_tariff",
            ],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        tariff_payload = ((turns[0].get("turn") or {}).get("payload") or {}).get("tariff_payload") or {}
        self.assertEqual(tariff_payload.get("name"), "Agent Tarife")
        self.assertEqual(tariff_payload.get("cargoProviderCode"), "TEXMP")
        self.assertEqual(float(tariff_payload.get("amount") or 0), 44.5)
        self.assertTrue(any((row or {}).get("name") == "Agent Tarife" for row in turns[0].get("after") or []))
        self.assertFalse(any((row or {}).get("name") == "Agent Tarife" for row in turns[1].get("after") or []))
        self.assertTrue(any(bool((row or {}).get("isBuiltinAccepted")) for row in turns[2].get("after") or []))
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_verified_by_db"))
        self.assertGreaterEqual(int(audit.get("line_count") or 0), 3)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(all((review.get("checks") or {}).values()))

    def test_gemini_logistics_bulk_tariff_accept_delete_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-logistics/live-logistics-bulk-tariff-accept-delete-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("step") for row in turns],
            ["bulk_accept", "save_bulk_tariff_1", "save_bulk_tariff_2", "bulk_delete"],
        )
        self.assertEqual(
            [(row.get("turn") or {}).get("capability") for row in turns],
            [
                "logistics.accept_logistics_cargo_tariffs",
                "logistics.save_logistics_cargo_tariff",
                "logistics.save_logistics_cargo_tariff",
                "logistics.delete_logistics_cargo_tariffs",
            ],
        )
        for row in turns:
            turn = row.get("turn") or {}
            self.assertTrue(turn.get("success"), row)
            self.assertEqual(turn.get("tool"), "operations.manual_action.route")
            self.assertEqual(turn.get("mode"), "approval_required")
            self.assertTrue(turn.get("approval_required"))
            execute = row.get("execute") or {}
            self.assertTrue(execute.get("success"), row)
            self.assertEqual((execute.get("verify") or {}).get("verified_by"), "db")
        accept_payload = ((turns[0].get("turn") or {}).get("payload") or {}).get("item_pks") or []
        delete_payload = ((turns[-1].get("turn") or {}).get("payload") or {}).get("item_pks") or []
        self.assertEqual(len(accept_payload), 2)
        self.assertEqual(len(delete_payload), 2)
        self.assertGreaterEqual(len(turns[-1].get("before") or []), 2)
        self.assertEqual(turns[-1].get("after") or [], [])
        audit = artifact.get("audit") or {}
        self.assertTrue(audit.get("contains_bulk_accept"))
        self.assertTrue(audit.get("contains_bulk_delete"))
        self.assertTrue(audit.get("contains_db_verify"))
        self.assertGreaterEqual(int(audit.get("line_count") or 0), 4)
        review = artifact.get("teacher_review") or {}
        self.assertTrue(review.get("all_checks_passed"), review)
        self.assertTrue(review.get("bulk_delete_removed_rows"), review)

    def test_gemini_logistics_conversation_capability_overview_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-logistics/live-logistics-conversation-capability-overview.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("prompt") for row in turns],
            [
                "lojistik tarafinda hangi islemleri yapabiliyorsun",
                "kargo tarafinda neler yapabiliriz",
                "Trendyol kargo firmalarini listele",
                "kargo tarife profilini goster",
                "Trendyol Express tarifeleriyle ilgili neler yapabilirsin",
            ],
        )
        self.assertEqual(turns[0].get("mode"), "answer")
        self.assertEqual(turns[1].get("mode"), "answer")
        self.assertEqual(turns[-1].get("mode"), "answer")
        self.assertEqual(turns[2].get("tool"), "logistics.provider_catalog")
        self.assertEqual(turns[3].get("tool"), "logistics.profile")
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertNotEqual(row.get("tool"), "orders.lookup", row)
            quality = row.get("answer_quality") or {}
            self.assertTrue(quality.get("not_fixed_low_value"), row)
            self.assertTrue(quality.get("mentions_logistics_terms"), row)
            self.assertTrue(quality.get("not_orders_capability_help"), row)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("no_order_lookup_for_logistics_help"), review)
        self.assertTrue(review.get("orders_capability_help_not_leaked"), review)

    def test_gemini_logistics_tariff_read_summary_records_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-logistics/live-logistics-tariff-read-summary-records.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("prompt") for row in turns],
            [
                "kargo tarifelerimi ozetle",
                "aktif kargo tarife sayisi kac",
                "kargo tarife kayitlarini listele",
                "kargo tarife kayitlari ve ozetini goster",
                "Kargo tarifelerimi goster",
            ],
        )
        self.assertEqual(turns[0].get("tools"), ["logistics.profile"])
        self.assertEqual(turns[1].get("tools"), ["logistics.tariff_count"])
        self.assertEqual(turns[2].get("tools"), ["logistics.tariff_lookup"])
        self.assertEqual(turns[3].get("tools"), ["logistics.profile", "logistics.tariff_lookup"])
        self.assertEqual(turns[4].get("tools"), ["logistics.tariff_count"])
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertNotIn("orders.lookup", row.get("tools") or [], row)
            quality = row.get("answer_quality") or {}
            self.assertTrue(quality.get("not_fixed_low_value"), row)
            self.assertTrue(quality.get("mentions_tariff_terms"), row)
            self.assertTrue(quality.get("not_order_search_answer"), row)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("expected_tools"), review)
        self.assertTrue(review.get("no_order_lookup"), review)
        self.assertTrue(review.get("visible_answer_quality"), review)

    def test_gemini_listing_conversation_read_quality_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-listing/live-listing-conversation-read-quality.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("prompt") for row in turns],
            [
                "ilanlar tarafinda neler yapabiliyorsun",
                "at kili firca ilanlarini listele",
                "at kili firca fiyatlarini ver",
                "dikkat isteyen ilan sayisi kac",
                "at kili firca ilanini satis artirmak icin yorumla",
            ],
        )
        self.assertEqual(turns[0].get("mode"), "answer")
        self.assertEqual(turns[0].get("tools"), [])
        self.assertEqual(turns[1].get("tools"), ["listing.search"])
        self.assertEqual(turns[2].get("tools"), ["listing.price_lookup"])
        self.assertEqual(turns[3].get("tools"), ["listing.attention_count"])
        self.assertEqual(turns[4].get("tools"), ["listing.search", "listing.quality_audit"])
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertNotIn("orders.lookup", row.get("tools") or [], row)
            quality = row.get("answer_quality") or {}
            self.assertTrue(quality.get("not_fixed_low_value"), row)
            self.assertTrue(quality.get("mentions_listing_terms"), row)
            self.assertTrue(quality.get("not_order_search_answer"), row)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("expected_tools"), review)
        self.assertTrue(review.get("capability_answer"), review)
        self.assertTrue(review.get("shows_listing_rows"), review)
        self.assertTrue(review.get("shows_price"), review)
        self.assertTrue(review.get("shows_attention_count"), review)
        self.assertTrue(review.get("sales_advice"), review)

    def test_gemini_stock_conversation_read_quality_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-stock/live-stock-conversation-read-quality.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("prompt") for row in turns],
            [
                "stok tarafinda neler yapabiliyorsun",
                "stok genel ozetini ver",
                "dusuk stok sayisi kac",
                "stoktaki urunleri listele",
                "BICAK BILEYICI APARAT stok urununu bul",
                "stokta biten urun sayisi kac",
            ],
        )
        self.assertEqual(turns[0].get("mode"), "answer")
        self.assertEqual(turns[0].get("tools"), [])
        self.assertEqual(turns[1].get("tools"), ["stock.inventory_overview"])
        self.assertEqual(turns[2].get("tools"), ["stock.low_stock_count"])
        self.assertEqual(turns[3].get("tools"), ["stock.items_list"])
        self.assertEqual(turns[4].get("tools"), ["stock.search"])
        self.assertEqual(turns[5].get("tools"), ["stock.zero_or_negative_count"])
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertNotIn("orders.lookup", row.get("tools") or [], row)
            quality = row.get("answer_quality") or {}
            self.assertTrue(quality.get("not_fixed_low_value"), row)
            self.assertTrue(quality.get("mentions_stock_terms"), row)
            self.assertTrue(quality.get("not_order_search_answer"), row)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("expected_tools"), review)
        self.assertTrue(review.get("capability_answer"), review)
        self.assertTrue(review.get("shows_inventory_overview"), review)
        self.assertTrue(review.get("shows_low_stock_count"), review)
        self.assertTrue(review.get("shows_stock_rows"), review)
        self.assertTrue(review.get("shows_stock_search_result"), review)
        self.assertTrue(review.get("shows_zero_negative_count"), review)

    def test_gemini_stock_manual_movement_adjust_export_execute_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-stock/live-stock-manual-movement-adjust-export-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("D:\\\\SoftWareProjects", raw_text)
        self.assertNotIn("api_key", raw_text)
        self.assertNotIn("AIza", raw_text)
        self.assertNotIn("sk-", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual([row.get("name") for row in turns], ["manual_in", "manual_out", "adjust", "export"])
        self.assertEqual(
            [row.get("action_type") for row in turns],
            [
                "stock.action_manual_in",
                "stock.action_manual_out",
                "stock.action_adjust_item_stock_to",
                "stock.action_export_txs_excel",
            ],
        )
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertEqual(row.get("mode"), "approval_required", row)
            self.assertEqual(((row.get("tool_call") or {}).get("tool")), "operations.manual_action.prepare", row)
            self.assertTrue(((row.get("execute") or {}).get("success")), row)
            self.assertTrue((((row.get("execute") or {}).get("verify") or {}).get("verified")), row)
            self.assertTrue(str(row.get("answer") or "").strip(), row)
        self.assertEqual((((turns[0].get("execute") or {}).get("verify") or {}).get("verified_by")), "db")
        self.assertEqual((((turns[1].get("execute") or {}).get("verify") or {}).get("verified_by")), "db")
        self.assertEqual((((turns[2].get("execute") or {}).get("verify") or {}).get("verified_by")), "db")
        self.assertEqual((((turns[3].get("execute") or {}).get("verify") or {}).get("verified_by")), "filesystem")
        audit_operations = artifact.get("audit_operations") or []
        self.assertEqual(
            [row.get("operation") for row in audit_operations],
            [
                "stock.action_manual_in",
                "stock.action_manual_out",
                "stock.action_adjust_item_stock_to",
                "stock.action_export_txs_excel",
            ],
        )
        self.assertTrue(all(row.get("status") == "success" and row.get("verified") for row in audit_operations), audit_operations)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("expected_tools"), review)
        self.assertTrue(review.get("executed_all_actions"), review)
        self.assertTrue(review.get("db_verified_movements"), review)
        self.assertTrue(review.get("filesystem_verified_export"), review)
        self.assertTrue(review.get("visible_answers_present"), review)

    def test_gemini_stock_remaining_writes_execute_artifact_proves_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-stock/live-stock-remaining-writes-execute.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        self.assertNotIn("D:\\\\SoftWareProjects", raw_text)
        self.assertNotIn("api_key", raw_text)
        self.assertNotIn("AIza", raw_text)
        self.assertNotIn("sk-", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        operations = artifact.get("operations") or []
        expected = {
            "stock.action_update_tx_attachments",
            "stock.action_update_tx_edit_fields",
            "stock.action_auto_deduct_order_items",
            "stock.action_delete_item",
            "stock.action_create_brand",
            "stock.action_update_brand",
            "stock.action_delete_brand",
            "stock.action_create_company",
            "stock.action_update_company",
            "stock.action_delete_company",
            "stock.action_create_upper_group",
            "stock.action_update_upper_group",
            "stock.action_create_sub_group",
            "stock.action_update_sub_group",
            "stock.action_delete_sub_group",
            "stock.action_delete_upper_group",
        }
        actual = {row.get("capability_id") for row in operations}
        self.assertTrue(expected.issubset(actual), actual)
        for row in operations:
            self.assertTrue(row.get("prepare_success"), row)
            self.assertTrue(row.get("execute_success"), row)
            self.assertTrue(row.get("verified"), row)
            self.assertIn(row.get("verified_by"), {"db", "catalog"}, row)
        self.assertTrue(str(artifact.get("live_answer") or "").strip())
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("executed_all_actions"), review)
        self.assertTrue(review.get("verified_all_actions"), review)
        self.assertTrue(review.get("db_verified"), review)
        self.assertTrue(review.get("catalog_verified"), review)
        self.assertTrue(review.get("visible_live_answer_present"), review)

    def test_gemini_finance_conversation_read_quality_artifact_proves_visible_quality(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/gemini-finance/live-finance-conversation-read-quality.json"
        self.assertTrue(path.exists(), path)
        raw_text = path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\\\Users\\\\", raw_text)
        artifact = json.loads(raw_text)
        self.assertEqual((artifact.get("source_app") or {}).get("entrypoint"), "desktop/main.py")
        self.assertFalse(bool((artifact.get("source_app") or {}).get("packaged_exe_used")))
        self.assertEqual((artifact.get("provider") or {}).get("provider_code"), "gemini")
        attempts = artifact.get("provider_attempts") or []
        self.assertTrue(any((row or {}).get("status") == "ok" for row in attempts), attempts)
        turns = artifact.get("turns") or []
        self.assertEqual(
            [row.get("prompt") for row in turns],
            [
                "finans tarafinda neler yapabiliyorsun",
                "bugunku karim ne kadar",
                "bu ay nakit akisi ne",
                "maliyet kalemlerini listele",
                "Paketleme Live Finans Gideri maliyet kalemini bul",
                "finans ozetini ver",
            ],
        )
        self.assertEqual(turns[0].get("mode"), "answer")
        self.assertEqual(turns[0].get("tools"), [])
        self.assertEqual(turns[1].get("tools"), ["finance.profit_amount"])
        self.assertEqual(turns[2].get("tools"), ["finance.cashflow_summary"])
        self.assertEqual(turns[3].get("tools"), ["finance.cost_catalog"])
        self.assertEqual(turns[4].get("tools"), ["finance.cost_item_lookup"])
        self.assertEqual(turns[5].get("tools"), ["finance.profit_amount", "finance.cashflow_net", "finance.cost_item_count"])
        for row in turns:
            self.assertTrue(row.get("success"), row)
            self.assertNotIn("orders.lookup", row.get("tools") or [], row)
            quality = row.get("answer_quality") or {}
            self.assertTrue(quality.get("not_fixed_low_value"), row)
            self.assertTrue(quality.get("mentions_finance_terms"), row)
            self.assertTrue(quality.get("not_order_search_answer"), row)
            self.assertTrue(quality.get("ascii_safe"), row)
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("status"), "pass")
        self.assertTrue(review.get("expected_tools"), review)
        self.assertTrue(review.get("capability_answer"), review)
        self.assertTrue(review.get("shows_profit"), review)
        self.assertTrue(review.get("shows_cashflow"), review)
        self.assertTrue(review.get("shows_cost_rows"), review)
        self.assertTrue(review.get("shows_cost_lookup"), review)
        self.assertTrue(review.get("shows_finance_overview"), review)
        self.assertTrue(review.get("no_order_lookup_degrade"), review)
        self.assertTrue(review.get("answers_ascii_safe"), review)

    def test_source_ui_marketplace_catalog_smoke_proves_current_app_chat(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/source-ui/source-marketplace-catalog-chat-smoke.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        source_app = artifact.get("source_app") or {}
        self.assertEqual(source_app.get("process"), "python.exe")
        self.assertFalse(bool(source_app.get("packaged_exe_used")))
        visible = artifact.get("visible_result") or {}
        self.assertIn("marketplaces.catalog", visible.get("tool_state") or "")
        joined = "\n".join(str(row) for row in visible.get("transcript_lines") or [])
        self.assertIn("TRENDYOL", joined)
        self.assertIn("Pazaryeri katalog", joined)
        self.assertNotIn("siparis buldum", joined.casefold())
        review = artifact.get("teacher_review") or {}
        self.assertEqual(review.get("source_app_quality"), "pass")
        self.assertEqual(review.get("wrong_domain_regression"), "pass")

    def test_source_ui_logistics_window_smoke_uses_current_main_py_not_packaged_exe(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "AI/docs/live_llm_transcripts/source-ui/source-logistics-window-smoke.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        launch = artifact.get("launch") or {}
        self.assertIn("main.py", launch.get("command") or "")
        self.assertFalse(bool(launch.get("packaged_exe_used")))
        self.assertIn("OrderScout.exe", launch.get("packaged_exe_path_ignored") or "")
        computer_use = artifact.get("computer_use") or {}
        self.assertTrue(computer_use.get("verified_not_packaged_exe"))
        main_window = computer_use.get("main_window") or {}
        self.assertEqual(main_window.get("title"), "OrderScout - Ana Panel")
        self.assertEqual(main_window.get("app"), "python.exe")
        self.assertIn("Lojistik / Tanımlar", "\n".join(main_window.get("visible_text") or []))
        provider_window = computer_use.get("provider_window") or {}
        self.assertEqual(provider_window.get("title"), "Kargo Firmaları")
        provider_text = "\n".join(provider_window.get("visible_text") or [])
        self.assertIn("Kargo Firmaları", provider_text)
        self.assertIn("Kargo Firmasını Kaydet", provider_text)
        tariff_window = computer_use.get("tariff_window") or {}
        self.assertEqual(tariff_window.get("title"), "Kargo Tarifeleri")
        tariff_text = "\n".join(tariff_window.get("visible_text") or [])
        self.assertIn("Kargo Tarifeleri", tariff_text)
        self.assertIn("Desi Aralığı", tariff_text)
        verdict = artifact.get("verdict") or {}
        for key in (
            "source_main_window_opened",
            "logistics_tab_visible",
            "provider_window_opened",
            "tariff_window_opened",
            "manual_provider_surface_visible",
            "manual_tariff_surface_visible",
            "packaged_exe_not_used",
        ):
            self.assertTrue(verdict.get(key), key)

    def test_persisted_chat_tab_ui_smoke_proves_visible_approval_execute_flow(self) -> None:
        root = self._artifact_root()
        path = root / "ui-chat-tab-approval-smoke.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        transcript = _compact_text(artifact.get("transcript"))
        self.assertIn("son gelen iki siparisi yazdir", transcript)
        self.assertIn("Tool calisti: labels.create_from_orders.prepare", transcript)
        self.assertIn("Onay gerekiyor", transcript)
        self.assertIn("Onayli aksiyon calistirildi", transcript)
        before = artifact.get("before_approval_state") or {}
        self.assertEqual(before.get("status"), "approval_required")
        self.assertIn("ORD-UI-SMOKE-1", before.get("pending") or "")
        self.assertIn("ORD-UI-SMOKE-2", before.get("pending") or "")
        after = artifact.get("after_execute_state") or {}
        self.assertEqual(after.get("status"), "executed")
        self.assertTrue(artifact.get("execute_called"))
        self.assertEqual(artifact.get("execute_action_type"), "labels.action_create_labels_from_selected_orders")
        self.assertTrue((artifact.get("execute_verify") or {}).get("verified"))
        self.assertEqual((artifact.get("execute_verify") or {}).get("verified_by"), "payload_and_docx_content")
        self.assertTrue((artifact.get("execute_verify") or {}).get("docx_order_numbers_verified"))
        self.assertIn("kanit: payload_and_docx_content", transcript)
        scenarios = artifact.get("additional_write_scenarios") or []
        by_name = {row.get("name"): row for row in scenarios if isinstance(row, dict)}
        self.assertIn("return_approval", by_name)
        self.assertIn("cargo_change", by_name)
        self.assertEqual(by_name["return_approval"].get("execute_action_type"), "orders.approve_return_claim")
        self.assertTrue((by_name["return_approval"].get("execute_verify") or {}).get("verified"))
        self.assertIn("CLAIM-UI-SMOKE", json.dumps(by_name["return_approval"], ensure_ascii=False))
        self.assertEqual(by_name["cargo_change"].get("execute_action_type"), "orders.change_order_cargo_provider")
        self.assertTrue((by_name["cargo_change"].get("execute_verify") or {}).get("verified"))
        self.assertIn("ORD-UI-SMOKE-CARGO", json.dumps(by_name["cargo_change"], ensure_ascii=False))

    def test_persisted_source_main_window_smoke_uses_current_code_not_packaged_exe(self) -> None:
        root = self._artifact_root()
        path = root / "source-main-window-smoke.json"
        self.assertTrue(path.exists(), path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        joined = json.dumps(artifact, ensure_ascii=False)
        current_evidence = artifact.get("current_closure_evidence") or {}
        self.assertEqual(current_evidence.get("method"), "source_offscreen_widget_tests")
        self.assertFalse(bool(current_evidence.get("computer_use_used")))
        self.assertFalse(bool(current_evidence.get("packaged_exe_used")))
        self.assertIn(
            "test_main_source_ai_builder_returns_current_clickable_chat_tab",
            current_evidence.get("source_tests") or [],
        )
        self.assertEqual(
            ((artifact.get("launch") or {}).get("command")),
            "<workspace>\\desktop\\.codex-venv\\Scripts\\python.exe main.py",
        )
        self.assertIn("OrderScout - Ana Panel", joined)
        self.assertIn("Orders / Sipariş Yönetimi", joined)
        self.assertTrue((artifact.get("verdict") or {}).get("source_main_window_opened"))
        self.assertTrue((artifact.get("verdict") or {}).get("orders_surface_visible"))
        self.assertTrue((artifact.get("verdict") or {}).get("toolbar_ai_opens_chat_tab"))
        self.assertTrue((artifact.get("verdict") or {}).get("historical_direct_chat_ui_executed_by_computer_use"))
        self.assertTrue((artifact.get("verdict") or {}).get("historical_direct_order_read_ui_executed_by_computer_use"))
        self.assertFalse((artifact.get("verdict") or {}).get("current_closure_uses_computer_use"))
        self.assertFalse((artifact.get("verdict") or {}).get("current_closure_uses_packaged_exe"))
        self.assertEqual(
            (artifact.get("verdict") or {}).get("source_offscreen_widget_evidence"),
            "test_main_source_ai_builder_returns_current_clickable_chat_tab",
        )
        closure_evidence = artifact.get("current_closure_evidence") or {}
        self.assertTrue(closure_evidence.get("redacted"))
        self.assertEqual(
            closure_evidence.get("redaction_scope"),
            "customer names, order numbers, claim ids, tracking numbers",
        )
        aliases = closure_evidence.get("aliases") or {}
        self.assertEqual(aliases.get("recent_order"), "<source-order-recent-1>")
        self.assertEqual(aliases.get("return_claim"), "<source-claim-waiting-1>")
        self.assertEqual(aliases.get("return_order"), "<source-return-order-1>")
        self.assertEqual(aliases.get("read_order"), "<source-order-read-1>")
        self.assertTrue(((artifact.get("direct_chat") or {}).get("visible_answer_quality") or {}).get("not_fixed_fallback"))
        self.assertTrue(((artifact.get("direct_order_read") or {}).get("visible_answer_quality") or {}).get("used_read_tool_for_order_data"))
        self.assertIn("Tool calisti: orders.recent", joined)
        self.assertTrue((artifact.get("computer_use") or {}).get("verified_not_packaged_exe"))
        recheck = artifact.get("recheck_2026_06_16") or {}
        self.assertFalse((recheck.get("computer_use") or {}).get("packaged_exe_running"))
        self.assertIn("desktop\\.codex-venv\\Scripts\\pythonw.exe main.py", ((recheck.get("launch") or {}).get("command") or ""))
        self.assertIn("Yerel chat hazır", json.dumps(recheck.get("ai_tab_evidence") or [], ensure_ascii=False))
        self.assertIn("Aktif beyin", json.dumps(recheck.get("ai_tab_evidence") or [], ensure_ascii=False))
        recheck_chat = recheck.get("direct_chat_recheck") or {}
        self.assertEqual(recheck_chat.get("runtime"), "llama_cpp_server")
        self.assertEqual(recheck_chat.get("profile"), "os_guarded_low_memory")
        self.assertTrue((recheck_chat.get("visible_answer_quality") or {}).get("not_fixed_fallback"))
        self.assertTrue((recheck_chat.get("visible_answer_quality") or {}).get("no_tool_used_for_casual_identity_question"))
        capability_chat = recheck.get("capability_question_recheck") or {}
        self.assertEqual(capability_chat.get("runtime"), "llama_cpp_server")
        self.assertEqual(capability_chat.get("profile"), "os_guarded_low_memory")
        self.assertTrue((capability_chat.get("visible_answer_quality") or {}).get("not_count_or_lookup"))
        self.assertTrue((capability_chat.get("visible_answer_quality") or {}).get("no_tool_used_for_capability_question"))
        capability_joined = json.dumps(capability_chat, ensure_ascii=False)
        self.assertIn("etiket", capability_joined)
        self.assertIn("iade", capability_joined)
        self.assertIn("kargo", capability_joined)
        self.assertNotIn("Tool calisti", capability_joined)
        self.assertNotIn("orders.count", capability_joined)
        self.assertNotIn("orders.lookup", capability_joined)
        followup_label = recheck.get("recent_order_followup_label_prepare_recheck") or {}
        self.assertEqual(followup_label.get("read_runtime"), "llama_cpp_server")
        self.assertEqual(followup_label.get("read_profile"), "os_guarded_low_memory")
        self.assertEqual(followup_label.get("followup_runtime"), "rule_fallback")
        self.assertEqual(followup_label.get("followup_profile"), "contextual_write_rule")
        self.assertEqual(followup_label.get("order_number"), "<source-order-recent-1>")
        followup_quality = followup_label.get("visible_answer_quality") or {}
        self.assertTrue(followup_quality.get("read_used_orders_recent"))
        self.assertTrue(followup_quality.get("followup_used_contextual_label_prepare"))
        self.assertTrue(followup_quality.get("same_order_number_preserved"))
        self.assertTrue(followup_quality.get("approval_required"))
        self.assertFalse(followup_quality.get("api_call_performed"))
        self.assertFalse(followup_quality.get("db_write_performed"))
        self.assertFalse(followup_quality.get("execute_performed"))
        self.assertTrue(followup_quality.get("not_casual_fallback"))
        followup_joined = json.dumps(followup_label, ensure_ascii=False)
        self.assertIn("Tool calisti: orders.recent", followup_joined)
        self.assertIn("Tool calisti: labels.create_from_orders.prepare", followup_joined)
        self.assertIn("Onay gerekiyor", followup_joined)
        self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", followup_joined)
        self.assertNotIn("Onayli aksiyon calistirildi", followup_joined)
        self.assertNotIn("Iyiyim, buradayim", followup_joined)
        followup_cargo = recheck.get("recent_order_followup_cargo_prepare_recheck") or {}
        self.assertEqual(followup_cargo.get("read_runtime"), "llama_cpp_server")
        self.assertEqual(followup_cargo.get("read_profile"), "os_guarded_low_memory")
        self.assertEqual(followup_cargo.get("followup_runtime"), "llama_cpp_server")
        self.assertEqual(followup_cargo.get("followup_profile"), "balanced_local_model")
        self.assertEqual(followup_cargo.get("order_number"), "<source-order-recent-1>")
        self.assertEqual(followup_cargo.get("cargo_provider_code"), "ARASMP")
        cargo_quality = followup_cargo.get("visible_answer_quality") or {}
        self.assertTrue(cargo_quality.get("read_used_orders_recent"))
        self.assertTrue(cargo_quality.get("followup_used_contextual_cargo_prepare"))
        self.assertTrue(cargo_quality.get("same_order_number_preserved"))
        self.assertTrue(cargo_quality.get("cargo_provider_code_preserved"))
        self.assertTrue(cargo_quality.get("approval_required"))
        self.assertFalse(cargo_quality.get("api_call_performed"))
        self.assertFalse(cargo_quality.get("db_write_performed"))
        self.assertFalse(cargo_quality.get("execute_performed"))
        self.assertTrue(cargo_quality.get("not_casual_fallback"))
        cargo_joined = json.dumps(followup_cargo, ensure_ascii=False)
        self.assertIn("Tool calisti: orders.recent", cargo_joined)
        self.assertIn("Tool calisti: orders.change_cargo_provider.prepare", cargo_joined)
        self.assertIn("Onay gerekiyor", cargo_joined)
        self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", cargo_joined)
        self.assertIn("payload: order=<source-order-recent-1>, cargo_provider_code=ARASMP", cargo_joined)
        self.assertNotIn("Onayli aksiyon calistirildi", cargo_joined)
        followup_return = recheck.get("return_followup_approve_prepare_recheck") or {}
        self.assertEqual(followup_return.get("read_runtime"), "llama_cpp_server")
        self.assertEqual(followup_return.get("read_profile"), "os_guarded_low_memory")
        self.assertEqual(followup_return.get("followup_runtime"), "rule_fallback")
        self.assertEqual(followup_return.get("followup_profile"), "contextual_write_rule")
        self.assertEqual(followup_return.get("claim_id"), "<source-claim-waiting-1>")
        self.assertEqual(followup_return.get("order_number"), "<source-return-order-1>")
        return_quality = followup_return.get("visible_answer_quality") or {}
        self.assertTrue(return_quality.get("read_used_returns_query"))
        self.assertTrue(return_quality.get("followup_used_contextual_return_approve_prepare"))
        self.assertTrue(return_quality.get("same_claim_id_preserved"))
        self.assertTrue(return_quality.get("same_order_number_preserved"))
        self.assertTrue(return_quality.get("approval_required"))
        self.assertFalse(return_quality.get("api_call_performed"))
        self.assertFalse(return_quality.get("db_write_performed"))
        self.assertFalse(return_quality.get("execute_performed"))
        self.assertTrue(return_quality.get("not_casual_fallback"))
        return_joined = json.dumps(followup_return, ensure_ascii=False)
        self.assertIn("Tool calisti: returns.query", return_joined)
        self.assertIn("Tool calisti: returns.approve.prepare", return_joined)
        self.assertIn("Onay gerekiyor", return_joined)
        self.assertIn("Gercek API istegi veya DB yazimi yapilmadi", return_joined)
        self.assertIn("<source-claim-waiting-1>", return_joined)
        self.assertNotIn("Onayli aksiyon calistirildi", return_joined)
        self.assertNotIn("Iyiyim, buradayim", return_joined)
        leakage_guard = recheck.get("return_query_prompt_leakage_guard_recheck") or {}
        self.assertEqual(leakage_guard.get("runtime"), "llama_cpp_server")
        self.assertEqual(leakage_guard.get("profile"), "os_guarded_low_memory")
        leakage_quality = leakage_guard.get("visible_answer_quality") or {}
        self.assertTrue(leakage_quality.get("used_returns_query"))
        self.assertTrue(leakage_quality.get("prompt_leakage_filtered"))
        self.assertTrue(leakage_quality.get("no_prompt_instruction_visible"))
        self.assertTrue(leakage_quality.get("no_raw_json_visible"))
        self.assertTrue(leakage_quality.get("deterministic_fallback_visible"))
        self.assertTrue(leakage_quality.get("not_casual_fallback"))
        leakage_joined = json.dumps(leakage_guard, ensure_ascii=False)
        self.assertIn("Tool calisti: returns.query", leakage_joined)
        self.assertIn("all doneminde 0 iade eslesti", leakage_joined)
        self.assertNotIn("Bu senin", leakage_joined)
        self.assertNotIn("read-only tool", leakage_joined)
        self.assertNotIn("Uydurma", leakage_joined)
        self.assertNotIn("Gizli anahtar", leakage_joined)
        self.assertNotIn("ham JSON", leakage_joined)
        self.assertEqual((recheck.get("regression_fixed") or {}).get("test"), "test_empty_local_library_auto_selects_cloud_provider")
        self.assertNotIn("D:\\OrderScout\\os-0.3.4\\OrderScout.exe", joined)
        sensitive_values = (
            "".join(("113", "228", "82128")),
            "".join(("112", "680", "67005")),
            "".join(("75a7", "c1c0", "-73a2-49f7-bb8a-", "366dee971405")),
            "".join(("733", "003", "3148238230")),
            " ".join(("Eda", "Tek")),
            " ".join(("Samir", "Abdurrahman")),
            " ".join(("Hayriye", "Aytekin")),
            "".join(("113", "171", "88733")),
        )
        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, joined)


class _CountingClient:
    def __init__(self, client: Callable[[str], str]):
        self._client = client
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(str(prompt or ""))
        return self._client(prompt)


class TestGeminiLiveModelProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not _live_eval_enabled():
            raise unittest.SkipTest("Set ORDERSCOUT_LIVE_LLM_EVAL=1 to run real cloud LLM probes.")
        env_record, env_source, _missing = _direct_env_record()
        if env_record and _compact_text(env_record.get("provider_code")).casefold() == "gemini":
            cls._provider_record, cls._provider_source = env_record, env_source
        else:
            cls._provider_record, cls._provider_source = _app_provider_by_code("gemini")
        if not cls._provider_record:
            raise unittest.SkipTest("No enabled Gemini provider record is available.")

    def test_real_gemini_free_catalog_has_working_chat_candidate(self) -> None:
        record = dict(self._provider_record)
        provider_label = _safe_provider_label(record, self._provider_source)
        catalog_res = list_provider_models(
            provider_code="gemini",
            endpoint_url=record.get("endpoint_url"),
            api_key=record.get("api_key"),
            free_only=True,
            limit=80,
        )
        self.assertTrue(catalog_res.success, catalog_res.message)
        catalog_records = list((catalog_res.data or {}).get("records") or [])
        catalog_ids = [_compact_text(row.get("id")) for row in catalog_records if _compact_text(row.get("id"))]
        self.assertGreater(len(catalog_ids), 0, provider_label)

        preferred = [
            _compact_text(record.get("default_model")),
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemma-3-27b-it",
            "gemma-3n-e4b-it",
        ]
        candidates: list[str] = []
        for candidate in [*preferred, *catalog_ids]:
            if candidate and candidate in catalog_ids and candidate not in candidates:
                candidates.append(candidate)
        max_models = max(1, min(int(os.environ.get("ORDERSCOUT_GEMINI_PROBE_MAX_MODELS", "4")), 8))
        candidates = candidates[:max_models]
        self.assertGreater(len(candidates), 0, provider_label)

        attempts: list[dict[str, Any]] = []
        working_attempts: list[dict[str, Any]] = []
        for candidate in candidates:
            probe_record = dict(record)
            probe_record["default_model"] = candidate
            probe_record["maxOutputTokens"] = 48
            probe_record["temperature"] = 0
            client = build_provider_chat_client(probe_record, timeout=float(os.environ.get("ORDERSCOUT_LIVE_LLM_TIMEOUT", "120")))
            self.assertIsNotNone(client)
            try:
                answer = _compact_text(client("Sadece OK yaz."))
                plan = getattr(client, "resource_plan", {}) or {}
                row = {
                    "requested_model": candidate,
                    "actual_model": _compact_text(plan.get("actual_model")) or _compact_text(getattr(client, "model_name", "")),
                    "fallback_used": bool(plan.get("fallback_used")),
                    "answer": answer,
                    "status": "ok" if answer else "empty",
                }
            except Exception as exc:  # pragma: no cover - live provider behavior
                row = {
                    "requested_model": candidate,
                    "actual_model": "",
                    "fallback_used": False,
                    "answer": "",
                    "status": "error",
                    "error": str(exc),
                }
            attempts.append(row)
            if row.get("status") == "ok":
                working_attempts.append(row)

        artifact_path = _write_live_artifact(
            "live gemini model probe",
            provider_label=provider_label,
            transcript=[
                {
                    "user": "Sadece OK yaz.",
                    "answer": "; ".join(
                        f"{row.get('requested_model')} -> {row.get('answer')}"
                        for row in working_attempts
                    ),
                    "tool_calls": [],
                }
            ],
            extra={
                "catalog_total": len(catalog_ids),
                "catalog_sample": catalog_ids[:20],
                "attempts": attempts,
                "working": working_attempts[0] if working_attempts else {},
                "working_count": len(working_attempts),
            },
        )
        if artifact_path is not None:
            self.assertTrue(artifact_path.exists())
        self.assertGreaterEqual(len(working_attempts), 1, provider_label + "\n" + json.dumps(attempts, ensure_ascii=False, indent=2))


class TestOpenRouterLiveModelProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not _live_eval_enabled():
            raise unittest.SkipTest("Set ORDERSCOUT_LIVE_LLM_EVAL=1 to run real cloud LLM probes.")
        cls._provider_record, cls._provider_source = _app_provider_by_code("openrouter")
        if not cls._provider_record:
            raise unittest.SkipTest("No enabled OpenRouter provider record is available.")

    def test_real_openrouter_free_model_responds_or_records_rate_limit(self) -> None:
        record = dict(self._provider_record)
        provider_label = _safe_provider_label(record, self._provider_source)
        catalog_res = list_provider_models(
            provider_code="openrouter",
            endpoint_url=record.get("endpoint_url"),
            api_key=record.get("api_key"),
            free_only=True,
            limit=80,
        )
        self.assertTrue(catalog_res.success, catalog_res.message)
        catalog_records = list((catalog_res.data or {}).get("records") or [])
        catalog_ids = [_compact_text(row.get("id")) for row in catalog_records if _compact_text(row.get("id"))]
        self.assertGreater(len(catalog_ids), 0, provider_label)

        preferred = [
            _compact_text(record.get("default_model")),
            "google/gemini-2.0-flash-exp:free",
            "google/gemma-3-27b-it:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat-v3-0324:free",
        ]
        candidates: list[str] = []
        for candidate in [*preferred, *catalog_ids]:
            if candidate and candidate in catalog_ids and candidate not in candidates:
                candidates.append(candidate)
        max_models = max(1, min(int(os.environ.get("ORDERSCOUT_OPENROUTER_PROBE_MAX_MODELS", "3")), 8))
        candidates = candidates[:max_models]
        attempts: list[dict[str, Any]] = []
        working_attempts: list[dict[str, Any]] = []
        for candidate in candidates:
            probe_record = dict(record)
            probe_record["default_model"] = candidate
            probe_record["max_tokens"] = 48
            probe_record["temperature"] = 0
            client = build_provider_chat_client(probe_record, timeout=float(os.environ.get("ORDERSCOUT_LIVE_LLM_TIMEOUT", "120")))
            self.assertIsNotNone(client)
            try:
                answer = _compact_text(client("Sadece OK yaz."))
                row = {
                    "requested_model": candidate,
                    "answer": answer,
                    "status": "ok" if answer else "empty",
                }
            except Exception as exc:  # pragma: no cover - live provider behavior
                row = {
                    "requested_model": candidate,
                    "answer": "",
                    "status": "error",
                    "error": str(exc),
                }
            attempts.append(row)
            if row.get("status") == "ok":
                working_attempts.append(row)

        artifact_path = _write_live_artifact(
            "live openrouter model probe",
            provider_label=provider_label,
            transcript=[
                {
                    "user": "Sadece OK yaz.",
                    "answer": "; ".join(
                        f"{row.get('requested_model')} -> {row.get('answer')}"
                        for row in working_attempts
                    ),
                    "tool_calls": [],
                }
            ],
            extra={
                "catalog_total": len(catalog_ids),
                "catalog_sample": catalog_ids[:20],
                "attempts": attempts,
                "working": working_attempts[0] if working_attempts else {},
                "working_count": len(working_attempts),
            },
        )
        if artifact_path is not None:
            self.assertTrue(artifact_path.exists())
        self.assertGreaterEqual(len(working_attempts), 1, provider_label + "\n" + json.dumps(attempts, ensure_ascii=False, indent=2))


class TestLocalModelLiveProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not _truthy_env("ORDERSCOUT_LIVE_LOCAL_MODEL_PROBE"):
            raise unittest.SkipTest("Set ORDERSCOUT_LIVE_LOCAL_MODEL_PROBE=1 to run local llama.cpp model probes.")

    def test_local_gemma_or_gpt_model_responds(self) -> None:
        res = list_installed_models()
        self.assertTrue(res.success, res.message)
        records = [
            dict(row or {})
            for row in ((res.data or {}).get("records") or [])
            if bool(row.get("exists_on_disk")) and _compact_text(row.get("local_path"))
        ]
        preferred_tokens = ("1b", "e4b", "gemma-3", "gemma-4", "gpt-oss", "llama")
        records.sort(
            key=lambda row: (
                next(
                    (idx for idx, token in enumerate(preferred_tokens) if token in f"{row.get('repo_id')} {row.get('filename')}".casefold()),
                    len(preferred_tokens),
                ),
                len(_compact_text(row.get("local_path"))),
            )
        )
        max_models = max(1, min(int(os.environ.get("ORDERSCOUT_LOCAL_PROBE_MAX_MODELS", "1")), 3))
        attempts: list[dict[str, Any]] = []
        working_attempts: list[dict[str, Any]] = []
        try:
            for record in records[:max_models]:
                probe_record = dict(record)
                runtime_config = dict(probe_record.get("runtime_config") or {})
                runtime_config.setdefault("performance_preset", "eco")
                runtime_config.setdefault("num_ctx", 512)
                runtime_config.setdefault("max_tokens", 48)
                runtime_config.setdefault("keep_alive", "0s")
                probe_record["runtime_config"] = runtime_config
                try:
                    client = build_local_planner_client(probe_record)
                    self.assertIsNotNone(client)
                    answer = _compact_text(client("Sadece OK yaz."))
                    row = {
                        "model": _compact_text(record.get("repo_id")) or _compact_text(record.get("display_name")),
                        "filename": _compact_text(record.get("filename")),
                        "runtime_name": _compact_text(getattr(client, "runtime_name", "")),
                        "answer": answer,
                        "status": "ok" if answer else "empty",
                        "resource_plan": getattr(client, "resource_plan", {}) or {},
                    }
                except Exception as exc:  # pragma: no cover - local hardware behavior
                    row = {
                        "model": _compact_text(record.get("repo_id")) or _compact_text(record.get("display_name")),
                        "filename": _compact_text(record.get("filename")),
                        "answer": "",
                        "status": "error",
                        "error": str(exc),
                    }
                attempts.append(row)
                if row.get("status") == "ok":
                    working_attempts.append(row)
        finally:
            shutdown_managed_llama_servers()

        artifact_path = _write_live_artifact(
            "live local model probe",
            provider_label="source=local_models; provider=llama.cpp; model=installed-gguf",
            transcript=[
                {
                    "user": "Sadece OK yaz.",
                    "answer": "; ".join(
                        f"{row.get('model')} -> {row.get('answer')}"
                        for row in working_attempts
                    ),
                    "tool_calls": [],
                }
            ],
            extra={
                "attempts": attempts,
                "working": working_attempts[0] if working_attempts else {},
                "working_count": len(working_attempts),
            },
        )
        if artifact_path is not None:
            self.assertTrue(artifact_path.exists())
        self.assertGreaterEqual(len(working_attempts), 1, json.dumps(attempts, ensure_ascii=False, indent=2))

    def test_best_safe_local_model_has_real_multi_turn_chat_quality(self) -> None:
        def searchable(value: Any) -> str:
            text = unicodedata.normalize("NFKD", _compact_text(value).casefold())
            return "".join(char for char in text if not unicodedata.combining(char))

        res = list_installed_models()
        self.assertTrue(res.success, res.message)
        records = [
            dict(row or {})
            for row in ((res.data or {}).get("records") or [])
            if bool(row.get("exists_on_disk")) and _compact_text(row.get("local_path"))
        ]
        preferred_repos = (
            "jc-builds/gemma-4-e4b-it-gguf",
            "igorls/gemma-4-12b-it-heretic-gguf",
            "antirez/deepseek-v4-gguf",
        )
        selected: dict[str, Any] | None = None
        for repo_id in preferred_repos:
            selected = next(
                (
                    record
                    for record in records
                    if _compact_text(record.get("repo_id")).casefold() == repo_id
                ),
                None,
            )
            if selected:
                break
        self.assertIsNotNone(selected, "No best-safe local quality candidate is installed.")
        record = dict(selected or {})
        runtime_config = dict(record.get("runtime_config") or {})
        runtime_config.update(
            {
                "performance_preset": "balanced",
                "num_ctx": 2048,
                "max_tokens": 384,
                "keep_alive": "0s",
            }
        )
        record["runtime_config"] = runtime_config

        prompts = (
            "naber dayi napiyon",
            "valla biraz keyfim yok, iki laf edelim",
            "e ticaret nasil bisey sence, iyi mi",
            "siparislerimle ilgili neler yapabiliriz",
        )
        history: list[dict[str, str]] = []
        transcript: list[dict[str, Any]] = []
        try:
            client = build_local_planner_client(record)
            self.assertIsNotNone(client)
            for prompt in prompts:
                responses: list[str] = []

                def recording_client(model_prompt: str) -> str:
                    response = _compact_text(client(model_prompt))
                    responses.append(response)
                    return response

                result = run_agent_turn(
                    prompt,
                    planner_client=recording_client,
                    chat_client=recording_client,
                    history=history,
                )
                self.assertTrue(result.success, result.message)
                data = dict(result.data or {})
                answer = _compact_text(data.get("answer") or result.message)
                self.assertTrue(responses, prompt)
                history.extend(
                    [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": answer},
                    ]
                )
                transcript.append(
                    {
                        "user": prompt,
                        "mode": data.get("mode"),
                        "tool": (data.get("tool_call") or {}).get("tool")
                        if isinstance(data.get("tool_call"), dict)
                        else None,
                        "answer": answer,
                        "raw_llm_response": responses[-1],
                        "answer_preserved_from_model": answer == responses[-1],
                    }
                )
        finally:
            shutdown_managed_llama_servers()

        for row in transcript:
            self.assertEqual(row.get("mode"), "answer", row)
            self.assertIsNone(row.get("tool"), row)
            self.assertGreater(len(_compact_text(row.get("answer"))), 20, row)
        for row in transcript[:3]:
            self.assertTrue(row.get("answer_preserved_from_model"), row)
        casual_joined = " ".join(searchable(row.get("answer")) for row in transcript[:3])
        for forbidden in ("nasil yardimci olabilirim", "buradayim. ne yapalim", '"reply"', "tool result"):
            self.assertNotIn(forbidden, casual_joined)
        ecommerce_answer = searchable(transcript[2].get("answer"))
        self.assertTrue(
            any(token in ecommerce_answer for token in ("urun", "musteri", "pazar", "rekabet", "stok", "kargo", "satis")),
            ecommerce_answer,
        )
        capability_answer = searchable(transcript[3].get("answer"))
        for term in ("etiket", "iade", "kargo"):
            self.assertIn(term, capability_answer)

        artifact_path = _write_live_artifact(
            "live local best conversation quality",
            provider_label=(
                "source=local_models; provider=llama.cpp; "
                f"model={_compact_text(record.get('repo_id')) or _compact_text(record.get('filename'))}"
            ),
            transcript=transcript,
            extra={
                "model": {
                    "repo_id": _compact_text(record.get("repo_id")),
                    "filename": _compact_text(record.get("filename")),
                },
                "runtime": _compact_text(getattr(client, "runtime_name", "")),
                "resource_plan": getattr(client, "resource_plan", {}) or {},
                "quality_gates": {
                    "all_turns_tool_free": all(row.get("tool") is None for row in transcript),
                    "all_casual_visible_answers_are_raw_model_answers": all(
                        bool(row.get("answer_preserved_from_model")) for row in transcript[:3]
                    ),
                    "capability_covers_labels_returns_cargo": all(
                        term in capability_answer for term in ("etiket", "iade", "kargo")
                    ),
                },
            },
        )
        if artifact_path is not None:
            self.assertTrue(artifact_path.exists())


class TestOrdersAgenticLiveEval(IsolatedDbTestCase):
    _provider_record: dict[str, Any]
    _provider_source: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not _live_eval_enabled():
            raise unittest.SkipTest("Set ORDERSCOUT_LIVE_LLM_EVAL=1 to run real cloud LLM Orders evals.")
        cls._provider_record, cls._provider_source = _live_provider_record()

    def _client(self):
        record = dict(self._provider_record)
        missing = [key for key in ("provider_code", "api_key", "default_model") if not _compact_text(record.get(key))]
        if missing:
            self.fail("Live LLM provider record is missing required fields: " + ", ".join(missing))
        client = build_provider_chat_client(record, timeout=float(os.environ.get("ORDERSCOUT_LIVE_LLM_TIMEOUT", "120")))
        self.assertIsNotNone(client)
        return _CountingClient(client)

    def _seed_orders_eval_data(self) -> None:
        today = datetime.now(TZ_GMT3).date()
        today_start = int(datetime.combine(today, datetime.min.time(), tzinfo=TZ_GMT3).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            ready_header = OrderHeader(orderNumber="ORD-LIVE-READY", is_printed=False, is_extracted=False)
            risk_header = OrderHeader(orderNumber="ORD-LIVE-RISK", is_printed=False, is_extracted=False)
            session.add(ready_header)
            session.add(risk_header)
            session.flush()
            session.add(
                OrderData(
                    order_header_id=ready_header.pk,
                    orderNumber="ORD-LIVE-READY",
                    id=7101,
                    shipmentPackageId=7101,
                    orderDate=today_start + 1_000,
                    lastModifiedDate=today_start + 2_000,
                    status="Created",
                    shipmentPackageStatus="Created",
                    cargoTrackingNumber="TRK-LIVE",
                    cargoProviderName="Aras",
                    totalPrice=125.0,
                    packageTotalPrice=125.0,
                )
            )
            session.add(
                OrderData(
                    order_header_id=risk_header.pk,
                    orderNumber="ORD-LIVE-RISK",
                    id=7102,
                    shipmentPackageId=7102,
                    orderDate=today_start + 3_000,
                    lastModifiedDate=today_start + 4_000,
                    status="Created",
                    shipmentPackageStatus="Created",
                    totalPrice=225.0,
                    packageTotalPrice=225.0,
                )
            )
            session.add(
                ReturnClaim(
                    claimId="CLAIM-LIVE-WAIT",
                    orderNumber="ORD-LIVE-RETURN",
                    claimDate=today_start + 5_000,
                    orderDate=today_start + 5_000,
                    lastModifiedDate=today_start + 6_000,
                    claimItemStatus="WaitingInAction",
                    totalPrice=75.0,
                    itemCount=1,
                    waitingClaimLineItemIds=["line-live-1"],
                )
            )
            session.commit()

    def test_real_cloud_llm_routes_orders_manual_surface(self) -> None:
        self._seed_orders_eval_data()
        client = self._client()
        cases = [
            {"prompt": "Bugun kac siparisim var?", "tools": {"orders.count", "orders.summary"}, "mode": {"tool", "tools"}},
            {"prompt": "Kargoya hazir yazdirilmamis paketleri listele", "tools": {"orders.ready_to_ship"}, "mode": {"tool"}},
            {"prompt": "Kargo takip veya firma eksigi olan riskli siparisleri goster", "tools": {"orders.fulfillment_risk"}, "mode": {"tool"}},
            {"prompt": "ORD-LIVE-READY siparisinin detayini ve kalemlerini getir", "tools": {"orders.full_context"}, "mode": {"tool"}},
            {"prompt": "Onay bekleyen iadeleri listele", "tools": {"returns.query"}, "mode": {"tool"}},
            {
                "prompt": "UI'da iade var ama Trendyol webde gorunmuyor, stale kayitlari kontrol et",
                "tools": {"returns.reconcile_snapshot"},
                "mode": {"tool"},
            },
            {
                "prompt": "UI'da iade var ama Trendyol webde gorunmuyor, stale kayitlari temizle",
                "tools": {"returns.mark_stale.prepare"},
                "mode": {"approval_required"},
                "approval_required": True,
                "action_type": "orders.mark_return_claims_stale",
                "execute_enabled": False,
            },
            {
                "prompt": "CLAIM-LIVE-WAIT iadesini onaylat",
                "tools": {"returns.approve.prepare"},
                "mode": {"approval_required"},
                "approval_required": True,
                "action_type": "orders.approve_return_claim",
                "execute_enabled": True,
            },
            {
                "prompt": "ORD-LIVE-READY icin etiket olustur",
                "tools": {"labels.create_from_orders.prepare"},
                "mode": {"approval_required"},
                "approval_required": True,
                "action_type": "labels.action_create_labels_from_selected_orders",
                "execute_enabled": True,
            },
            {
                "prompt": "siparis verilerini cek",
                "tools": {"operations.manual_action.route"},
                "mode": {"tool"},
                "route_status": "needs_payload",
                "capability_id": "orders.get_orders_from_companies",
            },
        ]
        failures: list[str] = []
        failed_prompts: set[str] = set()
        rows: list[str] = []
        total_llm_calls = 0
        for case in cases:
            prompt = str(case["prompt"])
            expected_tools = set(case["tools"])
            before_calls = len(client.prompts)
            result = run_agent_turn(prompt, planner_client=client, chat_client=client, db_name=self.db_path)
            llm_calls = len(client.prompts) - before_calls
            total_llm_calls += llm_calls
            if not result.success:
                failures.append(f"{prompt}: {result.message}; llm_calls={llm_calls}")
                failed_prompts.add(prompt)
                continue
            data = result.data or {}
            tool = ((result.data or {}).get("tool_call") or {}).get("tool")
            if not tool and (result.data or {}).get("tool_calls"):
                tool = ((result.data or {}).get("tool_calls") or [{}])[0].get("tool")
            decision_source = (((result.data or {}).get("tool_call") or {}).get("decision_source") or "unknown")
            mode = str(data.get("mode") or "")
            tool_result = data.get("tool_result") if isinstance(data.get("tool_result"), dict) else {}
            action = data.get("action_proposal") if isinstance(data.get("action_proposal"), dict) else None
            if action is None and isinstance(tool_result.get("action"), dict):
                action = tool_result.get("action")
            route_status = str(tool_result.get("route_status") or "")
            capability_id = str((tool_result.get("match") or {}).get("capability_id") or "")
            rows.append(
                f"{prompt}: tool={tool}; mode={mode}; source={decision_source}; "
                f"action_type={(action or {}).get('action_type')}; route_status={route_status}; llm_calls={llm_calls}"
            )
            if llm_calls <= 0:
                failures.append(f"{prompt}: live LLM was not called")
                failed_prompts.add(prompt)
            if tool not in expected_tools:
                failures.append(f"{prompt}: expected one of {sorted(expected_tools)}, got {tool}; source={decision_source}; llm_calls={llm_calls}")
                failed_prompts.add(prompt)
            expected_modes = set(case.get("mode") or [])
            if expected_modes and mode not in expected_modes:
                failures.append(f"{prompt}: expected mode one of {sorted(expected_modes)}, got {mode}")
                failed_prompts.add(prompt)
            if "approval_required" in case and bool(data.get("approval_required")) != bool(case.get("approval_required")):
                failures.append(f"{prompt}: expected approval_required={case.get('approval_required')}, got {data.get('approval_required')}")
                failed_prompts.add(prompt)
            if "action_type" in case and (action or {}).get("action_type") != case.get("action_type"):
                failures.append(f"{prompt}: expected action_type={case.get('action_type')}, got {(action or {}).get('action_type')}")
                failed_prompts.add(prompt)
            if "execute_enabled" in case and bool((action or {}).get("execute_enabled")) != bool(case.get("execute_enabled")):
                failures.append(f"{prompt}: expected execute_enabled={case.get('execute_enabled')}, got {(action or {}).get('execute_enabled')}")
                failed_prompts.add(prompt)
            if "route_status" in case and route_status != case.get("route_status"):
                failures.append(f"{prompt}: expected route_status={case.get('route_status')}, got {route_status}")
                failed_prompts.add(prompt)
            if "capability_id" in case and capability_id != case.get("capability_id"):
                failures.append(f"{prompt}: expected capability_id={case.get('capability_id')}, got {capability_id}")
                failed_prompts.add(prompt)
        pass_rate = (len(cases) - len(failed_prompts)) / len(cases)
        provider_label = _safe_provider_label(self._provider_record, self._provider_source)
        self.assertGreaterEqual(
            total_llm_calls,
            len(cases),
            provider_label + "\nLive LLM was not called for every prompt.\n" + "\n".join(rows),
        )
        self.assertGreaterEqual(
            pass_rate,
            0.80,
            provider_label + f"\npass_rate={pass_rate:.0%}; total_llm_calls={total_llm_calls}\n" + "\n".join(failures + rows),
        )

    def test_real_cloud_llm_recent_old_orders_followup_print_context(self) -> None:
        old_ms = int((datetime.now(TZ_GMT3) - timedelta(days=10)).timestamp() * 1000)
        with Session(get_engine(self.db_path)) as session:
            for index, order_number in enumerate(("ORD-LIVE-OLD-ONE", "ORD-LIVE-OLD-TWO")):
                header = OrderHeader(orderNumber=order_number, is_printed=False, is_extracted=False)
                session.add(header)
                session.flush()
                session.add(
                    OrderData(
                        order_header_id=header.pk,
                        orderNumber=order_number,
                        id=9100 + index,
                        shipmentPackageId=9100 + index,
                        orderDate=old_ms - index,
                        lastModifiedDate=old_ms + index,
                        status="ReadyToShip",
                        shipmentPackageStatus="ReadyToShip",
                        customerFirstName="Live",
                        customerLastName=f"Old {index + 1}",
                        cargoProviderName="Trendyol Express",
                        cargoTrackingNumber=f"TRK-LIVE-OLD-{index + 1}",
                        totalPrice=100.0 + index,
                        packageTotalPrice=100.0 + index,
                    )
                )
            session.commit()

        client = self._client()
        first = run_agent_turn("son gelen 2 siparisi soyle", planner_client=client, chat_client=client, db_name=self.db_path)
        self.assertTrue(first.success, first.message)
        first_data = first.data or {}
        first_tool = first_data.get("tool_call") or {}
        first_args = first_tool.get("arguments") or {}
        first_answer = _compact_text(first_data.get("answer") or first.message)
        self.assertEqual(first_tool.get("tool"), "orders.recent", first_answer)
        self.assertEqual(first_args.get("period"), "all", first_answer)
        self.assertEqual(first_args.get("limit"), 2, first_answer)
        self.assertIn("ORD-LIVE-OLD-ONE", first_answer)
        self.assertIn("ORD-LIVE-OLD-TWO", first_answer)

        second = run_agent_turn(
            "bu iki siparisi yazdir",
            planner_client=client,
            chat_client=client,
            db_name=self.db_path,
            history=[
                {"role": "user", "content": "son gelen 2 siparisi soyle"},
                {"role": "assistant", "content": first_answer},
            ],
        )
        self.assertTrue(second.success, second.message)
        second_data = second.data or {}
        second_tool = second_data.get("tool_call") or {}
        second_result = second_data.get("tool_result") if isinstance(second_data.get("tool_result"), dict) else {}
        action = second_data.get("action_proposal") if isinstance(second_data.get("action_proposal"), dict) else second_result.get("action")
        action = dict(action or {})
        payload = ((action.get("arguments") or {}).get("payload") or {})
        second_answer = _compact_text(second_data.get("answer") or second.message)
        self.assertEqual(second_tool.get("tool"), "labels.create_from_orders.prepare", second_answer)
        self.assertTrue(second_data.get("approval_required"), second_answer)
        self.assertEqual(action.get("action_type"), "labels.action_create_labels_from_selected_orders", second_answer)
        self.assertEqual(payload.get("order_numbers"), ["ORD-LIVE-OLD-ONE", "ORD-LIVE-OLD-TWO"], second_answer)
        self.assertIn("Onay gerekiyor", second_answer)
        self.assertIn("ORD-LIVE-OLD-ONE", second_answer)
        self.assertIn("ORD-LIVE-OLD-TWO", second_answer)

        provider_code = _compact_text(self._provider_record.get("provider_code")) or "provider"
        artifact_path = _write_live_artifact(
            f"live {provider_code} recent old orders followup print context",
            provider_label=_safe_provider_label(self._provider_record, self._provider_source),
            transcript=[
                {
                    "user": "son gelen 2 siparisi soyle",
                    "mode": first_data.get("mode"),
                    "tool": first_tool.get("tool"),
                    "arguments": first_args,
                    "answer": first_answer,
                },
                {
                    "user": "bu iki siparisi yazdir",
                    "mode": second_data.get("mode"),
                    "tool": second_tool.get("tool"),
                    "approval_required": second_data.get("approval_required"),
                    "action_type": action.get("action_type"),
                    "order_numbers": payload.get("order_numbers"),
                    "answer": second_answer,
                },
            ],
            extra={"llm_calls": len(client.prompts)},
        )
        if artifact_path is not None:
            self.assertTrue(artifact_path.exists())
        self.assertGreaterEqual(len(client.prompts), 2)


if __name__ == "__main__":
    unittest.main()
