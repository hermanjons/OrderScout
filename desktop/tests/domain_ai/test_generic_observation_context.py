"""Prior generic work must remain intelligible without forged or private facts."""
import json

import pytest

from AI.processors.analysis_operations import calculate_observations
from AI.processors.observation_context import generic_observation_context
from AI.processors.report_builder import build_observation_report_snapshot
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.tabular_analysis import analyze_observation_table


def _step(state, name, operation, data, **kwargs):
    state.completed_steps.append(AgentTaskStep(
        index=len(state.completed_steps) + 1, step_id=name, prompt="Observe",
        status="completed", verification_status="observed", tool_names=[operation],
        result_data={"tool_result": data}, **kwargs,
    ))


def _state(groups=2):
    state = AgentSessionState(goal="Review attached sales", active_domain="general")
    raw = {"rows": [{"quantity": index + 1, "revenue": 2.5, "currency": "TRY",
                    "unit": "adet", "discount": None, "sku": f"SKU-{index}"} for index in range(groups)],
           "attachment": {"name": "source-sales.json", "source_path": "C:/private/source.json"},
           "format": "json", "row_count": groups,
           "data_coverage": {"status": "complete"}, "api_key": "never-model-this-secret",
           "customer": {"email": "private@example.test"}}
    _step(state, "read", "files.read", raw)
    source = {"source_id": "sales", "source_step_id": "read", "operation_id": "files.read", "result": raw}
    table = analyze_observation_table(sources=[source], source_id="sales", rows_path="rows",
                                     group_by=["sku"], measures=[{"name": "units", "operator": "sum",
                                                                  "path": "quantity", "unit_path": "unit"}])
    assert table.success
    _step(state, "table", "analysis.table", table.data)
    calculation = calculate_observations(sources=[source], calculations=[{
        "calculation_id": "difference", "operator": "subtract", "operands": [
            {"source_id": "sales", "path": "rows.1.quantity"},
            {"source_id": "sales", "path": "rows.0.quantity"},
        ]}])
    assert calculation.success
    _step(state, "calculation", "analysis.calculate", calculation.data)
    notes = [{"kind": "hypothesis", "text": "A hypothesis, not a fact", "source_ids": ["sales"]}]
    snapshot = build_observation_report_snapshot(title="Source sales", sources=[source], notes=notes, sheets=[{
        "name": "Sales", "source_id": "sales", "rows_path": "rows", "columns": [
            {"key": "revenue", "label": "Revenue", "data_type": "number", "source_path": "revenue"},
            {"key": "discount", "label": "Discount", "data_type": "number", "source_path": "discount"},
        ],
    }])
    _step(state, "report", "reports.build_snapshot", {"report_snapshot": snapshot.to_dict()}, arguments={"notes": notes})
    return state


def test_calculation_table_and_report_receipts_survive_conversation_projection():
    from AI.processors.task_runtime import _safe_existing_observation_context

    state = _state()
    projected = _safe_existing_observation_context(state)["generic_evidence"]
    assert projected["verified_calculations"][0]["result"] == "1.00"
    assert projected["verified_calculations"][0]["unit"] == "adet"
    assert projected["verified_table_analyses"][0]["rows"][1]["metrics"]["units"]["value"] == 2
    report = projected["verified_report_preparations"][0]
    assert report["data_row_count"] == 2 and report["null_cell_count"] == 2
    assert report["preparation_proves_file_creation"] is False
    assert report["model_notes_are_verified_facts"] is False
    assert projected["verified_artifact_receipts"] == []
    assert report["source_metadata"][0]["name"] == "source-sales.json"
    assert report["source_metadata"][0]["rows_read"] == 2
    serialized = json.dumps(projected)
    assert "never-model-this-secret" not in serialized and "private@example.test" not in serialized
    assert "A hypothesis, not a fact" not in serialized
    assert "C:/private/source" not in serialized


def test_report_summary_uses_exact_current_proposal_and_keeps_nulls():
    from AI.processors.observation_context import verified_pending_report_answer
    from AI.processors.tools import reports_prepare_xlsx
    state = _state()
    snapshot = state.completed_steps[-1].result_data["tool_result"]["report_snapshot"]
    prepared = reports_prepare_xlsx(report_snapshot=snapshot, output_path="context-report.xlsx")
    assert prepared.success
    state.pending_actions = [prepared.data["action"]]
    state.active_pending_action_id = prepared.data["action"]["action_id"]
    state.status = 'pending_approval'
    _step(state, 'prepare', 'reports.xlsx.prepare', prepared.data)
    answer = verified_pending_report_answer(state)
    assert "source-sales.json" in answer and "2 satır" in answer
    assert "2 hücre" in answer and "onayını bekliyor" in answer
    assert "private@example.test" not in answer and "C:/private/source" not in answer
    state.cancel_active_pending_action(reason="user cancelled", cancelled_by="user")
    assert verified_pending_report_answer(state) == ""


@pytest.mark.parametrize("mutation", ["read", "report_cells", "report_source", "table"])
def test_corrupt_prior_proof_is_not_promoted_to_verified_context(mutation):
    from Core.processors.report_artifacts import ReportSnapshot

    state = _state()
    if mutation == "read":
        state.completed_steps[0].result_data["tool_result"]["rows"][0]["quantity"] = 900
    elif mutation == "table":
        state.completed_steps[1].result_data["tool_result"]["rows"][0]["metrics"]["units"]["value"] = 900
    else:
        raw = state.completed_steps[-1].result_data["tool_result"]["report_snapshot"]
        if mutation == "report_cells":
            raw["sheets"][0]["rows"][0][0] = 900
        else:
            raw["metadata"]["source_receipts"][0]["operation_id"] = "orders.revenue_total"
        # Even a newly valid content hash cannot rewrite observed provenance.
        raw.pop("content_hash")
        raw.pop("snapshot_id")
        state.completed_steps[-1].result_data["tool_result"]["report_snapshot"] = ReportSnapshot.from_dict(raw).to_dict()
    projected = generic_observation_context(state)
    if mutation == "read":
        assert projected["verified_calculations"] == []
        assert projected["verified_table_analyses"] == []
        assert projected["verified_report_preparations"] == []
    elif mutation == "table":
        assert projected["verified_table_analyses"] == []
    else:
        assert projected["verified_report_preparations"] == []


def test_bare_readback_without_actual_approved_execution_is_not_a_created_artifact():
    state = _state()
    snapshot = state.completed_steps[-1].result_data["tool_result"]["report_snapshot"]
    verify = {"verified": True, "verified_by": "xlsx_exact_snapshot_readback", "problems": [],
              "snapshot_id": snapshot["snapshot_id"], "content_hash": snapshot["content_hash"],
              "file_sha256": "f" * 64, "size_bytes": 1234, "sheet_count": 3, "sheets": [],
              "output_path": "C:/private/output.xlsx"}
    state.last_tool_results = [{"tool_names": ["execute_approved_operation"], "data": {"verify": verify}}]
    projected = generic_observation_context(state)
    assert projected["verified_artifact_receipts"] == []
    assert "C:/private" not in json.dumps(projected)
    verify["content_hash"] = "unrelated-report"
    assert generic_observation_context(state)["verified_artifact_receipts"] == []
    verify["content_hash"] = snapshot["content_hash"]
    verify["verified_by"] = "filesystem"
    assert generic_observation_context(state)["verified_artifact_receipts"] == []


def test_truncated_table_context_preserves_actual_source_population_and_flag():
    projected = generic_observation_context(_state(groups=25))
    table = projected["verified_table_analyses"][0]
    assert table["source_row_count"] == 25 and table["group_count"] == 25
    assert len(table["rows"]) == 20 and table["context_rows_truncated"] is True


def test_large_context_remains_bounded_and_marks_omission():
    state = _state()
    # Source-bound group identity is intentionally large, but context may omit
    # this proof rather than claim its truncated labels as different records.
    raw = state.completed_steps[0].result_data["tool_result"]
    raw["rows"][0]["sku"] = "x" * 100_000
    source = {"source_id": "sales", "source_step_id": "read", "operation_id": "files.read", "result": raw}
    table = analyze_observation_table(sources=[source], source_id="sales", rows_path="rows",
                                     group_by=["sku"], measures=[{"name": "count", "operator": "count"}])
    assert table.success
    state.completed_steps[1].result_data["tool_result"] = table.data
    projected = generic_observation_context(state)
    assert len(json.dumps(projected, ensure_ascii=False)) <= 48_000
    assert projected["context_truncated"] is True
    assert projected["verified_table_analyses"] == []
