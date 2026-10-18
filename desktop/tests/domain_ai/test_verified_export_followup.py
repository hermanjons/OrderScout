"""Actual approved report receipts remain usable without rereading the source."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from AI.processors import file_workspace, observation_artifacts, task_runtime
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.observation_context import (
    generic_observation_context, verified_export_report_answer, verified_export_report_receipts,
)
from AI.processors.response_verifier import project_fallback_response, verify_response_projection
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.turn_service import run_interpreted_turn
from Core.processors.report_artifacts import ReportSnapshot, verify_report_snapshot_xlsx
from Feedback.processors.pipeline import Result


def _followup():
    return {"mode": "inspect", "domain": "files", "intent_kind": "data_read", "valid": True,
            "requested_fields": ["artifact", "item_sales_rows", "currency", "count", "action_result"],
            "requires_clarification": False, "operation_policy": "existing_observations_only",
            "semantic_contract": {"information_source": "local_business_data"}}


@pytest.mark.parametrize('authorized_repair', [True, False])
def test_pending_report_interpretation_repair_is_bounded_and_cannot_expand_operation_authority(approved_report, authorized_repair):
    _, _, state = approved_report
    original = state.to_dict()
    bad = _actual_glm_files_followup_contract()
    bad['valid'] = True
    bad['requested_fields'] = ['artifact', 'amount', 'currency', 'count']
    repaired = _actual_glm_files_followup_contract()
    repaired['requested_fields'] = ['artifact', 'scope', 'count', 'currency']
    if not authorized_repair:
        repaired.update(mode='act', intent_kind='action', operation_policy='allow_new_operations')
    calls = []
    def model(prompt):
        calls.append(prompt)
        assert prompt.startswith('Historical report interpretation repair')
        assert len(calls) == 1
        return json.dumps(repaired)
    def forbidden(*args, **kwargs):
        raise AssertionError('Historical interpretation repair cannot invoke operations or conversation fallback')
    result = run_interpreted_turn('Onay bekleyen raporun kaynak dosyası, sütunları ve dövizleri neler?',
        interpretation_result=Result.ok(data=bad), client=model, history=[], db_name='unused.db',
        task_runner=forbidden, conversation_runner=forbidden,
        observation_reader=task_runtime.run_existing_observation_read_turn,
        capability_reader=forbidden, policy_context_builder=forbidden, session_state=state)
    assert len(calls) == 1
    assert result.success is authorized_repair, result.data
    assert result.data['tool_names'] == []
    returned = result.data.get('state') or result.data['session_state']
    for key in ('pending_actions', 'action_history', 'completed_steps'):
        assert returned[key] == original[key]


def _actual_glm_followup_contract():
    # Public JSON authored by the real candidate-2 GLM followup. There was no
    # action_result field and the entity namespace was explicitly "none".
    return {
        "mode": "inspect", "domain": "general", "intent_kind": "data_read", "request_shape": "record_detail",
        "entity": "none", "metric": "detail",
        "objective": "Onayli raporun gercekten olusturuldugunu, kaynak dosyayi, birim/doviz korunumunu ve bos discount alanlarinin dogrulanmasini kayitli kanitlarla acikla",
        "reason": "Kullanici gecmiste olusturulan ve dogrulanan raporun kaynagini ve dogrulama yontemini soruyor; bu mevcut verified_artifact_receipts ve report preparation kayitlarindan inspect + existing_observations_only ile cevaplanabilir, yeni okuma veya yeniden uretim gerekmez",
        "calculation_grouping": "none", "comparison_policy": "not_requested", "status_codes": [],
        "requires_clarification": False, "missing_input": "none", "population_basis": "entity_records",
        "operation_policy": "existing_observations_only", "information_source": "local_business_data",
        "freshness": "unspecified", "period": "unspecified", "status_scope": "unspecified", "record_scope": "unspecified",
        "requested_fields": ["artifact", "scope", "count", "currency", "item_sales_rows"], "direct_output_fields": [],
        "explanation_topics": ["verification", "data_source"], "identifier_display": "auto",
        "metric_population": None, "grouped_projection": None, "status_codes_note": None,
    }


def _actual_glm_files_followup_contract():
    # Exact public candidate-3 interpretation: files has no domain-specific
    # semantic projection contract, while the historical policy is explicit.
    return {
        "mode": "inspect", "domain": "files",
        "objective": "Onayli raporun gercekten olusturuldugunu, kaynak dosyayi, birim/doviz korunumunu ve bos discount alanlarinin dogrulanmasini kayitli kanitlarla acikla",
        "calculation_grouping": "none", "comparison_policy": "not_requested", "status_codes": [],
        "requires_clarification": False, "missing_input": "none", "population_basis": "entity_records",
        "intent_kind": "data_read", "request_shape": "record_detail", "entity": "none", "metric": "detail",
        "information_source": "local_business_data", "operation_policy": "existing_observations_only",
        "freshness": "unspecified", "period": "unspecified", "record_scope": "unspecified", "status_scope": "unspecified",
        "requested_fields": ["artifact", "scope", "count", "item_sales_rows", "currency"], "direct_output_fields": [],
        "explanation_topics": ["verification"],
        "reason": "Kullanici gecmis teslimin kaynagini ve dogrulamasini soruyor; verified_artifact_receipts ve verified_report_preparations kayitlari inspect+existing_observations_only ile cevaplanabilir. Kayit dosyanin olusturuldugunu ve bagimsiz read-back ile dogrulandigini kanitlar; su an fiziksel varlik yeni okumasi olmadigi icin iddia edilmez.",
        "clarification": "",
    }


@pytest.fixture
def approved_report(tmp_path, monkeypatch):
    monkeypatch.setattr(file_workspace, "ATTACHMENTS_ROOT", tmp_path / "imports")
    monkeypatch.setattr(observation_artifacts, "OBSERVATION_ARTIFACTS_ROOT", tmp_path / "observations")
    records = [{"sku": "MUG", "quantity": 4, "unit": "adet", "revenue": 1200.5, "currency": "TRY", "discount": None},
               {"sku": "FILTER", "quantity": 3, "unit": "adet", "revenue": 90.25, "currency": "USD", "discount": None},
               {"sku": "EMPTY", "quantity": 0, "unit": "adet", "revenue": 0, "currency": "TRY", "discount": None}]
    selected = tmp_path / "pilot-sales.json"
    selected.write_text(json.dumps(records), encoding="utf-8")
    previous = AgentSessionState(goal="Import chosen sales", active_domain="general")
    metadata = file_workspace.register_attachment(selected, previous.session_id)
    previous.active_entities["file_workspace"] = {"session_id": previous.session_id, "attachments": [metadata]}
    output = tmp_path / "approved-sales.xlsx"
    plan = {"steps": [
        {"id": "read", "operation_id": "files.read", "arguments": {"attachment_id": metadata["attachment_id"]},
         "depends_on": [], "objective": "Read the chosen sales JSON", "expected_evidence": ["rows", "source_hash"]},
        {"id": "report", "operation_id": "reports.build_snapshot", "arguments": {
            "title": "Pilot Sales Report", "sources": [{"source_id": "sales", "source_step_id": "read", "operation_id": "files.read",
                "result": {"$from_step": "read", "path": "tool_result"}}],
            "sheets": [{"name": "Sales", "source_id": "sales", "rows_path": "rows", "columns": [
                {"key": key, "label": key.title(), "source_path": key, "data_type": kind}
                for key, kind in [("sku", "string"), ("quantity", "integer"), ("unit", "string"),
                                  ("revenue", "number"), ("currency", "string"), ("discount", "number")]]}]},
         "depends_on": ["read"], "objective": "Copy the source fields exactly", "expected_evidence": ["report_snapshot"]},
        {"id": "prepare", "operation_id": "reports.xlsx.prepare", "arguments": {
            "report_snapshot": {"$from_step": "report", "path": "tool_result.report_snapshot"}, "output_path": str(output)},
         "depends_on": ["report"], "objective": "Prepare the exact Excel report", "expected_evidence": ["action", "snapshot_id"]},
    ]}
    def planner(prompt):
        if prompt.startswith("OrderScout semantic action verifier"):
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                               "unwanted_effect": False, "reason": "User requested the source-preserving Excel report"})
        if prompt.startswith("GoalPlan observation"):
            return json.dumps({"decision": "continue", "reason": "Complete the requested report graph"})
        return json.dumps(plan)
    started = task_runtime.run_agent_task(
        "Read the chosen sales file and prepare an Excel report with exact native quantities, currencies and null cells.",
        domain="general", session_state=previous, planner_client=planner, persist=False,
        turn_interpretation={"mode": "act", "domain": "general", "intent_kind": "action", "valid": True,
                             "requested_fields": ["artifact"], "requires_clarification": False},
    )
    assert started.success, started.message
    prepared = AgentSessionState.from_dict(started.data["state"])
    assert prepared.status == "pending_approval" and not output.exists()
    assert verified_export_report_answer(prepared) == ""
    snapshot = prepared.completed_steps[1].result_data["tool_result"]["report_snapshot"]
    approved = task_runtime.resume_agent_task_with_approval(
        prepared.to_dict(), approved_by="exact-export-test", persist=False,
        idempotency_key="actual-approved-report", audit_path=str(tmp_path / "audit.jsonl"),
    )
    assert approved.success, approved.message
    state = AgentSessionState.from_dict(approved.data["state"])
    assert verify_report_snapshot_xlsx(snapshot, output)["verified"] is True
    return state, output, prepared


def test_actual_current_approval_followup_describes_native_values_and_nulls_without_any_new_operation(approved_report):
    state, output, _ = approved_report
    receipt = verified_export_report_receipts(state)
    assert len(receipt) == 1 and receipt[0]["filename"] == output.name
    assert receipt[0]["current_file_existence_verified"] is False
    assert receipt[0]["status_basis"] == "recorded_independent_readback"
    assert receipt[0]["output_path"] == str(output)
    completed = [step.to_dict() for step in state.completed_steps]
    actions = deepcopy(state.action_history)
    with patch("AI.processors.tools.available_tools", side_effect=AssertionError("followup exposed operations")):
        result = task_runtime.run_existing_observation_read_turn(
            "Dosya oluşturuldu mu, hangi kaynaktan geldi ve boş hücreler nasıl korundu?",
            interpretation=_followup(), session_state=state,
        )
    assert result.success, result.message
    answer = result.data["answer"]
    for fact in (output.name, "pilot-sales.json", "3 veri satırı", "Revenue", "TRY, USD", "adet", "Discount: 3 boş hücre"):
        assert fact in answer
    assert "sıfıra çevrilmedi" in answer and "şu anki varlığı yeniden kontrol edilmedi" in answer
    assert result.data["model_invoked"] is False and result.data["tool_calls"] == []
    assert result.data["state"]["completed_steps"] == completed
    assert result.data["state"]["action_history"] == actions
    assert str(output.parent) not in answer


@pytest.mark.parametrize("model_contract", [_actual_glm_followup_contract, _actual_glm_files_followup_contract])
@pytest.mark.parametrize("message", [
    "Ek dosyadan istediğim rapor gerçekten oluşturuldu mu? Hangi kaynak dosyadan geldiğini, kayıtların birim ve dövizlerinin korunduğunu ve boş discount alanlarının sonucunu nasıl doğruladığını söyle.",
    "Explain the recorded delivery and how the selected source values were preserved.",
])
def test_legacy_model_json_survives_explicit_compatibility_dispatch_without_keyword_routing(approved_report, message, model_contract):
    state, output, _ = approved_report
    original_steps = [step.to_dict() for step in state.completed_steps]
    original_actions = deepcopy(state.action_history)
    calls = []

    def actual_model_response(prompt):
        calls.append(prompt)
        assert len(calls) == 1, "Delivery explanation must not invoke a new planner or response model"
        return json.dumps(model_contract())

    with patch("AI.processors.tools.available_tools", side_effect=AssertionError("delivery dispatched a tool")):
        # This recorded JSON belongs to the retained legacy interpretation API.
        # The default conversation entrypoints now use the model-owned loop;
        # their prose/receipt parity is covered by test_turn_entrypoint_parity.
        interpretation = task_runtime.interpret_agent_turn(message, planner_client=actual_model_response,
                                                          history=[], session_state=state)
        def forbidden(*args, **kwargs):
            raise AssertionError("Legacy historical dispatch must not access a new source")
        response = run_interpreted_turn(message, interpretation_result=interpretation, client=forbidden,
            history=[], db_name="unused.sqlite3", session_state=state,
            task_runner=forbidden, observation_reader=task_runtime.run_existing_observation_read_turn,
            conversation_runner=forbidden, capability_reader=forbidden, policy_context_builder=forbidden)
        result = {**response.data, "success": response.success, "tools": response.data.get("tool_names", []),
                  "session_state": response.data.get("state") or response.data.get("session_state")}
    assert result["success"], result
    interpretation = dict(interpretation.data)
    assert interpretation["operation_policy"] == "existing_observations_only"
    assert interpretation["domain"] == model_contract()["domain"] and interpretation["intent_kind"] == "data_read"
    assert interpretation["explanation_topics"] == model_contract()["explanation_topics"]
    if interpretation["domain"] == "files":
        assert interpretation["semantic_contract"] == {}
    assert "unrequested_existing_observations_only_to_allow_new_operations" not in interpretation["semantic_corrections"]
    assert result["decision_path"] == "typed_existing_observation_verified_projection"
    assert result["tools"] == [] and len(calls) == 1
    for fact in (output.name, "pilot-sales.json", "3 veri satırı", "TRY, USD", "adet", "Discount: 3 boş hücre"):
        assert fact in result["answer"]
    assert "şu anki varlığı yeniden kontrol edilmedi" in result["answer"]
    assert result["session_state"]["completed_steps"] == original_steps
    assert result["session_state"]["action_history"] == original_actions


@pytest.mark.parametrize("intent_kind", ["data_read", "correction"])
def test_empty_contract_and_missing_receipt_historical_dispatch_fails_closed_without_any_new_operation(intent_kind):
    state = AgentSessionState(goal="Previous turn", active_domain="files", status="complete")
    interpretation = {**_actual_glm_files_followup_contract(), "valid": True,
                      "semantic_contract": {}, "intent_kind": intent_kind}

    def unexpected(*args, **kwargs):
        raise AssertionError("Historical policy escaped into a new operation or model")

    with patch("AI.processors.tools.available_tools", side_effect=unexpected):
        result = run_interpreted_turn(
            "Explain the previous delivery.", interpretation_result=Result.ok("Typed historical request", data=interpretation),
            client=unexpected, history=[], db_name="unused.sqlite3", session_state=state,
            task_runner=unexpected, observation_reader=task_runtime.run_existing_observation_read_turn,
            conversation_runner=unexpected, capability_reader=unexpected, policy_context_builder=unexpected,
        )
    assert result is not None and not result.success
    assert result.data["decision_path"] == "typed_existing_observation_projection_failed_closed"
    assert result.data["tool_names"] == []
    assert result.data["session_state"]["completed_steps"] == []
    assert result.data["session_state"]["action_history"] == []


@pytest.mark.parametrize("proof", ["prepare_only", "changed_source", "changed_execute_hash"])
def test_missing_delivery_proof_keeps_historical_permission_and_fails_closed_without_new_operations(approved_report, proof):
    state, _, prepared = approved_report
    if proof == "prepare_only":
        state = prepared
    elif proof == "changed_source":
        state.completed_steps[0].result_data["tool_result"]["rows"][0]["revenue"] = 999
    else:
        executed = next(row["data"] for row in state.last_tool_results if row["tool_names"] == ["execute_approved_operation"])
        executed["verify"]["content_hash"] = "0" * 64
    result = task_runtime.interpret_agent_turn(
        "Explain the recorded delivery.", planner_client=lambda _: json.dumps(_actual_glm_followup_contract()),
        history=[], session_state=state,
    )
    assert result.success, result.message
    assert result.data["operation_policy"] == "existing_observations_only"
    assert "unrequested_existing_observations_only_to_allow_new_operations" not in result.data["semantic_corrections"]
    with patch("AI.processors.tools.available_tools", side_effect=AssertionError("Missing proof granted new tools")):
        closed = task_runtime.run_existing_observation_read_turn(
            "Explain the recorded delivery.", interpretation=result.data, session_state=state,
        )
    if proof == 'prepare_only':
        assert closed.success
        assert 'dosyanın oluşturulduğunu kanıtlamaz' in closed.data['answer']
        assert 'oluşturma işlemi henüz çalıştırılmadı' in closed.data['answer']
        assert closed.data['state']['pending_actions'] == state.to_dict()['pending_actions']
        assert closed.data['state']['action_history'] == state.to_dict()['action_history']
        assert closed.data['tool_names'] == []
    else:
        assert not closed.success
        assert closed.data["decision_path"] == "typed_existing_observation_projection_failed_closed"
    assert closed.data["model_invoked"] is False
    assert verified_export_report_answer(state) == ""


def test_recorded_export_is_truthful_after_current_file_is_removed(approved_report):
    state, output, _ = approved_report
    output.unlink()
    assert not output.exists()
    result = task_runtime.run_existing_observation_read_turn("Önceki raporu açıkla.", interpretation=_followup(), session_state=state)
    assert result.success
    assert "kaydedilen doğrulama sırasında" in result.data["answer"]
    assert "şu anki varlığı yeniden kontrol edilmedi" in result.data["answer"]


@pytest.mark.parametrize("mutation", ["source", "report_cell", "approved_cell", "verify_hash", "bad_hash_type", "headers", "audit", "history", "time", "missing_result", "bad_type"])
def test_changed_or_incomplete_export_proof_fails_closed(approved_report, mutation):
    state, _, _ = approved_report
    executed = next(row["data"] for row in state.last_tool_results if row["tool_names"] == ["execute_approved_operation"])
    if mutation == "source":
        state.completed_steps[0].result_data["tool_result"]["rows"][0]["revenue"] = 9
    elif mutation == "report_cell":
        state.completed_steps[1].result_data["tool_result"]["report_snapshot"]["sheets"][0]["rows"][0][3] = 9
    elif mutation == "approved_cell":
        executed["audit"]["action"]["arguments"]["payload"]["report_snapshot"]["sheets"][0]["rows"][0][3] = 9
    elif mutation == "verify_hash":
        executed["verify"]["content_hash"] = "0" * 64
    elif mutation == "bad_hash_type":
        executed["verify"]["content_hash"] = ["malformed"]
    elif mutation == "headers":
        executed["verify"]["sheets"][0]["headers"][0] = "Invented"
    elif mutation == "audit":
        executed["audit"]["execute_success"] = False
    elif mutation == "history":
        state.action_history.clear()
    elif mutation == "time":
        executed["audit"]["timestamp"] = "2026-10-11T12:00:00"
    elif mutation == "missing_result":
        executed.pop("result")
    else:
        executed["verify"] = ["not typed proof"]
    assert verified_export_report_answer(state) == ""
    result = task_runtime.run_existing_observation_read_turn("Önceki raporu açıkla.", interpretation=_followup(), session_state=state)
    assert not result.success and result.data["tool_names"] == []
    assert result.data["response_verification"]["response_verification"]["reason_codes"] == ["verified_export_receipt_missing"]


def test_prepare_only_has_no_export_receipt_and_cannot_claim_a_created_file(approved_report):
    _, _, prepared = approved_report
    assert generic_observation_context(prepared)["verified_artifact_receipts"] == []
    assert verified_export_report_answer(prepared) == ""


@pytest.mark.parametrize("corrupt", [False, True])
def test_an_older_export_receipt_cannot_describe_a_new_unexported_or_corrupt_report(approved_report, corrupt):
    state, _, _ = approved_report
    raw = deepcopy(state.completed_steps[1].result_data["tool_result"]["report_snapshot"])
    raw["title"] = "A newer report"
    raw.pop("content_hash")
    raw.pop("snapshot_id")
    raw = ReportSnapshot.from_dict(raw).to_dict()
    if corrupt:
        raw["sheets"][0]["rows"][0][3] = 999
    state.completed_steps.append(AgentTaskStep(index=4, step_id="new_report", prompt="Build newer report", status="completed",
        verification_status="observed", tool_names=["reports.build_snapshot"], result_data={"tool_result": {"report_snapshot": raw}}))
    assert verified_export_report_answer(state) == ""
    result = task_runtime.run_existing_observation_read_turn("Rapor oluşturuldu mu?", interpretation=_followup(), session_state=state)
    assert not result.success and result.data["tool_names"] == []


def test_response_projection_rejects_omitted_or_invented_file_facts(approved_report):
    state, _, _ = approved_report
    state.active_entities["turn_interpretation"] = _followup()
    answer = project_fallback_response(state, "unverified text")
    assert verify_response_projection(answer, state).success
    for candidate in ("Dosya şu anda diskte mevcut.", answer.replace("TRY, USD", "TRY"), answer + "\nGelir toplamı 999 TL."):
        rejected = verify_response_projection(candidate, state)
        assert not rejected.success
        assert rejected.data["response_verification"]["reason_codes"] == ["verified_export_projection_mismatch"]


def test_actual_glm_attachment_diagnostic_approved_state_supports_no_operation_followup():
    diagnostic = Path(__file__).resolve().parents[3] / "output/agentic-2026-10-11/attachment-glm-diagnostic.json"
    if not diagnostic.exists():
        pytest.skip("Live diagnostic artifact is local acceptance evidence")
    saved = json.loads(diagnostic.read_text(encoding="utf-8"))
    state = AgentSessionState.from_dict(saved["turns"][2]["raw_turn_data"]["state"])
    with patch("AI.processors.tools.available_tools", side_effect=AssertionError("live followup reread source")):
        result = task_runtime.run_existing_observation_read_turn(
            "Gerçekten oluşturulan raporu, kaynağını ve boş hücreleri açıkla.", interpretation=_followup(), session_state=state,
        )
    assert result.success, result.message
    answer = result.data["answer"]
    for fact in ("Pilot Sales Report", "pilot-sales.json", "3 veri satırı", "Revenue", "TRY, USD", "adet", "Discount: 3 boş hücre"):
        assert fact in answer
    assert "amount" not in answer and result.data["tool_calls"] == []
