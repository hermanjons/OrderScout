"""Actual pending instructions survive typed read-only inquiries and exact approval."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors import observation_context, task_runtime, tools, workflow_store
from AI.processors.business_acceptance_fixtures import WORKFLOW_ACCEPTANCE_SPEC, workflow_save_prompt
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.response_verifier import verify_response_projection
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.turn_service import run_interpreted_turn
from Feedback.processors.pipeline import Result


def _captured():
    return json.loads((Path(__file__).parent / "fixtures" / "schedule_glm_pending_interpretation.json").read_text(encoding="utf-8"))


def test_actual_file_report_inquiry_keeps_model_authored_historical_read():
    captured = json.loads((Path(__file__).parent / "fixtures" /
        "attachment_glm_pending_interpretation.json").read_text(encoding="utf-8"))
    interpreted = task_runtime.interpret_agent_turn(captured["prompt"],
        planner_client=lambda _: json.dumps(captured["response"]))
    assert interpreted.success, interpreted.message
    assert interpreted.data["mode"] == "inspect"
    assert interpreted.data["domain"] == "files"
    assert interpreted.data["intent_kind"] == "data_read"
    assert interpreted.data["operation_policy"] == "existing_observations_only"
    assert not any("future_coordination" in reason for reason in interpreted.data["semantic_corrections"])


@pytest.mark.parametrize("mode", ["chat", "explain"])
def test_nonbusiness_turn_keeps_visible_card_and_exact_current_sqlite_approval(prepared_workflow, monkeypatch, mode):
    from types import SimpleNamespace
    from AI.views.chat_tab import AITab
    state = prepared_workflow
    def unexpected(*args, **kwargs):
        raise AssertionError("A conversation exposed operations or execution")
    original_registry = tools.available_tools
    monkeypatch.setattr(tools, "available_tools", unexpected)
    result = task_runtime.run_model_conversation_turn("Bu teklif hakkında konuşalım", mode=mode,
        objective="Discuss the current proposal", chat_client=lambda _: "Mevcut teklif onay bekliyor; henüz uygulanmadı.",
        session_state=state, operation_policy="existing_observations_only")
    assert result.success and result.data["tool_names"] == []
    assert result.data["state"] == result.data["session_state"]
    preserved = result.data["session_state"]
    for key in ("session_id", "goal", "status", "pending_actions", "active_pending_action_id", "completed_steps", "action_history"):
        assert preserved[key] == state.to_dict()[key]
    visible = {}
    adapter = SimpleNamespace(_tool_names_from_result_data=lambda _: [],
        _set_agent_state=lambda **values: visible.update(values))
    AITab._update_agent_state_from_result_data(adapter, {"session_state": preserved})
    assert visible["status"] == "approval_required"
    assert visible["pending_action"] == state.active_pending_action()
    monkeypatch.setattr(tools, "available_tools", original_registry)
    approved = run_contextual_conversation_turn("Onaylıyorum.", client=unexpected, provider_code="openrouter",
        model_name="z-ai/glm-5.3-flash", db_name="unused", history=[], session_state=preserved,
        persist=False, allow_approval_execute=True)
    assert approved["success"], approved.get("answer")
    execute = next(row for row in approved["session_state"]["action_history"] if row.get("phase") == "execute")
    assert execute["verify"]["verified_by"] == "workflow_exact_revision_sqlite_readback"
    assert execute["verify"]["verified"] is True


@pytest.fixture
def prepared_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_store, "AI_DOMAIN_ROOT", tmp_path / "workflows")
    goal = workflow_save_prompt()
    plan = {"steps": [{"id": "prepare", "operation_id": "workflows.save.prepare", "arguments": {
        "spec": deepcopy(WORKFLOW_ACCEPTANCE_SPEC), "workflow_id": "actual-pending-read"},
        "depends_on": [], "objective": "Prepare the exact reviewed instruction package", "expected_evidence": ["action"]}]}
    def planner(prompt):
        if prompt.startswith("OrderScout semantic action verifier"):
            return json.dumps({"verdict": "allow", "objective_aligned": True, "domain_aligned": True,
                "unwanted_effect": False, "reason": "Only this exact reviewed package is prepared",
                "configuration_schema_reviews": [{"argument_path": "/spec/parameter_schema",
                    "requested_schema_json": json.dumps(WORKFLOW_ACCEPTANCE_SPEC["parameter_schema"]),
                    "requirement_quotes": [goal[:950]]}]})
        return json.dumps(plan)
    result = task_runtime.run_agent_task(goal, domain="general", planner_client=planner, persist=False,
        db_name=str(tmp_path / "business.sqlite3"), turn_interpretation={"valid": True, "mode": "act",
            "domain": "general", "intent_kind": "action", "requested_fields": ["action_result"],
            "operation_policy": "allow_new_operations", "requires_clarification": False})
    assert result.success, result.message
    state = AgentSessionState.from_dict(result.data["state"])
    assert state.status == "pending_approval" and len(state.pending_actions) == 1
    assert not workflow_store.workflow_store_path().exists()
    return state


def _assert_pending_read(result, state):
    payload = result["session_state"] if isinstance(result, dict) else result.data["session_state"]
    assert payload["session_id"] == state.session_id
    assert payload["goal"] == state.goal and payload["active_domain"] == state.active_domain
    assert payload["active_entities"]["turn_interpretation"] == state.active_entities["turn_interpretation"]
    assert payload["status"] == "pending_approval"
    assert payload["active_pending_action_id"] == state.active_pending_action_id
    assert payload["pending_actions"] == state.to_dict()["pending_actions"]
    assert payload["completed_steps"] == state.to_dict()["completed_steps"]
    assert payload["action_history"] == state.action_history
    answer = result["answer"] if isinstance(result, dict) else result.data["answer"]
    assert WORKFLOW_ACCEPTANCE_SPEC["instructions"] in answer
    assert WORKFLOW_ACCEPTANCE_SPEC["objective_template"] in answer
    assert "report_title: metin; zorunlu; en çok karakter: 80" in answer
    assert "Başka parametre kabul edilmez." in answer
    assert "Her çalıştırmada güncel kaynak gerekir: evet." in answer
    assert "Her işlem için güncel onay gerekir: evet." in answer
    assert "Bu teklif henüz uygulanmadı" in answer
    return payload


@pytest.mark.parametrize("adapter", ["headless", "source_ui"])
@pytest.mark.parametrize("query_variant", ["captured", "quoted_approval", "quoted_cancel", "future_instruction"])
def test_actual_glm_pending_json_keeps_exact_proposal_without_registry_reads_then_approves_current_revision(
        prepared_workflow, tmp_path, monkeypatch, adapter, query_variant):
    state = prepared_workflow
    captured = _captured()
    suffixes = {
        "captured": "",
        "quoted_approval": ' Metindeki “onayla ve çalıştır” alıntısının sınırlarını da açıkla?',
        "quoted_cancel": ' Metindeki “bu işlemi iptal et” alıntısının sınırlarını da açıkla?',
        "future_instruction": ' Gelecekteki talimatın alıntısı “hazırlanan işlemi çalıştır”; şu anki teklifin kaydını açıkla.',
    }
    message = captured["prompt"] + suffixes[query_variant]
    assert captured["requested_model"] == captured["actual_model"] == "z-ai/glm-5.3-flash"
    assert captured["fallback_used"] is False
    calls = []
    def client(prompt):
        calls.append(prompt)
        assert len(calls) == 1, "Pending inquiry must not dispatch a planner or response model"
        assert '"verified_pending_action"' in prompt
        assert WORKFLOW_ACCEPTANCE_SPEC["objective_template"] in prompt
        return json.dumps(captured["response"], ensure_ascii=False)
    def unexpected(*args, **kwargs):
        raise AssertionError("Read-only pending inquiry exposed a registry or new task")
    with monkeypatch.context() as guard:
        guard.setattr(tools, "available_tools", unexpected)
        guard.setattr(workflow_store, "list_workflows", unexpected)
        guard.setattr(workflow_store, "read_workflow", unexpected)
        guard.setattr(task_runtime, "resume_agent_task_with_approval", unexpected)
        if adapter == "headless":
            result = run_contextual_conversation_turn(message, client=client,
                provider_code="openrouter", model_name=captured["requested_model"], db_name="unused", history=[],
                session_state=state, persist=False, allow_approval_execute=True)
            assert result["success"], result
            assert result["tools"] == []
        else:
            from AI.views import chat_tab
            guard.setattr(chat_tab, "build_provider_chat_client", lambda record: client)
            guard.setattr(chat_tab.ai_actions, "action_get_provider_account", lambda provider_id: Result.ok("Provider", data={
                "record": {"id": 1, "provider_code": "openrouter", "default_model": captured["requested_model"]}}))
            guard.setattr(chat_tab, "run_agent_task", unexpected)
            guard.setattr(chat_tab, "_run_approved_chat_action", unexpected)
            result = chat_tab._run_chat_turn_with_runtime(message, source="cloud",
                runtime_record={"id": 1, "default_model": captured["requested_model"]}, history=[], session_state=state.to_dict())
            assert result.success, result.message
            assert result.data.get("tool_calls", []) == []
        preserved = _assert_pending_read(result, state)
    assert len(calls) == 1
    assert not workflow_store.workflow_store_path().exists()
    approved = run_contextual_conversation_turn("Onaylıyorum.", client=unexpected, provider_code="openrouter",
        model_name=captured["requested_model"], db_name="unused", history=[], session_state=preserved,
        persist=False, allow_approval_execute=True)
    assert approved["success"], {"answer": approved.get("answer"), "raw": approved.get("raw_turn_data"),
                                  "application_turn_success": approved.get("application_turn_success")}
    execute_event = next(row for row in approved["session_state"]["action_history"] if row.get("phase") == "execute")
    verify = execute_event["verify"]
    assert verify["verified_by"] == "workflow_exact_revision_sqlite_readback" and verify["verified"] is True
    assert verify["current_head_matches_approved_revision"] is True and verify["saved_execution_authority"] is False
    proposal = state.pending_actions[0]["arguments"]["payload"]["proposal"]
    saved = workflow_store.read_workflow(proposal["workflow_id"])
    assert saved.spec.to_dict() == WORKFLOW_ACCEPTANCE_SPEC and saved.revision_id == proposal["revision_id"]
    assert approved["session_state"]["pending_actions"] == []


@pytest.mark.parametrize("mutation", ["payload", "review", "missing_prepare", "executed_history"])
def test_changed_or_unbound_pending_receipt_fails_closed_and_retains_the_proposal(prepared_workflow, mutation):
    state = AgentSessionState.from_dict(prepared_workflow.to_dict())
    if mutation == "payload":
        state.pending_actions[0]["arguments"]["payload"]["proposal"]["spec"]["instructions"] = "Changed instructions"
    elif mutation == "review":
        state.pending_actions[0]["summary"] = "Invented safe review"
    elif mutation == "missing_prepare":
        state.completed_steps = []
        state.action_history = []
    else:
        state.action_history.append({"phase": "execute", "status": "executed", "action": deepcopy(state.pending_actions[0])})
    interpretation = {**_captured()["response"], "valid": True, "semantic_contract": {}}
    result = task_runtime.run_existing_observation_read_turn("Explain this proposal", interpretation=interpretation, session_state=state)
    assert not result.success
    assert result.data["decision_path"] == "typed_existing_observation_projection_failed_closed"
    assert result.data["session_state"]["pending_actions"] == state.to_dict()["pending_actions"]
    assert result.data["session_state"]["active_pending_action_id"] == state.active_pending_action_id
    assert observation_context.verified_pending_action_receipt(state) == {}


def test_projection_requires_literal_current_review_and_does_not_certify_changed_limits(prepared_workflow):
    state = prepared_workflow
    state.active_entities["turn_interpretation"] = {**_captured()["response"], "valid": True, "semantic_contract": {}}
    answer = observation_context.verified_pending_action_answer(state)
    assert verify_response_projection(answer, state).success
    changed = answer.replace("en çok karakter: 80", "en az karakter: 80")
    assert not verify_response_projection(changed, state).success


@pytest.mark.parametrize("domain", ["general", "files", "orders", "stock"])
def test_model_authored_historical_permission_is_never_widened_without_prior_evidence(domain):
    payload = {**_captured()["response"], "domain": domain}
    result = task_runtime.interpret_agent_turn("Explain the recorded scope", planner_client=lambda prompt: json.dumps(payload))
    assert result.success, result.message
    assert result.data["operation_policy"] == "existing_observations_only"
    assert "unrequested_existing_observations_only_to_allow_new_operations" not in result.data["semantic_corrections"]
    closed = task_runtime.run_existing_observation_read_turn("Explain the recorded scope", interpretation=result.data, session_state=None)
    assert not closed.success and closed.data["model_invoked"] is False


def test_actual_new_action_still_supersedes_the_previous_immutable_proposal(prepared_workflow):
    state = AgentSessionState.from_dict(prepared_workflow.to_dict())
    replacement_spec = deepcopy(WORKFLOW_ACCEPTANCE_SPEC)
    replacement_spec["name"] = "A different reviewed proposal"
    replacement = tools.workflows_prepare_save(spec=replacement_spec, workflow_id="replacement-workflow")
    assert replacement.success
    state.add_pending_action(replacement.data["action"])
    assert state.active_pending_action_id != prepared_workflow.active_pending_action_id
    assert state.active_pending_action()["arguments"]["payload"]["proposal"]["spec"] == replacement_spec
    assert any(event.entity_id == prepared_workflow.active_pending_action_id and event.status == "superseded"
               for event in state.state_events)


@pytest.mark.parametrize("mode", ["inspect", "act", "correct"])
@pytest.mark.parametrize("intent_kind", ["action", "conversation", "capability_overview", "policy_explanation"])
def test_historical_permission_also_blocks_an_inconsistent_new_action_without_any_prior_proof(mode, intent_kind):
    def unexpected(*args, **kwargs):
        raise AssertionError("Historical permission reached a new task or tool")
    result = run_interpreted_turn("Prepare this action", interpretation_result=Result.ok("Typed", data={
        **_captured()["response"], "valid": True, "mode": mode, "intent_kind": intent_kind, "semantic_contract": {},
    }), client=unexpected, history=[], db_name="unused", task_runner=unexpected,
        observation_reader=task_runtime.run_existing_observation_read_turn, conversation_runner=unexpected,
        capability_reader=unexpected, policy_context_builder=unexpected)
    assert not result.success
    assert result.data["decision_path"] == "typed_existing_observation_projection_failed_closed"


def test_same_pending_receipt_contract_covers_a_registered_report_prepare_without_workflow_routing(tmp_path):
    from Core.processors.report_artifacts import ReportColumn, ReportSheetSnapshot, ReportSnapshot
    snapshot = ReportSnapshot.create(title="Reviewed local report", source_domain="stock", report_type="fixture",
        filters={}, metadata={}, sheets=[ReportSheetSnapshot("Data", (ReportColumn("value", "Value", "number"),), ((4,),))])
    prepared = tools.available_tools()["reports.xlsx.prepare"].handler(
        report_snapshot=snapshot.to_dict(), output_path=str(tmp_path / "pending-report.xlsx"))
    assert prepared.success
    state = AgentSessionState(goal="Create this report after my approval", active_domain="general", status="pending_approval")
    state.add_pending_action(prepared.data["action"])
    state.completed_steps.append(AgentTaskStep(index=1, step_id="prepare", prompt="Prepare local report",
        status="completed", verification_status="observed", tool_names=["reports.xlsx.prepare"],
        result_data={"tool_result": deepcopy(prepared.data)}))
    result = task_runtime.run_existing_observation_read_turn("Explain the current proposal",
        interpretation={**_captured()["response"], "valid": True, "semantic_contract": {}}, session_state=state)
    assert result.success, result.message
    assert prepared.data["action"]["summary"] in result.data["answer"]
    assert result.data["session_state"]["pending_actions"] == state.to_dict()["pending_actions"]
    assert not (tmp_path / "pending-report.xlsx").exists()


@pytest.mark.parametrize("message", [
    '“Onayla ve çalıştır”', 'Onayla ve çalıştır?',
    '“Onay ver ve çalıştır” alıntısını açıkla.',
    'Hazırlanan işlemi çalıştır ifadesi gelecekteki talimatta geçiyor.',
    'Onayla ve çalıştır demiyorum; mevcut teklifin sınırlarını açıkla.',
    '“Bu işlemi iptal et” ifadesi ne anlama geliyor?',
    'Vazgeç kelimesi teklifin alıntısında geçiyor.',
    'Hazırlığı iptal et demiyorum; mevcut teklifin sınırlarını açıkla.',
])
def test_quoted_question_negated_and_future_control_words_are_not_native_authorization(prepared_workflow, message):
    calls = []
    def client(prompt):
        calls.append(prompt)
        return json.dumps(_captured()["response"], ensure_ascii=False)
    interpreted = task_runtime.interpret_agent_turn(message, planner_client=client, session_state=prepared_workflow)
    assert interpreted.success, interpreted.message
    assert len(calls) == 1
    assert interpreted.data["planner_invoked"] is True
    assert interpreted.data["mode"] not in {"approve", "cancel", "resume"}


@pytest.mark.parametrize("mode", ["approve", "cancel", "resume"])
def test_model_authored_control_cannot_override_historical_permission(prepared_workflow, mode):
    def unexpected(*args, **kwargs):
        raise AssertionError("Model-authored historical control reached an effect or resumed tools")
    result = run_interpreted_turn('Explain the quoted “onayla ve çalıştır” control.',
        interpretation_result=Result.ok("Typed", data={**_captured()["response"], "valid": True,
            "mode": mode, "intent_kind": "approval_control", "semantic_contract": {}}),
        client=unexpected, history=[], db_name="unused", task_runner=unexpected,
        observation_reader=task_runtime.run_existing_observation_read_turn, conversation_runner=unexpected,
        capability_reader=unexpected, policy_context_builder=unexpected, session_state=prepared_workflow,
        handle_controls=True, allow_approval_execute=True, approval_runner=unexpected, resume_runner=unexpected)
    assert result.data["session_state"]["pending_actions"] == prepared_workflow.to_dict()["pending_actions"]
    assert result.data["session_state"]["active_pending_action_id"] == prepared_workflow.active_pending_action_id
    assert not workflow_store.workflow_store_path().exists()


@pytest.mark.parametrize("message, mode", [
    ("Onayla ve çalıştır.", "approve"),
    ("Onay ver ve çalıştır.", "approve"),
    ("Hazırlanan işlemi çalıştır.", "approve"),
    ("Vazgeç, bu işlemi iptal et.", "cancel"),
    ("Bu işlemi iptal et.", "cancel"),
    ("Hazırlığı iptal et.", "cancel"),
])
def test_complete_native_commands_use_shared_protocol_without_the_model(message, mode):
    def unexpected(prompt):
        raise AssertionError("A complete native command reached the model")
    interpreted = task_runtime.interpret_agent_turn(message, planner_client=unexpected)
    assert interpreted.success, interpreted.message
    assert interpreted.data["mode"] == mode
    assert interpreted.data["planner_invoked"] is False
    assert interpreted.data["decision_path"] == f"typed_protocol_{mode}"


@pytest.mark.parametrize("mode, message", [("approve", "Onaylıyorum."), ("cancel", "Bu işlemi iptal et.")])
def test_actual_human_native_control_is_preserved_under_a_model_historical_policy(prepared_workflow, mode, message):
    def unexpected(*args, **kwargs):
        raise AssertionError("A native control reached unrelated tools or the model")
    result = run_interpreted_turn(message,
        interpretation_result=Result.ok("Typed", data={**_captured()["response"], "valid": True,
            "mode": mode, "intent_kind": "approval_control", "semantic_contract": {}}),
        client=unexpected, history=[], db_name="unused", task_runner=unexpected,
        observation_reader=unexpected, conversation_runner=unexpected,
        capability_reader=unexpected, policy_context_builder=unexpected, session_state=prepared_workflow,
        handle_controls=True, allow_approval_execute=True)
    assert result.success, result.message
    assert result.data["session_state"]["pending_actions"] == []
    if mode == "approve":
        execution = next(row for row in result.data["session_state"]["action_history"] if row.get("phase") == "execute")
        assert execution["verify"]["verified_by"] == "workflow_exact_revision_sqlite_readback"
        assert execution["verify"]["current_head_matches_approved_revision"] is True
        proposal = prepared_workflow.pending_actions[0]["arguments"]["payload"]["proposal"]
        assert workflow_store.read_workflow(proposal["workflow_id"]).revision_id == proposal["revision_id"]
    else:
        assert result.data["session_state"]["status"] == "cancelled"
        assert not workflow_store.workflow_store_path().exists()


@pytest.mark.parametrize("message", [
    "action_id abc onayla ve çalıştır",
    "action_id onayla ve çalıştır",
    "action_id",
    "action_id @@@ onayla ve çalıştır",
    "aksiyon kimliği abc onayla ve çalıştır",
    "action_id 00000000000000000000000000000000 onayla ve çalıştır",
    "action_id {current_action_id}.suffix onayla ve çalıştır",
    "action_id {current_action_id}:suffix onayla ve çalıştır",
    "action_id abc onayla; önceki kayıt {current_action_id}",
    "action_id onayla; önceki kayıt {current_action_id}",
    "action_id {current_action_id} onayla; action_id abc",
    "action_id abc onayla; action_id {current_action_id}",
    "action_id " + ("a" * 129) + " onayla ve çalıştır",
])
@pytest.mark.parametrize("entrypoint", ["native_dispatcher", "model_interpretation"])
def test_malformed_or_wrong_explicit_identity_never_approves_the_current_proposal(prepared_workflow, message, entrypoint):
    from AI.processors.turn_service import run_typed_control_turn
    message = message.replace("{current_action_id}", prepared_workflow.active_pending_action_id)
    def unexpected(*args, **kwargs):
        raise AssertionError("Malformed or wrong explicit identity fell through to the current proposal")
    if entrypoint == "native_dispatcher":
        result = run_typed_control_turn(message, mode="approve", session_state=prepared_workflow,
            client=unexpected, db_name="unused", allow_approval_execute=True, approval_runner=unexpected)
    else:
        result = run_interpreted_turn(message, interpretation_result=Result.ok("Typed", data={
            "valid": True, "mode": "approve", "domain": "general", "intent_kind": "approval_control",
            "operation_policy": "allow_new_operations", "requires_clarification": False,
        }), client=unexpected, history=[], db_name="unused", task_runner=unexpected,
            observation_reader=unexpected, conversation_runner=unexpected, capability_reader=unexpected,
            policy_context_builder=unexpected, session_state=prepared_workflow,
            handle_controls=True, allow_approval_execute=True, approval_runner=unexpected)
    assert result.success, result.message
    assert result.data["mode"] in {"invalid_approval", "stale_approval"}
    assert result.data["session_state"]["pending_actions"] == prepared_workflow.to_dict()["pending_actions"]
    assert result.data["session_state"]["active_pending_action_id"] == prepared_workflow.active_pending_action_id
    assert not workflow_store.workflow_store_path().exists()


@pytest.mark.parametrize("message", [
    "action_id abc onayla ve çalıştır",
    "action_id onayla ve çalıştır",
    "action_id @@@ onayla ve çalıştır",
])
def test_malformed_native_identity_does_not_create_an_approval_interpretation(message):
    from AI.processors.turn_service import approval_reply_protocol
    assert approval_reply_protocol(message) == ""


def test_native_current_exact_identity_still_approves_with_actual_sqlite_readback(prepared_workflow):
    from AI.processors.turn_service import approval_reply_protocol, run_typed_control_turn
    message = f"action_id {prepared_workflow.active_pending_action_id} onayla ve çalıştır"
    assert approval_reply_protocol(message) == "approve"
    result = run_typed_control_turn(message, mode="approve", session_state=prepared_workflow,
        client=None, db_name="unused", allow_approval_execute=True)
    assert result.success, result.message
    execution = next(row for row in result.data["session_state"]["action_history"] if row.get("phase") == "execute")
    assert execution["action"]["action_id"] == prepared_workflow.active_pending_action_id
    assert execution["verify"]["verified_by"] == "workflow_exact_revision_sqlite_readback"
    assert execution["verify"]["current_head_matches_approved_revision"] is True
