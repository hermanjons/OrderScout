from copy import deepcopy

import pytest

from AI.processors import analysis_operations, observation_artifacts, report_builder, tabular_analysis, tools
from AI.processors.observation_projection import observed_source_payload, source_projection_hash
from AI.processors.session_state import AgentSessionState, AgentTaskStep, Observation


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")


def _completed(state, operation, result, *, observed_at="2026-10-07T08:15:00+03:00"):
    observation = Observation.create(domain=operation.split(".")[0], operation_name=operation, success=True,
                                     source=operation, observed_at=observed_at, facts={"context_kind": "read_scope"})
    state.observations.append(observation)
    step = AgentTaskStep(index=1, step_id="source", prompt="Observed canonical source", operation_domain=observation.domain,
                         status="completed", tool_names=[operation], observation_ids=[observation.observation_id],
                         verification_status="observed", result_data={"tool_result": deepcopy(result)})
    state.completed_steps.append(step)
    state.last_tool_results.append({"step": 1, "tool_names": [operation], "data": deepcopy(result)})


def _historical(result, operation="orders.summary"):
    state = AgentSessionState(goal="Keep the completed observation", active_domain="general")
    _completed(state, operation, result)
    registry = tools.available_tools()
    ref = observation_artifacts.publish_completed_observation(state, "source", registry=registry)
    read = observation_artifacts.read_observation_artifact(
        artifact_id=ref["artifact_id"], session_id=state.session_id,
        authorized_capabilities=state.active_entities["observation_artifacts"]["capabilities"])
    assert read.success, read.message
    return read.data, state


def _sales(account=101, environment="stage", period="last_7_days", amount=100):
    return {"tool": "orders.summary", "estimated_revenue": amount, "currency": "TRY", "total_orders": 2,
            "account_scopes": [{"api_account_id": account, "environment": environment}], "period": period,
            "data_coverage": {"status": "partial"}}


def _calculate(left, right, *, right_operation="artifacts.read", field="estimated_revenue"):
    return analysis_operations.calculate_observations(sources=[
        {"source_id": "left", "source_step_id": "left_read", "operation_id": "artifacts.read", "result": left},
        {"source_id": "right", "source_step_id": "right_read", "operation_id": right_operation, "result": right}],
        calculations=[{"calculation_id": "difference", "operator": "subtract", "operands": [
            {"source_id": "left", "path": "result." + field},
            {"source_id": "right", "path": ("result." if right_operation == "artifacts.read" else "") + field}]}])


@pytest.mark.parametrize("difference", ["account", "environment"])
@pytest.mark.parametrize("fresh_second", [False, True])
def test_historical_original_store_scope_must_match_other_same_domain_operands(store, difference, fresh_second):
    left, _ = _historical(_sales())
    raw_right = _sales(account=102 if difference == "account" else 101,
                       environment="prod" if difference == "environment" else "stage")
    right = raw_right if fresh_second else _historical(raw_right)[0]
    result = _calculate(left, right, right_operation="orders.summary" if fresh_second else "artifacts.read")
    assert not result.success and result.data["reason"] == "analysis_source_entity_scope_mismatch"


def test_historical_scope_period_unit_and_earliest_time_survive_verified_arithmetic(store):
    left, _ = _historical(_sales(amount=300))
    right, _ = _historical(_sales(period="previous_7_days", amount=100))
    result = _calculate(left, right)
    assert result.success, result.data
    proof = result.data["verified_calculations"][0]
    assert proof["result_value"] == 200 and proof["unit"] == "TRY"
    receipts = proof["source_receipts"]
    assert receipts[0]["scope"] == {"account_scopes": [{"api_account_id": 101, "environment": "stage"}]}
    assert receipts[1]["period"] == {"period": "previous_7_days"}
    assert receipts[0]["coverage"] == {"status": "partial"}
    provenance = receipts[0]["source_provenance"]
    assert provenance["fresh_read"] is False and provenance["freshness"] == "historical_snapshot"
    assert provenance["observed_at"] == "2026-10-07T08:15:00+03:00"
    assert provenance["original_operation_id"] == "orders.summary"
    assert receipts[0]["source_result_hash"] == source_projection_hash(left)
    assert result.data["evidence_hash"] == source_projection_hash({k: v for k, v in result.data.items() if k != "evidence_hash"})


def test_original_order_count_does_not_turn_into_generic_artifact_record_unit(store):
    raw = {"tool": "orders.query", "count": 4, "account_scopes": [{"api_account_id": 101, "environment": "stage"}]}
    left, _ = _historical(raw, "orders.query")
    right, _ = _historical({**raw, "count": 2}, "orders.query")
    result = _calculate(left, right, field="count")
    assert result.success and result.data["verified_calculations"][0]["unit"] == "order"


def test_verified_derived_calculation_retains_original_account_scope_in_another_analysis(store):
    def derived(account):
        left, _ = _historical(_sales(account=account, amount=300))
        right, _ = _historical(_sales(account=account, amount=100))
        result = _calculate(left, right)
        assert result.success
        return result.data
    left, right = derived(101), derived(102)
    result = analysis_operations.calculate_observations(sources=[
        {"source_id": "left", "source_step_id": "left", "operation_id": "analysis.calculate", "result": left},
        {"source_id": "right", "source_step_id": "right", "operation_id": "analysis.calculate", "result": right}],
        calculations=[{"calculation_id": "derived_difference", "operator": "subtract", "operands": [
            {"source_id": "left", "path": "verified_calculations.0.result_value"},
            {"source_id": "right", "path": "verified_calculations.0.result_value"}]}])
    assert not result.success and result.data["reason"] == "analysis_source_entity_scope_mismatch"


def test_rearchived_observation_keeps_original_time_instead_of_latest_artifact_read_time(store):
    original, previous = _historical(_sales())
    next_state = AgentSessionState(goal="Read the prior snapshot", active_domain="general")
    observation_artifacts.transfer_observation_capabilities(previous, next_state)
    _completed(next_state, "artifacts.read", original, observed_at="2026-10-11T12:00:00+03:00")
    ref = observation_artifacts.publish_completed_observation(next_state, "source")
    archived = observation_artifacts.read_observation_artifact(
        artifact_id=ref["artifact_id"], session_id=next_state.session_id,
        authorized_capabilities=next_state.active_entities["observation_artifacts"]["capabilities"])
    assert archived.success
    producer, payload, provenance = observed_source_payload(archived.data, "artifacts.read")
    assert producer == "orders.summary" and payload == _sales()
    assert provenance["observed_at"] == "2026-10-07T08:15:00+03:00"
    assert len(provenance["artifact_chain"]) == 2
    assert all(entry["observed_at"] == "2026-10-07T08:15:00+03:00" for entry in provenance["artifact_chain"])
    assert archived.data["read_at"] != provenance["observed_at"]


@pytest.mark.parametrize("field,value", [("fresh_read", True), ("historical_observation", False),
                                         ("observed_at", "2026-10-11T12:00:00+03:00"), ("verified", False)])
def test_source_projection_rejects_changed_historical_metadata(store, field, value):
    historic, _ = _historical(_sales())
    historic[field] = value
    with pytest.raises(ValueError, match="historical_receipt_invalid"):
        observed_source_payload(historic, "artifacts.read")


def test_table_from_historical_source_keeps_partial_coverage_and_export_inherits_original_provenance(store, tmp_path):
    from AI.processors.operation_runtime import execute_approved_operation
    from Core.processors.report_artifacts import verify_report_snapshot_xlsx
    from openpyxl import load_workbook
    raw = {"tool": "files.read", "rows": [{"currency": "TRY", "amount": 10.5}, {"currency": "TRY", "amount": None}],
           "data_coverage": {"status": "partial"}, "source_hash": "a" * 64}
    historical, _ = _historical(raw, "files.read")
    source = {"source_id": "historic", "source_step_id": "historical_read", "operation_id": "artifacts.read", "result": historical}
    analyzed = tabular_analysis.analyze_observation_table(
        sources=[source], source_id="historic", rows_path="result.rows", group_by=["currency"],
        measures=[{"name": "total", "operator": "sum", "path": "amount", "unit_path": "currency"}])
    assert analyzed.success, analyzed.data
    assert analyzed.data["data_coverage"] == {"status": "partial"}
    metric = analyzed.data["rows"][0]["metrics"]["total"]
    assert metric["value"] == 10.5 and metric["null_count"] == 1
    derived = {"source_id": "calculated", "source_step_id": "table", "operation_id": "analysis.table", "result": analyzed.data}
    snapshot = report_builder.build_observation_report_snapshot(title="Historical calculated report", sources=[derived], sheets=[
        {"name": "Calculated", "source_id": "calculated", "rows_path": "rows", "columns": [
            {"key": "total", "label": "Total", "source_path": "metrics.total.value", "data_type": "number"}]}])
    receipt = snapshot.metadata["source_receipts"][0]
    assert receipt["coverage"] == {"status": "partial"}
    assert receipt["source_is_fresh_read"] is False
    assert receipt["source_observed_at"] == "2026-10-07T08:15:00+03:00"
    assert receipt["source_freshness"] == "derived_from_historical_snapshot"
    assert receipt["original_operation_id"] == "files.read"
    proof = dict(zip((column.key for column in snapshot.sheets[-1].columns), snapshot.sheets[-1].rows[0]))
    assert proof["source_observed_at"] == receipt["source_observed_at"]
    path = tmp_path / "historical-table.xlsx"
    prepared = tools.reports_prepare_xlsx(report_snapshot=snapshot.to_dict(), output_path=str(path))
    assert prepared.success and prepared.data["valid"]
    assert not path.exists()
    exported = execute_approved_operation(prepared.data["action"], approved_by="historical-table-proof-test",
                                         audit_path=str(tmp_path / "audit.jsonl"), idempotency_key="historical-derived-proof")
    assert exported.success and verify_report_snapshot_xlsx(snapshot, path)["verified"]
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook["Kaynak Kanıtı"].values)
        written = dict(zip(rows[0], rows[1]))
        assert written["Asıl gözlem zamanı"] == "2026-10-07T08:15:00+03:00"
        assert written["Kaynak güncelliği"] == "derived_from_historical_snapshot"
        assert written["Asıl kaynak operasyonu"] == "files.read"
        assert written["Yeni kaynak sorgusu"] is False
    finally:
        workbook.close()
