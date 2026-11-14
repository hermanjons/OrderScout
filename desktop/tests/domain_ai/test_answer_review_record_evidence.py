"""Review packets preserve real source rows; these tests do not simulate an LLM."""
import copy
import json
from pathlib import Path

from AI.processors.model_loop import _preview
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.answer_review import review_sources
from AI.runtime.context_window import json_bytes


def state_for(payload, *, step_id="receipt_1"):
    state = AgentSessionState(goal="Inspect the returned records")
    state.completed_steps.append(AgentTaskStep(
        index=1, step_id=step_id, prompt="returns.lookup", tool_names=["returns.lookup"],
        status="completed", arguments={"api_account_ids": [2]}, result_data={"tool_result": payload},
    ))
    return state


def decoded_rows(source, collection):
    projection = source["record_evidence"][collection]
    columns = projection["columns"]
    return [(record["source_index"], {
        columns[index]: value for index, value in zip(record["field_indexes"], record["values"])
    }, record["omitted_fields"]) for record in projection["rows"]]


def test_review_packet_distinguishes_unfiltered_query_from_accounts_with_matching_rows():
    payload = {"orders": [{"order_number": f"SYNTHETIC-{i}", "api_account_id": 2} for i in range(40)],
        "total_count": 40, "requested_api_account_ids": [], "account_scopes": [{"api_account_id": 2}],
        "query_scope": {"account_filter_applied": False, "api_account_ids": []}}
    source = review_sources(state_for(payload), _preview)[0]
    assert source["scope"]["query_scope"] == payload["query_scope"]
    assert source["scope"]["account_scopes"] == [{"api_account_id": 2}]
    payload["orders"] = []
    payload["query_scope"] = {"account_filter_applied": True, "api_account_ids": [3]}
    payload["account_scopes"] = [{"api_account_id": 3}]
    assert review_sources(state_for(payload), _preview)[0]["scope"]["query_scope"] == payload["query_scope"]


def actual_returns_receipt():
    fixture = Path(__file__).parent / "fixtures/answer_review/returns_lookup_29.json"
    return json.loads(fixture.read_text(encoding="utf-8"))["receipt"]


def test_actual_single_order_context_keeps_nested_product_evidence_for_review():
    fixture = Path(__file__).parent / "fixtures/answer_review/order_detail_local.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))["receipt"]
    before = copy.deepcopy(payload)
    state = state_for(payload)
    state.completed_steps[0].tool_names = ["orders.full_context"]
    sources = review_sources(state, _preview, candidate_answer="DEMO-202605-000386")
    assert sources[0]["complete_result"] == payload
    items = sources[0]["complete_result"]["contexts"][0]["items"]
    assert {(row["product_name"], row["quantity"]) for row in items} == {
        ("Karpuz Kesme Aparatı-demo", 3), ("Aile Ağacı Fotoğraf Çerçevesi-demo", 2)}
    assert json_bytes(sources) <= 20000 and payload == before


def test_actual_29_return_rows_keep_dates_and_true_oldest_records_within_budget():
    payload = actual_returns_receipt()
    # This is the original incorrect candidate's literal identity selection.
    # Review must retain the other rows too, so the model can correct ranking.
    candidate = "DEMO-202609-000071 / DEMO-202610-000155 / DEMO-202610-000008"
    assert _preview(payload)["returns"]["stored_row_count"] == 29
    sources = review_sources(state_for(payload), _preview, candidate_answer=candidate)
    assert json_bytes(sources) <= 20000
    assert json_bytes(sources[0]["record_evidence"]) <= 14000
    summary = sources[0]["record_collections"][0]
    assert summary == {
        "collection": "returns", "returned_row_count": 29, "projected_row_count": 29,
        "omitted_row_count": 0, "all_returned_rows_included": True,
        "source_truncated": False, "omitted_fields_are_unknown": True,
    }
    rows = decoded_rows(sources[0], "returns")
    assert sorted(index for index, _, _ in rows) == list(range(29))
    for index, fields, omitted in rows:
        original = payload["returns"][index]
        assert fields == {key: value for key, value in original.items()
                          if value is None or isinstance(value, (str, int, float, bool))}
        assert set(omitted) == {"claim_line_item_ids", "waiting_line_item_ids"}
    waiting = [row for _, row, _ in rows if row["status"] == "WaitingInAction"]
    assert len(waiting) == 7
    actual_oldest = sorted(waiting, key=lambda row: row["claim_date_ms"])[:3]
    assert [row["order_number"] for row in actual_oldest] == [
        "DEMO-202609-000071", "DEMO-202610-000092", "DEMO-202610-000113",
    ]
    assert [row["total_price"] for row in actual_oldest] == [559.8, 99.9, 329.9]
    assert sources[0]["scope"]["environment_by_account"] == {"2": "local"}
    assert sources[0]["arguments"]["api_account_ids"] == [2]


def test_projection_omissions_and_source_truncation_are_separate():
    payload = actual_returns_receipt()
    payload["truncated"] = True
    payload["total_count"] = 1000
    source = review_sources(state_for(payload), _preview)[0]
    summary = source["record_collections"][0]
    assert summary["source_truncated"] is True
    assert summary["all_returned_rows_included"] is True
    assert summary["returned_row_count"] == 29
    assert source["compact_facts"]["total_count"] == 1000


def test_large_projection_prioritizes_literal_identity_and_marks_unknown_fields():
    payload = {"truncated": False, "rows": [
        {"orderNumber": f"ORDER-{index:04}", "amount": index + 0.25,
         "nullable": None, "description": "a" * 161,
         "nested": {"value": "not projected"}, "api_key": "must-not-reach-review"}
        for index in range(300)
    ]}
    sources = review_sources(state_for(payload), _preview, candidate_answer="ORDER-0299")
    assert json_bytes(sources) <= 20000
    assert json_bytes(sources[0]["record_evidence"]) <= 14000
    summary = sources[0]["record_collections"][0]
    assert summary["returned_row_count"] == 300
    assert 0 < summary["projected_row_count"] < 300
    assert summary["omitted_row_count"] == 300 - summary["projected_row_count"]
    assert summary["all_returned_rows_included"] is False
    assert summary["source_truncated"] is False
    rows = decoded_rows(sources[0], "rows")
    assert rows[0] == (299, {"orderNumber": "ORDER-0299", "amount": 299.25, "nullable": None},
                       ["description", "nested"])
    assert "must-not-reach-review" not in json.dumps(sources)
    assert "api_key" not in sources[0]["record_evidence"]["rows"]["columns"]


def test_literal_ids_are_prioritized_across_sources_without_business_query_rules():
    state = state_for({"records": [{"identity": f"old-{index:04}", "value": "s" * 140}
                                   for index in range(90)]}, step_id="older")
    state.completed_steps.append(AgentTaskStep(
        index=2, step_id="newer", prompt="stock.items", tool_names=["stock.items"],
        status="completed", result_data={"tool_result": {
            "items": [{"sku": f"SKU-{index:04}", "value": "n" * 140} for index in range(90)]}},
    ))
    sources = review_sources(state, _preview, candidate_answer="old-0089 SKU-0089")
    assert json_bytes(sources) <= 20000
    assert sum(json_bytes(source.get("record_evidence", {})) for source in sources) <= 14000
    by_step = {source["step_id"]: source for source in sources}
    assert decoded_rows(by_step["older"], "records")[0][0] == 89
    assert decoded_rows(by_step["newer"], "items")[0][0] == 89
    assert by_step["older"]["record_collections"][0]["source_truncated"] is None


def test_small_complete_results_and_two_argument_compatibility_remain_exact():
    payload = {"row_count": 32, "rows": [{"id": "R-1234", "price": 42.25, "note": None}]}
    source = review_sources(state_for(payload), _preview)[0]
    assert source["complete_result"] == payload
    assert "record_evidence" not in source
    assert "record_collections" not in source


def test_review_packet_construction_does_not_mutate_durable_records():
    payload = actual_returns_receipt()
    before = copy.deepcopy(payload)
    review_sources(state_for(payload), _preview, candidate_answer="DEMO-202610-000113")
    assert payload == before


def test_count_only_receipts_keep_the_full_existing_source_budget():
    state = AgentSessionState(goal="Inspect the counts from each account")
    for index in range(8):
        state.completed_steps.append(AgentTaskStep(
            index=index, step_id=f"count_{index}", prompt="orders.status_counts",
            tool_names=["orders.status_counts"], status="completed",
            arguments={"api_account_ids": [index]}, result_data={"tool_result": {
                "total_count": 100 + index,
                "status_counts": {f"status_{number}": number + index for number in range(22)},
                "environment_by_account": {str(index): "local"},
            }},
        ))
    sources = review_sources(state, _preview)
    assert 6000 < json_bytes(sources) <= 20000
    assert len(sources) == 8
    assert all(source["complete_result"]["total_count"] == 100 + index
               for index, source in enumerate(sources))
