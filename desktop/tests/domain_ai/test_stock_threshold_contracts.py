"""Real stock thresholds: shared manual writes, exact approval and readback."""
import json
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from sqlmodel import Session

from AI.processors import model_loop, operation_runtime, tools
from AI.runtime.stock_policy_contracts import stock_thresholds_prepare
from Core.utils.model_utils import get_engine
from Stock.models.models import StockItem
from Stock.processors import item_updates, pipeline
from Stock.views import actions
from tests.support.db_case import IsolatedDbTestCase


class Model:
    resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
    def __init__(self, responses):
        self.responses = iter(responses)
    def invoke_tools(self, prompt, *, tools):
        value = next(self.responses)
        return json.dumps(value) if isinstance(value, dict) else value


def call(name, **arguments):
    return {"mode": "tool", "tool": name, "arguments": arguments}


class TestStockThresholds(IsolatedDbTestCase):
    def setUp(self):
        super().setUp()
        with Session(get_engine(self.db_path)) as session:
            session.add_all([StockItem(pk=1, sku="KUPA-1", name="Kupa-demo", min_stock=25,
                max_stock=100, safety_stock=3, reorder_point=10, reorder_qty=5),
                StockItem(pk=2, sku="KUPA-2", name="Diğer Kupa-demo", min_stock=12)])
            session.commit()
        self.audit = str(Path(self._tmp_dir.name)/"audit.jsonl")

    def record(self, item_id=1):
        return item_updates.read_item_update_snapshot(item_id=item_id, db_name=self.db_path).data["record"]

    def prepared(self, updates):
        result = stock_thresholds_prepare(item_id=1, updates=updates, db_name=self.db_path)
        self.assertTrue(result.success, result.message)
        action = result.data["action"]
        # Direct executor tests still bind the trusted test database, as the
        # normal model loop does at its own approval boundary.
        action["arguments"]["payload"] = {"db_name": self.db_path}
        return action

    def test_preview_keeps_zero_null_fraction_and_unmodified_fields_without_write(self):
        original = self.record()
        action = self.prepared({"min_stock": 0, "safety_stock": None, "reorder_qty": .125})
        preview = stock_thresholds_prepare(item_id=1, updates={"min_stock": 0}, db_name=self.db_path)
        self.assertFalse(preview.data["zero_minimum_disables_all_alerts"])
        row = action["rows"][0]
        self.assertEqual(row["before"], original)
        self.assertEqual(row["changes"]["min_stock"], {"before": 25, "after": 0})
        self.assertIsNone(row["after"]["safety_stock"])
        self.assertEqual(row["after"]["reorder_qty"], .125)
        self.assertEqual(row["after"]["max_stock"], 100)
        self.assertEqual(self.record(), original)
        self.assertTrue(action["execute_enabled"])

    def test_execute_uses_shared_manual_primitive_and_verifies_actual_policy_fields(self):
        action = self.prepared({"min_stock": 0, "safety_stock": None, "reorder_qty": .125})
        with patch.object(pipeline, "update_item", wraps=pipeline.update_item) as shared:
            result = operation_runtime.execute_stock_item_update(action, audit_path=self.audit)
        self.assertTrue(result.success, result.message)
        self.assertEqual(shared.call_count, 1)
        self.assertIn("expected_values", shared.call_args.kwargs)
        record = result.data["verify"]["records"][0]
        self.assertEqual(record["min_stock"], 0)
        self.assertIsNone(record["safety_stock"])
        self.assertEqual(record["reorder_qty"], .125)
        self.assertEqual(self.record(2)["min_stock"], 12)
        visible = tools.stock_search(query="KUPA-1", db_name=self.db_path).data["items"][0]
        self.assertEqual(visible["reorder_qty"], .125)
        self.assertIsNone(visible["safety_stock"])
        self.assertEqual(visible["max_stock"], 100)
        with pipeline.database_scope(self.db_path):
            manual = actions.action_update_item(1, {"min_stock": .03125})
        self.assertTrue(manual.success, manual.message)
        self.assertEqual(tools.stock_search(query="KUPA-1", db_name=self.db_path).data["items"][0]["min_stock"], .03125)

    def test_stale_approval_cannot_overwrite_an_intervening_manual_change(self):
        action = self.prepared({"min_stock": 5})
        with pipeline.database_scope(self.db_path):
            self.assertTrue(actions.action_update_item(1, {"min_stock": 30}).success)
        result = operation_runtime.execute_stock_item_update(action, audit_path=self.audit)
        self.assertFalse(result.success)
        self.assertEqual(result.data["reason"], "stock_item_changed_since_prepare")
        self.assertEqual(self.record()["min_stock"], 30)

    def test_compare_and_set_also_catches_a_change_after_the_initial_read(self):
        action = self.prepared({"min_stock": 5})
        actual_update = pipeline.update_records
        def racing_update(**kwargs):
            self.assertTrue(actual_update(model=StockItem, filters={"pk": 1}, update_data={"min_stock": 31}, db_name=self.db_path).success)
            return actual_update(**kwargs)
        with patch.object(pipeline, "update_records", side_effect=racing_update):
            result = operation_runtime.execute_stock_item_update(action, audit_path=self.audit)
        self.assertFalse(result.success)
        self.assertEqual(result.data["reason"], "stock_item_changed_since_prepare")
        self.assertEqual(self.record()["min_stock"], 31)

    def test_comparison_uses_raw_stored_identity_values_not_display_normalization(self):
        with Session(get_engine(self.db_path)) as session:
            item = session.get(StockItem, 1)
            item.name = "  Kupa-demo  "
            item.unit = "adet "
            session.add(item)
            session.commit()
        action = self.prepared({"min_stock": 5})
        self.assertEqual(action["rows"][0]["before"]["name"], "Kupa-demo")
        self.assertEqual(action["rows"][0]["expected_values"]["name"], "  Kupa-demo  ")
        result = operation_runtime.execute_stock_item_update(action, audit_path=self.audit)
        self.assertTrue(result.success, result.message)
        with Session(get_engine(self.db_path)) as session:
            record = session.get(StockItem, 1)
            self.assertEqual(record.name, "  Kupa-demo  ")
            self.assertEqual(record.unit, "adet ")
            self.assertEqual(record.min_stock, 5)

    def test_verify_cannot_accept_missing_policy_fields_or_an_empty_target_set(self):
        action = self.prepared({"min_stock": 5})
        incomplete = self.record()
        del incomplete["min_stock"]
        from Feedback.processors.pipeline import Result
        with patch.object(item_updates, "read_item_update_snapshot", return_value=Result.ok(data={"record": incomplete})):
            self.assertFalse(operation_runtime.verify_stock_item_update(action).success)
        self.assertFalse(operation_runtime.verify_stock_item_update({"rows": []}).success)

    def test_replaying_success_does_not_reapply_the_old_value(self):
        action = self.prepared({"min_stock": 5})
        first = operation_runtime.execute_stock_item_update(action, audit_path=self.audit, idempotency_key="threshold-test")
        self.assertTrue(first.success, first.message)
        with pipeline.database_scope(self.db_path):
            self.assertTrue(actions.action_update_item(1, {"min_stock": 30}).success)
        second = operation_runtime.execute_stock_item_update(action, audit_path=self.audit, idempotency_key="threshold-test")
        self.assertTrue(second.success and second.data["idempotent"])
        self.assertEqual(self.record()["min_stock"], 30)

    def test_invalid_policy_values_are_rejected_by_both_preview_and_manual_update(self):
        original = self.record()
        for value in (-1, float("nan"), float("inf"), True, "invalid", ""):
            with self.subTest(value=value):
                result = stock_thresholds_prepare(item_id=1, updates={"min_stock": value}, db_name=self.db_path)
                self.assertFalse(result.success)
                with pipeline.database_scope(self.db_path):
                    self.assertFalse(actions.action_update_item(1, {"min_stock": value}).success)
                self.assertEqual(self.record(), original)

    def test_schema_and_noop_do_not_clear_an_omitted_threshold_or_require_approval(self):
        tool = tools.registered_tools()["stock.thresholds.prepare"]
        validator = Draft202012Validator(tool.parameters)
        for updates in ({"min_stock": 0}, {"min_stock": None}, {"min_stock": .125}):
            self.assertFalse(list(validator.iter_errors({"item_id": 1, "updates": updates})))
        for updates in ({}, {"balance": 10}, {"min_stock": True}, {"min_stock": -1}):
            self.assertTrue(list(validator.iter_errors({"item_id": 1, "updates": updates})))
        result = stock_thresholds_prepare(item_id=1, updates={"min_stock": 25}, db_name=self.db_path)
        self.assertTrue(result.success)
        self.assertFalse(result.data["write_required"])
        self.assertNotIn("action", result.data)
        self.assertEqual(self.record()["safety_stock"], 3)

    def test_invalid_identities_never_select_a_different_card_by_integer_coercion(self):
        for identity in (0, -1, True, 1.5):
            with self.subTest(identity=identity):
                result = stock_thresholds_prepare(item_id=identity, updates={"min_stock": 5}, db_name=self.db_path)
                self.assertFalse(result.success)
                self.assertEqual(result.data["reason"], "invalid_stock_item_id")
        self.assertEqual(self.record()["min_stock"], 25)

    def test_model_can_finish_an_already_current_request_without_a_pending_approval(self):
        registry = tools.registered_tools()
        client = Model([call("stock.thresholds.prepare", item_id=1, updates={"min_stock": 25}),
            "Minimum stok zaten 25; yeni bir değişiklik veya onay gerekmiyor."])
        with patch.object(tools, "available_tools", return_value={"stock.thresholds.prepare": registry["stock.thresholds.prepare"]}):
            result = model_loop.run_model_loop("Minimum eşiği 25 yap", client=client, db_name=self.db_path)
        self.assertTrue(result.success, result.data)
        self.assertFalse(result.data["approval_required"])
        self.assertEqual(self.record()["min_stock"], 25)

    def test_model_read_prepare_approve_readback_and_consumed_approval_use_real_domain(self):
        registry = tools.registered_tools()
        client = Model([call("stock.search", query="KUPA-1"),
            call("stock.thresholds.prepare", item_id=1, updates={"min_stock": 0}),
            "Kupa-demo minimum stoğu 25'ten 0'a indirilmeye hazır; onayını bekliyorum.",
            "Minimum stok kaydedildi; doğrulanmış yeni değer 0."])
        with patch.object(tools, "available_tools", return_value={k: registry[k] for k in ("stock.search", "stock.thresholds.prepare")}):
            prepared = model_loop.run_model_loop("Kupa minimum stoğunu sıfır yap", client=client, db_name=self.db_path)
            self.assertTrue(prepared.success and prepared.data["approval_required"], prepared.data)
            self.assertEqual(self.record()["min_stock"], 25)
            approved = model_loop.resume_model_loop_approval(prepared.data["state"], planner_client=client,
                db_name=self.db_path, audit_path=self.audit)
        self.assertTrue(approved.success, approved.data)
        self.assertEqual(approved.data["execute"]["verify"]["records"][0]["min_stock"], 0)
        self.assertEqual(self.record()["min_stock"], 0)
        stale = model_loop.resume_model_loop_approval(approved.data["state"], planner_client=client, db_name=self.db_path)
        self.assertFalse(stale.success)
        self.assertEqual(self.record()["min_stock"], 0)
