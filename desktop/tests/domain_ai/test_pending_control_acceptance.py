"""Pending acceptance checks preserve actual prepare authority across inquiries.

Captured cloud failures remain historical regression input. Scripted model JSON
below exercises the shared runtime on real isolated prepare records; it does not
claim a fresh live model acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from AI.processors.business_agent_acceptance_cli import (
    SCENARIOS, pending_control_problems, pending_control_reference, validate_business_turn,
)
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors import workflow_store
from tests.domain_ai.test_pending_action_existing_observation import prepared_workflow


def _captured_failure():
    return json.loads((Path(__file__).parent / "fixtures" / "schedule_glm_pending_authority_loss.json").read_text(encoding="utf-8"))


def _prepare_and_read():
    prepare, historical_read, _ = _captured_failure()["turns"]
    read = deepcopy(prepare)
    read["scenario_id"] = "workflow_save_pending"
    read["prompt"] = historical_read["prompt"]
    read["runtime"] = {"model_response_count": 0}
    read["answer"] = "The current proposal has not been saved or executed."
    read["tool_call"] = {}
    read["tool_calls"] = []
    return prepare, read


def test_original_cloud_pending_authority_loss_is_rejected_in_the_pending_phase():
    captured = _captured_failure()
    assert captured["selected_model"] == "z-ai/glm-5.3-flash"
    prepare, historical_read, historical_approve = captured["turns"]
    before = deepcopy(captured)
    reference = pending_control_reference(prepare)
    problems = validate_business_turn(historical_read, SCENARIOS["workflow_save_pending"],
        model=captured["selected_model"], pending_reference=reference)
    assert {"pending_current_immutable_proposal_lost_or_changed",
            "pending_current_task_owner_lost_or_changed",
            "pending_canonical_active_approval_state_missing_or_changed",
            "pending_read_changed_action_history",
            "pending_read_changed_completed_observations"} <= set(problems)
    assert historical_approve["execute"]["success"] is None
    assert captured == before  # Never rewrite the original failed cloud evidence.


def test_pending_inquiry_can_pass_without_another_provider_response_only_with_the_exact_frozen_proposal():
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    assert validate_business_turn(read, SCENARIOS["workflow_save_pending"], model="unused/model",
                                  pending_reference=reference) == []
    assert "pending_current_proposal_reference_missing" in validate_business_turn(
        read, SCENARIOS["workflow_save_pending"], model="unused/model")


def test_reference_freezes_the_original_prepare_before_later_ui_or_model_mutations():
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    frozen = deepcopy(reference)
    prepare["pending_action"]["arguments"]["payload"]["proposal"]["spec"]["instructions"] = "Unapproved replacement"
    prepare["raw_turn_data"]["state"]["pending_actions"].clear()
    prepare["raw_turn_data"]["state"]["action_history"].clear()
    prepare["raw_turn_data"]["state"]["completed_steps"].clear()
    assert reference == frozen
    assert pending_control_problems(read, reference) == []


@pytest.mark.parametrize("field,value", [
    ("action_id", "another-action"), ("action_type", "another.effect"),
    ("domain", "orders"), ("tool", "reports.xlsx.prepare"),
    ("prepare_fingerprint", "another-fingerprint"),
    ("arguments", {"payload": {"unreviewed": True}}),
    ("summary", "A different approval packet"),
])
def test_replaced_review_packet_cannot_pass_even_when_all_current_views_agree(field, value):
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    for action in (read["pending_action"], read["action_proposal"], read["raw_turn_data"]["state"]["pending_actions"][0]):
        action[field] = deepcopy(value)
    assert "pending_current_immutable_proposal_lost_or_changed" in pending_control_problems(read, reference)


@pytest.mark.parametrize("mutation", ["lost_task", "lost_action_owner", "lost_canonical_owner", "changed_task"])
def test_pending_control_owner_must_remain_explicit_and_exact(mutation):
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    state = read["raw_turn_data"]["state"]
    if mutation == "lost_task":
        state.pop("session_id")
    elif mutation == "lost_action_owner":
        read["pending_action"].pop("_agent_task_session_id")
    elif mutation == "lost_canonical_owner":
        state["pending_actions"][0].pop("_agent_task_session_id")
    else:
        state["session_id"] = "another-current-task"
    assert any("owner" in problem or "canonical" in problem for problem in pending_control_problems(read, reference))


@pytest.mark.parametrize("mutation", ["active_id", "resolved", "removed", "duplicated", "another_pending", "approval_disabled"])
def test_canonical_pending_collection_and_active_state_cannot_change_during_an_inquiry(mutation):
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    state = read["raw_turn_data"]["state"]
    if mutation == "active_id":
        state["active_pending_action_id"] = "another-active-id"
    elif mutation == "resolved":
        state["status"] = "complete"
    elif mutation == "removed":
        state["pending_actions"] = []
    elif mutation == "duplicated":
        state["pending_actions"].append(deepcopy(state["pending_actions"][0]))
    elif mutation == "another_pending":
        replacement = deepcopy(state["pending_actions"][0])
        replacement["action_id"] = "another-waiting-action"
        state["pending_actions"].append(replacement)
    else:
        state["pending_actions"][0]["approval_required"] = False
    assert "pending_canonical_active_approval_state_missing_or_changed" in pending_control_problems(read, reference)


@pytest.mark.parametrize("field", ["action_history", "completed_steps"])
def test_new_history_or_observation_during_pending_read_is_not_hidden_by_a_preserved_ui_card(field):
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    read["raw_turn_data"]["state"][field].append({"phase": "execute", "success": True})
    expected = "pending_read_changed_action_history" if field == "action_history" else "pending_read_changed_completed_observations"
    assert expected in pending_control_problems(read, reference)


@pytest.mark.parametrize("location", ["captured_result", "raw_flag", "canonical_flag", "failed_result_effect", "failed_execute_attempt"])
def test_pending_read_rejects_actual_or_claimed_effects_independently_of_visible_answer(location):
    prepare, read = _prepare_and_read()
    reference = pending_control_reference(prepare)
    if location == "captured_result":
        read["execute"] = {"success": True, "message": "Executed", "data": {}}
    elif location == "raw_flag":
        read["raw_turn_data"]["db_write_performed"] = True
    elif location == "canonical_flag":
        read["raw_turn_data"]["state"]["pending_actions"][0]["api_call_performed"] = True
    elif location == "failed_result_effect":
        read["execute"] = {"success": False, "message": "Readback failed after write", "data": {
            "state": {}, "execute": {"file_written": True}}}
    else:
        read["execute"] = {"success": False, "message": "Execution was attempted and failed", "data": {}}
    assert "pending_read_claimed_or_performed_effect" in pending_control_problems(read, reference)


@pytest.mark.parametrize("malformed", [None, [], {"raw_turn_data": {"state": []}}, {"pending_action": "invalid"}])
def test_missing_or_malformed_original_reference_cannot_become_acceptance(malformed):
    _, read = _prepare_and_read()
    reference = pending_control_reference(malformed) if isinstance(malformed, dict) else malformed
    assert pending_control_problems(read, reference) == ["pending_current_proposal_reference_missing"]


def test_real_shared_runtime_pending_read_preserves_the_proposal_and_passes_the_driver_before_exact_approval(
        prepared_workflow):
    from AI.processors.session_state import AgentSessionState
    from AI.views.chat_tab import _chat_data_from_task_result
    from Feedback.processors.pipeline import Result
    # This is the same source-UI adapter that binds the actual task owner to
    # canonical pending actions before the live driver freezes its reference.
    original = _chat_data_from_task_result(Result.ok("Prepared", data={"state": prepared_workflow.to_dict()}))["state"]
    state = AgentSessionState.from_dict(original)
    original_action = deepcopy(original["pending_actions"][0])
    prepare = {"pending_action": original_action, "raw_turn_data": {"state": deepcopy(original)}}
    reference = pending_control_reference(prepare)
    captured = json.loads((Path(__file__).parent / "fixtures" / "schedule_glm_pending_interpretation.json").read_text(encoding="utf-8"))
    calls = []
    def client(prompt):
        calls.append(prompt)
        assert len(calls) == 1
        return json.dumps(captured["response"], ensure_ascii=False)
    result = run_contextual_conversation_turn(captured["prompt"], client=client,
        provider_code="openrouter", model_name=captured["requested_model"], db_name="unused", history=[],
        session_state=state, persist=False)
    assert result["success"], result
    actual = result["session_state"]
    turn = {"success": result["success"], "answer": result["answer"],
        "pending_action": deepcopy(actual["pending_actions"][0]),
        "raw_turn_data": {"state": actual}, "runtime": {"model_response_count": 0},
        "execute": {"success": None}}
    assert validate_business_turn(turn, SCENARIOS["workflow_save_pending"], model="unused/model",
                                  pending_reference=reference) == []
    assert len(calls) == 1
    assert actual["pending_actions"] == original["pending_actions"]
    assert actual["completed_steps"] == original["completed_steps"]
    assert not workflow_store.workflow_store_path().exists()
    def no_model(*args, **kwargs):
        raise AssertionError("Current exact approval must not request another plan")
    approved = run_contextual_conversation_turn("Onaylıyorum.", client=no_model, provider_code="openrouter",
        model_name=captured["requested_model"], db_name="unused", history=[], session_state=actual,
        persist=False, allow_approval_execute=True)
    assert approved["success"], approved
    event = next(row for row in approved["session_state"]["action_history"] if row.get("phase") == "execute")
    assert event["action"]["action_id"] == original_action["action_id"]
    assert event["verify"]["verified_by"] == "workflow_exact_revision_sqlite_readback"
    assert event["verify"]["current_head_matches_approved_revision"] is True
    assert event["verify"]["saved_execution_authority"] is False
