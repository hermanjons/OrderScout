from __future__ import annotations

import unittest

from AI.processors.agent import (
    _candidate_tools_for_message,
    _decision_prompt,
    _history_with_authoritative_state,
    choose_action,
)
from AI.processors.operation_catalog import (
    build_operation_catalog,
    operation_catalog_parity_report,
    planner_manual_operation_payload,
    retrieve_operation_candidates,
)
from AI.processors import task_runtime
from AI.processors.tools import available_tools
from AI.processors.session_state import AgentSessionState, SelectionSnapshot


class TestOperationCatalog(unittest.TestCase):
    def test_catalog_has_one_valid_metadata_contract_per_operation_name(self) -> None:
        tools = available_tools()
        catalog = build_operation_catalog(tools)

        self.assertGreaterEqual(len(catalog), len(tools))
        self.assertEqual(len(catalog), len(set(catalog)))
        for name, entry in catalog.items():
            self.assertEqual(entry.metadata.name, name)
            self.assertTrue(entry.metadata.owner_domain)
            self.assertTrue(entry.canonical_callable)
            self.assertEqual(entry.metadata.to_dict()["name"], name)

    def test_orders_aggregate_tools_bind_to_canonical_domain_functions(self) -> None:
        catalog = build_operation_catalog(available_tools(), include_manual=False)

        self.assertEqual(
            catalog["orders.item_sales_summary"].canonical_callable,
            "Orders.processors.agentic_repository.summarize_order_item_sales",
        )
        self.assertEqual(
            catalog["returns.selected_reason_summary"].canonical_callable,
            "Orders.processors.agentic_repository.summarize_return_reasons",
        )

    def test_retrieval_finds_specific_orders_aggregates_without_generic_router(self) -> None:
        catalog = build_operation_catalog(available_tools(), include_manual=False)

        sales = retrieve_operation_candidates(
            "Son uc haftanin en cok satan urunlerini adet ve ciroyla ozetle",
            catalog=catalog,
            domains={"orders"},
            limit=8,
        )
        reasons = retrieve_operation_candidates(
            "Secili iadelerin ortak nedenlerini dagilim olarak ver",
            catalog=catalog,
            domains={"orders"},
            limit=8,
        )

        self.assertIn("orders.item_sales_summary", [entry.name for entry in sales[:4]])
        self.assertIn("returns.selected_reason_summary", [entry.name for entry in reasons[:4]])

    def test_orders_planner_retrieval_exposes_atomic_sync_without_generic_router(self) -> None:
        candidates = task_runtime._planner_operation_candidates(
            "orders",
            "Guncel siparisleri API'den cek, yerel veritabanina kaydet ve senkronize et",
        )

        self.assertIn("orders.fetch.prepare", candidates)
        self.assertEqual(next(iter(candidates)), "orders.fetch.prepare")
        self.assertNotIn("operations.manual_action.route", candidates)
        self.assertNotIn("operations.manual_action.prepare", candidates)

    def test_orders_planner_retrieval_exposes_exact_full_context(self) -> None:
        candidates = task_runtime._planner_operation_candidates(
            "orders",
            "99000000001 siparisinin urunlerini, detaylarini ve tam baglamini goster",
        )

        self.assertIn("orders.full_context", candidates)
        self.assertEqual(next(iter(candidates)), "orders.full_context")
        self.assertNotIn("operations.manual_action.route", candidates)

    def test_planner_candidate_surface_is_bounded_and_keeps_label_dependencies(self) -> None:
        candidates = _candidate_tools_for_message(
            "Bekleyen siparisleri TANEX 2610 etiket olarak yazdir",
            available_tools(),
            history=[],
        )

        self.assertLessEqual(len(candidates), 18)
        self.assertIn("labels.create_from_orders.prepare", candidates)
        self.assertTrue(
            {"orders.ready_to_ship", "orders.ready_to_ship_count"}.intersection(candidates)
        )
        self.assertNotIn("operations.manual_action.route", candidates)
        self.assertNotIn("operations.capability_match", candidates)

    def test_planner_receives_typed_manual_operation_instead_of_fuzzy_router(self) -> None:
        query = "Bekleyen siparisleri TANEX 2610 etiket olarak yazdir"
        candidates = _candidate_tools_for_message(query, available_tools(), history=[])
        payload = planner_manual_operation_payload(query, domains={"labels", "orders"})
        prompt = _decision_prompt(query, candidates, history=[])

        self.assertIn(
            "labels.action_create_labels_from_selected_orders",
            [row["operation_id"] for row in payload],
        )
        self.assertIn("labels.action_create_labels_from_selected_orders", prompt)
        self.assertNotIn('"name": "operations.manual_action.route"', prompt)

    def test_orders_parity_report_proves_canonical_domain_bindings(self) -> None:
        report = operation_catalog_parity_report(domain="orders")

        self.assertTrue(report["ready"])
        self.assertEqual(report["problem_count"], 0)
        self.assertGreater(report["manual_capability_count"], 0)
        self.assertGreater(report["agent_operation_count"], 0)
        self.assertIn(
            "orders.item_sales_summary",
            [
                row["operation_id"]
                for row in report["agent_operations"]
                if row["canonical_owner_status"] == "domain_or_core_callable"
            ],
        )
        self.assertEqual(report["problems"], [])
        raw_fetch = next(
            row
            for row in report["manual_capabilities"]
            if row["capability_id"] == "orders.fetch_orders_all"
        )
        self.assertEqual(
            raw_fetch["binding_status"],
            "superseded_by_typed_operation",
        )
        self.assertEqual(
            raw_fetch["superseded_by"],
            "orders.get_orders_from_companies",
        )

    def test_top_selling_products_route_to_item_aggregate_with_three_week_scope(self) -> None:
        result = choose_action(
            "Son 3 haftanin en cok satan urunlerini adet ve ciroyla ozetle",
            tools=available_tools(),
        )

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(decision.tool_name, "orders.item_sales_summary")
        self.assertEqual(decision.arguments.get("period"), "last_21_days")
        self.assertEqual(decision.arguments.get("group_by"), "product")

    def test_selected_return_reason_aggregate_uses_exact_typed_selection(self) -> None:
        state = AgentSessionState(goal="Analyze selected returns")
        state.add_selection_snapshot(
            SelectionSnapshot.from_return_claim_ids(
                ["CLAIM-A", "CLAIM-B"],
                source_tool="returns.query",
            )
        )
        message = "Secili iadelerin ortak nedenlerini dagilim olarak ver"
        history = _history_with_authoritative_state(
            [{"role": "user", "content": message}],
            state=state,
            user_message=message,
        )

        result = choose_action(message, tools=available_tools(), history=history)

        self.assertTrue(result.success, result.message)
        decision = (result.data or {}).get("decision")
        self.assertEqual(decision.tool_name, "returns.selected_reason_summary")
        self.assertEqual(decision.arguments.get("claim_ids"), ["CLAIM-A", "CLAIM-B"])


if __name__ == "__main__":
    unittest.main()
