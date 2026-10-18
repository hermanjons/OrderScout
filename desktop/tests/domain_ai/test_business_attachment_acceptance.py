from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from AI.processors import file_workspace, tools
from AI.processors.business_agent_acceptance_cli import retain_approved_export
from AI.processors.business_acceptance_evidence import (
    completed_observation_receipts, validate_attachment_export_cells, validate_attachment_observations,
    validate_general_report_sources,
)
from AI.processors.business_attachment_fixtures import seed_attachment_fixtures
from AI.processors.session_state import AgentSessionState
from AI.views.chat_tab import AITab


def _observed_turn(result, operation="files.read"):
    return {"raw_turn_data": {"state": {"completed_steps": [{
        "step_id": "actual_read", "status": "completed", "verification_status": "observed",
        "tool_names": [operation], "result_data": {"tool_result": result},
    }]}}}


class TestBusinessAttachmentAcceptance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orderscout-attachment-acceptance-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fixtures = seed_attachment_fixtures(self.root)
        self.session_id = "isolated-file-test-" + uuid4().hex

    def _import_and_read(self, kind):
        messages = []
        # Use the actual source UI method and actual immutable file import;
        # only its label/transcript widgets are replaced by inert view sinks.
        view = SimpleNamespace(
            _conversation_state=AgentSessionState(session_id=self.session_id, goal="").to_dict(),
            _append_chat_message=lambda role, text: messages.append((role, text)),
            btn_attach=SimpleNamespace(setToolTip=lambda text: None),
        )
        AITab._import_chat_attachments(view, [self.fixtures[kind]["path"]])
        selected = view._conversation_state["active_entities"]["file_workspace"]["attachments"]
        self.assertEqual(len(selected), 1, messages)
        result = file_workspace.read_attachment(attachment_id=selected[0]["attachment_id"], session_id=self.session_id)
        self.assertTrue(result.success, result.message)
        return selected, _observed_turn(result.data)

    def _build_source_report(self, kind="json", *, reordered=False, crossed_fields=False):
        selected, turn = self._import_and_read(kind)
        receipt = completed_observation_receipts(turn)[0]
        result = receipt["result"]
        fields = list(self.fixtures[kind]["columns"])
        if reordered:
            fields.reverse()
        source_keys = ({column["label"]: column["key"] for column in result["columns"]}
                       if kind == "xlsx" else {field: field for field in fields})
        built = tools.reports_build_snapshot(
            title="Exact source report", sources=[{"source_id": "selected_file", "source_step_id": receipt["source_step_id"],
                                                   "operation_id": "files.read", "result": result}],
            sheets=[{"name": "Serbest Tablo", "source_id": "selected_file", "rows_path": "rows", "columns": [
                {"key": "custom_" + field if reordered else field,
                 "label": "Özel başlık " + str(index) if reordered else field,
                 "source_path": "/" + source_keys[({"quantity": "revenue", "revenue": "quantity"}.get(field, field)
                                                   if crossed_fields else field)],
                 "data_type": ("integer" if field == "quantity" and not crossed_fields
                               else "number" if field in {"quantity", "revenue", "discount"} else "string")}
                for index, field in enumerate(fields)]}],
        )
        self.assertTrue(built.success, built.message)
        return turn, built.data["report_snapshot"]

    def _validate_cells(self, saved, turn, snapshot, kind="json"):
        return validate_attachment_export_cells(saved, self.fixtures, required_formats=(kind,),
                                               report_snapshot=snapshot, source_receipts=completed_observation_receipts(turn))

    def test_real_source_ui_import_and_native_json_rows_satisfy_independent_oracle(self):
        selected, turn = self._import_and_read("json")
        evidence = validate_attachment_observations(turn, self.fixtures, selected, required_formats=("json",))
        self.assertTrue(evidence["passed"], evidence)
        receipt = completed_observation_receipts(turn)[0]
        self.assertEqual(receipt["operation_id"], "files.read")
        self.assertNotIn("tool", receipt["result"])
        self.assertEqual(receipt["result"]["rows"], self.fixtures["json"]["rows"])

    def test_real_xlsx_headers_native_numbers_and_nulls_satisfy_independent_oracle(self):
        selected, turn = self._import_and_read("xlsx")
        evidence = validate_attachment_observations(turn, self.fixtures, selected, required_formats=("xlsx",))
        self.assertTrue(evidence["passed"], evidence)
        result = completed_observation_receipts(turn)[0]["result"]
        self.assertEqual(result["columns"][1]["data_type"], "integer")
        self.assertIsNone(result["rows"][0]["column_6"])

    def test_model_cannot_supply_a_path_or_invent_registered_file_identity(self):
        registry = tools.available_tools()
        parameters = registry["files.read"].parameters
        self.assertNotIn("path", parameters["properties"])
        self.assertFalse(parameters["additionalProperties"])
        with self.assertRaises(TypeError):
            registry["files.read"].handler(path=self.fixtures["json"]["path"], session_id=self.session_id)
        unknown = registry["files.read"].handler(attachment_id="att_" + "0" * 32, session_id=self.session_id)
        self.assertFalse(unknown.success)
        self.assertEqual(unknown.data["reason"], "attachment_not_registered_in_session")

    def test_equal_rows_with_wrong_owner_hash_or_native_types_do_not_pass(self):
        selected, turn = self._import_and_read("json")
        for mutation in ("owner", "hash", "type", "coverage", "null"):
            with self.subTest(mutation=mutation):
                altered = deepcopy(turn)
                result = altered["raw_turn_data"]["state"]["completed_steps"][0]["result_data"]["tool_result"]
                if mutation == "owner":
                    result["session_id"] = "invented-other-owner"
                elif mutation == "hash":
                    result["source_hash"] = "0" * 64
                elif mutation == "type":
                    result["rows"][0]["quantity"] = "4"
                elif mutation == "coverage":
                    result["data_coverage"]["status"] = "partial"
                else:
                    result["rows"][0]["discount"] = 0
                evidence = validate_attachment_observations(altered, self.fixtures, selected, required_formats=("json",))
                self.assertFalse(evidence["passed"])

    def test_registry_list_metadata_alone_cannot_certify_report_file_sources(self):
        selected, turn = self._import_and_read("json")
        listing = file_workspace.list_attachments(session_id=self.session_id)
        listed_turn = _observed_turn(listing.data, "files.list")
        listing_receipt = completed_observation_receipts(listed_turn)[0]
        built = {"report_snapshot": {
            "source_domain": "reports", "report_type": "reports.observations", "snapshot_id": "rpt_test",
            "content_hash": "hash", "metadata": {"data_row_count": 1, "source_receipts": [{
                "source_step_id": listing_receipt["source_step_id"], "operation_id": "files.list",
                "source_result_hash": listing_receipt["source_result_hash"],
            }]}}}
        report_step = _observed_turn(built, "reports.build_snapshot")["raw_turn_data"]["state"]["completed_steps"][0]
        report_step["step_id"] = "built_report"
        listed_turn["raw_turn_data"]["state"]["completed_steps"].append(report_step)
        evidence = validate_general_report_sources(listed_turn, required_domains=("files",), required_source_operations=("files.read",))
        self.assertIn("general_report_required_source_operation_missing:files.read", evidence["problems"])

    def test_actual_approved_report_saved_cells_equal_attached_file_native_rows(self):
        self._check_approved_native_rows("number")

    def test_actual_nullable_text_column_preserves_source_null_and_native_blank(self):
        self._check_approved_native_rows("string")

    def _check_approved_native_rows(self, discount_type):
        selected, turn = self._import_and_read("json")
        receipt = completed_observation_receipts(turn)[0]
        built = tools.reports_build_snapshot(
            title="Attachment report", sources=[{"source_id": "selected_file", "source_step_id": receipt["source_step_id"],
                                                  "operation_id": "files.read", "result": receipt["result"]}],
            sheets=[{"name": "Ek Dosya", "source_id": "selected_file", "rows_path": "rows", "columns": [
                {"key": key, "label": key, "source_path": key,
                 "data_type": discount_type if key == "discount" else "integer" if key == "quantity" else "number" if key == "revenue" else "string"}
                for key in self.fixtures["json"]["columns"]]}],
        )
        self.assertTrue(built.success, built.message)
        output = self.root / "approved.xlsx"
        prepared = tools.reports_prepare_xlsx(report_snapshot=built.data["report_snapshot"], output_path=str(output))
        self.assertTrue(prepared.success, prepared.message)
        self.assertFalse(output.exists())
        from AI.processors.operation_runtime import execute_approved_operation
        exported = execute_approved_operation(prepared.data["action"], approved_by="synthetic-file-acceptance",
                                             idempotency_key=self.session_id, audit_path=self.root / "audit.jsonl")
        self.assertTrue(exported.success, exported.message)
        export_turn = {"scenario_id": "attachment_approve", "approved_action": prepared.data["action"],
                       "execute": {"success": True, "data": exported.data}}
        retained = retain_approved_export(export_turn, isolation_root=self.root, artifact_path=self.root / "evidence" / "live.json")
        snapshot = built.data["report_snapshot"]
        evidence = self._validate_cells(retained, turn, snapshot)
        self.assertTrue(evidence["passed"], evidence)
        changed = deepcopy(retained)
        changed["sheets"][0]["rows"][1][3] = 9999
        self.assertFalse(self._validate_cells(changed, turn, snapshot)["passed"])

    def test_original_record_values_cannot_be_scattered_or_change_null_to_zero(self):
        turn, snapshot = self._build_source_report()
        saved = {"sheets": deepcopy(snapshot["sheets"])}
        self.assertTrue(self._validate_cells(saved, turn, snapshot)["passed"])
        saved["sheets"][0]["rows"][0][-1] = 0
        self.assertFalse(self._validate_cells(saved, turn, snapshot)["passed"])

    def test_saved_source_records_cannot_be_counted_twice(self):
        turn, snapshot = self._build_source_report()
        saved = {"sheets": deepcopy(snapshot["sheets"])}
        saved["sheets"][0]["rows"].append(deepcopy(saved["sheets"][0]["rows"][0]))
        evidence = self._validate_cells(saved, turn, snapshot)
        self.assertFalse(evidence["passed"])
        self.assertIn("attachment_saved_record_duplicated:PILOT-KUPA", evidence["problems"])

    def test_field_cell_swap_cannot_pass_as_preserved_values_under_unchanged_provenance(self):
        turn, snapshot = self._build_source_report()
        saved = {"sheets": deepcopy(snapshot["sheets"])}
        for row in saved["sheets"][0]["rows"]:
            row[1], row[3] = row[3], row[1]
        evidence = self._validate_cells(saved, turn, snapshot)
        self.assertFalse(evidence["passed"], evidence)
        self.assertIn("attachment_saved_record_cells_missing_or_changed:PILOT-KUPA", evidence["problems"])
        self.assertIn("attachment_saved_record_cells_missing_or_changed:PILOT-FILTRE", evidence["problems"])

    def test_arbitrary_labels_and_order_preserve_exact_source_field_cells_for_json_and_xlsx(self):
        for kind in ("json", "xlsx"):
            with self.subTest(kind=kind):
                turn, snapshot = self._build_source_report(kind, reordered=True)
                saved = {"sheets": [{"name": sheet["name"], "rows": [
                    [column["label"] for column in sheet["columns"]], *deepcopy(sheet["rows"]),
                ]} for sheet in snapshot["sheets"]]}
                evidence = self._validate_cells(saved, turn, snapshot, kind)
                self.assertTrue(evidence["passed"], evidence)
                self.assertEqual(evidence["proof"][0]["saved_rows"][0]["field_columns"]["quantity"], 5)

    def test_missing_projection_or_changed_source_hash_cannot_certify_equal_saved_values(self):
        turn, snapshot = self._build_source_report()
        saved = {"sheets": deepcopy(snapshot["sheets"])}
        no_projection = validate_attachment_export_cells(saved, self.fixtures, required_formats=("json",))
        self.assertFalse(no_projection["passed"])
        changed = deepcopy(turn)
        changed["raw_turn_data"]["state"]["completed_steps"][0]["result_data"]["tool_result"]["source_hash"] = "0" * 64
        self.assertFalse(self._validate_cells(saved, changed, snapshot)["passed"])

    def test_rehashed_wrong_declared_field_binding_cannot_certify_source_preservation(self):
        from AI.processors.business_acceptance_evidence import receipt_hash
        turn, snapshot = self._build_source_report()
        wrong = deepcopy(snapshot)
        projection = wrong["metadata"]["projections"][0]
        projection["columns"][1]["source_path"] = "/revenue"
        projection["columns"][3]["source_path"] = "/quantity"
        for row in wrong["sheets"][0]["rows"]:
            row[1], row[3] = row[3], row[1]
        content = {key: wrong[key] for key in ("schema_version", "title", "source_domain", "report_type", "filters", "metadata", "sheets")}
        wrong["content_hash"] = receipt_hash(content)
        wrong["snapshot_id"] = "rpt_" + wrong["content_hash"][:24]
        evidence = self._validate_cells({"sheets": wrong["sheets"]}, turn, wrong)
        self.assertFalse(evidence["passed"])
        self.assertIn("attachment_declared_field_source_mismatch:quantity", evidence["problems"])

    def test_actual_built_and_approved_export_with_crossed_field_bindings_is_rejected(self):
        turn, snapshot = self._build_source_report(crossed_fields=True)
        output = self.root / "crossed-fields.xlsx"
        prepared = tools.reports_prepare_xlsx(report_snapshot=snapshot, output_path=str(output))
        self.assertTrue(prepared.success, prepared.message)
        from AI.processors.operation_runtime import execute_approved_operation
        exported = execute_approved_operation(prepared.data["action"], approved_by="synthetic-oracle-counterexample",
                                             idempotency_key=self.session_id, audit_path=self.root / "crossed-audit.jsonl")
        self.assertTrue(exported.success, exported.message)
        export_turn = {"scenario_id": "attachment_approve", "approved_action": prepared.data["action"],
                       "execute": {"success": True, "data": exported.data}}
        retained = retain_approved_export(export_turn, isolation_root=self.root, artifact_path=self.root / "evidence" / "crossed.json")
        self.assertEqual(retained["sheets"][0]["rows"][1][1], 1200.5)
        self.assertEqual(retained["sheets"][0]["rows"][1][3], 4)
        evidence = self._validate_cells(retained, turn, snapshot)
        self.assertFalse(evidence["passed"], evidence)
        self.assertIn("attachment_declared_field_source_mismatch:quantity", evidence["problems"])

    def test_cell_native_types_and_header_binding_are_checked_independently(self):
        turn, snapshot = self._build_source_report()
        original = {"sheets": [{"name": sheet["name"], "rows": [
            [column["label"] for column in sheet["columns"]], *deepcopy(sheet["rows"]),
        ]} for sheet in snapshot["sheets"]]}
        for mutation in ("numeric_string", "boolean_zero", "header_swap", "currency_swap", "source_schema_drift"):
            with self.subTest(mutation=mutation):
                saved = deepcopy(original)
                projected = deepcopy(snapshot)
                if mutation == "numeric_string":
                    saved["sheets"][0]["rows"][1][1] = "4"
                elif mutation == "boolean_zero":
                    saved["sheets"][0]["rows"][3][1] = False
                elif mutation == "header_swap":
                    row = saved["sheets"][0]["rows"][0]
                    row[1], row[3] = row[3], row[1]
                elif mutation == "currency_swap":
                    saved["sheets"][0]["rows"][1][4] = "USD"
                else:
                    projected["metadata"]["projections"][0]["columns"][1]["source_path"] = "/revenue"
                self.assertFalse(self._validate_cells(saved, turn, projected)["passed"])


if __name__ == "__main__":
    unittest.main()
