from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from Core.processors.operation_contracts import OperationMetadata

from AI.processors.manual_capabilities import (
    MANUAL_EXECUTE_ADAPTERS,
    find_manual_capability,
    list_manual_capabilities,
    manual_execute_blockers,
    manual_read_blockers,
)
from AI.processors.tools import AgentTool, OperationInputSource, available_tools


_SUPERSEDED_MANUAL_CAPABILITIES = {
    # Raw marketplace fetch is an internal stage of the public sync action. It
    # remains visible in inventory, but the agent must use the typed, approved
    # fetch+persist operation instead of exposing the unsafe half-operation.
    "orders.fetch_orders_all": "orders.get_orders_from_companies",
}


_GENERIC_QUERY_TOKENS = frozenset(
    {
        "bir",
        "bu",
        "icin",
        "ile",
        "ne",
        "ve",
        "ver",
        "bana",
        "goster",
        "getir",
        "yap",
    }
)

_TOKEN_ALIASES = {
    "sayi": {"count", "adet", "sayisi", "toplam", "kac"},
    "siparis": {"order", "orders", "paket"},
    "iade": {"return", "returns", "claim"},
    "urun": {"product", "item", "kalem"},
    "satis": {"sales", "sold", "satan"},
    "neden": {"reason", "sebep"},
    "etiket": {"label", "labels", "print", "create", "olustur", "yazdir"},
    "kargo": {"cargo", "shipping"},
    "bekleyen": {"ready", "waiting", "pending"},
    "ozet": {"summary", "aggregate", "dagilim"},
    "secili": {"selected", "selection", "bunlar", "bunlari"},
    "excel": {"xlsx", "export", "report"},
    "senkronize": {
        "senkron",
        "sync",
        "synchronize",
        "fetch",
        "cek",
        "yenile",
        "guncelle",
        "guncel",
    },
    "kaydet": {"save", "persist", "write"},
    "detay": {"detail", "details", "context", "full", "baglam"},
}

_EFFECT_INTENT_TOKENS = frozenset(
    {
        "create",
        "update",
        "delete",
        "approve",
        "change",
        "write",
        "olustur",
        "guncelle",
        "sil",
        "onay",
        "degistir",
        "yazdir",
        "fetch",
        "sync",
        "synchronize",
        "save",
        "persist",
        "cek",
        "kaydet",
        "yenile",
        "senkronize",
    }
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    text = _text(value).casefold().replace("ı", "i")
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(value: Any, *, expand_aliases: bool = True) -> set[str]:
    base = {
        token
        for token in _normalized(value).split()
        if len(token) > 1 and token not in _GENERIC_QUERY_TOKENS
    }
    expanded = set(base)
    for token in tuple(base):
        for stem in (
            "siparis",
            "iade",
            "urun",
            "satis",
            "sayi",
            "neden",
            "etiket",
            "kargo",
            "bekleyen",
            "secili",
            "detay",
            "baglam",
            "senkron",
            "kaydet",
            "guncel",
            "yenile",
        ):
            if token.startswith(stem):
                expanded.add(stem)
    if expand_aliases:
        for canonical, aliases in _TOKEN_ALIASES.items():
            group = {canonical, *aliases}
            if expanded.intersection(group):
                expanded.update(group)
    return expanded


def operation_metadata_for_agent_tool(tool: AgentTool) -> OperationMetadata:
    effectful = bool(tool.requires_approval or tool.action_type != "read")
    risk_map = {"low": "R0", "medium": "R1", "high": "R2", "critical": "R3"}
    risk_level = risk_map.get(_text(tool.risk_level).casefold(), "R1" if effectful else "R0")
    if not effectful:
        risk_level = "R0"
    effect_class = "read"
    if effectful:
        effect_class = "external_mutation" if risk_level in {"R2", "R3"} else "local_effect"
    return OperationMetadata(
        name=tool.name,
        version="1.0",
        owner_domain=tool.domain,
        effect_class=effect_class,
        input_schema=dict(tool.parameters or {}),
        output_schema=dict(tool.result_schema or {"type": "object", "additionalProperties": True}),
        environment_scope=("local", "production", "stage") if effectful else ("local",),
        account_scope="runtime_resolved",
        risk_level=risk_level,
        approval_policy="none" if not effectful else "prepare_then_confirm",
        idempotency="safe" if not effectful else "operation_defined",
        retry_behavior="safe" if not effectful else "never_without_idempotency",
        supports_prepare=effectful,
        supports_execute=True,
        supports_verify=effectful,
        supports_cancellation=True,
        supports_progress=True,
        sensitive_fields=("credentials", "api_key", "api_secret", "token", "password"),
    )


@dataclass(frozen=True)
class OperationCatalogEntry:
    metadata: OperationMetadata
    description: str
    binding_kind: str
    canonical_callable: str
    exposed_tool_name: str
    input_source_requirements: tuple[OperationInputSource, ...] = ()

    @property
    def name(self) -> str:
        return self.metadata.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "binding_kind": self.binding_kind,
            "canonical_callable": self.canonical_callable,
            "exposed_tool_name": self.exposed_tool_name,
            "operation_metadata": self.metadata.to_dict(),
            "input_source_requirements": [row.to_dict() for row in self.input_source_requirements],
        }


def build_operation_catalog(
    tools: dict[str, AgentTool] | None = None,
    *,
    include_manual: bool = True,
) -> dict[str, OperationCatalogEntry]:
    registry = tools if tools is not None else available_tools()
    entries: dict[str, OperationCatalogEntry] = {}
    for name, tool in registry.items():
        callable_name = _text(tool.canonical_callable) or (
            f"{tool.handler.__module__}.{getattr(tool.handler, '__name__', type(tool.handler).__name__)}"
        )
        entries[name] = OperationCatalogEntry(
            metadata=operation_metadata_for_agent_tool(tool),
            description=_text(tool.description),
            binding_kind="agent_tool",
            canonical_callable=callable_name,
            exposed_tool_name=name,
            input_source_requirements=tuple(tool.input_source_requirements),
        )
    if include_manual:
        for capability in list_manual_capabilities():
            if capability.capability_id in entries:
                continue
            canonical_callable = MANUAL_EXECUTE_ADAPTERS.get(
                capability.capability_id,
                f"{capability.module_path}.{capability.function_name}",
            )
            entries[capability.capability_id] = OperationCatalogEntry(
                metadata=capability.operation_metadata(),
                description=(
                    f"Manual {capability.domain} capability: {capability.function_name}. "
                    f"Mode={capability.mode}; required={','.join(capability.required_parameters) or '-'}"
                ),
                binding_kind="manual_capability",
                canonical_callable=canonical_callable,
                exposed_tool_name=(
                    "operations.manual_action.prepare"
                    if capability.mode == "write"
                    else "operations.manual_action.read"
                ),
            )
    return dict(sorted(entries.items()))


def close_operation_prerequisites(
    operation_ids: list[str],
    *,
    catalog: dict[str, OperationCatalogEntry],
    limit: int = 20,
    mandatory_operation_ids: tuple[str, ...] = (),
    allowed_operation_ids: set[str] | None = None,
) -> list[OperationCatalogEntry]:
    """Bound a ranked catalog while keeping required producer schemas visible.

    The caller supplies its already authorized operation surface. Dependency
    closure never expands that surface or executes an operation. A consumer
    whose complete producer graph is unavailable, cyclic or too large is
    omitted instead of exposing a contract the planner cannot safely satisfy.
    Ranked consumers keep their order; producers use registry declaration order.
    Mandatory control operations reserve capacity before ranked candidates.
    """
    bound = max(1, min(64, int(limit or 20)))
    allowed = set(catalog) if allowed_operation_ids is None else set(allowed_operation_ids)

    def closure(name: str, visiting: set[str]) -> list[str] | None:
        if name not in allowed or name not in catalog or name in visiting or len(visiting) >= bound:
            return None
        entry = catalog[name]
        result = [name]
        for requirement in entry.input_source_requirements:
            if not requirement.required:
                continue
            for producer_id in requirement.producer_operation_ids:
                producer = catalog.get(producer_id)
                if (producer is None or (
                    requirement.producer_effect_class
                    and producer.metadata.effect_class != requirement.producer_effect_class
                )):
                    return None
                dependencies = closure(producer_id, {*visiting, name})
                if dependencies is None:
                    return None
                for dependency in dependencies:
                    if dependency not in result:
                        result.append(dependency)
                        if len(result) > bound:
                            return None
        return result

    mandatory: list[str] = []
    for name in mandatory_operation_ids:
        dependencies = closure(_text(name), set())
        if dependencies is None:
            continue
        additions = [item for item in dependencies if item not in mandatory]
        if len(mandatory) + len(additions) <= bound:
            mandatory.extend(additions)

    selected: list[str] = []
    for name in dict.fromkeys(_text(item) for item in operation_ids if _text(item)):
        if name in mandatory:
            continue
        dependencies = closure(name, set())
        if dependencies is None:
            continue
        additions = [item for item in dependencies if item not in selected and item not in mandatory]
        if len(selected) + len(mandatory) + len(additions) <= bound:
            selected.extend(additions)
    return [catalog[name] for name in [*selected, *mandatory]]


def retrieve_operation_candidates(
    query: str,
    *,
    catalog: dict[str, OperationCatalogEntry] | None = None,
    domains: set[str] | None = None,
    binding_kinds: set[str] | None = None,
    limit: int = 16,
    offset: int = 0,
) -> list[OperationCatalogEntry]:
    entries = catalog if catalog is not None else build_operation_catalog()
    query_tokens = _tokens(query)
    normalized_query = _normalized(query)
    clean_domains = {_normalized(value) for value in set(domains or set()) if _normalized(value)}
    clean_binding_kinds = {_text(value) for value in set(binding_kinds or set()) if _text(value)}
    scored: list[tuple[int, str, OperationCatalogEntry]] = []
    for entry in entries.values():
        if clean_domains and _normalized(entry.metadata.owner_domain) not in clean_domains:
            continue
        if clean_binding_kinds and entry.binding_kind not in clean_binding_kinds:
            continue
        searchable = " ".join(
            (
                entry.name,
                entry.description,
                entry.metadata.owner_domain,
                " ".join(entry.metadata.record_ref_types),
                " ".join(dict(entry.metadata.input_schema.get("properties") or {}).keys()),
            )
        )
        # Alias expansion belongs to the user's wording. Expanding the catalog
        # side as well makes every operation sharing one broad noun inherit all
        # sibling verbs (for example a label "mark" operation looking like a
        # label "create/print" operation), which destroys capability precision.
        candidate_tokens = _tokens(searchable, expand_aliases=False)
        overlap = query_tokens.intersection(candidate_tokens)
        score = len(overlap) * 12
        operation_tail = _normalized(entry.name.replace(".", " "))
        if operation_tail and operation_tail in normalized_query:
            score += 80
        domain = _normalized(entry.metadata.owner_domain)
        if domain and domain in query_tokens:
            score += 20
        if "selected" in candidate_tokens and query_tokens.intersection({"selected", "selection", "secili", "bunlar", "bunlari"}):
            score += 24
        if "aggregate" in candidate_tokens or "summary" in candidate_tokens:
            if query_tokens.intersection({"summary", "aggregate", "ozet", "dagilim", "satan", "sales"}):
                score += 22
        if (
            entry.metadata.effect_class != "read"
            and not query_tokens.intersection(_EFFECT_INTENT_TOKENS)
        ):
            score -= 20
        if score > 0:
            scored.append((score, entry.name, entry))
    scored.sort(key=lambda row: (-row[0], row[1]))
    start = max(0, int(offset or 0))
    return [row[2] for row in scored[start : start + max(1, min(64, int(limit or 16)))]]


def discover_operation_catalog(
    *,
    query: str = "",
    domains: list[str] | None = None,
    include_manual: bool = False,
    limit: int = 16,
    offset: int = 0,
    tools: dict[str, AgentTool] | None = None,
) -> dict[str, Any]:
    """Expose executable contracts so a model can discover its next operation.

    Discovery describes the registered environment. It neither infers a user
    intent nor grants permission to run a discovered operation.
    """
    catalog = build_operation_catalog(tools, include_manual=include_manual)
    available_domains = sorted({entry.metadata.owner_domain for entry in catalog.values()})
    clean_domains = {_normalized(value) for value in domains or [] if _normalized(value)}
    filtered = {
        name: entry for name, entry in catalog.items()
        if not clean_domains or _normalized(entry.metadata.owner_domain) in clean_domains
    }
    page_size = max(1, min(32, int(limit or 16)))
    start = max(0, int(offset or 0))
    if _text(query):
        page = retrieve_operation_candidates(
            query, catalog=filtered, limit=page_size + 1, offset=start,
        )
    else:
        page = list(filtered.values())[start : start + page_size + 1]
    has_more = len(page) > page_size
    operations = [{"operation_id": entry.name, **entry.to_dict()} for entry in page[:page_size]]
    return {
        "query": _text(query),
        "domains": sorted(clean_domains),
        "include_manual": bool(include_manual),
        "operations": operations,
        "available_domains": available_domains,
        "unknown_domains": sorted(clean_domains.difference(_normalized(value) for value in available_domains)),
        "available_operation_count": len(filtered),
        "returned_count": len(operations),
        "offset": start,
        "next_offset": start + len(operations) if has_more else None,
        "has_more": has_more,
        "discovery_grants_execution_permission": False,
    }


def retrieve_agent_tools(
    query: str,
    tools: dict[str, AgentTool],
    *,
    limit: int = 16,
) -> dict[str, AgentTool]:
    catalog = build_operation_catalog(tools, include_manual=False)
    entries = retrieve_operation_candidates(
        query,
        catalog=catalog,
        binding_kinds={"agent_tool"},
        limit=limit,
    )
    return {
        entry.name: tools[entry.name]
        for entry in entries
        if entry.name in tools
    }


def planner_manual_operation_payload(
    query: str,
    *,
    domains: set[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return bounded typed manual capabilities without exposing fuzzy routing."""

    entries = retrieve_operation_candidates(
        query,
        domains=domains,
        binding_kinds={"manual_capability"},
        limit=limit,
    )
    return [
        {
            "operation_id": entry.name,
            "owner_domain": entry.metadata.owner_domain,
            "effect_class": entry.metadata.effect_class,
            "input_schema": dict(entry.metadata.input_schema or {}),
            "record_ref_types": list(entry.metadata.record_ref_types),
            "risk_level": entry.metadata.risk_level,
            "approval_policy": entry.metadata.approval_policy,
            "exposed_tool": entry.exposed_tool_name,
            "canonical_callable": entry.canonical_callable,
        }
        for entry in entries
    ]


def operation_catalog_parity_report(
    *,
    domain: str = "",
    tools: dict[str, AgentTool] | None = None,
) -> dict[str, Any]:
    """Machine-check manual/UI and AI bindings against one canonical callable."""

    registry = tools or available_tools()
    clean_domain = _normalized(domain)
    catalog = build_operation_catalog(registry)
    manual_rows: list[dict[str, Any]] = []
    for capability in list_manual_capabilities():
        if clean_domain and _normalized(capability.domain) != clean_domain:
            continue
        entry = catalog[capability.capability_id]
        blockers = (
            manual_execute_blockers(capability)
            if capability.mode == "write"
            else manual_read_blockers(capability)
        )
        direct_bindings = sorted(
            candidate.name
            for candidate in catalog.values()
            if candidate.binding_kind == "agent_tool"
            and candidate.canonical_callable == entry.canonical_callable
        )
        bridge_available = entry.exposed_tool_name in registry and not blockers
        superseded_by = _SUPERSEDED_MANUAL_CAPABILITIES.get(
            capability.capability_id
        )
        superseding_entry = catalog.get(superseded_by or "")
        superseding_capability = (
            find_manual_capability(superseded_by) if superseded_by else None
        )
        superseding_blockers = (
            manual_execute_blockers(superseding_capability)
            if superseding_capability is not None
            and superseding_capability.mode == "write"
            else manual_read_blockers(superseding_capability)
            if superseding_capability is not None
            else ["replacement capability missing"]
        )
        superseded_binding_available = bool(
            superseding_entry
            and superseding_entry.exposed_tool_name in registry
            and not superseding_blockers
        )
        problems: list[str] = []
        if blockers and not superseded_binding_available:
            problems.extend(f"bridge_blocked:{reason}" for reason in blockers)
        if (
            not direct_bindings
            and not bridge_available
            and not superseded_binding_available
        ):
            problems.append("no_agent_binding")
        manual_rows.append(
            {
                "capability_id": capability.capability_id,
                "owner_domain": capability.domain,
                "mode": capability.mode,
                "canonical_callable": entry.canonical_callable,
                "exposed_tool": entry.exposed_tool_name,
                "direct_agent_operations": direct_bindings,
                "superseded_by": superseded_by or "",
                "binding_status": (
                    "shared_direct"
                    if direct_bindings
                    else "shared_typed_bridge"
                    if bridge_available
                    else "superseded_by_typed_operation"
                    if superseded_binding_available
                    else "blocked"
                ),
                "problems": problems,
            }
        )

    agent_rows: list[dict[str, Any]] = []
    for entry in catalog.values():
        if entry.binding_kind != "agent_tool":
            continue
        if clean_domain and _normalized(entry.metadata.owner_domain) != clean_domain:
            continue
        adapter_owned = entry.canonical_callable.startswith("AI.processors.tools.")
        agent_rows.append(
            {
                "operation_id": entry.name,
                "owner_domain": entry.metadata.owner_domain,
                "canonical_callable": entry.canonical_callable,
                "canonical_owner_status": (
                    "ai_adapter_only" if adapter_owned else "domain_or_core_callable"
                ),
                "problems": (
                    ["agent_tool_canonical_callable_is_ai_adapter"]
                    if adapter_owned
                    else []
                ),
            }
        )

    problems = [
        {"kind": "manual_capability", "id": row["capability_id"], "problems": row["problems"]}
        for row in manual_rows
        if row["problems"]
    ] + [
        {"kind": "agent_operation", "id": row["operation_id"], "problems": row["problems"]}
        for row in agent_rows
        if row["problems"]
    ]
    return {
        "domain": domain or "all",
        "ready": not problems,
        "manual_capability_count": len(manual_rows),
        "agent_operation_count": len(agent_rows),
        "problem_count": len(problems),
        "problems": problems,
        "manual_capabilities": manual_rows,
        "agent_operations": agent_rows,
    }
