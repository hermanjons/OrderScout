"""Model-facing tool contracts and discovery-driven transport windows.

The menu describes capabilities. Only the execution boundary grants access;
loading or describing a tool never enlarges source, child or effect authority.
"""
from __future__ import annotations

from copy import deepcopy
import json


MAX_WIRE_TOOLS = 128
DEFAULT_SCHEMA_BYTES = 16000
DEFAULT_SUMMARY_BYTES = 16000
DISCOVERY_TOOL = "operations.discover"


class ToolCatalogError(RuntimeError):
    pass


def _can_offer(tool):
    return tool.read_only and (not tool.destructive or tool.requires_approval)


def compact_operation_description(description, *, max_chars=80):
    text = " ".join(str(description or "").split())
    return text if len(text) <= max_chars else text[:max_chars - 1].rsplit(" ", 1)[0] + "…"


def _wire_parameters(tool):
    schema = deepcopy(tool.parameters)
    for requirement in tool.input_source_requirements:
        node = schema
        for segment in requirement.argument_path.split("."):
            array = segment.endswith("[]")
            key = segment[:-2] if array else segment
            node = (node.get("properties") or {}).get(key) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
            if array:
                node = node.get("items")
        if not isinstance(node, dict):
            continue
        path = {"type": "string", "minLength": 1}
        if requirement.result_path:
            path["const"] = requirement.result_path
        node.clear()
        node.update({"type": "object", "properties": {
            "$from_step": {"type": "string", "minLength": 1,
                "description": "An actual completed observations[].step_id; do not invent an ID."},
            "path": path}, "required": ["$from_step", "path"], "additionalProperties": False,
            "description": "Bind the complete stored source by reference. Do not copy or reconstruct source records. "
                "The host resolves this binding before validating and calling the domain function."})
    return schema


def tool_definitions(registry):
    definitions = []
    for name, tool in registry.items():
        if not _can_offer(tool):
            continue
        description = tool.description
        if name == DISCOVERY_TOOL:
            description += (
                "\nCurrent tool_menu.visible_tool_names already have full callable contracts; use them directly. "
                "For a missing contract, copy its exact operation name from the directory and query it with limit=1. "
                "Dotted operation IDs use exact lookup: exact_match_found=false means no such permitted contract; "
                "suggested_operations are related names, not loaded contracts. Search with words or browse a domain instead of inventing names. "
                "Returned operations can exceed the next menu's capacity; check visible_tool_names before rediscovering. "
                "Stored result bindings remain usable when a source tool's schema leaves the menu.")
        if tool.requires_approval:
            description += ("\nPrepare only: this call creates a read-only proposal and needs no separate approval. "
                            "Execution requires the user's exact current approval after the proposal exists.")
        fields = (tool.result_schema or {}).get("properties") or {}
        if fields:
            description += "\nOutput fields: " + ", ".join(fields)
        if tool.input_source_requirements:
            description += "\nRequires completed-source bindings: " + json.dumps(
                [row.to_dict() for row in tool.input_source_requirements], ensure_ascii=False)
        definitions.append({"name": name, "description": description, "parameters": _wire_parameters(tool)})
    return definitions


def record_discovered_tools(state, payload, registry):
    names = state.active_entities["model_loop"].setdefault("loaded_tool_names", [])
    # Search results are best-first. Keep that ranking when the next bounded
    # menu consumes the most recently discovered names first.
    for descriptor in reversed(payload.get("operations") or []):
        if not isinstance(descriptor, dict):
            continue
        name = descriptor.get("exposed_tool_name")
        if not isinstance(name, str) or name not in registry or not _can_offer(registry[name]):
            continue
        if name in names:
            names.remove(name)
        names.append(name)


def select_tool_menu(registry, state, *, limit=MAX_WIRE_TOOLS, max_schema_bytes=DEFAULT_SCHEMA_BYTES,
                     max_summary_bytes=DEFAULT_SUMMARY_BYTES):
    from AI.runtime.context_window import json_bytes
    registry = {name: tool for name, tool in registry.items() if _can_offer(tool)}
    sizes = {name: json_bytes(tool_definitions({name: tool})) for name, tool in registry.items()}
    needs_discovery = len(registry) > limit or sum(sizes.values()) > max_schema_bytes
    if not needs_discovery:
        selected = dict(registry)
    else:
        if DISCOVERY_TOOL not in registry or limit < 2:
            raise ToolCatalogError("A large tool catalog requires the permitted discovery operation")
        names = [DISCOVERY_TOOL]
        loaded = state.active_entities["model_loop"].get("loaded_tool_names") or []

        # Navigation/control contracts must survive a burst of business-tool
        # discovery. Otherwise inspecting a saved result needs more discovery,
        # which evicts other contracts and can become a lookup-only loop.
        # Resolving a named store is foundational navigation too; offering this
        # permitted contract never executes a read or selects a store for the model.
        navigation = ("approvals.cancel", "conversation.read", "observations.read", "marketplaces.account_lookup")
        requested = [name for name in reversed(loaded)
                     if name in registry and name != DISCOVERY_TOOL and name not in navigation]
        reserve_loaded = int(bool(requested))
        for name in navigation:
            if (name in registry and len(names) < limit - reserve_loaded
                    and sum(sizes[key] for key in names) + sizes[name] <= max_schema_bytes):
                names.append(name)

        # Most recently discovered contracts get the next menu. Existing
        # observations remain bindable even after a schema leaves this window.
        added_loaded = False
        for name in requested:
            if (name in registry and name not in names and len(names) < limit
                    and (sum(sizes[key] for key in names) + sizes[name] <= max_schema_bytes
                         or not added_loaded)):
                # At least one explicitly discovered contract must fit even if
                # it alone exceeds the target. Never truncate that contract.
                names.append(name)
                added_loaded = True
        # Producer IDs are alternatives, not an AND-dependency closure. A report
        # may bind a source already observed. Do not hide its callable contract
        # just because all possible producers cannot fit into a local menu.
        for name in list(names):
            for requirement in registry[name].input_source_requirements:
                if any(row.status == "completed" and any(tool in requirement.producer_operation_ids
                    for tool in row.tool_names) for row in state.completed_steps):
                    continue
                for producer in requirement.producer_operation_ids:
                    if (producer in registry and producer not in names and len(names) < limit
                            and sum(sizes[key] for key in names) + sizes[producer] <= max_schema_bytes):
                        names.append(producer)
                        break
        selected = {name: registry[name] for name in names}
    schema_bytes = json_bytes(tool_definitions(selected))
    state.active_entities["model_loop"]["tool_menu"] = {
        "permitted_tool_count": len(registry), "visible_tool_count": len(selected),
        "visible_tool_names": list(selected),
        "loaded_tool_names_not_visible": list(dict.fromkeys(name for name in reversed(
            state.active_entities["model_loop"].get("loaded_tool_names") or [])
            if name in registry and name not in selected)),
        "catalog_requires_discovery": needs_discovery,
        "schema_bytes": schema_bytes, "schema_byte_target": max_schema_bytes,
        "schema_byte_target_exceeded": schema_bytes > max_schema_bytes,
        "discovery_operation": DISCOVERY_TOOL if DISCOVERY_TOOL in registry else None}
    if needs_discovery:
        # Compact directory lets the model ask for exact contracts rather than
        # guessing a broad business keyword. Full schemas still use discovery.
        directory = {}
        for name, tool in registry.items():
            directory.setdefault(tool.domain or "general", []).append(name)
        metadata = state.active_entities["model_loop"]["tool_menu"]
        metadata["operation_names_by_domain"] = directory
        # The name directory is an index, not enough information to choose
        # between capabilities. Offer bounded descriptions across all domains
        # without ranking them against the user's message or executing work.
        summaries = {}
        for index in range(max((len(names) for names in directory.values()), default=0)):
            for domain, domain_names in directory.items():
                if index >= len(domain_names):
                    continue
                name = domain_names[index]
                tool = registry[name]
                row = {"description": compact_operation_description(tool.description),
                       "mode": "prepare" if tool.requires_approval else "read"}
                candidate = {key: dict(value) for key, value in summaries.items()}
                candidate.setdefault(domain, {})[name] = row
                if json_bytes(candidate) <= max(2, max_summary_bytes):
                    summaries = candidate
        summary_count = sum(len(rows) for rows in summaries.values())
        metadata.update({"operation_summaries_by_domain": summaries,
            "operation_summary_count": summary_count,
            "operation_summaries_complete": summary_count == len(registry),
            "operation_summary_bytes": json_bytes(summaries),
            "operation_summary_byte_target": max(2, max_summary_bytes),
            "discovery_page_arguments": {"query": "", "include_manual": False, "limit": 16, "offset": 0}})
    return selected
