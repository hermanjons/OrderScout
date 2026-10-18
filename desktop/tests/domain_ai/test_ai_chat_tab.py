from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from AI.views.chat_tab import (
    AITab,
    DB_NAME,
    _chat_data_from_task_result,
    _cloud_provider_sort_key,
    _format_runtime_activity,
    _orders_task_requested,
    _run_approved_chat_action,
    _run_chat_turn_with_runtime,
    _task_domain_requested,
)
from AI.processors.session_state import AgentSessionState, PendingActionSnapshot, SelectionSnapshot
from AI.processors.task_runtime import safe_agent_runtime_context
from Feedback.processors.pipeline import Result


class _RunningWorker:
    def isRunning(self) -> bool:
        return True


class _BlockedPlan:
    safe_to_run = False
    profile = "blocked_insufficient_memory"
    reason = "OS koruma rezervi"
    num_ctx = 512
    max_tokens = 256


class _SafePlan:
    safe_to_run = True
    profile = "os_guarded_low_memory"
    reason = ""
    num_ctx = 768
    max_tokens = 256


class _SignalProbe:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _DeferredWorker:
    instances = []

    def __init__(self, func, *args, parent=None, **kwargs):
        self.func = func
        self.args = args
        self.parent = parent
        self.kwargs = kwargs
        self.result_ready = _SignalProbe()
        self.progress = _SignalProbe()
        self.finished = _SignalProbe()
        self.started = False
        type(self).instances.append(self)

    def isRunning(self) -> bool:
        return self.started

    def start(self) -> None:
        self.started = True


class _ImmediateWorker(_DeferredWorker):
    def start(self) -> None:
        self.started = True
        kwargs = dict(self.kwargs)
        progress_callback_kw = str(kwargs.pop("progress_callback_kw", "") or "")
        if progress_callback_kw:
            kwargs[progress_callback_kw] = (
                lambda percent, message: [
                    callback(percent, message)
                    for callback in list(self.progress.callbacks)
                ]
            )
        result = self.func(*self.args, **kwargs)
        if not isinstance(result, Result):
            result = Result.ok("Worker tamamlandi.", close_dialog=False, data={"result": result})
        for callback in list(self.result_ready.callbacks):
            callback(result)
        self.started = False
        for callback in list(self.finished.callbacks):
            callback()


class TestAiChatTab(unittest.TestCase):
    def test_stock_operation_prompt_selects_registered_stock_task_domain(self) -> None:
        self.assertEqual(_task_domain_requested("Stok operasyonunu toparla"), "stock")
        self.assertEqual(
            _task_domain_requested("Stok durumunu ve kritik dusuk stoklari ozetle"),
            "stock",
        )
        self.assertEqual(_task_domain_requested("Stok urunlerini listele"), "")

    def test_registered_business_domains_route_to_task_runtime_from_source_ui(self) -> None:
        cases = {
            "Finans operasyonunu toparla": "finance",
            "Ilan operasyonunu toparla": "listing",
            "Lojistik operasyonunu toparla": "logistics",
            "Pazaryeri operasyonunu toparla": "marketplaces",
        }
        for prompt, expected_domain in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(_task_domain_requested(prompt), expected_domain)

    def test_registered_business_domain_write_goals_route_to_task_runtime_only_with_task_intent(self) -> None:
        cases = {
            "Stok gorevi olarak yeni bir stok karti olustur": "stock",
            "Finans gorevi olarak yeni bir maliyet kalemi ekle": "finance",
            "Ilan gorevi olarak bu urunun fiyatini guncelle": "listing",
            "Lojistik gorevi olarak yeni bir kargo tarifesi kaydet": "logistics",
            "Pazaryeri gorevi olarak Trendyol kaydini guncelle": "marketplaces",
        }
        for prompt, expected_domain in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(_task_domain_requested(prompt), expected_domain)

        self.assertEqual(
            _task_domain_requested("Yeni bir finans maliyet kalemi ekle"),
            "",
            "Tek adimli write istegi mevcut dogrudan prepare/approval yolunu kullanmali.",
        )

    def test_cloud_stock_task_runs_registered_task_runtime(self) -> None:
        def planner(prompt: str) -> str:
            if prompt.startswith("OrderScout typed tur yorumu"):
                return json.dumps(
                    {
                        "mode": "inspect",
                        "domain": "stock",
                        "objective": "Stok operasyonunu toparla",
                        "intent_kind": "data_read",
                        "requested_fields": [],
                        "entity": "stock_item",
                        "metric": "summary",
                        "status_scope": "all",
                        "period": "all",
                        "freshness": "local_snapshot",
                        "reason": "Stok ozeti istendi.",
                        "requires_clarification": False,
                        "clarification": "",
                    }
                )
            return '{"steps":[{"id":"stock.inventory_overview"}]}'

        setattr(planner, "runtime_name", "gemini_chat")
        setattr(planner, "model_name", "gemini-2.5-flash")
        setattr(planner, "resource_plan", {"actual_model": "gemini-2.5-flash"})
        state = {
            "session_id": "stock-task-1",
            "active_domain": "stock",
            "status": "complete",
            "completed_steps": [
                {"step_id": "stock.inventory_overview", "tool_names": ["stock.inventory_overview"], "status": "completed"}
            ],
            "remaining_steps": [],
            "pending_actions": [],
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={"record": {"id": 43, "provider_code": "gemini", "api_key": "secret", "default_model": "gemini-2.5-flash"}},
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok("ok", close_dialog=False, data={"state": state}),
        ) as task_mock:
            prior_conversation_state = AgentSessionState(
                goal="OrderScout AI conversation",
                active_domain="orders",
            ).to_dict()
            result = _run_chat_turn_with_runtime(
                "Stok operasyonunu toparla",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
                session_state=prior_conversation_state,
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(task_mock.call_args.kwargs.get("domain"), "stock")
        self.assertTrue(task_mock.call_args.kwargs.get("persist"))
        self.assertEqual(
            task_mock.call_args.kwargs.get("session_state"),
            prior_conversation_state,
        )
        self.assertEqual((result.data or {}).get("session_state"), state)

    def test_model_interpretation_routes_simple_orders_inspection_to_unified_task_runtime(self) -> None:
        self.assertEqual(
            _task_domain_requested("kac siparis var bekleyen"),
            "",
            "Regression precondition: the old keyword task gate misses this natural prompt.",
        )

        def planner(prompt: str) -> str:
            self.assertIn("OrderScout typed tur yorumu", prompt)
            return json.dumps(
                {
                    "mode": "inspect",
                    "domain": "orders",
                    "objective": "Kargoya hazir bekleyen siparislerin authoritative sayisini getir",
                    "reason": "Kullanici Orders verisi soruyor.",
                    "requires_clarification": False,
                }
            )

        setattr(planner, "runtime_name", "openrouter_chat")
        setattr(planner, "model_name", "test-model")
        setattr(planner, "resource_plan", {"actual_model": "test-model"})
        task_state = {
            "session_id": "simple-inspect-task",
            "active_domain": "orders",
            "status": "complete",
            "active_entities": {"final_answer": "Kargoya hazir 4 siparis var."},
            "completed_steps": [
                {
                    "step_id": "ready_count",
                    "tool_names": ["orders.ready_to_ship_count"],
                    "status": "completed",
                }
            ],
            "remaining_steps": [],
            "pending_actions": [],
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "openrouter",
                        "api_key": "secret",
                        "default_model": "test-model",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok("ok", close_dialog=False, data={"state": task_state}),
        ) as task_mock, patch("AI.views.chat_tab.run_agent_turn") as turn_mock:
            result = _run_chat_turn_with_runtime(
                "kac siparis var bekleyen",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        task_mock.assert_called_once()
        turn_mock.assert_not_called()
        self.assertEqual(task_mock.call_args.kwargs.get("domain"), "orders")
        interpretation = task_mock.call_args.kwargs.get("turn_interpretation") or {}
        self.assertEqual(interpretation.get("mode"), "inspect")
        self.assertTrue(interpretation.get("planner_invoked"))

    def test_source_chat_projects_orders_capabilities_from_canonical_catalog(self) -> None:
        def planner(_prompt: str) -> str:
            return json.dumps(
                {
                    "mode": "explain",
                    "domain": "orders",
                    "objective": "Orders yeteneklerini açıkla",
                    "intent_kind": "capability_overview",
                    "requested_fields": [],
                    "reason": "Kullanıcı Orders tarafında neler yapılabildiğini soruyor.",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            )

        setattr(planner, "runtime_name", "gemini_chat")
        setattr(planner, "model_name", "gemini-test")
        setattr(planner, "resource_plan", {"actual_model": "gemini-test"})
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "secret",
                        "default_model": "gemini-test",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_model_conversation_turn"
        ) as prose_mock, patch(
            "AI.views.chat_tab.run_agent_task"
        ) as task_mock:
            result = _run_chat_turn_with_runtime(
                "Peki siparişler tarafında seninle neler yapabiliriz?",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        prose_mock.assert_not_called()
        task_mock.assert_not_called()
        data = result.data or {}
        self.assertEqual(
            data.get("decision_path"), "typed_capability_catalog_grounded"
        )
        self.assertEqual(
            [row.get("tool") for row in data.get("direct_tool_calls") or []],
            ["operations.capability_catalog"],
        )
        answer = str(data.get("answer") or result.message)
        for token in ("etiket", "İadeleri", "kargo", "Excel", "web", "onaylamadan execute etmem"):
            self.assertIn(token, answer)

    def test_pending_action_read_is_answered_from_typed_state_before_provider_or_tools(
        self,
    ) -> None:
        state = AgentSessionState(
            goal="11 siparis icin TANEX 2610 etiket hazirligi",
            active_domain="orders",
            status="pending_approval",
        )
        action = state.add_pending_action(
            {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "source_tool": "labels.create_from_orders.prepare",
                "risk_level": "medium",
                "execute_enabled": True,
                "arguments": {
                    "payload": {
                        "order_numbers": ["ORD-PENDING-1", "ORD-PENDING-2"],
                        "brand_code": "TANEX",
                        "model_code": "TANEX_2610",
                    }
                },
                "rows": [
                    {"order_number": "ORD-PENDING-1"},
                    {"order_number": "ORD-PENDING-2"},
                ],
            }
        )
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account"
        ) as account_mock, patch(
            "AI.views.chat_tab.build_provider_chat_client"
        ) as provider_mock, patch(
            "AI.views.chat_tab.interpret_agent_turn"
        ) as interpretation_mock, patch(
            "AI.views.chat_tab.run_agent_task"
        ) as task_mock:
            result = _run_chat_turn_with_runtime(
                "Bu hazırlık hangi sipariş kümesine ve hangi şablona bağlı, "
                "herhangi bir dosya üretildi mi?",
                source="cloud",
                runtime_record={
                    "id": 43,
                    "provider_code": "gemini",
                    "default_model": "gemini-test",
                },
                history=[],
                session_state=state.to_dict(),
            )

        self.assertTrue(result.success, result.message)
        account_mock.assert_not_called()
        provider_mock.assert_not_called()
        interpretation_mock.assert_not_called()
        task_mock.assert_not_called()
        data = result.data or {}
        answer = data.get("answer") or result.message
        self.assertEqual(data.get("decision_path"), "pending_action_scope_read_guard")
        self.assertEqual(data.get("tool_calls"), [])
        self.assertFalse(data.get("model_invocation_attempted"))
        self.assertFalse(data.get("model_response_received"))
        self.assertFalse(data.get("model_invoked"))
        self.assertFalse(data.get("accepted_semantic_output"))
        self.assertEqual(
            data.get("final_response_source"),
            "typed_pending_state_projection",
        )
        self.assertTrue(data.get("pending_action_read_only"))
        self.assertTrue(data.get("pending_action_preserved"))
        self.assertEqual(data.get("active_pending_action_id"), action["action_id"])
        self.assertIn("2 sipariş", answer)
        self.assertIn("TANEX 2610", answer)
        self.assertIn("ORD-PENDING-1", answer)
        self.assertIn("ORD-PENDING-2", answer)
        self.assertIn("dosya/çıktı üretimi", answer)
        returned_state = AgentSessionState.from_dict(data.get("session_state") or {})
        self.assertEqual(returned_state.status, "pending_approval")
        self.assertEqual(
            (returned_state.active_pending_action() or {}).get("action_id"),
            action["action_id"],
        )

    def test_model_interpretation_keeps_hypothetical_action_question_tool_free(self) -> None:
        def planner(prompt: str) -> str:
            if prompt.startswith("OrderScout typed tur yorumu"):
                return json.dumps(
                    {
                        "mode": "act",
                        "domain": "orders",
                        "objective": "Secili siparislerin etiketlerini hazirla",
                        "intent_kind": "action",
                        "requested_fields": ["action_result"],
                        "reason": "Model varsayimsal soruyu yanlislikla action sandi.",
                        "requires_clarification": False,
                        "clarification": "",
                    }
                )
            self.assertIn("Bu turda tool yoktur", prompt)
            return "Yazdırmanı isteseydin önce kesin sipariş kapsamını gösterip onayını beklerdim."

        setattr(planner, "runtime_name", "gemini_chat")
        setattr(planner, "model_name", "test-model")
        setattr(planner, "resource_plan", {"actual_model": "test-model"})
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "secret",
                        "default_model": "test-model",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch("AI.views.chat_tab.run_agent_task") as task_mock, patch(
            "AI.views.chat_tab.run_agent_turn"
        ) as turn_mock:
            result = _run_chat_turn_with_runtime(
                "Bu siparisleri yazdir desem ne yapardin?",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        task_mock.assert_not_called()
        turn_mock.assert_not_called()
        self.assertEqual((result.data or {}).get("tool_names"), [])
        self.assertEqual(
            (result.data or {}).get("decision_path"),
            "typed_model_non_business_turn",
        )
        interpretation = (result.data or {}).get("turn_interpretation") or {}
        self.assertEqual(interpretation.get("mode"), "explain")
        self.assertEqual(interpretation.get("intent_kind"), "conversation")
        self.assertEqual(interpretation.get("requested_fields"), [])
        self.assertIn(
            "hypothetical_action_mode_to_explain",
            interpretation.get("semantic_corrections") or [],
        )
        answer = (result.data or {}).get("answer") or ""
        self.assertIn("dry-run", answer)
        self.assertIn("açık onayın", answer)
        self.assertIn("yeniden okuyarak", answer)
        self.assertIn(
            "hypothetical_action_answer_to_canonical_safety_explanation",
            (result.data or {}).get("response_semantic_corrections") or [],
        )

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            try:
                widget.close()
            except Exception:
                pass
            try:
                widget.deleteLater()
            except Exception:
                pass
        self._app.processEvents()

    def test_cloud_provider_sort_prefers_validated_gemini_free_model(self) -> None:
        records = [
            {"label": "OpenRouter Planner", "provider_code": "openrouter", "default_model": "nvidia/nemotron-3-nano-30b-a3b:free"},
            {"label": "Gemini Lite", "provider_code": "gemini", "default_model": "gemini-2.5-flash-lite"},
            {"label": "Gemini 3.1 Lite", "provider_code": "gemini", "default_model": "gemini-3.1-flash-lite"},
        ]

        ordered = sorted(records, key=_cloud_provider_sort_key)

        self.assertEqual([row["label"] for row in ordered], ["Gemini 3.1 Lite", "Gemini Lite", "OpenRouter Planner"])

    def test_chat_exposes_segmented_source_and_conversation_controls(self) -> None:
        tab = AITab()

        self.assertTrue(tab.source_combo.isHidden())
        self.assertFalse(tab.btn_source_local.isHidden())
        self.assertFalse(tab.btn_source_cloud.isHidden())
        self.assertTrue(tab.btn_source_local.isChecked())
        self.assertTrue(tab.cloud_filter_shell.isHidden())
        self.assertTrue(tab.fallback_checkbox.isHidden())

        with patch.object(tab, "_refresh_current_source") as refresh_mock:
            tab._set_source_from_segment("cloud")

        self.assertTrue(tab.btn_source_cloud.isChecked())
        self.assertFalse(tab.cloud_filter_shell.isHidden())
        self.assertFalse(tab.fallback_checkbox.isHidden())
        refresh_mock.assert_called_once()

    def test_cloud_models_are_grouped_under_provider_with_live_route_metadata(self) -> None:
        tab = AITab()
        route = {
            "provider_code": "openrouter",
            "ordered_model_ids": ["openai/gpt-oss-120b:free", "qwen/qwen3-coder:free"],
        }
        tab._populate_cloud_model_list(
            [
                {
                    "provider": {"id": 7, "provider_code": "openrouter", "label": "OpenRouter"},
                    "route": route,
                    "models": [
                        {
                            "id": "openai/gpt-oss-120b:free",
                            "name": "GPT OSS 120B",
                            "is_free": True,
                            "capability_profile": {"tool_calling": True},
                        },
                        {
                            "id": "qwen/qwen3-coder:free",
                            "name": "Qwen3 Coder",
                            "is_free": True,
                            "capability_profile": {"tool_calling": True},
                        },
                    ],
                }
            ]
        )

        self.assertEqual(tab.model_list.count(), 3)
        header = tab.model_list.item(0).data(Qt.ItemDataRole.UserRole)
        self.assertEqual(header.get("_source_kind"), "cloud_provider_header")
        self.assertTrue(bool(tab.model_list.item(0).flags() & Qt.ItemFlag.ItemIsSelectable))
        selected = tab._selected_provider_record()
        self.assertIsNotNone(selected)
        self.assertEqual(selected.get("default_model"), "openai/gpt-oss-120b:free")
        self.assertEqual(selected.get("free_model_test_route"), route)
        self.assertTrue(selected.get("model_metadata", {}).get("capability_profile", {}).get("tool_calling"))

        tab._on_model_list_item_clicked(tab.model_list.item(0))
        self.assertEqual(tab.model_list.count(), 1)
        tab._on_model_list_item_clicked(tab.model_list.item(0))
        self.assertEqual(tab.model_list.count(), 3)

    def test_advanced_settings_change_only_the_selected_chat_model_record(self) -> None:
        tab = AITab()
        first = QListWidgetItem("Yerel A")
        first.setData(
            Qt.ItemDataRole.UserRole,
            {
                "_source_kind": "local_model",
                "repo_id": "orderscout/model-a",
                "filename": "model-a.gguf",
                "resource_plan": {
                    "safe_to_run": True,
                    "profile": "fixture",
                    "num_ctx": 1024,
                    "max_tokens": 128,
                },
            },
        )
        second = QListWidgetItem("Yerel B")
        second.setData(
            Qt.ItemDataRole.UserRole,
            {
                "_source_kind": "local_model",
                "repo_id": "orderscout/model-b",
                "filename": "model-b.gguf",
                "resource_plan": {
                    "safe_to_run": True,
                    "profile": "fixture",
                    "num_ctx": 1024,
                    "max_tokens": 128,
                },
            },
        )
        tab.model_list.addItem(first)
        tab.model_list.addItem(second)
        tab.model_list.setCurrentItem(first)

        tab._apply_advanced_model_settings(first, {"num_ctx": 4096, "temperature": 0.2})

        self.assertEqual(first.data(Qt.ItemDataRole.UserRole).get("num_ctx"), 4096)
        self.assertEqual(first.data(Qt.ItemDataRole.UserRole).get("temperature"), 0.2)
        self.assertNotIn("num_ctx", second.data(Qt.ItemDataRole.UserRole))
        self.assertIn("yaln", tab.model_status.text().casefold())

    def test_advanced_popup_can_restore_its_conversation_defaults(self) -> None:
        tab = AITab()
        item = QListWidgetItem("Yerel model")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "_source_kind": "local_model",
                "repo_id": "orderscout/local-model",
                "filename": "local-model.gguf",
                "temperature": 0.2,
                "resource_plan": {
                    "safe_to_run": True,
                    "profile": "fixture",
                    "num_ctx": 8192,
                    "max_tokens": 1024,
                },
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentItem(item)

        tab._open_advanced_model_settings()
        self._app.processEvents()
        dialog = tab._advanced_dialog
        self.assertIsNotNone(dialog)
        dialog._fields["temperature"].setText("0.85")
        dialog._reset_defaults()

        self.assertEqual(dialog._fields["temperature"].text(), "0.2")
        self.assertIn("num_gpu", dialog._fields)
        self.assertEqual(dialog.minimumHeight(), 590)

    def test_advanced_popup_disables_unsupported_provider_settings_and_omits_them_on_apply(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        item = QListWidgetItem("Cloud model")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "id": 7,
                "_source_kind": "cloud_model",
                "provider_code": "fixture",
                "default_model": "fixture/capability-model",
                "model_metadata": {
                    "capability_profile": {
                        "supported_model_settings": ["num_ctx", "max_tokens", "top_p"],
                    }
                },
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentItem(item)

        tab._open_advanced_model_settings()
        self._app.processEvents()
        dialog = tab._advanced_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog._fields["num_ctx"].isEnabled())
        self.assertFalse(dialog._fields["temperature"].isEnabled())
        self.assertIn("temperature", dialog._unsupported_fields)

        dialog._fields["num_ctx"].setText("32768")
        dialog._fields["temperature"].setText("0.95")
        dialog._apply()
        self._app.processEvents()

        applied = item.data(Qt.ItemDataRole.UserRole)
        self.assertEqual(applied.get("num_ctx"), 32768)
        self.assertNotIn("temperature", applied)

    def test_contextual_followup_can_start_orders_task_without_repeating_domain_name(self) -> None:
        history = [
            {"role": "user", "content": "Son iki siparisi getir"},
            {"role": "assistant", "content": "1. ORD-CHAT-TASK-1\n2. ORD-CHAT-TASK-2"},
        ]

        self.assertTrue(
            _orders_task_requested(
                "bunlari yazdir, sonra fis cikarildi isaretle; bitene kadar devam et",
                history=history,
            )
        )
        self.assertFalse(
            _orders_task_requested(
                "bunlari bitene kadar devam et",
                history=[{"role": "assistant", "content": "Film listesini konusuyorduk."}],
            )
        )

    def test_natural_compound_orders_request_starts_task_without_task_keywords(self) -> None:
        self.assertTrue(
            _orders_task_requested(
                "son 2 siparisi getir, sonra yazdir ve fis cikarildi olarak isaretle",
                history=[],
            )
        )
        self.assertTrue(
            _orders_task_requested(
                "siparisleri getir ve etiketlerini yazdir",
                history=[],
            )
        )
        self.assertFalse(
            _orders_task_requested(
                "son 2 siparisi getir",
                history=[],
            )
        )
        self.assertFalse(
            _orders_task_requested(
                "siparisleri getir ve durumlarini goster",
                history=[],
            )
        )
        self.assertTrue(
            _orders_task_requested(
                "ORD-EXPLICIT-1 ve ORD-EXPLICIT-2 yazdir, sonra fis cikarildi isaretle",
                history=[],
            )
        )

    def test_post_operation_advice_question_does_not_start_task_runtime(self) -> None:
        self.assertFalse(
            _orders_task_requested(
                "tamam dosyayı gördüm, bu kadar gecikmiş siparişte ilk operasyonel hamlem ne olmalı",
                history=[
                    {
                        "role": "assistant",
                        "content": "21 siparis icin etiket DOCX dosyasi dogrulandi.",
                    }
                ],
            )
        )

    def test_historical_label_reference_with_repeat_analysis_does_not_start_task(self) -> None:
        self.assertFalse(
            _orders_task_requested(
                "iadeleri şimdilik bir kenara bırakalım; başta etiket "
                "hazırladığımız 21 siparişin gecikme analizini tekrar göster",
                history=[
                    {
                        "role": "assistant",
                        "content": "21 sipariş için etiket oluşturuldu.",
                    }
                ],
            )
        )

    def test_composer_accepts_guidance_while_agent_worker_is_running(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        item = QListWidgetItem("Gemma 4")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "repo_id": "jc-builds/Gemma-4-E4B-it-GGUF",
                "filename": "Gemma-4-E4B-it-Q4_K_M.gguf",
                "resource_plan": {
                    "safe_to_run": True,
                    "profile": "test_safe",
                    "reason": "",
                    "num_ctx": 512,
                    "max_tokens": 128,
                },
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)
        tab.composer.setPlainText("Bugün kaç siparişim var?")

        tab._chat_worker = _RunningWorker()
        tab._update_chat_controls()

        self.assertTrue(tab.btn_send.isEnabled())
        self.assertTrue(tab.composer.isEnabled())
        self.assertEqual(tab.btn_send.text(), "Yönlendir")

        tab._chat_worker = None
        tab._update_chat_controls()

        self.assertTrue(tab.btn_send.isEnabled())
        self.assertTrue(tab.composer.isEnabled())
        self.assertEqual(tab.btn_send.text(), "Gönder")


    def test_agent_activity_is_visible_in_transcript(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        tab._append_chat_activity("Istegi analiz ediyorum.")

        self.assertIn("Istegi analiz ediyorum.", tab.transcript.toPlainText())
        self.assertGreater(tab._chat_message_count, 0)

    def test_chat_surface_layout_contract_keeps_readable_messages_and_inline_approval(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        self.assertEqual(tab.transcript.objectName(), "AiTranscript")
        self.assertEqual(tab.composer.objectName(), "AiComposer")
        self.assertEqual(tab.btn_send.objectName(), "AiSendButton")
        self.assertLessEqual(tab.composer.maximumHeight(), 62)
        self.assertLessEqual(tab.composer.parentWidget().maximumHeight(), 128)

        tab._append_chat_message("user", "son gelen iki siparisi yazdir")
        tab._append_chat_message("assistant", "Iki siparis buldum, onay hazirliyorum.")
        tab._append_chat_activity("Tool calisti: labels.create_from_orders.prepare")
        action = {
            "title": "Siparis etiketi olusturma onayi",
            "summary": "2 siparis icin etiket olusturma hazirlaniyor.",
            "risk_level": "medium",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "arguments": {"payload": {"order_numbers": ["ORD-UI-LAYOUT-1", "ORD-UI-LAYOUT-2"]}},
            "rows": [
                {"title": "Etiket", "payload": {"order_numbers": ["ORD-UI-LAYOUT-1"]}},
                {"title": "Etiket", "payload": {"order_numbers": ["ORD-UI-LAYOUT-2"]}},
            ],
        }
        tab._show_action_approval_dialog(action)

        plain = tab.transcript.toPlainText()
        html_text = tab.transcript.toHtml().casefold()
        self.assertEqual(tab.chat_stack.currentIndex(), 1)
        self.assertIn("Sen", plain)
        self.assertIn("OrderScout AI", plain)
        self.assertIn("Tool calisti: labels.create_from_orders.prepare", plain)
        self.assertIn("Onay gerekiyor", plain)
        self.assertIn("Vazgeç Onayla ve çalıştır", plain)
        self.assertIn("orderscout://approval/approve/", html_text)
        self.assertIn("orderscout://approval/cancel/", html_text)
        self.assertIn("background-color:#2563eb", html_text)
        self.assertIn("background-color:#ffffff", html_text)
        self.assertTrue(
            "background-color:#eef2f7" in html_text
            or 'bgcolor="#eef2f7"' in html_text
        )
        self.assertIn("color:#c2410c", html_text)
        self.assertEqual(len(tab._approval_card_actions), 1)
        self.assertIn(tab._latest_approval_card_token, tab._approval_card_actions)

    def test_chat_tab_ui_smoke_artifact_captures_pending_approval_and_execute(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        action = {
            "title": "Siparis etiketi olusturma onayi",
            "summary": "2 siparis icin etiket olusturma hazirlaniyor.",
            "risk_level": "medium",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "arguments": {"payload": {"order_numbers": ["ORD-UI-SMOKE-1", "ORD-UI-SMOKE-2"]}},
            "rows": [
                {"title": "Siparis etiketi olusturma onayi", "payload": {"order_numbers": ["ORD-UI-SMOKE-1"]}},
                {"title": "Siparis etiketi olusturma onayi", "payload": {"order_numbers": ["ORD-UI-SMOKE-2"]}},
            ],
        }
        data = {
            "mode": "approval_required",
            "approval_required": True,
            "tool_calls": [
                {
                    "tool": "labels.create_from_orders.prepare",
                    "arguments": {"order_numbers": ["ORD-UI-SMOKE-1", "ORD-UI-SMOKE-2"]},
                }
            ],
            "action_proposal": action,
            "answer": "Onay gerekiyor: 2 siparis icin etiket olusturma hazirlaniyor.",
        }

        tab._append_chat_message("user", "son gelen iki siparisi yazdir")
        tab._append_chat_activity("Tool calisti: labels.create_from_orders.prepare")
        tab._update_agent_state_from_result_data(data)
        tab._append_chat_message("assistant", data["answer"])

        self.assertFalse(tab.agent_state_card.isVisible())
        self.assertIn("Onay", tab.agent_state_title.text())
        self.assertIn("labels.create_from_orders.prepare", tab.agent_state_text.text())
        self.assertIn("ORD-UI-SMOKE", tab.agent_state_pending.text())
        before_approval_state = {
            "status": tab._agent_state.get("status"),
            "title": tab.agent_state_title.text(),
            "text": tab.agent_state_text.text(),
            "pending": tab.agent_state_pending.text(),
            "history": tab.agent_state_history.text(),
        }

        execute_result = Result.ok(
            "Runtime execute edildi.",
            close_dialog=False,
            data={
                "verify": {
                    "verified": True,
                    "verified_by": "payload_and_docx_content",
                    "docx_order_numbers_verified": True,
                    "order_numbers": ["ORD-UI-SMOKE-1", "ORD-UI-SMOKE-2"],
                    "output_path": "C:/tmp/agent-labels.docx",
                },
                "audit": {"operation": "labels.action_create_labels_from_selected_orders"},
            },
        )
        tab._show_action_approval_dialog(action)
        card_text = tab.transcript.toPlainText()
        self.assertIn("Onay gerekiyor", card_text)
        self.assertIn("Onayla ve çalıştır", card_text)
        self.assertIn("Vazgeç", card_text)

        with patch(
            "AI.views.chat_tab.execute_approved_operation",
            return_value=execute_result,
        ) as execute_mock, patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
            tab.composer.setPlainText("onayla")
            tab._send_message()

        execute_mock.assert_called_once()
        transcript_text = tab.transcript.toPlainText()
        self.assertIn("son gelen iki siparisi yazdir", transcript_text)
        self.assertIn("Tool calisti: labels.create_from_orders.prepare", transcript_text)
        self.assertIn("Onayli aksiyon calistirildi", transcript_text)
        self.assertIn("verify: dogrulandi", transcript_text)
        self.assertIn("kanit: payload_and_docx_content", transcript_text)
        self.assertIn("siparis: ORD-UI-SMOKE-1, ORD-UI-SMOKE-2", transcript_text)
        self.assertIn("cikti: C:/tmp/agent-labels.docx", transcript_text)
        self.assertIn("audit: labels.action_create_labels_from_selected_orders", transcript_text)
        self.assertEqual(tab._agent_state.get("status"), "executed")
        self.assertIn("Runtime execute edildi", tab.agent_state_text.text())

        additional_scenarios = []

        def _exercise_ui_write_scenario(
            *,
            name: str,
            user_prompt: str,
            tool_name: str,
            approval_action: dict,
            answer: str,
            execute_verify: dict,
        ) -> None:
            scenario_data = {
                "mode": "approval_required",
                "approval_required": True,
                "tool_calls": [{"tool": tool_name, "arguments": {}}],
                "action_proposal": approval_action,
                "answer": answer,
            }
            tab._append_chat_message("user", user_prompt)
            tab._append_chat_activity(f"Tool calisti: {tool_name}")
            tab._update_agent_state_from_result_data(scenario_data)
            tab._append_chat_message("assistant", answer)
            before_state = {
                "status": tab._agent_state.get("status"),
                "title": tab.agent_state_title.text(),
                "text": tab.agent_state_text.text(),
                "pending": tab.agent_state_pending.text(),
                "history": tab.agent_state_history.text(),
            }
            scenario_result = Result.ok("Runtime execute edildi.", close_dialog=False, data={"verify": execute_verify})
            tab._show_action_approval_dialog(approval_action)
            with patch(
                "AI.views.chat_tab.execute_approved_operation",
                return_value=scenario_result,
            ) as scenario_execute_mock, patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
                tab.composer.setPlainText("onayla")
                tab._send_message()
            scenario_execute_mock.assert_called_once()
            additional_scenarios.append(
                {
                    "name": name,
                    "user_prompt": user_prompt,
                    "tool": tool_name,
                    "before_approval_state": before_state,
                    "after_execute_state": {
                        "status": tab._agent_state.get("status"),
                        "title": tab.agent_state_title.text(),
                        "text": tab.agent_state_text.text(),
                        "pending": tab.agent_state_pending.text(),
                        "history": tab.agent_state_history.text(),
                    },
                    "execute_called": scenario_execute_mock.called,
                    "execute_action_type": scenario_execute_mock.call_args.args[0].get("action_type"),
                    "execute_verify": execute_verify,
                }
            )

        _exercise_ui_write_scenario(
            name="return_approval",
            user_prompt="Mahmut olan iadeyi onayla",
            tool_name="returns.approve.prepare",
            approval_action={
                "title": "Iade onayi",
                "summary": "CLAIM-UI-SMOKE iadesi onaylanacak.",
                "risk_level": "high",
                "action_type": "orders.approve_return_claim",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {"payload": {"claim_id": "CLAIM-UI-SMOKE", "order_number": "ORD-UI-SMOKE-RETURN"}},
                "rows": [{"title": "Iade onayi", "payload": {"claim_id": "CLAIM-UI-SMOKE"}}],
            },
            answer="Onay gerekiyor: CLAIM-UI-SMOKE iadesi onaylanmaya hazirlaniyor.",
            execute_verify={"verified": True, "claim_ids": ["CLAIM-UI-SMOKE"], "status": "Accepted"},
        )
        _exercise_ui_write_scenario(
            name="cargo_change",
            user_prompt="Mahmut olan siparisin kargosunu Aras yap",
            tool_name="orders.change_cargo_provider.prepare",
            approval_action={
                "title": "Kargo degisikligi onayi",
                "summary": "ORD-UI-SMOKE-CARGO siparisi ARAS kargoya alinacak.",
                "risk_level": "high",
                "action_type": "orders.change_order_cargo_provider",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {
                    "payload": {
                        "order": {"orderNumber": "ORD-UI-SMOKE-CARGO", "shipmentPackageId": 9001},
                        "cargo_provider_code": "ARAS",
                    }
                },
                "rows": [{"title": "Kargo degisikligi", "payload": {"order_number": "ORD-UI-SMOKE-CARGO", "cargo_provider_code": "ARAS"}}],
            },
            answer="Onay gerekiyor: ORD-UI-SMOKE-CARGO siparisinin kargo firmasi ARAS olarak degistirilmeye hazirlaniyor.",
            execute_verify={"verified": True, "order_numbers": ["ORD-UI-SMOKE-CARGO"], "cargo_provider_code": "ARAS"},
        )

        transcript_text = tab.transcript.toPlainText()

        artifact = {
            "name": "ui-chat-tab-approval-smoke",
            "ui": "AITab",
            "transcript": transcript_text,
            "before_approval_state": before_approval_state,
            "after_execute_state": {
                "status": tab._agent_state.get("status"),
                "title": tab.agent_state_title.text(),
                "text": tab.agent_state_text.text(),
                "pending": tab.agent_state_pending.text(),
                "history": tab.agent_state_history.text(),
            },
            "execute_called": execute_mock.called,
            "execute_action_type": execute_mock.call_args.args[0].get("action_type"),
            "execute_verify": (execute_result.data or {}).get("verify"),
            "additional_write_scenarios": additional_scenarios,
        }
        artifact_path = (
            Path(__file__).resolve().parents[2]
            / "AI/docs/live_llm_transcripts/gemini-app-provider/ui-chat-tab-approval-smoke.json"
        )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

        text = artifact_path.read_text(encoding="utf-8")
        self.assertIn("Onayli aksiyon calistirildi", text)
        self.assertIn("labels.action_create_labels_from_selected_orders", text)
        self.assertIn("orders.approve_return_claim", text)
        self.assertIn("orders.change_order_cargo_provider", text)
        self.assertIn('"verified": true', text)

    def test_agent_state_panel_tracks_pending_action(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        tab._update_agent_state_from_result_data(
            {
                "approval_required": True,
                "tool_calls": [{"tool": "returns.approve.prepare", "arguments": {"query": "CLAIM-1"}}],
                "action_proposal": {
                    "title": "Iade onayi",
                    "summary": "CLAIM-1 iadesi onaylanacak.",
                    "action_type": "returns.approve",
                },
            }
        )

        self.assertFalse(tab.agent_state_card.isVisible())
        self.assertIn("Onay", tab.agent_state_title.text())
        self.assertIn("returns.approve.prepare", tab.agent_state_text.text())
        self.assertIn("CLAIM-1", tab.agent_state_pending.text())

    def test_agent_state_panel_tracks_task_state(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        tab._update_agent_state_from_result_data(
            {
                "state_path": "C:/tmp/task.json",
                "state": {
                    "session_id": "abc123session",
                    "status": "pending_approval",
                    "completed_steps": [{"tool_names": ["orders.ready_to_ship"]}],
                    "remaining_steps": [{"prompt": "riskleri listele"}],
                    "pending_actions": [
                        {
                            "title": "Iade onayi",
                            "summary": "CLAIM-TASK onay bekliyor.",
                            "action_type": "orders.approve_return_claim",
                        }
                    ],
                },
            }
        )

        self.assertFalse(tab.agent_state_card.isVisible())
        self.assertIn("Onay", tab.agent_state_title.text())
        self.assertIn("orders.ready_to_ship", tab.agent_state_text.text())
        self.assertIn("kayitli", tab.agent_state_text.text())
        self.assertIn("CLAIM-TASK", tab.agent_state_pending.text())

    def test_agent_state_panel_renders_task_action_history(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        tab._update_agent_state_from_result_data(
            {
                "state_path": "C:/tmp/task.json",
                "state": {
                    "session_id": "hist-session",
                    "status": "complete",
                    "completed_steps": [{"tool_names": ["returns.approve.prepare"]}],
                    "remaining_steps": [],
                    "pending_actions": [],
                    "action_history": [
                        {
                            "phase": "prepare",
                            "status": "pending_approval",
                            "action_type": "orders.approve_return_claim",
                        },
                        {
                            "phase": "execute",
                            "status": "executed",
                            "action_type": "orders.approve_return_claim",
                            "success": True,
                            "verify": {"verified": True},
                            "audit_path": "C:/tmp/audit.jsonl",
                        },
                    ],
                },
            }
        )

        self.assertFalse(tab.agent_state_card.isVisible())
        self.assertIn("prepare/pending_approval", tab.agent_state_history.text())
        self.assertIn("execute/executed", tab.agent_state_history.text())
        self.assertIn("verify", tab.agent_state_history.text())
        self.assertIn("audit", tab.agent_state_history.text())

    def test_task_session_list_can_restore_saved_state(self) -> None:
        row = {
            "session_id": "restore-session",
            "goal": "Bugunku siparis operasyonunu toparla",
            "status": "pending_approval",
            "pending_count": 1,
            "completed_step_count": 2,
            "path": "C:/tmp/restore-session.json",
        }
        state_payload = {
            "session_id": "restore-session",
            "goal": "ORD-1 kargo firmasini degistir",
            "status": "pending_approval",
            "active_entities": {
                "conversation_history": [
                    {"role": "user", "content": "Son siparisi getir"},
                    {"role": "assistant", "content": "1. ORD-1"},
                ],
                "runtime_context": {
                    "source": "cloud",
                    "provider_id": 43,
                    "model_name": "gemini-2.5-flash-lite",
                },
            },
            "completed_steps": [{"tool_names": ["orders.ready_to_ship"]}],
            "remaining_steps": [],
            "pending_actions": [
                {
                    "title": "Kargo degisikligi",
                    "summary": "ORD-1 kargo degisecek.",
                    "action_type": "orders.change_cargo_provider",
                }
            ],
            "action_history": [
                {"phase": "prepare", "status": "pending_approval", "action_type": "orders.change_cargo_provider"}
            ],
        }
        fake_state = type("FakeTaskState", (), {"to_dict": lambda self: state_payload})()

        with patch("AI.views.chat_tab.list_agent_task_states", return_value=[row]), patch(
            "AI.views.chat_tab.load_agent_task_state",
            return_value=fake_state,
        ) as load_mock:
            tab = AITab()
            self.addCleanup(tab.deleteLater)
            self.addCleanup(tab.close)
            tab.show()
            self._app.processEvents()
            tab.task_session_combo.setCurrentIndex(1)
            tab._load_selected_task_session()

        load_mock.assert_called_once_with("restore-session")
        transcript = tab.transcript.toPlainText()
        self.assertNotIn("restore-session", transcript)
        self.assertIn("Son siparisi getir", transcript)
        self.assertIn("1. ORD-1", transcript)
        self.assertIn("ORD-1 kargo firmasini degistir", transcript)
        self.assertIn("Onay gerekiyor", transcript)
        self.assertIn("Kayitli gorev onay bekleyen adimdan devam etmeye hazir", transcript)
        self.assertIn("orders.ready_to_ship", tab.agent_state_text.text())
        self.assertIn("ORD-1", tab.agent_state_pending.text())
        self.assertIn("prepare/pending_approval", tab.agent_state_history.text())
        pending = tab._pending_action_from_state() or {}
        self.assertEqual(pending.get("_agent_task_session_id"), "restore-session")
        self.assertEqual((pending.get("_agent_task_runtime") or {}).get("provider_id"), 43)

        before_count = tab._chat_message_count
        tab._restore_task_chat_context(
            _chat_data_from_task_result(
                Result.ok(
                    "loaded",
                    close_dialog=False,
                    data={"state": state_payload, "state_path": row["path"]},
                )
            )
        )
        self.assertEqual(tab._chat_message_count, before_count + 1)
        self.assertIn("zaten bu sohbette yuklu", tab.transcript.toPlainText())

    def test_completed_task_session_restore_recovers_final_answer_for_followup_context(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        state_payload = {
            "session_id": "completed-restore",
            "goal": "Son iki siparisi yazdir",
            "status": "complete",
            "active_entities": {
                "conversation_history": [
                    {"role": "user", "content": "Son iki siparisi getir"},
                    {"role": "assistant", "content": "1. ORD-R1\n2. ORD-R2"},
                ],
                "final_answer": "ORD-R1 ve ORD-R2 etiketleri olusturuldu ve dogrulandi.",
            },
            "completed_steps": [{"tool_names": ["labels.create_from_orders.prepare"]}],
            "remaining_steps": [],
            "pending_actions": [],
        }
        fake_state = type("FakeTaskState", (), {"to_dict": lambda self: state_payload})()
        tab.task_session_combo.clear()
        tab.task_session_combo.addItem(
            "completed",
            {"session_id": "completed-restore", "path": "C:/tmp/completed-restore.json"},
        )

        with patch("AI.views.chat_tab.load_agent_task_state", return_value=fake_state):
            tab._load_selected_task_session()

        transcript = tab.transcript.toPlainText()
        self.assertIn("ORD-R1 ve ORD-R2 etiketleri olusturuldu ve dogrulandi", transcript)
        self.assertIn("Kayitli gorev baglami sohbete geri yuklendi", transcript)
        self.assertNotIn("Onay gerekiyor", transcript)
        self.assertTrue(
            any(
                row.get("role") == "assistant"
                and "ORD-R1 ve ORD-R2 etiketleri" in row.get("content", "")
                for row in tab._chat_history
            )
        )

    def test_task_result_pending_action_carries_resume_session_metadata(self) -> None:
        result = Result.ok(
            "task pending",
            close_dialog=False,
            data={
                "state_path": "C:/tmp/task-session-9.json",
                "state": {
                    "session_id": "task-session-9",
                    "status": "pending_approval",
                    "completed_steps": [{"tool_names": ["returns.approve.prepare"]}],
                    "remaining_steps": [],
                    "pending_actions": [
                        {
                            "title": "Iade onayi",
                            "summary": "CLAIM-9 onay bekliyor.",
                            "action_type": "orders.approve_return_claim",
                        }
                    ],
                },
            },
        )

        data = _chat_data_from_task_result(result)

        action = data["action_proposal"]
        self.assertEqual(action["_agent_task_session_id"], "task-session-9")
        self.assertTrue(action["_agent_task_resume"])
        self.assertEqual(action["_agent_task_state_path"], "C:/tmp/task-session-9.json")
        self.assertTrue(data["approval_required"])
        self.assertEqual(data["mode"], "approval_required")
        self.assertIn("CLAIM-9 onay bekliyor", data["answer"])
        self.assertNotIn("orders.approve_return_claim", data["answer"])
        self.assertNotIn("task-session-9", data["answer"])

    def test_completed_task_result_exposes_last_scalar_context_to_next_chat_turn(self) -> None:
        authoritative_answer = (
            "Sıfır veya negatif stok bakiyesine sahip toplam 2 adet ürün bulunmaktadır."
        )
        scalar_context = {
            "kind": "scalar_tool_result",
            "active_domain": "stock",
            "source_tool": "stock.zero_or_negative_count",
            "scalar_facts": {"count": 2},
            "authoritative_answer": authoritative_answer,
        }
        result = Result.ok(
            authoritative_answer,
            close_dialog=False,
            data={
                "answer": authoritative_answer,
                "state": {
                    "session_id": "stock-scalar-task",
                    "active_domain": "stock",
                    "status": "complete",
                    "completed_steps": [
                        {
                            "tool_names": ["stock.zero_or_negative_count"],
                            "result_data": {
                                "answer": authoritative_answer,
                                "tool_result": {"count": 2},
                                "conversation_context": scalar_context,
                            },
                        }
                    ],
                    "remaining_steps": [],
                    "pending_actions": [],
                },
            },
        )

        data = _chat_data_from_task_result(result)

        self.assertEqual(data.get("conversation_context"), scalar_context)
        self.assertEqual(data.get("answer"), authoritative_answer)

    def test_task_pending_result_preserves_safe_natural_llm_approval_answer(self) -> None:
        natural_answer = (
            "CLAIM-9 iadesini onaylamak icin hazirladim. "
            "Onay verirsen islemi calistiracagim."
        )
        result = Result.ok(
            "task pending",
            close_dialog=False,
            data={
                "state": {
                    "session_id": "task-natural-pending",
                    "status": "pending_approval",
                    "completed_steps": [
                        {
                            "tool_names": ["returns.approve.prepare"],
                            "result_data": {"answer": natural_answer},
                        }
                    ],
                    "remaining_steps": [],
                    "pending_actions": [
                        {
                            "title": "Iade onayi",
                            "summary": "CLAIM-9 onay bekliyor.",
                            "action_type": "orders.approve_return_claim",
                        }
                    ],
                },
            },
        )

        data = _chat_data_from_task_result(result)

        self.assertEqual(data.get("answer"), natural_answer)
        self.assertNotIn("Agent gorevi 1 adim ilerledi", data.get("answer") or "")

    def test_task_pending_result_prefers_verified_final_projection_over_raw_last_step(
        self,
    ) -> None:
        projected_answer = (
            "Kapsam: MDB (TRENDYOL / production).\n\n"
            "Onay gerekiyor: siparis senkronizasyonu hazirlandi."
        )
        result = Result.ok(
            projected_answer,
            close_dialog=False,
            data={
                "answer": projected_answer,
                "state": {
                    "session_id": "task-projected-pending",
                    "status": "pending_approval",
                    "completed_steps": [
                        {
                            "tool_names": ["orders.fetch.prepare"],
                            "result_data": {
                                "answer": (
                                    "Onay gerekiyor: siparis "
                                    "senkronizasyonu hazirlandi."
                                )
                            },
                        }
                    ],
                    "remaining_steps": [],
                    "pending_actions": [
                        {
                            "title": "Siparis senkronizasyonu",
                            "summary": "Bir hesap icin hazirlandi.",
                            "action_type": (
                                "orders.get_orders_from_companies"
                            ),
                        }
                    ],
                },
            },
        )

        data = _chat_data_from_task_result(result)

        self.assertEqual(data.get("answer"), projected_answer)
        self.assertIn("MDB (TRENDYOL / production)", data.get("answer") or "")

    def test_response_progress_shell_shows_percent_state(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        tab._start_chat_progress(estimated_seconds=30)
        self.assertTrue(tab.chat_progress_shell.isVisible())
        self.assertEqual(tab.chat_progress.value(), 4)
        self.assertIn("4%", tab.chat_progress_percent.text())

        tab._set_chat_progress(64, "Model cevabi uretiyor", percent_text="64% | 2s")
        self.assertEqual(tab.chat_progress.value(), 64)
        self.assertEqual(tab.chat_progress_percent.text(), "64% | 2s")
        self.assertIn("Model", tab.chat_progress_label.text())

    def test_task_progress_is_rendered_in_chat_without_duplicate_activity(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()
        tab._chat_progress_started_at = time.monotonic()

        tab._on_task_progress(24, "Adim 1/3: Kargoya hazir siparisleri kontrol ediyorum.")
        tab._on_task_progress(24, "Adim 1/3: Kargoya hazir siparisleri kontrol ediyorum.")
        tab._on_task_progress(46, "Adim 1/3 tamamlandi.")

        transcript = tab.transcript.toPlainText()
        self.assertEqual(
            transcript.count("Adim 1/3: Kargoya hazir siparisleri kontrol ediyorum."),
            1,
        )
        self.assertIn("Adim 1/3 tamamlandi.", transcript)
        self.assertEqual(tab.chat_progress.value(), 46)
        self.assertIn("Adim 1/3 tamamlandi.", tab.chat_progress_label.text())

    def test_response_progress_switches_to_busy_when_estimate_is_exceeded(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        tab._chat_worker = _RunningWorker()
        tab._start_chat_progress(estimated_seconds=8)
        tab._chat_progress_started_at = time.monotonic() - 9

        tab._advance_chat_progress()

        self.assertEqual(tab.chat_progress.minimum(), 0)
        self.assertEqual(tab.chat_progress.maximum(), 0)
        self.assertIn("uzun", tab.chat_progress_label.text())

    def test_send_starts_progress_before_local_runtime_is_built(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        item = QListWidgetItem("Gemma 4")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "repo_id": "jc-builds/Gemma-4-E4B-it-GGUF",
                "filename": "Gemma-4-E4B-it-Q4_K_M.gguf",
                "_source_kind": "local_model",
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)
        tab.composer.setPlainText("Bugun kac siparisim var?")

        _DeferredWorker.instances.clear()
        with patch("AI.views.chat_tab.build_local_resource_plan", return_value=_SafePlan()), patch(
            "AI.views.chat_tab.build_local_planner_client",
            side_effect=AssertionError("runner UI thread'de kurulmamalı"),
        ), patch("AI.views.chat_tab.SyncWorker", _DeferredWorker):
            tab._resource_plan_cache.clear()
            tab._send_message()

        self.assertEqual(len(_DeferredWorker.instances), 1)
        worker = _DeferredWorker.instances[0]
        self.assertTrue(worker.started)
        self.assertEqual(worker.kwargs.get("source"), "local")
        self.assertEqual(worker.kwargs.get("progress_callback_kw"), "progress_callback")
        self.assertTrue(worker.progress.callbacks)
        self.assertTrue(tab.chat_progress_shell.isVisible())
        self.assertGreater(tab.chat_progress.value(), 0)
        self.assertFalse(tab.btn_send.isEnabled())
        self.assertTrue(tab.composer.isEnabled())
        self.assertFalse(tab.btn_pause_task.isHidden())
        self.assertIsNotNone(worker.kwargs.get("task_control"))

    def test_chat_worker_finish_reenables_consecutive_messages_with_history(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.show()
        self._app.processEvents()

        item = QListWidgetItem("Gemma 4")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "repo_id": "jc-builds/Gemma-4-E4B-it-GGUF",
                "filename": "Gemma-4-E4B-it-Q4_K_M.gguf",
                "_source_kind": "local_model",
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)

        _DeferredWorker.instances.clear()
        with patch("AI.views.chat_tab.build_local_resource_plan", return_value=_SafePlan()), patch("AI.views.chat_tab.SyncWorker", _DeferredWorker):
            tab._resource_plan_cache.clear()
            tab.composer.setPlainText("Bugun kac siparisim var?")
            tab._send_message()

            first_worker = _DeferredWorker.instances[-1]
            for callback in first_worker.result_ready.callbacks:
                callback(Result.ok("Ilk cevap.", close_dialog=False, data={"answer": "Ilk cevap.", "tool_calls": []}))
            for callback in first_worker.finished.callbacks:
                callback()

            self.assertIsNone(tab._chat_worker)
            self.assertTrue(tab.composer.isEnabled())

            tab.composer.setPlainText("Peki yazdirilmamis olanlari yazdir")
            tab._update_chat_controls()
            self.assertTrue(tab.btn_send.isEnabled())
            tab._send_message()

        self.assertEqual(len(_DeferredWorker.instances), 2)
        second_history = _DeferredWorker.instances[-1].kwargs.get("history") or []
        self.assertEqual([row.get("role") for row in second_history[-3:]], ["user", "assistant", "user"])
        self.assertIn("Bugun kac siparisim var?", second_history[-3].get("content", ""))
        self.assertIn("Ilk cevap.", second_history[-2].get("content", ""))
        self.assertIn("Peki yazdirilmamis", second_history[-1].get("content", ""))

    def test_local_runtime_build_failure_falls_back_to_rule_agent(self) -> None:
        def fake_agent_turn(text, *, model_record=None, planner_client=None, chat_client=None, history=None):
            self.assertEqual(text, "at kılı fırça ürünü bul bana")
            self.assertIsNone(planner_client)
            self.assertIsNone(chat_client)
            return Result.ok(
                "At kılı fırça bulundu.",
                close_dialog=False,
                data={
                    "answer": "At kılı fırça bulundu.",
                    "tool_call": {"tool": "listing.search", "arguments": {"query": "at kili firca"}},
                    "tool_calls": [{"tool": "listing.search", "arguments": {"query": "at kili firca"}}],
                    "tool_result": {"count": 1, "results": [{"title": "At Kılı Fırça"}]},
                },
            )

        with patch("AI.views.chat_tab.build_local_planner_client", side_effect=RuntimeError("runner patladi")), patch(
            "AI.views.chat_tab.run_agent_turn",
            side_effect=fake_agent_turn,
        ):
            result = _run_chat_turn_with_runtime(
                "at kılı fırça ürünü bul bana",
                source="local",
                runtime_record={"repo_id": "jc-builds/Gemma-4-E4B-it-GGUF", "filename": "Gemma.gguf"},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual((result.data or {}).get("answer"), "At kılı fırça bulundu.")
        self.assertEqual(((result.data or {}).get("runtime") or {}).get("runtime_name"), "rule_fallback")
        self.assertEqual(((result.data or {}).get("tool_call") or {}).get("tool"), "listing.search")

    def test_local_contextual_write_followup_uses_typed_model_interpretation_before_task_runtime(self) -> None:
        history = [
            {"role": "user", "content": "son gelen 1 siparisi soyle"},
            {
                "role": "assistant",
                "content": "Lokal kayda gore 1 siparis buldum:\n1. 11322882128 | durum: ReadyToShip | musteri: Eda Tek",
            },
            {"role": "user", "content": "bunu yazdir"},
        ]

        def planner(_prompt: str) -> str:
            return json.dumps(
                {
                    "mode": "act",
                    "domain": "orders",
                    "objective": "Onceki typed siparis secimi icin etiket hazirla",
                    "reason": "Kullanici gercek cikti istiyor.",
                    "requires_clarification": False,
                }
            )

        setattr(planner, "runtime_name", "llama_cpp_chat")
        setattr(planner, "model_name", "local-test-model")
        setattr(planner, "resource_plan", {"profile": "local"})
        task_state = {
            "session_id": "local-followup-task",
            "active_domain": "orders",
            "status": "pending_approval",
            "active_entities": {
                "pending_answer": "Onay gerekiyor: 1 siparis icin etiket olusturma hazirlaniyor."
            },
            "completed_steps": [
                {
                    "tool_names": ["labels.create_from_orders.prepare"],
                    "status": "completed",
                }
            ],
            "remaining_steps": [],
            "pending_actions": [{"action_type": "labels.action_create_labels_from_selected_orders"}],
        }

        with patch(
            "AI.views.chat_tab.build_local_planner_client",
            return_value=planner,
        ) as planner_mock, patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok(
                "pending",
                close_dialog=False,
                data={"state": task_state},
            ),
        ) as task_mock, patch("AI.views.chat_tab.run_agent_turn") as turn_mock:
            result = _run_chat_turn_with_runtime(
                "bunu yazdir",
                source="local",
                runtime_record={"repo_id": "Andycurrent/Gemma-3-1B-it-GLM-4.7-Flash-Heretic-Uncensored-Thinking_GGUF"},
                history=history,
            )

        planner_mock.assert_called_once()
        task_mock.assert_called_once()
        turn_mock.assert_not_called()
        self.assertTrue(result.success, result.message)
        self.assertTrue((result.data or {}).get("approval_required"))
        self.assertEqual(
            ((result.data or {}).get("turn_interpretation") or {}).get("mode"),
            "act",
        )
        self.assertEqual(task_mock.call_args.kwargs.get("domain"), "orders")
        self.assertEqual(
            (task_mock.call_args.kwargs.get("turn_interpretation") or {}).get("decision_path"),
            "typed_model_turn_interpretation",
        )

    def test_orders_task_prompt_runs_persisted_task_runtime(self) -> None:
        task_state = {
            "session_id": "task-session-1",
            "status": "complete",
            "completed_steps": [
                {"tool_names": ["orders.ready_to_ship"], "status": "completed"},
                {"tool_names": ["orders.fulfillment_risk"], "status": "completed"},
            ],
            "remaining_steps": [],
            "pending_actions": [],
        }
        with patch("AI.views.chat_tab.build_local_planner_client", side_effect=RuntimeError("runner yok")), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok("task ok", close_dialog=False, data={"state": task_state, "state_path": "C:/tmp/task-session-1.json"}),
        ) as task_mock, patch("AI.views.chat_tab.run_agent_turn") as turn_mock:
            result = _run_chat_turn_with_runtime(
                "Bugunku siparis operasyonunu toparla",
                source="local",
                runtime_record={"repo_id": "jc-builds/Gemma-4-E4B-it-GGUF", "filename": "Gemma.gguf"},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        task_mock.assert_called_once()
        self.assertTrue(task_mock.call_args.kwargs.get("persist"))
        runtime_context = task_mock.call_args.kwargs.get("runtime_context") or {}
        self.assertEqual(runtime_context.get("source"), "local")
        self.assertEqual(
            ((runtime_context.get("model_record") or {}).get("repo_id")),
            "jc-builds/Gemma-4-E4B-it-GGUF",
        )
        turn_mock.assert_not_called()
        data = result.data or {}
        self.assertEqual(data.get("mode"), "task")
        self.assertEqual(data.get("state_path"), "C:/tmp/task-session-1.json")
        self.assertIn("Agent gorevi tamamlandi", data.get("answer") or "")
        self.assertEqual(((data.get("tool_calls") or [])[0]).get("tool"), "orders.ready_to_ship")

    def test_cloud_orders_task_runtime_context_keeps_reasoning_effort(self) -> None:
        task_state = {
            "session_id": "task-cloud-reasoning",
            "status": "complete",
            "active_entities": {"final_answer": "Task tamamlandi."},
            "completed_steps": [],
            "remaining_steps": [],
            "pending_actions": [],
        }

        def planner(prompt: str) -> str:
            if prompt.startswith("OrderScout typed tur yorumu"):
                return json.dumps(
                    {
                        "mode": "inspect",
                        "domain": "orders",
                        "objective": "Bugunku siparis operasyonunu toparla",
                        "intent_kind": "data_read",
                        "requested_fields": [],
                        "entity": "order",
                        "metric": "summary",
                        "status_scope": "all",
                        "period": "today",
                        "freshness": "local_snapshot",
                        "reason": "Orders operasyon ozeti istendi.",
                        "requires_clarification": False,
                        "clarification": "",
                    }
                )
            return '{"mode":"answer","reply":"ok"}'

        setattr(planner, "runtime_name", "gemini_chat")
        setattr(planner, "model_name", "gemini-2.5-flash-lite")
        setattr(
            planner,
            "resource_plan",
            {
                "profile": "cloud_provider",
                "provider_code": "gemini",
                "reasoning_effort": "high",
            },
        )

        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "label": "Gemini Free",
                        "provider_code": "gemini",
                        "api_key": "runtime-secret",
                        "default_model": "gemini-2.5-flash-lite",
                        "reasoning_effort": "high",
                        "allow_model_fallback": False,
                        "model_metadata": {
                            "supported_parameters": ["tools", "response_format"],
                            "context_length": 1_048_576,
                            "api_key": "must-not-persist",
                        },
                        "free_model_test_route": {
                            "provider_code": "gemini",
                            "state_hash": "catalog-state-43",
                            "generated_from_live_catalog": True,
                            "model_ids": [
                                "gemini-2.5-flash-lite",
                                "gemini-2.0-flash-lite",
                            ],
                        },
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok("task ok", close_dialog=False, data={"state": task_state}),
        ) as task_mock, patch(
            "AI.views.chat_tab.run_agent_turn"
        ) as turn_mock:
            result = _run_chat_turn_with_runtime(
                "Bugunku siparis operasyonunu toparla",
                source="cloud",
                runtime_record={"id": 43, "label": "Gemini Free", "default_model": "stale-list-model"},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        task_mock.assert_called_once()
        runtime_context = task_mock.call_args.kwargs.get("runtime_context") or {}
        self.assertEqual(runtime_context.get("source"), "cloud")
        self.assertEqual(runtime_context.get("provider_id"), 43)
        self.assertEqual(runtime_context.get("model_name"), "gemini-2.5-flash-lite")
        self.assertEqual(runtime_context.get("reasoning_effort"), "high")
        self.assertIs(runtime_context.get("allow_model_fallback"), False)
        self.assertEqual(
            (runtime_context.get("model_metadata") or {}).get("supported_parameters"),
            ["tools", "response_format"],
        )
        self.assertEqual(
            (runtime_context.get("free_model_test_route") or {}).get("state_hash"),
            "catalog-state-43",
        )
        self.assertRegex(runtime_context.get("runtime_policy_hash") or "", r"^[0-9a-f]{32}$")
        serialized = json.dumps(runtime_context, ensure_ascii=False)
        self.assertNotIn("runtime-secret", serialized)
        self.assertNotIn("must-not-persist", serialized)
        self.assertNotIn("api_key", serialized)
        turn_mock.assert_not_called()

    def test_cloud_runtime_envelope_preserves_model_invocation_provenance(self) -> None:
        def planner(prompt: str) -> str:
            if prompt.startswith("OrderScout typed tur yorumu"):
                return json.dumps(
                    {
                        "mode": "chat",
                        "domain": "general",
                        "objective": "Gundelik sohbete cevap ver",
                        "intent_kind": "conversation",
                        "requested_fields": [],
                        "entity": "none",
                        "metric": "none",
                        "status_scope": "unspecified",
                        "period": "unspecified",
                        "freshness": "unspecified",
                        "reason": "Gundelik sohbet.",
                        "requires_clarification": False,
                        "clarification": "",
                    }
                )
            return '{"mode":"answer","reply":"ok"}'

        setattr(planner, "runtime_name", "gemini_chat")
        setattr(planner, "model_name", "gemini-2.5-flash")
        setattr(
            planner,
            "resource_plan",
            {
                "profile": "cloud_provider",
                "requested_model": "gemini-2.5-flash",
                "actual_model": "gemini-2.5-flash",
                "fallback_used": False,
            },
        )

        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "runtime-secret",
                        "default_model": "gemini-2.5-flash",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_turn",
            return_value=Result.ok(
                "ok",
                close_dialog=False,
                data={
                    "answer": "Gercek model cevabi.",
                    "model_invoked": True,
                    "decision_path": "llm_tool_plan",
                },
            ),
        ):
            result = _run_chat_turn_with_runtime(
                "Merhaba, bugun nasil gidiyor?",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        runtime = (result.data or {}).get("runtime") or {}
        self.assertIs(runtime.get("model_invoked"), True)
        self.assertEqual(
            runtime.get("decision_path"),
            "typed_model_non_business_turn",
        )
        self.assertEqual(
            (runtime.get("resource_plan") or {}).get("actual_model"),
            "gemini-2.5-flash",
        )

    def test_task_pending_action_carries_secret_free_runtime_resume_context(self) -> None:
        state = {
            "session_id": "task-runtime-context",
            "status": "pending_approval",
            "active_entities": {
                "runtime_context": {
                    "source": "cloud",
                    "provider_id": 43,
                    "provider_label": "Gemini Free",
                    "model_name": "gemini-2.5-flash-lite",
                    "reasoning_effort": "high",
                }
            },
            "completed_steps": [],
            "remaining_steps": [],
            "pending_actions": [
                {
                    "title": "Iade onayi",
                    "summary": "CLAIM-RUNTIME onaylanacak.",
                    "action_type": "orders.approve_return_claim",
                }
            ],
        }

        data = _chat_data_from_task_result(
            Result.ok("pending", close_dialog=False, data={"state": state})
        )

        action = data.get("action_proposal") or {}
        self.assertEqual(action.get("_agent_task_session_id"), "task-runtime-context")
        self.assertEqual(
            (action.get("_agent_task_runtime") or {}).get("provider_id"),
            43,
        )
        self.assertEqual(
            (action.get("_agent_task_runtime") or {}).get("reasoning_effort"),
            "high",
        )
        serialized = json.dumps(action, ensure_ascii=False)
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("secret", serialized.casefold())

    def test_approved_task_resume_rebuilds_same_cloud_runtime(self) -> None:
        runtime_context = safe_agent_runtime_context(
            {
                "source": "cloud",
                "provider_id": 43,
                "provider_label": "Gemini Free",
                "provider_code": "gemini",
                "model_name": "gemini-2.5-flash-lite",
                "reasoning_effort": "high",
                "allow_model_fallback": False,
                "model_metadata": {
                    "supported_parameters": ["tools", "response_format"],
                    "context_length": 1_048_576,
                },
                "free_model_test_route": {
                    "provider_code": "gemini",
                    "state_hash": "catalog-state-43",
                    "generated_from_live_catalog": True,
                    "model_ids": [
                        "gemini-2.5-flash-lite",
                        "gemini-2.0-flash-lite",
                    ],
                },
                "temperature": 0.2,
            }
        )
        action = {
            "title": "Iade onayi",
            "action_type": "orders.approve_return_claim",
            "_agent_task_session_id": "task-cloud-resume",
            "_agent_task_runtime": runtime_context,
        }

        def planner(_prompt: str) -> str:
            return "ok"

        with patch(
            "AI.views.chat_tab.DB_NAME",
            "C:\\tmp\\source-resume.sqlite3",
        ), patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "runtime-secret",
                        "default_model": "changed-after-task",
                        "reasoning_effort": "low",
                        "allow_model_fallback": True,
                        "model_metadata": {
                            "supported_parameters": [],
                            "context_length": 8_192,
                        },
                        "free_model_test_route": {
                            "model_ids": ["changed-after-task"],
                        },
                        "temperature": 1.8,
                    }
                },
            ),
        ) as provider_mock, patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ) as build_mock, patch(
            "AI.views.chat_tab.resume_agent_task_by_id",
            return_value=Result.ok(
                "complete",
                close_dialog=False,
                data={
                    "state": {
                        "session_id": "task-cloud-resume",
                        "status": "complete",
                        "active_entities": {"final_answer": "Iade onaylandi."},
                        "completed_steps": [],
                        "remaining_steps": [],
                        "pending_actions": [],
                    }
                },
            ),
        ) as resume_mock:
            result = _run_approved_chat_action(action)

        self.assertTrue(result.success, result.message)
        provider_mock.assert_called_once_with(43)
        build_record = build_mock.call_args.args[0]
        self.assertEqual(build_record.get("api_key"), "runtime-secret")
        self.assertEqual(build_record.get("default_model"), "gemini-2.5-flash-lite")
        self.assertEqual(build_record.get("reasoning_effort"), "high")
        self.assertIs(build_record.get("allow_model_fallback"), False)
        self.assertEqual(
            (build_record.get("model_metadata") or {}).get("supported_parameters"),
            ["tools", "response_format"],
        )
        self.assertEqual(
            (build_record.get("free_model_test_route") or {}).get("state_hash"),
            "catalog-state-43",
        )
        self.assertEqual(build_record.get("temperature"), 0.2)
        resume_mock.assert_called_once_with(
            "task-cloud-resume",
            approved_by="chat_ui",
            progress_callback=None,
            db_name="C:\\tmp\\source-resume.sqlite3",
            planner_client=planner,
            chat_client=planner,
        )

    def test_approved_task_resume_rejects_changed_runtime_policy_snapshot(self) -> None:
        runtime_context = safe_agent_runtime_context(
            {
                "source": "cloud",
                "provider_id": 43,
                "provider_code": "gemini",
                "model_name": "gemini-2.5-flash-lite",
                "allow_model_fallback": False,
                "model_metadata": {
                    "supported_parameters": ["tools", "response_format"],
                },
            }
        )
        runtime_context["allow_model_fallback"] = True
        action = {
            "title": "Iade onayi",
            "action_type": "orders.approve_return_claim",
            "_agent_task_session_id": "task-cloud-policy-tampered",
            "_agent_task_runtime": runtime_context,
        }

        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account"
        ) as provider_mock, patch(
            "AI.views.chat_tab.build_provider_chat_client"
        ) as build_mock, patch(
            "AI.views.chat_tab.resume_agent_task_by_id"
        ) as resume_mock, patch(
            "AI.views.chat_tab.load_agent_task_state",
            side_effect=RuntimeError("fixture state unavailable"),
        ):
            result = _run_approved_chat_action(action)

        self.assertFalse(result.success)
        self.assertIn("runtime politikasi degismis", result.message)
        provider_mock.assert_not_called()
        build_mock.assert_not_called()
        resume_mock.assert_not_called()

    def test_task_result_prefers_runtime_final_answer(self) -> None:
        task_state = {
            "session_id": "task-session-final",
            "status": "complete",
            "active_entities": {"final_answer": "Operasyon ozeti hazir: risk ve iade kontrol edildi."},
            "completed_steps": [
                {"tool_names": ["orders.ready_to_ship"], "status": "completed"},
                {"tool_names": ["orders.fulfillment_risk"], "status": "completed"},
            ],
            "remaining_steps": [],
            "pending_actions": [],
        }

        data = _chat_data_from_task_result(
            Result.ok(
                "Operasyon ozeti hazir: risk ve iade kontrol edildi.",
                close_dialog=False,
                data={
                    "state": task_state,
                    "state_path": "C:/tmp/task-session-final.json",
                    "answer": "Operasyon ozeti hazir: risk ve iade kontrol edildi.",
                },
            )
        )

        self.assertEqual(data.get("answer"), "Operasyon ozeti hazir: risk ve iade kontrol edildi.")
        self.assertEqual(data.get("mode"), "task")
        self.assertEqual(((data.get("tool_calls") or [])[0]).get("tool"), "orders.ready_to_ship")

    def test_task_result_preserves_provider_unavailable_answer(self) -> None:
        answer = (
            "Seçili cloud model provider kota/rate-limit sınırına takıldı. "
            "Hiçbir business tool çalıştırılmadı."
        )
        task_state = {
            "session_id": "task-provider-unavailable",
            "status": "provider_unavailable",
            "active_entities": {"final_answer": answer},
            "completed_steps": [],
            "remaining_steps": [],
            "pending_actions": [],
        }

        data = _chat_data_from_task_result(
            Result.ok(
                answer,
                close_dialog=False,
                data={
                    "state": task_state,
                    "answer": answer,
                    "mode": "provider_unavailable",
                    "provider_unavailable": True,
                },
            )
        )

        self.assertEqual(data.get("answer"), answer)
        self.assertEqual(data.get("mode"), "provider_unavailable")
        self.assertNotIn("durumunda durdu", data.get("answer") or "")

    def test_provider_unavailable_result_sets_distinct_ui_agent_state(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        answer = (
            "Seçili cloud model provider kota/rate-limit sınırına takıldı. "
            "Hiçbir business tool çalıştırılmadı."
        )

        tab._update_agent_state_from_result_data(
            {
                "provider_unavailable": True,
                "mode": "provider_unavailable",
                "answer": answer,
                "tool_calls": [],
            }
        )

        self.assertEqual(
            tab._agent_state.get("status"),
            "provider_unavailable",
        )
        self.assertEqual(tab._agent_state.get("tools"), [])
        self.assertEqual(tab._agent_state.get("detail"), answer)

    def test_cloud_turn_surfaces_provider_quota_without_starting_business_task(
        self,
    ) -> None:
        calls = {"count": 0}

        def planner(_prompt: str) -> str:
            calls["count"] += 1
            planner.resource_plan.update(
                {
                    "actual_model": "",
                    "model_invocation_attempted": True,
                    "invocation_error_reason": "http_429",
                    "normalized_error_history": [
                        {
                            "provider_code": "gemini",
                            "category": "quota",
                            "retryable": True,
                            "quota_scope": "project",
                            "status_code": 429,
                            "safe_message": (
                                "Provider kota veya rate-limit yanıtı verdi."
                            ),
                            "model_fallback_allowed": False,
                        }
                    ],
                }
            )
            raise RuntimeError("provider response intentionally redacted")

        planner.runtime_name = "gemini_chat"
        planner.model_name = "gemini-3.5-flash"
        planner.resource_plan = {
            "provider_code": "gemini",
            "requested_model": "gemini-3.5-flash",
            "allow_model_fallback": False,
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "secret",
                        "default_model": "gemini-3.5-flash",
                        "allow_model_fallback": False,
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task"
        ) as task_mock, patch(
            "AI.views.chat_tab.run_agent_turn"
        ) as turn_mock:
            result = _run_chat_turn_with_runtime(
                "başkan kaç sipariş var bekleyen",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(calls["count"], 1)
        task_mock.assert_not_called()
        turn_mock.assert_not_called()
        data = result.data or {}
        self.assertTrue(data.get("provider_unavailable"))
        self.assertEqual(data.get("mode"), "provider_unavailable")
        self.assertFalse(data.get("model_invoked"))
        self.assertTrue(data.get("model_invocation_attempted"))
        self.assertIn("rate-limit", data.get("answer") or "")
        self.assertNotIn("açık söyler", data.get("answer") or "")

    def test_cloud_public_web_intent_routes_source_ui_to_web_task_runtime(
        self,
    ) -> None:
        def planner(_prompt: str) -> str:
            return json.dumps(
                {
                    "mode": "inspect",
                    "domain": "listing",
                    "objective": "Hepsiburada güncel kargo tarifelerini araştır",
                    "intent_kind": "data_read",
                    "requested_fields": [],
                    "entity": "cargo_tariff",
                    "metric": "list",
                    "status_scope": "unspecified",
                    "period": "unspecified",
                    "freshness": "unspecified",
                    "information_source": "external_public_web",
                    "reason": "kamuya açık güncel kaynak",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            )

        planner.runtime_name = "openrouter_chat"
        planner.model_name = "deepseek-test"
        planner.resource_plan = {
            "provider_code": "openrouter",
            "requested_model": "deepseek-test",
            "actual_model": "deepseek-test",
        }
        task_state = {
            "session_id": "public-web-source-ui",
            "active_domain": "web",
            "status": "complete",
            "active_entities": {
                "final_answer": "Kaynaklı güncel tarife araştırması tamamlandı."
            },
            "completed_steps": [
                {
                    "tool_names": ["web.search"],
                    "status": "completed",
                },
                {
                    "tool_names": ["web.open"],
                    "status": "completed",
                },
            ],
            "remaining_steps": [],
            "pending_actions": [],
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "openrouter",
                        "api_key": "secret",
                        "default_model": "deepseek-test",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok(
                "task ok",
                close_dialog=False,
                data={"state": task_state},
            ),
        ) as task_mock, patch(
            "AI.views.chat_tab.run_agent_turn"
        ) as legacy_turn_mock:
            result = _run_chat_turn_with_runtime(
                "Hepsiburada'nın güncel kargo fiyatlarını internette bul",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        task_mock.assert_called_once()
        self.assertEqual(task_mock.call_args.kwargs.get("domain"), "web")
        interpretation = (
            task_mock.call_args.kwargs.get("turn_interpretation") or {}
        )
        self.assertEqual(interpretation.get("domain"), "web")
        self.assertEqual(
            interpretation.get("information_source"),
            "external_public_web",
        )
        self.assertIn(
            "external_public_source_domain_to_web",
            interpretation.get("semantic_corrections") or [],
        )
        legacy_turn_mock.assert_not_called()

    def test_verified_web_uncertainty_is_accepted_without_claiming_source_evidence(
        self,
    ) -> None:
        def planner(_prompt: str) -> str:
            return json.dumps(
                {
                    "mode": "inspect",
                    "domain": "web",
                    "objective": "Hepsiburada kargo fiyatlarını internette bul",
                    "intent_kind": "data_read",
                    "requested_fields": [],
                    "entity": "general",
                    "metric": "summary",
                    "status_scope": "all",
                    "period": "all",
                    "freshness": "live_external",
                    "information_source": "external_public_web",
                    "reason": "Public web araştırması istendi.",
                    "requires_clarification": False,
                    "clarification": "",
                }
            )

        planner.runtime_name = "gemini_chat"
        planner.model_name = "gemini-3.5-flash"
        planner.resource_plan = {
            "requested_model": "gemini-3.5-flash",
            "actual_model": "gemini-3.5-flash",
            "model_invocation_attempted": True,
            "any_model_response_received": True,
            "final_model_response_received": True,
        }
        answer = (
            "Web araştırmasında 1 public kaynak açıp içeriğini inceledim; "
            "ancak hedefle ilişkili doğrulanabilir kanıt bulamadım ve ilgisiz "
            "metni cevap diye kullanmadım."
        )
        task_state = {
            "session_id": "verified-web-uncertainty",
            "goal": "Hepsiburada kargo fiyatlarını internette bul",
            "status": "failed",
            "active_domain": "web",
            "active_entities": {
                "response_synthesis": {
                    "reason": "opened_sources_lack_goal_evidence",
                    "final_source": "deterministic_verified_uncertainty",
                    "final_projection_verified": True,
                    "uncertainty_verified": True,
                }
            },
            "completed_steps": [],
            "remaining_steps": [],
            "pending_actions": [],
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "secret",
                        "default_model": "gemini-3.5-flash",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok(
                answer,
                close_dialog=False,
                data={"state": task_state, "answer": answer},
            ),
        ):
            result = _run_chat_turn_with_runtime(
                "Hepsiburada kargo fiyatlarını internette bul",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(
            data.get("final_response_source"),
            "deterministic_verified_uncertainty",
        )
        self.assertTrue(data.get("accepted_semantic_output"))
        self.assertEqual(data.get("answer"), answer)

    def test_model_authored_verified_deterministic_projection_is_accepted(
        self,
    ) -> None:
        model = "nvidia/nemotron-3-ultra-550b-a55b:free"

        def planner(_prompt: str) -> str:
            return json.dumps(
                {
                    "mode": "inspect",
                    "domain": "orders",
                    "objective": "En son siparişin tam bağlamını göster",
                    "intent_kind": "data_read",
                    "requested_fields": [
                        "order_number",
                        "item",
                        "cargo",
                        "tracking_number",
                        "returns",
                    ],
                    "entity": "order",
                    "metric": "detail",
                    "status_scope": "all",
                    "period": "all",
                    "freshness": "current_local",
                    "information_source": "local_business_data",
                    "reason": "Sipariş detay okuması",
                    "requires_clarification": False,
                    "clarification": "",
                }
            )

        planner.runtime_name = "openrouter_chat"
        planner.model_name = model
        planner.resource_plan = {
            "requested_model": model,
            "actual_model": model,
            "model_invocation_attempted": True,
            "any_model_response_received": True,
            "final_model_response_received": True,
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
        }
        answer = (
            "Siparis ORD-1 detaylari: Kalemler: Urun A | adet: 1. "
            "Kargo: Trendyol Express | takip: TRK-1. Iade kaydi yok."
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
                            "operation_id": "orders.full_context",
                        }
                    ],
                },
                "response_synthesis": {
                    "final_source": "deterministic_verified_projection",
                    "final_projection_verified": False,
                    "fallback_projection_verified": True,
                },
            },
            "completed_steps": [
                {"tool_names": ["orders.full_context"]}
            ],
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 44,
                        "provider_code": "openrouter",
                        "api_key": "secret",
                        "default_model": model,
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            return_value=Result.ok(
                answer,
                close_dialog=False,
                data={
                    "answer": answer,
                    "tool_call": {
                        "tool": "orders.full_context",
                        "arguments": {"order_numbers": ["ORD-1"]},
                    },
                    "tool_calls": [
                        {
                            "tool": "orders.full_context",
                            "arguments": {"order_numbers": ["ORD-1"]},
                        }
                    ],
                    "tool_result": {"state": state},
                },
            ),
        ):
            result = _run_chat_turn_with_runtime(
                "En son siparişin tam bağlamını göster",
                source="cloud",
                runtime_record={"id": 44},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertTrue(data.get("accepted_semantic_output"))
        self.assertEqual(
            data.get("accepted_semantic_output_source"),
            "model_authored_verified_projection",
        )
        self.assertEqual(
            data.get("final_response_source"),
            "deterministic_verified_projection",
        )

    def test_partial_non_business_provider_failure_never_surfaces_generic_app_error(
        self,
    ) -> None:
        calls = {"count": 0}

        def planner(_prompt: str) -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                planner.resource_plan.update(
                    {
                        "actual_model": "nemotron-test",
                        "model_invocation_attempted": True,
                        "invocation_outcome_history": [
                            {
                                "contract": "json_text_guarded",
                                "requested_model": "nemotron-test",
                                "actual_model": "nemotron-test",
                                "response_received": True,
                                "error_reason": "",
                                "fallback_used": False,
                            }
                        ],
                    }
                )
                return json.dumps(
                    {
                        "mode": "chat",
                        "domain": "general",
                        "objective": "Kullanıcıyla gündelik sohbeti sürdür",
                        "intent_kind": "conversation",
                        "requested_fields": [],
                        "reason": "gündelik sohbet",
                        "requires_clarification": False,
                        "clarification": "",
                    },
                    ensure_ascii=False,
                )
            planner.resource_plan.update(
                {
                    "actual_model": "",
                    "model_invocation_attempted": True,
                    "invocation_error_reason": "empty_response",
                    "invocation_outcome_history": [
                        {
                            "contract": "json_text_guarded",
                            "requested_model": "nemotron-test",
                            "actual_model": "nemotron-test",
                            "response_received": True,
                            "error_reason": "",
                            "fallback_used": False,
                        },
                        {
                            "contract": "text",
                            "requested_model": "nemotron-test",
                            "actual_model": "",
                            "response_received": False,
                            "error_reason": "empty_response",
                            "fallback_used": False,
                        },
                    ],
                }
            )
            raise RuntimeError("provider response intentionally redacted")

        planner.runtime_name = "openrouter_chat"
        planner.model_name = "nemotron-test"
        planner.resource_plan = {
            "provider_code": "openrouter",
            "requested_model": "nemotron-test",
            "allow_model_fallback": False,
        }
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "openrouter",
                        "api_key": "secret",
                        "default_model": "nemotron-test",
                        "allow_model_fallback": False,
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.run_agent_task"
        ) as task_mock, patch(
            "AI.views.chat_tab.run_agent_turn"
        ) as turn_mock:
            result = _run_chat_turn_with_runtime(
                "e-ticaret insanı yorar mı sence?",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        self.assertEqual(calls["count"], 2)
        task_mock.assert_not_called()
        turn_mock.assert_not_called()
        data = result.data or {}
        self.assertTrue(data.get("provider_unavailable"))
        self.assertEqual(data.get("mode"), "provider_unavailable")
        self.assertEqual(
            data.get("decision_path"),
            "typed_model_non_business_provider_unavailable",
        )
        self.assertNotIn("Uygulama hatasi", data.get("answer") or "")
        self.assertIn("kullanılamıyor", data.get("answer") or "")
        self.assertTrue(data.get("model_response_received"))
        self.assertFalse(data.get("final_model_response_received"))
        self.assertFalse(data.get("accepted_semantic_output"))

    def test_blocked_local_model_disables_send_control(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        item = QListWidgetItem("gpt-oss")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "repo_id": "openai/gpt-oss-20b",
                "filename": "gpt-oss:20b",
                "_source_kind": "local_model",
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)
        tab.composer.setPlainText("merhaba")

        with patch("AI.views.chat_tab.build_local_resource_plan", return_value=_BlockedPlan()):
            tab._resource_plan_cache.clear()
            tab._update_chat_controls()

        self.assertFalse(tab.btn_send.isEnabled())
        self.assertIn("bloke", tab.composer_meta.text())

    def test_cloud_provider_without_default_model_disables_send_control(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.source_combo.blockSignals(True)
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
        tab.source_combo.blockSignals(False)

        item = QListWidgetItem("Gemini Missing Model")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "_source_kind": "cloud_provider",
                "id": 42,
                "label": "Gemini Missing Model",
                "provider_code": "gemini",
                "default_model": "",
                "is_enabled": True,
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)
        tab.composer.setPlainText("Bugun kac siparisim var?")

        tab._update_chat_controls()

        self.assertFalse(tab.btn_send.isEnabled())
        self.assertIn("varsayilan model", tab.composer_meta.text())

    def test_cloud_provider_with_default_model_enables_send_control(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.source_combo.blockSignals(True)
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
        tab.source_combo.blockSignals(False)

        item = QListWidgetItem("Gemini Free")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "_source_kind": "cloud_provider",
                "id": 43,
                "label": "Gemini Free",
                "provider_code": "gemini",
                "default_model": "gemini-2.5-flash-lite",
                "is_enabled": True,
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)
        tab.composer.setPlainText("Bugun kac siparisim var?")

        tab._update_chat_controls()

        self.assertTrue(tab.btn_send.isEnabled())
        self.assertIn("gemini-2.5-flash-lite", tab.composer_meta.text())

    def test_empty_local_library_auto_selects_cloud_provider(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        _DeferredWorker.instances.clear()
        with patch("AI.views.chat_tab.SyncWorker", _DeferredWorker):
            tab._refresh_local_models()
            local_worker = _DeferredWorker.instances[-1]
            for callback in local_worker.result_ready.callbacks:
                callback(Result.ok("Lokal model yok.", close_dialog=False, data={"records": []}))
            for callback in local_worker.finished.callbacks:
                callback()
            self._app.processEvents()

            self.assertEqual(tab.source_combo.currentData(), "cloud")
            cloud_worker = _DeferredWorker.instances[-1]
            self.assertIsNot(cloud_worker, local_worker)
            for callback in cloud_worker.result_ready.callbacks:
                callback(
                    Result.ok(
                        "Cloud provider hesaplari listelendi.",
                        close_dialog=False,
                        data={
                            "records": [
                                {
                                    "_source_kind": "cloud_provider",
                                    "id": 11,
                                    "label": "OpenRouter Planner",
                                    "provider_code": "openrouter",
                                    "default_model": "nvidia/nemotron-3-nano-30b-a3b:free",
                                    "is_enabled": True,
                                },
                                {
                                    "_source_kind": "cloud_provider",
                                    "id": 12,
                                    "label": "Gemini AI Studio",
                                    "provider_code": "gemini",
                                    "default_model": "gemini-2.5-flash-lite",
                                    "is_enabled": True,
                                },
                            ]
                        },
                    )
                )
            for callback in cloud_worker.finished.callbacks:
                callback()

        tab.composer.setPlainText("naber dayi")
        tab._update_chat_controls()

        self.assertTrue(tab.btn_send.isEnabled())
        self.assertIn("Gemini AI Studio", tab.brain_label.text())
        self.assertIn("gemini-2.5-flash-lite", tab.composer_meta.text())

    def test_cloud_runtime_activity_shows_provider_fallback_model(self) -> None:
        text = _format_runtime_activity(
            "cloud",
            {
                "runtime_name": "gemini_chat",
                "model_name": "gemini-2.0-flash-lite",
                "resource_plan": {
                    "profile": "cloud_provider",
                    "provider_code": "gemini",
                    "requested_model": "gemini-3-flash",
                    "actual_model": "gemini-2.0-flash-lite",
                    "fallback_used": True,
                },
            },
        )

        self.assertIn("Cloud runner: gemini_chat / gemini-2.0-flash-lite", text)
        self.assertIn("fallback: gemini-3-flash -> gemini-2.0-flash-lite", text)

    def test_cloud_runtime_fetches_full_provider_record_before_agent_turn(self) -> None:
        def fake_provider_client(record):
            self.assertEqual(record.get("api_key"), "secret-key")
            self.assertEqual(record.get("default_model"), "gemini-2.5-flash-lite")

            def _client(prompt: str) -> str:
                setattr(_client, "model_name", "gemini-2.0-flash-lite")
                plan = getattr(_client, "resource_plan", {}) or {}
                plan.update(
                    {
                        "actual_model": "gemini-2.0-flash-lite",
                        "requested_model": record.get("default_model"),
                        "fallback_used": True,
                    }
                )
                setattr(_client, "resource_plan", plan)
                return '{"mode":"inspect","domain":"orders","objective":"Count current orders","intent_kind":"data_read","request_shape":"scalar","requested_fields":["count"],"metric":"count","period":"today","requires_clarification":false}'

            setattr(_client, "runtime_name", "gemini_chat")
            setattr(_client, "model_name", record.get("default_model"))
            setattr(_client, "resource_plan", {"profile": "cloud_provider", "provider_code": "gemini"})
            return _client

        def fake_run_agent_task(*_args, **kwargs):
            planner = kwargs.get("planner_client")
            if planner is not None:
                planner("fake prompt")
            answer = "2026-05-28 doneminde 0 siparis var."
            return Result.ok(
                answer,
                close_dialog=False,
                data={
                    "answer": answer,
                    "model_invoked": True,
                    "state": {
                        "status": "complete",
                        "active_entities": {"final_answer": answer},
                        "completed_steps": [
                            {
                                "tool_names": ["orders.count"],
                                "result_message": answer,
                                "result_data": {
                                    "answer": answer,
                                    "tool_result": {"count": 0},
                                },
                            }
                        ],
                        "pending_actions": [],
                        "progress_events": [],
                    },
                },
            )

        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "secret-key",
                        "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
                        "default_model": "gemini-2.5-flash-lite",
                        "is_enabled": True,
                    }
                },
            ),
        ) as get_provider_mock, patch(
            "AI.views.chat_tab.build_provider_chat_client",
            side_effect=fake_provider_client,
        ), patch(
            "AI.views.chat_tab.run_agent_task",
            side_effect=fake_run_agent_task,
        ) as agent_mock:
            result = _run_chat_turn_with_runtime(
                "Bugun kac siparisim var?",
                source="cloud",
                runtime_record={"id": 43, "label": "Gemini Free", "default_model": "stale-list-model"},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        get_provider_mock.assert_called_once_with(43)
        self.assertEqual(
            agent_mock.call_args.kwargs["runtime_context"]["model_name"],
            "gemini-2.5-flash-lite",
        )
        self.assertTrue(agent_mock.call_args.kwargs["db_name"])
        runtime = (result.data or {}).get("runtime") or {}
        self.assertEqual(runtime.get("runtime_name"), "gemini_chat")
        self.assertEqual(runtime.get("model_name"), "gemini-2.0-flash-lite")
        self.assertTrue((runtime.get("resource_plan") or {}).get("fallback_used"))
        self.assertEqual((runtime.get("resource_plan") or {}).get("requested_model"), "gemini-2.5-flash-lite")

    def test_failed_typed_interpretation_does_not_escape_active_orders_context(self) -> None:
        def fake_provider_client(_record):
            def _client(_prompt: str) -> str:
                return ""

            setattr(_client, "runtime_name", "gemini_chat")
            setattr(_client, "model_name", "gemini-2.5-flash")
            setattr(_client, "resource_plan", {"provider_code": "gemini"})
            return _client

        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "gemini",
                        "api_key": "secret-key",
                        "default_model": "gemini-2.5-flash",
                        "is_enabled": True,
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            side_effect=fake_provider_client,
        ), patch(
            "AI.views.chat_tab.interpret_agent_turn",
            return_value=Result.fail(
                "typed interpretation invalid",
                close_dialog=False,
                data={
                    "valid": False,
                    "decision_path": "typed_model_turn_interpretation_failed",
                },
            ),
        ), patch("AI.views.chat_tab.run_agent_task") as task_mock, patch(
            "AI.views.chat_tab.run_agent_turn"
        ) as legacy_mock:
            result = _run_chat_turn_with_runtime(
                "Bekleyen kargo sayisi kac?",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
                session_state={"active_domain": "orders"},
            )

        self.assertTrue(result.success, result.message)
        data = dict(result.data or {})
        self.assertEqual(
            data.get("decision_path"),
            "typed_model_turn_interpretation_failed_closed",
        )
        self.assertEqual(data.get("tool_names"), [])
        self.assertIn("orders", str(data.get("answer") or "").casefold())
        runtime = dict(data.get("runtime") or {})
        self.assertFalse(runtime.get("model_invoked"))
        self.assertTrue(runtime.get("model_invocation_attempted"))
        self.assertFalse(runtime.get("model_response_received"))
        task_mock.assert_not_called()
        legacy_mock.assert_not_called()

    def test_approval_dialog_text_contains_preview_and_no_api_notice(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        title, summary, details = tab._approval_dialog_text(
            {
                "title": "Fiyat degisikligi onayi",
                "summary": "1 ilanin satis fiyati 89.99 TL olarak degistirilmeye hazirlaniyor.",
                "risk_level": "high",
                "action_type": "listing.update_price",
                "rows": [
                    {
                        "title": "At Kili Fircasi",
                        "barcode": "BAR-1",
                        "current_sale_price": 100.0,
                        "requested_sale_price": 89.99,
                    }
                ],
            }
        )

        self.assertEqual(title, "Fiyat degisikligi onayi")
        self.assertIn("89.99", summary)
        self.assertIn("At Kili Fircasi", details)
        self.assertIn("Gerçek API isteği henüz gönderilmedi", details)

    def test_approval_dialog_text_renders_every_order_in_large_scope(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        order_numbers = [str(11300000000 + index) for index in range(1, 22)]

        _title, _summary, details = tab._approval_dialog_text(
            {
                "title": "Siparis etiketi olusturma onayi",
                "summary": "21 siparis icin etiket olusturma hazirlaniyor.",
                "risk_level": "medium",
                "action_type": "labels.action_create_labels_from_selected_orders",
                "rows": [
                    {"operation": "create_label", "order_number": order_number}
                    for order_number in order_numbers
                ],
            }
        )

        for order_number in order_numbers:
            self.assertIn(order_number, details)
        preview_lines = [line for line in details.splitlines() if line[:1].isdigit()]
        self.assertEqual(len(preview_lines), 21)
        self.assertNotIn("create_label", details)

    def test_approval_dialog_text_shows_return_claim_and_order_preview(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        claim_id = "75a7c1c0-73a2-49f7-bb8a-366dee971405"
        title, summary, details = tab._approval_dialog_text(
            {
                "title": "Iade onayi",
                "summary": "1 iade onaya hazirlaniyor.",
                "risk_level": "high",
                "action_type": "orders.approve_return_claim",
                "rows": [
                    {
                        "operation": "approve_return",
                        "claim_id": claim_id,
                        "order_number": "11268067005",
                        "waiting_line_item_ids": ["line-1"],
                        "changes": {"status": {"before": "WaitingInAction", "after": "Accepted"}},
                    }
                ],
            }
        )

        self.assertEqual(title, "Iade onayi")
        self.assertIn("1 iade", summary)
        self.assertIn("İade talebini onaylama", details)
        self.assertNotIn("approve_return", details)
        self.assertIn(claim_id, details)
        self.assertIn("11268067005", details)
        self.assertIn("WaitingInAction -> Accepted", details)
        self.assertIn("Gerçek API isteği henüz gönderilmedi", details)

    def test_inline_approval_card_executes_after_chat_approval(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Stok karti onayi",
            "summary": "Stok karti olusturulacak.",
            "risk_level": "medium",
            "action_type": "stock.item_create",
            "approval_required": True,
            "execute_enabled": True,
            "warnings": [],
            "rows": [{"after": {"sku": "APPROVE-1", "name": "Approve Test"}}],
        }

        tab._set_agent_state(status="approval_required", pending_action=action)
        tab._show_action_approval_dialog(action)
        self.assertIn("Onay gerekiyor", tab.transcript.toPlainText())
        self.assertIn("Stok karti onayi", tab.transcript.toPlainText())

        with patch(
            "AI.views.chat_tab.execute_approved_operation",
            return_value=Result.ok("Runtime execute edildi.", close_dialog=False),
        ) as execute_mock, patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
            tab.composer.setPlainText("onayla ve calistir")
            tab._send_message()

        execute_mock.assert_called_once()
        self.assertEqual(execute_mock.call_args.args[0], action)
        self.assertEqual(execute_mock.call_args.kwargs.get("approved_by"), "chat_ui")
        self.assertIn("Runtime execute edildi", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "executed")
        self.assertIn("Aksiyon", tab.agent_state_title.text())
        self.assertIn("Runtime execute edildi", tab.agent_state_text.text())

    def test_inline_approval_card_click_executes_active_action(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Iade onayi",
            "summary": "CLAIM-CARD-CLICK onaylanacak.",
            "risk_level": "high",
            "action_type": "orders.approve_return_claim",
            "approval_required": True,
            "execute_enabled": True,
            "rows": [{"claim_id": "CLAIM-CARD-CLICK", "order_number": "ORD-CARD-CLICK"}],
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab._show_action_approval_dialog(action)
        token = tab._latest_approval_card_token

        card_html = tab.transcript.toHtml()
        self.assertIn(f"orderscout://approval/approve/{token}", card_html)
        self.assertIn(f"orderscout://approval/cancel/{token}", card_html)

        execute_result = Result.ok(
            "Iade onaylandi.",
            close_dialog=False,
            data={
                "verify": {"verified": True, "claim_ids": ["CLAIM-CARD-CLICK"]},
                "audit": {"operation": "orders.approve_return_claim"},
            },
        )
        with patch("AI.views.chat_tab.execute_approved_operation", return_value=execute_result) as execute_mock, patch(
            "AI.views.chat_tab.SyncWorker",
            _ImmediateWorker,
        ):
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{token}"))

        execute_mock.assert_called_once()
        self.assertEqual(execute_mock.call_args.args[0], action)
        self.assertEqual(execute_mock.call_args.kwargs.get("approved_by"), "chat_ui")
        transcript = tab.transcript.toPlainText()
        self.assertIn("Onayla ve çalıştır", transcript)
        self.assertIn("Iade onaylandi", transcript)
        self.assertIn("verify: dogrulandi", transcript)
        self.assertEqual(tab._agent_state.get("status"), "executed")

    def test_approved_action_runs_in_worker_and_rejects_duplicate_clicks_while_busy(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Kargo onayi",
            "summary": "ORD-ASYNC kargosu degisecek.",
            "risk_level": "high",
            "action_type": "orders.change_order_cargo_provider",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab._show_action_approval_dialog(action)
        token = tab._latest_approval_card_token
        execute_result = Result.ok(
            "Kargo degisikligi tamamlandi.",
            close_dialog=False,
            data={"verify": {"verified": True, "order_numbers": ["ORD-ASYNC"]}},
        )

        _DeferredWorker.instances.clear()
        with patch("AI.views.chat_tab.SyncWorker", _DeferredWorker), patch(
            "AI.views.chat_tab.execute_approved_operation",
            return_value=execute_result,
        ) as execute_mock:
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{token}"))

            self.assertEqual(len(_DeferredWorker.instances), 1)
            worker = _DeferredWorker.instances[0]
            self.assertIs(tab._action_worker, worker)
            self.assertTrue(worker.started)
            execute_mock.assert_not_called()
            self.assertFalse(tab.composer.isEnabled())

            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{token}"))
            self.assertEqual(len(_DeferredWorker.instances), 1)
            self.assertIn("Bir islem zaten calisiyor", tab.transcript.toPlainText())

            result = worker.func(
                *worker.args,
                progress_callback=lambda percent, message: [
                    callback(percent, message)
                    for callback in list(worker.progress.callbacks)
                ],
            )
            for callback in list(worker.result_ready.callbacks):
                callback(result)
            worker.started = False
            for callback in list(worker.finished.callbacks):
                callback()

        execute_mock.assert_called_once_with(action, approved_by="chat_ui")
        self.assertIsNone(tab._action_worker)
        self.assertIn("Kargo degisikligi tamamlandi", tab.transcript.toPlainText())
        self.assertIn("verify: dogrulandi", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "executed")

    def test_persisted_task_approval_resume_is_deferred_to_action_worker(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Iade onayi",
            "summary": "CLAIM-ASYNC onaylanacak.",
            "risk_level": "high",
            "action_type": "orders.approve_return_claim",
            "approval_required": True,
            "execute_enabled": True,
            "_agent_task_session_id": "task-async-resume",
            "_agent_task_resume": True,
        }
        completed_state = {
            "session_id": "task-async-resume",
            "status": "complete",
            "active_entities": {"final_answer": "CLAIM-ASYNC onaylandi ve dogrulandi."},
            "completed_steps": [{"tool_names": ["returns.approve.prepare"]}],
            "remaining_steps": [],
            "pending_actions": [],
        }
        tab._set_agent_state(status="approval_required", pending_action=action)

        _DeferredWorker.instances.clear()
        with patch("AI.views.chat_tab.SyncWorker", _DeferredWorker), patch(
            "AI.views.chat_tab.resume_agent_task_by_id",
            return_value=Result.ok(
                "Task tamamlandi.",
                close_dialog=False,
                data={"state": completed_state, "answer": "CLAIM-ASYNC onaylandi ve dogrulandi."},
            ),
        ) as resume_mock:
            tab.composer.setPlainText("onayla")
            tab._send_message()

            worker = _DeferredWorker.instances[-1]
            resume_mock.assert_not_called()
            self.assertTrue(worker.started)
            result = worker.func(
                *worker.args,
                progress_callback=lambda percent, message: [
                    callback(percent, message)
                    for callback in list(worker.progress.callbacks)
                ],
            )
            for callback in list(worker.result_ready.callbacks):
                callback(result)
            worker.started = False
            for callback in list(worker.finished.callbacks):
                callback()

        resume_mock.assert_called_once_with(
            "task-async-resume",
            approved_by="chat_ui",
            progress_callback=ANY,
            db_name=DB_NAME,
        )
        self.assertIn("CLAIM-ASYNC onaylandi ve dogrulandi", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "completed")

    def test_inline_approval_card_click_cancels_without_execute_and_stale_card_is_inert(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        first_action = {
            "title": "Ilk kargo onayi",
            "summary": "ORD-CARD-OLD kargosu degisecek.",
            "risk_level": "high",
            "action_type": "orders.change_order_cargo_provider",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab._set_agent_state(status="approval_required", pending_action=first_action)
        tab._show_action_approval_dialog(first_action)
        stale_token = tab._latest_approval_card_token

        second_action = {
            "title": "Aktif kargo onayi",
            "summary": "ORD-CARD-ACTIVE kargosu degisecek.",
            "risk_level": "high",
            "action_type": "orders.change_order_cargo_provider",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab._set_agent_state(status="approval_required", pending_action=second_action)
        tab._show_action_approval_dialog(second_action)
        active_token = tab._latest_approval_card_token

        with patch("AI.views.chat_tab.execute_approved_operation") as execute_mock:
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{stale_token}"))
            execute_mock.assert_not_called()
            self.assertIn("artik aktif degil", tab.transcript.toPlainText())

            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/cancel/{active_token}"))
            execute_mock.assert_not_called()

        transcript = tab.transcript.toPlainText()
        self.assertIn("Vazgeç", transcript)
        self.assertIn("Riskli islem iptal edildi", transcript)
        self.assertEqual(tab._agent_state.get("status"), "cancelled")

    def test_inline_approval_card_resumes_persisted_agent_task_after_chat_approval(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Iade onayi",
            "summary": "CLAIM-RESUME onaylanacak.",
            "risk_level": "high",
            "action_type": "orders.approve_return_claim",
            "approval_required": True,
            "execute_enabled": True,
            "_agent_task_session_id": "task-session-resume",
            "_agent_task_resume": True,
        }
        resumed_state = {
            "session_id": "task-session-resume",
            "status": "complete",
            "active_entities": {"final_answer": "CLAIM-RESUME iadesi onaylandi ve dogrulandi."},
            "completed_steps": [{"tool_names": ["returns.approve.prepare", "orders.approve_return_claim"]}],
            "remaining_steps": [],
            "pending_actions": [],
        }

        tab._set_agent_state(status="approval_required", pending_action=action)
        tab._show_action_approval_dialog(action)
        self.assertIn("Onay gerekiyor", tab.transcript.toPlainText())

        with patch(
            "AI.views.chat_tab.resume_agent_task_by_id",
            return_value=Result.ok("Task resume edildi.", close_dialog=False, data={"state": resumed_state, "state_path": "C:/tmp/task.json"}),
        ) as resume_mock, patch("AI.views.chat_tab.execute_approved_operation") as execute_mock, patch(
            "AI.views.chat_tab.SyncWorker",
            _ImmediateWorker,
        ):
            tab.composer.setPlainText("tamam onayliyorum")
            tab._send_message()

        resume_mock.assert_called_once_with(
            "task-session-resume",
            approved_by="chat_ui",
            progress_callback=ANY,
            db_name=DB_NAME,
        )
        execute_mock.assert_not_called()
        self.assertIn("CLAIM-RESUME iadesi onaylandi ve dogrulandi", tab.transcript.toPlainText())
        self.assertNotIn("task-session-resume", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "completed")
        self.assertIn("orders.approve_return_claim", tab.agent_state_text.text())

    def test_task_approval_renders_next_pending_action_as_new_inline_card(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        first_action = {
            "title": "Etiket onayi",
            "summary": "Iki siparis yazdirilacak.",
            "risk_level": "medium",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "_agent_task_session_id": "task-session-two-phase",
            "_agent_task_resume": True,
        }
        second_action = {
            "title": "Fis durumu onayi",
            "summary": "Iki siparis fis cikarildi olarak isaretlenecek.",
            "risk_level": "medium",
            "action_type": "labels.mark_orders_extracted_from_label_result",
            "approval_required": True,
            "execute_enabled": True,
        }
        resumed_state = {
            "session_id": "task-session-two-phase",
            "status": "pending_approval",
            "completed_steps": [
                {
                    "tool_names": ["labels.create_from_orders.prepare"],
                    "result_data": {
                        "answer": (
                            "ORD-1 ve ORD-2 etiketleri olusturuldu. "
                            "Simdi fis durumunu isaretlemek icin onayini bekliyorum."
                        )
                    },
                }
            ],
            "remaining_steps": [],
            "pending_actions": [second_action],
            "action_history": [
                {
                    "phase": "execute",
                    "status": "executed",
                    "action_type": "labels.action_create_labels_from_selected_orders",
                    "success": True,
                    "verify": {"verified": True, "order_numbers": ["ORD-1", "ORD-2"]},
                }
            ],
        }
        completed_state = {
            "session_id": "task-session-two-phase",
            "status": "complete",
            "active_entities": {
                "final_answer": (
                    "ORD-1 ve ORD-2 icin etiket ve fis islemleri tamamlandi ve dogrulandi."
                )
            },
            "completed_steps": [
                {"tool_names": ["labels.create_from_orders.prepare"]},
                {"tool_names": ["operations.manual_action.route"]},
            ],
            "remaining_steps": [],
            "pending_actions": [],
            "action_history": [
                {
                    "phase": "execute",
                    "status": "executed",
                    "action_type": "labels.action_create_labels_from_selected_orders",
                    "success": True,
                    "verify": {"verified": True, "order_numbers": ["ORD-1", "ORD-2"]},
                },
                {
                    "phase": "execute",
                    "status": "executed",
                    "action_type": "labels.mark_orders_extracted_from_label_result",
                    "success": True,
                    "verify": {"verified": True, "order_numbers": ["ORD-1", "ORD-2"]},
                },
            ],
        }
        tab._set_agent_state(status="approval_required", pending_action=first_action)
        tab._show_action_approval_dialog(first_action)
        first_token = tab._latest_approval_card_token

        with patch(
            "AI.views.chat_tab.resume_agent_task_by_id",
            side_effect=[
                Result.ok(
                    "Ilk aksiyon calisti.",
                    close_dialog=False,
                    data={
                        "state": resumed_state,
                        "execute": {"verify": {"verified": True, "order_numbers": ["ORD-1", "ORD-2"]}},
                        "state_path": "C:/tmp/two-phase.json",
                    },
                ),
                Result.ok(
                    "Iki aksiyon tamamlandi.",
                    close_dialog=False,
                    data={
                        "state": completed_state,
                        "execute": {"verify": {"verified": True, "order_numbers": ["ORD-1", "ORD-2"]}},
                        "state_path": "C:/tmp/two-phase.json",
                        "answer": "ORD-1 ve ORD-2 icin etiket ve fis islemleri tamamlandi ve dogrulandi.",
                    },
                ),
            ],
        ) as resume_mock, patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{first_token}"))

        second_token = tab._latest_approval_card_token
        self.assertNotEqual(second_token, first_token)
        active_action = tab._approval_card_actions[second_token]
        self.assertEqual(active_action.get("action_type"), "labels.mark_orders_extracted_from_label_result")
        self.assertEqual(active_action.get("_agent_task_session_id"), "task-session-two-phase")
        transcript = tab.transcript.toPlainText()
        self.assertIn("Gorev sonraki riskli adima ilerledi", transcript)
        self.assertIn("Fis durumu onayi", transcript)
        self.assertIn("Simdi fis durumunu isaretlemek icin onayini bekliyorum", transcript)
        self.assertIn("verify: dogrulandi", transcript)
        self.assertEqual(tab._agent_state.get("status"), "approval_required")

        with patch(
            "AI.views.chat_tab.resume_agent_task_by_id",
            return_value=Result.ok(
                "Iki aksiyon tamamlandi.",
                close_dialog=False,
                data={
                    "state": completed_state,
                    "execute": {"verify": {"verified": True, "order_numbers": ["ORD-1", "ORD-2"]}},
                    "state_path": "C:/tmp/two-phase.json",
                    "answer": "ORD-1 ve ORD-2 icin etiket ve fis islemleri tamamlandi ve dogrulandi.",
                },
            ),
        ) as second_resume_mock, patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{second_token}"))

        second_resume_mock.assert_called_once_with(
            "task-session-two-phase",
            approved_by="chat_ui",
            progress_callback=ANY,
            db_name=DB_NAME,
            task_store_root="C:\\tmp",
        )
        self.assertNotIn("artik aktif degil", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "completed")
        self.assertEqual(
            tab._conversation_state.get("session_id"),
            "task-session-two-phase",
        )
        self.assertEqual(tab._conversation_state.get("status"), "complete")
        self.assertEqual(tab._conversation_state.get("pending_actions"), [])

    def test_task_cancel_updates_persisted_session_instead_of_only_ui_state(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Etiket onayi",
            "summary": "Iki siparis yazdirilacak.",
            "risk_level": "medium",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "_agent_task_session_id": "task-session-cancel",
            "_agent_task_resume": True,
            "_agent_task_store_root": "C:\\tmp",
        }
        cancelled_state = {
            "session_id": "task-session-cancel",
            "status": "cancelled",
            "completed_steps": [],
            "remaining_steps": [],
            "pending_actions": [],
            "action_history": [{"phase": "cancel", "status": "cancelled"}],
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab.composer.setPlainText("vazgec")

        with patch(
            "AI.views.chat_tab.cancel_agent_task_by_id",
            return_value=Result.ok(
                "Agent gorevi iptal edildi. Gercek islem calismadi.",
                close_dialog=False,
                data={"state": cancelled_state, "state_path": "C:/tmp/cancelled.json"},
            ),
        ) as cancel_mock, patch("AI.views.chat_tab.resume_agent_task_by_id") as resume_mock, patch(
            "AI.views.chat_tab.execute_approved_operation"
        ) as execute_mock:
            tab._send_message()

        cancel_mock.assert_called_once_with(
            "task-session-cancel",
            cancelled_by="chat_ui",
            task_store_root="C:\\tmp",
        )
        resume_mock.assert_not_called()
        execute_mock.assert_not_called()
        self.assertIn("Agent gorevi iptal edildi", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "cancelled")

    def test_failed_task_execute_keeps_same_pending_card_retryable(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Etiket onayi",
            "summary": "ORD-RETRY etiketi olusturulacak.",
            "risk_level": "medium",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "_agent_task_session_id": "task-session-retry",
            "_agent_task_resume": True,
            "_agent_task_state_path": "C:/tmp/retry.json",
        }
        failed_state = {
            "session_id": "task-session-retry",
            "status": "failed",
            "completed_steps": [{"tool_names": ["labels.create_from_orders.prepare"]}],
            "remaining_steps": [],
            "pending_actions": [
                {
                    key: value
                    for key, value in action.items()
                    if not key.startswith("_agent_task_")
                }
            ],
            "action_history": [
                {
                    "phase": "execute",
                    "status": "failed",
                    "action_type": "labels.action_create_labels_from_selected_orders",
                    "success": False,
                    "verify": {"verified": False},
                }
            ],
        }
        completed_state = {
            "session_id": "task-session-retry",
            "status": "complete",
            "active_entities": {"final_answer": "ORD-RETRY etiketi olusturuldu ve dogrulandi."},
            "completed_steps": [{"tool_names": ["labels.create_from_orders.prepare"]}],
            "remaining_steps": [],
            "pending_actions": [],
            "action_history": [],
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab._show_action_approval_dialog(action)
        token = tab._latest_approval_card_token
        failed_result = Result.fail("Gecici dosya hatasi.", close_dialog=False)
        failed_result.data = {
            "state": failed_state,
            "execute": {"verify": {"verified": False}},
            "state_path": "C:/tmp/retry.json",
        }

        with patch("AI.views.chat_tab.resume_agent_task_by_id", return_value=failed_result), patch(
            "AI.views.chat_tab.SyncWorker",
            _ImmediateWorker,
        ):
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{token}"))

        self.assertEqual(tab._agent_state.get("status"), "approval_required")
        self.assertEqual(
            (tab._pending_action_from_state() or {}).get("_agent_task_session_id"),
            "task-session-retry",
        )

        with patch(
            "AI.views.chat_tab.resume_agent_task_by_id",
            return_value=Result.ok(
                "Retry basarili.",
                close_dialog=False,
                data={
                    "state": completed_state,
                    "execute": {"verify": {"verified": True, "order_numbers": ["ORD-RETRY"]}},
                    "state_path": "C:/tmp/retry.json",
                    "answer": "ORD-RETRY etiketi olusturuldu ve dogrulandi.",
                },
            ),
        ) as retry_mock, patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
            tab.transcript.anchorClicked.emit(QUrl(f"orderscout://approval/approve/{token}"))

        retry_mock.assert_called_once_with(
            "task-session-retry",
            approved_by="chat_ui",
            progress_callback=ANY,
            db_name=DB_NAME,
            task_store_root="C:\\tmp",
        )
        self.assertNotIn("artik aktif degil", tab.transcript.toPlainText())
        self.assertEqual(tab._agent_state.get("status"), "completed")
        self.assertEqual(tab._conversation_state.get("session_id"), "task-session-retry")
        self.assertEqual(tab._conversation_state.get("status"), "complete")
        self.assertEqual(tab._conversation_state.get("pending_actions"), [])

    def test_pending_action_can_be_approved_from_chat_text_without_new_llm_turn(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Iade onayi",
            "summary": "CLAIM-CHAT onay bekliyor.",
            "risk_level": "high",
            "action_type": "orders.approve_return_claim",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab.composer.setPlainText("tamam onayliyorum")

        with patch(
            "AI.views.chat_tab.execute_approved_operation",
            return_value=Result.ok(
                "Runtime execute edildi.",
                close_dialog=False,
                data={"verify": {"verified": True, "claim_ids": ["CLAIM-CHAT"]}, "audit": {"operation": "orders.approve_return_claim"}},
            ),
        ) as execute_mock, patch("AI.views.chat_tab._run_chat_turn_with_runtime") as runner_mock, patch(
            "AI.views.chat_tab.SyncWorker",
            _ImmediateWorker,
        ):
            tab._send_message()

        execute_mock.assert_called_once()
        self.assertEqual(execute_mock.call_args.args[0], action)
        self.assertEqual(execute_mock.call_args.kwargs.get("approved_by"), "chat_ui")
        runner_mock.assert_not_called()
        transcript = tab.transcript.toPlainText()
        self.assertIn("tamam onayliyorum", transcript)
        self.assertIn("Onayli aksiyon calistirildi", transcript)
        self.assertIn("verify: dogrulandi", transcript)
        self.assertIn("iade: CLAIM-CHAT", transcript)
        self.assertIn("audit: orders.approve_return_claim", transcript)
        self.assertEqual(tab._agent_state.get("status"), "executed")

    def test_pending_action_can_be_cancelled_from_chat_text_without_execute(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "title": "Kargo onayi",
            "summary": "ORD-CHAT kargo degisecek.",
            "risk_level": "high",
            "action_type": "orders.change_order_cargo_provider",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab.composer.setPlainText("hayir iptal et")

        with patch("AI.views.chat_tab.execute_approved_operation") as execute_mock, patch("AI.views.chat_tab._run_chat_turn_with_runtime") as runner_mock:
            tab._send_message()

        execute_mock.assert_not_called()
        runner_mock.assert_not_called()
        transcript = tab.transcript.toPlainText()
        self.assertIn("hayir iptal et", transcript)
        self.assertIn("Riskli islem iptal edildi", transcript)
        self.assertEqual(tab._agent_state.get("status"), "cancelled")

    def test_pending_scope_question_with_do_not_run_is_not_cancel_reply(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)

        self.assertEqual(
            tab._approval_reply_intent(
                "Şu an onay bekleyen işlem tam olarak neyi değiştirecek? Çalıştırma."
            ),
            "",
        )
        self.assertEqual(tab._approval_reply_intent("hayır iptal et"), "cancel")

        label_action = {
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
        }
        scope_question = (
            "Bu hazırlık hangi sipariş kümesine ve hangi şablona bağlı, "
            "herhangi bir dosya üretildi mi?"
        )
        self.assertFalse(
            tab._pending_action_revision_requested(scope_question, label_action)
        )
        self.assertEqual(tab._approval_reply_intent(scope_question), "")

    def test_pending_scope_read_keeps_pending_action_after_answer(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "summary": "3 adet manuel stok girisi hazir.",
            "action_type": "stock.action_manual_in",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab.source_combo.blockSignals(True)
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
        tab.source_combo.blockSignals(False)
        item = QListWidgetItem("Gemini pending read")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "_source_kind": "cloud_provider",
                "id": 43,
                "label": "Gemini pending read",
                "provider_code": "gemini",
                "default_model": "gemini-test",
                "is_enabled": True,
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentItem(item)
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab.composer.setPlainText(
            "Şu an onay bekleyen işlem tam olarak neyi değiştirecek? Çalıştırma."
        )
        result = Result.ok(
            "Kapsam okundu.",
            data={
                "answer": "Üç adet manuel giriş hazırlığı; henüz yazım yok.",
                "approval_required": False,
                "tool_calls": [],
            },
        )

        with patch("AI.views.chat_tab._run_chat_turn_with_runtime", return_value=result), patch(
            "AI.views.chat_tab.SyncWorker",
            _ImmediateWorker,
        ):
            tab._send_message()

        self.assertEqual(
            (tab._agent_state.get("pending_action") or {}).get("action_type"),
            "stock.action_manual_in",
        )
        self.assertEqual(tab._agent_state.get("status"), "approval_required")

    def test_pending_label_scope_correction_supersedes_before_hayir_cancel_intent(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "summary": "1 siparis icin etiket hazirlaniyor.",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        prompt = "Hayir, ilk 4 degil; listedeki 21 siparisin tamamini hazirla."
        tab.composer.setPlainText(prompt)

        with patch.object(
            tab,
            "_supersede_pending_action_for_revision",
            wraps=tab._supersede_pending_action_for_revision,
        ) as supersede_mock, patch.object(
            tab,
            "_handle_pending_action_reply",
            wraps=tab._handle_pending_action_reply,
        ) as reply_mock:
            tab._send_message()

        supersede_mock.assert_called_once_with(prompt)
        reply_mock.assert_not_called()
        self.assertEqual(len(tab._superseded_actions), 1)
        self.assertEqual(tab._superseded_actions[0].get("status"), "superseded")
        self.assertNotIn("Riskli islem iptal edildi", tab.transcript.toPlainText())

    def test_pending_label_all_waiting_scope_revision_supersedes_stale_card(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "summary": "4 siparis icin etiket hazirlaniyor.",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "action_id": "action-scope-revision",
            "_agent_task_session_id": "task-scope-revision",
            "_agent_task_store_root": "C:\\tmp\\scope-revision",
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        prompt = "bütün bekleyen siparişler için istemiştim"
        tab.composer.setPlainText(prompt)

        superseded_state = {
            "session_id": "task-scope-revision",
            "status": "superseded",
            "completed_steps": [],
            "remaining_steps": [],
            "pending_actions": [],
            "action_history": [{"phase": "supersede", "status": "superseded"}],
        }
        with patch(
            "AI.views.chat_tab.supersede_agent_task_by_id",
            return_value=Result.ok(
                "Eski kapsam gecersiz kilindi.",
                close_dialog=False,
                data={"state": superseded_state},
            ),
        ) as persisted_supersede_mock, patch.object(
            tab,
            "_supersede_pending_action_for_revision",
            wraps=tab._supersede_pending_action_for_revision,
        ) as supersede_mock, patch.object(
            tab,
            "_handle_pending_action_reply",
            wraps=tab._handle_pending_action_reply,
        ) as reply_mock:
            tab._send_message()

        supersede_mock.assert_called_once_with(prompt)
        persisted_supersede_mock.assert_called_once_with(
            "task-scope-revision",
            superseded_by="chat_scope_revision",
            reason="scope_revised_from_chat_ui",
            action_id="action-scope-revision",
            task_store_root="C:\\tmp\\scope-revision",
        )
        reply_mock.assert_not_called()
        self.assertEqual(len(tab._superseded_actions), 1)
        self.assertEqual(tab._superseded_actions[0].get("status"), "superseded")
        self.assertEqual(
            tab._superseded_actions[0].get("action_id"),
            "action-scope-revision",
        )
        self.assertEqual(tab._conversation_state.get("status"), "superseded")
        self.assertIn("geçersiz kılındı", tab.transcript.toPlainText())

    def test_explicit_superseded_action_approval_is_not_applied_to_active_action(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        active_id = "2b690dec6d4edbc98264ae27fb642da7"
        stale_id = "0a461f4c7c6adef0369cfa633fb955a7"
        action = {
            "summary": "12 siparis icin TANEX 2610 etiketi hazirlaniyor.",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "action_id": active_id,
            "approval_required": True,
            "execute_enabled": True,
            "_agent_task_session_id": "task-stale-action-reference",
        }
        tab._set_agent_state(status="approval_required", pending_action=action)
        tab._superseded_actions.append(
            {
                "action_id": stale_id,
                "status": "superseded",
                "action_type": action["action_type"],
            }
        )

        with patch.object(tab, "_start_approved_action_worker") as start_mock:
            handled = tab._handle_pending_action_reply(
                f"eski action_id {stale_id} onayla ve çalıştır"
            )

        self.assertTrue(handled)
        start_mock.assert_called_once()
        submitted_action = start_mock.call_args.args[0]
        self.assertEqual(submitted_action.get("action_id"), stale_id)
        self.assertNotEqual(submitted_action.get("action_id"), active_id)
        self.assertEqual(
            start_mock.call_args.kwargs.get("task_session_id"),
            "task-stale-action-reference",
        )

    def test_pending_label_identity_or_delivered_objection_supersedes_stale_card(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        action = {
            "summary": "1 siparis icin etiket hazirlaniyor.",
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
        }

        for prompt in (
            "baskan bu siparis ne aq kimin siparisi bu",
            "tamam da bu siparis teslim edilmis, yanlis siparis gosterdin",
        ):
            self.assertTrue(
                tab._pending_action_revision_requested(prompt, action),
                prompt,
            )

    def test_offscreen_source_ui_2026_07_15_chain_replaces_four_and_keeps_final_seven(self) -> None:
        tab = AITab()
        self.addCleanup(tab.deleteLater)
        self.addCleanup(tab.close)
        tab.model_list.clear()
        item = QListWidgetItem("Offscreen local test model")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "repo_id": "orderscout/offscreen-test",
                "filename": "offscreen.gguf",
                "_source_kind": "local_model",
            },
        )
        tab.model_list.addItem(item)
        tab.model_list.setCurrentRow(0)

        seven = [f"ORD-OFFSCREEN-SEVEN-{index}" for index in range(7)]
        four = [f"ORD-OFFSCREEN-STALE-{index}" for index in range(4)]
        read_context = SelectionSnapshot.from_order_numbers(
            seven,
            source_tool="orders.ready_to_ship",
            period="all",
            account_by_order={order_number: "77" for order_number in seven},
            environment_by_account={"77": "production"},
            account_scopes=[
                {
                    "api_account_id": 77,
                    "store_name": "Modo Di Bellezza",
                    "platform": "trendyol",
                    "environment": "production",
                }
            ],
        ).to_context()

        def label_action(order_numbers: list[str]) -> dict:
            raw = {
                "title": "Sipariş etiketi oluşturma onayı",
                "summary": f"{len(order_numbers)} sipariş için etiket oluşturma hazırlanıyor.",
                "risk_level": "medium",
                "action_type": "labels.action_create_labels_from_selected_orders",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {"payload": {"order_numbers": list(order_numbers)}},
                "rows": [{"order_number": value} for value in order_numbers],
            }
            return PendingActionSnapshot.from_action(raw).to_action(raw)

        stale_action = label_action(four)
        revised_action = label_action(seven)
        final_action = label_action(seven)
        messages = [
            "kaç sipariş var bekleyen",
            "bi daha bak hele",
            "hangi mağazaya bakıyosun şuan",
            "toplam bekleyen kaç sipariş var",
            "bu siparişleri yazdırabilr misin",
            "bütün bekleyen siparişler için istemiştim",
            "tamam yazdır bu 7 taneyi",
        ]
        responses = [
            Result.ok(
                "Kargoya hazır 7 sipariş var.",
                close_dialog=False,
                data={
                    "answer": "Kargoya hazır 7 sipariş var.",
                    "tool_call": {"tool": "orders.ready_to_ship_count", "arguments": {"period": "all"}},
                    "tool_calls": [{"tool": "orders.ready_to_ship_count", "arguments": {"period": "all"}}],
                    "tool_result": {"count": 7, "period": "all", "simulated_excluded": 5},
                    "conversation_context": {
                        "kind": "orders_ready_to_ship_scope",
                        "source_tool": "orders.ready_to_ship_count",
                        "period": "all",
                        "total_count": 7,
                        "account_scopes": read_context["account_scopes"],
                    },
                },
            ),
            Result.ok(
                "Authoritative Orders listesinden yeniden okudum: 7 sipariş.",
                close_dialog=False,
                data={
                    "answer": "Authoritative Orders listesinden yeniden okudum: 7 sipariş.",
                    "tool_call": {"tool": "orders.ready_to_ship", "arguments": {"period": "all"}},
                    "tool_calls": [{"tool": "orders.ready_to_ship", "arguments": {"period": "all"}}],
                    "tool_result": {"order_numbers": seven},
                    "conversation_context": read_context,
                },
            ),
            Result.ok(
                "Modo Di Bellezza (trendyol / production) kapsamına bakıyorum.",
                close_dialog=False,
                data={
                    "answer": "Modo Di Bellezza (trendyol / production) kapsamına bakıyorum.",
                    "tool_calls": [],
                },
            ),
            Result.ok(
                "Toplam 7 bekleyen sipariş var.",
                close_dialog=False,
                data={
                    "answer": "Toplam 7 bekleyen sipariş var.",
                    "tool_call": {"tool": "orders.ready_to_ship", "arguments": {"period": "all"}},
                    "tool_calls": [{"tool": "orders.ready_to_ship", "arguments": {"period": "all"}}],
                    "tool_result": {"order_numbers": seven},
                    "conversation_context": read_context,
                },
            ),
            Result.ok(
                "Onay gerekiyor: 4 sipariş için etiket hazırlanıyor.",
                close_dialog=False,
                data={
                    "answer": "Onay gerekiyor: 4 sipariş için etiket hazırlanıyor.",
                    "approval_required": True,
                    "action_proposal": stale_action,
                    "tool_call": {"tool": "labels.create_from_orders.prepare", "arguments": {}},
                    "tool_calls": [{"tool": "labels.create_from_orders.prepare", "arguments": {}}],
                    "tool_result": {"action": stale_action},
                    "conversation_context": SelectionSnapshot.from_order_numbers(
                        four,
                        source_tool="labels.create_from_orders.prepare",
                    ).to_context(),
                },
            ),
            Result.ok(
                "Düzeltildi: 7 sipariş için etiket hazırlanıyor.",
                close_dialog=False,
                data={
                    "answer": "Düzeltildi: 7 sipariş için etiket hazırlanıyor.",
                    "approval_required": True,
                    "action_proposal": revised_action,
                    "tool_call": {"tool": "labels.create_from_orders.prepare", "arguments": {}},
                    "tool_calls": [{"tool": "labels.create_from_orders.prepare", "arguments": {}}],
                    "tool_result": {"action": revised_action},
                    "conversation_context": SelectionSnapshot.from_order_numbers(
                        seven,
                        source_tool="labels.create_from_orders.prepare",
                    ).to_context(),
                },
            ),
            Result.ok(
                "Onay gerekiyor: seçili 7 sipariş için etiket hazırlanıyor.",
                close_dialog=False,
                data={
                    "answer": "Onay gerekiyor: seçili 7 sipariş için etiket hazırlanıyor.",
                    "approval_required": True,
                    "action_proposal": final_action,
                    "tool_call": {"tool": "labels.create_from_orders.prepare", "arguments": {}},
                    "tool_calls": [{"tool": "labels.create_from_orders.prepare", "arguments": {}}],
                    "tool_result": {"action": final_action},
                    "conversation_context": SelectionSnapshot.from_order_numbers(
                        seven,
                        source_tool="labels.create_from_orders.prepare",
                    ).to_context(),
                },
            ),
        ]
        calls: list[dict] = []

        def fake_runtime(message: str, **kwargs) -> Result:
            calls.append({"message": message, "history": list(kwargs.get("history") or [])})
            return responses[len(calls) - 1]

        with patch("AI.views.chat_tab.build_local_resource_plan", return_value=_SafePlan()), patch(
            "AI.views.chat_tab._run_chat_turn_with_runtime",
            side_effect=fake_runtime,
        ), patch("AI.views.chat_tab.SyncWorker", _ImmediateWorker):
            for message in messages:
                tab.composer.setPlainText(message)
                tab._send_message()

        self.assertEqual([row["message"] for row in calls], messages)
        self.assertEqual(len(tab._superseded_actions), 2)
        self.assertTrue(all(row.get("status") == "superseded" for row in tab._superseded_actions))
        pending = tab._pending_action_from_state() or {}
        pending_snapshot = PendingActionSnapshot.from_action(pending)
        self.assertEqual(tuple(ref.record_id for ref in pending_snapshot.refs), tuple(seven))
        self.assertEqual(pending_snapshot.selected_record_count, 7)
        self.assertEqual(pending_snapshot.invariant_problems(pending), [])
        self.assertEqual(calls[-1]["history"][-1]["content"], messages[-1])
        self.assertTrue(
            any(
                isinstance(row.get("context"), dict)
                and row["context"].get("selection_id") == read_context["selection_id"]
                for row in calls[-1]["history"]
            )
        )
        transcript = tab.transcript.toPlainText()
        self.assertIn("geçersiz kılındı", transcript)
        self.assertIn("seçili 7 sipariş", transcript)
        self.assertNotIn("sipariş bulunamadı", transcript.casefold())


    def test_source_chat_r334_policy_explanation_uses_grounded_context_not_capability_catalog(self) -> None:
        prompts: list[str] = []

        def planner(prompt: str) -> str:
            prompts.append(prompt)
            if len(prompts) == 1:
                return json.dumps(
                    {
                        "mode": "explain",
                        "domain": "orders",
                        "objective": "Veri kaynağı ve onay mekanizmasını açıkla",
                        "intent_kind": "policy_explanation",
                        "request_shape": "policy_explanation",
                        "explanation_topics": ["data_source", "approval"],
                        "requested_fields": [],
                        "direct_output_fields": [],
                        "information_source": "unspecified",
                        "operation_policy": "allow_new_operations",
                        "calculation_count": 0,
                        "calculation_grouping": "none",
                        "derived_calculation": {},
                        "derived_calculations": [],
                        "reason": "Kullanıcı çalışma politikasını soruyor.",
                        "requires_clarification": False,
                        "clarification": "",
                    },
                    ensure_ascii=False,
                )
            if len(prompts) == 2:
                return json.dumps(
                    {
                        "explanation_topics": [
                            "data_source",
                            "approval",
                        ]
                    },
                    ensure_ascii=False,
                )
            return (
                "API güncellemesi istemezsen son kaydedilmiş yerel snapshot'ı kullanırım; "
                "pazaryerini sessizce yenilemem. Salt okunur kontroller onay istemez. "
                "Dosya, DB veya dış sistem etkisini exact kapsamla hazırlayıp açık onayından "
                "sonra çalıştırır, sonucu read-back ile doğrularım."
            )

        setattr(planner, "runtime_name", "openrouter_chat")
        setattr(planner, "model_name", "deepseek/deepseek-v4-flash")
        setattr(
            planner,
            "resource_plan",
            {"actual_model": "deepseek/deepseek-v4-flash"},
        )
        with patch(
            "AI.views.chat_tab.ai_actions.action_get_provider_account",
            return_value=Result.ok(
                "loaded",
                close_dialog=False,
                data={
                    "record": {
                        "id": 43,
                        "provider_code": "openrouter",
                        "api_key": "secret",
                        "default_model": "deepseek/deepseek-v4-flash",
                    }
                },
            ),
        ), patch(
            "AI.views.chat_tab.build_provider_chat_client",
            return_value=planner,
        ), patch(
            "AI.views.chat_tab.grounded_capability_overview"
        ) as capability_mock, patch(
            "AI.views.chat_tab.run_agent_task"
        ) as task_mock:
            result = _run_chat_turn_with_runtime(
                "İyiyim. Birazdan siparişlere bakacağız; ben API'den güncelleme istemediğim sürece hangi veriyi kullanacağını ve hangi durumda benden onay isteyeceğini kısaca anlat.",
                source="cloud",
                runtime_record={"id": 43},
                history=[],
            )

        self.assertTrue(result.success, result.message)
        capability_mock.assert_not_called()
        task_mock.assert_not_called()
        self.assertEqual(len(prompts), 3)
        self.assertIn("topic completeness audit", prompts[1])
        self.assertIn("TrustedPolicyContext", prompts[2])
        self.assertIn("orders.default_read_source", prompts[2])
        self.assertIn("runtime.effects_prepare_then_confirm", prompts[2])
        data = dict(result.data or {})
        self.assertEqual(
            data.get("decision_path"), "typed_model_policy_explanation"
        )
        self.assertTrue(data.get("policy_context_used"))
        self.assertEqual(data.get("direct_tool_calls") or [], [])
        answer = str(data.get("answer") or result.message)
        for token in ("yerel snapshot", "sessizce yenilemem", "onay", "read-back"):
            self.assertIn(token, answer)


if __name__ == "__main__":
    unittest.main()
