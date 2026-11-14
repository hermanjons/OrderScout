"""Operation identities and capability descriptions must not imply authority."""
from __future__ import annotations

from AI.processors.operation_catalog import (
    build_operation_catalog, discover_operation_catalog, retrieve_operation_candidates,
)
from AI.processors.tools import AgentTool, available_tools
from AI.processors.session_state import AgentSessionState
from AI.runtime.catalog import record_discovered_tools, select_tool_menu


def _unused_handler(**_kwargs):
    raise AssertionError("Discovery must not execute discovered operations")


def _registry():
    return {
        name: AgentTool(name=name, description="Research operation", domain="web",
                        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
                        result_schema={"type": "object", "properties": {"value": {"type": "string"}}},
                        handler=_unused_handler)
        for name in ("web.alpha", "web.beta", "web.gamma")
    }


def test_discovery_browses_with_stable_pagination_and_never_executes():
    first = discover_operation_catalog(domains=["web"], limit=2, tools=_registry())
    second = discover_operation_catalog(domains=["web"], limit=2, offset=first["next_offset"], tools=_registry())

    assert [row["operation_id"] for row in first["operations"]] == ["web.alpha", "web.beta"]
    assert [row["operation_id"] for row in second["operations"]] == ["web.gamma"]
    assert first["has_more"] and first["next_offset"] == 2
    assert second["has_more"] is False and second["next_offset"] is None
    assert first["available_operation_count"] == 3
    assert first["discovery_grants_execution_permission"] is False


def test_discovery_search_pages_do_not_repeat_ranked_operations():
    first = discover_operation_catalog(query="research", limit=2, tools=_registry())
    second = discover_operation_catalog(query="research", limit=2, offset=first["next_offset"], tools=_registry())
    assert len(first["operations"]) == 2
    assert len(second["operations"]) == 1
    assert not ({row["operation_id"] for row in first["operations"]}
                & {row["operation_id"] for row in second["operations"]})


def test_discovery_unknown_domain_and_empty_registry_do_not_fall_back_to_all_tools():
    unknown = discover_operation_catalog(domains=["absent"], tools=_registry())
    assert unknown["operations"] == []
    assert unknown["unknown_domains"] == ["absent"]
    assert unknown["available_domains"] == ["web"]
    assert build_operation_catalog({}, include_manual=False) == {}
    assert retrieve_operation_candidates("research", catalog={}) == []
    assert discover_operation_catalog(tools={})["operations"] == []


def test_registered_discovery_exposes_executable_web_contracts_and_approval_metadata():
    tool = available_tools()["operations.discover"]
    result = tool.handler(domains=["web"], limit=32)
    assert result.success, result.message
    assert tool.read_only and not tool.requires_approval
    operations = {row["operation_id"]: row for row in result.data["operations"]}
    opened = operations["web.open"]["operation_metadata"]
    export = operations["web.research_report_xlsx.prepare"]["operation_metadata"]

    assert opened["input_schema"]["required"] == ["url"]
    observed = opened["output_schema"]["properties"]["web_observation"]["properties"]
    assert {"observation_id", "relevant_text", "content_hash", "links"} <= set(observed)
    assert observed["links"]["items"]["properties"]["url"]["type"] == "string"
    assert opened["effect_class"] == "read" and opened["approval_policy"] == "none"
    assert export["effect_class"] == "local_effect"
    assert export["approval_policy"] == "prepare_then_confirm"
    assert operations["web.research_report_xlsx.prepare"]["exposed_tool_name"] == "web.research_report_xlsx.prepare"


def test_discovery_preserves_atomic_and_manual_binding_distinction():
    discovered = discover_operation_catalog(domains=["orders"], include_manual=True, limit=32)
    kinds = {row["binding_kind"] for row in discovered["operations"]}
    assert "manual_capability" in kinds
    manual = next(row for row in discovered["operations"] if row["binding_kind"] == "manual_capability")
    assert manual["exposed_tool_name"] in {"operations.manual_action.read", "operations.manual_action.prepare"}
    assert "input_schema" in manual["operation_metadata"]


def operation(name, description="Read registered information.", **kwargs):
    return AgentTool(name=name, description=description,
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda: (_ for _ in ()).throw(AssertionError("Discovery executed a tool")),
        domain=kwargs.pop("domain", name.split(".")[0]), **kwargs)


def test_exact_identity_lookup_keeps_prepare_contract_over_a_related_read():
    producer = operation("example.widget_report", "Read the widget report and xlsx prepare information.")
    prepare = operation("example.widget_report_xlsx.prepare", "Prepare an export proposal.",
        requires_approval=True, action_type="prepare_write")
    registry = {row.name: row for row in (producer, prepare)}

    result = discover_operation_catalog(query=prepare.name, limit=1, tools=registry)

    assert result["lookup_mode"] == "exact" and result["exact_match_found"] is True
    assert [row["operation_id"] for row in result["operations"]] == [prepare.name]
    assert result["suggested_operations"] == []
    assert not result["has_more"] and result["next_page_arguments"] is None
    assert result["discovery_grants_execution_permission"] is False


def test_unknown_exact_name_returns_no_contract_and_does_not_load_its_suggestion():
    names = ("operations.discover", "example.widget_report", "example.other_read")
    registry = {name: operation(name) for name in names}
    state = AgentSessionState(goal="Inspect capabilities")
    state.active_entities["model_loop"] = {}

    result = discover_operation_catalog(query="example.widget_report_xlsx.prepare", limit=1, tools=registry)
    record_discovered_tools(state, result, registry)

    assert result["lookup_mode"] == "exact" and result["exact_match_found"] is False
    assert result["operations"] == [] and result["returned_count"] == 0
    assert result["suggested_operations"][0]["operation_id"] == "example.widget_report"
    assert result["suggestions_are_callable_contracts"] is False
    assert all("operation_metadata" not in row for row in result["suggested_operations"])
    assert state.active_entities["model_loop"]["loaded_tool_names"] == []
    assert list(select_tool_menu(registry, state, limit=2)) == ["operations.discover"]


def test_exact_lookup_respects_domain_and_registry_boundaries():
    registry = {name: operation(name) for name in ("example.read", "private.read")}

    result = discover_operation_catalog(query="private.read", domains=["example"], tools=registry)

    assert result["exact_match_found"] is False and result["operations"] == []
    assert all(row["owner_domain"] == "example" for row in result["suggested_operations"])
    # A tool removed by the authorized registry is absent from suggestions too.
    del registry["private.read"]
    result = discover_operation_catalog(query="private.read", tools=registry)
    assert result["exact_match_found"] is False
    assert "private.read" not in [row["operation_id"] for row in result["suggested_operations"]]


def test_word_search_and_domain_browse_retain_explicit_pagination():
    registry = {f"example.read_{index}": operation(f"example.read_{index}", "Read widget records.")
                for index in range(5)}
    for query, mode in (("widget records", "search"), ("", "browse")):
        result = discover_operation_catalog(query=query, domains=["example"], limit=2, tools=registry)
        second = discover_operation_catalog(**result["next_page_arguments"], tools=registry)
        combined = discover_operation_catalog(query=query, domains=["example"], limit=4, tools=registry)

        assert result["lookup_mode"] == mode and result["exact_match_found"] is None
        assert result["next_page_arguments"] == {"query": query, "domains": ["example"],
            "include_manual": False, "limit": 2, "offset": 2}
        assert result["operations"] + second["operations"] == combined["operations"]
