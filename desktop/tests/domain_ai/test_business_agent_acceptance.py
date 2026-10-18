from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from AI.processors.business_agent_acceptance_cli import (
    LOCAL_EXPORT_ACTIONS, NetworkBoundary, ObservedCloudClient, SCENARIOS,
    canonical_execution_evidence,
    load_provider_readonly, local_export_approval_problems, retain_approved_export, secret_safe, validate_business_turn,
)
from AI.processors.business_acceptance_fixtures import seed_business_fixture
from AI.processors.business_acceptance_evidence import (
    completed_observation_receipts, fixture_windows, receipt_hash,
    validate_fixture_observations, validate_general_report_sources,
)
from tests.support.db_case import IsolatedDbTestCase


def _live_turn(*operations):
    return {"success": True, "answer": "Sentetik kayıtlar ve kapsam doğrulandı.",
            "tool_calls": [{"tool": operation} for operation in operations],
            "runtime": {"model_response_count": 2, "actual_model": "test/model",
                        "requested_model": "test/model", "fallback_used": False},
            "execute": {"success": None}, "raw_turn_data": {"state": {"status": "complete"}}}


def _completed_turn(results):
    steps = [{"step_id": "observed_" + str(index), "status": "completed", "verification_status": "observed",
              "tool_names": [result["tool"]], "result_data": {"tool_result": result}}
             for index, result in enumerate(results)]
    return {"raw_turn_data": {"state": {"completed_steps": steps}}}


class TestBusinessAcceptanceContracts(unittest.TestCase):
    def test_delivery_followups_cannot_pass_after_a_handled_failed_task(self):
        for scenario_id in ("attachment_followup", "general_report_followup", "workflow_report_followup", "report_followup"):
            with self.subTest(scenario_id=scenario_id):
                turn = _live_turn("files.read", "analysis.table")
                turn["raw_turn_data"]["state"]["status"] = "failed"
                turn["answer"] = "İşlem doğrulanamadı; durduruldu."
                self.assertIn("required_goal_not_complete:failed", validate_business_turn(
                    turn, SCENARIOS[scenario_id], model="test/model"))

    def test_required_goal_completion_rejects_partial_receipts_despite_successful_ui_answer(self):
        for status in ("failed", "paused", "running", "pending_approval", "cancelled", None):
            with self.subTest(status=status):
                turn = _live_turn("orders.summary", "stock.inventory_overview", "finance.cashflow_summary")
                turn["raw_turn_data"]["state"].update({"status": status, "goal_progress": {
                    "reason": "deferred_source_bound_calculation_missing"}})
                self.assertTrue(any(p.startswith("required_goal_not_complete:") for p in
                                    validate_business_turn(turn, SCENARIOS["business_research"], model="test/model")))
        turn["raw_turn_data"]["state"] = {"status": "complete", "remaining_steps": [{"step_id": "unfinished"}]}
        self.assertIn("completed_goal_has_unfinished_work", validate_business_turn(
            turn, SCENARIOS["business_research"], model="test/model"))

    def test_canonical_execution_resolves_real_shared_result_and_cannot_override_outer_failure(self):
        evidence = {"verify": {"verified": True, "verified_by": "xlsx_exact_snapshot_readback"}}
        turn = _live_turn()
        turn["execute"] = {"success": True, "message": "Completed", "data": {
            "state": {"status": "complete"}, "execute": evidence}}
        self.assertEqual(canonical_execution_evidence(turn), (True, evidence))
        self.assertEqual(validate_business_turn(turn, SCENARIOS["approve_report"], model="test/model"), [])
        turn["execute"]["success"] = False
        self.assertIn("approved_export_not_executed", validate_business_turn(
            turn, SCENARIOS["approve_report"], model="test/model"))
        # Arbitrary dictionaries with a `data` field are business payloads.
        turn["execute"] = {"success": True, "data": evidence, "business_record": 1}
        self.assertIn("independent_export_readback_missing", validate_business_turn(
            turn, SCENARIOS["approve_report"], model="test/model"))

    def test_cross_domain_research_cannot_pass_on_order_tool_count_alone(self):
        turn = _live_turn("orders.summary", "orders.item_sales_summary")
        problems = validate_business_turn(turn, SCENARIOS["business_research"], model="test/model")
        self.assertIn("missing_observation_domain:stock", problems)
        self.assertIn("missing_observation_domain:finance", problems)

    def test_counterfeit_live_evidence_and_fallback_are_rejected(self):
        turn = _live_turn("orders.summary", "stock.inventory_overview", "finance.cashflow_summary")
        turn["runtime"].update({"model_response_count": 0, "actual_model": "different/model", "fallback_used": True})
        problems = validate_business_turn(turn, SCENARIOS["business_research"], model="test/model")
        self.assertIn("live_model_response_missing", problems)
        self.assertIn("exact_model_identity_not_proven", problems)
        self.assertIn("model_fallback_used", problems)

    def test_prepare_needs_immutable_identity_and_has_no_approved_effect(self):
        turn = _live_turn("orders.item_sales_summary", "orders.item_sales_report_xlsx.prepare")
        turn["action_proposal"] = {"approval_required": True}
        turn["execute"]["success"] = True
        problems = validate_business_turn(turn, SCENARIOS["report_prepare"], model="test/model")
        self.assertIn("pending_immutable_action_missing", problems)
        self.assertIn("unexpected_execute_before_approval", problems)

    def test_execute_success_flag_alone_cannot_certify_export(self):
        turn = _live_turn()
        turn["execute"] = {"success": True, "data": {}}
        problems = validate_business_turn(turn, SCENARIOS["approve_report"], model="test/model")
        self.assertIn("independent_export_readback_missing", problems)

    def test_pending_state_read_requires_current_authority_without_requiring_a_new_provider_response(self):
        turn = _live_turn()
        turn["runtime"] = {"model_response_count": 0}
        problems = validate_business_turn(turn, SCENARIOS["pending_scope"], model="test/model")
        self.assertIn("pending_current_proposal_reference_missing", problems)
        self.assertNotIn("live_model_response_missing", problems)

    def test_local_export_guard_rejects_other_action_and_path_escape(self):
        with tempfile.TemporaryDirectory() as isolated:
            allowed = {"action_type": next(iter(LOCAL_EXPORT_ACTIONS)), "external_write": False,
                       "arguments": {"payload": {"output_path": str(Path(isolated) / "report.xlsx")}}}
            self.assertEqual(local_export_approval_problems(allowed, isolated), [])
            outside = {**allowed, "arguments": {"payload": {"output_path": str(Path(isolated).parent / "outside.xlsx")}}}
            self.assertIn("approval_output_outside_isolation", local_export_approval_problems(outside, isolated))
            external = {**allowed, "action_type": "orders.change_order_cargo_provider", "external_write": True}
            problems = local_export_approval_problems(external, isolated)
            self.assertIn("approval_action_not_allowlisted_local_export", problems)
            self.assertIn("approval_has_external_or_destructive_effect", problems)

    def test_secret_scrub_applies_to_values_and_nested_credential_fields(self):
        payload = {"api_key": "provider-secret", "nested": [{"answer": "provider-secret appeared", "Authorization": "Bearer x"}],
                   "response": "fixture content"}
        cleaned = secret_safe(payload, ("provider-secret",))
        serialized = json.dumps(cleaned)
        self.assertNotIn("provider-secret", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertEqual(cleaned["response"], "fixture content")

    def test_network_boundary_allows_provider_but_blocks_marketplace_and_private_web(self):
        boundary = NetworkBoundary("https://openrouter.ai/api/v1", allow_public_web=True)
        boundary.check("POST", "https://openrouter.ai/api/v1/chat/completions", {"Authorization": "Bearer synthetic"})
        boundary.check("GET", "https://partner.trendyol.com/help")
        for method, url, headers in (
            ("POST", "https://partner.trendyol.com/update", {}),
            ("GET", "https://stageapigw.trendyol.com/suppliers/2738/orders", {}),
            ("GET", "https://192.168.1.1/private", {}),
            ("GET", "https://example.com/leak", {"Authorization": "Bearer synthetic"}),
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                boundary.check(method, url, headers)

    def test_model_response_observer_preserves_client_contract_and_never_records_prompt(self):
        rows = []

        class Client:
            model_name = "test/model"
            resource_plan = {"requested_model": "test/model", "actual_model": "test/model"}

            def __call__(self, prompt):
                return "Observed fixture answer."

            def invoke_structured(self, prompt, schema):
                self.resource_plan["last_invocation_contract"] = "goal_plan"
                return '{"steps":[{"operation":"orders.summary"}]}'

        client = Client()
        observed = ObservedCloudClient(client, rows.append)
        result = observed.invoke_structured("PRIVATE PROMPT NEVER RECORDED", schema={"type": "object"})
        self.assertEqual(result, '{"steps":[{"operation":"orders.summary"}]}')
        self.assertEqual(rows[0]["response"]["steps"][0]["operation"], "orders.summary")
        self.assertEqual(rows[0]["contract"], "goal_plan")
        self.assertNotIn("PRIVATE PROMPT", json.dumps(rows))
        observed.resource_plan = {"actual_model": "test/model", "marker": True}
        self.assertIs(observed.resource_plan, client.resource_plan)
        self.assertTrue(client.resource_plan["marker"])

    def test_approved_export_retention_keeps_readable_workbook_with_bound_identity(self):
        from Core.processors.report_artifacts import ReportColumn, ReportSheetSnapshot, ReportSnapshot, write_report_snapshot_xlsx
        with tempfile.TemporaryDirectory() as isolated:
            root = Path(isolated)
            source = root / "business" / "approved.xlsx"
            source.parent.mkdir()
            snapshot = ReportSnapshot.create(title="Stok", source_domain="stock", report_type="fixture",
                filters={}, metadata={}, sheets=[ReportSheetSnapshot("Stok", (
                    ReportColumn("currency", "Döviz"), ReportColumn("value", "Değer", "number")), (("TRY", 400), ("USD", 30), ("", None)))])
            verify = write_report_snapshot_xlsx(snapshot, source)
            action = {"action_id": "approved-current", "action_type": "ai.action_export_report_snapshot_xlsx",
                      "arguments": {"payload": {"output_path": str(source), "report_snapshot": snapshot.to_dict()}}}
            turn = {"scenario_id": "general_report_approve", "approved_action": action,
                    "execute": {"success": True, "message": "Saved", "data": {
                        "state": {"status": "complete"}, "execute": {"result": verify, "verify": verify}}}}
            retained = retain_approved_export(turn, isolation_root=root / "business", artifact_path=root / "evidence" / "live.json")
            self.assertTrue(Path(retained["artifact_path"]).is_file())
            self.assertEqual(retained["approved_action_id"], "approved-current")
            self.assertEqual(retained["sheets"][0]["rows"], [["Döviz", "Değer"], ["TRY", 400], ["USD", 30], [None, None]])
            self.assertEqual(retained["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(retained["approved_content_hash"], snapshot.content_hash)
            # A recorded success cannot authorize another snapshot or changed cells.
            changed = deepcopy(turn)
            changed["execute"]["data"]["execute"]["verify"]["content_hash"] = "different"
            with self.assertRaisesRegex(ValueError, "identity differs"):
                retain_approved_export(changed, isolation_root=root / "business", artifact_path=root / "bad.json")
            from openpyxl import load_workbook
            book = load_workbook(source)
            book["Stok"]["B2"] = 999
            book.save(source)
            book.close()
            turn["execute"]["data"]["execute"]["verify"]["file_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "cells differ"):
                retain_approved_export(turn, isolation_root=root / "business", artifact_path=root / "bad.json")

    def test_export_retention_rejects_output_different_from_approved_path(self):
        with tempfile.TemporaryDirectory() as isolated:
            source = Path(isolated) / "unexpected.xlsx"
            source.write_bytes(b"not read because the approval identity is wrong")
            turn = {"scenario_id": "approve", "approved_action": {
                "action_type": "ai.action_export_report_snapshot_xlsx",
                "arguments": {"payload": {"output_path": str(Path(isolated) / "approved.xlsx")}}},
                "execute": {"success": True, "data": {"verify": {"verified": True, "output_path": str(source)}}}}
            with self.assertRaisesRegex(ValueError, "differs from the approved"):
                retain_approved_export(turn, isolation_root=isolated, artifact_path=Path(isolated) / "live.json")

    def test_provider_loader_reads_only_provider_table_without_modifying_source_file(self):
        with tempfile.TemporaryDirectory() as isolated:
            path = Path(isolated) / "source.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE ai_provider_account (pk INTEGER PRIMARY KEY, provider_code TEXT, label TEXT, endpoint_url TEXT, api_key TEXT, default_model TEXT, is_enabled INTEGER)")
                db.execute("INSERT INTO ai_provider_account VALUES (1,'openrouter','Fixture provider',NULL,'synthetic-key-only','old/model',1)")
            db.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            provider = load_provider_readonly(path, 1, "test/model")
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(provider["default_model"], "test/model")
            self.assertFalse(provider["allow_model_fallback"])


class TestBusinessAcceptanceFixture(IsolatedDbTestCase):
    def _observed_fixture(self):
        from AI.processors import tools
        fixture = seed_business_fixture(self.db_path, isolation_root=self._tmp_dir.name)
        anchor = datetime.fromisoformat(fixture["as_of"]).date()
        results = []
        for start, end in ((anchor - timedelta(days=6), anchor),
                           (anchor - timedelta(days=13), anchor - timedelta(days=7))):
            result = tools.orders_summary(db_name=self.db_path, period="custom",
                                          start_date=start.isoformat(), end_date=end.isoformat(), api_account_ids=[101])
            self.assertTrue(result.success, result.message)
            results.append(result.data)
        results.extend([tools.stock_inventory_overview(db_name=self.db_path).data,
                        tools.finance_cashflow_summary(db_name=self.db_path, period="this_month").data])
        return fixture, _completed_turn(results)

    def test_business_oracle_requires_actual_both_scoped_periods_and_separate_currencies(self):
        fixture, turn = self._observed_fixture()
        evidence = validate_fixture_observations(turn, fixture)
        self.assertTrue(evidence["passed"], evidence)
        self.assertEqual(len(evidence["checks"]), 6)
        self.assertEqual(evidence["proof"]["recent"]["expected_count"], 3)
        self.assertEqual(evidence["proof"]["previous"]["expected_revenue_try"], 800)

    def test_equal_numbers_in_wrong_account_or_period_are_not_fixture_evidence(self):
        fixture, turn = self._observed_fixture()
        original = deepcopy(turn)
        for mutation in ("account", "period", "environment", "snapshot"):
            with self.subTest(mutation=mutation):
                turn = deepcopy(original)
                result = turn["raw_turn_data"]["state"]["completed_steps"][0]["result_data"]["tool_result"]
                if mutation == "account":
                    result["requested_api_account_ids"] = [102]
                elif mutation == "period":
                    result["start_ms"] += 86_400_000
                elif mutation == "environment":
                    result["account_scopes"][0]["environment"] = "production"
                else:
                    result.pop("source_snapshot_hash")
                evidence = validate_fixture_observations(turn, fixture)
                self.assertFalse(evidence["passed"])
                self.assertIn("fixture_observation_missing_or_mismatched:orders_recent_revenue_try", evidence["problems"])

    def test_failed_steps_or_plan_literals_cannot_supply_observation_numbers(self):
        fixture, turn = self._observed_fixture()
        step = turn["raw_turn_data"]["state"]["completed_steps"][0]
        step["arguments"] = deepcopy(step["result_data"]["tool_result"])
        step["status"] = "failed"
        turn["answer"] = "3000 TRY, 800 TRY, 3 ve 2 sipariş"
        evidence = validate_fixture_observations(turn, fixture)
        self.assertFalse(evidence["passed"])
        self.assertEqual(len(completed_observation_receipts(turn)), 3)

    def test_finance_and_stock_currency_labels_are_part_of_the_oracle(self):
        fixture, turn = self._observed_fixture()
        steps = turn["raw_turn_data"]["state"]["completed_steps"]
        steps[2]["result_data"]["tool_result"]["stock_value_by_currency"][0]["currency"] = "EUR"
        steps[3]["result_data"]["tool_result"]["combined_net"] = 220
        evidence = validate_fixture_observations(turn, fixture)
        self.assertFalse(evidence["checks"]["stock_separate_currency_values"])
        self.assertFalse(evidence["checks"]["finance_separate_currency_values"])

    def test_general_report_provenance_requires_exact_completed_sources(self):
        fixture, turn = self._observed_fixture()
        receipts = completed_observation_receipts(turn)
        sources = [{key: row[key] for key in ("source_step_id", "operation_id", "source_result_hash")} for row in receipts]
        snapshot = {"snapshot_id": "rpt_fixture", "content_hash": "fixture-hash", "source_domain": "reports",
                    "report_type": "reports.observations", "metadata": {"source_receipts": sources, "data_row_count": 4}}
        report_result = {"tool": "reports.build_snapshot", "report_snapshot": snapshot}
        report_step = _completed_turn([report_result])["raw_turn_data"]["state"]["completed_steps"][0]
        report_step["step_id"] = "built_report"
        turn["raw_turn_data"]["state"]["completed_steps"].append(report_step)
        self.assertTrue(validate_general_report_sources(turn)["passed"])
        turn["pending_action"] = {"arguments": {"payload": {"report_snapshot": deepcopy(snapshot)}}}
        turn["pending_action"]["arguments"]["payload"]["report_snapshot"]["content_hash"] = "different-built-report"
        self.assertIn("general_report_proposal_not_exact_built_snapshot", validate_general_report_sources(turn)["problems"])
        turn.pop("pending_action")
        sources[0]["source_result_hash"] = receipt_hash({"tool": "orders.summary", "model_invented_total": 3000})
        evidence = validate_general_report_sources(turn)
        self.assertFalse(evidence["passed"])
        self.assertIn("general_report_source_not_exact_completed_observation", evidence["problems"])

    def test_fixture_is_domain_readable_and_preserves_reference_values(self):
        from AI.processors import tools
        fixture = seed_business_fixture(self.db_path, isolation_root=self._tmp_dir.name)
        orders = tools.orders_summary(db_name=self.db_path, period="all", api_account_ids=[101])
        stock = tools.stock_inventory_overview(db_name=self.db_path)
        finance = tools.finance_cashflow_summary(db_name=self.db_path, period="all")
        self.assertTrue(orders.success, orders.message)
        self.assertTrue(stock.success, stock.message)
        self.assertTrue(finance.success, finance.message)
        self.assertEqual({row["currency"]: row["amount"] for row in stock.data["stock_value_by_currency"]},
                         fixture["stock"]["stock_value_by_currency"])
        self.assertEqual({row["currency"]: row["combined_net"] for row in finance.data["currency_totals"]},
                         fixture["finance"]["movement_net_by_currency"])
        self.assertIsNone(finance.data["combined_net"])

    def test_fixture_refuses_source_database_outside_isolation(self):
        with self.assertRaises(ValueError):
            seed_business_fixture(self.db_path, isolation_root=Path(self._tmp_dir.name) / "different-root")

    def test_fixture_refuses_overwriting_existing_business_records(self):
        seed_business_fixture(self.db_path, isolation_root=self._tmp_dir.name)
        with self.assertRaisesRegex(ValueError, "empty database"):
            seed_business_fixture(self.db_path, isolation_root=self._tmp_dir.name)


if __name__ == "__main__":
    unittest.main()
