"""Prepare and approved export retain the real manual profit calculation."""
from openpyxl import load_workbook

import pytest
import json
from copy import deepcopy
from pathlib import Path

from AI.processors import model_loop, operation_runtime, task_runtime, tools
from Feedback.processors.pipeline import Result
from Testing.processors.business_agent_fixtures import seed_business_fixture


def test_profit_tool_prepares_real_costs_then_exports_that_snapshot(tmp_path):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    output = tmp_path / "profit.xlsx"
    result = tools.orders_prepare_export_profit_excel(
        db_name=database, query="PILOT-A-NEW-1", output_path=str(output),
    )
    assert result.success, result.message
    action = result.data["action"]
    assert action["execute_enabled"], action
    payload = action["arguments"]["payload"]["estimated_profit_payload"]
    assert payload["estimated_profit_ready"], payload["estimated_profit_missing_reasons"]
    assert payload["estimated_profit"] == 800
    assert payload["estimated_profit_detail"]["results"]["total_costs"] == 200
    assert not output.exists()
    audit = tmp_path / "audit.jsonl"
    executed = operation_runtime.execute_approved_operation(
        action, idempotency_key="profit-domain-parity", audit_path=audit,
    )
    assert executed.success, executed.data
    assert executed.data["verify"]["verified"]
    assert executed.data["verify"]["verified_by"] == "xlsx_exact_snapshot_readback"
    workbook = load_workbook(output, read_only=True, data_only=True)
    try:
        sheet = workbook["Ozet"]
        assert sheet["B2"].value == "PILOT-A-NEW-1"
        assert sheet["B5"].value == payload["estimated_profit_detail"]["results"]["total_costs_text"]
        assert sheet["B6"].value == payload["estimated_profit_text"]
        assert sheet["B7"].value == "Hazır"
        assert workbook["Satis"].max_row == 2
        assert workbook["Maliyetler"].cell(workbook["Maliyetler"].max_row, 3).value == sheet["B5"].value
    finally:
        workbook.close()
    assert "orders.action_export_order_profit_excel" in audit.read_text(encoding="utf-8")


@pytest.mark.parametrize("suffix", ["", ".csv"])
def test_prepare_normalizes_the_exact_path_that_the_writer_and_verifier_use(tmp_path, suffix):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    prepared = tools.orders_prepare_export_profit_excel(db_name=database, query="PILOT-A-NEW-1",
                                                        output_path=str(tmp_path / ("profit" + suffix)))
    action = prepared.data["action"]
    target = str(tmp_path / "profit.xlsx")
    assert action["arguments"]["payload"]["output_path"] == target
    assert action["rows"][0]["output_path"] == target
    executed = operation_runtime.execute_approved_operation(action, idempotency_key="normalized-profit",
                                                           audit_path=tmp_path / "audit.jsonl")
    assert executed.success, executed.data
    assert executed.data["verify"]["output_path"] == target


def test_writer_success_with_a_nonempty_wrong_file_is_a_failed_effect(tmp_path, monkeypatch):
    from Orders.views import actions
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    output = tmp_path / "profit.xlsx"
    prepared = tools.orders_prepare_export_profit_excel(db_name=database, query="PILOT-A-NEW-1", output_path=str(output))
    def wrong_file(**kwargs):
        output.write_bytes(b"nonempty but not a workbook")
        return Result.ok("Writer says success", data={"output_path": str(output), "verified": True})
    monkeypatch.setattr(actions, "write_order_profit_payload_to_excel", wrong_file)
    result = operation_runtime.execute_approved_operation(prepared.data["action"], idempotency_key="bad-profit",
                                                          audit_path=tmp_path / "audit.jsonl")
    assert not result.success, result.data
    assert result.data["verify"]["verified"] is False
    assert '"status": "failed"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_verifier_requires_the_approved_estimate_even_if_writer_claims_verification(tmp_path):
    output = tmp_path / "profit.xlsx"
    output.write_bytes(b"a nonempty file")
    action = {"arguments": {"payload": {"order_number": "ORDER-17", "output_path": str(output)}}}
    result = operation_runtime.verify_order_profit_excel_export(
        action, Result.ok("claimed", data={"verified": True, "output_path": str(output)}))
    assert not result.success and result.data["verified"] is False


class Model:
    resource_plan = {"capability_profile": {"native_tool_runtime_enabled": True}}
    def __init__(self, decisions):
        self.decisions = iter(decisions)
    def invoke_tools(self, prompt, *, tools):
        decision = next(self.decisions)
        return json.dumps(decision) if isinstance(decision, dict) else decision


def _completed_native_profit_export(tmp_path):
    database = str(tmp_path / "fixture.sqlite3")
    seed_business_fixture(database, isolation_root=tmp_path)
    output = tmp_path / "native-profit.xlsx"
    decisions = [
        {"mode": "tool", "tool": "orders.query", "arguments": {"period": "all", "order_numbers": ["PILOT-A-NEW-1"]}},
        {"mode": "tool", "tool": "orders.export_profit_excel.prepare", "arguments": {"query": "PILOT-A-NEW-1", "output_path": str(output)}},
        "Sipariş kârı Excel'ini hazırladım; dosyayı kaydetmek için onayını bekliyorum.",
    ]
    prepared = model_loop.run_model_loop(f"PILOT-A-NEW-1 siparişinin kâr Excel'ini {output} dosyasına hazırla.",
        client=Model(decisions), db_name=database, persist=False)
    state = prepared.data["state"]
    assert state["status"] == "pending_approval", prepared.data
    assert not output.exists()
    answer = f"Kâr Excel'i oluşturuldu: [Excel'i indir]({output})"
    completed = task_runtime.resume_agent_task_with_approval(state, action_id=state["active_pending_action_id"],
        planner_client=Model([answer]), db_name=database, persist=False, audit_path=tmp_path / "audit.jsonl")
    assert completed.success, completed.data
    assert completed.data["answer"] == answer
    return completed, output


def test_native_approval_publishes_an_exact_profit_file_receipt_and_allows_its_link(tmp_path):
    from AI.processors.observation_context import verified_export_report_receipts
    from AI.processors.session_state import AgentSessionState
    completed, output = _completed_native_profit_export(tmp_path)
    restored = AgentSessionState.from_dict(completed.data["state"])
    receipts = verified_export_report_receipts(restored)
    assert len(receipts) == 1, completed.data
    assert receipts[0]["output_path"] == str(output)
    assert receipts[0]["verified_by"] == "xlsx_exact_snapshot_readback"
    assert len(receipts[0]["file_sha256"]) == 64


def test_profit_receipt_creates_a_clickable_download_in_the_actual_chat_widget(tmp_path, monkeypatch):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QApplication
    from AI.views import chat_tab
    completed, output = _completed_native_profit_export(tmp_path)
    app = QApplication.instance() or QApplication([])
    widget = chat_tab.AITab()
    opened = []
    monkeypatch.setattr(chat_tab.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    try:
        widget._append_verified_artifact_links(completed.data)
        assert len(widget._delivered_artifacts) == 1
        token, receipt = next(iter(widget._delivered_artifacts.items()))
        assert receipt["output_path"] == str(output)
        assert output.name in widget.transcript.toPlainText()
        widget._on_transcript_anchor_clicked(QUrl("orderscout://artifact/open/" + token))
        assert [output] == [Path(path) for path in opened]
    finally:
        widget.close()
        app.processEvents()


@pytest.mark.parametrize("change", ["missing_prepare", "different_account", "failed_audit", "no_approver",
                                    "filesystem_only", "wrong_hash", "missing_event", "writer_result_mismatch"])
def test_profit_file_delivery_requires_the_complete_observed_approved_verified_chain(tmp_path, change):
    from AI.processors.observation_context import verified_export_report_receipts
    from AI.processors.session_state import AgentSessionState
    from AI.runtime.artifact_delivery import unverified_local_artifact_links
    completed, output = _completed_native_profit_export(tmp_path)
    state = deepcopy(completed.data["state"])
    execution = next(row["data"] for row in state["last_tool_results"]
                     if row["tool_names"] == ["execute_approved_operation"])
    if change == "missing_prepare":
        state["completed_steps"] = [row for row in state["completed_steps"]
                                    if row["tool_names"] != ["orders.export_profit_excel.prepare"]]
    elif change == "different_account":
        execution["audit"]["action"]["arguments"]["payload"]["api_account_id"] = 102
    elif change == "failed_audit":
        execution["audit"]["status"] = "failed"
    elif change == "no_approver":
        execution["audit"]["approved_by"] = ""
    elif change == "filesystem_only":
        execution["verify"]["verified_by"] = "filesystem"
    elif change == "wrong_hash":
        execution["verify"]["file_sha256"] = "0" * 64
    elif change == "missing_event":
        state["action_history"] = []
    else:
        execution["result"]["content_hash"] = "0" * 64
    restored = AgentSessionState.from_dict(state)
    assert verified_export_report_receipts(restored) == []
    assert unverified_local_artifact_links(f"[Excel]({output})", restored) == [str(output)]
