from __future__ import annotations

from AI.processors.operation_catalog import (
    build_operation_catalog, discover_operation_catalog, retrieve_operation_candidates,
)
from AI.processors.tools import AgentTool, available_tools


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
