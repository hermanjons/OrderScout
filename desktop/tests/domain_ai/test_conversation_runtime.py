from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from AI.processors import conversation_runtime
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.session_state import (
    AgentSessionState,
    AgentTaskStep,
    GoalPlan,
    PendingActionSnapshot,
)
from Feedback.processors.pipeline import Result


class _SequencedClient:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []
        self.model_name = "test-model"
        self.resource_plan = {
            "provider_code": "test",
            "requested_model": "test-model",
            "actual_model": "test-model",
            "fallback_used": False,
        }

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected provider call")
        return self.responses.pop(0)


class TestConversationRuntime(unittest.TestCase):
    def test_pending_state_read_bypasses_provider_and_preserves_action(self) -> None:
        raw_action = {
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "arguments": {
                "payload": {
                    "order_numbers": ["1001", "1002"],
                    "model_code": "TANEX_2610",
                }
            },
            "safe_payload": {
                "order_numbers": ["1001", "1002"],
                "model_code": "TANEX_2610",
            },
            "rows": [
                {"order_number": "1001"},
                {"order_number": "1002"},
            ],
        }
        pending = PendingActionSnapshot.from_action(raw_action).to_action(
            raw_action
        )
        state = AgentSessionState(
            goal="Bekleyen siparis etiketlerini hazirla",
            active_domain="orders",
            status="pending_approval",
            pending_actions=[pending],
            active_pending_action_id=pending["action_id"],
        )
        client = _SequencedClient()
        history: list[dict[str, object]] = []

        turn = run_contextual_conversation_turn(
            "Hangi siparişler, şablon ne ve dosya üretildi mi?",
            client=client,
            provider_code="gemini",
            model_name="test-model",
            db_name="ignored.sqlite3",
            history=history,
            session_state=state,
        )

        self.assertTrue(turn.get("success"), turn)
        self.assertEqual(client.calls, [])
        self.assertFalse(turn.get("model_invoked"))
        self.assertFalse(turn.get("interpretation_model_invoked"))
        self.assertEqual(turn.get("tools"), [])
        self.assertEqual(
            (turn.get("runtime_plan") or {}).get("actual_model"),
            "",
        )
        self.assertEqual(
            turn.get("decision_path"),
            "pending_action_scope_read_guard",
        )
        self.assertIn("1001", str(turn.get("answer")))
        self.assertIn("1002", str(turn.get("answer")))
        self.assertIn("TANEX 2610", str(turn.get("answer")))
        self.assertIn("dosya üretilmedi", str(turn.get("answer")))
        self.assertIn("yapılmaz", str(turn.get("answer")))
        next_state = dict(turn.get("session_state") or {})
        self.assertEqual(
            next_state.get("active_pending_action_id"),
            pending["action_id"],
        )
        self.assertEqual(next_state.get("status"), "pending_approval")

    def test_rejected_final_response_verification_fails_application_turn(self) -> None:
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "inspect",
                    "domain": "orders",
                    "objective": "Onay bekleyen iade sayisini getir",
                    "intent_kind": "data_read",
                    "requested_fields": ["count", "scope"],
                    "reason": "Authoritative read",
                    "requires_clarification": False,
                    "clarification": "",
                }
            )
        )
        rejected_state = AgentSessionState(
            goal="Onay bekleyen iade sayisini getir",
            active_domain="orders",
            status="complete",
            active_entities={
                "response_verifications": [
                    {
                        "source": "final_response",
                        "allowed": False,
                        "reason_codes": ["scope_evidence_missing"],
                    }
                ]
            },
        )
        with patch.object(
            conversation_runtime,
            "run_agent_task",
            return_value=Result.ok(
                "0 iade var; kapsam bulunamadi.",
                close_dialog=False,
                data={
                    "answer": "0 iade var; kapsam bulunamadi.",
                    "state": rejected_state.to_dict(),
                    "session_state": rejected_state.to_dict(),
                    "model_invoked": True,
                },
            ),
        ):
            turn = run_contextual_conversation_turn(
                "MDB production hesabinda onay bekleyen kac iade var?",
                client=client,
                provider_code="local-best",
                model_name="test-model",
                db_name="ignored.sqlite3",
                history=[],
            )

        self.assertFalse(turn.get("application_turn_success"), turn)
        self.assertFalse(turn.get("success"), turn)

    def test_local_business_projection_never_falls_through_to_nonbusiness_chat(
        self,
    ) -> None:
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "explain",
                    "domain": "orders",
                    "objective": "Ciro para birimi ve hesap kapsamini acikla",
                    "intent_kind": "conversation",
                    "request_shape": "scalar",
                    "requested_fields": ["amount", "store", "scope"],
                    "entity": "order",
                    "metric": "detail",
                    "status_scope": "all",
                    "record_scope": "all_matching",
                    "period": "all",
                    "freshness": "local_snapshot",
                    "information_source": "local_business_data",
                    "operation_policy": "allow_new_operations",
                    "reason": "Yerel siparis ozeti soruluyor",
                    "requires_clarification": False,
                    "clarification": "",
                }
            )
        )
        completed = AgentSessionState(
            goal="Ciro para birimi ve hesap kapsami",
            active_domain="orders",
            status="complete",
            active_entities={
                "response_verifications": [
                    {"source": "final_response", "allowed": True}
                ]
            },
            completed_steps=[
                AgentTaskStep(
                    index=1,
                    step_id="revenue_scope",
                    prompt="Ciro kapsamını getir",
                    status="completed",
                    tool_names=["orders.revenue_total"],
                    result_message="Ciro ve kapsam getirildi.",
                    result_data={
                        "tool_result": {
                            "estimated_revenue": 502518.01,
                            "currency": "TRY",
                            "account_scopes": [
                                {
                                    "store_name": "MDB",
                                    "platform": "TRENDYOL",
                                    "environment": "production",
                                }
                            ],
                        }
                    },
                )
            ],
        )

        with patch.object(
            conversation_runtime,
            "run_agent_task",
            return_value=Result.ok(
                "Tahmini ciro 502518.01 TRY; kapsam MDB / TRENDYOL / production.",
                close_dialog=False,
                data={
                    "answer": (
                        "Tahmini ciro 502518.01 TRY; kapsam MDB / "
                        "TRENDYOL / production."
                    ),
                    "decision_path": "agent_task_completed",
                    "state": completed.to_dict(),
                    "session_state": completed.to_dict(),
                    "model_invoked": True,
                },
            ),
        ) as task_call:
            turn = run_contextual_conversation_turn(
                "bu cironun birimini ve hesap kapsamini soyler misin?",
                client=client,
                provider_code="gemini",
                model_name="test-model",
                db_name="ignored.sqlite3",
                history=[
                    {
                        "role": "assistant",
                        "content": "Toplam ciro 502.518,01 birimdir.",
                    }
                ],
            )

        self.assertTrue(turn.get("success"), turn)
        task_call.assert_called_once()
        interpretation = dict(turn.get("turn_interpretation") or {})
        self.assertEqual(interpretation.get("mode"), "inspect")
        self.assertEqual(interpretation.get("intent_kind"), "data_read")
        self.assertIn(
            "currency", interpretation.get("requested_fields") or []
        )
        self.assertIn(
            "business_evidence_source_requires_inspect",
            interpretation.get("semantic_corrections") or [],
        )
        self.assertIn(
            "population_amount_detail_metric_to_amount",
            interpretation.get("semantic_corrections") or [],
        )
        self.assertEqual(
            (interpretation.get("semantic_contract") or {}).get("metric"),
            "amount",
        )
        self.assertEqual(turn.get("tools"), ["orders.revenue_total"])
        self.assertNotEqual(
            turn.get("decision_path"), "typed_model_non_business_turn"
        )

    def test_typed_cancel_clears_pending_action_without_replaying_prior_tool(self) -> None:
        raw_action = {
            "action_type": "labels.action_create_labels_from_selected_orders",
            "approval_required": True,
            "execute_enabled": True,
            "arguments": {"payload": {"order_numbers": ["1001"]}},
            "rows": [{"order_number": "1001"}],
        }
        pending = PendingActionSnapshot.from_action(raw_action).to_action(raw_action)
        prior_step = AgentTaskStep(
            index=1,
            prompt="Etiketleri hazırla",
            step_id="prepare-labels",
            status="completed",
            tool_names=["labels.create_from_orders.prepare"],
            result_message="Etiket hazırlığı onay bekliyor.",
            result_data={
                "tool_result": {
                    "tool": "labels.create_from_orders.prepare",
                    "message": "Etiket hazırlığı onay bekliyor.",
                    "data": {"pending_actions": [pending]},
                }
            },
        )
        state = AgentSessionState(
            goal="Sipariş etiketlerini hazırla",
            active_domain="orders",
            status="pending_approval",
            completed_steps=[prior_step],
            pending_actions=[pending],
            active_pending_action_id=pending["action_id"],
        )
        plan = GoalPlan.create(
            goal=state.goal,
            domain="orders",
            step_ids=["prepare-labels"],
            prompts=["Etiketleri hazırla"],
        )
        state.add_goal_plan(plan)
        state.set_goal_plan_status("pending_approval")

        turn = run_contextual_conversation_turn(
            "Vazgeç, bu işlemi iptal et.",
            client=_SequencedClient(),
            provider_code="local-best",
            model_name="test-model",
            db_name="ignored.sqlite3",
            history=[],
            session_state=state,
        )

        self.assertTrue(turn.get("success"), turn)
        self.assertTrue(turn.get("application_turn_success"), turn)
        self.assertEqual(turn.get("turn_interpretation", {}).get("mode"), "cancel")
        self.assertFalse(turn.get("interpretation_model_invoked"))
        self.assertFalse(turn.get("model_invoked"))
        self.assertEqual(turn.get("tools"), [])
        self.assertEqual(turn.get("tool_results"), [])
        next_state = dict(turn.get("session_state") or {})
        self.assertEqual(next_state.get("pending_actions"), [])
        self.assertEqual(next_state.get("active_pending_action_id"), "")
        self.assertEqual(next_state.get("status"), "cancelled")
        self.assertEqual(
            (next_state.get("goal_plans") or [])[0].get("status"),
            "cancelled",
        )
        self.assertEqual(
            (next_state.get("action_history") or [])[-1].get("phase"),
            "cancel",
        )
        self.assertEqual(
            (next_state.get("progress_events") or [])[-1].get("phase"),
            "cancelled",
        )
        self.assertEqual(
            next_state.get("active_domain"),
            "orders",
        )

    def test_existing_observation_explanation_never_enters_agent_task_runtime(
        self,
    ) -> None:
        state = AgentSessionState(
            goal="Bütün siparişleri analiz et",
            active_domain="orders",
            status="complete",
        )
        prior_contract = {
            "entity": "order",
            "metric": "count",
            "status_scope": "all",
            "record_scope": "all_matching",
            "period": "all",
            "projection": ["count", "status", "amount", "item_sales_rows"],
            "metric_requirements": [
                "orders.total_count",
                "orders.status_distribution",
                "orders.revenue_total",
                "orders.item_sales_summary",
            ],
        }
        state.record_turn(
            role="user",
            content="Bütün siparişlerimi analiz et",
            mode="inspect",
            objective="Bütün siparişleri analiz et",
            intent_kind="data_read",
            requested_fields=["count", "status", "amount", "item_sales_rows"],
            semantic_contract=prior_contract,
        )
        state.record_turn(
            role="assistant",
            content="Toplam 3112 sipariş bütün dönemler kapsamında analiz edildi.",
            mode="complete",
            objective="Bütün siparişleri analiz et",
            tool_names=[
                "orders.count",
                "orders.status_counts",
                "orders.revenue_total",
                "orders.item_sales_summary",
            ],
        )
        state.completed_steps = [
            AgentTaskStep(
                index=1,
                prompt="Toplam sipariş sayısını getir",
                step_id="total",
                status="completed",
                tool_names=["orders.count"],
                result_message="3112 sipariş",
                result_data={
                    "tool_result": {
                        "count": 3112,
                        "period": "all",
                        "source_revision": "rev-1",
                        "source_snapshot_hash": "hash-1",
                        "account_scopes": [
                            {
                                "store_name": "MDB",
                                "platform": "TRENDYOL",
                                "environment": "production",
                                "api_account_id": 1,
                            }
                        ],
                    }
                },
            )
        ]
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "inspect",
                    "domain": "orders",
                    "objective": "Analizin kapsamını yeniden oku",
                    "intent_kind": "data_read",
                    "requested_fields": ["scope"],
                    "entity": "order",
                    "metric": "summary",
                    "status_scope": "all",
                    "record_scope": "all_matching",
                    "period": "all",
                    "freshness": "local_snapshot",
                    "information_source": "local_business_data",
                    "reason": "Kapsam kanıtı",
                    "requires_clarification": False,
                    "clarification": "",
                }
            ),
            (
                "Önceki typed kanıta göre analiz iki kayda değil, "
                "bütün dönemlerdeki siparişlere aittir."
            ),
        )
        history = [
            {"role": "user", "content": "Bütün siparişlerimi analiz et"},
            {
                "role": "assistant",
                "content": (
                    "Toplam 3112 sipariş bütün dönemler kapsamında analiz edildi."
                ),
            },
        ]

        with patch.object(
            conversation_runtime,
            "run_agent_task",
            side_effect=AssertionError("No-new-operation turn planned a tool"),
        ):
            turn = run_contextual_conversation_turn(
                (
                    "Bu analiz iki siparişe mi ait, bütün siparişlere mi? "
                    "Yeni veri işlemi çalıştırmadan önceki kanıttan açıkla."
                ),
                client=client,
                provider_code="gemini",
                model_name="test-model",
                db_name="ignored.sqlite3",
                history=history,
                session_state=state,
            )

        self.assertTrue(turn.get("success"), turn)
        self.assertEqual(turn.get("tools"), [])
        self.assertEqual(turn.get("tool_results"), [])
        self.assertEqual(
            (turn.get("turn_interpretation") or {}).get("operation_policy"),
            "existing_observations_only",
        )
        self.assertEqual(turn.get("decision_path"), "typed_model_non_business_turn")
        self.assertIn("bütün dönemlerdeki", str(turn.get("answer")))
        self.assertEqual(len(client.calls), 2)
        self.assertIn("OperationPolicy: existing_observations_only", client.calls[1])
        self.assertIn('"record_scope": "all_matching"', client.calls[1])
        self.assertIn('"store_name": "MDB"', client.calls[1])
        self.assertNotIn('"api_account_id": 1', client.calls[1])

    def test_existing_observation_ratio_uses_verified_projection_without_new_tool(
        self,
    ) -> None:
        state = AgentSessionState(
            goal="Sipariş özeti",
            active_domain="orders",
            status="complete",
            completed_steps=[
                AgentTaskStep(
                    index=1,
                    step_id="summary",
                    prompt="Sipariş özeti",
                    operation_domain="orders",
                    status="completed",
                    tool_names=["orders.summary"],
                    result_data={
                        "tool_result": {
                            "tool": "orders.summary",
                            "total_orders": 3112,
                            "status_counts": {
                                "Cancelled": 110,
                                "Delivered": 2957,
                                "UnDeliveredAndReturned": 44,
                                "UnDelivered": 1,
                            },
                        }
                    },
                )
            ],
        )
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "explain",
                    "domain": "orders",
                    "objective": "Önceki sayılardan teslim oranını hesapla",
                    "intent_kind": "conversation",
                    "request_shape": "focused_analysis",
                    "requested_fields": ["ratio", "count", "status"],
                    "entity": "order",
                    "metric": "ratio",
                    "status_scope": "delivered",
                    "record_scope": "all_matching",
                    "period": "all",
                    "freshness": "local_snapshot",
                    "information_source": "local_business_data",
                    "operation_policy": "existing_observations_only",
                    "reason": "Önceki observation hesabı",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            )
        )

        with patch.object(
            conversation_runtime,
            "run_agent_task",
            side_effect=AssertionError("No-new-query ratio planned a tool"),
        ):
            turn = run_contextual_conversation_turn(
                (
                    "Yeni sorgu çalıştırmadan, az önceki sayılara göre teslim "
                    "edilenlerin toplam içindeki payını hesapla; kullandığın "
                    "işlemi de göster."
                ),
                client=client,
                provider_code="gemini",
                model_name="test-model",
                db_name="ignored.sqlite3",
                history=[],
                session_state=state,
            )

        self.assertTrue(turn.get("success"), turn)
        self.assertEqual(turn.get("tools"), [])
        self.assertEqual(turn.get("tool_results"), [])
        self.assertEqual(len(client.calls), 1)
        self.assertIn("2957", str(turn.get("answer")))
        self.assertIn("3112", str(turn.get("answer")))
        self.assertIn("95.02", str(turn.get("answer")))
        self.assertNotIn("95.01", str(turn.get("answer")))
        self.assertEqual(
            turn.get("decision_path"),
            "typed_existing_observation_verified_projection",
        )

    def test_r349_external_refresh_prohibition_dispatches_requested_local_read(
        self,
    ) -> None:
        message = (
            "Tamam, dışarıdan veri çekmeden elindeki siparişlerin genel "
            "fotoğrafını çıkar: toplamı, durum dağılımını, toplam ciroyu "
            "ve sipariş başına ortalama ciroyu söyle."
        )
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "inspect",
                    "domain": "orders",
                    "objective": "Read the local Orders population summary.",
                    "intent_kind": "data_read",
                    "request_shape": "broad_analysis",
                    "requested_fields": [
                        "status",
                        "amount",
                        "calculation",
                        "currency",
                    ],
                    "direct_output_fields": ["status", "amount"],
                    "entity": "order",
                    "metric": "derived",
                    "status_scope": "all",
                    "record_scope": "all_matching",
                    "period": "all",
                    "freshness": "local_snapshot",
                    "information_source": "local_business_data",
                    "operation_policy": "allow_new_operations",
                    "calculation_grouping": "single_result",
                    "calculation_count": 1,
                    "derived_calculation": {
                        "operator": "divide",
                        "operands": [
                            {"ref": "orders.revenue_total"},
                            {"ref": "orders.total_count"},
                        ],
                        "result_kind": "amount_per_order",
                        "precision": 2,
                        "show_work": True,
                    },
                    "reason": "Use local Orders data without external refresh.",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            )
        )
        completed_state = AgentSessionState(
            goal=message,
            active_domain="orders",
            status="complete",
        ).to_dict()
        local_result = Result.ok(
            "Doğrulanmış lokal Orders özeti.",
            close_dialog=False,
            data={
                "mode": "answer",
                "answer": "Doğrulanmış lokal Orders özeti.",
                "state": completed_state,
                "session_state": completed_state,
            },
        )

        with patch.object(
            conversation_runtime,
            "run_existing_observation_read_turn",
            side_effect=AssertionError(
                "External refresh prohibition reused prior observations"
            ),
        ), patch.object(
            conversation_runtime,
            "run_agent_task",
            return_value=local_result,
        ) as task_call:
            turn = run_contextual_conversation_turn(
                message,
                client=client,
                provider_code="openrouter",
                model_name="deepseek/deepseek-v4-flash",
                db_name="ignored.sqlite3",
                history=[],
                session_state=AgentSessionState(
                    goal="Orders capability overview",
                    active_domain="orders",
                    status="complete",
                ),
            )

        self.assertTrue(turn.get("success"), turn)
        task_call.assert_called_once()
        interpretation = dict(turn.get("turn_interpretation") or {})
        self.assertEqual(
            interpretation.get("operation_policy"),
            "allow_new_operations",
        )
        self.assertNotIn(
            "action_intent",
            dict(interpretation.get("semantic_contract") or {}),
        )
        self.assertEqual(turn.get("answer"), "Doğrulanmış lokal Orders özeti.")

    def test_failed_agent_task_is_not_reported_as_successful_conversation_turn(self) -> None:
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "chat",
                    "domain": "orders",
                    "objective": "Onceki count hedefi",
                    "intent_kind": "data_read",
                    "requested_fields": ["count"],
                    "reason": "Stale yorum",
                    "requires_clarification": False,
                    "clarification": "",
                }
            )
        )
        failed_state = AgentSessionState(
            goal="Etiketleri hazirla",
            active_domain="orders",
            status="failed",
        )
        with patch.object(
            conversation_runtime,
            "run_agent_task",
            return_value=Result.ok(
                "Islem guvenli dogrulamayi gecmedi ve durduruldu.",
                close_dialog=False,
                data={
                    "answer": "Islem guvenli dogrulamayi gecmedi ve durduruldu.",
                    "state": failed_state.to_dict(),
                    "session_state": failed_state.to_dict(),
                    "model_invoked": True,
                },
            ),
        ):
            turn = run_contextual_conversation_turn(
                "Bunlari TANEX 2610 etiketine hazirla ama dosya uretme.",
                client=client,
                provider_code="local-best",
                model_name="test-model",
                db_name="ignored.sqlite3",
                history=[],
            )

        self.assertFalse(turn.get("success"), turn)
        self.assertFalse(turn.get("application_turn_success"), turn)
        self.assertEqual(turn.get("mode"), "")
        self.assertEqual(
            turn.get("turn_interpretation", {}).get("mode"),
            "act",
        )
    def test_typed_final_response_verification_overrules_literal_message_mismatch(self) -> None:
        verified_state = {
            "active_entities": {
                "response_verifications": [
                    {
                        "source": "model_candidate",
                        "allowed": True,
                    },
                    {
                        "source": "final_response",
                        "allowed": True,
                    },
                ]
            }
        }
        rejected_state = {
            "active_entities": {
                "response_verifications": [
                    {
                        "source": "final_response",
                        "allowed": False,
                    }
                ]
            }
        }

        self.assertTrue(
            conversation_runtime._final_response_semantically_verified(
                verified_state
            )
        )
        self.assertFalse(
            conversation_runtime._final_response_semantically_verified(
                rejected_state
            )
        )
        self.assertFalse(
            conversation_runtime._final_response_semantically_verified({})
        )
        tool_results = [
            {
                "tool": "orders.ready_to_ship_count",
                "message": "all doneminde kargoya hazir 18 siparis var.",
                "data": {
                    "count": 18,
                    "simulated_excluded": 5,
                },
            }
        ]
        answer = (
            "Kargoya hazir 18 siparis var. "
            "Kapsam: MDB (TRENDYOL / production)."
        )
        self.assertFalse(
            conversation_runtime._visible_answer_conflicts_with_authoritative_results(
                answer,
                tool_results,
                verified_state,
            )
        )
        self.assertTrue(
            conversation_runtime._visible_answer_conflicts_with_authoritative_results(
                answer,
                tool_results,
                {},
            )
        )

    def test_task_control_evidence_preserves_compact_plan_and_verifier_trace(self) -> None:
        evidence = conversation_runtime._task_control_evidence(
            {
                "status": "complete",
                "active_goal_plan_id": "plan-1",
                "goal_plans": [
                    {
                        "plan_id": "plan-1",
                        "status": "complete",
                        "source": "model",
                        "revision": 1,
                        "steps": [
                            {
                                "step_id": "s1",
                                "operation_candidates": [
                                    "orders.ready_to_ship_count"
                                ],
                                "status": "completed",
                                "verification_status": "verified",
                                "attempt_count": 1,
                                "result_data": {
                                    "orders": [
                                        {"order_number": "must-not-be-copied"}
                                    ]
                                },
                            }
                        ],
                    }
                ],
                "active_entities": {
                    "goal_evaluations": [
                        {
                            "step_id": "s1",
                            "decision": "continue",
                            "reason": "goal_evaluator_failed_existing_plan_continues",
                            "applied": False,
                        }
                    ],
                    "semantic_verifications": [
                        {"step_id": "s1", "status": "verified"}
                    ],
                    "response_verifications": [
                        {"field": "count", "status": "verified"}
                    ],
                },
                "progress_events": [
                    {"phase": "plan"},
                    {"phase": "act"},
                    {"phase": "verify"},
                ],
            }
        )

        self.assertEqual(evidence["task_status"], "complete")
        self.assertEqual(evidence["active_goal_plan_id"], "plan-1")
        step = evidence["goal_plans"][0]["steps"][0]
        self.assertEqual(step["operation_id"], "orders.ready_to_ship_count")
        self.assertEqual(step["verification_status"], "verified")
        self.assertNotIn("result_data", step)
        self.assertEqual(
            evidence["goal_evaluations"][0]["reason"],
            "goal_evaluator_failed_existing_plan_continues",
        )
        self.assertEqual(
            evidence["progress_phases"], ["plan", "act", "verify"]
        )

    def test_orders_capability_answer_is_grounded_and_never_claims_order_cancellation(self) -> None:
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "explain",
                    "domain": "orders",
                    "objective": "Orders yeteneklerini açıkla",
                    "intent_kind": "capability_overview",
                    "operation_policy": "existing_observations_only",
                    "requested_fields": [],
                    "reason": "Kullanıcı capability soruyor",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            )
        )
        history: list[dict[str, object]] = []

        turn = run_contextual_conversation_turn(
            "Sipariş tarafında neler yapabilirsin?",
            client=client,
            provider_code="openrouter",
            model_name="test-model",
            db_name="ignored.sqlite3",
            history=history,
        )

        self.assertTrue(turn.get("success"), turn)
        self.assertEqual(turn.get("tools"), ["operations.capability_catalog"])
        self.assertEqual(
            (turn.get("turn_interpretation") or {}).get("operation_policy"),
            "existing_observations_only",
        )
        answer = str(turn.get("answer"))
        self.assertIn("İptal edilmiş siparişleri", answer)
        self.assertNotIn("siparişleri iptal edebilirim", answer.casefold())
        self.assertIn("açıkça onaylamadan execute etmem", answer)
        self.assertEqual(len(client.calls), 1)

    def test_r368_explicit_no_operation_capability_request_stays_catalog_grounded(
        self,
    ) -> None:
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "explain",
                    "domain": "orders",
                    "objective": "Sipariş alanındaki yetenekleri sade anlat",
                    "intent_kind": "conversation",
                    "request_shape": "capability_overview",
                    "operation_policy": "existing_observations_only",
                    "requested_fields": [],
                    "reason": "Yalnız yetenek açıklaması isteniyor",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            )
        )

        turn = run_contextual_conversation_turn(
            "İşleme geçmeden sipariş alanında hangi tür işleri yapabildiğini "
            "sade biçimde anlat; yalnız yetenekleri açıkla, veri okuma veya "
            "aksiyon çalıştırma.",
            client=client,
            provider_code="openrouter",
            model_name="test-model",
            db_name="ignored.sqlite3",
            history=[],
        )

        self.assertTrue(turn.get("success"), turn)
        self.assertEqual(turn.get("tools"), ["operations.capability_catalog"])
        interpretation = dict(turn.get("turn_interpretation") or {})
        self.assertEqual(
            interpretation.get("intent_kind"),
            "capability_overview",
        )
        self.assertEqual(
            interpretation.get("operation_policy"),
            "existing_observations_only",
        )
        answer = str(turn.get("answer") or "")
        self.assertNotIn("sipariş oluşturma", answer.casefold())
        self.assertNotIn("ödeme doğrulama", answer.casefold())
        self.assertNotIn("fatura bilgilerini", answer.casefold())
        self.assertIn("Kargoya hazır siparişleri", answer)
        self.assertIn("açıkça onaylamadan execute etmem", answer)
        self.assertEqual(len(client.calls), 1)

    def test_chat_turn_uses_typed_interpretation_and_persists_visible_exchange(self) -> None:
        client = _SequencedClient(
            json.dumps(
                {
                    "mode": "chat",
                    "domain": "general",
                    "objective": "Kullanıcıyla gündelik sohbet et",
                    "requested_fields": [],
                    "reason": "E-ticaret işlemi istenmiyor",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            ),
            "İyiyim başkan, senden ne haber?",
        )
        history: list[dict[str, object]] = []

        turn = run_contextual_conversation_turn(
            "Nasılsın başkan?",
            client=client,
            provider_code="gemini",
            model_name="test-model",
            db_name="ignored.sqlite3",
            history=history,
        )

        self.assertTrue(turn.get("success"), turn)
        self.assertTrue(turn.get("application_turn_success"), turn)
        self.assertEqual(turn.get("tools"), [])
        self.assertFalse(turn.get("task_planner_model_invoked"))
        self.assertEqual(turn.get("history_message_count_after_turn"), 2)
        state = AgentSessionState.from_dict(dict(turn.get("session_state") or {}))
        self.assertEqual(
            [row.role for row in state.conversation_turns],
            ["user", "assistant"],
        )
        self.assertEqual(turn.get("runtime_plan", {}).get("actual_model"), "test-model")

    def test_invalid_typed_interpretation_fails_closed_without_legacy_router(self) -> None:
        client = _SequencedClient("not-json", "still-not-json")
        history: list[dict[str, object]] = []

        turn = run_contextual_conversation_turn(
            "Bunu yap işte",
            client=client,
            provider_code="openrouter",
            model_name="test-model",
            db_name="ignored.sqlite3",
            history=history,
        )

        self.assertFalse(turn.get("success"), turn)
        self.assertTrue(turn.get("application_turn_success"), turn)
        self.assertEqual(turn.get("tools"), [])
        self.assertEqual(turn.get("mode"), "clarification")
        self.assertIn("netleştir", str(turn.get("answer")))
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(
            client.calls[1].startswith("OrderScout typed turn contract repair"),
            client.calls[1],
        )
        self.assertNotIn("legacy", str(turn.get("decision_path") or "").casefold())


    def test_r334_policy_explanation_is_model_authored_from_canonical_policy_context(self) -> None:
        client = _SequencedClient(
            json.dumps(
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
                    "reason": "Kullanıcı runtime politikasını soruyor.",
                    "requires_clarification": False,
                    "clarification": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "explanation_topics": [
                        "data_source",
                        "approval",
                    ]
                },
                ensure_ascii=False,
            ),
            (
                "API senkronizasyonu istemezsen kalıcı yerel snapshot üzerinden okurum ve "
                "pazaryerini sessizce yenilemem. R0 salt okumalar onaysızdır; dosya, DB veya "
                "dış sistem etkisini önce hazırlar, açık onayından sonra çalıştırır ve read-back "
                "ile doğrularım."
            ),
        )
        history: list[dict[str, object]] = []

        turn = run_contextual_conversation_turn(
            "API'den güncelleme istemediğim sürece hangi veriyi kullanırsın ve hangi durumda onay istersin?",
            client=client,
            provider_code="openrouter",
            model_name="deepseek/deepseek-v4-flash",
            db_name="ignored.sqlite3",
            history=history,
        )

        self.assertTrue(turn.get("success"), turn)
        self.assertEqual(turn.get("tools"), [])
        self.assertEqual(
            turn.get("decision_path"), "typed_model_policy_explanation"
        )
        interpretation = dict(turn.get("turn_interpretation") or {})
        self.assertEqual(
            interpretation.get("intent_kind"), "policy_explanation"
        )
        self.assertEqual(
            interpretation.get("explanation_topics"),
            ["data_source", "approval"],
        )
        self.assertEqual(len(client.calls), 3)
        self.assertIn("topic completeness audit", client.calls[1])
        self.assertIn("canonical_runtime_policy", client.calls[2])
        self.assertIn("orders.no_implicit_marketplace_refresh", client.calls[2])
        self.assertIn("runtime.approval_is_not_execution", client.calls[2])
        answer = str(turn.get("answer") or "")
        for token in ("yerel snapshot", "sessizce yenilemem", "onay", "read-back"):
            self.assertIn(token, answer)


if __name__ == "__main__":
    unittest.main()
