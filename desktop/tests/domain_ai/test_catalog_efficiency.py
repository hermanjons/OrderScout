"""Keep discovery/window metadata truthful without choosing the model's task."""
from copy import deepcopy

from AI.processors.session_state import AgentSessionState, AgentTaskStep
from AI.runtime.catalog import record_discovered_tools, select_tool_menu, tool_definitions
from AI.runtime.context_window import json_bytes
from AI.runtime.contracts import AgentTool, OperationInputSource


def tool(name, **kwargs):
    return AgentTool(name=name, description=kwargs.pop("description", "Read one value."),
        parameters=kwargs.pop("parameters", {"type": "object", "properties": {}, "additionalProperties": False}),
        handler=lambda: None, domain=name.split(".")[0], **kwargs)


def state_with_loaded(*names):
    state = AgentSessionState(goal="Inspect existing evidence")
    state.active_entities["model_loop"] = {"loaded_tool_names": list(names)}
    return state


def test_menu_distinguishes_current_contracts_from_discovered_contracts_outside_window():
    registry = {name: tool(name) for name in ("operations.discover", "example.first", "example.second")}
    state = state_with_loaded()
    record_discovered_tools(state, {"operations": [
        {"exposed_tool_name": "example.first"}, {"exposed_tool_name": "example.second"}]}, registry)

    selected = select_tool_menu(registry, state, limit=2)
    metadata = state.active_entities["model_loop"]["tool_menu"]

    assert metadata["visible_tool_names"] == [row["name"] for row in tool_definitions(selected)]
    assert metadata["visible_tool_names"] == ["operations.discover", "example.first"]
    assert metadata["loaded_tool_names_not_visible"] == ["example.second"]
    assert metadata["permitted_tool_count"] == 3 and metadata["visible_tool_count"] == 2

    # Reusing a saved discovery result is sufficient to change the contract window.
    record_discovered_tools(state, {"operations": [{"exposed_tool_name": "example.second"}]}, registry)
    select_tool_menu(registry, state, limit=2)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    assert metadata["visible_tool_names"] == ["operations.discover", "example.second"]
    assert metadata["loaded_tool_names_not_visible"] == ["example.first"]


def test_menu_metadata_excludes_revoked_and_unofferable_tools():
    registry = {"operations.discover": tool("operations.discover"), "example.read": tool("example.read"),
        "example.execute": tool("example.execute", read_only=False),
        "example.delete": tool("example.delete", destructive=True)}
    state = state_with_loaded("revoked.read", "example.execute", "example.delete")
    record_discovered_tools(state, {"operations": [
        {"exposed_tool_name": name} for name in (*registry, "revoked.read")] + [
        {"exposed_tool_name": ["example.read"]}]}, registry)

    selected = select_tool_menu(registry, state, limit=2)
    metadata = state.active_entities["model_loop"]["tool_menu"]

    assert set(selected) == {"operations.discover", "example.read"}
    assert metadata["permitted_tool_count"] == metadata["visible_tool_count"] == 2
    assert metadata["loaded_tool_names_not_visible"] == []
    assert "operation_names_by_domain" not in metadata
    assert not {"revoked.read", "example.execute", "example.delete"}.intersection(metadata["visible_tool_names"])


def test_schema_window_reports_exact_bytes_and_retains_full_oversized_contract():
    discovery = tool("operations.discover")
    first = tool("example.first", description="Complete contract. " * 200)
    second = tool("example.second", description="Another contract. " * 200)
    registry = {row.name: row for row in (discovery, first, second)}
    state = state_with_loaded(second.name, first.name)
    target = sum(json_bytes(tool_definitions({row.name: row})) for row in (discovery, first))

    selected = select_tool_menu(registry, state, max_schema_bytes=target)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    assert list(selected) == [discovery.name, first.name]
    assert metadata["schema_bytes"] == json_bytes(tool_definitions(selected)) <= target
    assert metadata["schema_byte_target_exceeded"] is False

    selected = select_tool_menu(registry, state, max_schema_bytes=1000)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    assert list(selected) == [discovery.name, first.name]
    assert metadata["schema_byte_target_exceeded"] is True
    assert tool_definitions(selected)[-1]["description"] == first.description
    assert metadata["schema_bytes"] == json_bytes(tool_definitions(selected))


def test_existing_source_remains_bindable_without_reloading_its_contract():
    source = tool("data.read")
    consumer = tool("output.prepare", requires_approval=True,
        parameters={"type": "object", "properties": {"snapshot": {"type": "object"}}, "required": ["snapshot"]},
        input_source_requirements=(OperationInputSource("snapshot", (source.name,), "tool_result.snapshot"),))
    registry = {row.name: row for row in (tool("operations.discover"), source, consumer)}
    state = state_with_loaded(consumer.name)
    observed = AgentTaskStep(index=1, step_id="call_1", prompt=source.name, tool_names=[source.name],
        status="completed", verification_status="observed", result_data={"tool_result": {"snapshot": {"rows": [1, 2]}}})
    state.completed_steps.append(observed)
    original_schema, original_result = deepcopy(consumer.parameters), deepcopy(observed.result_data)

    selected = select_tool_menu(registry, state, limit=2)
    contract = next(row for row in tool_definitions(selected) if row["name"] == consumer.name)

    assert source.name not in selected and consumer.name in selected
    assert contract["parameters"]["properties"]["snapshot"]["properties"]["path"]["const"] == "tool_result.snapshot"
    assert consumer.parameters == original_schema
    assert observed.result_data == original_result


def test_empty_menu_does_not_claim_old_contracts_are_currently_available():
    state = state_with_loaded("example.read")
    assert select_tool_menu({}, state) == {}
    metadata = state.active_entities["model_loop"]["tool_menu"]
    assert metadata["visible_tool_names"] == metadata["loaded_tool_names_not_visible"] == []
    assert metadata["permitted_tool_count"] == metadata["visible_tool_count"] == 0
    assert metadata["discovery_operation"] is None


def test_discovery_burst_cannot_evict_memory_and_cancellation_from_normal_window():
    navigation = ("approvals.cancel", "conversation.read", "observations.read")
    registry = {name: tool(name) for name in ("operations.discover", *navigation)}
    for index in range(25):
        name = f"listing.operation_{index}"
        registry[name] = tool(name, description="One specific business capability. " * 35)
    state = state_with_loaded(*navigation, *[name for name in registry if name.startswith("listing.")])
    selected = select_tool_menu(registry, state, max_schema_bytes=6000)
    assert all(name in selected for name in ("operations.discover", *navigation, "listing.operation_24"))
    assert len(selected) < len(registry)
    assert state.active_entities["model_loop"]["tool_menu"]["schema_bytes"] <= 6000


def test_two_slot_transport_keeps_the_requested_business_contract_over_navigation():
    names = ("operations.discover", "approvals.cancel", "conversation.read", "observations.read", "listing.link.prepare")
    registry = {name: tool(name) for name in names}
    state = state_with_loaded("listing.link.prepare")
    selected = select_tool_menu(registry, state, limit=2)
    assert list(selected) == ["operations.discover", "listing.link.prepare"]


def test_navigation_reservation_preserves_the_full_single_oversized_contract_exception():
    names = ("operations.discover", "approvals.cancel", "conversation.read", "observations.read")
    registry = {name: tool(name) for name in names}
    oversized = tool("listing.link.prepare", description="Complete single-purpose contract. " * 250)
    registry[oversized.name] = oversized
    state = state_with_loaded(oversized.name)
    selected = select_tool_menu(registry, state, max_schema_bytes=4000)
    assert all(name in selected for name in (*names, oversized.name))
    assert state.active_entities["model_loop"]["tool_menu"]["schema_byte_target_exceeded"]
    assert tool_definitions({oversized.name: selected[oversized.name]})[0]["description"] == oversized.description


def test_compact_directory_explains_capabilities_without_loading_their_contracts():
    registry = {row.name: row for row in (
        tool("operations.discover"),
        tool("example.compose", description="Build custom tables from observed records; does not write a file."),
        tool("example.product_summary", description="Summarize product sales by quantity and revenue."),
        tool("example.profit_export.prepare", description="Prepare a single order profit workbook proposal.",
             requires_approval=True),
    )}
    state = state_with_loaded()

    selected = select_tool_menu(registry, state, limit=2)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    summaries = metadata["operation_summaries_by_domain"]["example"]

    assert list(selected) == ["operations.discover"]
    assert summaries["example.compose"] == {"description": registry["example.compose"].description, "mode": "read"}
    assert "product sales" in summaries["example.product_summary"]["description"]
    assert summaries["example.profit_export.prepare"]["mode"] == "prepare"
    assert metadata["operation_summaries_complete"] and metadata["operation_summary_count"] == len(registry)
    assert state.active_entities["model_loop"].get("loaded_tool_names", []) == []


def test_description_directory_is_bounded_and_exposes_browse_path_for_omitted_entries():
    registry = {"operations.discover": tool("operations.discover")}
    registry.update({f"large.read_{index}": tool(f"large.read_{index}", description="Read one precise capability. " * 40)
                     for index in range(40)})
    registry["small.compose"] = tool("small.compose", description="Compose observed records into a custom table.")
    state = state_with_loaded()

    select_tool_menu(registry, state, limit=2, max_summary_bytes=1000)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    summaries = metadata["operation_summaries_by_domain"]

    assert metadata["operation_summary_bytes"] == json_bytes(summaries) <= 1000
    assert not metadata["operation_summaries_complete"] and metadata["operation_summary_count"] < len(registry)
    assert "small.compose" in summaries["small"]
    assert "large.read_39" in metadata["operation_names_by_domain"]["large"]
    assert metadata["discovery_page_arguments"] == {"query": "", "include_manual": False, "limit": 16, "offset": 0}
    assert all(len(row["description"]) <= 80 for domain in summaries.values() for row in domain.values())
    assert summaries["large"]["large.read_0"]["description"].endswith("…")


def test_capability_directory_cannot_restore_revoked_or_unofferable_operations():
    registry = {name: tool(name) for name in ("operations.discover", "example.first", "example.second")}
    registry["private.execute"] = tool("private.execute", read_only=False)
    registry["private.delete"] = tool("private.delete", destructive=True)
    state = state_with_loaded("revoked.read", "private.execute")

    select_tool_menu(registry, state, limit=2)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    names = {name for rows in metadata["operation_summaries_by_domain"].values() for name in rows}

    assert names == {"operations.discover", "example.first", "example.second"}
    assert set(metadata["operation_names_by_domain"]) == {"operations", "example"}


def test_real_catalog_describes_general_reports_product_summaries_and_profit_exports():
    from AI.processors.tools import available_tools
    registry = available_tools()
    state = state_with_loaded()
    select_tool_menu(registry, state)
    metadata = state.active_entities["model_loop"]["tool_menu"]
    summaries = metadata["operation_summaries_by_domain"]

    for domain, name, mode in (("reports", "reports.build_snapshot", "read"),
        ("orders", "orders.item_sales_summary", "read"),
        ("orders", "orders.item_sales_report", "read"),
        ("orders", "orders.export_profit_excel.prepare", "prepare")):
        row = summaries[domain][name]
        assert row["description"] and row["mode"] == mode
        assert registry[name].description.startswith(row["description"].removesuffix("…"))
        assert name not in metadata["visible_tool_names"]
    assert metadata["operation_summary_bytes"] <= metadata["operation_summary_byte_target"]
