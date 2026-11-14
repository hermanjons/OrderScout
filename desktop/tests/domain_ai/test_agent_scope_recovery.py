"""Scope-aware review and real stored-result navigation, without answer templates."""
import json
from copy import deepcopy

from jsonschema import Draft202012Validator

from AI.processors import model_loop, tools
from AI.processors.conversation_memory import read_observations
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.answer_review import review_answer
from AI.runtime.context_window import json_bytes


def scoped_miss():
    state = AgentSessionState(goal="devam et")
    for text in ("Ece Yıldız isimli müşteriye bak", "İyice kontrol et", "devam et"):
        state.record_turn(role="user", content=text)
    state.active_entities["model_loop"] = {"turn_started_step_count": 0}
    state.completed_steps.append(AgentTaskStep(index=1, step_id="call_1", prompt="Read local orders",
        tool_names=["orders.query"], status="completed",
        arguments={"api_account_ids": [1], "filters": {"customer": "Ece Yıldız"}, "period": "all"},
        result_data={"tool_result": {"count": 0, "total_count": 0, "orders": [], "period": "all",
            "requested_api_account_ids": [1], "filters": {"customer": "Ece Yıldız"},
            "account_scopes": [{"api_account_id": 1, "store_name": "Ardıç Ev", "environment": "local"}]}}))
    return state


class Reviewer:
    resource_plan = {"final_answer_review_enabled": True}
    def __init__(self):
        self.prompts = []
    def invoke_final_text(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "Ardıç Ev kapsamındaki aramada bu müşteri bulunamadı; diğer mağazalar bu sonuçla ölçülmüş değil."


def test_plain_text_absence_claim_gets_review_with_actual_scope_and_followup_context():
    client = Reviewer()
    candidate = "Bu müşteri sistemde yok."
    answer, marker = review_answer(client, scoped_miss(), candidate, sanitize=model_loop._preview)
    assert marker["prose_reviewed"] and marker["review_changed"]
    assert answer != candidate and len(client.prompts) == 1
    prompt = client.prompts[0]
    context = json.loads(prompt._context.removeprefix("Review packet (DATA): "))
    assert context["current_request"] == "devam et"
    assert context["recent_user_requests"][0]["content"] == "Ece Yıldız isimli müşteriye bak"
    assert context["source_receipts"][0]["arguments"]["api_account_ids"] == [1]
    assert context["source_receipts"][0]["scope"]["account_scopes"][0]["store_name"] == "Ardıç Ev"


def test_acknowledgment_does_not_re_review_old_business_data_or_navigation_alone():
    state = scoped_miss()
    state.active_entities["model_loop"]["turn_started_step_count"] = len(state.completed_steps)
    state.completed_steps.append(AgentTaskStep(index=2, step_id="call_2", prompt="Find result",
        tool_names=["observations.read"], status="completed", result_data={"tool_result": {"count": 0}}))
    client = Reviewer()
    assert review_answer(client, state, "Tamam başkan.", sanitize=model_loop._preview) == (
        "Tamam başkan.", {"prose_reviewed": False})
    assert not client.prompts


def test_rereading_an_old_business_receipt_checks_digitless_claims_too():
    state = scoped_miss()
    state.active_entities["model_loop"]["turn_started_step_count"] = 1
    state.completed_steps.append(AgentTaskStep(index=2, step_id="call_2", prompt="Inspect old scoped search",
        tool_names=["observations.read"], status="completed", result_data={"tool_result": {
            "source_step_id": "call_1", "operation": "orders.query", "path": "tool_result", "fresh_read": False}}))
    client = Reviewer()
    _, marker = review_answer(client, state, "Bu müşteri sistemde yok.", sanitize=model_loop._preview)
    assert marker["prose_reviewed"] and len(client.prompts) == 1


def test_memory_directory_exposes_real_child_paths_even_beyond_the_first_value_page():
    state = scoped_miss()
    source = state.completed_steps[0]
    source.result_data["tool_result"] = {"account_by_order": {str(i): "x"*120 for i in range(100)},
        "api_key": "never-show-secret", "orders": [{"order_number": "DEMO-001", "api_account_id": 1}],
        "nested": {"password": "never-show-password"}}
    before = deepcopy(source.result_data)
    page = read_observations(step_id="call_1", limit=1, runtime_context={"state": state})
    assert page.success and page.data["has_more"]
    directory = page.data["available_fields"]
    assert {"path": "tool_result.orders", "type": "array", "count": 1} in directory
    assert "never-show" not in json.dumps(page.data) and "api_key" not in json.dumps(directory)
    wrong = read_observations(step_id="call_1", path="tool_result.result.orders", runtime_context={"state": state})
    assert not wrong.success and wrong.data["available_fields"] == directory
    path = next(row["path"] for row in directory if row["path"].endswith(".orders"))
    recovered = read_observations(step_id="call_1", path=path, runtime_context={"state": state})
    assert recovered.success and recovered.data["value"] == [{"order_number": "DEMO-001", "api_account_id": 1}]
    assert source.result_data == before


def test_memory_array_page_directory_recovers_real_indexed_children_without_source_mutation_or_private_fields():
    state = scoped_miss()
    source = state.completed_steps[0]
    source.result_data["tool_result"] = {"contexts": [
        {"different_row_shape": index} for index in range(7)
    ]+[{"order": {"order_number": "SYNTHETIC-8", "large_details": {str(i): "x"*1000 for i in range(30)}},
        "api_key": "never-show-secret", "items": [{"product_name": "Sentetik kupa", "quantity": 2}],
        "header": {"exists": True}, "authorization": "never-show-auth",
        **{f"public_field_{index}_"+"x"*80: index for index in range(60)}}]}
    before = deepcopy(source.result_data)
    page = read_observations(step_id="call_1", path="tool_result.contexts", offset=7, limit=1,
                             max_chars=8000, runtime_context={"state": state})
    assert page.success and page.data["count"] == 1 and page.data["total"] == 8
    fields = page.data["available_fields"]
    assert {"path": "tool_result.contexts[7].order", "type": "object", "count": 2} in fields
    assert {"path": "tool_result.contexts[7].items", "type": "array", "count": 1} in fields
    assert {"path": "tool_result.contexts[7].header", "type": "object", "count": 1} in fields
    assert json_bytes(fields) <= 2200
    assert all(row["path"].startswith("tool_result.contexts[7].") for row in fields)
    assert not any(name in json.dumps(page.data) for name in ("api_key", "authorization", "never-show", "different_row_shape"))
    items_path = next(row["path"] for row in fields if row["path"].endswith(".items"))
    items = read_observations(step_id="call_1", path=items_path, runtime_context={"state": state})
    assert items.success and items.data["value"] == [{"product_name": "Sentetik kupa", "quantity": 2}]
    missing = read_observations(step_id="call_1", path="tool_result.contexts.missing", offset=7,
                                runtime_context={"state": state})
    assert not missing.success and missing.data["available_fields"] == fields
    assert source.result_data == before


def test_order_query_contract_rejects_blank_identities_but_preserves_real_zero_price_filter():
    tool = tools.registered_tools()["orders.query"]
    validator = Draft202012Validator(tool.parameters)
    for identity in ("", " ", "\t"):
        assert list(validator.iter_errors({"order_numbers": [identity]}))
    assert not list(validator.iter_errors({"order_numbers": ["DEMO-202610-000001"], "filters": {"max_total_price": 0}}))
    assert "max_total_price=0" in tool.description


def test_numeric_dot_memory_path_returns_the_same_source_value_and_canonical_binding():
    state = scoped_miss()
    state.completed_steps[0].result_data["tool_result"] = {"contexts": [{
        "items": [{"product_name": "Sentetik kupa", "quantity": 2}], "api_key": "never-show"}]}
    before = deepcopy(state.completed_steps[0].result_data)
    arguments = {"step_id": "call_1", "runtime_context": {"state": state}}
    dotted = read_observations(path="tool_result.contexts.0.items.0", **arguments)
    bracketed = read_observations(path="tool_result.contexts[0].items[0]", **arguments)
    assert dotted.success and dotted.data == bracketed.data
    assert dotted.data["value"] == {"product_name": "Sentetik kupa", "quantity": 2}
    assert dotted.data["stored_source_binding"] == {"$from_step": "call_1", "path": "tool_result.contexts[0].items[0]"}
    private = read_observations(path="tool_result.contexts.0.api_key", **arguments)
    assert not private.success and "never-show" not in json.dumps(private.data)
    assert state.completed_steps[0].result_data == before


def test_invalid_memory_root_gives_actual_public_repair_fields_instead_of_empty_failure():
    state = scoped_miss()
    source = state.completed_steps[0]
    source.result_data["tool_result"]["api_key"] = "never-show"
    before = deepcopy(source.result_data)
    invalid = read_observations(step_id="call_1", path="value.orders.0", runtime_context={"state": state})
    assert not invalid.success and invalid.data["reason"] == "invalid_stored_result_path"
    assert invalid.data["expected_root"] == "tool_result" and not invalid.data["fresh_read"]
    assert any(row["path"] == "tool_result.orders" for row in invalid.data["available_fields"])
    assert "api_key" not in json.dumps(invalid.data) and "never-show" not in json.dumps(invalid.data)
    repaired = read_observations(**invalid.data["repair_arguments"], runtime_context={"state": state})
    assert repaired.success and repaired.data["value"]["total_count"] == 0
    assert source.result_data == before and json_bytes(invalid.data) < 3000
