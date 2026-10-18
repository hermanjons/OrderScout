from __future__ import annotations

from AI.processors.operation_catalog import (
    build_operation_catalog,
    close_operation_prerequisites,
    discover_operation_catalog,
    retrieve_operation_candidates,
)
from AI.processors.tools import AgentTool, OperationInputSource, available_tools


def _unused_handler(**_kwargs):
    raise AssertionError("Catalog closure must never execute an operation")


def _tool(name, *, producers=(), required=True, domain="general", effectful=False):
    return AgentTool(
        name=name, description="Ranked export operation", domain=domain,
        parameters={"type": "object", "properties": {}}, handler=_unused_handler,
        requires_approval=effectful, action_type="prepare_write" if effectful else "read",
        input_source_requirements=(OperationInputSource(
            "snapshot", producer_operation_ids=tuple(producers), required=required,
        ),) if producers else (),
    )


def _catalog(*tools):
    return build_operation_catalog({tool.name: tool for tool in tools}, include_manual=False)


def _names(entries):
    return [entry.name for entry in entries]


def test_ranked_consumer_keeps_its_required_unranked_producer_inside_bound():
    # The producer has no lexical match. Its presence must come only from the
    # canonical dependency metadata, regardless of names or business domains.
    producer = _tool("research.assemble", domain="web")
    producer = AgentTool(
        **{**producer.__dict__, "description": "Immutable observations"},
    )
    consumer = _tool("artifacts.emit", producers=(producer.name,), domain="reports", effectful=True)
    catalog = _catalog(consumer, producer, *[_tool(f"ranked.filler_{i}") for i in range(20)])
    ranked = retrieve_operation_candidates("artifacts.emit export", catalog=catalog, limit=20)
    assert consumer.name == ranked[0].name
    assert producer.name not in _names(ranked)

    closed = close_operation_prerequisites(_names(ranked), catalog=catalog, limit=20)
    assert _names(closed)[:2] == [consumer.name, producer.name]
    assert len(closed) == 20
    assert len(set(_names(closed))) == 20
    assert catalog[consumer.name].metadata.approval_policy == "prepare_then_confirm"


def test_transitive_shared_producers_preserve_priority_and_reserve_discovery():
    catalog = _catalog(
        _tool("output.first", producers=("middle.snapshot",), effectful=True),
        _tool("output.second", producers=("middle.snapshot",), effectful=True),
        _tool("middle.snapshot", producers=("data.read",)), _tool("data.read"),
        _tool("operations.discover"), _tool("irrelevant.tail"),
    )
    closed = close_operation_prerequisites(
        ["output.first", "output.second", "irrelevant.tail", "output.first"],
        catalog=catalog, limit=5, mandatory_operation_ids=("operations.discover",),
    )
    assert _names(closed) == [
        "output.first", "middle.snapshot", "data.read", "output.second", "operations.discover",
    ]


def test_insufficient_bound_omits_consumer_instead_of_exposing_missing_schema():
    catalog = _catalog(_tool("output.emit", producers=("data.build",)),
                       _tool("data.build"), _tool("operations.discover"))
    closed = close_operation_prerequisites(
        ["output.emit"], catalog=catalog, limit=2,
        mandatory_operation_ids=("operations.discover",),
    )
    assert _names(closed) == ["operations.discover"]


def test_closure_never_expands_the_callers_allowed_operation_surface():
    catalog = _catalog(_tool("output.emit", producers=("private.read",)),
                       _tool("private.read", domain="private"), _tool("data.safe"))
    closed = close_operation_prerequisites(
        ["output.emit", "data.safe"], catalog=catalog,
        allowed_operation_ids={"output.emit", "data.safe"},
    )
    assert _names(closed) == ["data.safe"]
    assert close_operation_prerequisites(["data.safe"], catalog=catalog,
                                         allowed_operation_ids=set()) == []


def test_missing_cyclic_and_effectful_read_producers_are_fail_closed():
    catalog = _catalog(
        _tool("broken.missing", producers=("absent.read",)),
        _tool("cycle.first", producers=("cycle.second",)),
        _tool("cycle.second", producers=("cycle.first",)),
        _tool("broken.effect", producers=("danger.write",)),
        _tool("danger.write", effectful=True), _tool("data.safe"),
    )
    closed = close_operation_prerequisites(
        ["broken.missing", "cycle.first", "broken.effect", "data.safe"], catalog=catalog,
    )
    assert _names(closed) == ["data.safe"]


def test_deep_graph_is_bounded_and_optional_producers_do_not_require_visibility():
    chain = [_tool(f"chain.{i}", producers=(f"chain.{i + 1}",)) for i in range(80)]
    catalog = _catalog(*chain, _tool("chain.80"),
                       _tool("optional.emit", producers=("absent.read",), required=False))
    assert close_operation_prerequisites(["chain.0"], catalog=catalog, limit=64) == []
    assert _names(close_operation_prerequisites(["optional.emit"], catalog=catalog, limit=1)) == ["optional.emit"]


def test_actual_export_dependency_contract_exposes_builder_schema_without_handlers():
    tools = available_tools()
    catalog = build_operation_catalog(tools, include_manual=False)
    closed = close_operation_prerequisites(["reports.xlsx.prepare"], catalog=catalog, limit=2)
    assert _names(closed) == ["reports.xlsx.prepare", "reports.build_snapshot"]
    payload = closed[0].to_dict()
    assert payload["input_source_requirements"] == [{
        "argument_path": "report_snapshot",
        "producer_operation_ids": ["reports.build_snapshot"],
        "result_path": "tool_result.report_snapshot", "required": True,
        "producer_effect_class": "read", "binding_kind": "completed_step_output",
    }]
    builder_schema = closed[1].metadata.input_schema
    assert {"sources", "sheets"} <= set(builder_schema["required"])
    assert closed[0].metadata.approval_policy == "prepare_then_confirm"
    assert closed[1].metadata.effect_class == "read"
    # Generic source contracts describe trusted completed reads without forcing
    # every possible read operation into the limited catalog.
    for name in ("reports.build_snapshot", "analysis.calculate", "analysis.table"):
        requirement = catalog[name].to_dict()["input_source_requirements"][0]
        assert requirement["argument_path"] == "sources[].result"
        assert requirement["producer_operation_ids"] == []
        assert requirement["result_path"] == "tool_result"


def test_discovery_publishes_source_contract_without_granting_execution_permission():
    result = discover_operation_catalog(query="reports.xlsx.prepare", domains=["reports"], limit=32)
    export = next(row for row in result["operations"] if row["operation_id"] == "reports.xlsx.prepare")
    assert export["input_source_requirements"][0]["producer_operation_ids"] == ["reports.build_snapshot"]
    assert result["discovery_grants_execution_permission"] is False
