from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
from unittest.mock import patch

import pytest

from AI.processors import report_builder, tools
from AI.processors.observation_projection import source_path_value, source_projection_hash
from AI.processors.operation_runtime import execute_approved_operation
from Core.processors.report_artifacts import verify_report_snapshot_xlsx
from Feedback.processors.pipeline import Result


def _sources():
    return [
        {"source_id": "sales", "source_step_id": "sales_read", "operation_id": "orders.item_sales_summary",
         "result": {"tool": "orders.item_sales_summary", "period": "last_7_days",
                    "products": [{"sku": "A", "quantity": 3, "revenue": 150.5, "currency": "TRY"}],
                    "coverage": {"status": "partial"}}},
        {"source_id": "movements", "source_step_id": "finance_read", "operation_id": "finance.cashflow_summary",
         "result": {"tool": "finance.cashflow_summary",
                    "currency_totals": [{"currency": "TRY", "combined_net": 50.25, "balance": None}]}},
    ]


def _sheets():
    return [
        {"name": "Sales", "source_id": "sales", "rows_path": "products", "columns": [
            {"key": "product", "label": "Product", "source_path": "sku", "data_type": "string"},
            {"key": "units", "label": "Units", "source_path": "quantity", "data_type": "integer"},
            {"key": "revenue", "label": "Revenue", "source_path": "revenue", "data_type": "number"},
            {"key": "currency", "label": "Currency", "source_path": "currency", "data_type": "string"},
        ]},
        {"name": "Movements", "source_id": "movements", "rows_path": "currency_totals", "columns": [
            {"key": "currency", "label": "Currency", "source_path": "currency", "data_type": "string"},
            {"key": "net", "label": "Registered movement", "source_path": "combined_net", "data_type": "number"},
            {"key": "balance", "label": "Known balance", "source_path": "balance", "data_type": "number"},
        ]},
    ]


def test_projection_copies_multiple_domain_rows_and_labels_model_inference():
    sources = _sources()
    snapshot = report_builder.build_observation_report_snapshot(
        title="My operations", sources=sources, sheets=_sheets(),
        notes=[{"kind": "hypothesis", "text": "Consider checking payment dates.", "source_ids": ["movements"]}],
    )
    assert snapshot.source_domain == "reports" and snapshot.report_type == "reports.observations"
    assert snapshot.sheets[0].rows == (("A", 3, 150.5, "TRY"),)
    assert snapshot.sheets[1].rows == (("TRY", 50.25, None),)
    assert snapshot.sheets[2].name == "Model Notları"
    assert "not a verified source fact" in snapshot.sheets[2].rows[0][3]
    metadata = snapshot.metadata
    assert metadata["source_receipts"][0]["source_result_hash"] == source_projection_hash(sources[0]["result"])
    assert metadata["source_receipts"][0]["coverage"] == {"status": "partial"}
    assert metadata["domain_calculations_performed"] is False
    assert metadata["null_cell_count"] == 1 and metadata["data_row_count"] == 2
    sources[0]["result"]["products"][0]["revenue"] = 9999
    assert snapshot.sheets[0].rows[0][2] == 150.5


def test_projection_accepts_a_source_root_as_one_row_and_preserves_dates():
    snapshot = report_builder.build_observation_report_snapshot(
        title="Read result", sources=[{"source_id": "x", "source_step_id": "read", "operation_id": "x.read",
                                      "result": {"count": 3, "day": date(2026, 10, 8)}}],
        sheets=[{"name": "Root", "source_id": "x", "rows_path": "", "columns": [
            {"key": "count", "label": "Count", "source_path": "count", "data_type": "integer"},
            {"key": "date", "label": "Day", "source_path": "day", "data_type": "date"},
        ]}],
    )
    assert snapshot.sheets[0].rows == ((3, "2026-10-08"),)


@pytest.mark.parametrize("case", ["unknown_source", "missing_field", "numeric_type_mismatch", "duplicate_source", "unbound_note"])
def test_report_builder_rejects_unsupported_source_projections(case):
    sources, sheets, notes = _sources(), _sheets(), []
    if case == "unknown_source":
        sheets[0]["source_id"] = "never_observed"
    elif case == "missing_field":
        sheets[0]["columns"][0]["source_path"] = "unobserved_profit"
    elif case == "numeric_type_mismatch":
        sources[0]["result"]["products"][0]["revenue"] = "150.5 TRY"
    elif case == "duplicate_source":
        sources.append(deepcopy(sources[0]))
    else:
        notes = [{"kind": "recommendation", "text": "Try this", "source_ids": ["unread"]}]
    with pytest.raises(ValueError):
        report_builder.build_observation_report_snapshot(title="Report", sources=sources, sheets=sheets, notes=notes)


def test_pure_projection_supports_dot_and_json_pointer_without_evaluating_code():
    data = {"rows": [{"value": Decimal("1.25"), "a/b": "literal"}], "none": None}
    assert source_path_value(data, "rows.0.value") == Decimal("1.25")
    assert source_path_value(data, "/rows/0/a~1b") == "literal"
    assert source_path_value(data, "none") is None
    assert source_projection_hash(data) == source_projection_hash({"none": None, "rows": data["rows"]})
    with pytest.raises(ValueError):
        source_path_value(data, "sum(rows.value)")
    with pytest.raises(ValueError):
        source_projection_hash({"value": float("nan")})


def test_generic_report_build_prepare_approval_export_and_exact_readback(tmp_path):
    registry = tools.available_tools()
    discovered = registry["operations.discover"].handler(domains=["reports"], limit=32)
    assert discovered.success
    assert {row["operation_id"] for row in discovered.data["operations"]} == {
        "reports.build_snapshot", "reports.xlsx.prepare",
    }
    built = registry["reports.build_snapshot"].handler(title="Across domains", sources=_sources(), sheets=_sheets())
    assert built.success, built.message
    output = tmp_path / "my-report.xlsx"
    prepared = registry["reports.xlsx.prepare"].handler(
        report_snapshot=built.data["report_snapshot"], output_path=str(output),
    )
    assert prepared.success and prepared.data["valid"], prepared.message
    assert not output.exists()
    assert prepared.data["content_hash"] == built.data["report_content_hash"]
    exported = execute_approved_operation(
        prepared.data["action"], approved_by="isolated-report-test",
        idempotency_key="generic-report-test", audit_path=tmp_path / "audit.jsonl",
    )
    assert exported.success, exported.message
    assert exported.data["verify"]["verified_by"] == "xlsx_exact_snapshot_readback"
    checked = verify_report_snapshot_xlsx(built.data["report_snapshot"], output)
    assert checked["verified"] and checked["problems"] == []


def test_generic_report_cannot_prepare_a_different_report_family(tmp_path):
    from Core.processors.report_artifacts import ReportColumn, ReportSnapshot, make_report_sheet
    web = ReportSnapshot.create(
        title="Web", source_domain="web", report_type="web.research", filters={}, metadata={},
        sheets=[make_report_sheet(name="Web", columns=[ReportColumn("fact", "Fact")], rows=[{"fact": "Opened"}])],
    )
    result = tools.reports_prepare_xlsx(report_snapshot=web.to_dict(), output_path=str(tmp_path / "not-created.xlsx"))
    assert result.success and result.data["valid"] is False
    assert result.data["action"]["execute_enabled"] is False


def test_model_planned_cross_domain_report_binds_reads_until_approved_exact_readback(tmp_path):
    from AI.processors.task_runtime import run_agent_task, resume_agent_task_with_approval
    from openpyxl import load_workbook

    registry = tools.available_tools()
    sources = _sources()
    source_payloads = {source["operation_id"]: source["result"] for source in sources}
    reads = []

    def observed_read(operation_id):
        def handler(**_arguments):
            reads.append(operation_id)
            return Result.ok("Isolated authoritative fixture", data=deepcopy(source_payloads[operation_id]))
        return handler

    # Keep real operation metadata and all production artifact handlers. Only
    # the two business reads are replaced with independent synthetic sources.
    registry = {
        name: replace(tool, handler=observed_read(name)) if name in source_payloads else tool
        for name, tool in registry.items()
        if name in {*source_payloads, "reports.build_snapshot", "reports.xlsx.prepare", "operations.discover"}
    }
    output = tmp_path / "agent-created.xlsx"
    bound_sources = [{**source, "result": {"$from_step": source["source_step_id"], "path": "tool_result"}}
                     for source in sources]
    plan = {"steps": [
        {"id": "sales_read", "operation_id": "orders.item_sales_summary", "arguments": {}, "depends_on": [],
         "objective": "Read the sales source", "expected_evidence": ["products"]},
        {"id": "finance_read", "operation_id": "finance.cashflow_summary", "arguments": {}, "depends_on": [],
         "objective": "Read the movement source", "expected_evidence": ["currency_totals"]},
        {"id": "custom_report", "operation_id": "reports.build_snapshot",
         "arguments": {"title": "My cross-domain report", "sources": bound_sources, "sheets": _sheets(),
                       "notes": [{"kind": "hypothesis", "text": "Check payment dates", "source_ids": ["movements"]}]},
         "depends_on": ["sales_read", "finance_read"], "objective": "Project both sources into my selected layout",
         "expected_evidence": ["report_snapshot", "source_receipts"]},
        {"id": "prepare_xlsx", "operation_id": "reports.xlsx.prepare",
         "arguments": {"report_snapshot": {"$from_step": "custom_report", "path": "tool_result.report_snapshot"},
                       "output_path": str(output)},
         "depends_on": ["custom_report"], "objective": "Prepare the custom Excel report",
         "expected_evidence": ["action", "snapshot_id", "output_path"]},
    ]}

    def planner(prompt):
        if prompt.startswith("OrderScout semantic action verifier"):
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                               "unwanted_effect": False, "reason": "User requested this report file"})
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "continue", "reason": "Complete the remaining report steps"})
        return json.dumps(plan)

    with patch("AI.processors.tools.available_tools", return_value=registry):
        started = run_agent_task(
            "Create a custom Excel report with sales and finance observations in separate sheets",
            domain="general", planner_client=planner, persist=False,
            turn_interpretation={"mode": "act", "intent_kind": "action", "domain": "general", "valid": True,
                                 "objective": "Create my custom sales and finance Excel report",
                                 "requested_fields": ["artifact"], "requires_clarification": False},
        )
        assert started.success, started.message
        state = started.data["state"]
        assert state["status"] == "pending_approval", json.dumps({
            "plan": {key: value for key, value in state["active_entities"].get("task_plan", {}).items()
                     if key not in {"step_specs"}},
            "completed": [{"id": row["step_id"], "status": row["status"], "message": row.get("result_message"),
                           "error": row.get("error"), "data": row["result_data"] if row["status"] != "completed" else None}
                          for row in state["completed_steps"]],
        }, ensure_ascii=False, indent=2)
        assert reads == ["orders.item_sales_summary", "finance.cashflow_summary"]
        assert [step["tool_names"] for step in state["completed_steps"]] == [
            ["orders.item_sales_summary"], ["finance.cashflow_summary"],
            ["reports.build_snapshot"], ["reports.xlsx.prepare"],
        ]
        assert not output.exists()
        report_result = state["completed_steps"][2]["result_data"]["tool_result"]
        snapshot = report_result["report_snapshot"]
        assert report_result["source_receipts"][0]["source_result_hash"] == source_projection_hash(sources[0]["result"])
        action = state["pending_actions"][0]
        assert action["domain"] == "reports"
        assert action["arguments"]["content_hash"] == report_result["report_content_hash"]
        resumed = resume_agent_task_with_approval(
            state, approved_by="isolated-model-report-test", audit_path=str(tmp_path / "audit.jsonl"),
            idempotency_key="source-bound-model-report", continue_after_execute=True, persist=False,
        )

    assert resumed.success, f"{resumed.message} | {resumed.data}"
    assert resumed.data["state"]["status"] == "complete"
    verify = resumed.data["state"]["action_history"][-1]["verify"]
    assert verify["verified"] and verify["verified_by"] == "xlsx_exact_snapshot_readback"
    assert verify_report_snapshot_xlsx(snapshot, output)["verified"]
    workbook = load_workbook(output, read_only=True, data_only=True)
    try:
        assert tuple(workbook["Sales"].values)[1] == ("A", 3, 150.5, "TRY")
        assert tuple(workbook["Movements"].values)[1] == ("TRY", 50.25, None)
        assert "not a verified source fact" in tuple(workbook["Model Notları"].values)[1][3]
    finally:
        workbook.close()
