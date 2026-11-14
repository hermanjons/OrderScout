"""Navigation must not evict already-observed small aggregates from working memory."""
from AI.processors.model_loop import _sources
from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.context_window import compact_facts, json_bytes


def test_complete_status_map_survives_discovery_and_memory_navigation():
    counts = {"Picking": 238, "Shipped": 118, "Cancelled": 86, "ReadyToShip": 48,
              "Invoiced": 39, "Delivered": 25, "UnDeliveredAndReturned": 13, "UnDelivered": 2, "AtCollectionPoint": 1}
    state = AgentSessionState(goal="570 siparişi sınıflandır")
    state.completed_steps = [AgentTaskStep(index=1, prompt="Read actual counts", step_id="call_1", status="completed",
        tool_names=["orders.status_counts"], result_data={"tool_result": {"total_orders": 570, "status_counts": counts}})]
    for index in range(2, 10):
        state.completed_steps.append(AgentTaskStep(index=index, prompt="Navigate", step_id=f"call_{index}",
            status="completed", tool_names=["operations.discover"], result_data={"tool_result": {"operations": []}}))
    source = _sources(state)[0]
    assert source["compact_facts"]["status_counts"] == counts
    assert source["compact_facts"]["total_orders"] == 570
    assert source["full_result_stored"]


def test_compact_facts_does_not_sample_tables_or_truncate_aggregate_maps():
    counts = {f"state{i}": i for i in range(9)}
    payload = {"status_counts": counts, "rows": [{"id": i} for i in range(570)], "long_text": "x" * 5000}
    result = compact_facts(payload)
    assert result == {"status_counts": counts}
    assert json_bytes(result) <= 1400


def test_compact_fact_budget_and_private_fields_remain_protected():
    state = AgentSessionState(goal="Inspect stored facts")
    for index in range(45):
        state.completed_steps.append(AgentTaskStep(index=index + 1, prompt="Read", step_id=f"call_{index}",
            status="completed", tool_names=["example.read"], result_data={"tool_result": {
                "api_key": "never-visible", "counts": {f"s{i}": i for i in range(12)},
                **{f"fact{i}": "v" * 150 for i in range(10)}}}))
    sources = _sources(state)
    assert sum(json_bytes(row.get("compact_facts", {})) for row in sources if "compact_facts" in row) <= 6000
    assert "never-visible" not in str(sources)
    assert len(sources) == 40


def test_original_population_counts_survive_many_later_scoped_reads_with_metadata():
    counts = {"Picking": 238, "Shipped": 118, "Cancelled": 86, "ReadyToShip": 48,
              "Invoiced": 39, "Delivered": 25, "UnDeliveredAndReturned": 13, "UnDelivered": 2, "AtCollectionPoint": 1}
    state = AgentSessionState(goal="Classify population")
    for index in range(26):
        state.completed_steps.append(AgentTaskStep(index=index + 1, step_id=f"call_{index + 1}", prompt="Read counts",
            tool_names=["orders.status_counts"], status="completed", arguments={"api_account_ids": [index + 100]},
            result_data={"tool_result": {"status_counts": counts if index == 0 else {"Delivered": index},
                "total_orders": 570 if index == 0 else index, "source_revision": 123456,
                "source_snapshot_hash": "f" * 64, "query_fingerprint": "a" * 64,
                "account_by_order": {f"order{i}": index + 100 for i in range(20)},
                "requested_api_account_ids": [index + 100], "environment_by_account": {str(index + 100): "stage"},
                "period": "all", "start_ms": None, "end_ms": None}}))
    sources = _sources(state)
    assert sources[0]["compact_facts"]["status_counts"] == counts
    assert sources[0]["compact_facts"]["total_orders"] == 570
    assert sources[0]["arguments"] == {"api_account_ids": [100]}
    assert sources[0]["observed_scope"]["environment_by_account"] == {"100": "stage"}
    assert "account_by_order" not in sources[0]["compact_facts"]
    assert sum(json_bytes(row.get("compact_facts", {})) for row in sources if "compact_facts" in row) <= 6000
