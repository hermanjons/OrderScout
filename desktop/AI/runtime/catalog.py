"""Model-facing tool contracts and discovery-driven transport windows.

The menu describes capabilities. Only the execution boundary grants access;
loading or describing a tool never enlarges source, child or effect authority.
"""
from __future__ import annotations

from copy import deepcopy
import json


MAX_WIRE_TOOLS = 128
DISCOVERY_TOOL = "operations.discover"


class ToolCatalogError(RuntimeError):
    pass


def tool_definitions(registry):
    definitions = []
    for name, tool in registry.items():
        if not tool.read_only or tool.destructive and not tool.requires_approval:
            continue
        description = tool.description
        if tool.requires_approval:
            description += "\nPrepare only; execution requires the user's exact current approval."
        fields = (tool.result_schema or {}).get("properties") or {}
        if fields:
            description += "\nOutput fields: " + ", ".join(fields)
        if tool.input_source_requirements:
            description += "\nRequires completed-source bindings: " + json.dumps(
                [row.to_dict() for row in tool.input_source_requirements], ensure_ascii=False)
        definitions.append({"name": name, "description": description, "parameters": deepcopy(tool.parameters)})
    return definitions


def record_discovered_tools(state, payload, registry):
    names = state.active_entities["model_loop"].setdefault("loaded_tool_names", [])
    for descriptor in payload.get("operations") or []:
        if not isinstance(descriptor, dict):
            continue
        name = descriptor.get("exposed_tool_name")
        if name not in registry:
            continue
        if name in names:
            names.remove(name)
        names.append(name)


def select_tool_menu(registry, state, *, limit=MAX_WIRE_TOOLS):
    if len(registry) <= limit:
        selected = dict(registry)
    else:
        if DISCOVERY_TOOL not in registry or limit < 2:
            raise ToolCatalogError("A large tool catalog requires the permitted discovery operation")
        names = [DISCOVERY_TOOL]
        if "approvals.cancel" in registry:
            names.append("approvals.cancel")
        loaded = state.active_entities["model_loop"].get("loaded_tool_names") or []

        def prerequisites(name, visited=None):
            visited = set() if visited is None else visited
            if name in visited or name not in registry:
                return []
            visited.add(name)
            result = []
            for requirement in registry[name].input_source_requirements:
                for producer in requirement.producer_operation_ids:
                    result.extend(prerequisites(producer, visited))
            return result + [name]

        # Most recently discovered contracts get the next menu. Existing
        # observations remain bindable even after a schema leaves this window.
        for name in reversed(loaded):
            group = [item for item in prerequisites(name) if item not in names]
            if len(names) + len(group) <= limit:
                names.extend(group)
        selected = {name: registry[name] for name in names}
    state.active_entities["model_loop"]["tool_menu"] = {
        "permitted_tool_count": len(registry), "visible_tool_count": len(selected),
        "catalog_requires_discovery": len(registry) > limit,
        "discovery_operation": DISCOVERY_TOOL if DISCOVERY_TOOL in registry else None}
    return selected
