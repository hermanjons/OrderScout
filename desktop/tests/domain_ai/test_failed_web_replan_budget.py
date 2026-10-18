from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from AI.processors import web_research
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.processors.task_runtime import _replan_after_failed_step, _task_replan_count
from AI.processors.tools import available_tools


GOAL = "Model X kullanıcı yorumlarını internette bul ve kaynakla özetle"
PRODUCT_URL = "https://shop.example.com/model-x"
FOLLOW_URL = "https://shop.example.com/model-x/product-reviews"
SECOND_URL = "https://sources.example.com/model-x/reviews"


def _failed_web_state(path: str, *, max_replans: int, reserved: int = 0):
    """Use the registered search handler and actual HTML observation parser."""
    search_transport = Mock(return_value=[
        {"title": "Model X product page", "url": PRODUCT_URL},
        {"title": "Model X customer reviews", "url": SECOND_URL},
    ])
    search = available_tools()["web.search"].handler(
        query=GOAL, search_client=search_transport,
    )
    assert search.success, search.message
    assert search.data["evidence_status"] == "candidate_sources_only"
    assert search.data["search_results_are_final_evidence"] is False
    link = (
        '<a href="/model-x/product-reviews">Musteri yorumlari</a>'
        if path == "contained_link" else ""
    )
    fetch_transport = Mock(return_value={
        "url": PRODUCT_URL,
        "content_type": "text/html; charset=utf-8",
        "body": (
            "<html><head><title>Model X</title></head><body><main>"
            "<h1>Model X</h1><p>Product catalogue. Technical specifications.</p>"
            f"{link}</main></body></html>"
        ).encode("utf-8"),
    })
    observation = web_research.open_web_source(
        PRODUCT_URL, query_summary=GOAL, fetcher=fetch_transport,
        now=datetime(2026, 10, 11, tzinfo=timezone.utc),
    )
    assessment = web_research.evaluate_web_observation_goal_evidence(observation, GOAL)
    assert assessment["adequate"] is False, assessment
    search_step = AgentTaskStep(
        index=1, step_id="search", prompt="Search public review candidates",
        operation_candidates=["web.search"], operation_domain="web",
        arguments={"query": GOAL}, status="completed", tool_names=["web.search"],
        verification_status="observed", result_data={"tool_result": search.data},
    )
    failed = AgentTaskStep(
        index=2, step_id="open_failed", prompt="Read candidate evidence",
        operation_candidates=["web.open"], operation_domain="web",
        arguments={"url": PRODUCT_URL}, status="failed", tool_names=["web.open"],
        verification_status="failed", result_message="Source lacks requested review evidence",
        result_data={"tool_result": {
            "tool": "web.open", "url": PRODUCT_URL, "requested_url": PRODUCT_URL,
            "web_observation": observation.to_dict(), "goal_evidence": assessment,
        }},
    )
    dependent = AgentTaskStep(
        index=3, step_id="find_review", prompt="Inspect source review text",
        operation_candidates=["web.find_text"], operation_domain="web",
        depends_on=[failed.step_id], arguments={
            "web_observation": {"$from_step": failed.step_id, "path": "tool_result.web_observation"},
            "pattern": "review",
        },
    )
    state = AgentSessionState(
        goal=GOAL, active_domain="web", completed_steps=[search_step, failed],
        remaining_steps=[dependent], active_entities={"execution_budget": {
            "contract_version": 1, "max_steps": 5, "max_replans": max_replans,
            "started_steps": 2, "applied_replans": reserved,
            "reserved_child_replans": reserved,
        }},
    )
    return state, failed, search_transport, fetch_transport


@pytest.mark.parametrize("path", ["contained_link", "search_candidate"])
@pytest.mark.parametrize("max_replans,reserved", [(0, 0), (1, 1)])
def test_no_web_replacement_when_shared_replan_budget_is_exhausted(path, max_replans, reserved):
    state, failed, search, fetch = _failed_web_state(path, max_replans=max_replans, reserved=reserved)
    before = deepcopy(state.to_dict())
    planner = Mock(side_effect=AssertionError("Exhausted budget must not call the model"))

    assert _replan_after_failed_step(
        state, failed, planner_client=planner, max_replans=max_replans, max_steps=3,
    ) is False

    assert state.to_dict() == before
    assert _task_replan_count(state) == reserved
    planner.assert_not_called()
    search.assert_called_once()
    fetch.assert_called_once()


@pytest.mark.parametrize("path", ["contained_link", "search_candidate"])
def test_one_web_replacement_uses_one_shared_replan_without_executing_it(path):
    state, failed, search, fetch = _failed_web_state(path, max_replans=1)
    completed_search = deepcopy(state.completed_steps[0].to_dict())
    failed_arguments = deepcopy(failed.arguments)
    original_observation = deepcopy(failed.result_data["tool_result"]["web_observation"])
    budget = deepcopy(state.active_entities["execution_budget"])
    planner = Mock(side_effect=AssertionError("Deterministic navigation needs no model"))

    assert _replan_after_failed_step(
        state, failed, planner_client=planner, max_replans=1, max_steps=3,
    ) is True

    replacement, dependent = state.remaining_steps
    contained = path == "contained_link"
    assert replacement.step_id == f"open_failed_{'follow' if contained else 'fallback'}_1"
    assert replacement.operation_candidates == ["web.follow" if contained else "web.open"]
    assert replacement.arguments["link_url" if contained else "url"] == (FOLLOW_URL if contained else SECOND_URL)
    assert replacement.status == "pending"
    assert replacement.tool_names == []
    assert replacement.depends_on == []
    assert dependent.depends_on == [replacement.step_id]
    assert dependent.arguments["web_observation"] == {
        "$from_step": replacement.step_id, "path": "tool_result.web_observation",
    }
    assert state.completed_steps[0].to_dict() == completed_search
    assert failed.step_id == "open_failed" and failed.status == "failed"
    assert failed.arguments == failed_arguments
    assert failed.result_data["tool_result"]["web_observation"] == original_observation
    assert failed.result_data["replacement_step_ids"] == [replacement.step_id]
    assert failed.verification_status == "superseded"
    assert state.active_entities["replans"][0]["source"] == "deterministic_web_recovery"
    assert state.active_entities["replans"][0]["applied"] is True
    assert _task_replan_count(state) == 1
    assert state.active_entities["execution_budget"] == budget
    assert state.pending_actions == [] and state.action_history == []

    after = deepcopy(state.to_dict())
    assert _replan_after_failed_step(
        state, failed, planner_client=planner, max_replans=1, max_steps=3,
    ) is False
    assert state.to_dict() == after
    planner.assert_not_called()
    search.assert_called_once()
    fetch.assert_called_once()


@pytest.mark.parametrize("path", ["contained_link", "search_candidate"])
def test_parent_web_repair_can_use_only_the_budget_remaining_after_child_reservation(path):
    state, failed, search, fetch = _failed_web_state(path, max_replans=2, reserved=1)
    planner = Mock(side_effect=AssertionError("No model call for deterministic navigation"))
    assert _task_replan_count(state) == 1

    assert _replan_after_failed_step(
        state, failed, planner_client=planner, max_replans=2, max_steps=3,
    ) is True
    assert _task_replan_count(state) == 2
    assert state.active_entities["execution_budget"]["reserved_child_replans"] == 1
    after = deepcopy(state.to_dict())
    assert _replan_after_failed_step(
        state, failed, planner_client=planner, max_replans=2, max_steps=3,
    ) is False
    assert state.to_dict() == after
    planner.assert_not_called()
    search.assert_called_once()
    fetch.assert_called_once()
