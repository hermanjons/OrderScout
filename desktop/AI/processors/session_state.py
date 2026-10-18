from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from Core.processors.record_refs import RecordRef


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


_ACTION_ID_REFERENCE_LABEL = r"(?i)(?<!\w)(?:action|aksiyon)[_\s-]*(?:id|kimli(?:k|ği|gi))(?!\w)"


def has_explicit_action_id_reference(text: Any) -> bool:
    """Keep a malformed explicit target distinct from an unnamed current action."""
    return bool(re.search(_ACTION_ID_REFERENCE_LABEL, _compact_text(text)))


def referenced_action_id_from_text(
    text: Any,
    *,
    known_action_ids: Iterable[Any] = (),
) -> str:
    """Return only an explicit pending-action identity reference.

    Approval language remains a UI concern, while resolving which immutable
    action the user named belongs to shared typed session semantics. Explicit
    labels take priority over identities mentioned elsewhere. A malformed label
    returns no identity and must be rejected using has_explicit_action_id_reference;
    it never falls back to a known or digest-shaped identity in the same message.
    """

    clean_text = _compact_text(text)
    if not clean_text:
        return ""
    labels = list(re.finditer(_ACTION_ID_REFERENCE_LABEL, clean_text))
    if labels:
        if len(labels) != 1:
            return ""  # Multiple explicit targets require clarification.
        labelled = re.match(
            r"\s*[:=#]?\s*([A-Za-z0-9][A-Za-z0-9._:-]{7,127})(?=$|[\s,;!?])",
            clean_text[labels[0].end():],
        )
        if not labelled:
            return ""
        target = labelled.group(1).rstrip(".,;!?")
        return next((_compact_text(value) for value in known_action_ids
                     if _compact_text(value).casefold() == target.casefold()), target)
    for raw_action_id in sorted(
        {_compact_text(value) for value in known_action_ids if _compact_text(value)},
        key=len,
        reverse=True,
    ):
        if re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(raw_action_id)}(?![A-Za-z0-9_-])",
            clean_text,
            flags=re.IGNORECASE,
        ):
            return raw_action_id
    opaque = re.search(
        r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{32,64}(?![A-Fa-f0-9])",
        clean_text,
    )
    return opaque.group(0) if opaque else ""


@dataclass(frozen=True)
class SelectionSnapshot:
    selection_id: str
    domain: str
    record_type: str
    refs: tuple[RecordRef, ...]
    source_tool: str
    period: str = ""
    listed_count: int = 0
    total_count: int = 0
    truncated: bool = False
    account_scopes: tuple[dict[str, Any], ...] = ()
    query_fingerprint: str = ""
    source_revision: str = ""
    source_snapshot_hash: str = ""

    @staticmethod
    def _fingerprint_payload(
        *,
        domain: str,
        record_type: str,
        refs: tuple[RecordRef, ...],
        source_tool: str,
        period: str,
        listed_count: int,
        total_count: int,
        truncated: bool,
        query_fingerprint: str = "",
        source_revision: str = "",
        source_snapshot_hash: str = "",
    ) -> str:
        payload = {
            "domain": domain,
            "record_type": record_type,
            "refs": [ref.to_dict() for ref in refs],
            "source_tool": source_tool,
            "period": period,
            "listed_count": listed_count,
            "total_count": total_count,
            "truncated": truncated,
            "query_fingerprint": _compact_text(query_fingerprint),
            "source_revision": _compact_text(source_revision),
            "source_snapshot_hash": _compact_text(source_snapshot_hash),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()

    @classmethod
    def from_order_numbers(
        cls,
        order_numbers: list[Any] | tuple[Any, ...],
        *,
        source_tool: str,
        period: str = "",
        listed_count: int | None = None,
        total_count: int | None = None,
        truncated: bool = False,
        account_by_order: dict[str, Any] | None = None,
        environment_by_account: dict[str, Any] | None = None,
        account_scopes: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        source: str = "local_db",
        query_fingerprint: str = "",
        source_revision: str | int = "",
        source_snapshot_hash: str = "",
    ) -> "SelectionSnapshot":
        normalized_ids = tuple(
            dict.fromkeys(
                _compact_text(value)
                for value in list(order_numbers or [])
                if _compact_text(value)
            )
        )
        account_map = {
            _compact_text(key): _compact_text(value)
            for key, value in dict(account_by_order or {}).items()
            if _compact_text(key)
        }
        environment_map = {
            _compact_text(key): _compact_text(value)
            for key, value in dict(environment_by_account or {}).items()
            if _compact_text(key)
        }
        refs = tuple(
            RecordRef(
                domain="orders",
                record_type="order",
                record_id=record_id,
                source=_compact_text(source) or "local_db",
                account=account_map.get(record_id) or "unknown",
                environment=environment_map.get(account_map.get(record_id, "")) or "unknown",
            )
            for record_id in normalized_ids
        )
        listed = len(refs) if listed_count is None else max(0, int(listed_count))
        total = len(refs) if total_count is None else max(0, int(total_count))
        normalized_tool = _compact_text(source_tool)
        normalized_period = _compact_text(period)
        normalized_query_fingerprint = _compact_text(query_fingerprint)
        normalized_source_revision = _compact_text(source_revision)
        normalized_source_snapshot_hash = _compact_text(source_snapshot_hash)
        selection_id = cls._fingerprint_payload(
            domain="orders",
            record_type="order",
            refs=refs,
            source_tool=normalized_tool,
            period=normalized_period,
            listed_count=listed,
            total_count=total,
            truncated=bool(truncated),
            query_fingerprint=normalized_query_fingerprint,
            source_revision=normalized_source_revision,
            source_snapshot_hash=normalized_source_snapshot_hash,
        )
        return cls(
            selection_id=selection_id,
            domain="orders",
            record_type="order",
            refs=refs,
            source_tool=normalized_tool,
            period=normalized_period,
            listed_count=listed,
            total_count=total,
            truncated=bool(truncated),
            account_scopes=tuple(dict(row) for row in account_scopes if isinstance(row, dict)),
            query_fingerprint=normalized_query_fingerprint,
            source_revision=normalized_source_revision,
            source_snapshot_hash=normalized_source_snapshot_hash,
        )

    @classmethod
    def from_return_claim_ids(
        cls,
        claim_ids: list[Any] | tuple[Any, ...],
        *,
        source_tool: str,
        period: str = "",
        listed_count: int | None = None,
        total_count: int | None = None,
        truncated: bool = False,
        account_by_claim: dict[str, Any] | None = None,
        environment_by_account: dict[str, Any] | None = None,
        order_by_claim: dict[str, Any] | None = None,
        account_scopes: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        source: str = "local_db",
        query_fingerprint: str = "",
        source_revision: str | int = "",
        source_snapshot_hash: str = "",
    ) -> "SelectionSnapshot":
        normalized_ids = tuple(
            dict.fromkeys(
                _compact_text(value)
                for value in list(claim_ids or [])
                if _compact_text(value)
            )
        )
        account_map = {
            _compact_text(key): _compact_text(value)
            for key, value in dict(account_by_claim or {}).items()
            if _compact_text(key)
        }
        environment_map = {
            _compact_text(key): _compact_text(value)
            for key, value in dict(environment_by_account or {}).items()
            if _compact_text(key)
        }
        order_map = {
            _compact_text(key): _compact_text(value)
            for key, value in dict(order_by_claim or {}).items()
            if _compact_text(key) and _compact_text(value)
        }
        refs = tuple(
            RecordRef(
                domain="orders",
                record_type="return_claim",
                record_id=claim_id,
                source=_compact_text(source) or "local_db",
                account=account_map.get(claim_id) or "unknown",
                environment=environment_map.get(account_map.get(claim_id, "")) or "unknown",
                identifiers=(
                    {"order_number": order_map[claim_id]}
                    if claim_id in order_map
                    else {}
                ),
            )
            for claim_id in normalized_ids
        )
        listed = len(refs) if listed_count is None else max(0, int(listed_count))
        total = len(refs) if total_count is None else max(0, int(total_count))
        normalized_tool = _compact_text(source_tool)
        normalized_period = _compact_text(period)
        normalized_query_fingerprint = _compact_text(query_fingerprint)
        normalized_source_revision = _compact_text(source_revision)
        normalized_source_snapshot_hash = _compact_text(source_snapshot_hash)
        selection_id = cls._fingerprint_payload(
            domain="orders",
            record_type="return_claim",
            refs=refs,
            source_tool=normalized_tool,
            period=normalized_period,
            listed_count=listed,
            total_count=total,
            truncated=bool(truncated),
            query_fingerprint=normalized_query_fingerprint,
            source_revision=normalized_source_revision,
            source_snapshot_hash=normalized_source_snapshot_hash,
        )
        return cls(
            selection_id=selection_id,
            domain="orders",
            record_type="return_claim",
            refs=refs,
            source_tool=normalized_tool,
            period=normalized_period,
            listed_count=listed,
            total_count=total,
            truncated=bool(truncated),
            account_scopes=tuple(dict(row) for row in account_scopes if isinstance(row, dict)),
            query_fingerprint=normalized_query_fingerprint,
            source_revision=normalized_source_revision,
            source_snapshot_hash=normalized_source_snapshot_hash,
        )

    @classmethod
    def from_context(cls, context: dict[str, Any]) -> "SelectionSnapshot | None":
        kind = _compact_text(context.get("kind"))
        if kind not in {"order_selection", "return_selection"}:
            return None
        if kind == "return_selection":
            record_refs = [
                RecordRef.from_dict(dict(row))
                for row in list(context.get("record_refs") or [])
                if isinstance(row, dict) and _compact_text(row.get("record_id"))
            ]
            claim_ids = (
                [ref.record_id for ref in record_refs]
                if record_refs
                else list(context.get("claim_ids") or [])
            )
            account_by_claim = (
                {ref.record_id: ref.account for ref in record_refs}
                if record_refs
                else dict(context.get("account_by_claim") or {})
            )
            environment_by_account = (
                {ref.account: ref.environment for ref in record_refs}
                if record_refs
                else dict(context.get("environment_by_account") or {})
            )
            order_by_claim = {
                ref.record_id: _compact_text(ref.identifiers.get("order_number"))
                for ref in record_refs
                if _compact_text(ref.identifiers.get("order_number"))
            }
            if not order_by_claim:
                order_numbers = [
                    _compact_text(value)
                    for value in list(context.get("order_numbers") or [])
                    if _compact_text(value)
                ]
                if len(order_numbers) == len(claim_ids):
                    order_by_claim = dict(zip(claim_ids, order_numbers))
            snapshot = cls.from_return_claim_ids(
                claim_ids,
                source_tool=_compact_text(context.get("source_tool")),
                period=_compact_text(context.get("period")),
                listed_count=context.get("listed_count"),
                total_count=context.get("total_count"),
                truncated=bool(context.get("truncated")),
                account_by_claim=account_by_claim,
                environment_by_account=environment_by_account,
                order_by_claim=order_by_claim,
                account_scopes=tuple(
                    dict(row)
                    for row in list(context.get("account_scopes") or [])
                    if isinstance(row, dict)
                ),
                source=(record_refs[0].source if record_refs else _compact_text(context.get("source")) or "local_db"),
                query_fingerprint=_compact_text(context.get("query_fingerprint")),
                source_revision=_compact_text(context.get("source_revision")),
                source_snapshot_hash=_compact_text(
                    context.get("source_snapshot_hash")
                ),
            )
            expected_id = _compact_text(context.get("selection_id"))
            if expected_id and expected_id != snapshot.selection_id:
                return None
            return snapshot
        record_refs = [
            RecordRef.from_dict(dict(row))
            for row in list(context.get("record_refs") or [])
            if isinstance(row, dict) and _compact_text(row.get("record_id"))
        ]
        if record_refs:
            order_numbers = [ref.record_id for ref in record_refs]
            account_by_order = {ref.record_id: ref.account for ref in record_refs}
            environment_by_account = {ref.account: ref.environment for ref in record_refs}
            source = record_refs[0].source
        else:
            order_numbers = list(context.get("order_numbers") or [])
            account_by_order = dict(context.get("account_by_order") or {})
            environment_by_account = dict(context.get("environment_by_account") or {})
            source = _compact_text(context.get("source")) or "local_db"
        snapshot = cls.from_order_numbers(
            order_numbers,
            source_tool=_compact_text(context.get("source_tool")),
            period=_compact_text(context.get("period")),
            listed_count=context.get("listed_count"),
            total_count=context.get("total_count"),
            truncated=bool(context.get("truncated")),
            account_by_order=account_by_order,
            environment_by_account=environment_by_account,
            account_scopes=tuple(
                dict(row)
                for row in list(context.get("account_scopes") or [])
                if isinstance(row, dict)
            ),
            source=source,
            query_fingerprint=_compact_text(context.get("query_fingerprint")),
            source_revision=_compact_text(context.get("source_revision")),
            source_snapshot_hash=_compact_text(
                context.get("source_snapshot_hash")
            ),
        )
        expected_id = _compact_text(context.get("selection_id"))
        if expected_id and expected_id != snapshot.selection_id:
            return None
        return snapshot

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(ref.record_id for ref in self.refs)

    @property
    def is_complete(self) -> bool:
        count = len(self.refs)
        return bool(
            count
            and not self.truncated
            and self.listed_count == count
            and self.total_count == count
        )

    @property
    def is_authoritative_read(self) -> bool:
        return bool(self.source_tool and not self.source_tool.endswith(".prepare"))

    def to_context(self) -> dict[str, Any]:
        is_return = self.record_type == "return_claim"
        payload = {
            "kind": "return_selection" if is_return else "order_selection",
            "selection_id": self.selection_id,
            "source_tool": self.source_tool,
            "period": self.period,
            "record_refs": [ref.to_dict() for ref in self.refs],
            "listed_count": self.listed_count,
            "total_count": self.total_count,
            "truncated": self.truncated,
            "account_scopes": [dict(row) for row in self.account_scopes],
            "query_fingerprint": self.query_fingerprint,
            "source_revision": self.source_revision,
            "source_snapshot_hash": self.source_snapshot_hash,
        }
        if is_return:
            payload["claim_ids"] = list(self.record_ids)
            payload["order_numbers"] = [
                _compact_text(ref.identifiers.get("order_number"))
                for ref in self.refs
                if _compact_text(ref.identifiers.get("order_number"))
            ]
            payload["account_by_claim"] = {
                ref.record_id: ref.account
                for ref in self.refs
                if ref.account and ref.account != "unknown"
            }
        else:
            payload["order_numbers"] = list(self.record_ids)
            payload["account_by_order"] = {
                ref.record_id: ref.account
                for ref in self.refs
                if ref.account and ref.account != "unknown"
            }
        payload["environment_by_account"] = {
            ref.account: ref.environment
            for ref in self.refs
            if ref.account and ref.account != "unknown"
            and ref.environment and ref.environment != "unknown"
        }
        return payload


@dataclass(frozen=True)
class AnalysisContext:
    analysis_id: str
    domain: str
    analysis_type: str
    selection_id: str
    source_tools: tuple[str, ...]
    facts: dict[str, Any] = field(default_factory=dict)
    aggregates: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        domain: str,
        analysis_type: str,
        selection_id: str = "",
        source_tools: list[Any] | tuple[Any, ...] = (),
        facts: dict[str, Any] | None = None,
        aggregates: dict[str, Any] | None = None,
    ) -> "AnalysisContext":
        payload = {
            "domain": _compact_text(domain),
            "analysis_type": _compact_text(analysis_type),
            "selection_id": _compact_text(selection_id),
            "source_tools": list(
                dict.fromkeys(
                    _compact_text(value)
                    for value in source_tools
                    if _compact_text(value)
                )
            ),
            "facts": dict(facts or {}),
            "aggregates": dict(aggregates or {}),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(
            analysis_id=hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest(),
            domain=payload["domain"],
            analysis_type=payload["analysis_type"],
            selection_id=payload["selection_id"],
            source_tools=tuple(payload["source_tools"]),
            facts=payload["facts"],
            aggregates=payload["aggregates"],
        )

    @classmethod
    def from_context(cls, payload: dict[str, Any]) -> "AnalysisContext | None":
        if _compact_text(payload.get("kind")) != "analysis_context":
            return None
        context = cls.create(
            domain=_compact_text(payload.get("domain")),
            analysis_type=_compact_text(payload.get("analysis_type")),
            selection_id=_compact_text(payload.get("selection_id")),
            source_tools=tuple(payload.get("source_tools") or ()),
            facts=dict(payload.get("facts") or {}),
            aggregates=dict(payload.get("aggregates") or {}),
        )
        expected = _compact_text(payload.get("analysis_id"))
        if expected and expected != context.analysis_id:
            return None
        return context

    def to_context(self) -> dict[str, Any]:
        return {
            "kind": "analysis_context",
            "analysis_id": self.analysis_id,
            "domain": self.domain,
            "analysis_type": self.analysis_type,
            "selection_id": self.selection_id,
            "source_tools": list(self.source_tools),
            "facts": dict(self.facts or {}),
            "aggregates": dict(self.aggregates or {}),
        }


@dataclass(frozen=True)
class ConversationTurn:
    """Typed user/assistant turn metadata used by the control plane.

    ``content`` remains available for answer generation, but routing decisions can
    consume ``mode`` and ``objective`` without reparsing arbitrary old prose.
    """

    turn_id: str
    role: str
    mode: str
    objective: str
    content: str
    created_at: str
    tool_names: tuple[str, ...] = ()
    intent_kind: str = ""
    requested_fields: tuple[str, ...] = ()
    semantic_contract: dict[str, Any] = field(default_factory=dict)
    correction_of_turn_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        role: str,
        content: str,
        mode: str = "conversation",
        objective: str = "",
        tool_names: list[Any] | tuple[Any, ...] = (),
        intent_kind: str = "",
        requested_fields: list[Any] | tuple[Any, ...] = (),
        semantic_contract: dict[str, Any] | None = None,
        correction_of_turn_id: str = "",
        turn_id: str = "",
        created_at: str = "",
    ) -> "ConversationTurn":
        return cls(
            turn_id=_compact_text(turn_id) or uuid4().hex,
            role=_compact_text(role).casefold() or "user",
            mode=_compact_text(mode).casefold() or "conversation",
            objective=_compact_text(objective),
            content=_compact_text(content),
            created_at=_compact_text(created_at) or _utcnow_iso(),
            tool_names=tuple(
                dict.fromkeys(
                    _compact_text(value)
                    for value in tool_names
                    if _compact_text(value)
                )
            ),
            intent_kind=_compact_text(intent_kind).casefold(),
            requested_fields=tuple(
                dict.fromkeys(
                    _compact_text(value).casefold()
                    for value in requested_fields
                    if _compact_text(value)
                )
            ),
            semantic_contract=dict(semantic_contract or {}),
            correction_of_turn_id=_compact_text(correction_of_turn_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "mode": self.mode,
            "objective": self.objective,
            "content": self.content,
            "created_at": self.created_at,
            "tool_names": list(self.tool_names),
            "intent_kind": self.intent_kind,
            "requested_fields": list(self.requested_fields),
            "semantic_contract": dict(self.semantic_contract or {}),
            "correction_of_turn_id": self.correction_of_turn_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConversationTurn":
        return cls.create(
            turn_id=_compact_text(payload.get("turn_id")),
            role=_compact_text(payload.get("role")),
            mode=_compact_text(payload.get("mode")),
            objective=_compact_text(payload.get("objective")),
            content=_compact_text(payload.get("content")),
            created_at=_compact_text(payload.get("created_at")),
            tool_names=tuple(payload.get("tool_names") or ()),
            intent_kind=_compact_text(payload.get("intent_kind")),
            requested_fields=tuple(payload.get("requested_fields") or ()),
            semantic_contract=dict(payload.get("semantic_contract") or {}),
            correction_of_turn_id=_compact_text(
                payload.get("correction_of_turn_id")
            ),
        )


@dataclass(frozen=True)
class ActiveScope:
    """Authoritative domain/account/environment boundary for later operations."""

    scope_id: str
    domain: str
    account_ids: tuple[str, ...] = ()
    company_ids: tuple[str, ...] = ()
    marketplaces: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    observed_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        domain: str,
        account_ids: list[Any] | tuple[Any, ...] = (),
        company_ids: list[Any] | tuple[Any, ...] = (),
        marketplaces: list[Any] | tuple[Any, ...] = (),
        environments: list[Any] | tuple[Any, ...] = (),
        filters: dict[str, Any] | None = None,
        source: str = "",
        observed_at: str = "",
    ) -> "ActiveScope":
        payload = {
            "domain": _compact_text(domain).casefold(),
            "account_ids": list(
                dict.fromkeys(_compact_text(value) for value in account_ids if _compact_text(value))
            ),
            "company_ids": list(
                dict.fromkeys(_compact_text(value) for value in company_ids if _compact_text(value))
            ),
            "marketplaces": list(
                dict.fromkeys(_compact_text(value).casefold() for value in marketplaces if _compact_text(value))
            ),
            "environments": list(
                dict.fromkeys(_compact_text(value).casefold() for value in environments if _compact_text(value))
            ),
            "filters": dict(filters or {}),
            "source": _compact_text(source),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(
            scope_id=hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest(),
            domain=payload["domain"],
            account_ids=tuple(payload["account_ids"]),
            company_ids=tuple(payload["company_ids"]),
            marketplaces=tuple(payload["marketplaces"]),
            environments=tuple(payload["environments"]),
            filters=payload["filters"],
            source=payload["source"],
            observed_at=_compact_text(observed_at) or _utcnow_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "domain": self.domain,
            "account_ids": list(self.account_ids),
            "company_ids": list(self.company_ids),
            "marketplaces": list(self.marketplaces),
            "environments": list(self.environments),
            "filters": dict(self.filters or {}),
            "source": self.source,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActiveScope | None":
        scope = cls.create(
            domain=_compact_text(payload.get("domain")),
            account_ids=tuple(payload.get("account_ids") or ()),
            company_ids=tuple(payload.get("company_ids") or ()),
            marketplaces=tuple(payload.get("marketplaces") or ()),
            environments=tuple(payload.get("environments") or ()),
            filters=dict(payload.get("filters") or {}),
            source=_compact_text(payload.get("source")),
            observed_at=_compact_text(payload.get("observed_at")),
        )
        expected = _compact_text(payload.get("scope_id"))
        if expected and expected != scope.scope_id:
            return None
        return scope


@dataclass(frozen=True)
class Observation:
    """Typed, attributable result of a read or post-action verification."""

    observation_id: str
    domain: str
    operation_name: str
    success: bool
    scope_id: str = ""
    selection_id: str = ""
    refs: tuple[RecordRef, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    aggregates: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    observed_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        domain: str,
        operation_name: str,
        success: bool,
        scope_id: str = "",
        selection_id: str = "",
        refs: list[RecordRef] | tuple[RecordRef, ...] = (),
        facts: dict[str, Any] | None = None,
        aggregates: dict[str, Any] | None = None,
        source: str = "",
        observed_at: str = "",
    ) -> "Observation":
        normalized_refs = tuple(refs)
        timestamp = _compact_text(observed_at) or _utcnow_iso()
        payload = {
            "domain": _compact_text(domain).casefold(),
            "operation_name": _compact_text(operation_name),
            "success": bool(success),
            "scope_id": _compact_text(scope_id),
            "selection_id": _compact_text(selection_id),
            "refs": [ref.to_dict() for ref in normalized_refs],
            "facts": dict(facts or {}),
            "aggregates": dict(aggregates or {}),
            "source": _compact_text(source),
            "observed_at": timestamp,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(
            observation_id=hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest(),
            domain=payload["domain"],
            operation_name=payload["operation_name"],
            success=payload["success"],
            scope_id=payload["scope_id"],
            selection_id=payload["selection_id"],
            refs=normalized_refs,
            facts=payload["facts"],
            aggregates=payload["aggregates"],
            source=payload["source"],
            observed_at=timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "domain": self.domain,
            "operation_name": self.operation_name,
            "success": self.success,
            "scope_id": self.scope_id,
            "selection_id": self.selection_id,
            "record_refs": [ref.to_dict() for ref in self.refs],
            "facts": dict(self.facts or {}),
            "aggregates": dict(self.aggregates or {}),
            "source": self.source,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Observation | None":
        refs: list[RecordRef] = []
        for row in list(payload.get("record_refs") or []):
            if not isinstance(row, dict):
                continue
            try:
                refs.append(RecordRef.from_dict(dict(row)))
            except ValueError:
                return None
        observation = cls.create(
            domain=_compact_text(payload.get("domain")),
            operation_name=_compact_text(payload.get("operation_name")),
            success=bool(payload.get("success")),
            scope_id=_compact_text(payload.get("scope_id")),
            selection_id=_compact_text(payload.get("selection_id")),
            refs=refs,
            facts=dict(payload.get("facts") or {}),
            aggregates=dict(payload.get("aggregates") or {}),
            source=_compact_text(payload.get("source")),
            observed_at=_compact_text(payload.get("observed_at")),
        )
        expected = _compact_text(payload.get("observation_id"))
        if expected and expected != observation.observation_id:
            return None
        return observation


@dataclass(frozen=True)
class SessionStateEvent:
    """Append-only lifecycle event; state changes never rewrite earlier events."""

    event_id: str
    event_type: str
    entity_id: str
    status: str
    payload: dict[str, Any]
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        entity_id: str,
        status: str,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        created_at: str = "",
    ) -> "SessionStateEvent":
        return cls(
            event_id=_compact_text(event_id) or uuid4().hex,
            event_type=_compact_text(event_type),
            entity_id=_compact_text(entity_id),
            status=_compact_text(status),
            payload=dict(payload or {}),
            created_at=_compact_text(created_at) or _utcnow_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "status": self.status,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionStateEvent":
        return cls.create(
            event_id=_compact_text(payload.get("event_id")),
            event_type=_compact_text(payload.get("event_type")),
            entity_id=_compact_text(payload.get("entity_id")),
            status=_compact_text(payload.get("status")),
            payload=dict(payload.get("payload") or {}),
            created_at=_compact_text(payload.get("created_at")),
        )


_ACTION_IDENTIFIER_FIELDS = (
    # Claim mutations also carry their parent order number. The claim must win
    # as the primary typed identity so account/environment lookup and later
    # execute/verify steps stay bound to the exact mutation target.
    ("claim_id", "orders", "return_claim"),
    ("order_number", "orders", "order"),
    ("tx_id", "stock", "transaction"),
    ("sku", "stock", "item"),
    ("api_account_id", "account", "marketplace_account"),
    ("pk", "generic", "record"),
    ("id", "generic", "record"),
)


def _action_record_refs(action: dict[str, Any], *, stored_first: bool = True) -> tuple[RecordRef, ...]:
    stored_rows = list(action.get("record_refs") or []) if stored_first else []
    stored: list[RecordRef] = []
    for row in stored_rows:
        if not isinstance(row, dict) or not _compact_text(row.get("record_id")):
            continue
        try:
            stored.append(RecordRef.from_dict(dict(row)))
        except ValueError:
            continue
    if stored:
        return tuple(stored)

    rows = [dict(row) for row in list(action.get("rows") or []) if isinstance(row, dict)]
    arguments = dict(action.get("arguments") or {})
    payload = dict(arguments.get("payload") or {})
    account_by_record: dict[str, str] = {}
    environment_by_account: dict[str, str] = {}
    for container in (arguments, payload):
        for map_key in ("account_by_record", "account_by_order", "account_by_claim"):
            account_by_record.update(
                {
                    _compact_text(key): _compact_text(value)
                    for key, value in dict(container.get(map_key) or {}).items()
                    if _compact_text(key) and _compact_text(value)
                }
            )
        environment_by_account.update(
            {
                _compact_text(key): _compact_text(value)
                for key, value in dict(
                    container.get("environment_by_account") or {}
                ).items()
                if _compact_text(key) and _compact_text(value)
            }
        )
        for reference in list(container.get("order_refs") or []):
            if not isinstance(reference, dict):
                continue
            order_number = _compact_text(
                reference.get("order_number") or reference.get("orderNumber")
            )
            api_account_id = _compact_text(reference.get("api_account_id"))
            if order_number and api_account_id:
                account_by_record[order_number] = api_account_id
    argument_candidates: list[tuple[str, str, str, dict[str, Any]]] = []
    plural_fields = (
        ("order_numbers", "orders", "order"),
        ("orders", "orders", "order"),
        ("claim_ids", "orders", "return_claim"),
        ("tx_ids", "stock", "transaction"),
    )
    for container in (arguments, payload):
        for key, domain, record_type in plural_fields:
            for identifier_value in list(container.get(key) or []):
                identifier = _compact_text(identifier_value)
                if identifier:
                    argument_candidates.append((domain, record_type, identifier, {}))
    # Account ids are scope metadata when a concrete order/claim/transaction set
    # exists. Treat them as record targets only for account-only actions.
    if not argument_candidates:
        for container in (arguments, payload):
            for identifier_value in list(container.get("api_account_ids") or []):
                identifier = _compact_text(identifier_value)
                if identifier:
                    argument_candidates.append(
                        ("account", "marketplace_account", identifier, {})
                    )
    row_candidates: list[tuple[str, str, str, dict[str, Any]]] = []
    for row in rows:
        for key, domain, record_type in _ACTION_IDENTIFIER_FIELDS:
            identifier = _compact_text(row.get(key))
            if identifier:
                row_candidates.append((domain, record_type, identifier, row))
                break
    # Execute input is authoritative when the action carries an explicit typed
    # identifier list. Some previews intentionally include comparison rows that
    # are not mutation targets (for example stale-return reconciliation).
    candidates = argument_candidates or row_candidates
    refs: list[RecordRef] = []
    seen: set[tuple[str, str, str]] = set()
    for domain, record_type, identifier, row in candidates:
        key = (domain, record_type, identifier)
        if key in seen:
            continue
        seen.add(key)
        account = _compact_text(
            row.get("api_account_id")
            or row.get("account_id")
            or account_by_record.get(identifier)
            or action.get("account")
        ) or "unknown"
        environment = _compact_text(
            row.get("environment")
            or environment_by_account.get(account)
            or action.get("environment")
        ) or "unknown"
        refs.append(
            RecordRef(
                domain=domain,
                record_type=record_type,
                record_id=identifier,
                source="prepared_action",
                account=account,
                environment=environment,
                identifiers={
                    field: _compact_text(row.get(field))
                    for field, _domain, _record_type in _ACTION_IDENTIFIER_FIELDS
                    if _compact_text(row.get(field))
                },
            )
        )
    return tuple(refs)


def pending_action_semantic_fingerprint(action: dict[str, Any]) -> str:
    """Hash every effect-bearing approval field into one immutable identity."""

    payload = dict(action or {})
    refs = _action_record_refs(payload)
    selected_count = int(payload.get("selected_record_count", len(refs)) or 0)
    preview_count = int(payload.get("preview_item_count", len(refs)) or 0)
    execute_count = int(payload.get("execute_input_count", len(refs)) or 0)
    identity_payload = {
        "operation_name": _compact_text(
            payload.get("action_type")
            or payload.get("operation")
            or payload.get("capability_id")
            or payload.get("tool")
        ),
        "selection_id": _compact_text(payload.get("selection_id")),
        "arguments": dict(payload.get("arguments") or {}),
        "rows": [
            dict(row)
            for row in list(payload.get("rows") or [])
            if isinstance(row, dict)
        ],
        "record_refs": [ref.to_dict() for ref in refs],
        "selected_record_count": selected_count,
        "preview_item_count": preview_count,
        "execute_input_count": execute_count,
        "approval_required": bool(
            payload.get("approval_required", payload.get("requires_approval", True))
        ),
        "risk_level": _compact_text(payload.get("risk_level")),
        "execute_enabled": bool(payload.get("execute_enabled")),
        "external_write": bool(payload.get("external_write")),
        "destructive": bool(payload.get("destructive")),
        "operation_metadata": dict(payload.get("operation_metadata") or {}),
    }
    encoded = json.dumps(
        identity_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()


@dataclass(frozen=True)
class PendingActionSnapshot:
    action_id: str
    operation_name: str
    selection_id: str
    refs: tuple[RecordRef, ...]
    selected_record_count: int
    preview_item_count: int
    execute_input_count: int
    prepare_fingerprint: str
    status: str = "pending_approval"

    @classmethod
    def from_action(cls, action: dict[str, Any]) -> "PendingActionSnapshot":
        refs = _action_record_refs(action)
        count = len(refs)
        selected_count = int(action.get("selected_record_count", count) or 0)
        preview_count = int(action.get("preview_item_count", count) or 0)
        execute_count = int(action.get("execute_input_count", count) or 0)
        operation_name = _compact_text(
            action.get("action_type")
            or action.get("operation")
            or action.get("capability_id")
            or action.get("tool")
        )
        selection_id = _compact_text(action.get("selection_id"))
        fingerprint = pending_action_semantic_fingerprint(action)
        return cls(
            action_id=_compact_text(action.get("action_id")) or fingerprint,
            operation_name=operation_name,
            selection_id=selection_id,
            refs=refs,
            selected_record_count=selected_count,
            preview_item_count=preview_count,
            execute_input_count=execute_count,
            prepare_fingerprint=fingerprint,
            status=_compact_text(action.get("status")) or "pending_approval",
        )

    @classmethod
    def reprepare(cls, action: dict[str, Any]) -> dict[str, Any]:
        """Kapsam bilinçli değiştiğinde eski immutable prepare kimliğini yeniler."""
        payload = dict(action or {})
        for key in (
            "action_id",
            "selection_id",
            "record_refs",
            "selected_record_count",
            "preview_item_count",
            "execute_input_count",
            "prepare_fingerprint",
        ):
            payload.pop(key, None)
        return cls.from_action(payload).to_action(payload)

    @classmethod
    def refresh_identity(cls, action: dict[str, Any]) -> dict[str, Any]:
        """Re-hash a fully bound proposal without discarding its exact scope."""

        payload = dict(action or {})
        payload.pop("action_id", None)
        payload.pop("prepare_fingerprint", None)
        return cls.from_action(payload).to_action(payload)

    def invariant_problems(self, action: dict[str, Any] | None = None) -> list[str]:
        problems: list[str] = []
        counts = {
            self.selected_record_count,
            self.preview_item_count,
            self.execute_input_count,
        }
        if len(counts) != 1:
            problems.append("selection_preview_execute_count_mismatch")
        if self.refs and self.selected_record_count != len(self.refs):
            problems.append("selected_record_count_record_refs_mismatch")
        if action is not None:
            expected = _compact_text(action.get("prepare_fingerprint"))
            if expected and expected != self.prepare_fingerprint:
                problems.append("prepare_fingerprint_mismatch")
            stored_refs = tuple(
                (ref.domain, ref.record_type, ref.record_id)
                for ref in self.refs
            )
            argument_scope = {
                "rows": [],
                "arguments": dict(action.get("arguments") or {}),
            }
            row_scope = {
                "rows": list(action.get("rows") or []),
                "arguments": {},
            }
            argument_refs = tuple(
                (ref.domain, ref.record_type, ref.record_id)
                for ref in _action_record_refs(argument_scope, stored_first=False)
            )
            payload_refs = argument_refs or tuple(
                (ref.domain, ref.record_type, ref.record_id)
                for ref in _action_record_refs(row_scope, stored_first=False)
            )
            if stored_refs and payload_refs and stored_refs != payload_refs:
                problems.append("prepare_payload_record_refs_mismatch")
        return problems

    def to_action(self, action: dict[str, Any]) -> dict[str, Any]:
        payload = dict(action or {})
        payload.update(
            {
                "action_id": self.action_id,
                "selection_id": self.selection_id,
                "record_refs": [ref.to_dict() for ref in self.refs],
                "selected_record_count": self.selected_record_count,
                "preview_item_count": self.preview_item_count,
                "execute_input_count": self.execute_input_count,
                "prepare_fingerprint": self.prepare_fingerprint,
                "status": self.status,
            }
        )
        return payload


@dataclass
class AgentTaskStep:
    index: int
    prompt: str
    step_id: str = ""
    objective: str = ""
    depends_on: list[str] = field(default_factory=list)
    operation_candidates: list[str] = field(default_factory=list)
    operation_domain: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    expected_evidence: list[str] = field(default_factory=list)
    status: str = "pending"
    tool_names: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    verification_status: str = "pending"
    attempt_count: int = 0
    result_message: str = ""
    result_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "prompt": self.prompt,
            "step_id": self.step_id,
            "objective": self.objective or self.prompt,
            "depends_on": list(self.depends_on),
            "operation_candidates": list(self.operation_candidates),
            "operation_domain": self.operation_domain,
            "arguments": dict(self.arguments or {}),
            "expected_evidence": list(self.expected_evidence),
            "status": self.status,
            "tool_names": list(self.tool_names),
            "observation_ids": list(self.observation_ids),
            "verification_status": self.verification_status,
            "attempt_count": self.attempt_count,
            "result_message": self.result_message,
            "result_data": dict(self.result_data or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentTaskStep":
        return cls(
            index=int(payload.get("index") or 0),
            prompt=str(payload.get("prompt") or ""),
            step_id=str(payload.get("step_id") or ""),
            objective=str(payload.get("objective") or payload.get("prompt") or ""),
            depends_on=[
                str(item)
                for item in list(payload.get("depends_on") or [])
                if str(item or "").strip()
            ],
            operation_candidates=[
                str(item)
                for item in list(payload.get("operation_candidates") or [])
                if str(item or "").strip()
            ],
            operation_domain=str(payload.get("operation_domain") or "").casefold(),
            arguments=dict(payload.get("arguments") or {}),
            expected_evidence=[
                str(item)
                for item in list(payload.get("expected_evidence") or [])
                if str(item or "").strip()
            ],
            status=str(payload.get("status") or "pending"),
            tool_names=[str(item) for item in list(payload.get("tool_names") or [])],
            observation_ids=[
                str(item)
                for item in list(payload.get("observation_ids") or [])
                if str(item or "").strip()
            ],
            verification_status=str(
                payload.get("verification_status") or "pending"
            ),
            attempt_count=int(payload.get("attempt_count") or 0),
            result_message=str(payload.get("result_message") or ""),
            result_data=dict(payload.get("result_data") or {}),
        )


@dataclass
class GoalPlan:
    goal: str
    domain: str
    steps: list[AgentTaskStep]
    plan_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "planned"
    source: str = "deterministic"
    revision: int = 1
    parent_plan_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    @classmethod
    def create(
        cls,
        *,
        goal: str,
        domain: str,
        step_ids: list[str],
        prompts: list[str],
        step_specs: list[dict[str, Any]] | None = None,
        source: str = "deterministic",
        metadata: dict[str, Any] | None = None,
    ) -> "GoalPlan":
        steps: list[AgentTaskStep] = []
        previous_step_id = ""
        specs = list(step_specs or [])
        for index, prompt in enumerate(list(prompts or [])):
            step_id = (
                _compact_text(step_ids[index])
                if index < len(step_ids)
                else f"step_{index + 1}"
            )
            spec = dict(specs[index] or {}) if index < len(specs) else {}
            dependencies_were_declared = "depends_on" in spec
            explicit_dependencies = [
                _compact_text(value)
                for value in list(spec.get("depends_on") or [])
                if _compact_text(value)
            ]
            operation_id = _compact_text(
                spec.get("operation_id") or spec.get("tool")
            )
            steps.append(
                AgentTaskStep(
                    index=index + 1,
                    step_id=step_id,
                    prompt=_compact_text(prompt),
                    objective=(
                        _compact_text(spec.get("objective"))
                        or _compact_text(prompt)
                    ),
                    depends_on=(
                        explicit_dependencies
                        if dependencies_were_declared
                        else [previous_step_id]
                        if previous_step_id
                        else []
                    ),
                    operation_candidates=[operation_id] if operation_id else [],
                    operation_domain=_compact_text(
                        spec.get("operation_domain") or spec.get("domain")
                    ).casefold(),
                    arguments=dict(spec.get("arguments") or {}),
                    expected_evidence=[
                        _compact_text(value)
                        for value in list(spec.get("expected_evidence") or [])
                        if _compact_text(value)
                    ],
                )
            )
            previous_step_id = step_id
        return cls(
            goal=_compact_text(goal),
            domain=_compact_text(domain).casefold() or "orders",
            steps=steps,
            source=_compact_text(source) or "deterministic",
            metadata=dict(metadata or {}),
        )

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()

    def step(self, step_id: str) -> AgentTaskStep | None:
        clean_id = _compact_text(step_id)
        for row in self.steps:
            if _compact_text(row.step_id) == clean_id:
                return row
        return None

    def ready_steps(self) -> list[AgentTaskStep]:
        completed_ids = {
            _compact_text(step.step_id)
            for step in self.steps
            if step.status in {"completed", "superseded"}
        }
        return [
            step
            for step in self.steps
            if step.status == "pending"
            and all(_compact_text(dep) in completed_ids for dep in step.depends_on)
        ]

    def append_replan_steps(
        self,
        steps: list[AgentTaskStep],
        *,
        failed_step_id: str,
        reason: str = "",
    ) -> None:
        existing_by_id = {_compact_text(step.step_id): index for index, step in enumerate(self.steps) if step.step_id}
        incoming_ids: set[str] = set()
        appended: list[str] = []
        replaced_definitions: list[dict[str, Any]] = []
        for step in steps:
            if not step.step_id or step.step_id in incoming_ids:
                continue
            incoming_ids.add(step.step_id)
            existing_index = existing_by_id.get(step.step_id)
            if existing_index is not None:
                previous = self.steps[existing_index]
                if (previous.status not in {"pending", "superseded"} or previous.attempt_count
                        or previous.tool_names or previous.observation_ids or previous.result_data):
                    continue
                replaced_definitions.append(previous.to_dict())
                self.steps[existing_index] = step
            else:
                existing_by_id[step.step_id] = len(self.steps)
                self.steps.append(step)
            appended.append(step.step_id)
        self.revision += 1
        self.status = "running"
        history = [
            dict(row)
            for row in list(self.metadata.get("replans") or [])
            if isinstance(row, dict)
        ]
        history.append(
            {
                "revision": self.revision,
                "failed_step_id": _compact_text(failed_step_id),
                "replacement_step_ids": appended,
                "reason": _compact_text(reason),
            }
        )
        if replaced_definitions:
            history[-1]["superseded_step_definitions"] = replaced_definitions
        self.metadata["replans"] = history
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "domain": self.domain,
            "status": self.status,
            "source": self.source,
            "revision": self.revision,
            "parent_plan_id": self.parent_plan_id,
            "metadata": dict(self.metadata or {}),
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoalPlan":
        return cls(
            plan_id=str(payload.get("plan_id") or uuid4().hex),
            goal=str(payload.get("goal") or ""),
            domain=str(payload.get("domain") or "orders").casefold(),
            status=str(payload.get("status") or "planned"),
            source=str(payload.get("source") or "deterministic"),
            revision=max(1, int(payload.get("revision") or 1)),
            parent_plan_id=str(payload.get("parent_plan_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
            steps=[
                AgentTaskStep.from_dict(dict(item))
                for item in list(payload.get("steps") or [])
                if isinstance(item, dict)
            ],
            created_at=str(payload.get("created_at") or _utcnow_iso()),
            updated_at=str(payload.get("updated_at") or _utcnow_iso()),
        )


@dataclass
class AgentSessionState:
    goal: str
    active_domain: str = "orders"
    session_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "running"
    active_entities: dict[str, Any] = field(default_factory=dict)
    conversation_turns: list[ConversationTurn] = field(default_factory=list)
    active_scopes: dict[str, ActiveScope] = field(default_factory=dict)
    selection_snapshots: list[SelectionSnapshot] = field(default_factory=list)
    active_selection_ids: dict[str, str] = field(default_factory=dict)
    analysis_contexts: list[AnalysisContext] = field(default_factory=list)
    active_analysis_ids: dict[str, str] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    active_pending_action_id: str = ""
    state_events: list[SessionStateEvent] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    progress_events: list[dict[str, Any]] = field(default_factory=list)
    goal_plans: list[GoalPlan] = field(default_factory=list)
    active_goal_plan_id: str = ""
    completed_steps: list[AgentTaskStep] = field(default_factory=list)
    remaining_steps: list[AgentTaskStep] = field(default_factory=list)
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)
    memory_summary: str = ""
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    def __post_init__(self) -> None:
        if not self.active_selection_ids:
            for snapshot in self.selection_snapshots:
                self.active_selection_ids[snapshot.domain] = snapshot.selection_id
        if not self.active_analysis_ids:
            for context in self.analysis_contexts:
                self.active_analysis_ids[context.domain] = context.analysis_id
        if not self.active_pending_action_id and self.pending_actions:
            first = PendingActionSnapshot.from_action(dict(self.pending_actions[0] or {}))
            self.active_pending_action_id = first.action_id
        if not self.active_goal_plan_id and self.goal_plans:
            self.active_goal_plan_id = self.goal_plans[-1].plan_id

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()

    def _append_state_event(
        self,
        *,
        event_type: str,
        entity_id: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> SessionStateEvent:
        event = SessionStateEvent.create(
            event_type=event_type,
            entity_id=entity_id,
            status=status,
            payload=payload,
        )
        self.state_events.append(event)
        self.touch()
        return event

    def record_turn(
        self,
        *,
        role: str,
        content: str,
        mode: str = "conversation",
        objective: str = "",
        tool_names: list[Any] | tuple[Any, ...] = (),
        intent_kind: str = "",
        requested_fields: list[Any] | tuple[Any, ...] = (),
        semantic_contract: dict[str, Any] | None = None,
        correction_of_turn_id: str = "",
    ) -> ConversationTurn:
        turn = ConversationTurn.create(
            role=role,
            content=content,
            mode=mode,
            objective=objective,
            tool_names=tool_names,
            intent_kind=intent_kind,
            requested_fields=requested_fields,
            semantic_contract=semantic_contract,
            correction_of_turn_id=correction_of_turn_id,
        )
        self.conversation_turns.append(turn)
        self._append_state_event(
            event_type="conversation_turn",
            entity_id=turn.turn_id,
            status="recorded",
            payload={
                "role": turn.role,
                "mode": turn.mode,
                "objective": turn.objective,
                "intent_kind": turn.intent_kind,
                "requested_fields": list(turn.requested_fields),
                "semantic_contract": dict(turn.semantic_contract or {}),
                "correction_of_turn_id": turn.correction_of_turn_id,
            },
        )
        return turn

    def set_active_scope(self, scope: ActiveScope) -> ActiveScope:
        if not scope.domain:
            raise ValueError("Active scope domain cannot be empty.")
        previous = self.active_scopes.get(scope.domain)
        self.active_scopes[scope.domain] = scope
        self._append_state_event(
            event_type="active_scope",
            entity_id=scope.scope_id,
            status="activated",
            payload={
                "domain": scope.domain,
                "superseded_scope_id": previous.scope_id if previous else "",
            },
        )
        return scope

    def add_selection_snapshot(
        self,
        snapshot: SelectionSnapshot,
        *,
        activate: bool = True,
    ) -> SelectionSnapshot:
        if not any(row.selection_id == snapshot.selection_id for row in self.selection_snapshots):
            self.selection_snapshots.append(snapshot)
        previous_id = self.active_selection_ids.get(snapshot.domain, "")
        if activate:
            self.active_selection_ids[snapshot.domain] = snapshot.selection_id
        self._append_state_event(
            event_type="selection_snapshot",
            entity_id=snapshot.selection_id,
            status="activated" if activate else "recorded",
            payload={
                "domain": snapshot.domain,
                "record_count": len(snapshot.refs),
                "superseded_selection_id": previous_id if activate else "",
            },
        )
        return snapshot

    def active_selection(self, domain: str = "") -> SelectionSnapshot | None:
        clean_domain = _compact_text(domain).casefold() or self.active_domain.casefold()
        active_id = self.active_selection_ids.get(clean_domain, "")
        for snapshot in reversed(self.selection_snapshots):
            if snapshot.domain == clean_domain and (not active_id or snapshot.selection_id == active_id):
                return snapshot
        return None

    def add_analysis_context(
        self,
        context: AnalysisContext,
        *,
        activate: bool = True,
    ) -> AnalysisContext:
        if not any(row.analysis_id == context.analysis_id for row in self.analysis_contexts):
            self.analysis_contexts.append(context)
        previous_id = self.active_analysis_ids.get(context.domain, "")
        if activate:
            self.active_analysis_ids[context.domain] = context.analysis_id
        self._append_state_event(
            event_type="analysis_context",
            entity_id=context.analysis_id,
            status="activated" if activate else "recorded",
            payload={
                "domain": context.domain,
                "superseded_analysis_id": previous_id if activate else "",
            },
        )
        return context

    def add_observation(self, observation: Observation) -> Observation:
        if not any(row.observation_id == observation.observation_id for row in self.observations):
            self.observations.append(observation)
        self._append_state_event(
            event_type="observation",
            entity_id=observation.observation_id,
            status="succeeded" if observation.success else "failed",
            payload={
                "domain": observation.domain,
                "operation_name": observation.operation_name,
                "selection_id": observation.selection_id,
            },
        )
        return observation

    def add_goal_plan(self, plan: GoalPlan, *, activate: bool = True) -> GoalPlan:
        if not any(row.plan_id == plan.plan_id for row in self.goal_plans):
            self.goal_plans.append(plan)
        previous_id = self.active_goal_plan_id
        if activate:
            for row in self.goal_plans:
                if row.plan_id == previous_id and row.plan_id != plan.plan_id:
                    row.status = "superseded"
                    row.touch()
            self.active_goal_plan_id = plan.plan_id
            if plan.status == "planned":
                plan.status = "running"
                plan.touch()
        self._append_state_event(
            event_type="goal_plan",
            entity_id=plan.plan_id,
            status="activated" if activate else "recorded",
            payload={
                "domain": plan.domain,
                "revision": plan.revision,
                "step_ids": [step.step_id for step in plan.steps],
                "superseded_plan_id": previous_id if activate else "",
            },
        )
        return plan

    def active_goal_plan(self) -> GoalPlan | None:
        for plan in reversed(self.goal_plans):
            if not self.active_goal_plan_id or plan.plan_id == self.active_goal_plan_id:
                return plan
        return None

    def set_goal_plan_status(self, status: str) -> GoalPlan | None:
        plan = self.active_goal_plan()
        if plan is None:
            return None
        plan.status = _compact_text(status).casefold() or plan.status
        plan.touch()
        self._append_state_event(
            event_type="goal_plan",
            entity_id=plan.plan_id,
            status=plan.status,
            payload={"revision": plan.revision},
        )
        return plan

    def revise_goal_plan(
        self,
        replacement_steps: list[AgentTaskStep],
        *,
        failed_step_id: str,
        reason: str = "",
    ) -> GoalPlan | None:
        plan = self.active_goal_plan()
        if plan is None:
            return None
        plan.append_replan_steps(
            replacement_steps,
            failed_step_id=failed_step_id,
            reason=reason,
        )
        self._append_state_event(
            event_type="goal_plan_revised",
            entity_id=plan.plan_id,
            status="running",
            payload={
                "revision": plan.revision,
                "failed_step_id": _compact_text(failed_step_id),
                "replacement_step_ids": [
                    step.step_id for step in replacement_steps
                ],
                "reason": _compact_text(reason),
            },
        )
        return plan

    def ingest_tool_observation(
        self,
        *,
        context: dict[str, Any] | None,
        operation_name: str,
        success: bool,
        message: str = "",
        aggregates: dict[str, Any] | None = None,
        domain: str = "",
    ) -> Observation | None:
        """Ingest one tool result through the shared typed-state projection."""

        clean_operation = _compact_text(operation_name)
        payload = dict(context or {})
        selection = SelectionSnapshot.from_context(payload) if payload else None
        if selection is not None:
            activate_selection = selection.is_authoritative_read
            active_selection = self.active_selection(selection.domain)
            active_plan = self.active_goal_plan()
            plan_id = active_plan.plan_id if active_plan is not None else ""
            activation_meta_by_domain = dict(
                self.active_entities.get("selection_activation_meta") or {}
            )
            active_meta = dict(
                activation_meta_by_domain.get(selection.domain) or {}
            )

            def selection_priority(source_tool: str) -> int:
                """Rank user-visible record reads above aggregate samples.

                Aggregate/count tools may carry sample identifiers for later
                composition, but a secondary aggregate step in the same plan
                must never reorder or replace the exact list the user just
                saw.  The rule is based on operation shape, not wording or a
                provider-specific plan.
                """

                source = _compact_text(source_tool).casefold()
                if not source or source.endswith(".prepare"):
                    return 0
                leaf = source.rsplit(".", 1)[-1]
                if leaf.endswith("summary") or leaf.endswith("count") or leaf.endswith("analysis"):
                    return 10
                if leaf.endswith("_numbers") or leaf.endswith("_ids"):
                    return 50
                return 100

            candidate_priority = (
                (1000 if selection.is_complete else 0)
                + selection_priority(selection.source_tool)
            )
            current_priority = (
                (1000 if active_selection is not None and active_selection.is_complete else 0)
                + selection_priority(
                    active_selection.source_tool
                    if active_selection is not None
                    else ""
                )
            )
            same_plan = bool(
                plan_id
                and _compact_text(active_meta.get("plan_id")) == plan_id
            )
            if (
                activate_selection
                and active_selection is not None
                and same_plan
                and candidate_priority < current_priority
            ):
                activate_selection = False
            self.add_selection_snapshot(
                selection,
                activate=activate_selection,
            )
            if activate_selection:
                activation_meta_by_domain[selection.domain] = {
                    "plan_id": plan_id,
                    "selection_id": selection.selection_id,
                    "source_tool": selection.source_tool,
                    "priority": candidate_priority,
                }
                self.active_entities["selection_activation_meta"] = (
                    activation_meta_by_domain
                )
                self.set_active_scope(
                    ActiveScope.create(
                        domain=selection.domain,
                        account_ids=tuple(
                            dict.fromkeys(
                                ref.account
                                for ref in selection.refs
                                if ref.account and ref.account != "unknown"
                            )
                        ),
                        company_ids=tuple(
                            dict.fromkeys(
                                _compact_text(
                                    row.get("company_id")
                                    or row.get("comp_name")
                                    or row.get("store_name")
                                )
                                for row in selection.account_scopes
                                if _compact_text(
                                    row.get("company_id")
                                    or row.get("comp_name")
                                    or row.get("store_name")
                                )
                            )
                        ),
                        marketplaces=tuple(
                            dict.fromkeys(
                                _compact_text(row.get("platform"))
                                for row in selection.account_scopes
                                if _compact_text(row.get("platform"))
                            )
                        ),
                        environments=tuple(
                            dict.fromkeys(
                                ref.environment
                                for ref in selection.refs
                                if ref.environment and ref.environment != "unknown"
                            )
                        ),
                        filters={"period": selection.period} if selection.period else {},
                        source=selection.source_tool,
                    )
                )

        scope_rows = list(payload.get("account_scopes") or [])
        if not scope_rows and isinstance(payload.get("facts"), dict):
            scope_rows = list((payload.get("facts") or {}).get("account_scopes") or [])
        context_kind = _compact_text(payload.get("kind"))
        if selection is None and scope_rows and context_kind != "read_scope":
            self.set_active_scope(
                ActiveScope.create(
                    domain=_compact_text(domain).casefold() or self.active_domain,
                    account_ids=tuple(
                        dict.fromkeys(
                            _compact_text(
                                row.get("api_account_id") or row.get("account_id")
                            )
                            for row in scope_rows
                            if isinstance(row, dict)
                            and _compact_text(
                                row.get("api_account_id") or row.get("account_id")
                            )
                        )
                    ),
                    company_ids=tuple(
                        dict.fromkeys(
                            _compact_text(row.get("store_name"))
                            for row in scope_rows
                            if isinstance(row, dict)
                            and _compact_text(row.get("store_name"))
                        )
                    ),
                    marketplaces=tuple(
                        dict.fromkeys(
                            _compact_text(row.get("platform"))
                            for row in scope_rows
                            if isinstance(row, dict)
                            and _compact_text(row.get("platform"))
                        )
                    ),
                    environments=tuple(
                        dict.fromkeys(
                            _compact_text(row.get("environment"))
                            for row in scope_rows
                            if isinstance(row, dict)
                            and _compact_text(row.get("environment"))
                        )
                    ),
                    filters={
                        "period": _compact_text(
                            payload.get("period")
                            or dict(payload.get("facts") or {}).get("period")
                        )
                    },
                    source=clean_operation,
                )
            )

        analysis = AnalysisContext.from_context(payload) if payload else None
        if analysis is not None:
            self.add_analysis_context(analysis)

        if not clean_operation:
            return None
        observation_domain = _compact_text(domain).casefold() or self.active_domain
        scope = self.active_scopes.get(observation_domain.casefold())
        facts: dict[str, Any] = {
            "context_kind": context_kind,
            "message": _compact_text(message),
        }
        if context_kind == "web_observation":
            for key in (
                "web_observation_id",
                "url",
                "title",
                "query_summary",
                "source_domain",
                "source_class",
                "published_at",
                "accessed_at",
                "freshness",
                "trust",
                "content_hash",
            ):
                value = payload.get(key)
                if value not in (None, "", [], {}):
                    facts[key] = value
            facts["prompt_injection_detected"] = bool(
                payload.get("prompt_injection_detected")
            )
            facts["untrusted_content"] = True
        elif context_kind == "web_comparison":
            for key in ("status", "claim", "source_count", "citations"):
                value = payload.get(key)
                if value not in (None, "", [], {}):
                    facts[key] = value
        elif context_kind == "read_scope":
            facts["source_tool"] = clean_operation
            facts["population"] = _compact_text(payload.get("population"))
            facts["truncated"] = bool(payload.get("truncated"))
            if isinstance(payload.get("total_matching"), int):
                facts["total_matching"] = payload["total_matching"]
            facts["account_scopes"] = [
                {
                    key: row.get(key)
                    for key in (
                        "api_account_id",
                        "account_id",
                        "store_name",
                        "platform",
                        "environment",
                    )
                    if row.get(key) not in (None, "")
                }
                for row in scope_rows[:50]
                if isinstance(row, dict)
            ]
            if _compact_text(payload.get("period")):
                facts["period"] = _compact_text(payload.get("period"))

        observation = Observation.create(
            domain=observation_domain,
            operation_name=clean_operation,
            success=bool(success),
            scope_id=scope.scope_id if scope and context_kind != "read_scope" else "",
            selection_id=(
                selection.selection_id
                if selection is not None
                else analysis.selection_id
                if analysis is not None
                else ""
            ),
            refs=selection.refs if selection is not None else (),
            facts=facts,
            aggregates=dict(aggregates or {}),
            source=clean_operation,
        )
        return self.add_observation(observation)

    @staticmethod
    def _pending_action_context(action: dict[str, Any]) -> dict[str, Any]:
        snapshot = PendingActionSnapshot.from_action(dict(action or {}))
        arguments = dict(action.get("arguments") or {})
        action_payload = dict(arguments.get("payload") or {})
        return {
            key: value
            for key, value in {
                "kind": "pending_action",
                "source_tool": _compact_text(action.get("source_tool") or action.get("tool")),
                "action_type": snapshot.operation_name,
                "action_id": snapshot.action_id,
                "selection_id": snapshot.selection_id,
                "status": snapshot.status,
                "risk_level": _compact_text(action.get("risk_level")),
                "approval_required": True,
                "execute_enabled": bool(action.get("execute_enabled")),
                "record_refs": [ref.to_dict() for ref in snapshot.refs],
                "order_numbers": [
                    ref.record_id
                    for ref in snapshot.refs
                    if ref.record_type == "order"
                ],
                "claim_ids": [
                    ref.record_id
                    for ref in snapshot.refs
                    if ref.record_type == "return_claim"
                ],
                "safe_payload": {
                    key: action_payload.get(key)
                    for key in (
                        "item_id",
                        "warehouse_id",
                        "qty",
                        "target_qty",
                        "brand_code",
                        "model_code",
                        "currency",
                    )
                    if action_payload.get(key) not in (None, "")
                },
                "selected_record_count": snapshot.selected_record_count,
                "preview_item_count": snapshot.preview_item_count,
                "execute_input_count": snapshot.execute_input_count,
            }.items()
            if value not in ("", None, [], {})
        }

    def authoritative_context_rows(self) -> list[dict[str, Any]]:
        """Project only currently active typed entities for legacy readers.

        This is a migration boundary: old helpers may still accept a history-like
        shape, but stale contexts from raw chat rows are never forwarded.
        """

        rows: list[dict[str, Any]] = []
        for domain in sorted(self.active_selection_ids):
            snapshot = self.active_selection(domain)
            if snapshot is not None:
                rows.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "context": snapshot.to_context(),
                    }
                )
        for domain, analysis_id in sorted(self.active_analysis_ids.items()):
            context = next(
                (
                    row
                    for row in reversed(self.analysis_contexts)
                    if row.domain == domain and row.analysis_id == analysis_id
                ),
                None,
            )
            if context is not None:
                rows.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "context": context.to_context(),
                    }
                )
        recent_read_scopes: list[Observation] = []
        seen_read_scopes: set[str] = set()
        for observation in reversed(self.observations):
            if not observation.success or _compact_text(
                (observation.facts or {}).get("context_kind")
            ) != "read_scope":
                continue
            scope_key = json.dumps(
                {
                    "domain": observation.domain,
                    "population": (observation.facts or {}).get("population") or "",
                    "account_scopes": (observation.facts or {}).get("account_scopes") or [],
                    "period": (observation.facts or {}).get("period") or "",
                    "truncated": bool((observation.facts or {}).get("truncated")),
                    "total_matching": (observation.facts or {}).get("total_matching"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if scope_key in seen_read_scopes:
                continue
            seen_read_scopes.add(scope_key)
            recent_read_scopes.append(observation)
            if len(recent_read_scopes) >= 4:
                break
        for observation in reversed(recent_read_scopes):
            rows.append(
                {
                    "role": "assistant",
                    "content": "",
                    "context": {
                        "kind": "read_scope",
                        "domain": observation.domain,
                        "source_tool": observation.operation_name,
                        "population": _compact_text(
                            (observation.facts or {}).get("population")
                        ),
                        "truncated": bool((observation.facts or {}).get("truncated")),
                        "total_matching": (observation.facts or {}).get("total_matching"),
                        "account_scopes": list(
                            (observation.facts or {}).get("account_scopes") or []
                        ),
                        "period": _compact_text((observation.facts or {}).get("period")),
                    },
                }
            )
        pending = self.active_pending_action()
        if pending is not None:
            rows.append(
                {
                    "role": "assistant",
                    "content": "",
                    "context": self._pending_action_context(pending),
                }
            )
        for observation in [
            row
            for row in self.observations
            if row.success
            and _compact_text((row.facts or {}).get("context_kind"))
            in {"web_observation", "web_comparison"}
        ][-4:]:
            rows.append(
                {
                    "role": "assistant",
                    "content": "",
                    "context": dict(observation.facts or {}),
                }
            )
        return rows

    def active_pending_action(self) -> dict[str, Any] | None:
        active_id = _compact_text(self.active_pending_action_id)
        if not active_id:
            return None
        for action in self.pending_actions:
            snapshot = PendingActionSnapshot.from_action(dict(action or {}))
            if snapshot.action_id == active_id and snapshot.status == "pending_approval":
                return action
        return None

    def revise_pending_action_scope(
        self,
        action_id: str,
        record_ids: list[Any] | tuple[Any, ...],
        *,
        reason: str = "user_scope_revision",
    ) -> dict[str, Any]:
        """Narrow the exact active proposal and create a new immutable prepare ID."""

        active = self.active_pending_action()
        clean_action_id = _compact_text(action_id)
        if active is None or clean_action_id != _compact_text(self.active_pending_action_id):
            raise ValueError("Pending action is stale or is not the active approval target.")
        snapshot = PendingActionSnapshot.from_action(dict(active))
        requested = tuple(
            dict.fromkeys(
                _compact_text(value)
                for value in list(record_ids or [])
                if _compact_text(value)
            )
        )
        if not requested:
            raise ValueError("Revised pending action scope cannot be empty.")
        refs_by_id = {ref.record_id: ref for ref in snapshot.refs}
        unknown = [record_id for record_id in requested if record_id not in refs_by_id]
        if unknown:
            raise ValueError(
                "Revised pending action scope contains records outside the active proposal: "
                + ", ".join(unknown)
            )
        record_types = {refs_by_id[record_id].record_type for record_id in requested}
        if len(record_types) != 1:
            raise ValueError("Revised pending action scope must use one record type.")
        record_type = next(iter(record_types))
        revised = deepcopy(active)
        revised["status"] = "pending_approval"
        arguments = dict(revised.get("arguments") or {})
        payload = dict(arguments.get("payload") or {})
        target_keys = {
            "order": ("order_numbers", "orders"),
            "return_claim": ("claim_ids",),
            "transaction": ("tx_ids",),
        }.get(record_type, ())
        for container in (arguments, payload):
            for key in target_keys:
                if key in container:
                    container[key] = list(requested)
            mapping_keys = {
                "order": ("account_by_order",),
                "return_claim": ("account_by_claim",),
            }.get(record_type, ())
            for key in mapping_keys:
                if isinstance(container.get(key), dict):
                    container[key] = {
                        record_id: container[key][record_id]
                        for record_id in requested
                        if record_id in container[key]
                    }
            if record_type == "order" and isinstance(container.get("order_refs"), list):
                container["order_refs"] = [
                    row
                    for row in container["order_refs"]
                    if isinstance(row, dict)
                    and _compact_text(row.get("order_number") or row.get("orderNumber"))
                    in requested
                ]
        if record_type == "return_claim" and len(requested) == 1 and "order" in payload:
            payload["order"] = requested[0]
        arguments["payload"] = payload
        revised["arguments"] = arguments
        identity_fields = {
            "order": ("order_number",),
            "return_claim": ("claim_id", "claim_number"),
            "transaction": ("tx_id",),
        }.get(record_type, ("id", "pk"))
        revised_rows = [
            dict(row)
            for row in list(revised.get("rows") or [])
            if isinstance(row, dict)
            and any(_compact_text(row.get(key)) in requested for key in identity_fields)
        ]
        if revised_rows:
            revised["rows"] = revised_rows
        revised = PendingActionSnapshot.reprepare(revised)
        canonical = self.add_pending_action(revised, supersede_active=True)
        self._append_state_event(
            event_type="pending_action_revision",
            entity_id=_compact_text(canonical.get("action_id")),
            status="pending_approval",
            payload={
                "superseded_action_id": clean_action_id,
                "reason": _compact_text(reason),
                "record_ids": list(requested),
            },
        )
        return canonical

    def add_pending_action(
        self,
        action: dict[str, Any],
        *,
        supersede_active: bool = True,
    ) -> dict[str, Any]:
        canonical = PendingActionSnapshot.from_action(dict(action or {})).to_action(action)
        new_id = _compact_text(canonical.get("action_id"))
        active = self.active_pending_action()
        if active is not None:
            active_id = _compact_text(active.get("action_id"))
            if active_id == new_id:
                return active
            if not supersede_active:
                raise ValueError("An active pending action already exists.")
            self.resolve_pending_action(
                active_id,
                status="superseded",
                reason="replaced_by_new_prepare",
                replacement_action_id=new_id,
            )
        self.pending_actions.append(canonical)
        self.active_pending_action_id = new_id
        self._append_state_event(
            event_type="pending_action",
            entity_id=new_id,
            status="pending_approval",
            payload={
                "operation_name": _compact_text(canonical.get("action_type")),
                "selection_id": _compact_text(canonical.get("selection_id")),
            },
        )
        return canonical

    def resolve_pending_action(
        self,
        action_id: str,
        *,
        status: str,
        reason: str = "",
        replacement_action_id: str = "",
    ) -> dict[str, Any]:
        clean_id = _compact_text(action_id)
        clean_status = _compact_text(status).casefold()
        if clean_status not in {"approved", "executed", "failed", "cancelled", "superseded"}:
            raise ValueError(f"Unsupported pending action terminal status: {status}")
        if not clean_id or clean_id != _compact_text(self.active_pending_action_id):
            raise ValueError("Pending action is stale or is not the active approval target.")
        resolved: dict[str, Any] | None = None
        remaining: list[dict[str, Any]] = []
        for action in self.pending_actions:
            snapshot = PendingActionSnapshot.from_action(dict(action or {}))
            if snapshot.action_id == clean_id and resolved is None:
                resolved = dict(action)
                resolved["status"] = clean_status
                continue
            remaining.append(action)
        if resolved is None:
            raise ValueError("Active pending action could not be found.")
        self.pending_actions = remaining
        self.active_pending_action_id = ""
        self._append_state_event(
            event_type="pending_action",
            entity_id=clean_id,
            status=clean_status,
            payload={
                "reason": _compact_text(reason),
                "replacement_action_id": _compact_text(replacement_action_id),
            },
        )
        return resolved

    def cancel_active_pending_action(
        self,
        *,
        reason: str = "cancelled_by_user",
        cancelled_by: str = "user",
    ) -> dict[str, Any] | None:
        """Apply the complete typed cancellation transition in one place."""

        active = self.active_pending_action()
        if active is None:
            return None
        snapshot = PendingActionSnapshot.from_action(active)
        resolved = self.resolve_pending_action(
            snapshot.action_id,
            status="cancelled",
            reason=reason,
        )
        self.action_history.append(
            {
                "phase": "cancel",
                "status": "cancelled",
                "action_type": snapshot.operation_name,
                "approved_by": _compact_text(cancelled_by) or "user",
                "approval_required": bool(
                    active.get("approval_required", active.get("requires_approval", True))
                ),
                "execute_enabled": bool(active.get("execute_enabled", False)),
                "action": dict(active),
                "success": True,
                "result_message": (
                    "Pending action cancelled without executing its effect."
                ),
            }
        )
        self.remaining_steps = []
        self.status = "cancelled"
        self.set_goal_plan_status("cancelled")
        self.memory_summary = (
            "Kullanici pending action'i iptal etti; execute calismadi."
        )
        self.progress_events.append(
            {
                "index": len(self.progress_events) + 1,
                "phase": "cancelled",
                "status": "cancelled",
                "message": (
                    "Pending action kullanici tarafindan iptal edildi; execute calismadi."
                ),
                "percent": 100,
                "created_at": _utcnow_iso(),
            }
        )
        self.touch()
        return resolved

    def supersede_active_pending_action(
        self,
        *,
        reason: str = "superseded_by_user_scope_revision",
        superseded_by: str = "user",
    ) -> dict[str, Any] | None:
        """Terminally replace the active proposal without executing its effect."""

        active = self.active_pending_action()
        if active is None:
            return None
        snapshot = PendingActionSnapshot.from_action(active)
        resolved = self.resolve_pending_action(
            snapshot.action_id,
            status="superseded",
            reason=reason,
        )
        self.action_history.append(
            {
                "phase": "supersede",
                "status": "superseded",
                "action_type": snapshot.operation_name,
                "approved_by": _compact_text(superseded_by) or "user",
                "approval_required": bool(
                    active.get(
                        "approval_required",
                        active.get("requires_approval", True),
                    )
                ),
                "execute_enabled": bool(active.get("execute_enabled", False)),
                "action": dict(active),
                "success": True,
                "result_message": (
                    "Pending action superseded by a newer user scope without executing its effect."
                ),
            }
        )
        self.remaining_steps = []
        self.status = "superseded"
        self.set_goal_plan_status("superseded")
        self.memory_summary = (
            "Kullanici pending action kapsamını degistirdi; eski teklif superseded oldu ve execute calismadi."
        )
        self.progress_events.append(
            {
                "index": len(self.progress_events) + 1,
                "phase": "superseded",
                "status": "superseded",
                "message": (
                    "Pending action yeni kullanici kapsami nedeniyle gecersiz kilindi; execute calismadi."
                ),
                "percent": 100,
                "created_at": _utcnow_iso(),
            }
        )
        self.touch()
        return resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "active_domain": self.active_domain,
            "active_entities": dict(self.active_entities or {}),
            "conversation_turns": [turn.to_dict() for turn in self.conversation_turns],
            "active_scopes": {
                domain: scope.to_dict()
                for domain, scope in self.active_scopes.items()
            },
            "selection_snapshots": [snapshot.to_context() for snapshot in self.selection_snapshots],
            "active_selection_ids": dict(self.active_selection_ids or {}),
            "analysis_contexts": [context.to_context() for context in self.analysis_contexts],
            "active_analysis_ids": dict(self.active_analysis_ids or {}),
            "observations": [observation.to_dict() for observation in self.observations],
            "pending_actions": list(self.pending_actions or []),
            "active_pending_action_id": self.active_pending_action_id,
            "state_events": [event.to_dict() for event in self.state_events],
            "action_history": list(self.action_history or []),
            "progress_events": list(self.progress_events or []),
            "goal_plans": [plan.to_dict() for plan in self.goal_plans],
            "active_goal_plan_id": self.active_goal_plan_id,
            "completed_steps": [step.to_dict() for step in self.completed_steps],
            "remaining_steps": [step.to_dict() for step in self.remaining_steps],
            "last_tool_results": list(self.last_tool_results or []),
            "memory_summary": self.memory_summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentSessionState":
        state = cls(
            goal=str(payload.get("goal") or ""),
            active_domain=str(payload.get("active_domain") or "orders"),
            session_id=str(payload.get("session_id") or uuid4().hex),
            status=str(payload.get("status") or "running"),
            active_entities=dict(payload.get("active_entities") or {}),
            conversation_turns=[
                ConversationTurn.from_dict(dict(item))
                for item in list(payload.get("conversation_turns") or [])
                if isinstance(item, dict)
            ],
            active_scopes={
                _compact_text(domain).casefold(): scope
                for domain, row in dict(payload.get("active_scopes") or {}).items()
                if isinstance(row, dict)
                for scope in [ActiveScope.from_dict(dict(row))]
                if scope is not None
            },
            selection_snapshots=[
                snapshot
                for row in list(payload.get("selection_snapshots") or [])
                if isinstance(row, dict)
                for snapshot in [SelectionSnapshot.from_context(dict(row))]
                if snapshot is not None
            ],
            active_selection_ids={
                _compact_text(key).casefold(): _compact_text(value)
                for key, value in dict(payload.get("active_selection_ids") or {}).items()
                if _compact_text(key) and _compact_text(value)
            },
            analysis_contexts=[
                context
                for row in list(payload.get("analysis_contexts") or [])
                if isinstance(row, dict)
                for context in [AnalysisContext.from_context(dict(row))]
                if context is not None
            ],
            active_analysis_ids={
                _compact_text(key).casefold(): _compact_text(value)
                for key, value in dict(payload.get("active_analysis_ids") or {}).items()
                if _compact_text(key) and _compact_text(value)
            },
            observations=[
                observation
                for row in list(payload.get("observations") or [])
                if isinstance(row, dict)
                for observation in [Observation.from_dict(dict(row))]
                if observation is not None
            ],
            pending_actions=[dict(item) for item in list(payload.get("pending_actions") or []) if isinstance(item, dict)],
            active_pending_action_id=_compact_text(payload.get("active_pending_action_id")),
            state_events=[
                SessionStateEvent.from_dict(dict(item))
                for item in list(payload.get("state_events") or [])
                if isinstance(item, dict)
            ],
            action_history=[dict(item) for item in list(payload.get("action_history") or []) if isinstance(item, dict)],
            progress_events=[dict(item) for item in list(payload.get("progress_events") or []) if isinstance(item, dict)],
            goal_plans=[
                GoalPlan.from_dict(dict(item))
                for item in list(payload.get("goal_plans") or [])
                if isinstance(item, dict)
            ],
            active_goal_plan_id=_compact_text(payload.get("active_goal_plan_id")),
            completed_steps=[
                AgentTaskStep.from_dict(dict(item))
                for item in list(payload.get("completed_steps") or [])
                if isinstance(item, dict)
            ],
            remaining_steps=[
                AgentTaskStep.from_dict(dict(item))
                for item in list(payload.get("remaining_steps") or [])
                if isinstance(item, dict)
            ],
            last_tool_results=[dict(item) for item in list(payload.get("last_tool_results") or []) if isinstance(item, dict)],
            memory_summary=str(payload.get("memory_summary") or ""),
            created_at=str(payload.get("created_at") or _utcnow_iso()),
            updated_at=str(payload.get("updated_at") or _utcnow_iso()),
        )
        return state
