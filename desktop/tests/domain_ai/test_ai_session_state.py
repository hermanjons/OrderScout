from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from AI.processors import agent as ai_agent
from AI.processors.tools import AgentTool
from Feedback.processors.pipeline import Result
from AI.processors.session_state import (
    ActiveScope,
    AgentSessionState,
    AgentTaskStep,
    AnalysisContext,
    GoalPlan,
    Observation,
    PendingActionSnapshot,
    RecordRef,
    SelectionSnapshot,
    referenced_action_id_from_text,
)


class AISelectionSnapshotTests(unittest.TestCase):
    def test_explicit_stale_action_reference_never_falls_through_to_active_action(self) -> None:
        active_id = "2b690dec6d4edbc98264ae27fb642da7"
        stale_id = "0a461f4c7c6adef0369cfa633fb955a7"

        self.assertEqual(
            referenced_action_id_from_text(
                f"eski action_id {stale_id} onayla",
                known_action_ids=(active_id, stale_id),
            ),
            stale_id,
        )
        self.assertEqual(
            referenced_action_id_from_text(
                f"action_id={active_id} çalıştır",
                known_action_ids=(active_id, stale_id),
            ),
            active_id,
        )
        self.assertEqual(
            referenced_action_id_from_text(
                "sipariş 99000000001 için onayla",
                known_action_ids=(active_id, stale_id),
            ),
            "",
        )

    def test_goal_plan_round_trip_preserves_graph_revision_and_active_identity(self) -> None:
        plan = GoalPlan.create(
            goal="Bekleyen siparisleri incele ve etiket hazirla",
            domain="orders",
            step_ids=["orders.ready_to_ship", "orders.labels.prepare"],
            prompts=["Bekleyenleri getir", "Etiket aksiyonunu hazirla"],
            source="llm",
            metadata={"reason": "typed plan"},
        )
        state = AgentSessionState(goal=plan.goal)
        state.add_goal_plan(plan)

        self.assertEqual(plan.steps[1].depends_on, ["orders.ready_to_ship"])
        self.assertEqual([step.step_id for step in plan.ready_steps()], ["orders.ready_to_ship"])
        plan.steps[0].status = "completed"
        self.assertEqual([step.step_id for step in plan.ready_steps()], ["orders.labels.prepare"])
        replacement = AgentTaskStep(
            index=3,
            step_id="orders.full_context",
            prompt="Secimi dogrula",
            objective="Secimi dogrula",
        )
        state.revise_goal_plan(
            [replacement],
            failed_step_id="orders.labels.prepare",
            reason="scope requires readback",
        )

        restored = AgentSessionState.from_dict(state.to_dict())
        restored_plan = restored.active_goal_plan()
        self.assertIsNotNone(restored_plan)
        self.assertEqual(restored.active_goal_plan_id, plan.plan_id)
        self.assertEqual(restored_plan.revision, 2)
        self.assertEqual(
            [step.step_id for step in restored_plan.steps],
            [
                "orders.ready_to_ship",
                "orders.labels.prepare",
                "orders.full_context",
            ],
        )
        self.assertEqual(
            (restored_plan.metadata.get("replans") or [])[0].get(
                "failed_step_id"
            ),
            "orders.labels.prepare",
        )

    def test_goal_plan_supports_explicit_fan_out_fan_in_and_cross_source_steps(self) -> None:
        specs = [
            {
                "id": "orders_read",
                "operation_id": "orders.item_sales_summary",
                "operation_domain": "orders",
                "depends_on": [],
            },
            {
                "id": "public_research",
                "operation_id": "web.search",
                "operation_domain": "web",
                "depends_on": [],
            },
            {
                "id": "report_join",
                "operation_id": "artifacts.xlsx.render",
                "operation_domain": "artifacts",
                "depends_on": ["orders_read", "public_research"],
            },
        ]
        plan = GoalPlan.create(
            goal="Satis ve web arastirmasini raporla",
            domain="orders",
            step_ids=[spec["id"] for spec in specs],
            prompts=["Orders oku", "Web arastir", "Raporla"],
            step_specs=specs,
            source="llm_direct",
        )

        self.assertEqual(
            [step.step_id for step in plan.ready_steps()],
            ["orders_read", "public_research"],
        )
        self.assertEqual(plan.steps[1].operation_domain, "web")
        plan.steps[0].status = "completed"
        self.assertEqual(
            [step.step_id for step in plan.ready_steps()],
            ["public_research"],
        )
        plan.steps[1].status = "completed"
        self.assertEqual(
            [step.step_id for step in plan.ready_steps()],
            ["report_join"],
        )

        restored = GoalPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.steps[1].operation_domain, "web")
        self.assertEqual(
            restored.steps[2].depends_on,
            ["orders_read", "public_research"],
        )

    def test_bulk_order_payload_uses_orders_as_targets_not_account_scope(self) -> None:
        action = {
            "action_type": "orders.change_orders_cargo_provider_bulk",
            "arguments": {
                "payload": {
                    "orders": ["ORDER-A", "ORDER-B"],
                    "order_refs": [
                        {"order_number": "ORDER-A", "api_account_id": 2},
                        {"order_number": "ORDER-B", "api_account_id": 2},
                    ],
                    "api_account_ids": [2],
                }
            },
            "rows": [
                {"order_number": "ORDER-A", "api_account_id": 2},
                {"order_number": "ORDER-B", "api_account_id": 2},
            ],
        }

        prepared = PendingActionSnapshot.from_action(action).to_action(action)

        self.assertEqual(prepared.get("selected_record_count"), 2)
        self.assertEqual(
            [row.get("record_id") for row in prepared.get("record_refs") or []],
            ["ORDER-A", "ORDER-B"],
        )
        self.assertEqual(
            {row.get("account") for row in prepared.get("record_refs") or []},
            {"2"},
        )

    def test_complete_selection_round_trip_preserves_typed_record_scope(self) -> None:
        snapshot = SelectionSnapshot.from_order_numbers(
            ["ORD-1", "ORD-2", "ORD-3"],
            source_tool="orders.ready_to_ship",
            period="all",
            account_by_order={"ORD-1": "7", "ORD-2": "7", "ORD-3": "7"},
            environment_by_account={"7": "production"},
            account_scopes=[
                {
                    "api_account_id": 7,
                    "store_name": "Store Seven",
                    "platform": "trendyol",
                    "environment": "production",
                }
            ],
        )

        restored = SelectionSnapshot.from_context(snapshot.to_context())
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertTrue(restored.is_complete)
        self.assertTrue(restored.is_authoritative_read)
        self.assertEqual(restored.selection_id, snapshot.selection_id)
        self.assertEqual(restored.record_ids, ("ORD-1", "ORD-2", "ORD-3"))
        self.assertEqual(
            restored.refs[0],
            RecordRef(
                domain="orders",
                record_type="order",
                record_id="ORD-1",
                source="local_db",
                account="7",
                environment="production",
            ),
        )

    def test_selection_snapshot_rejects_tampered_identity_and_incomplete_scope(self) -> None:
        snapshot = SelectionSnapshot.from_order_numbers(
            ["ORD-1", "ORD-2"],
            source_tool="orders.ready_to_ship",
            listed_count=2,
            total_count=2,
        )
        tampered = snapshot.to_context()
        tampered["order_numbers"] = ["ORD-1", "ORD-TAMPERED"]
        tampered["record_refs"] = []
        self.assertIsNone(SelectionSnapshot.from_context(tampered))

        truncated = SelectionSnapshot.from_order_numbers(
            ["ORD-1", "ORD-2"],
            source_tool="orders.ready_to_ship",
            listed_count=2,
            total_count=7,
            truncated=True,
        )
        self.assertFalse(truncated.is_complete)

    def test_prepare_snapshot_is_not_an_authoritative_read_selection(self) -> None:
        snapshot = SelectionSnapshot.from_order_numbers(
            ["ORD-STALE-1", "ORD-STALE-2"],
            source_tool="labels.create_from_orders.prepare",
        )
        self.assertTrue(snapshot.is_complete)
        self.assertFalse(snapshot.is_authoritative_read)

    def test_return_selection_round_trip_preserves_exact_claim_identity(self) -> None:
        snapshot = SelectionSnapshot.from_return_claim_ids(
            ["CLAIM-1", "CLAIM-2"],
            source_tool="returns.query",
            account_by_claim={"CLAIM-1": "7", "CLAIM-2": "7"},
            environment_by_account={"7": "stage"},
            order_by_claim={"CLAIM-1": "ORD-1", "CLAIM-2": "ORD-2"},
        )

        restored = SelectionSnapshot.from_context(snapshot.to_context())

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.record_type, "return_claim")
        self.assertEqual(restored.record_ids, ("CLAIM-1", "CLAIM-2"))
        self.assertEqual(restored.refs[0].account, "7")
        self.assertEqual(restored.refs[0].environment, "stage")
        self.assertEqual(restored.refs[0].identifiers["order_number"], "ORD-1")

    def test_agent_session_state_persists_selection_snapshots(self) -> None:
        snapshot = SelectionSnapshot.from_order_numbers(
            ["ORD-1", "ORD-2"],
            source_tool="orders.ready_to_ship",
            period="all",
        )
        state = AgentSessionState(
            goal="Prepare labels safely",
            selection_snapshots=[snapshot],
        )

        restored = AgentSessionState.from_dict(state.to_dict())
        self.assertEqual(len(restored.selection_snapshots), 1)
        self.assertEqual(restored.selection_snapshots[0].selection_id, snapshot.selection_id)
        self.assertEqual(restored.selection_snapshots[0].record_ids, ("ORD-1", "ORD-2"))

    def test_analysis_context_round_trip_rejects_tampered_facts(self) -> None:
        context = AnalysisContext.create(
            domain="orders",
            analysis_type="ready_queue",
            selection_id="selection-1",
            source_tools=("orders.ready_to_ship",),
            facts={"account_scope": [7]},
            aggregates={"count": 7},
        )
        restored = AnalysisContext.from_context(context.to_context())
        self.assertEqual(restored, context)

        tampered = context.to_context()
        tampered["aggregates"] = {"count": 4}
        self.assertIsNone(AnalysisContext.from_context(tampered))

    def test_pending_action_fingerprint_detects_record_scope_drift(self) -> None:
        action = {
            "action_type": "labels.create",
            "status": "pending_approval",
            "arguments": {"payload": {"order_numbers": ["A", "B", "C"]}},
            "rows": [
                {"order_number": "A"},
                {"order_number": "B"},
                {"order_number": "C"},
            ],
        }
        snapshot = PendingActionSnapshot.from_action(action)
        prepared = snapshot.to_action(action)
        self.assertEqual(snapshot.invariant_problems(prepared), [])

        prepared["arguments"]["payload"]["order_numbers"] = ["A", "B"]
        restored = PendingActionSnapshot.from_action(prepared)
        self.assertEqual(
            restored.invariant_problems(prepared),
            [
                "prepare_fingerprint_mismatch",
                "prepare_payload_record_refs_mismatch",
            ],
        )

    def test_agent_session_state_canonicalizes_new_pending_action(self) -> None:
        state = AgentSessionState(goal="Prepare labels safely")
        action = state.add_pending_action(
            {
                "action_type": "labels.create",
                "arguments": {"payload": {"order_numbers": ["A", "B"]}},
                "rows": [{"order_number": "A"}, {"order_number": "B"}],
            }
        )

        self.assertEqual(action["selected_record_count"], 2)
        self.assertEqual(len(action["record_refs"]), 2)
        self.assertTrue(action["prepare_fingerprint"])
        self.assertEqual(state.active_pending_action_id, action["action_id"])

    def test_new_prepare_supersedes_previous_pending_action_by_identity(self) -> None:
        state = AgentSessionState(goal="Prepare only the current order selection")
        old_action = state.add_pending_action(
            {
                "action_type": "labels.create",
                "arguments": {"payload": {"order_numbers": ["OLD-1"]}},
                "rows": [{"order_number": "OLD-1"}],
            }
        )
        new_action = state.add_pending_action(
            {
                "action_type": "labels.create",
                "arguments": {"payload": {"order_numbers": ["NEW-1", "NEW-2"]}},
                "rows": [
                    {"order_number": "NEW-1"},
                    {"order_number": "NEW-2"},
                ],
            }
        )

        self.assertEqual(len(state.pending_actions), 1)
        self.assertEqual(state.active_pending_action_id, new_action["action_id"])
        self.assertEqual(
            [ref["record_id"] for ref in state.pending_actions[0]["record_refs"]],
            ["NEW-1", "NEW-2"],
        )
        superseded = [
            event
            for event in state.state_events
            if event.entity_id == old_action["action_id"] and event.status == "superseded"
        ]
        self.assertEqual(len(superseded), 1)
        with self.assertRaisesRegex(ValueError, "stale"):
            state.resolve_pending_action(old_action["action_id"], status="approved")

    def test_template_correction_rotates_action_identity_on_same_exact_selection(self) -> None:
        state = AgentSessionState(goal="Correct the label template without changing orders")

        def proposal(model_code: str) -> dict[str, Any]:
            return {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "selection_id": "selection-same-12",
                "risk_level": "medium",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {
                    "payload": {
                        "order_numbers": ["ORDER-A", "ORDER-B"],
                        "brand_code": "TANEX",
                        "model_code": model_code,
                    },
                    "source_snapshot_hash": "snapshot-same-12",
                },
                "rows": [
                    {"operation": "create_label", "order_number": "ORDER-A"},
                    {"operation": "create_label", "order_number": "ORDER-B"},
                ],
            }

        old_action = state.add_pending_action(proposal("TANEX_2736"))
        replacement = state.add_pending_action(proposal("TANEX_2610"))

        self.assertNotEqual(old_action["action_id"], replacement["action_id"])
        self.assertNotEqual(
            old_action["prepare_fingerprint"],
            replacement["prepare_fingerprint"],
        )
        self.assertEqual(state.active_pending_action_id, replacement["action_id"])
        supersede_events = [
            event
            for event in state.state_events
            if event.entity_id == old_action["action_id"]
            and event.status == "superseded"
        ]
        self.assertEqual(len(supersede_events), 1)
        self.assertEqual(
            supersede_events[0].payload.get("replacement_action_id"),
            replacement["action_id"],
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            state.resolve_pending_action(old_action["action_id"], status="approved")

    def test_pending_action_inspection_reads_only_exact_active_typed_target(self) -> None:
        state = AgentSessionState(goal="Inspect the exact pending label proposal")
        old_action = state.add_pending_action(
            {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "risk_level": "medium",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {"payload": {"order_numbers": ["OLD-ORDER"]}},
                "rows": [{"order_number": "OLD-ORDER"}],
            }
        )
        active_action = state.add_pending_action(
            {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "risk_level": "medium",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {"payload": {"order_numbers": ["READY-A", "READY-B"]}},
                "rows": [
                    {"order_number": "READY-A"},
                    {"order_number": "READY-B"},
                ],
            }
        )

        result = ai_agent.run_agent_turn(
            "Onay bekleyen işlem tam olarak neyi değiştirecek? Çalıştırma.",
            planner_client=lambda _prompt: (_ for _ in ()).throw(
                AssertionError("Typed pending inspection must not call a model.")
            ),
            chat_client=lambda _prompt: (_ for _ in ()).throw(
                AssertionError("Typed pending inspection must not call a model.")
            ),
            session_state=state,
        )

        self.assertTrue(result.success, result.message)
        data = result.data or {}
        self.assertEqual(data.get("tool_calls"), [])
        answer = str(data.get("answer") or "")
        self.assertIn(active_action["action_id"], answer)
        self.assertIn("READY-A", answer)
        self.assertIn("READY-B", answer)
        self.assertNotIn("OLD-ORDER", answer)
        self.assertNotIn(old_action["action_id"], answer)

    def test_pending_action_scope_revision_supersedes_old_exact_identity(self) -> None:
        state = AgentSessionState(goal="Narrow the prepared label set")
        old_action = state.add_pending_action(
            {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "arguments": {
                    "payload": {"order_numbers": ["ORDER-A", "ORDER-B", "ORDER-C"]},
                    "account_by_order": {
                        "ORDER-A": "7",
                        "ORDER-B": "7",
                        "ORDER-C": "7",
                    },
                },
                "rows": [
                    {"order_number": "ORDER-A", "api_account_id": 7},
                    {"order_number": "ORDER-B", "api_account_id": 7},
                    {"order_number": "ORDER-C", "api_account_id": 7},
                ],
            }
        )

        revised = state.revise_pending_action_scope(
            old_action["action_id"],
            ["ORDER-B", "ORDER-C"],
        )

        self.assertNotEqual(revised["action_id"], old_action["action_id"])
        self.assertEqual(state.active_pending_action_id, revised["action_id"])
        self.assertEqual(
            ((revised.get("arguments") or {}).get("payload") or {}).get("order_numbers"),
            ["ORDER-B", "ORDER-C"],
        )
        self.assertEqual(
            [row.get("record_id") for row in revised.get("record_refs") or []],
            ["ORDER-B", "ORDER-C"],
        )
        self.assertEqual(revised.get("selected_record_count"), 2)
        with self.assertRaisesRegex(ValueError, "stale"):
            state.revise_pending_action_scope(old_action["action_id"], ["ORDER-A"])
        with self.assertRaisesRegex(ValueError, "outside"):
            state.revise_pending_action_scope(revised["action_id"], ["ORDER-X"])

    def test_natural_reprepare_supersedes_typed_pending_action_before_approval(self) -> None:
        state = AgentSessionState(goal="Correct the pending label target")
        old_action = state.add_pending_action(
            {
                "action_type": "labels.action_create_labels_from_selected_orders",
                "approval_required": True,
                "execute_enabled": True,
                "arguments": {"payload": {"order_numbers": ["ORD-A", "ORD-B"]}},
                "rows": [
                    {"order_number": "ORD-A"},
                    {"order_number": "ORD-B"},
                ],
            }
        )

        def prepare_labels(*, db_name: str, order_numbers=None, **_kwargs):
            selected = list(order_numbers or [])
            return Result.ok(
                "Corrected label proposal prepared.",
                close_dialog=False,
                data={
                    "approval_required": True,
                    "action": {
                        "action_type": "labels.action_create_labels_from_selected_orders",
                        "approval_required": True,
                        "execute_enabled": True,
                        "arguments": {"payload": {"order_numbers": selected}},
                        "rows": [
                            {"order_number": order_number}
                            for order_number in selected
                        ],
                    },
                },
            )

        registry = {
            "labels.create_from_orders.prepare": AgentTool(
                name="labels.create_from_orders.prepare",
                description="Prepare labels for exact order numbers.",
                parameters={
                    "type": "object",
                    "properties": {
                        "order_numbers": {"type": "array", "items": {"type": "string"}},
                        "brand_code": {"type": "string"},
                        "model_code": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=prepare_labels,
                domain="orders",
                requires_approval=True,
                action_type="prepare_write",
            )
        }
        with patch.object(ai_agent, "available_tools", return_value=registry):
            result = ai_agent.run_agent_turn(
                "Hayir, yalniz ORD-B siparisini etiket olarak yazdir.",
                session_state=state,
            )

        self.assertTrue(result.success, result.message)
        restored = AgentSessionState.from_dict((result.data or {}).get("session_state") or {})
        active = restored.active_pending_action()
        self.assertIsNotNone(active)
        assert active is not None
        self.assertNotEqual(active.get("action_id"), old_action.get("action_id"))
        self.assertEqual(
            ((active.get("arguments") or {}).get("payload") or {}).get("order_numbers"),
            ["ORD-B"],
        )
        self.assertTrue(
            any(
                event.entity_id == old_action["action_id"]
                and event.status == "superseded"
                for event in restored.state_events
            )
        )

    def test_active_selection_is_domain_scoped_and_latest_is_authoritative(self) -> None:
        old_orders = SelectionSnapshot.from_order_numbers(
            ["OLD-ORDER"],
            source_tool="orders.ready_to_ship",
        )
        current_orders = SelectionSnapshot.from_order_numbers(
            ["CURRENT-1", "CURRENT-2"],
            source_tool="orders.ready_to_ship",
        )
        state = AgentSessionState(goal="Use current orders only")
        state.add_selection_snapshot(old_orders)
        state.add_selection_snapshot(current_orders)

        active = state.active_selection("orders")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.selection_id, current_orders.selection_id)
        self.assertEqual(active.record_ids, ("CURRENT-1", "CURRENT-2"))
        self.assertEqual(
            state.state_events[-1].payload.get("superseded_selection_id"),
            old_orders.selection_id,
        )

    def test_secondary_aggregate_sample_cannot_reorder_visible_list_in_same_plan(self) -> None:
        state = AgentSessionState(
            goal="Final olmayan siparisleri listele ve durum dagilimini dogrula",
            active_domain="orders",
        )
        state.add_goal_plan(
            GoalPlan.create(
                goal=state.goal,
                domain="orders",
                step_ids=["list_rows", "status_summary"],
                prompts=[state.goal, state.goal],
                step_specs=[
                    {
                        "operation_id": "orders.query",
                        "arguments": {},
                        "depends_on": [],
                    },
                    {
                        "operation_id": "orders.nonfinal_summary",
                        "arguments": {},
                        "depends_on": ["list_rows"],
                    },
                ],
                source="llm_direct",
            )
        )
        visible = SelectionSnapshot.from_order_numbers(
            ["ORD-2", "ORD-3", "ORD-1"],
            source_tool="orders.query",
            listed_count=3,
            total_count=3,
        )
        aggregate_sample = SelectionSnapshot.from_order_numbers(
            ["ORD-1", "ORD-2", "ORD-3"],
            source_tool="orders.nonfinal_summary",
            listed_count=3,
            total_count=3,
        )

        state.ingest_tool_observation(
            context=visible.to_context(),
            operation_name="orders.query",
            success=True,
        )
        state.ingest_tool_observation(
            context=aggregate_sample.to_context(),
            operation_name="orders.nonfinal_summary",
            success=True,
        )

        active = state.active_selection("orders")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.selection_id, visible.selection_id)
        self.assertEqual(active.record_ids, ("ORD-2", "ORD-3", "ORD-1"))
        self.assertTrue(
            any(
                row.selection_id == aggregate_sample.selection_id
                for row in state.selection_snapshots
            )
        )
        self.assertEqual(
            state.state_events[-2].status,
            "recorded",
        )

    def test_truncated_identifier_sample_cannot_supersede_complete_population(self) -> None:
        state = AgentSessionState(
            goal="Final olmayan siparisleri ozetle ve kimlik ornegi al",
            active_domain="orders",
        )
        state.add_goal_plan(
            GoalPlan.create(
                goal=state.goal,
                domain="orders",
                step_ids=["summary", "identifier_sample"],
                prompts=[state.goal, state.goal],
                step_specs=[
                    {
                        "operation_id": "orders.nonfinal_summary",
                        "arguments": {},
                        "depends_on": [],
                    },
                    {
                        "operation_id": "orders.nonfinal_order_numbers",
                        "arguments": {"limit": 50},
                        "depends_on": ["summary"],
                    },
                ],
                source="llm_direct",
            )
        )
        complete_population = SelectionSnapshot.from_order_numbers(
            [f"ORD-{index}" for index in range(1, 8)],
            source_tool="orders.nonfinal_summary",
            listed_count=7,
            total_count=7,
            truncated=False,
        )
        truncated_sample = SelectionSnapshot.from_order_numbers(
            [f"ORD-{index}" for index in range(1, 51)],
            source_tool="orders.nonfinal_order_numbers",
            listed_count=50,
            total_count=162,
            truncated=True,
        )

        state.ingest_tool_observation(
            context=complete_population.to_context(),
            operation_name="orders.nonfinal_summary",
            success=True,
        )
        state.ingest_tool_observation(
            context=truncated_sample.to_context(),
            operation_name="orders.nonfinal_order_numbers",
            success=True,
        )

        active = state.active_selection("orders")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.selection_id, complete_population.selection_id)
        self.assertEqual(len(active.record_ids), 7)

    def test_typed_scope_observation_and_turn_survive_round_trip(self) -> None:
        state = AgentSessionState(goal="Inspect ready orders", active_domain="orders")
        scope = state.set_active_scope(
            ActiveScope.create(
                domain="orders",
                account_ids=[7],
                marketplaces=["Trendyol"],
                environments=["production"],
                filters={"status": "ready_to_ship"},
                source="orders.ready_to_ship",
            )
        )
        selection = state.add_selection_snapshot(
            SelectionSnapshot.from_order_numbers(
                ["ORD-7"],
                source_tool="orders.ready_to_ship",
                account_by_order={"ORD-7": "7"},
                environment_by_account={"7": "production"},
            )
        )
        state.record_turn(
            role="user",
            content="Bekleyen siparisleri yazdir.",
            mode="action_request",
            objective="print_ready_orders",
        )
        state.add_observation(
            Observation.create(
                domain="orders",
                operation_name="orders.ready_to_ship",
                success=True,
                scope_id=scope.scope_id,
                selection_id=selection.selection_id,
                refs=selection.refs,
                aggregates={"count": 1},
                source="local_db",
            )
        )

        restored = AgentSessionState.from_dict(state.to_dict())

        self.assertEqual(restored.active_scopes["orders"].scope_id, scope.scope_id)
        self.assertEqual(restored.active_selection("orders").record_ids, ("ORD-7",))
        self.assertEqual(restored.conversation_turns[0].mode, "action_request")
        self.assertEqual(restored.observations[0].aggregates, {"count": 1})
        self.assertEqual(
            [event.event_type for event in restored.state_events],
            ["active_scope", "selection_snapshot", "conversation_turn", "observation"],
        )

    def test_authoritative_state_projection_ignores_stale_raw_history_selection(self) -> None:
        stale = SelectionSnapshot.from_order_numbers(
            ["DELIVERED-OLD"],
            source_tool="orders.lookup",
        )
        current = SelectionSnapshot.from_order_numbers(
            ["READY-1", "READY-2"],
            source_tool="orders.ready_to_ship",
        )
        state = AgentSessionState(goal="Print the current ready queue")
        state.add_selection_snapshot(current)
        message = "bunlari etiket olarak yazdir 2610"
        projected = ai_agent._history_with_authoritative_state(
            [
                {
                    "role": "assistant",
                    "content": "stale delivered order",
                    "context": stale.to_context(),
                },
                {"role": "user", "content": message},
            ],
            state=state,
            user_message=message,
        )

        decision_result = ai_agent.choose_action(message, history=projected)

        self.assertTrue(decision_result.success, decision_result.message)
        decision = (decision_result.data or {}).get("decision")
        self.assertEqual(decision.tool_name, "labels.create_from_orders.prepare")
        self.assertEqual(decision.arguments.get("order_numbers"), ["READY-1", "READY-2"])
        self.assertNotIn("DELIVERED-OLD", str(projected))

    def test_return_approval_uses_claim_as_primary_typed_record(self) -> None:
        snapshot = PendingActionSnapshot.from_action(
            {
                "action_type": "orders.approve_return_claim",
                "arguments": {
                    "account_by_claim": {"CLAIM-1": "2738"},
                    "environment_by_account": {"2738": "stage"},
                    "payload": {"order": "CLAIM-1"},
                },
                "rows": [
                    {
                        "claim_id": "CLAIM-1",
                        "order_number": "ORDER-1",
                    }
                ],
            }
        )

        self.assertEqual(len(snapshot.refs), 1)
        ref = snapshot.refs[0]
        self.assertEqual(ref.domain, "orders")
        self.assertEqual(ref.record_type, "return_claim")
        self.assertEqual(ref.record_id, "CLAIM-1")
        self.assertEqual(ref.account, "2738")
        self.assertEqual(ref.environment, "stage")
        self.assertEqual(ref.identifiers.get("order_number"), "ORDER-1")

    def test_provider_fallback_metadata_cannot_mutate_selection_snapshot(self) -> None:
        snapshot = SelectionSnapshot.from_order_numbers(
            [f"ORD-FALLBACK-{index}" for index in range(7)],
            source_tool="orders.ready_to_ship",
            period="all",
        )
        state = AgentSessionState(
            goal="Prepare selected orders",
            selection_snapshots=[snapshot],
            active_entities={
                "runtime_context": {
                    "provider_code": "gemini",
                    "actual_model": "gemini-3.5-flash",
                }
            },
        )
        payload = state.to_dict()
        payload["active_entities"]["runtime_context"] = {
            "provider_code": "openrouter",
            "actual_model": "fallback/free-model",
            "fallback_from": "gemini-3.5-flash",
        }

        restored = AgentSessionState.from_dict(payload)

        self.assertEqual(restored.selection_snapshots[0].selection_id, snapshot.selection_id)
        self.assertEqual(restored.selection_snapshots[0].record_ids, snapshot.record_ids)


if __name__ == "__main__":
    unittest.main()
