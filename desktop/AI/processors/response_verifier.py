from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from Feedback.processors.pipeline import Result

from AI.processors.session_state import AgentSessionState
from AI.processors.response_layout import presentation_numeric_text, record_answer_blocks
from AI.processors.grouped_projection import grouped_projection
from AI.processors.semantic_contracts import (
    cancellation_reason_distribution_contract,
    order_status_codes,
    validate_orders_read_arguments,
)
from Core.processors.verified_calculations import (
    COMPARISON_OPERATORS,
    evaluate_verified_calculation,
    evaluate_verified_comparison,
)
from Orders.processors.agentic_metrics import (
    ORDER_CANCELLATION_REASON_DISTRIBUTION_METRIC,
    ORDER_CANCELLED_COUNT_METRIC,
    ORDER_FULFILLMENT_RISK_COUNT_METRIC,
    ORDER_ITEM_SALES_REPORT_METRIC,
    ORDER_ITEM_SALES_SUMMARY_METRIC,
    ORDER_NONFINAL_COUNT_METRIC,
    ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC,
    ORDER_READY_TO_SHIP_COUNT_METRIC,
    ORDER_REVENUE_TOTAL_METRIC,
    ORDER_STATUS_DISTRIBUTION_METRIC,
    ORDER_TOTAL_COUNT_METRIC,
    normalize_order_metric_requirements,
    order_metric_evidence_keys,
)


_REQUEST_FIELDS = {
    "count",
    "scope",
    "order_number",
    "status",
    "store",
    "amount",
    "currency",
    "date",
    "customer_name",
    "address",
    "phone",
    "email",
    "tracking_number",
    "package_id",
    "claim_id",
    "reason",
    "item",
    "item_count",
    "sku",
    "barcode",
    "quantity",
    "cargo",
    "cargo_options",
    "returns",
    "item_sales_rows",
    "item_sales_quantity",
    "item_sales_order_count",
    "item_sales_amount",
    "web_sources",
    "research_findings",
    "artifact",
    "action_result",
    "risk",
    "ratio",
    "calculation",
}

_SENSITIVE_KEY_FIELDS = {
    "customer": "customer_name",
    "customername": "customer_name",
    "customerfirstname": "customer_name",
    "customerlastname": "customer_name",
    "firstname": "customer_name",
    "lastname": "customer_name",
    "buyer": "customer_name",
    "recipient": "customer_name",
    "recipientname": "customer_name",
    "customeremail": "email",
    "email": "email",
    "phone": "phone",
    "phonenumber": "phone",
    "customerphone": "phone",
    "shipmentaddress": "address",
    "invoiceaddress": "address",
    "address": "address",
    "fulladdress": "address",
    "district": "address",
    "city": "address",
    "postalcode": "address",
    "cargotrackingnumber": "tracking_number",
    "trackingnumber": "tracking_number",
    "cargosendernumber": "tracking_number",
    "packageid": "package_id",
    "shipmentpackageid": "package_id",
    "claimid": "claim_id",
    "ordernumber": "order_number",
}

_STORE_KEYS = {
    "store",
    "storename",
    "account",
    "accountname",
    "company",
    "companyname",
    "compname",
}

_AMOUNT_KEYS = {
    "estimatedrevenue",
    "totalrevenue",
    "revenue",
    "amounttotal",
    "totalamount",
    "returnamount",
    "grossamount",
    "totalprice",
}

_AGGREGATE_AMOUNT_KEYS = {
    "estimatedrevenue",
    "totalrevenue",
    "revenue",
    "amounttotal",
    "totalamount",
    "returnamount",
    "grossamount",
}

_STATUS_PHRASES = {
    "delivered": {"delivered", "teslim edildi", "teslim edilmis"},
    "shipped": {"shipped", "kargoda", "kargoya verildi"},
    "readytoship": {"readytoship", "kargoya hazir"},
    "cancelled": {"cancelled", "canceled", "iptal edildi", "iptal"},
    "returned": {"returned", "iade edildi"},
    "undelivered": {"undelivered", "teslim edilemedi", "teslim edilemeyen"},
    "undeliveredandreturned": {
        "undeliveredandreturned",
        "teslim edilemedi ve iade",
        "teslim edilemeyen ve iade edilen",
        "teslim edilemeyen ve iade donen",
        "iade donen",
    },
    "waitinginaction": {"waitinginaction", "aksiyon bekliyor", "onay bekliyor"},
}

_ACTION_NOUNS = (
    "etiket",
    "yazdir",
    "kargo firm",
    "iade onay",
    "excel",
    "senkron",
    "fis/cikti",
    "fis cikti",
)

_COMPLETION_WORDS = (
    "olusturuldu",
    "yazdirildi",
    "degistirildi",
    "onaylandi",
    "kaydedildi",
    "isaretlendi",
    "tamamlandi",
    "gerceklestirildi",
    "dogrulandi",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalized(value: Any) -> str:
    text = unicodedata.normalize(
        "NFKD",
        _text(value).casefold().translate(str.maketrans({"ı": "i"})),
    )
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalized(value))


def requested_response_fields(state: AgentSessionState) -> set[str]:
    active = state.active_entities if isinstance(state.active_entities, dict) else {}
    interpretation = (
        dict(active.get("turn_interpretation") or {})
        if isinstance(active.get("turn_interpretation"), dict)
        else {}
    )
    typed = {
        _text(value).casefold()
        for value in list(interpretation.get("requested_fields") or [])
        if _text(value).casefold() in _REQUEST_FIELDS
    }
    if typed:
        return typed

    goal = _normalized(interpretation.get("objective") or state.goal)
    fields: set[str] = set()
    if any(token in goal for token in ("kac ", "kac tane", "sayisi", "adet", "count")):
        fields.add("count")
    if any(token in goal for token in ("magaza", "hangi hesap", "store", "seller")):
        fields.add("store")
    if any(token in goal for token in ("durum", "status")):
        fields.add("status")
    if any(token in goal for token in ("siparis no", "siparis numara", "order number")):
        fields.add("order_number")
    if any(token in goal for token in ("tutar", "fiyat", "ciro", "amount", "price", "stok deger")):
        fields.add("amount")
    if any(token in goal for token in ("sku", "urun kodu", "stok kodu")):
        fields.add("sku")
    if any(token in goal for token in ("miktar", "quantity", "qty")):
        fields.add("quantity")
    if "birim" in goal.replace("para birim", ""):
        fields.add("unit")
    if any(token in goal for token in ("doviz", "para birim", "currency")):
        fields.add("currency")
    if any(token in goal for token in ("tarih", "ne zaman", "date")):
        fields.add("date")
    if any(token in goal for token in ("kimin", "musteri", "alici", "customer")):
        fields.add("customer_name")
    if any(token in goal for token in ("adres", "address")):
        fields.add("address")
    if any(token in goal for token in ("telefon", "phone")):
        fields.add("phone")
    if any(token in goal for token in ("e posta", "email")):
        fields.add("email")
    if any(token in goal for token in ("takip no", "takip numara", "tracking")):
        fields.add("tracking_number")
    if any(token in goal for token in ("paket no", "paket kimlik", "package id")):
        fields.add("package_id")
    if any(token in goal for token in ("claim id", "claim no", "iade no")):
        fields.add("claim_id")
    if any(
        token in goal
        for token in ("urun", "kalem", "icerik", "icerig", "product", "item")
    ):
        fields.add("item")
    if re.search(
        r"(?<!\w)(?:urun|kalem|product|item)\w*\s+"
        r"(?:sayi|aded|adet|count)\w*(?!\w)",
        goal,
    ):
        fields.discard("item")
        fields.discard("count")
        fields.add("item_count")
    if any(token in goal for token in ("internet", "web", "kaynak", "source", "arastir")):
        fields.add("research_findings")
        if _text(interpretation.get("information_source")).casefold() != "local_business_data":
            fields.add("web_sources")
    if any(token in goal for token in ("excel", "xlsx", "rapor", "dosya")):
        fields.add("artifact")
    mode = _text(interpretation.get("mode")).casefold()
    if mode in {"act", "correct", "approve"} or state.action_history:
        fields.add("action_result")
    return fields


def _turn_semantic_contract(state: AgentSessionState) -> dict[str, Any]:
    active = state.active_entities if isinstance(state.active_entities, dict) else {}
    interpretation = (
        dict(active.get("turn_interpretation") or {})
        if isinstance(active.get("turn_interpretation"), dict)
        else {}
    )
    return (
        dict(interpretation.get("semantic_contract") or {})
        if isinstance(interpretation.get("semantic_contract"), dict)
        else {}
    )


def _order_metric_requirements(state: AgentSessionState) -> set[str]:
    return set(
        normalize_order_metric_requirements(
            _turn_semantic_contract(state).get("metric_requirements") or []
        )
    )


def _direct_projection_fields(state: AgentSessionState) -> set[str]:
    """Return base outputs requested independently of a derived result."""

    raw = _turn_semantic_contract(state).get("direct_projection")
    return {
        _text(value).casefold()
        for value in (
            list(raw) if isinstance(raw, (list, tuple, set)) else []
        )
        if _text(value)
    }


def _persisted_item_sales_evidence_allowed(
    state: AgentSessionState,
) -> bool:
    """Allow immutable prior product evidence only for explicit typed reuse.

    A normal item-sales request must be backed by the operation completed in
    the current task.  The narrower ``existing_observations_only`` policy is
    different: it explicitly forbids a new domain read and may reuse the
    hash-verified contextual product summary already stored in typed state.
    Keeping this gate here prevents an unrelated stale observation from
    satisfying a fresh business-data request.
    """

    active = (
        state.active_entities
        if isinstance(state.active_entities, dict)
        else {}
    )
    interpretation = (
        dict(active.get("turn_interpretation") or {})
        if isinstance(active.get("turn_interpretation"), dict)
        else {}
    )
    contract = _turn_semantic_contract(state)
    metric = _text(contract.get("metric")).casefold()
    contextual_summary = bool(
        metric == "summary"
        and contract.get("contextual_item_identity_required") is True
        and ORDER_ITEM_SALES_SUMMARY_METRIC
        in normalize_order_metric_requirements(
            contract.get("metric_requirements") or []
        )
    )
    return bool(
        _text(interpretation.get("operation_policy")).casefold()
        == "existing_observations_only"
        and (metric == "derived" or contextual_summary)
        and _focused_item_sales_observation_evidence(state)
    )


def _general_broad_business_read_requested(state: AgentSessionState) -> bool:
    contract = _turn_semantic_contract(state)
    interpretation = dict((state.active_entities or {}).get("turn_interpretation") or {})
    return bool(
        _text(interpretation.get("domain") or state.active_domain).casefold() == "general"
        and _text(interpretation.get("intent_kind")).casefold() == "data_read"
        and _text(interpretation.get("mode")).casefold() == "inspect"
        and _text(contract.get("request_shape") or interpretation.get("request_shape")).casefold()
        in {"broad_analysis", "focused_analysis"}
        and _text(interpretation.get("request_shape")).casefold() != "record_list"
    )


def _general_broad_summary_requested(state: AgentSessionState) -> bool:
    """A cross-domain summary does not implicitly request a product record list."""

    contract = _turn_semantic_contract(state)
    interpretation = dict((state.active_entities or {}).get("turn_interpretation") or {})
    return bool(
        _general_broad_business_read_requested(state)
        and _text(contract.get("entity")).casefold() == "none"
        and _text(contract.get("metric")).casefold() == "summary"
        and not grouped_projection(contract)
        and ORDER_ITEM_SALES_REPORT_METRIC not in _order_metric_requirements(state)
        and "item_sales_rows" not in _direct_projection_fields(state)
        and "item_sales_rows" not in {
            _text(value).casefold()
            for value in list(interpretation.get("direct_output_fields") or [])
        }
    )


def _aggregate_analysis_requested(state: AgentSessionState) -> bool:
    """Identify typed analytical output while preserving explicit row contracts."""

    contract = _turn_semantic_contract(state)
    requirements = _order_metric_requirements(state)
    return _general_broad_summary_requested(state) or bool(
        _text(contract.get("entity")).casefold() == "order"
        and _text(contract.get("record_scope")).casefold() == "all_matching"
        and ORDER_TOTAL_COUNT_METRIC in requirements
        and bool(
            {
                ORDER_ITEM_SALES_SUMMARY_METRIC,
                ORDER_ITEM_SALES_REPORT_METRIC,
            }.intersection(requirements)
        )
        and len(requirements) >= 3
    )


_ORDER_ROW_DETAIL_FIELDS = frozenset(
    {
        "status",
        "amount",
        "date",
        "customer_name",
        "cargo",
        "tracking_number",
        "package_id",
        "item_count",
    }
)


def _typed_order_list(state: AgentSessionState) -> bool:
    contract = _turn_semantic_contract(state)
    return contract.get("entity") == "order" and (
        contract.get("metric") == "list" or contract.get("request_shape") == "record_list"
    )


def _order_row_projection_requested(
    state: AgentSessionState,
    requested: set[str],
) -> bool:
    contract = _turn_semantic_contract(state)
    product_report_contract = bool(
        "item_sales_rows" in requested
        and ORDER_ITEM_SALES_REPORT_METRIC
        in _order_metric_requirements(state)
    )
    typed_list_contract = bool(
        _text(contract.get("entity")).casefold() == "order"
        and _text(contract.get("metric")).casefold() == "list"
    )
    return bool(
        _text(contract.get("entity")).casefold() != "return_claim"
        and not product_report_contract
        and
        requested.intersection(
            _ORDER_ROW_DETAIL_FIELDS | ({"item", "sku", "barcode", "quantity"} if typed_list_contract else set())
        )
        and ("order_number" in requested or typed_list_contract)
    )


_RETURN_ROW_DETAIL_FIELDS = frozenset(
    {"claim_id", "order_number", "status", "reason"}
)


def _return_row_projection_requested(
    state: AgentSessionState,
    requested: set[str],
) -> bool:
    contract = _turn_semantic_contract(state)
    return bool(
        _text(contract.get("entity")).casefold() == "return_claim"
        and _text(contract.get("metric")).casefold() == "list"
        and requested.intersection(_RETURN_ROW_DETAIL_FIELDS)
    )


def _evidence_payloads(state: AgentSessionState) -> Iterable[Any]:
    current_observation_ids = {
        _text(observation_id)
        for step in state.completed_steps
        for observation_id in list(step.observation_ids or [])
        if _text(observation_id)
    }
    for step in state.completed_steps:
        result_data = dict(step.result_data or {})
        tool_result = result_data.get("tool_result")
        if isinstance(tool_result, dict):
            yield tool_result
    for observation in state.observations:
        if (
            current_observation_ids
            and _text(observation.observation_id) in current_observation_ids
        ):
            yield observation.to_dict()
    if _persisted_item_sales_evidence_allowed(state):
        # Only expose the hash-verified, privacy-minimized contextual summary.
        # Arbitrary historical observations must never become grounding for a
        # fresh business-data request merely because they still exist in state.
        persisted = _focused_item_sales_observation_evidence(state)
        if persisted:
            yield persisted
    for event in state.action_history:
        if event.get("phase") != "execute":
            continue
        yield {
            "success": event.get("success"),
            "action_type": event.get("action_type"),
            "action": dict(event.get("action") or {}),
            "verify": dict(event.get("verify") or {}),
        }


def _account_scope_rows(state: AgentSessionState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for payload in _evidence_payloads(state):
        if not isinstance(payload, dict):
            continue
        for raw in list(payload.get("account_scopes") or []):
            if not isinstance(raw, dict):
                continue
            row = {
                "api_account_id": raw.get("api_account_id"),
                "account_id": _text(raw.get("account_id")),
                "store_name": _text(raw.get("store_name")),
                "platform": _text(raw.get("platform")),
                "environment": _text(raw.get("environment")),
            }
            key = (
                _text(row.get("api_account_id")),
                row["account_id"],
                row["store_name"],
                row["environment"],
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _registered_account_population(state: AgentSessionState) -> dict[str, Any]:
    """Describe the coverage of the current authoritative account lookup."""
    for step in reversed(state.completed_steps):
        if "marketplaces.account_lookup" not in set(step.tool_names or []):
            continue
        result = dict((step.result_data or {}).get("tool_result") or {})
        evidence = dict(result.get("read_evidence") or {})
        count = result.get("count")
        total = result.get("total_matching")
        if not isinstance(count, int) or not isinstance(total, int):
            return {}
        truncated = result.get("truncated") is True
        return {
            "count": count,
            "total_matching": total,
            "truncated": truncated,
            "scope": _text(evidence.get("scope")),
            "complete": (
                evidence.get("source") == "local_database"
                and evidence.get("scope") == "all_accounts"
                and not truncated
                and count == total
            ),
        }
    return {}


def _currency_values(state: AgentSessionState) -> list[str]:
    """Collect only canonical currency dimensions from operation evidence."""

    values: list[str] = []

    def add(raw: Any) -> None:
        value = _text(raw).upper()
        if value and value not in values and value != "MIXED":
            values.append(value)

    for payload in _evidence_payloads(state):
        if not isinstance(payload, dict):
            continue
        add(payload.get("currency"))
        for raw in list(payload.get("currencies") or []):
            add(raw)
        for field in ("currency_totals", "stock_value_by_currency"):
            for row in list(payload.get(field) or []):
                if isinstance(row, dict):
                    add(row.get("currency"))
        for row in list(payload.get("orders") or []):
            if isinstance(row, dict):
                add(row.get("currency"))
        for context in list(payload.get("contexts") or []):
            if not isinstance(context, dict):
                continue
            order = context.get("order")
            if isinstance(order, dict):
                add(order.get("currency"))
    from AI.processors.observation_context import _verified_reports

    for report in _verified_reports(state):
        for sheet in report["source_value_preservation"]:
            for field in sheet["fields"]:
                for currency in field.get("currency_values", []):
                    add(currency)
    return values


def _collect_evidence(state: AgentSessionState) -> dict[str, Any]:
    strings: set[str] = set()
    numbers: set[str] = set()
    sensitive: dict[str, set[str]] = defaultdict(set)
    stores: set[str] = set()
    statuses: set[str] = set()

    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                clean_key = _key(raw_key)
                if clean_key in {"statuscounts", "statuses"} and isinstance(child, dict):
                    statuses.update(_text(status) for status in child if _text(status))
                visit(child, (*path, clean_key))
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                visit(child, path)
            return
        if value is None or isinstance(value, bool):
            return
        raw = _text(value)
        if not raw:
            return
        strings.add(raw)
        numbers.update(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", raw))
        leaf = path[-1] if path else ""
        sensitive_field = next(
            (
                _SENSITIVE_KEY_FIELDS[key_name]
                for key_name in reversed(path)
                if key_name in _SENSITIVE_KEY_FIELDS
            ),
            "",
        )
        if sensitive_field:
            sensitive[sensitive_field].add(raw)
        typed_record_ref_account = bool(
            leaf == "account" and "recordrefs" in path
        )
        if leaf in _STORE_KEYS and not typed_record_ref_account:
            stores.add(raw)
        if leaf in {"status", "shipmentstatus", "shipmentpackagestatus"}:
            statuses.add(raw)

    for step in state.completed_steps:
        operations = {_text(value) for value in list(step.tool_names or []) if _text(value)}
        if operations.intersection({"orders.ready_to_ship", "orders.ready_to_ship_count"}):
            statuses.add("ReadyToShip")
        if operations.intersection(
            {"orders.cancelled_count", "orders.cancellations"}
        ):
            statuses.add("Cancelled")
    for payload in _evidence_payloads(state):
        visit(payload)
    visit(state.goal, ("goal",))
    return {
        "strings": strings,
        "numbers": numbers,
        "sensitive": sensitive,
        "stores": stores,
        "statuses": statuses,
    }


def _cargo_provider_values(state: AgentSessionState) -> set[str]:
    """Collect carrier labels from current authoritative Order rows."""

    values: set[str] = set()
    for payload in _evidence_payloads(state):
        if not isinstance(payload, dict):
            continue
        raw_orders = [
            row
            for row in list(payload.get("orders") or [])
            if isinstance(row, dict)
        ]
        if isinstance(payload.get("order"), dict):
            raw_orders.append(dict(payload.get("order") or {}))
        for context in list(payload.get("contexts") or []):
            if isinstance(context, dict) and isinstance(
                context.get("order"), dict
            ):
                raw_orders.append(dict(context.get("order") or {}))
        for row in raw_orders:
            provider = _text(
                row.get("cargo_provider")
                or row.get("cargo_provider_name")
            )
            if provider:
                values.add(provider)
    return values


def _amount_values(state: AgentSessionState) -> list[int | float]:
    values: list[int | float] = []

    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, (*path, _key(key)))
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child, path)
            return
        if not path or path[-1] not in _AMOUNT_KEYS or isinstance(value, bool):
            return
        parsed: int | float | None = None
        if isinstance(value, (int, float)):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = float(value.replace(",", "."))
            except ValueError:
                parsed = None
        if parsed is not None and parsed not in values:
            values.append(parsed)

    for payload in _evidence_payloads(state):
        visit(payload)
    # Canonical valuation and cashflow totals carry money in scoped currency
    # rows, rather than the Orders-specific aggregate keys above.
    for operation, field, amount_key in (
        ("stock.inventory_overview", "stock_value_by_currency", "amount"),
        ("finance.cashflow_summary", "currency_totals", "combined_net"),
    ):
        result = next((dict(step.result_data or {}).get("tool_result") or {}
            for step in reversed(state.completed_steps)
            if step.status == "completed" and step.verification_status in {"observed", "verified"}
            and step.tool_names == [operation]
            and (dict(step.result_data or {}).get("tool_result") or {}).get("tool") == operation), {})
        for row in result.get(field) or []:
            if isinstance(row, dict):
                amount = row.get(amount_key)
                if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount not in values:
                    values.append(amount)
    return values


def _direct_numeric_values(
    state: AgentSessionState,
    *,
    keys: set[str],
    operations: set[str] | None = None,
) -> list[int | float]:
    """Read named metrics without borrowing numbers from nested sample rows."""

    values: list[int | float] = []
    normalized_keys = {_key(value) for value in keys}
    normalized_operations = {_text(value) for value in (operations or set())}
    for step in state.completed_steps:
        step_operations = {
            _text(value) for value in list(step.tool_names or []) if _text(value)
        }
        if normalized_operations and not step_operations.intersection(
            normalized_operations
        ):
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        for raw_key, raw_value in tool_result.items():
            if _key(raw_key) not in normalized_keys or isinstance(raw_value, bool):
                continue
            parsed: int | float | None = None
            if isinstance(raw_value, (int, float)):
                parsed = raw_value
            elif isinstance(raw_value, str):
                try:
                    parsed = float(raw_value.replace(",", "."))
                except ValueError:
                    parsed = None
            if parsed is not None and parsed not in values:
                values.append(parsed)
    return values


def _order_metric_numeric_values(
    state: AgentSessionState,
    metric_id: str,
) -> list[int | float]:
    """Read an Orders metric only from operations authorized by its domain contract."""

    values: list[int | float] = []
    for step in state.completed_steps:
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        for operation_id in (
            _text(value) for value in list(step.tool_names or []) if _text(value)
        ):
            evidence_keys = order_metric_evidence_keys(metric_id, operation_id)
            for key in evidence_keys:
                raw_value = tool_result.get(key)
                if isinstance(raw_value, bool):
                    continue
                parsed: int | float | None = None
                if isinstance(raw_value, (int, float)):
                    parsed = raw_value
                elif isinstance(raw_value, str):
                    try:
                        parsed = float(raw_value.replace(",", "."))
                    except ValueError:
                        parsed = None
                if parsed is not None and parsed not in values:
                    values.append(parsed)
    return values


def _cancellation_reason_distribution(
    state: AgentSessionState,
) -> dict[str, Any]:
    """Return the canonical cancellation summary for the active turn."""

    for step in reversed(state.completed_steps):
        operations = {
            _text(value) for value in list(step.tool_names or []) if _text(value)
        }
        if "orders.cancellations" not in operations:
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        if not isinstance(tool_result.get("cancel_reasons"), dict):
            continue
        try:
            cancelled_orders = int(tool_result.get("cancelled_orders") or 0)
        except (TypeError, ValueError):
            continue
        reasons: list[dict[str, Any]] = []
        for raw_reason, raw_count in dict(
            tool_result.get("cancel_reasons") or {}
        ).items():
            reason = _text(raw_reason)
            if not reason or isinstance(raw_count, bool):
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            reasons.append({"reason": reason, "count": count})
        reasons.sort(
            key=lambda row: (
                -int(row.get("count") or 0),
                _text(row.get("reason")).casefold(),
            )
        )
        return {
            "authoritative": True,
            "cancelled_orders": cancelled_orders,
            "reason_count_unit": _text(tool_result.get("cancel_reason_count_unit")) or "order_line",
            "reasons": reasons,
        }
    return {}


def _response_amount_values(
    state: AgentSessionState,
    *,
    prefer_order_rows: bool = False,
) -> list[int | float]:
    """Prefer the requested aggregate over unrelated per-order sample prices."""

    if prefer_order_rows:
        row_values: list[int | float] = []
        for payload in _evidence_payloads(state):
            if not isinstance(payload, dict):
                continue
            for raw in list(payload.get("orders") or []):
                if not isinstance(raw, dict):
                    continue
                value = raw.get("total_price")
                parsed: int | float | None = None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    parsed = value
                elif isinstance(value, str):
                    try:
                        parsed = float(value.replace(",", "."))
                    except ValueError:
                        parsed = None
                if parsed is not None and parsed not in row_values:
                    row_values.append(parsed)
        if row_values:
            return row_values
    if ORDER_REVENUE_TOTAL_METRIC in _order_metric_requirements(state):
        # Aggregate revenue is a typed metric. A product row's gross_amount,
        # an order sample price, or another nested number cannot satisfy it.
        return _order_metric_numeric_values(
            state,
            ORDER_REVENUE_TOTAL_METRIC,
        )
    aggregate_values = _direct_numeric_values(
        state,
        keys=_AGGREGATE_AMOUNT_KEYS,
    )
    return aggregate_values or _amount_values(state)


def _status_count_rows(state: AgentSessionState) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    for step in state.completed_steps:
        step_operations = {
            _text(value)
            for value in list(step.tool_names or [])
            if _text(value)
        }
        authoritative_keys = {
            key
            for operation_id in step_operations
            for metric_id in (
                ORDER_STATUS_DISTRIBUTION_METRIC,
                ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC,
            )
            for key in order_metric_evidence_keys(metric_id, operation_id)
        }
        if "status_counts" not in authoritative_keys:
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        raw_counts = tool_result.get("status_counts")
        if not isinstance(raw_counts, dict):
            continue
        clean: dict[str, int] = {}
        for raw_status, raw_count in raw_counts.items():
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            status = _text(raw_status)
            if status:
                clean[status] = count
        fingerprint = tuple(sorted(clean.items()))
        # An authoritative empty distribution is evidence of a zero-row
        # result, not absence of evidence. Keep one empty snapshot so the
        # verifier and fallback can distinguish it from a missing operation.
        if (clean or not raw_counts) and fingerprint not in seen:
            seen.add(fingerprint)
            rows.append(clean)
    return rows


def _focused_order_status_ratio(state: AgentSessionState) -> dict[str, Any]:
    """Project one or more typed status buckets over the order population."""

    contract = _turn_semantic_contract(state)
    if _text(contract.get("metric")).casefold() != "ratio":
        return {}
    status_scope = _text(contract.get("status_scope")).casefold()
    status_members = [
        _text(value).casefold()
        for value in list(contract.get("status_members") or [])
        if _text(value)
    ]
    if not status_members and status_scope in {
        "delivered",
        "cancelled",
        "shipped",
        "undelivered",
        "undelivered_and_returned",
    }:
        status_members = [status_scope]
    if not status_members:
        return {}
    rows = _status_count_rows(state)
    totals = _order_metric_numeric_values(state, ORDER_TOTAL_COUNT_METRIC)
    if len(rows) != 1 or not totals:
        return {}
    status_counts = rows[0]
    member_keys = {_key(value) for value in status_members}
    matching = [
        (status, int(count))
        for status, count in status_counts.items()
        if _key(status) in member_keys
    ]
    if len(matching) != len(member_keys):
        return {}
    denominator = int(totals[0])
    if denominator <= 0:
        return {}
    numerator = sum(count for _status, count in matching)
    statuses = [status for status, _count in matching]
    components = [
        {"status": status, "count": count}
        for status, count in matching
    ]
    return {
        "status": statuses[0] if len(statuses) == 1 else " + ".join(statuses),
        "statuses": statuses,
        "status_members": status_members,
        "components": components,
        "status_scope": status_scope,
        "numerator": numerator,
        "denominator": denominator,
        "percentage": round((numerator * 100.0) / denominator, 2),
    }


def _typed_status_member_keys(state: AgentSessionState) -> set[str]:
    """Return the exact lifecycle members authorized by the typed turn."""

    contract = _turn_semantic_contract(state)
    return {
        _key(value)
        for value in list(contract.get("status_members") or [])
        if _text(value)
    }


def _answer_mentions_status(answer: str, status: str) -> bool:
    normalized_answer = _normalized(answer)
    canonical = _normalized(status)
    if canonical and canonical in normalized_answer:
        return True
    aliases = _STATUS_PHRASES.get(_key(status), set())
    return any(_normalized(alias) in normalized_answer for alias in aliases)


def _folded_search_text(value: Any) -> str:
    text = unicodedata.normalize(
        "NFKD",
        _text(value).casefold().translate(str.maketrans({"ı": "i"})),
    )
    return "".join(char for char in text if not unicodedata.combining(char))


def _labelled_numeric_claims(answer: str, label_pattern: str) -> list[str]:
    searchable = _folded_search_text(answer)
    return [
        match.group(1)
        for match in re.finditer(
            rf"(?:{label_pattern})[^0-9]{{0,32}}([0-9](?:[0-9.,]*[0-9])?)",
            searchable,
            flags=re.IGNORECASE,
        )
    ]


def _total_order_claims(answer: str) -> list[str]:
    searchable = _folded_search_text(answer)
    claims = [
        match.group(1)
        for match in re.finditer(
            r"toplam(?:da)?[^0-9%]{0,24}([0-9](?:[0-9.,]*[0-9])?)\s*(?:adet\s+)?siparis",
            searchable,
            flags=re.IGNORECASE,
        )
    ]
    claims.extend(
        match.group(1)
        for match in re.finditer(
            r"toplam\s+siparis(?:ler)?[^0-9%]{0,24}([0-9](?:[0-9.,]*[0-9])?)",
            searchable,
            flags=re.IGNORECASE,
        )
    )
    return list(dict.fromkeys(claims))


def _answer_projects_total_order_value(
    answer: str,
    expected_values: list[int | float],
) -> bool:
    """Accept any natural wording that keeps the typed total beside its entity."""

    expected = {
        equivalent
        for value in expected_values
        for equivalent in _numeric_token_equivalents(value)
    }
    searchable = _folded_search_text(answer)
    for match in re.finditer(r"(?<![A-Za-z])\d+(?:[.,]\d+)*", searchable):
        if not _numeric_token_equivalents(match.group(0)).intersection(expected):
            continue
        window = searchable[
            max(0, match.start() - 36) : min(len(searchable), match.end() + 36)
        ]
        if re.search(r"\bsiparis(?:ler|i|in|te|ten)?\b|\border(?:s)?\b", window):
            return True
    return False


def _ready_order_claims(answer: str) -> list[str]:
    return _labelled_numeric_claims(
        answer,
        r"kargoya\s+hazir|ready\s*to\s*ship|readytoship",
    )


def _risk_counts(state: AgentSessionState) -> list[int]:
    if (
        ORDER_FULFILLMENT_RISK_COUNT_METRIC
        in _order_metric_requirements(state)
    ):
        return [
            int(value)
            for value in _order_metric_numeric_values(
                state,
                ORDER_FULFILLMENT_RISK_COUNT_METRIC,
            )
        ]
    values: list[int] = []
    risk_keys_by_operation = {
        "orders.fulfillment_risk": ("risk_count",),
        "orders.fulfillment_risk_count": ("risk_count",),
        "orders.shipping_deadline_analysis": ("overdue_count",),
    }
    for step in state.completed_steps:
        operation_ids = {
            _text(value) for value in list(step.tool_names or []) if _text(value)
        }
        keys = {
            key
            for operation_id in operation_ids
            for key in risk_keys_by_operation.get(operation_id, ())
        }
        if not keys:
            continue
        result_data = dict(step.result_data or {})
        candidates = [result_data]
        if isinstance(result_data.get("tool_result"), dict):
            candidates.append(dict(result_data.get("tool_result") or {}))
        for candidate in candidates:
            value = next(
                (candidate.get(key) for key in keys if candidate.get(key) is not None),
                None,
            )
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed not in values:
                values.append(parsed)
    return values


def _cargo_provider_options(state: AgentSessionState) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for step in state.completed_steps:
        operation_ids = {
            _text(value) for value in list(step.tool_names or []) if _text(value)
        }
        if not operation_ids.intersection(
            {"orders.cargo_provider_options", "logistics.provider_catalog"}
        ):
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        raw_rows = list(tool_result.get("providers") or tool_result.get("records") or [])
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            code = _text(raw.get("code"))
            name = _text(raw.get("name"))
            key = (code.casefold(), name.casefold())
            if (code or name) and key not in seen:
                seen.add(key)
                rows.append({"code": code, "name": name})
    return rows


def _provider_catalog_calendar_claims(answer: str, state: AgentSessionState) -> list[str]:
    normalized_answer = _normalized(answer)
    normalized_goal = _normalized(state.goal)
    month_names = (
        "ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik|"
        "january|february|march|april|may|june|july|august|september|october|november|december"
    )
    claims = [
        _text(match.group(0))
        for match in re.finditer(
            rf"(?<![a-z0-9])(?:[0-3]?\d\s+(?:{month_names})|(?:{month_names})\s+[0-3]?\d)(?![a-z0-9])",
            normalized_answer,
            flags=re.IGNORECASE,
        )
    ]
    return [claim for claim in claims if claim not in normalized_goal]


def _order_rows_projection(
    state: AgentSessionState,
    requested: set[str],
) -> list[dict[str, Any]]:
    if not requested.intersection(
        {
            "order_number",
            "status",
            "amount",
            "date",
            "customer_name",
            "cargo",
            "tracking_number",
            "package_id",
            "item_count",
            "item",
            "sku",
            "barcode",
            "quantity",
        }
    ):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    contexts_by_order = {
        _text(context.get("order", {}).get("order_number")): context
        for context in _full_order_context_rows(state)
    } if _typed_order_list(state) else {}
    interpretation = dict(state.active_entities.get("turn_interpretation") or {})
    for payload in _evidence_payloads(state):
        if not isinstance(payload, dict):
            continue
        raw_rows = list(payload.get("orders") or [])
        if isinstance(payload.get("order"), dict):
            raw_rows.append(dict(payload.get("order") or {}))
        for context in list(payload.get("contexts") or []):
            if not isinstance(context, dict):
                continue
            if isinstance(context.get("order"), dict):
                raw_rows.append(dict(context.get("order") or {}))
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            order_number = _text(raw.get("order_number"))
            if not order_number or order_number in seen:
                continue
            seen.add(order_number)
            row: dict[str, Any] = {}
            if "order_number" in requested:
                row["order_number"] = order_number
            if "status" in requested:
                row["status"] = _text(raw.get("status"))
            if "amount" in requested:
                row["amount"] = raw.get("total_price")
                row["currency"] = _text(raw.get("currency"))
            if "date" in requested:
                row["date"] = _text(raw.get("order_date"))
            if "customer_name" in requested:
                row["customer_name"] = _text(
                    raw.get("customer") or raw.get("customer_name")
                )
            if "cargo" in requested:
                row["cargo"] = _text(
                    raw.get("cargo_provider")
                    or raw.get("cargo_provider_name")
                )
            if "tracking_number" in requested:
                row["tracking_number"] = _text(
                    raw.get("cargo_tracking_number")
                    or raw.get("tracking_number")
                )
            if "package_id" in requested:
                row["package_id"] = _text(
                    raw.get("package_id") or raw.get("shipment_package_id")
                )
            if "item_count" in requested:
                row["item_count"] = raw.get("item_count")
            if _typed_order_list(state):
                if interpretation.get("identifier_display") == "ordinal" or "order_number" not in requested:
                    row["ordinal"] = len(rows) + 1
                item_fields = requested.intersection({"item", "sku", "barcode", "quantity"})
                if item_fields:
                    context = contexts_by_order.get(order_number)
                    row["items"] = None if context is None else [
                        {
                            ("product_name" if field == "item" else field): item.get("product_name" if field == "item" else field)
                            for field in sorted(item_fields)
                        }
                        for item in context.get("items") or [] if isinstance(item, dict)
                    ]
            rows.append(row)
    return rows


def _authoritative_empty_order_list(state: AgentSessionState) -> bool:
    contract = _turn_semantic_contract(state)
    if (
        _text(contract.get("entity")).casefold() != "order"
        or _text(contract.get("metric")).casefold() != "list"
        or _text(contract.get("record_scope")).casefold() != "all_matching"
    ):
        return False
    allowed_operations = {
        "orders.query",
        "orders.ready_to_ship",
        "orders.recent",
    }
    cardinality_keys = (
        "listed_count",
        "selected_count",
        "count",
        "ready_to_ship",
    )
    for step in state.completed_steps:
        operations = {
            _text(value)
            for value in list(step.tool_names or [])
            if _text(value)
        }
        if not operations.intersection(allowed_operations):
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        if not isinstance(tool_result.get("orders"), list):
            continue
        if tool_result.get("orders"):
            continue
        for key in cardinality_keys:
            raw_value = tool_result.get(key)
            if isinstance(raw_value, bool):
                continue
            try:
                if int(raw_value) == 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _return_query_list_result(state: AgentSessionState) -> dict[str, Any]:
    """Return the current contract-matching authoritative return list."""

    contract = _turn_semantic_contract(state)
    if (
        _text(contract.get("entity")).casefold() != "return_claim"
        or _text(contract.get("metric")).casefold() != "list"
    ):
        return {}
    status_scope = _text(contract.get("status_scope")).casefold()
    expected_period = _text(contract.get("period")).casefold()
    for step in reversed(state.completed_steps):
        operations = {
            _text(value) for value in list(step.tool_names or []) if _text(value)
        }
        if "returns.query" not in operations:
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        if not isinstance(tool_result.get("returns"), list):
            continue
        if _text(tool_result.get("mode")).casefold() not in {"", "list"}:
            continue
        actual_period = _text(tool_result.get("period")).casefold()
        if expected_period and actual_period and actual_period != expected_period:
            continue
        filters = dict(tool_result.get("filters") or {})
        if status_scope == "waiting_action":
            statuses = {
                _text(value).casefold()
                for value in (
                    list(filters.get("statuses") or [])
                    + [filters.get("status")]
                )
                if _text(value)
            }
            waiting_filter = bool(
                filters.get("waiting_action_only")
                or filters.get("actionable")
                or "waitinginaction" in statuses
            )
            if not waiting_filter:
                continue
        return tool_result
    return {}


def _return_rows_projection(
    state: AgentSessionState,
    requested: set[str],
) -> list[dict[str, Any]]:
    result = _return_query_list_result(state)
    rows: list[dict[str, Any]] = []
    for raw in list(result.get("returns") or []):
        if not isinstance(raw, dict):
            continue
        row: dict[str, Any] = {}
        if "claim_id" in requested:
            row["claim_id"] = _text(
                raw.get("claim_id") or raw.get("claim_number")
            )
        if "order_number" in requested:
            row["order_number"] = _text(raw.get("order_number"))
        if "status" in requested:
            row["status"] = _text(raw.get("status"))
        if "reason" in requested:
            row["reason"] = _text(raw.get("reason"))
        rows.append(row)
    return rows


def _authoritative_empty_return_list(state: AgentSessionState) -> bool:
    result = _return_query_list_result(state)
    if not result or result.get("returns") != [] or result.get("truncated") is not False:
        return False
    try:
        total_count = int(result.get("total_count", result.get("count")))
    except (TypeError, ValueError):
        return False
    return total_count == 0


def _answer_states_empty_return_list(answer: str) -> bool:
    normalized = _normalized(answer)
    return bool(
        re.search(r"(?<!\w)0\s+(?:adet\s+)?(?:iade|claim)(?!\w)", normalized)
        or any(
            marker in normalized
            for marker in (
                "iade yok",
                "iade bulunmuyor",
                "iade kaydi yok",
                "eslesen iade yok",
                "aksiyon bekleyen iade yok",
                "onay bekleyen iade yok",
                "claim bulunmuyor",
            )
        )
    )


def _answer_states_empty_order_list(answer: str) -> bool:
    normalized = _normalized(answer)
    return bool(
        re.search(r"(?<!\w)0\s+(?:adet\s+)?siparis(?!\w)", normalized)
        or any(
            marker in normalized
            for marker in (
                "siparis yok",
                "eslesen siparis yok",
                "eslesen kayit yok",
                "kayit bulunmuyor",
                "siparis bulunmuyor",
                "kuyruk bos",
                "kuyrugu bos",
            )
        )
    )


def _answer_states_empty_item_sales(answer: str) -> bool:
    normalized = _normalized(answer)
    return bool(
        any(
            marker in normalized
            for marker in (
                "urun satisi yok",
                "urun satiri yok",
                "satilan urun yok",
                "siparis kalemi satisi yok",
                "en cok satan urun bulunmuyor",
                "urun satis kaydi bulunmuyor",
            )
        )
        or re.search(
            r"(?<!\w)0\s+(?:adet\s+)?(?:urun|urun\s+satisi|"
            r"siparis\s+kalemi)(?!\w)",
            normalized,
        )
    )


def _full_order_context_rows(state: AgentSessionState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in state.completed_steps:
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        for raw in list(tool_result.get("contexts") or []):
            if isinstance(raw, dict):
                rows.append(dict(raw))
    return rows


def _exact_status_read_evidence_problems(state: AgentSessionState) -> list[str]:
    contract = _turn_semantic_contract(state)
    codes = set(order_status_codes(contract))
    if not codes:
        return []
    reason_aggregate = cancellation_reason_distribution_contract(contract)
    matching_results: list[dict[str, Any]] = []
    for step in state.completed_steps:
        payload = dict((step.result_data or {}).get("tool_result") or {})
        operation_id = _text(payload.get("tool")) or next(iter(step.tool_names), "")
        if validate_orders_read_arguments(
            contract, operation_id,
            {"filters": payload.get("filters"), "mode": payload.get("mode") or "list"},
        ):
            continue
        matching_results.append(payload)
    if not matching_results:
        return ["exact_status_read_evidence_missing"]
    problems: list[str] = []
    for payload in matching_results:
        rows = list(payload.get("orders") or []) + [
            context.get("order") or {}
            for context in list(payload.get("contexts") or [])
            if isinstance(context, dict)
        ]
        if any(_text(row.get("status")) not in codes for row in rows if isinstance(row, dict)):
            problems.append("exact_status_result_scope_mismatch")
        if (
            not reason_aggregate
            and
            contract.get("record_scope") == "all_matching"
            and contract.get("metric") in {"list", "detail"}
            and (payload.get("truncated") is True or int(payload.get("total_count") or 0) > len(rows))
        ):
            problems.append("exact_status_full_list_incomplete")
    return list(dict.fromkeys(problems))


def _return_context_evidence(state: AgentSessionState) -> tuple[bool, int]:
    contexts = _full_order_context_rows(state)
    if contexts:
        found = any("returns" in row for row in contexts)
        return found, sum(
            len(row.get("returns") or [])
            for row in contexts
            if isinstance(row.get("returns"), list)
        )
    counts: list[int] = []
    for payload in _evidence_payloads(state):
        if isinstance(payload, dict) and isinstance(payload.get("returns"), list):
            counts.append(len(payload.get("returns") or []))
    return (bool(counts), max(counts) if counts else 0)


def _order_item_text(item: dict[str, Any], requested: set[str]) -> str:
    parts: list[str] = []
    if "item" in requested:
        parts.append(_text(item.get("product_name")) or "Urun")
    for field, label in (("sku", "SKU"), ("barcode", "Barkod"), ("quantity", "adet")):
        if field in requested:
            value = item.get(field)
            parts.append(f"{label}: {value if value is not None and _text(value) else 'belirtilmemis'}")
    return " | ".join(parts)


def _full_order_context_projection(
    state: AgentSessionState,
    requested: set[str],
) -> str:
    contexts = _full_order_context_rows(state)
    if not contexts:
        return "Siparis tam baglami authoritative sonuc icinde bulunamadi."
    sections: list[str] = []
    for context in contexts:
        order = dict(context.get("order") or {})
        order_number = _text(order.get("order_number"))
        lines = [
            f"Siparis {order_number} detaylari:"
            if order_number and "order_number" in requested
            else "Siparis detaylari:"
        ]
        if requested.intersection({"item", "sku", "barcode", "quantity"}):
            items = [row for row in list(context.get("items") or []) if isinstance(row, dict)]
            if items:
                lines.append("Kalemler:")
                for item in items:
                    lines.append(f"- {_order_item_text(item, requested)}")
            else:
                lines.append("Siparis kalemi bulunmuyor.")
        if "amount" in requested:
            total_price = order.get("total_price")
            currency = _text(order.get("currency"))
            if total_price is None:
                lines.append("Tutar: belirtilmemis.")
            else:
                lines.append(
                    f"Tutar: {total_price}"
                    + (f" {currency}" if currency else "")
                    + "."
                )
        if "status" in requested:
            status = _text(order.get("status"))
            lines.append(
                f"Durum: {status}."
                if status
                else "Siparis durumu belirtilmemis."
            )
        if "cargo" in requested or "tracking_number" in requested:
            provider = _text(
                order.get("cargo_provider") or order.get("cargo_provider_name")
            )
            tracking = _text(
                order.get("cargo_tracking_number") or order.get("tracking_number")
            )
            cargo_parts = []
            if "cargo" in requested and provider:
                cargo_parts.append(provider)
            if "tracking_number" in requested and tracking:
                cargo_parts.append(tracking)
            lines.append(
                "Kargo: " + " | ".join(cargo_parts) + "."
                if cargo_parts
                else "Istenen kargo bilgisi bulunmuyor."
            )
        if "returns" in requested:
            returns = [row for row in list(context.get("returns") or []) if isinstance(row, dict)]
            if not returns:
                lines.append("Iade kaydi yok.")
            else:
                lines.append(f"Iade kaydi: {len(returns)}.")
                for row in returns:
                    status = _text(row.get("status"))
                    reason = _text(row.get("reason") or row.get("return_reason"))
                    detail = " | ".join(value for value in (status, reason) if value)
                    if detail:
                        lines.append(f"- {detail}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _stock_detail_rows(state: AgentSessionState) -> list[dict[str, Any]]:
    """Stock records cannot impersonate a typed order or mixed record scope."""
    if _text(_turn_semantic_contract(state).get("entity")).casefold() in {"order", "order_item", "return_claim"}:
        return []
    if any(step.status == "completed" and step.operation_domain == "orders" for step in state.completed_steps):
        return []
    for step in reversed(state.completed_steps):
        if step.status != "completed" or step.verification_status not in {"observed", "verified"} or step.tool_names != ["stock.inventory_overview"]:
            continue
        result = (step.result_data or {}).get("tool_result") or {}
        if result.get("tool") == "stock.inventory_overview":
            return [row for row in result.get("top_balances") or [] if isinstance(row, dict)]
    return []


def _stock_detail_answer(state: AgentSessionState, requested: set[str]) -> str:
    if not requested.intersection({"item", "sku", "quantity"}):
        return ""
    lines = []
    for row in _stock_detail_rows(state):
        line = f"{_text(row.get('sku'))} — {_text(row.get('name'))}: {_text(row.get('balance'))} {_text(row.get('unit'))}."
        if requested.intersection({"amount", "currency"}) and row.get("stock_value") is not None:
            line += f" Stok değeri: {_text(row.get('stock_value'))} {_text(row.get('stock_value_currency'))}."
        lines.append(line)
    return "\n".join(lines)


def _full_order_context_projection_problems(
    answer: str,
    state: AgentSessionState,
    requested: set[str],
) -> list[str]:
    """Verify record-detail fields against materialized order contexts."""

    detail_fields = {
        "item",
        "sku",
        "barcode",
        "quantity",
        "cargo",
        "tracking_number",
    }
    if not requested.intersection(detail_fields):
        return []
    stock_rows = _stock_detail_rows(state)
    if stock_rows and requested.intersection({"item", "sku", "quantity"}):
        problems = []
        for row in stock_rows:
            for field, key in (("item", "name"), ("sku", "sku")):
                if field in requested and _text(row.get(key)) and _normalized(row[key]) not in _normalized(answer):
                    problems.append("stock_record_projection_missing:" + key)
            if "quantity" in requested and not any(
                _text(row.get("sku")) in segment and _text(row.get("unit")) in segment
                and any(_numeric_token_equivalents(token).intersection(_numeric_token_equivalents(row.get("balance")))
                        for token in _answer_numeric_tokens(segment))
                for segment in answer.splitlines()
            ):
                problems.append("stock_record_quantity_unit_projection_missing")
        return problems
    contexts = _full_order_context_rows(state)
    if not contexts:
        contract = _turn_semantic_contract(state)
        if (
            contract.get(
                "contextual_public_product_web_research_required"
            )
            is True
            and "item" in requested
        ):
            identities: list[dict[str, Any]] = []
            for step in state.completed_steps:
                if "orders.product_public_identities" not in {
                    _text(value) for value in list(step.tool_names or [])
                }:
                    continue
                result_data = dict(step.result_data or {})
                tool_result = (
                    dict(result_data.get("tool_result") or {})
                    if isinstance(result_data.get("tool_result"), dict)
                    else {}
                )
                identities.extend(
                    dict(row)
                    for row in list(
                        tool_result.get("product_identities") or []
                    )
                    if isinstance(row, dict)
                    and _text(row.get("product_name"))
                )
            if not identities:
                return ["public_product_identity_evidence_missing"]

            def public_identity_is_projected(product_name: Any) -> bool:
                normalized_product = _normalized(product_name)
                normalized_answer = _normalized(answer)
                if normalized_product and normalized_product in normalized_answer:
                    return True
                # Marketplace titles commonly append pack size, merchant
                # codes and variant noise.  Public web sources may use a
                # different seller title for the same product type. Match a
                # strong majority of meaningful public-name tokens; never use
                # SKU, order, customer or other private identifiers here.
                ignored = {
                    "adet",
                    "urun",
                    "urunu",
                    "product",
                    "item",
                    "one",
                    "size",
                    "tek",
                    "ebat",
                }
                product_tokens = list(
                    dict.fromkeys(
                        token
                        for token in re.findall(
                            r"[a-z0-9]+",
                            normalized_product,
                        )
                        if len(token) >= 3
                        and token not in ignored
                        and not any(char.isdigit() for char in token)
                    )
                )
                if not product_tokens:
                    return False
                answer_tokens = set(
                    re.findall(r"[a-z0-9]+", normalized_answer)
                )
                matched = sum(
                    1 for token in product_tokens if token in answer_tokens
                )
                required = min(
                    len(product_tokens),
                    max(2, (len(product_tokens) * 7 + 9) // 10),
                )
                return matched >= required

            return [
                f"public_product_projection_missing:{index}"
                for index, identity in enumerate(identities, start=1)
                if not public_identity_is_projected(
                    identity.get("product_name")
                )
            ]
        # Cargo/tracking can also be a row-list projection and is verified by
        # the row contract below. Item/quantity, however, requires materialized
        # line context and must fail closed when that evidence is absent.
        return (
            ["full_order_context_evidence_missing"]
            if requested.intersection({"item", "sku", "barcode", "quantity"})
            else []
        )

    normalized_answer = _normalized(answer)
    answer_lines = [_text(line) for line in answer.splitlines() if _text(line)]

    def line_projects_labelled_quantity(line: str, quantity: Any) -> bool:
        normalized_line = _normalized(line)
        for token in _answer_numeric_tokens(line):
            if not _numeric_token_equivalents(token).intersection(
                _numeric_token_equivalents(quantity)
            ):
                continue
            normalized_token = _normalized(token)
            if normalized_token and re.search(
                rf"(?<![a-z0-9])(?:adet|miktar|quantity|qty)\s+"
                rf"{re.escape(normalized_token)}(?![a-z0-9])",
                normalized_line,
            ):
                return True
        return False

    def line_projects_labelled_identifier(
        line: str,
        *,
        value: Any,
        labels: tuple[str, ...],
    ) -> bool:
        normalized_line = _normalized(line)
        normalized_value = _normalized(value)
        if not normalized_value or normalized_value not in normalized_line:
            return False
        return any(
            re.search(
                rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])",
                normalized_line,
            )
            for label in labels
        )

    def line_projects_missing_identifier(
        line: str,
        *,
        labels: tuple[str, ...],
    ) -> bool:
        normalized_line = _normalized(line)
        return bool(
            any(
                re.search(
                    rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])",
                    normalized_line,
                )
                for label in labels
            )
            and any(
                marker in normalized_line
                for marker in (
                    "belirtilmemis",
                    "bulunmuyor",
                    "mevcut degil",
                    "yok",
                )
            )
        )

    problems: list[str] = []
    context_blocks = record_answer_blocks(answer, [
        _text(context.get("order", {}).get("order_number")) if "order_number" in requested else ""
        for context in contexts
    ]) if _typed_order_list(state) else []
    for context_index, context in enumerate(contexts, start=1):
        scoped_answer = answer
        if context_blocks:
            scoped_answer = _text(context_blocks[context_index - 1].get("text"))
            normalized_answer = _normalized(scoped_answer)
            answer_lines = [_text(line) for line in scoped_answer.splitlines() if _text(line)]
        order = dict(context.get("order") or {})
        order_number = _text(order.get("order_number")) or str(context_index)
        items = [
            dict(row)
            for row in list(context.get("items") or [])
            if isinstance(row, dict)
        ]
        if requested.intersection({"item", "sku", "barcode", "quantity"}):
            if not items:
                if not any(
                    marker in normalized_answer
                    for marker in (
                        "siparis kalemi bulunmuyor",
                        "urun bulunmuyor",
                        "kalem bulunmuyor",
                    )
                ):
                    problems.append(
                        f"item_projection_missing:{order_number}:empty"
                    )
            for item_index, item in enumerate(items, start=1):
                product_name = _text(item.get("product_name"))
                matching_line = next(
                    (
                        line
                        for line in answer_lines
                        if product_name
                        and _normalized(product_name) in _normalized(line)
                    ),
                    "",
                )
                if "item" in requested and product_name and not matching_line:
                    problems.append(
                        f"item_projection_missing:{order_number}:{item_index}"
                    )
                for field_name, labels in (
                    ("sku", ("sku", "stok kodu", "stock code")),
                    ("barcode", ("barkod", "barcode", "gtin")),
                ):
                    if field_name not in requested:
                        continue
                    value = _text(item.get(field_name))
                    if value:
                        if not any(
                            line_projects_labelled_identifier(
                                line,
                                value=value,
                                labels=labels,
                            )
                            for line in answer_lines
                        ):
                            problems.append(
                                f"{field_name}_projection_missing:"
                                f"{order_number}:{item_index}"
                            )
                    elif not any(
                        line_projects_missing_identifier(
                            line,
                            labels=labels,
                        )
                        for line in answer_lines
                    ):
                        problems.append(
                            f"{field_name}_absence_projection_missing:"
                            f"{order_number}:{item_index}"
                        )
                if "quantity" in requested:
                    quantity = item.get("quantity")
                    if quantity is None:
                        problems.append(
                            f"quantity_evidence_missing:{order_number}:{item_index}"
                        )
                    else:
                        candidate_lines = [matching_line] if matching_line else []
                        if len(items) == 1:
                            # With one materialized line item, a separate
                            # ``Adet: 2`` row is unambiguous. Require a labelled
                            # value so a package-size phrase inside the product
                            # name (for example ``20 Adet``) cannot impersonate
                            # the actual order-line quantity.
                            candidate_lines.extend(answer_lines)
                        if not any(
                            line_projects_labelled_quantity(line, quantity)
                            for line in dict.fromkeys(candidate_lines)
                            if _text(line)
                        ):
                            problems.append(
                                f"quantity_projection_missing:{order_number}:{item_index}"
                            )
        if "cargo" in requested:
            provider = _text(
                order.get("cargo_provider")
                or order.get("cargo_provider_name")
            )
            if provider and _normalized(provider) not in normalized_answer:
                problems.append(f"cargo_projection_missing:{order_number}")
            elif not provider and not any(
                marker in normalized_answer
                for marker in ("kargo bilgisi bulunmuyor", "kargo firmasi yok")
            ):
                problems.append(f"cargo_evidence_missing:{order_number}")
        if "tracking_number" in requested:
            tracking = _text(
                order.get("cargo_tracking_number")
                or order.get("tracking_number")
            )
            if tracking and tracking.casefold() not in scoped_answer.casefold():
                problems.append(
                    f"tracking_projection_missing:{order_number}"
                )
            elif not tracking and not any(
                marker in normalized_answer
                for marker in (
                    "takip bilgisi bulunmuyor",
                    "takip numarasi yok",
                )
            ):
                problems.append(
                    f"tracking_evidence_missing:{order_number}"
                )
    return problems


def _opened_web_observations(state: AgentSessionState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in state.completed_steps:
        operations = {_text(value) for value in list(step.tool_names or []) if _text(value)}
        if not operations.intersection({"web.open", "web.follow", "web.document.read"}):
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        observation = tool_result.get("web_observation")
        if not isinstance(observation, dict):
            continue
        goal_assessment = (
            dict(tool_result.get("goal_evidence_assessment") or {})
            if isinstance(tool_result.get("goal_evidence_assessment"), dict)
            else {}
        )
        if goal_assessment and not bool(goal_assessment.get("adequate")):
            # The URL was reachable, but the opened text did not prove the
            # user's requested fact.  It remains recovery/audit evidence and
            # must never become a cited answer source.
            continue
        url = _text(observation.get("url"))
        observation_id = _text(observation.get("observation_id"))
        content_hash = _text(observation.get("content_hash"))
        if not url.startswith(("https://", "http://")) or not observation_id or not content_hash:
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(dict(observation))
    return rows


def web_evidence_projection(state: AgentSessionState) -> list[dict[str, Any]]:
    """Project only opened sources; search snippets never become evidence."""

    projected: list[dict[str, Any]] = []
    for row in _opened_web_observations(state):
        injection = bool(row.get("prompt_injection_detected"))
        projected.append(
            {
                "observation_id": _text(row.get("observation_id")),
                "title": _text(row.get("title")) or _text(row.get("source_domain")) or "Kaynak",
                "url": _text(row.get("url")),
                "source_domain": _text(row.get("source_domain")),
                "source_class": _text(row.get("source_class")),
                "published_at": _text(row.get("published_at")),
                "accessed_at": _text(row.get("accessed_at")),
                "freshness": _text(row.get("freshness")),
                "trust": _text(row.get("trust")),
                "prompt_injection_detected": injection,
                "supported_claims": [
                    _text(value)
                    for value in list(row.get("supported_claims") or [])
                    if _text(value)
                ][:20],
                "contradictions": [
                    _text(value)
                    for value in list(row.get("contradictions") or [])
                    if _text(value)
                ][:20],
                # This is quoted evidence, never instruction material.  A
                # detected injection removes page prose from the model view.
                "evidence_excerpt": ""
                if injection
                else _text(row.get("relevant_text"))[:1_200],
            }
        )
    return projected


def append_verified_web_citations(answer: str, state: AgentSessionState) -> str:
    sources = web_evidence_projection(state)
    if not sources:
        return _text(answer)
    raw = _text(answer)
    missing = [row for row in sources if _text(row.get("url")) not in raw]
    if not missing:
        return raw
    lines = ["Kaynaklar:"]
    for row in missing:
        title = _text(row.get("title")) or _text(row.get("source_domain")) or "Kaynak"
        title = title.replace("[", "(").replace("]", ")")
        lines.append(f"- [{title}]({_text(row.get('url'))})")
    return "\n\n".join([raw, "\n".join(lines)]).strip()


def _answer_numeric_tokens(answer: str) -> list[str]:
    # Keep unary signs attached to their values. A date/range separator or
    # subtraction operator following a number is not a unary sign. The
    # unsigned branch preserves the existing identifier/date token contract.
    return re.findall(
        r"(?<![\w.,])[-+−]\d+(?:[.,]\d+)*|(?<![A-Za-z])\d+(?:[.,]\d+)*",
        answer,
    )


def _monetary_claims(answer: str, currencies: Iterable[str]) -> list[tuple[str, str]]:
    codes = sorted({_text(code).upper() for code in currencies if _text(code)}, key=len, reverse=True)
    if not codes:
        return []
    code_pattern = "|".join(re.escape(code) for code in codes)
    number_pattern = r"[-+−]?\d+(?:[.,]\d+)*"
    claims = []
    for match in re.finditer(
        rf"(?<!\w)({number_pattern})\s*({code_pattern})(?!\w)|"
        rf"(?<!\w)({code_pattern})\s*({number_pattern})(?!\w)",
        answer, flags=re.IGNORECASE,
    ):
        claims.append((match.group(1) or match.group(4), (match.group(2) or match.group(3)).upper()))
    return claims


def _numeric_token_equivalents(value: Any) -> set[str]:
    if value is None or isinstance(value, bool):
        return set()
    token = str(value).strip().replace("−", "-")
    if not token:
        return set()
    equivalents = {token.replace(",", ".")}

    def add_decimal_equivalent(candidate: str) -> None:
        try:
            parsed = Decimal(candidate)
        except (InvalidOperation, ValueError):
            return
        normalized = format(parsed.normalize(), "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        equivalents.add(normalized or "0")

    add_decimal_equivalent(token.replace(",", "."))
    integral_decimal = re.fullmatch(r"([+-]?\d+)[.,]0+", token)
    if integral_decimal:
        equivalents.add(integral_decimal.group(1))
    # Turkish and many European locales render integer thousands as 3.112 or
    # 3,112. If the source contains 3112, that formatting is the same fact,
    # not a hallucinated decimal. Only accept the stripped form when every
    # separator is followed by an exact three-digit grouping.
    sign = "-" if token.startswith("-") else ""
    magnitude = token.lstrip("+-")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", magnitude):
        equivalents.add(sign + re.sub(r"[.,]", "", magnitude))
    if "." in token and "," in token:
        decimal_separator = "." if token.rfind(".") > token.rfind(",") else ","
        thousands_separator = "," if decimal_separator == "." else "."
        integer_part, fractional_part = magnitude.rsplit(decimal_separator, 1)
        grouped_integer = integer_part.split(thousands_separator)
        if (
            fractional_part.isdigit()
            and grouped_integer
            and grouped_integer[0].isdigit()
            and 1 <= len(grouped_integer[0]) <= 3
            and all(
                part.isdigit() and len(part) == 3
                for part in grouped_integer[1:]
            )
        ):
            locale_normalized = sign + "".join(grouped_integer) + "." + fractional_part
            equivalents.add(locale_normalized)
            add_decimal_equivalent(locale_normalized)
    return equivalents


def _comparison_projection_segments(answer: str, calculation: dict[str, Any]) -> list[tuple[str, bool]]:
    """Match a relation by its bound values, order and operator, across locales."""
    operands = list(calculation.get("operands") or [])
    if len(operands) != 2:
        return []
    left = _numeric_token_equivalents(operands[0].get("value"))
    right = _numeric_token_equivalents(operands[1].get("value"))
    symbol = {
        "greater_than": ">", "greater_or_equal": ">=", "less_than": "<",
        "less_or_equal": "<=", "equal": "==", "not_equal": "!=",
    }.get(calculation.get("comparison_operator") or calculation.get("operator"))
    inverse = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "==": "==", "!=": "!="}.get(symbol)
    number = r"[-+−]?\d+(?:[.,]\d+)*"
    pattern = rf"(?<![\w.,])({number})\s*(>=|<=|==|!=|>|<|=|≥|≤|≠)\s*({number})(?![\w.,])"
    segments = []
    for segment in re.split(r"[\n;]+", answer):
        for match in re.finditer(pattern, segment):
            actual_left = _numeric_token_equivalents(match.group(1))
            actual_right = _numeric_token_equivalents(match.group(3))
            actual_symbol = {"=": "==", "≥": ">=", "≤": "<=", "≠": "!="}.get(match.group(2), match.group(2))
            ordered = bool(left.intersection(actual_left) and right.intersection(actual_right))
            reversed_order = bool(left.intersection(actual_right) and right.intersection(actual_left))
            relation_matches = bool(ordered and actual_symbol == symbol or reversed_order and actual_symbol == inverse)
            if relation_matches:
                # The same operands can have separately requested relations
                # (less-than true and greater-than false). Review each truth
                # only against its own relation, not a neighbouring proof.
                segments.append((_folded_search_text(segment), True))
    return segments


def _date_numeric_equivalents(value: Any) -> set[str]:
    raw = _text(value)
    equivalents: set[str] = set()
    for year, month, day in re.findall(
        r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
        raw,
    ):
        month = month.zfill(2)
        day = day.zfill(2)
        equivalents.update(
            {
                f"{year}.{month}.{day}",
                f"{day}.{month}.{year}",
            }
        )
    return equivalents


def _answer_contains_sensitive_value(answer: str, value: Any) -> bool:
    clean = _text(value)
    if len(clean) < 3:
        return False
    return bool(
        re.search(
            rf"(?<!\w){re.escape(clean)}(?!\w)",
            _text(answer),
            flags=re.IGNORECASE,
        )
    )


def _number_is_ordinal(answer: str, token: str) -> bool:
    pattern = re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)")
    return len(pattern.findall(answer)) > len(pattern.findall(presentation_numeric_text(answer)))


def _status_claim_problems(answer: str, statuses: set[str]) -> list[str]:
    normalized_answer = _normalized(answer)
    normalized_statuses = {_key(status) for status in statuses if _text(status)}
    problems: list[str] = []
    for canonical, phrases in _STATUS_PHRASES.items():
        if not any(_normalized(phrase) in normalized_answer for phrase in phrases):
            continue
        compatible = any(
            canonical in status or status in canonical
            for status in normalized_statuses
            if status
        )
        if not compatible:
            problems.append(f"ungrounded_status:{canonical}")
    return problems


def _executed_action_state_problems(answer: str, state: AgentSessionState) -> list[str]:
    has_execute, all_verified = _has_verified_execute(state)
    if not has_execute or not all_verified or state.active_pending_action():
        return []
    normalized = _normalized(answer)
    problems = []
    if re.search(r"\bonay(?:ini|inizi|i|imizi)?\s+bekl(?:iyor(?:um|uz)?|eniyor)\b", normalized):
        problems.append("executed_action_claimed_pending")
    workflow_saved = any(event.get("phase") == "execute" and event.get("success") is True
                         and event.get("action_type") == "ai.action_save_workflow_spec"
                         and (event.get("verify") or {}).get("verified") is True
                         for event in state.action_history)
    if workflow_saved and re.search(
        r"\b(?:yonerge|talimat\w*|is paketi|workflow)\b[^.\n!?]{0,140}"
        r"\b(?:kaydedilmedi|kaydedilmemis|saklanmadi|not (?:been )?saved)\b", normalized
    ):
        problems.append("verified_workflow_claimed_unsaved")
    return problems


def _has_verified_execute(state: AgentSessionState) -> tuple[bool, bool]:
    execute_rows = [
        event
        for event in state.action_history
        if event.get("phase") == "execute" and event.get("success") is True
    ]
    return bool(execute_rows), bool(execute_rows) and all(
        isinstance(event.get("verify"), dict)
        and (event.get("verify") or {}).get("verified") is True
        for event in execute_rows
    )


def _record_response_verification(
    state: AgentSessionState,
    *,
    allowed: bool,
    source: str,
    requested_fields: set[str],
    reason_codes: list[str],
) -> dict[str, Any]:
    active = state.active_entities if isinstance(state.active_entities, dict) else {}
    rows = [
        dict(row)
        for row in list(active.get("response_verifications") or [])
        if isinstance(row, dict)
    ]
    row = {
        "allowed": bool(allowed),
        "source": _text(source),
        "requested_fields": sorted(requested_fields),
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    rows.append(row)
    active["response_verifications"] = rows
    state.active_entities = active
    state.touch()
    return row


def _item_sales_report_rows(
    state: AgentSessionState,
) -> tuple[list[dict[str, Any]], str]:
    record_scope = _text(
        _turn_semantic_contract(state).get("record_scope")
    ).casefold()
    for step in state.completed_steps:
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        operation_ids = {
            _text(value)
            for value in list(step.tool_names or [])
            if _text(value)
        }
        if "orders.item_sales_summary" in operation_ids:
            tool_call = (
                dict(result_data.get("tool_call") or {})
                if isinstance(result_data.get("tool_call"), dict)
                else {}
            )
            call_arguments = (
                dict(tool_call.get("arguments") or {})
                if isinstance(tool_call.get("arguments"), dict)
                else dict(step.arguments or {})
            )
            if (
                record_scope == "all_matching"
                and list(call_arguments.get("order_numbers") or [])
            ):
                continue
            rows = [
                {
                    **dict(raw),
                    "rank": int(raw.get("rank") or index),
                }
                for index, raw in enumerate(
                    (
                        row
                        for row in list(tool_result.get("rows") or [])
                        if isinstance(row, dict)
                        and _text(row.get("product_name"))
                    ),
                    start=1,
                )
            ]
            if rows:
                return rows, _text(
                    tool_result.get("period_label")
                    or tool_result.get("period")
                )
        snapshot = (
            dict(tool_result.get("report_snapshot") or {})
            if isinstance(tool_result.get("report_snapshot"), dict)
            else {}
        )
        if _text(snapshot.get("report_type")) != "orders.item_sales":
            continue
        for sheet in list(snapshot.get("sheets") or []):
            if not isinstance(sheet, dict):
                continue
            columns = [
                _text(column.get("key"))
                for column in list(sheet.get("columns") or [])
                if isinstance(column, dict) and _text(column.get("key"))
            ]
            if not {"product_name", "quantity", "order_count", "gross_amount"}.issubset(
                set(columns)
            ):
                continue
            rows: list[dict[str, Any]] = []
            for raw in list(sheet.get("rows") or []):
                if isinstance(raw, dict):
                    row = dict(raw)
                elif isinstance(raw, (list, tuple)):
                    row = dict(zip(columns, raw))
                else:
                    continue
                if _text(row.get("product_name")):
                    rows.append(row)
            period = _text(
                (snapshot.get("metadata") or {}).get("period_label")
            )
            return rows, period
    return [], ""


def _item_sales_report_evidence_observed(
    state: AgentSessionState,
) -> tuple[bool, str]:
    """Return whether an authoritative item-sales row set was observed.

    Empty ``rows=[]`` is a valid exhaustive result for a bounded period.  It
    must not be conflated with an operation that never ran or returned an
    invalid payload.
    """

    for step in state.completed_steps:
        operation_ids = {
            _text(value)
            for value in list(step.tool_names or [])
            if _text(value)
        }
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        if operation_ids.intersection(
            {"orders.item_sales_summary", "orders.item_sales_report"}
        ) and isinstance(tool_result.get("rows"), list):
            return True, _text(
                tool_result.get("period_label")
                or tool_result.get("period")
            )
        snapshot = (
            dict(tool_result.get("report_snapshot") or {})
            if isinstance(tool_result.get("report_snapshot"), dict)
            else {}
        )
        if _text(snapshot.get("report_type")) == "orders.item_sales":
            return True, _text(
                (snapshot.get("metadata") or {}).get("period_label")
            )
    return False, ""


def _item_sales_rows_for_response(
    state: AgentSessionState,
) -> tuple[list[dict[str, Any]], str, bool]:
    """Return the rows the visible answer must project.

    ``orders.item_sales_report`` is an explicit list/report contract and every
    row in its bounded snapshot is part of the requested output.  The summary
    operation is analysis evidence: forcing all 20 default rows into a general
    business analysis makes the verifier replace a useful concise answer with
    a raw dump.  Preserve rank order but require/project only the leading five
    evidence rows for that analytical shape.
    """

    rows, period = _item_sales_report_rows(state)
    grouped = grouped_projection(_turn_semantic_contract(state))
    if grouped:
        return rows[:grouped["limit"]], period, True
    exhaustive = any(
        "orders.item_sales_report"
        in {
            _text(value)
            for value in list(step.tool_names or [])
            if _text(value)
        }
        for step in state.completed_steps
    )
    return (
        rows if exhaustive else rows[:5],
        period,
        exhaustive,
    )


def _authoritative_empty_focused_item_sales_result(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
) -> bool:
    """Validate a domain-declared zero-match product-sales aggregate."""

    if (
        rows
        or result.get("empty_result") is not True
        or result.get("metrics_complete") is not True
        or result.get("currency_applicable") is not False
        or _text(result.get("currency"))
        or dict(result.get("gross_amount_by_currency") or {})
    ):
        return False
    required_keys = {
        "order_count",
        "matched_order_count",
        "total_quantity",
        "total_gross_amount",
    }
    if not required_keys.issubset(result):
        return False
    try:
        return bool(
            int(result.get("order_count")) == 0
            and int(result.get("matched_order_count")) == 0
            and int(result.get("total_quantity")) == 0
            and Decimal(str(result.get("total_gross_amount"))).quantize(
                Decimal("0.01")
            )
            == Decimal("0.00")
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def _focused_item_sales_observation_evidence(
    state: AgentSessionState,
) -> dict[str, Any]:
    """Recover a prior exact-product summary from its immutable observation."""

    for observation in reversed(state.observations):
        if (
            not observation.success
            or _text(observation.operation_name)
            != "orders.item_sales_summary"
        ):
            continue
        payload = dict(
            (observation.aggregates or {}).get(
                "contextual_item_sales_summary"
            )
            or {}
        )
        expected_hash = _text(payload.pop("evidence_sha256", ""))
        actual_hash = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        rows = [
            dict(row)
            for row in list(payload.get("rows") or [])
            if isinstance(row, dict) and _text(row.get("product_name"))
        ]
        result = {
            key: payload.get(key)
            for key in (
                "order_count",
                "matched_order_count",
                "population_order_count",
                "total_quantity",
                "gross_amount_by_currency",
                "total_gross_amount",
                "currency",
                "empty_result",
                "metrics_complete",
                "currency_applicable",
                "identity_filter_count",
                "source_revision",
                "source_snapshot_hash",
            )
            if payload.get(key) is not None
        }
        authoritative_empty = _authoritative_empty_focused_item_sales_result(
            result,
            rows,
        )
        if not (
            payload.get("verified") is True
            and expected_hash
            and expected_hash == actual_hash
            and int(payload.get("identity_filter_count") or 0) == 1
            and _text(payload.get("identity_dependency_step_id"))
            and _text(payload.get("product_name"))
            and (rows or authoritative_empty)
        ):
            continue
        return {
            "product_name": _text(payload.get("product_name")),
            "rows": rows,
            "result": result,
            "period": _text(payload.get("period"))
            or _text(payload.get("period_label")),
            "identity_filter_count": 1,
            "identity_dependency_step_id": _text(
                payload.get("identity_dependency_step_id")
            ),
            "empty_result": authoritative_empty,
            "observation_id": _text(observation.observation_id),
            "evidence_sha256": expected_hash,
        }
    return {}


def _focused_item_sales_evidence(
    state: AgentSessionState,
    *,
    metrics: set[str],
    allow_derived: bool = False,
) -> dict[str, Any]:
    """Return one selected-product aggregate with exact dependency proof."""

    contract = _turn_semantic_contract(state)
    contract_metric = _text(contract.get("metric")).casefold()
    contextual_summary_contract = bool(
        contract_metric == "summary"
        and contract.get("contextual_item_identity_required") is True
        and ORDER_ITEM_SALES_SUMMARY_METRIC
        in normalize_order_metric_requirements(
            contract.get("metric_requirements") or []
        )
    )
    if (
        contract_metric not in metrics
        and not contextual_summary_contract
        and not (allow_derived and contract_metric == "derived")
    ):
        return {}
    summary_step = next(
        (
            step
            for step in reversed(state.completed_steps)
            if "orders.item_sales_summary"
            in {_text(value) for value in list(step.tool_names or [])}
        ),
        None,
    )
    if summary_step is None:
        return _focused_item_sales_observation_evidence(state)
    summary_data = dict(summary_step.result_data or {})
    dependency_bindings = dict(
        summary_data.get("dependency_bindings") or {}
    )
    identity_binding = _text(
        dependency_bindings.get("product_identities")
    )
    binding_suffix = ":tool_result.product_identities"
    if not identity_binding.endswith(binding_suffix):
        return {}
    identity_step_id = identity_binding[: -len(binding_suffix)]
    identity_step = next(
        (
            step
            for step in state.completed_steps
            if _text(step.step_id) == identity_step_id
            and "orders.product_public_identities"
            in {_text(value) for value in list(step.tool_names or [])}
        ),
        None,
    )
    if identity_step is None:
        return {}
    identity_result = dict(
        (identity_step.result_data or {}).get("tool_result") or {}
    )
    product_identities = [
        dict(value)
        for value in list(identity_result.get("product_identities") or [])
        if isinstance(value, dict) and _text(value.get("product_name"))
    ]
    if len(product_identities) != 1:
        return {}
    result = dict(summary_data.get("tool_result") or {})
    if int(result.get("identity_filter_count") or 0) != 1:
        return {}
    rows, period = _item_sales_report_rows(state)
    authoritative_empty = _authoritative_empty_focused_item_sales_result(
        result,
        rows,
    )
    if not rows and not authoritative_empty:
        return {}
    product_name = _text(product_identities[0].get("product_name"))
    if not product_name:
        return {}
    return {
        "product_name": product_name,
        "rows": rows,
        "result": result,
        "period": period,
        "identity_filter_count": int(
            result.get("identity_filter_count") or 0
        ),
        "identity_dependency_step_id": identity_step_id,
        "empty_result": authoritative_empty,
    }


def _focused_item_sales_quantity(
    state: AgentSessionState,
    *,
    allow_derived: bool = False,
) -> dict[str, Any]:
    """Return one selected-product quantity aggregate with typed filter proof."""

    focused = _focused_item_sales_evidence(
        state,
        metrics={"item_quantity_total"},
        allow_derived=allow_derived,
    )
    if not focused:
        return {}
    result = dict(focused.get("result") or {})
    rows = list(focused.get("rows") or [])
    try:
        quantity = int(result.get("total_quantity"))
        row_quantity = sum(int(row.get("quantity") or 0) for row in rows)
    except (TypeError, ValueError):
        return {}
    if quantity < 0 or row_quantity != quantity:
        return {}
    return {
        **{
            key: value
            for key, value in focused.items()
            if key not in {"result", "rows"}
        },
        "quantity": quantity,
        "matched_row_count": len(rows),
    }


def _focused_item_sales_order_count(
    state: AgentSessionState,
    *,
    allow_derived: bool = False,
) -> dict[str, Any]:
    """Return the distinct order count for one exact contextual product."""

    focused = _focused_item_sales_evidence(
        state,
        metrics={"item_order_count"},
        allow_derived=allow_derived,
    )
    if not focused:
        return {}
    result = dict(focused.get("result") or {})
    rows = list(focused.get("rows") or [])
    try:
        order_count = int(result.get("order_count"))
        matched_order_count = int(result.get("matched_order_count"))
        total_quantity = int(result.get("total_quantity"))
        row_order_counts = [
            int(row.get("order_count") or 0)
            for row in rows
        ]
    except (TypeError, ValueError):
        return {}
    empty_result = focused.get("empty_result") is True
    if empty_result:
        if order_count != 0 or matched_order_count != 0 or total_quantity != 0:
            return {}
    elif (
        order_count < 0
        or matched_order_count != order_count
        or total_quantity < order_count
        or not row_order_counts
        or max(row_order_counts) > order_count
        or sum(row_order_counts) < order_count
    ):
        return {}
    population_value = result.get("population_order_count")
    if population_value is not None:
        try:
            if order_count > int(population_value):
                return {}
        except (TypeError, ValueError):
            return {}
    return {
        **{
            key: value
            for key, value in focused.items()
            if key not in {"result", "rows"}
        },
        "order_count": order_count,
        "total_quantity": total_quantity,
        "matched_row_count": len(rows),
    }


def _focused_item_sales_amount(
    state: AgentSessionState,
    *,
    allow_derived: bool = False,
) -> dict[str, Any]:
    """Return gross sales amounts for one exact contextual product."""

    focused = _focused_item_sales_evidence(
        state,
        metrics={"item_gross_amount"},
        allow_derived=allow_derived,
    )
    if not focused:
        return {}
    result = dict(focused.get("result") or {})
    rows = list(focused.get("rows") or [])
    raw_amounts = result.get("gross_amount_by_currency")
    if focused.get("empty_result") is True:
        if not _authoritative_empty_focused_item_sales_result(result, rows):
            return {}
        return {
            **{
                key: value
                for key, value in focused.items()
                if key not in {"result", "rows"}
            },
            "amounts": [{"currency": "", "amount": "0.00"}],
            "matched_row_count": 0,
            "empty_result": True,
        }
    if not isinstance(raw_amounts, dict) or not raw_amounts:
        return {}
    try:
        amounts = {
            _text(currency): Decimal(str(amount)).quantize(Decimal("0.01"))
            for currency, amount in raw_amounts.items()
            if _text(currency)
        }
        row_amounts: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )
        for row in rows:
            currency = _text(row.get("currency")) or "TRY"
            row_amounts[currency] += Decimal(
                str(row.get("gross_amount") or 0)
            )
        row_amounts = {
            currency: amount.quantize(Decimal("0.01"))
            for currency, amount in row_amounts.items()
        }
    except (InvalidOperation, TypeError, ValueError):
        return {}
    if not amounts or amounts != row_amounts:
        return {}
    if len(amounts) == 1:
        currency, amount = next(iter(amounts.items()))
        try:
            if _text(result.get("currency")) != currency:
                return {}
            if Decimal(str(result.get("total_gross_amount"))).quantize(
                Decimal("0.01")
            ) != amount:
                return {}
        except (InvalidOperation, TypeError, ValueError):
            return {}
    return {
        **{
            key: value
            for key, value in focused.items()
            if key not in {"result", "rows"}
        },
        "amounts": [
            {
                "currency": currency,
                "amount": format(amount, ".2f"),
            }
            for currency, amount in sorted(amounts.items())
        ],
        "matched_row_count": len(rows),
    }


def _derived_calculation_contracts(
    state: AgentSessionState,
) -> list[dict[str, Any]]:
    contract = _turn_semantic_contract(state)
    if _text(contract.get("metric")).casefold() != "derived":
        return []
    calculations = contract.get("derived_calculations")
    if isinstance(calculations, list):
        rows = [
            dict(value)
            for value in calculations
            if isinstance(value, dict)
        ]
        if rows:
            return rows
    calculation = contract.get("derived_calculation")
    return [dict(calculation)] if isinstance(calculation, dict) else []


def _derived_calculation_contract(state: AgentSessionState) -> dict[str, Any]:
    calculations = _derived_calculation_contracts(state)
    return dict(calculations[0]) if calculations else {}


def _single_verified_metric_value(
    state: AgentSessionState,
    metric_id: str,
) -> int | float | None:
    values = _order_metric_numeric_values(state, metric_id)
    return values[0] if len(values) == 1 else None


def available_derived_calculation_refs(
    state: AgentSessionState,
) -> list[dict[str, Any]]:
    """Describe canonical operands actually backed by the current typed state."""

    refs: list[dict[str, Any]] = []
    for ref, metric_id, dimension in (
        ("orders.total_count", ORDER_TOTAL_COUNT_METRIC, "count"),
        (
            "orders.ready_to_ship_count",
            ORDER_READY_TO_SHIP_COUNT_METRIC,
            "count",
        ),
        ("orders.nonfinal_count", ORDER_NONFINAL_COUNT_METRIC, "count"),
        ("orders.revenue_total", ORDER_REVENUE_TOTAL_METRIC, "amount"),
    ):
        if _single_verified_metric_value(state, metric_id) is not None:
            refs.append({"ref": ref, "dimension": dimension})
    status_rows = _status_count_rows(state)
    if status_rows:
        refs.append(
            {
                "ref": "orders.status_counts",
                "dimension": "count_collection",
                "members": sorted(
                    {
                        _text(status)
                        for row in status_rows
                        for status in row
                        if _text(status)
                    }
                ),
            }
        )
        refs.append(
            {
                "ref": "orders.status_count",
                "dimension": "count",
                "members": sorted(
                    {
                        _text(status)
                        for row in status_rows
                        for status in row
                        if _text(status)
                    }
                ),
            }
        )
        refs.append(
            {
                "ref": "orders.status_count_sum",
                "dimension": "count",
                "members": sorted(
                    {
                        _text(status)
                        for row in status_rows
                        for status in row
                        if _text(status)
                    }
                ),
            }
        )
    contextual = _focused_item_sales_observation_evidence(state)
    if not contextual:
        contextual = _focused_item_sales_evidence(
            state,
            metrics={
                "item_quantity_total",
                "item_order_count",
                "item_gross_amount",
            },
            allow_derived=True,
        )
    if contextual:
        result = dict(contextual.get("result") or {})
        if result.get("total_quantity") is not None:
            refs.append(
                {
                    "ref": "orders.item_sales_quantity",
                    "dimension": "quantity",
                }
            )
        if result.get("order_count") is not None:
            refs.append(
                {
                    "ref": "orders.item_sales_order_count",
                    "dimension": "count",
                }
            )
        amounts = dict(result.get("gross_amount_by_currency") or {})
        if len(amounts) == 1:
            refs.append(
                {
                    "ref": "orders.item_gross_amount",
                    "dimension": "amount",
                    "currency": next(iter(amounts)),
                }
            )
    recent_calculations = _recent_verified_calculations(state)
    if recent_calculations:
        refs.append({"ref": "derived.latest", "dimension": "derived"})
        for offset, calculation in enumerate(recent_calculations):
            refs.append(
                {
                    "ref": "derived.recent",
                    "offset": offset,
                    "dimension": (
                        _text(calculation.get("result_kind")) or "derived"
                    ),
                    "result": calculation.get("result"),
                    "unit": _text(calculation.get("unit")),
                    "label": _text(calculation.get("result_label")),
                }
            )
    return refs


def _recent_verified_calculations(
    state: AgentSessionState,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    calculations: list[dict[str, Any]] = []
    for observation in reversed(state.observations):
        if (
            not observation.success
            or _text(observation.operation_name)
            != "core.verified_calculation"
        ):
            continue
        payload = dict(
            (observation.aggregates or {}).get("verified_calculation")
            or {}
        )
        if payload.get("verified") is not True or payload.get("result") is None:
            continue
        calculations.append(payload)
        if len(calculations) >= max(1, min(int(limit), 8)):
            break
    return calculations


def _latest_verified_calculation(state: AgentSessionState) -> dict[str, Any]:
    calculations = _recent_verified_calculations(state, limit=1)
    return dict(calculations[0]) if calculations else {}


def _resolve_derived_calculation_operand(
    state: AgentSessionState,
    operand: dict[str, Any],
    *,
    current_calculations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ref = _text(operand.get("ref")).casefold()
    member = _text(operand.get("member"))
    members = [
        _text(value)
        for value in list(operand.get("members") or [])
        if _text(value)
    ]
    value: Any = None
    label = ref
    suffix = ""
    currency = ""
    source = _text(operand.get("source"))
    components: list[dict[str, Any]] = []
    operand_evidence_hash = ""
    source_calculation: dict[str, Any] = {}
    if ref == ORDER_TOTAL_COUNT_METRIC:
        value = _single_verified_metric_value(state, ORDER_TOTAL_COUNT_METRIC)
        label = "toplam siparis"
        suffix = "siparis"
    elif ref == ORDER_READY_TO_SHIP_COUNT_METRIC:
        value = _single_verified_metric_value(
            state,
            ORDER_READY_TO_SHIP_COUNT_METRIC,
        )
        label = "kargoya hazir siparis"
        suffix = "siparis"
    elif ref == ORDER_NONFINAL_COUNT_METRIC:
        value = _single_verified_metric_value(state, ORDER_NONFINAL_COUNT_METRIC)
        label = "terminal olmayan siparis"
        suffix = "siparis"
    elif ref == ORDER_REVENUE_TOTAL_METRIC:
        value = _single_verified_metric_value(state, ORDER_REVENUE_TOTAL_METRIC)
        currencies = _currency_values(state)
        if len(currencies) != 1:
            return {}
        currency = currencies[0]
        label = "toplam ciro"
        suffix = currency
    elif ref == "orders.status_count":
        rows = _status_count_rows(state)
        if len(rows) != 1 or not member:
            return {}
        member_key = _key(member)
        matches = [
            (status, count)
            for status, count in rows[0].items()
            if _key(status) == member_key
        ]
        if len(matches) != 1:
            return {}
        status, value = matches[0]
        label = f"{status} siparis"
        suffix = "siparis"
        source = "orders.status_counts"
    elif ref == "orders.status_count_sum":
        rows = _status_count_rows(state)
        if len(rows) != 1 or len(members) < 2:
            return {}
        seen_member_keys: set[str] = set()
        for requested_member in members:
            requested_key = _key(requested_member)
            if not requested_key or requested_key in seen_member_keys:
                return {}
            seen_member_keys.add(requested_key)
            matches = [
                (status, count)
                for status, count in rows[0].items()
                if _key(status) == requested_key
            ]
            if len(matches) != 1:
                return {}
            status, component_value = matches[0]
            components.append(
                {
                    "ref": "orders.status_count",
                    "member": status,
                    "label": f"{status} siparis",
                    "value": str(component_value),
                    "suffix": "siparis",
                    "currency": "",
                    "source": "orders.status_counts",
                }
            )
        aggregate = evaluate_verified_calculation(
            operator="add",
            operands=[row.get("value") for row in components],
            precision=0,
        )
        if not aggregate.success:
            return {}
        value = (aggregate.data or {}).get("result")
        operand_evidence_hash = _text(
            (aggregate.data or {}).get("evidence_hash")
        )
        label = "secili durumlarin toplam siparisi"
        suffix = "siparis"
        source = "orders.status_counts"
    elif ref == "orders.item_sales_quantity":
        focused = _focused_item_sales_quantity(state, allow_derived=True)
        value = focused.get("quantity") if focused else None
        label = "urun satis adedi"
        suffix = "adet"
    elif ref == "orders.item_sales_order_count":
        focused = _focused_item_sales_order_count(state, allow_derived=True)
        value = focused.get("order_count") if focused else None
        label = "urunun yer aldigi siparis"
        suffix = "siparis"
    elif ref == "orders.item_gross_amount":
        focused = _focused_item_sales_amount(state, allow_derived=True)
        amounts = list(focused.get("amounts") or []) if focused else []
        if len(amounts) != 1:
            return {}
        value = amounts[0].get("amount")
        currency = _text(amounts[0].get("currency"))
        label = "urun brut satis tutari"
        suffix = currency
    elif ref == "derived.current":
        try:
            current_index = int(operand.get("index"))
        except (TypeError, ValueError):
            return {}
        current_rows = list(current_calculations or [])
        if current_index < 0 or current_index >= len(current_rows):
            return {}
        previous = dict(current_rows[current_index])
        if previous.get("verified") is not True or previous.get("result") is None:
            return {}
        source_calculation = previous
        value = previous.get("result")
        label = f"bu turdaki ara sonuc {current_index + 1}"
        suffix = _text(previous.get("unit"))
        currency = _text(previous.get("currency"))
        source = "core.verified_calculation.current_batch"
    elif ref == "derived.latest":
        previous = _latest_verified_calculation(state)
        if not previous:
            return {}
        source_calculation = dict(previous)
        value = previous.get("result")
        label = "onceki dogrulanmis sonuc"
        suffix = _text(previous.get("unit"))
        currency = _text(previous.get("currency"))
        source = "core.verified_calculation"
    elif ref == "derived.recent":
        try:
            offset = int(operand.get("offset"))
        except (TypeError, ValueError):
            return {}
        recent = _recent_verified_calculations(state)
        if offset < 0 or offset >= len(recent):
            return {}
        previous = dict(recent[offset])
        source_calculation = previous
        value = previous.get("result")
        label = f"onceki dogrulanmis sonuc {offset}"
        suffix = _text(previous.get("unit"))
        currency = _text(previous.get("currency"))
        source = "core.verified_calculation"
    elif ref == "literal":
        value = operand.get("value")
        label = "kullanici sabiti"
        currency = _text(operand.get("currency"))
        suffix = currency
    if value is None or isinstance(value, bool):
        return {}
    try:
        parsed = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return {}
    if not parsed.is_finite():
        return {}
    resolved = {
        "ref": ref,
        "member": member,
        "label": label,
        "value": str(value),
        "suffix": suffix,
        "currency": currency,
        "source": source,
    }
    if members:
        resolved["members"] = members
    if ref == "derived.recent":
        resolved["offset"] = int(operand.get("offset"))
    if ref == "derived.current":
        resolved["index"] = int(operand.get("index"))
    if source_calculation:
        resolved["source_calculation"] = source_calculation
    if components:
        resolved["components"] = components
        resolved["component_operator"] = "add"
        resolved["evidence_hash"] = operand_evidence_hash
    return resolved


def _calculation_display_expression(
    calculation: dict[str, Any],
    operands: list[dict[str, Any]],
    *,
    result: str,
    result_suffix: str,
    quantity_scaling: dict[str, Any] | None = None,
) -> str:
    operator = _text(calculation.get("operator")).casefold()
    rendered_operands = []
    scaling = dict(quantity_scaling or {})
    multipliers = list(scaling.get("display_operand_multipliers") or [])
    for operand_index, row in enumerate(operands):
        rendered = " ".join(
            value
            for value in (
                _text(row.get("value")),
                _text(row.get("suffix")),
            )
            if value
        )
        components = [
            dict(value)
            for value in list(row.get("components") or [])
            if isinstance(value, dict)
        ]
        if components and _text(row.get("component_operator")).casefold() == "add":
            component_text = " + ".join(
                " ".join(
                    value
                    for value in (
                        _text(component.get("value")),
                        _text(component.get("suffix")),
                    )
                    if value
                )
                for component in components
            )
            rendered = f"({component_text} = {rendered})"
        multiplier = multipliers[operand_index] if operand_index < len(multipliers) else "1"
        if multiplier != "1":
            rendered = f"({rendered} × {multiplier})"
        rendered_operands.append(rendered)
    if operator in {"percentage", "divide"}:
        left = " / ".join(rendered_operands)
        multiplier = scaling.get("display_result_multiplier", "100" if operator == "percentage" else "1")
        if multiplier != "1":
            left += f" × {multiplier}"
    elif operator == "minimum":
        left = "min(" + ", ".join(rendered_operands) + ")"
    elif operator == "maximum":
        left = "max(" + ", ".join(rendered_operands) + ")"
    else:
        symbol = {
            "add": " + ",
            "subtract": " - ",
            "multiply": " × ",
            "divide": " / ",
        }.get(operator, " ? ")
        left = symbol.join(rendered_operands)
        multiplier = scaling.get("display_result_multiplier", "1")
        if multiplier != "1":
            left = f"({left}) × {multiplier}"
    right = " ".join(value for value in (result, result_suffix) if value)
    return f"{left} = {right}"


def _verified_rounding_assessment(
    *,
    calculation: dict[str, Any],
    operands: list[dict[str, Any]],
    comparison_operand: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    """Verify whether a visible percentage-sum gap is component rounding.

    This is evidence analysis, not intent routing. It only returns a positive
    assessment when every added value is a previously verified percentage,
    all source percentages share the same denominator, their authoritative
    numerators exactly cover that denominator, and the comparison target is
    exactly 100 percent.
    """

    if (
        _text(calculation.get("operator")).casefold() != "add"
        or _text(calculation.get("result_kind")).casefold() != "percentage"
    ):
        return {}
    try:
        comparison_value = Decimal(
            str(comparison_operand.get("value")).replace(",", ".")
        )
        visible_result = Decimal(str(result).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return {}
    if comparison_value != Decimal("100") or visible_result == comparison_value:
        return {}

    numerators: list[Decimal] = []
    denominators: list[Decimal] = []
    for operand in operands:
        source_calculation = dict(operand.get("source_calculation") or {})
        source_contract = dict(source_calculation.get("contract") or {})
        source_operands = list(source_calculation.get("operands") or [])
        if (
            source_calculation.get("verified") is not True
            or _text(source_contract.get("operator")).casefold()
            not in {"divide", "percentage"}
            or _text(source_calculation.get("result_kind")).casefold()
            != "percentage"
            or len(source_operands) != 2
        ):
            return {}
        try:
            numerator = Decimal(
                str(dict(source_operands[0]).get("value")).replace(",", ".")
            )
            denominator = Decimal(
                str(dict(source_operands[1]).get("value")).replace(",", ".")
            )
        except (InvalidOperation, TypeError, ValueError):
            return {}
        numerators.append(numerator)
        denominators.append(denominator)
    if not numerators or len(set(denominators)) != 1:
        return {}
    denominator = denominators[0]
    numerator_sum = sum(numerators, Decimal("0"))
    if denominator == 0 or numerator_sum != denominator:
        return {}
    return {
        "rounding_assessment_verified": True,
        "rounding_assessment": "component_rounding_only",
        "rounding_exact_numerator_sum": format(numerator_sum, "f"),
        "rounding_exact_denominator": format(denominator, "f"),
        "rounding_assessment_label": (
            "Gorunen fark iki ondaliga yuvarlanan yuzde bilesenlerinden "
            "kaynaklaniyor; ham adetler toplamla tutarli"
        ),
    }


def _verified_standalone_numeric_comparison(
    calculation: dict[str, Any], operands: list[dict[str, Any]]
) -> dict[str, Any]:
    """Bind a model-selected numeric relation to Core comparison evidence."""

    if len(operands) != 2 or len({
        _text(row.get("currency")) for row in operands if _text(row.get("currency"))
    }) > 1:
        return {}
    evaluated = evaluate_verified_comparison(
        operator=_text(calculation.get("operator")),
        left=operands[0].get("value"),
        right=operands[1].get("value"),
    )
    if not evaluated.success:
        return {}
    proof = dict(evaluated.data or {})
    parent_hashes = [
        _text(row.get("evidence_hash"))
        or _text(dict(row.get("source_calculation") or {}).get("evidence_hash"))
        for row in operands
    ]
    evidence_hash = hashlib.sha256(json.dumps(
        {"comparison_evidence_hash": proof["evidence_hash"],
         "operand_evidence_hashes": parent_hashes, "contract": calculation},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "operator": proof["operator"], "contract": calculation,
        "operands": operands, "result_kind": "boolean",
        "result": proof["holds"], "result_value": proof["holds"],
        "result_label": "Karşılaştırma", "currency": "", "unit": "",
        "show_work": bool(calculation.get("show_work")),
        "expression": proof["expression"], "display_expression": proof["expression"],
        "comparison_verified": True, "comparison_operator": proof["operator"],
        "comparison_operand": operands[1], "comparison_holds": proof["holds"],
        "comparison_expression": proof["expression"],
        "comparison_label": "Doğru" if proof["holds"] else "Yanlış",
        "comparison_evidence_hash": proof["evidence_hash"],
        "operand_evidence_hashes": parent_hashes,
        "evidence_hash": evidence_hash, "verified": True,
    }


def _verified_derived_calculation_from_contract(
    state: AgentSessionState,
    calculation: dict[str, Any],
    *,
    current_calculations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve one model-authored formula from authoritative typed evidence."""

    operands = []
    for raw_operand in list(calculation.get("operands") or []):
        if not isinstance(raw_operand, dict):
            return {}
        if _text(raw_operand.get("ref")).casefold() == "orders.status_counts":
            status_rows = _status_count_rows(state)
            if len(status_rows) != 1 or not status_rows[0]:
                return {}
            for status, value in sorted(
                status_rows[0].items(),
                key=lambda item: _key(item[0]),
            ):
                operands.append(
                    {
                        "ref": "orders.status_count",
                        "member": status,
                        "label": f"{status} siparis",
                        "value": str(value),
                        "suffix": "siparis",
                        "currency": "",
                        "source": "orders.status_counts",
                    }
                )
            continue
        resolved = _resolve_derived_calculation_operand(
            state,
            dict(raw_operand),
            current_calculations=current_calculations,
        )
        if not resolved:
            return {}
        operands.append(resolved)
    if _text(calculation.get("operator")).casefold() in COMPARISON_OPERATORS:
        return _verified_standalone_numeric_comparison(calculation, operands)
    evaluated = evaluate_verified_calculation(
        operator=_text(calculation.get("operator")),
        operands=[row.get("value") for row in operands],
        precision=int(calculation.get("precision") or 0),
        operand_scales=[
            "0.01" if _text(row.get("suffix")) == "%" else "1"
            for row in operands
        ],
        result_scale="0.01" if calculation.get("result_kind") == "percentage" else "1",
    )
    if not evaluated.success:
        return {}
    result_kind = _text(calculation.get("result_kind")).casefold()
    currencies = {
        _text(row.get("currency"))
        for row in operands
        if _text(row.get("currency"))
    }
    if len(currencies) > 1:
        return {}
    currency = next(iter(currencies), "")
    if result_kind in {
        "amount",
        "amount_per_order",
        "amount_per_quantity",
    } and not currency:
        return {}
    unit = {
        "amount": currency,
        "amount_per_order": f"{currency}/siparis" if currency else "",
        "amount_per_quantity": f"{currency}/adet" if currency else "",
        "percentage": "%",
        "count": "adet",
        "quantity_per_order": "adet/siparis",
        "scalar": "",
    }.get(result_kind, "")
    result = _text(evaluated.data.get("result"))
    label = {
        "amount": "Hesaplanan tutar",
        "amount_per_order": "Siparis basina ortalama ciro",
        "amount_per_quantity": "Adet basina ortalama satis tutari",
        "percentage": "Hesaplanan oran",
        "count": "Hesaplanan adet",
        "quantity_per_order": "Siparis basina ortalama adet",
        "scalar": "Hesaplanan sonuc",
    }.get(result_kind, "Hesaplanan sonuc")
    result_member = ""
    result_members: list[str] = []
    operator = _text(calculation.get("operator")).casefold()
    if result_kind == "percentage":
        status_targets = [
            row
            for row in operands
            if _text(row.get("ref")).casefold() == "orders.status_count"
            and _text(row.get("member"))
        ]
        if len(status_targets) == 1:
            result_member = _text(status_targets[0].get("member"))
            result_members = [result_member]
            label = f"{result_member} durumu icin oran"
    elif operator in {"minimum", "maximum"}:
        try:
            result_decimal = Decimal(str(result).replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            result_decimal = None
        winning_members: list[str] = []
        winning_refs: set[str] = set()
        if result_decimal is not None:
            for row in operands:
                member = _text(row.get("member"))
                if not member:
                    continue
                try:
                    operand_decimal = Decimal(
                        str(row.get("value")).replace(",", ".")
                    )
                except (InvalidOperation, TypeError, ValueError):
                    continue
                if operand_decimal != result_decimal:
                    continue
                if member not in winning_members:
                    winning_members.append(member)
                winning_refs.add(_text(row.get("ref")).casefold())
        if winning_members:
            result_members = winning_members
            if len(winning_members) == 1:
                result_member = winning_members[0]
            if winning_refs == {"orders.status_count"}:
                subject = (
                    "En az gorulen durum"
                    if operator == "minimum"
                    else "En cok gorulen durum"
                )
                if len(winning_members) > 1:
                    subject += "lar"
                label = f"{subject} {', '.join(winning_members)}"
    display_expression = _calculation_display_expression(
        calculation,
        operands,
        result=result,
        result_suffix=unit,
        quantity_scaling=dict(evaluated.data.get("quantity_scaling") or {}),
    )
    verified_payload = {
        **dict(evaluated.data or {}),
        "contract": calculation,
        "operands": operands,
        "result_kind": result_kind,
        "result_label": label,
        "result_member": result_member,
        "result_members": result_members,
        "currency": currency,
        "unit": unit,
        "show_work": bool(calculation.get("show_work")),
        "display_expression": display_expression,
        "verified": True,
    }
    nested_operand_hashes = [
        _text(row.get("evidence_hash"))
        or _text(dict(row.get("source_calculation") or {}).get("evidence_hash"))
        for row in operands
    ]
    # Core verifies the chosen arithmetic. Bind that proof to the resolved
    # quantities and the separate display contract, even without nested sums.
    arithmetic_evidence_hash = _text(verified_payload.get("evidence_hash"))
    verified_payload.update({
        "arithmetic_evidence_hash": arithmetic_evidence_hash,
        "operand_evidence_hashes": nested_operand_hashes,
        "evidence_hash": hashlib.sha256(json.dumps({
            "arithmetic_evidence_hash": arithmetic_evidence_hash,
            "operand_evidence_hashes": nested_operand_hashes,
            "operand_units": [row.get("suffix", "") for row in operands],
            "result_kind": result_kind, "unit": unit, "currency": currency,
            "contract": calculation,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest(),
    })
    comparison_contract = (
        dict(calculation.get("comparison") or {})
        if isinstance(calculation.get("comparison"), dict)
        else {}
    )
    if comparison_contract:
        raw_comparison_operand = comparison_contract.get("operand")
        if not isinstance(raw_comparison_operand, dict):
            return {}
        comparison_operand = _resolve_derived_calculation_operand(
            state,
            dict(raw_comparison_operand),
            current_calculations=current_calculations,
        )
        if not comparison_operand:
            return {}
        comparison = evaluate_verified_comparison(
            operator=_text(comparison_contract.get("operator")),
            left=result,
            right=comparison_operand.get("value"),
        )
        if not comparison.success:
            return {}
        comparison_data = dict(comparison.data or {})
        comparison_operator = _text(
            comparison_data.get("operator")
        ).casefold()
        comparison_holds = comparison_data.get("holds") is True
        if comparison_operator == "equal":
            comparison_label = (
                "Tutarlı" if comparison_holds else "Tutarsız"
            )
        elif comparison_operator == "not_equal":
            comparison_label = (
                "Farklı" if comparison_holds else "Aynı"
            )
        else:
            comparison_label = (
                "Karşılaştırma sağlandı"
                if comparison_holds
                else "Karşılaştırma sağlanmadı"
            )
        verified_payload.update(
            {
                "arithmetic_evidence_hash": _text(
                    verified_payload.get("evidence_hash")
                ),
                "comparison_verified": True,
                "comparison_operator": comparison_operator,
                "comparison_operand": comparison_operand,
                "comparison_holds": comparison_holds,
                "comparison_expression": _text(
                    comparison_data.get("expression")
                ),
                "comparison_evidence_hash": _text(
                    comparison_data.get("evidence_hash")
                ),
                "comparison_label": comparison_label,
            }
        )
        if comparison_contract.get("include_difference") is True:
            verified_payload.update(
                {
                    "comparison_difference_included": True,
                    "comparison_difference": _text(
                        comparison_data.get("difference")
                    ),
                    "comparison_absolute_difference": _text(
                        comparison_data.get("absolute_difference")
                    ),
                }
            )
            rounding_assessment = _verified_rounding_assessment(
                calculation=calculation,
                operands=operands,
                comparison_operand=comparison_operand,
                result=result,
            )
            if rounding_assessment:
                verified_payload.update(rounding_assessment)
        verified_payload["evidence_hash"] = hashlib.sha256(
            json.dumps(
                {
                    "arithmetic_evidence_hash": verified_payload.get(
                        "arithmetic_evidence_hash"
                    ),
                    "comparison_evidence_hash": verified_payload.get(
                        "comparison_evidence_hash"
                    ),
                    "contract": calculation,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    return verified_payload


def verified_derived_calculations(
    state: AgentSessionState,
) -> list[dict[str, Any]]:
    """Resolve every independent formula in the current typed turn."""

    contracts = _derived_calculation_contracts(state)
    if not contracts:
        from AI.processors.observation_analysis_evidence import verified_observation_calculations
        return verified_observation_calculations(state)
    verified: list[dict[str, Any]] = []
    for calculation in contracts:
        row = _verified_derived_calculation_from_contract(
            state,
            calculation,
            current_calculations=verified,
        )
        if not row:
            return []
        verified.append(row)
    return verified


def verified_derived_calculation(state: AgentSessionState) -> dict[str, Any]:
    """Backward-compatible projection of the first verified formula."""

    calculations = verified_derived_calculations(state)
    return dict(calculations[0]) if calculations else {}


def _derived_calculation_projection(state: AgentSessionState) -> str:
    calculations = verified_derived_calculations(state)
    if not calculations:
        from AI.processors.observation_analysis_evidence import verified_observation_tables
        tables = verified_observation_tables(state)
        if tables:
            lines = []
            for table in tables:
                for row in table["rows"]:
                    group = ", ".join(f"{path}: {value}" for path, value in row["group"].items())
                    for name, metric in row["metrics"].items():
                        value = metric.get("exact_value")
                        unit = metric.get("unit")
                        detail = "değer bilinmiyor" if value is None else f"{value} {unit or '(birim belirtilmemiş)'}"
                        lines.append(f"{group + ' — ' if group else ''}{name}: {detail}.")
                if table["data_coverage"].get("status") != "complete":
                    lines.append("Bu hesap yalnız okunan satırları kapsıyor; dosyanın tamamını göstermiyor.")
            return "\n".join(lines)
        return "Turetilmis hesap authoritative kanitlardan dogrulanamadi."
    projections: list[str] = []
    for calculation in calculations:
        result_label = _text(calculation.get('result_label'))
        if calculation.get('result_kind') == 'quantity_per_order':
            result_label = 'Sipariş başına ortalama adet'
        if calculation.get("result_kind") == "boolean":
            for operand in calculation.get("operands") or []:
                source_calculation = dict(operand.get("source_calculation") or {})
                source_expression = _text(source_calculation.get("display_expression"))
                if source_expression:
                    projections.append(f"Dayanak: {source_expression}.")
            projections.append(
                f"Karşılaştırma: {_text(calculation.get('comparison_expression'))} "
                f"→ {_text(calculation.get('comparison_label'))}."
            )
            continue
        result_text = " ".join(
            value
            for value in (
                _text(calculation.get("result")),
                _text(calculation.get("unit")),
            )
            if value
        )
        if calculation.get("show_work") is True:
            projections.append(
                f"{result_label}: "
                f"{_text(calculation.get('display_expression'))}."
            )
        else:
            projections.append(
                f"{result_label}: {result_text}."
            )
        if calculation.get("comparison_verified") is True:
            if calculation.get("comparison_difference_included") is True:
                difference = _text(
                    calculation.get("comparison_absolute_difference")
                )
                difference_unit = (
                    "yuzde puan"
                    if _text(calculation.get("result_kind")).casefold()
                    == "percentage"
                    else _text(calculation.get("unit"))
                )
                comparison_operand = dict(
                    calculation.get("comparison_operand") or {}
                )
                comparison_value = _text(comparison_operand.get("value"))
                result_value = _text(calculation.get("result"))
                result_unit = _text(calculation.get("unit"))
                projections.append(
                    "Fark: |"
                    f"{result_value} {result_unit} - "
                    f"{comparison_value} {result_unit}| = "
                    f"{difference} {difference_unit}."
                )
            if calculation.get("rounding_assessment_verified") is True:
                projections.append(
                    "Degerlendirme: "
                    f"{_text(calculation.get('rounding_assessment_label'))}."
                )
            else:
                projections.append(
                    f"Tutarlılık: {_text(calculation.get('comparison_label')).casefold()} "
                    f"({_text(calculation.get('comparison_expression'))})."
                )
    return "\n".join(projections)


def _answer_projects_item_sales_quantity(
    answer: str,
    quantity: int,
) -> bool:
    searchable = _folded_search_text(answer)
    token = re.escape(str(int(quantity)))
    return bool(
        re.search(
            rf"(?<![0-9]){token}(?![0-9])\s+adet\w*.{{0,32}}"
            rf"(?:satil|satis|sold|sales)",
            searchable,
        )
        or re.search(
            rf"(?:toplam\s+)?(?:satis\s+)?(?:adet|miktar|quantity)\w*"
            rf"[^0-9]{{0,24}}{token}(?![0-9])",
            searchable,
        )
    )


def _answer_projects_item_sales_order_count(
    answer: str,
    order_count: int,
) -> bool:
    searchable = _folded_search_text(answer)
    token = re.escape(str(int(order_count)))
    return bool(
        re.search(
            rf"(?<![0-9]){token}(?![0-9])\s+"
            rf"(?:farkli\s+)?siparis\w*.{{0,32}}"
            rf"(?:satil|satis|dagil|yer\s+al)",
            searchable,
        )
        or re.search(
            rf"(?:farkli\s+)?siparis\w*\s+(?:sayi|aded|count)\w*"
            rf"[^0-9]{{0,24}}{token}(?![0-9])",
            searchable,
        )
    )


def _answer_projects_item_sales_amount(
    answer: str,
    amounts: list[dict[str, Any]],
) -> bool:
    normalized_answer = _normalized(answer)
    if not any(
        label in normalized_answer
        for label in (
            "brut satis",
            "satis tutari",
            "toplam tutar",
            "ciro",
            "gelir",
            "gross sales",
            "revenue",
        )
    ):
        return False
    answer_numbers = {
        equivalent
        for token in _answer_numeric_tokens(answer)
        for equivalent in _numeric_token_equivalents(token)
    }
    for row in amounts:
        currency = _text(row.get("currency"))
        amount = row.get("amount")
        if currency and _normalized(currency) not in normalized_answer:
            return False
        if not answer_numbers.intersection(
            _numeric_token_equivalents(amount)
        ):
            return False
    return True


def _human_period_scope(value: Any) -> str:
    """Project internal period enums/ranges into user-facing Turkish."""

    raw = _text(value)
    normalized = raw.casefold().replace(" ", "_")
    known = {
        "all": "tüm dönemler",
        "today": "bugün",
        "yesterday": "dün",
        "last_7_days": "son 7 gün",
        "last_14_days": "son 14 gün",
        "last_21_days": "son 21 gün",
        "last_30_days": "son 30 gün",
        "this_month": "bu ay",
    }
    if normalized in known:
        return known[normalized]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}", raw):
        start, end = raw.split("..", 1)
        return f"{start} – {end}"
    return raw.replace("_", " ")


def _grouped_sales_problems(answer: str, state: AgentSessionState, rows: list[dict[str, Any]]) -> list[str]:
    grouped = grouped_projection(_turn_semantic_contract(state))
    labels = {
        "quantity": r"(?:satilan\s+)?(?:adet|miktar|quantity|units(?:\s+sold)?)",
        "order_count": r"(?:siparis(?:\s+sayisi)?|order\s+count|orders)",
        "gross_amount": r"(?:brut(?:\s+tutar)?|gross(?:\s+amount)?)",
        "currency": r"(?:para\s+birimi|currency)",
    }
    lines = [line.replace("**", "").replace("`", "") for line in answer.splitlines()]
    columns: dict[str, int] = {}
    for i, line in enumerate(lines[:-1]):
        if "|" in line and re.search(r"\|\s*:?-{3,}", lines[i + 1]):
            cells = line.strip().strip("|").split("|")
            columns = {f: j for j, cell in enumerate(cells) for f, pattern in labels.items()
                       if re.fullmatch(pattern, _normalized(cell).strip())}
            break
    problems = []
    used_lines: set[int] = set()
    observed = _operation_tool_result(state, "orders.item_sales_summary") or _operation_tool_result(state, "orders.item_sales_report")
    product_count = observed.get("product_count")
    if isinstance(product_count, int) and len(rows) < min(grouped["limit"], product_count):
        problems.append("grouped_rows_incomplete")
    for rank, row in enumerate(rows, 1):
        name = _text(row.get("product_name"))
        match_index = next((i for i, line in enumerate(lines) if i not in used_lines and name.casefold() in line.casefold()), None)
        line = lines[match_index] if match_index is not None else ""
        if not line:
            problems.append(f"grouped_row_missing:{rank}")
            continue
        used_lines.add(match_index)
        # Keep decimal separators in row values. _normalized() is intended for
        # words and would turn 447983.29 into "447983 29" before comparison.
        body = unicodedata.normalize(
            "NFKD",
            line.replace(name, "").casefold().translate(str.maketrans({"ı": "i"})),
        )
        body = "".join(char for char in body if not unicodedata.combining(char))
        body = re.sub(r"[^a-z0-9.,:=+−-]+", " ", body).strip()
        cells = line.strip().strip("|").split("|")
        for field in grouped["fields"]:
            if field == "product_name":
                continue
            if field in columns and len(cells) > columns[field]:
                cell = cells[columns[field]]
                tokens = _answer_numeric_tokens(cell)
            else:
                match = re.search(labels[field] + r"\s*[:=]?\s*([-+]?\d[\d.,]*)", body)
                cell = match[1] if match else ""
                tokens = [cell] if cell else []
            if field == "currency":
                ok = _text(row.get(field)).casefold() in line.casefold()
            else:
                expected = _numeric_token_equivalents(str(row.get(field)))
                ok = any(expected.intersection(_numeric_token_equivalents(token)) for token in tokens)
            if not ok:
                problems.append(f"grouped_row_value_missing:{rank}:{field}")
        if "gross_amount" not in grouped["fields"] and (
            "gross_amount" in columns or re.search(labels["gross_amount"] + r"\s*[:=]?\s*\d", body)
        ):
            problems.append(f"grouped_unrequested_amount:{rank}")
    return problems


def _item_sales_report_projection(state: AgentSessionState) -> str:
    rows, period, exhaustive = _item_sales_rows_for_response(state)
    if not rows:
        observed_empty, observed_period = (
            _item_sales_report_evidence_observed(state)
        )
        if observed_empty:
            scope = _human_period_scope(observed_period or period)
            prefix = f"{scope} " if scope else ""
            return (
                f"{prefix}siparis kalemi satisi yok; "
                "en cok satan urun bulunmuyor."
            )
        return "En cok satan urun satirlari authoritative raporda bulunamadi."
    period_text = _human_period_scope(period)
    scope_text = (
        "Tüm dönemlerde"
        if period_text == "tüm dönemler"
        else period_text[:1].upper() + period_text[1:]
    )
    header = (
        f"{scope_text + ' ' if scope_text else ''}"
        f"{'en çok satan ürünler' if exhaustive else 'öne çıkan ürünler'}:"
    )
    lines = [header]
    grouped = grouped_projection(_turn_semantic_contract(state))
    for index, row in enumerate(rows, start=1):
        if grouped:
            parts = [f"{index}. {_text(row.get('product_name'))}"]
            for field, label in (("quantity", "adet"), ("order_count", "sipariş"), ("gross_amount", "brüt")):
                if field in grouped["fields"]:
                    value = row.get(field)
                    if field == "gross_amount":
                        try:
                            amount = Decimal(str(value)).quantize(Decimal("0.01"))
                            value = format(amount, ",.2f").replace(",", "_").replace(".", ",").replace("_", ".")
                        except (InvalidOperation, ValueError, TypeError):
                            value = _text(value)
                    parts.append(f"{label}: {value}")
            if "currency" in grouped["fields"]:
                if "gross_amount" in grouped["fields"]:
                    parts[-1] += f" {_text(row.get('currency'))}"
                else:
                    parts.append(f"para birimi: {_text(row.get('currency'))}")
            lines.append(" — ".join(parts[:2]) + (", " + ", ".join(parts[2:]) if len(parts) > 2 else ""))
            continue
        rank = int(row.get("rank") or index)
        gross_amount = row.get("gross_amount")
        gross = _text(gross_amount)
        currency = _text(row.get("currency")) or "TRY"
        lines.append(
            f"{rank}. {_text(row.get('product_name'))} | "
            f"adet: {int(row.get('quantity') or 0)} | "
            f"siparis: {int(row.get('order_count') or 0)} | "
            f"brut: {gross} {currency}"
        )
    return "\n".join(lines)


def _operation_tool_result(
    state: AgentSessionState,
    operation_id: str,
) -> dict[str, Any]:
    for step in reversed(state.completed_steps):
        if operation_id not in {_text(value) for value in list(step.tool_names or [])}:
            continue
        result_data = dict(step.result_data or {})
        tool_result = result_data.get("tool_result")
        if isinstance(tool_result, dict):
            return dict(tool_result)
    return {}


def _has_complete_nonfinal_lifecycle_evidence(
    state: AgentSessionState,
) -> bool:
    tool_result = _operation_tool_result(state, "orders.nonfinal_summary")
    status_counts = (
        dict(tool_result.get("status_counts") or {})
        if isinstance(tool_result.get("status_counts"), dict)
        else {}
    )
    try:
        total_count = int(tool_result.get("total_count") or 0)
        counted_total = sum(int(value or 0) for value in status_counts.values())
    except (TypeError, ValueError):
        return False
    return bool(
        tool_result.get("status_counts_complete") is True
        and total_count >= 0
        and counted_total == total_count
    )


def _authoritative_operation_count(
    state: AgentSessionState,
    operation_ids: tuple[str, ...],
    *,
    scalar_keys: tuple[str, ...],
    row_keys: tuple[str, ...],
) -> tuple[bool, int]:
    for operation_id in operation_ids:
        tool_result = _operation_tool_result(state, operation_id)
        if not tool_result:
            continue
        for key in scalar_keys:
            value = tool_result.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return True, max(0, int(value))
        for key in row_keys:
            rows = tool_result.get(key)
            if isinstance(rows, list):
                return True, len(rows)
    return False, 0


def _authoritative_return_clearance(
    state: AgentSessionState,
) -> tuple[bool, int]:
    observed, count = _authoritative_operation_count(
        state,
        ("returns.query", "returns.lookup"),
        scalar_keys=("actionable_count", "count", "total_count"),
        row_keys=("returns", "claims"),
    )
    if observed:
        return observed, count
    contexts = _operation_tool_result(state, "orders.full_context").get(
        "contexts"
    )
    if not isinstance(contexts, list) or not contexts:
        return False, 0
    if not all(
        isinstance(context, dict)
        and isinstance(context.get("returns"), list)
        for context in contexts
    ):
        return False, 0
    return True, sum(
        len(context.get("returns") or [])
        for context in contexts
        if isinstance(context, dict)
    )


def unsupported_operational_clearance_reason_codes(
    answer: str,
    state: AgentSessionState,
) -> list[str]:
    """Reject broad negative operational claims without typed evidence.

    This is a response-safety boundary, not an intent classifier: the model is
    free to phrase the answer naturally, while negative claims about returns,
    risk or the entire fulfillment lifecycle require the corresponding
    exhaustive domain observation.
    """

    no_issue_terms = (
        "bulunmuyor",
        "bulunmamaktadir",
        "yok",
        "gorunmuyor",
    )
    ready_observed, ready_count = _authoritative_operation_count(
        state,
        ("orders.ready_to_ship", "orders.ready_to_ship_count"),
        scalar_keys=("count", "total_count", "listed_count"),
        row_keys=("orders", "order_numbers"),
    )
    risk_observed, risk_count = _authoritative_operation_count(
        state,
        ("orders.fulfillment_risk", "orders.fulfillment_risk_count"),
        scalar_keys=("risk_count", "count", "total_count"),
        row_keys=("risks", "orders"),
    )
    returns_observed, return_count = _authoritative_return_clearance(state)
    reasons: list[str] = []
    claim_units = [
        _normalized(unit)
        for unit in re.split(
            r"(?:\r?\n)+|(?<=[.!?;])\s+",
            str(answer or ""),
        )
        if _normalized(unit)
    ]
    for normalized in claim_units:
        if not any(term in normalized for term in no_issue_terms):
            continue
        if re.search(
            r"(?:kritik\s+)?bekleyen(?:\s+bir)?\s+is\w*"
            r"(?:\s+\w+){0,4}\s+(?:yok|gorunmuyor|bulunmuyor|bulunmamaktadir)\b",
            normalized,
        ):
            if ready_observed and risk_observed and returns_observed:
                if ready_count or risk_count or return_count:
                    reasons.append("contradictory_global_pending_clearance")
            else:
                reasons.append("unsupported_global_pending_clearance")
        if re.search(
            r"(?:\biade(?:\s+(?:kaydi|talebi|siparisi|bekleyen|edilen)){0,2}|"
            r"\bbekleyen\s+iade)\s+"
            r"(?:yok|gorunmuyor|bulunmuyor|bulunmamaktadir)\b",
            normalized,
        ):
            if not returns_observed:
                reasons.append("unsupported_return_clearance")
            elif return_count:
                reasons.append("contradictory_return_clearance")
        if re.search(
            r"(?:\brisk(?:li)?(?:\s+(?:kaydi|siparis|durum)){0,2}|"
            r"\beksik\s+kargo(?:\s+kaydi)?)\s+"
            r"(?:yok|gorunmuyor|bulunmuyor|bulunmamaktadir)\b",
            normalized,
        ):
            if not risk_observed:
                reasons.append("unsupported_fulfillment_risk_clearance")
            elif risk_count:
                reasons.append("contradictory_fulfillment_risk_clearance")
        if (
            "fulfillment" in normalized
            and not risk_observed
            and not _has_complete_nonfinal_lifecycle_evidence(state)
        ):
            reasons.append("unsupported_fulfillment_lifecycle_clearance")
    return list(dict.fromkeys(reasons))


def _aggregate_analysis_indicators(state: AgentSessionState) -> dict[str, Any]:
    """Expose only domain-calculated indicators for broad Orders analysis."""

    if not _aggregate_analysis_requested(state):
        return {}
    active = dict(state.active_entities or {})
    if active.get("_response_projection_direct_only") is True:
        # A derived turn projects independently requested base metrics through
        # a cloned state before appending the verified Core calculation.  No
        # implicit analytical dimension may leak into that direct-only pass.
        return {}
    requested = requested_response_fields(state)
    summary = _operation_tool_result(state, "orders.summary")
    items = _operation_tool_result(state, "orders.item_sales_summary")
    if not items:
        report = _operation_tool_result(state, "orders.item_sales_report")
        snapshot = (
            dict(report.get("report_snapshot") or {})
            if isinstance(report.get("report_snapshot"), dict)
            else {}
        )
        metadata = (
            dict(snapshot.get("metadata") or {})
            if isinstance(snapshot.get("metadata"), dict)
            else {}
        )
        items = {
            key: report.get(key, metadata.get(key))
            for key in (
                "order_count",
                "total_quantity",
                "leading_five_quantity",
                "leading_five_quantity_share",
            )
            if report.get(key, metadata.get(key)) is not None
        }
    indicators: dict[str, Any] = {}
    if "status" in requested:
        indicators.update(
            {
                key: summary.get(key)
                for key in (
                    "dominant_status",
                    "dominant_status_count",
                    "dominant_status_rate",
                    "cancellation_rate",
                )
                if summary.get(key) is not None
            }
        )
    if ("amount" in requested and "calculation" not in requested
            and not _general_broad_summary_requested(state)):
        indicators.update(
            {
                key: summary.get(key)
                for key in (
                    "revenue_order_count",
                    "average_revenue_per_order",
                )
                if summary.get(key) is not None
            }
        )
    if requested.intersection(
        {
            "item_sales_rows",
            "item_sales_quantity",
            "item_sales_order_count",
            "item_sales_amount",
        }
    ):
        for key in (
            "total_quantity",
            "leading_five_quantity",
            "leading_five_quantity_share",
        ):
            if items.get(key) is not None:
                indicators[key] = items.get(key)
        if _general_broad_summary_requested(state):
            indicators["item_sales_period"] = items.get("period_label") or items.get("period")
            indicators["quantity_unit"] = items.get("quantity_unit")
    if "risk" in requested:
        risk_values = _risk_counts(state)
        if risk_values:
            indicators["fulfillment_risk_count"] = risk_values[0]
    return indicators


def _aggregate_status_indicators_available(state: AgentSessionState) -> bool:
    total_orders = _order_metric_numeric_values(
        state,
        ORDER_TOTAL_COUNT_METRIC,
    )
    if len(total_orders) == 1 and float(total_orders[0]) == 0.0:
        return False
    indicators = _aggregate_analysis_indicators(state)
    return bool(
        (
            _text(indicators.get("dominant_status"))
            and indicators.get("dominant_status_count") is not None
            and indicators.get("dominant_status_rate") is not None
        )
        or indicators.get("cancellation_rate") is not None
    )


def _aggregate_item_indicators_available(state: AgentSessionState) -> bool:
    indicators = _aggregate_analysis_indicators(state)
    if (
        indicators.get("total_quantity") is not None
        and int(indicators.get("total_quantity") or 0) == 0
    ):
        return False
    return indicators.get("leading_five_quantity_share") is not None


def _aggregate_analysis_projection(state: AgentSessionState) -> str:
    total_orders = _order_metric_numeric_values(
        state,
        ORDER_TOTAL_COUNT_METRIC,
    )
    if len(total_orders) == 1 and float(total_orders[0]) == 0.0:
        # Zero-row scopes are described by the explicit count, status and
        # item-sales empty projections. Ratios/averages derived from an empty
        # denominator are not useful business insights.
        return ""
    indicators = _aggregate_analysis_indicators(state)
    if not indicators:
        return ""
    lines = ["Analitik yorum:"]
    dominant_status = _text(indicators.get("dominant_status"))
    if dominant_status and indicators.get("dominant_status_count") is not None:
        lines.append(
            "- En buyuk durum grubu {}: {} siparis (%{}).".format(
                dominant_status,
                indicators.get("dominant_status_count"),
                indicators.get("dominant_status_rate"),
            )
        )
    if indicators.get("cancellation_rate") is not None:
        lines.append(
            f"- Iptal orani %{indicators.get('cancellation_rate')}."
        )
    if indicators.get("average_revenue_per_order") is not None:
        lines.append(
            "- Iptal disi siparis basina ortalama tutar: "
            f"{indicators.get('average_revenue_per_order')} TRY."
        )
    if indicators.get("leading_five_quantity_share") is not None:
        general_summary = _general_broad_summary_requested(state)
        period = _human_period_scope(indicators.get("item_sales_period")) if general_summary else ""
        quantity_label = ("pazaryeri siparis urun biriminin"
                          if indicators.get("quantity_unit") == "marketplace_item" else "adedin")
        lines.append(
            "- {}Ilk 5 urun, satilan toplam {} {} {} adedini (%{}) olusturuyor.".format(
                f"{period}: " if period else "",
                indicators.get("total_quantity"),
                quantity_label,
                indicators.get("leading_five_quantity"),
                indicators.get("leading_five_quantity_share"),
            )
        )
    if indicators.get("fulfillment_risk_count") is not None:
        risk_count = int(indicators.get("fulfillment_risk_count") or 0)
        lines.append(
            "- Fulfillment riski: 0 kayit; kritik risk gorunmuyor."
            if risk_count == 0
            else f"- Incelenmesi gereken {risk_count} fulfillment riski var."
        )
    return "\n".join(lines) if len(lines) > 1 else ""


def _aggregate_status_insight_projected(
    answer: str,
    state: AgentSessionState,
) -> bool:
    indicators = _aggregate_analysis_indicators(state)
    dominant_status = _text(indicators.get("dominant_status"))
    if dominant_status and _answer_mentions_status(answer, dominant_status):
        expected = {
            equivalent
            for key in ("dominant_status_count", "dominant_status_rate")
            for equivalent in _numeric_token_equivalents(indicators.get(key))
        }
        answer_values = {
            equivalent
            for token in _answer_numeric_tokens(answer)
            for equivalent in _numeric_token_equivalents(token)
        }
        if expected.intersection(answer_values):
            return True
    cancellation_rate = indicators.get("cancellation_rate")
    if cancellation_rate is None:
        return False
    return any(
        _numeric_token_equivalents(claim).intersection(
            _numeric_token_equivalents(cancellation_rate)
        )
        for claim in _labelled_numeric_claims(
            answer,
            r"iptal\s+orani|cancellation\s+rate",
        )
    )


def _aggregate_item_insight_projected(
    answer: str,
    state: AgentSessionState,
) -> bool:
    share = _aggregate_analysis_indicators(state).get(
        "leading_five_quantity_share"
    )
    if share is None:
        return False
    normalized_answer = _normalized(answer)
    if not any(
        marker in normalized_answer
        for marker in ("ilk 5 urun", "ilk bes urun", "urun yogunlugu", "top 5")
    ):
        return False
    answer_values = {
        equivalent
        for token in _answer_numeric_tokens(answer)
        for equivalent in _numeric_token_equivalents(token)
    }
    return bool(
        answer_values.intersection(_numeric_token_equivalents(share))
    )


def verify_response_projection(
    answer: str,
    state: AgentSessionState,
    *,
    source: str = "model",
) -> Result:
    requested = requested_response_fields(state)
    if _pending_report_followup_requested(state, requested):
        from AI.processors.observation_context import verified_pending_report_answer
        expected = verified_pending_report_answer(state)
        problems = (['pending_report_preparation_receipt_missing'] if not expected else
                    [] if _text(answer) == expected else ['pending_report_projection_mismatch'])
        verification = _record_response_verification(state, allowed=not problems, source=source,
                                                     requested_fields=requested, reason_codes=problems)
        if problems:
            return Result.fail('Mevcut raporun kesin hazırlık kaydı bu açıklamayı desteklemiyor.',
                close_dialog=False, data={'response_verification': verification, 'retryable': False})
        return Result.ok('Mevcut raporun bağlı kaynakları ve kesin onay kapsamı doğrulandı.',
                         close_dialog=False, data={'response_verification': verification})
    if _pending_action_followup_requested(state, requested):
        from AI.processors.observation_context import verified_pending_action_answer
        expected = verified_pending_action_answer(state)
        problems = (["pending_action_preparation_receipt_missing"] if not expected
                    else [] if _text(answer) == expected else ["pending_action_projection_mismatch"])
        verification = _record_response_verification(state, allowed=not problems, source=source,
                                                    requested_fields=requested, reason_codes=problems)
        if problems:
            return Result.fail("Mevcut teklifin hazırlık kaydı bu açıklamayı desteklemiyor.", close_dialog=False,
                               data={"response_verification": verification, "retryable": False})
        return Result.ok("Mevcut immutable teklif ve gerçek hazırlık kaydı açıklamayı destekliyor.", close_dialog=False,
                         data={"response_verification": verification})
    if _verified_export_followup_requested(state, requested):
        from AI.processors.observation_context import verified_export_report_answer
        expected = verified_export_report_answer(state)
        problems = (["verified_export_receipt_missing"] if not expected
                    else [] if _text(answer) == expected else ["verified_export_projection_mismatch"])
        verification = _record_response_verification(state, allowed=not problems, source=source,
                                                    requested_fields=requested, reason_codes=problems)
        if problems:
            return Result.fail("Önceki raporun doğrulama kaydı bu açıklamayı desteklemiyor.", close_dialog=False,
                               data={"response_verification": verification, "retryable": False})
        return Result.ok("Kaynaklı rapor ve kayıtlı exact dosya doğrulaması açıklamayı destekliyor.", close_dialog=False,
                         data={"response_verification": verification})
    derived_calculations = (
        verified_derived_calculations(state)
        if "calculation" in requested
        else []
    )
    derived_calculation = (
        dict(derived_calculations[0]) if derived_calculations else {}
    )
    direct_projection = _direct_projection_fields(state)
    evidence = _collect_evidence(state)
    sensitive = dict(evidence["sensitive"])
    normalized_answer = _normalized(answer)
    problems: list[str] = []
    requested_business_domains = {
        _text(value).casefold()
        for value in list((state.active_entities or {}).get("business_read_domains") or [])
    }
    if len(requested_business_domains) > 1:
        observed_business_domains = {
            _text(step.operation_domain).casefold()
            for step in state.completed_steps
            if step.status == "completed" and step.tool_names
        }
        problems.extend(
            f"cross_business_read_domain_unobserved:{domain}"
            for domain in sorted(requested_business_domains - observed_business_domains)
        )
    cross_business = _cross_business_read_evidence(state)
    stock_read = dict(cross_business.get("stock") or {})
    if not stock_read and "amount" in requested and (
        _text(state.active_domain).casefold() == "stock"
        or {operation for step in state.completed_steps if step.status == "completed"
            and step.verification_status in {"observed", "verified"} for operation in step.tool_names}
        == {"stock.inventory_overview"}
    ):
        stock_read = next((dict(step.result_data or {}).get("tool_result") or {}
            for step in reversed(state.completed_steps)
            if step.status == "completed" and step.verification_status in {"observed", "verified"}
            and step.tool_names == ["stock.inventory_overview"]
            and (dict(step.result_data or {}).get("tool_result") or {}).get("tool") == "stock.inventory_overview"), {})
    finance_read = dict(cross_business.get("finance") or {})
    monetary_rows = [
        row for row in [
            *list(stock_read.get("stock_value_by_currency") or []),
            *list(finance_read.get("currency_totals") or []),
        ] if isinstance(row, dict)
    ]
    monetary_claims = _monetary_claims(
        answer, [row.get("currency") for row in monetary_rows],
    )
    if stock_read:
        answer_numbers = {
            equivalent
            for token in _answer_numeric_tokens(answer)
            for equivalent in _numeric_token_equivalents(token)
        }
        for row in list(stock_read.get("stock_value_by_currency") or []):
            if not isinstance(row, dict):
                continue
            amount = row.get("amount")
            currency = _text(row.get("currency"))
            if amount is not None and not answer_numbers.intersection(
                _numeric_token_equivalents(amount)
            ):
                problems.append("cross_stock_value_omitted")
            if currency and currency.casefold() not in answer.casefold():
                problems.append("cross_stock_currency_omitted")
            if amount is not None and currency and not any(
                claimed_currency == currency.upper()
                and _numeric_token_equivalents(claimed_amount).intersection(
                    _numeric_token_equivalents(amount)
                )
                for claimed_amount, claimed_currency in monetary_claims
            ):
                problems.append("cross_stock_value_currency_pair_missing")
    if finance_read and not any(
        marker in normalized_answer for marker in ("nakit", "finans", "mali hareket", "odeme")
    ):
        problems.append("cross_finance_observation_omitted")
    finance_amounts = [
        (row.get("combined_net"), _text(row.get("currency")).upper())
        for row in list(finance_read.get("currency_totals") or [])
        if isinstance(row, dict) and row.get("combined_net") is not None
    ]
    for claimed_amount, claimed_currency in monetary_claims:
        matching_finance = {
            currency for amount, currency in finance_amounts
            if _numeric_token_equivalents(claimed_amount).intersection(
                _numeric_token_equivalents(amount)
            )
        }
        if matching_finance and claimed_currency not in matching_finance:
            matching_stock = any(
                _text(row.get("currency")).upper() == claimed_currency
                and _numeric_token_equivalents(claimed_amount).intersection(
                    _numeric_token_equivalents(row.get("amount"))
                )
                for row in list(stock_read.get("stock_value_by_currency") or [])
                if isinstance(row, dict)
            )
            if not matching_stock:
                problems.append("cross_finance_amount_currency_mismatch")
    if "currency" in requested and not cross_business:
        finance_currency_rows = [
            row for row in list(
                _operation_tool_result(state, "finance.cashflow_summary").get("currency_totals") or []
            ) if isinstance(row, dict) and row.get("combined_net") is not None
        ]
        for claimed_amount, claimed_currency in _monetary_claims(
            answer, [row.get("currency") for row in finance_currency_rows],
        ):
            matching_currencies = {
                _text(row.get("currency")).upper()
                for row in finance_currency_rows
                if _numeric_token_equivalents(claimed_amount).intersection(
                    _numeric_token_equivalents(row.get("combined_net"))
                )
            }
            if matching_currencies and claimed_currency not in matching_currencies:
                problems.append("finance_amount_currency_mismatch")
    account_population = _registered_account_population(state)
    if account_population.get("complete") is True and re.search(
        r"(?:baska|diger)\b.{0,160}\b(?:dogrulanamaz|bilinemez|belirsiz|tespit edilemez)",
        normalized_answer,
    ):
        problems.append("complete_account_population_misrepresented_as_unknown")
    if not _text(answer):
        problems.append("empty_response")
    problems.extend(
        unsupported_operational_clearance_reason_codes(answer, state)
    )
    internal_contract_markers = (
        "period_label",
        "api_account_ids",
        "query_fingerprint",
        "source_revision",
        "source_snapshot_hash",
        "listed_count",
        "selected_count",
        "simulated_excluded",
        "operation_id",
        "response_verification",
    )
    for marker in internal_contract_markers:
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(marker)}(?![A-Za-z0-9_])",
            answer,
            flags=re.IGNORECASE,
        ):
            problems.append(
                f"internal_contract_field_exposed:{marker}"
            )
    if re.search(
        r"(?<![A-Za-z0-9_])all\s+(?:donem(?:i|inde|ler|lerden)?|period)(?![A-Za-z0-9_])",
        normalized_answer,
    ):
        problems.append("internal_period_enum_exposed:all")

    allowed_numbers = {
        equivalent
        for token in set(evidence["numbers"])
        for equivalent in _numeric_token_equivalents(token)
    }
    allowed_numbers.update(
        equivalent
        for value in set(evidence["strings"])
        for equivalent in _date_numeric_equivalents(value)
    )
    focused_ratio_evidence = (
        _focused_order_status_ratio(state)
        if "ratio" in requested
        else {}
    )
    for value in (
        focused_ratio_evidence.get("numerator"),
        focused_ratio_evidence.get("denominator"),
        focused_ratio_evidence.get("percentage"),
    ):
        if value is None:
            continue
        allowed_numbers.update(_numeric_token_equivalents(value))
    if "calculation" in requested:
        if not derived_calculations:
            from AI.processors.observation_analysis_evidence import verified_observation_tables
            if not verified_observation_tables(state):
                problems.append("derived_calculation_evidence_missing")
        else:
            for calculation in derived_calculations:
                calculation_values = [
                    row.get("value")
                    for row in list(calculation.get("operands") or [])
                    if isinstance(row, dict) and row.get("value") is not None
                ]
                calculation_values.extend(
                    component.get("value")
                    for row in list(calculation.get("operands") or [])
                    if isinstance(row, dict)
                    for component in list(row.get("components") or [])
                    if isinstance(component, dict)
                    and component.get("value") is not None
                )
                calculation_values.append(calculation.get("result"))
                scaling = dict(calculation.get("quantity_scaling") or {})
                calculation_values.extend(scaling.get("display_operand_multipliers") or [])
                calculation_values.append(scaling.get("display_result_multiplier"))
                # A previous result can be displayed with its original work.
                # Ground those numbers in the referenced proof, without
                # admitting unrelated calculations from conversation history.
                for operand in calculation.get("operands") or []:
                    source = dict(operand.get("source_calculation") or {})
                    if source.get("verified") is not True or not source.get("evidence_hash"):
                        continue
                    calculation_values.append(source.get("result"))
                    for source_operand in source.get("operands") or []:
                        if not isinstance(source_operand, dict):
                            # Core proofs also support their original flat
                            # numeric operand representation.
                            calculation_values.append(source_operand)
                            continue
                        calculation_values.append(source_operand.get("value"))
                        calculation_values.extend(
                            component.get("value")
                            for component in source_operand.get("components") or []
                            if isinstance(component, dict)
                        )
                    if source.get("operator") == "percentage":
                        calculation_values.append(100)
                    source_scaling = dict(source.get("quantity_scaling") or {})
                    calculation_values.extend(source_scaling.get("display_operand_multipliers") or [])
                    calculation_values.append(source_scaling.get("display_result_multiplier"))
                comparison_operand = calculation.get("comparison_operand")
                if isinstance(comparison_operand, dict):
                    calculation_values.append(
                        comparison_operand.get("value")
                    )
                calculation_values.extend(
                    (
                        calculation.get("comparison_difference"),
                        calculation.get("comparison_absolute_difference"),
                    )
                )
                for value in calculation_values:
                    if value is not None:
                        allowed_numbers.update(
                            _numeric_token_equivalents(value)
                        )
                calculation_operator = _text(
                    dict(calculation.get("contract") or {}).get("operator")
                ).casefold()
                if calculation_operator == "percentage":
                    # ``× 100`` is part of the verified percentage operator,
                    # not a model-authored business fact.
                    allowed_numbers.update(_numeric_token_equivalents(100))
    for token in _answer_numeric_tokens(presentation_numeric_text(answer)):
        if (
            _numeric_token_equivalents(token).intersection(allowed_numbers)
        ):
            continue
        problems.append(f"ungrounded_number:{token}")

    for calculation_index, derived_calculation in enumerate(
        derived_calculations,
        start=1,
    ):
        problem_suffix = (
            f":{calculation_index}"
            if len(derived_calculations) > 1
            else ""
        )
        answer_number_equivalents = {
            equivalent
            for token in _answer_numeric_tokens(answer)
            for equivalent in _numeric_token_equivalents(token)
        }
        result_value = derived_calculation.get("result")
        boolean_result = derived_calculation.get("result_kind") == "boolean"
        if boolean_result:
            expected_truth = "dogru" if result_value is True else "yanlis"
            opposite_truth = "yanlis" if result_value is True else "dogru"
            relation_segments = _comparison_projection_segments(answer, derived_calculation)
            truth_matches = [
                relation_matches and bool(re.search(rf"(?<!\w){expected_truth}(?!\w)", segment))
                and not re.search(rf"(?<!\w){opposite_truth}(?!\w)", segment)
                and not re.search(rf"(?<!\w){expected_truth}\s+degil(?!\w)", segment)
                for segment, relation_matches in relation_segments
            ]
            if not truth_matches or not all(truth_matches):
                problems.append("comparison_boolean_projection_mismatch" + problem_suffix)
            for operand in derived_calculation.get("operands") or []:
                if not answer_number_equivalents.intersection(
                    _numeric_token_equivalents(operand.get("value"))
                ):
                    problems.append("comparison_operand_projection_missing" + problem_suffix)
        elif not answer_number_equivalents.intersection(
            _numeric_token_equivalents(result_value)
        ):
            problems.append(
                "derived_calculation_result_projection_missing"
                + problem_suffix
            )
        result_members = [
            _text(value)
            for value in list(
                derived_calculation.get("result_members") or []
            )
            if _text(value)
        ]
        result_member = _text(derived_calculation.get("result_member"))
        if result_member and result_member not in result_members:
            result_members.insert(0, result_member)
        for member_index, member in enumerate(result_members, start=1):
            member_key = _key(member)
            member_bound_to_result = any(
                member_key
                and member_key in _key(segment)
                and {
                    equivalent
                    for token in _answer_numeric_tokens(segment)
                    for equivalent in _numeric_token_equivalents(token)
                }.intersection(_numeric_token_equivalents(result_value))
                # Keep decimal points inside the same evidence segment; a
                # percentage such as 94.81 must remain bound to its label.
                for segment in re.split(r"[\n!?;]+", answer)
                if _text(segment)
            )
            if not member_bound_to_result:
                member_suffix = (
                    f"{problem_suffix}.{member_index}"
                    if len(result_members) > 1
                    else problem_suffix
                )
                problems.append(
                    "derived_calculation_member_projection_missing"
                    + member_suffix
                )
        if derived_calculation.get("show_work") is True:
            for index, operand in enumerate(
                list(derived_calculation.get("operands") or []),
                start=1,
            ):
                if not isinstance(operand, dict) or not answer_number_equivalents.intersection(
                    _numeric_token_equivalents(operand.get("value"))
                ):
                    problems.append(
                        "derived_calculation_operand_projection_missing:"
                        f"{calculation_index}.{index}"
                        if len(derived_calculations) > 1
                        else f"derived_calculation_operand_projection_missing:{index}"
                    )
                for component_index, component in enumerate(
                    list(operand.get("components") or [])
                    if isinstance(operand, dict)
                    else [],
                    start=1,
                ):
                    if not isinstance(component, dict) or not answer_number_equivalents.intersection(
                        _numeric_token_equivalents(component.get("value"))
                    ):
                        problems.append(
                            "derived_calculation_component_projection_missing:"
                            f"{calculation_index}.{index}.{component_index}"
                            if len(derived_calculations) > 1
                            else "derived_calculation_component_projection_missing:"
                            f"{index}.{component_index}"
                        )
            operator = _text(
                dict(derived_calculation.get("contract") or {}).get("operator")
            ).casefold()
            operator_markers = {
                "add": ("+", "topla", "toplam"),
                "subtract": ("-", "cikar", "fark"),
                "multiply": ("×", "*", "carp"),
                "divide": ("/", "bol"),
                "percentage": ("/", "%", "yuzde"),
                "minimum": ("min", "minimum", "en dusuk"),
                "maximum": ("max", "maksimum", "en yuksek"),
            }.get(operator, ())
            if operator_markers and not any(
                marker in _folded_search_text(answer)
                if marker.isalpha() or " " in marker
                else marker in answer
                for marker in operator_markers
            ):
                problems.append(
                    "derived_calculation_operator_projection_missing"
                    + problem_suffix
                )
        result_kind = _text(derived_calculation.get("result_kind")).casefold()
        currency = _text(derived_calculation.get("currency"))
        if currency and _normalized(currency) not in normalized_answer:
            problems.append(
                "derived_calculation_currency_projection_missing:"
                f"{currency}{problem_suffix}"
            )
        if result_kind == "percentage" and "%" not in answer and "yuzde" not in normalized_answer:
            problems.append(
                "derived_calculation_percentage_unit_missing"
                + problem_suffix
            )
        if result_kind == "amount_per_order" and not any(
            marker in normalized_answer
            for marker in ("siparis basina", "ortalama ciro", "try siparis")
        ):
            problems.append(
                "derived_calculation_amount_per_order_label_missing"
                + problem_suffix
            )
        if result_kind == "amount_per_quantity" and not any(
            marker in normalized_answer
            for marker in (
                "adet basina",
                "birim basina",
                "ortalama satis tutari",
                "try adet",
            )
        ):
            problems.append(
                "derived_calculation_amount_per_quantity_label_missing"
                + problem_suffix
            )
        if result_kind == "quantity_per_order" and not any(
            marker in normalized_answer
            for marker in ("siparis basina", "ortalama adet", "adet siparis")
        ):
            problems.append(
                "derived_calculation_quantity_per_order_label_missing"
                + problem_suffix
            )
        if derived_calculation.get("comparison_verified") is True and not boolean_result:
            comparison_operand = derived_calculation.get(
                "comparison_operand"
            )
            comparison_value = (
                comparison_operand.get("value")
                if isinstance(comparison_operand, dict)
                else None
            )
            if not answer_number_equivalents.intersection(
                _numeric_token_equivalents(comparison_value)
            ):
                problems.append(
                    "derived_calculation_comparison_operand_projection_missing"
                    + problem_suffix
                )
            if derived_calculation.get("comparison_difference_included") is True:
                difference_value = derived_calculation.get(
                    "comparison_absolute_difference"
                )
                if not answer_number_equivalents.intersection(
                    _numeric_token_equivalents(difference_value)
                ):
                    problems.append(
                        "derived_calculation_comparison_difference_projection_missing"
                        + problem_suffix
                    )
            if (
                derived_calculation.get("rounding_assessment_verified") is True
                and "yuvarla" not in _folded_search_text(answer)
            ):
                problems.append(
                    "derived_calculation_rounding_assessment_projection_missing"
                    + problem_suffix
                )
            comparison_operator = _text(
                derived_calculation.get("comparison_operator")
            ).casefold()
            comparison_holds = (
                derived_calculation.get("comparison_holds") is True
            )
            if comparison_operator == "equal":
                relation_markers = (
                    ("tutarli", "esit", "uyusuyor", "aynı", "ayni")
                    if comparison_holds
                    else (
                        "tutarsiz",
                        "esit degil",
                        "uyusmuyor",
                        "farkli",
                        "fark",
                    )
                )
            elif comparison_operator == "not_equal":
                relation_markers = (
                    ("farkli", "esit degil", "ayni degil")
                    if comparison_holds
                    else ("ayni", "esit")
                )
            else:
                relation_markers = {
                    "greater_than": ("buyuk", ">"),
                    "greater_or_equal": ("buyuk veya esit", ">="),
                    "less_than": ("kucuk", "<"),
                    "less_or_equal": ("kucuk veya esit", "<="),
                }.get(comparison_operator, ())
                if not comparison_holds:
                    relation_markers = (
                        "saglanmadi",
                        "dogru degil",
                        "yanlis",
                    )
            searchable_answer = _folded_search_text(answer)
            if relation_markers and not any(
                marker in searchable_answer or marker in answer
                for marker in relation_markers
            ):
                problems.append(
                    "derived_calculation_comparison_projection_missing"
                    + problem_suffix
                )

    row_projection_requested = _order_row_projection_requested(
        state,
        requested,
    )
    return_row_projection_requested = _return_row_projection_requested(
        state,
        requested,
    )
    empty_order_list = _authoritative_empty_order_list(state)
    if empty_order_list and not _answer_states_empty_order_list(answer):
        problems.append("empty_order_list_projection_missing")
    empty_return_list = _authoritative_empty_return_list(state)
    if empty_return_list and not _answer_states_empty_return_list(answer):
        problems.append("empty_return_list_projection_missing")
    if "reason" in requested and not return_row_projection_requested:
        cancellation_reasons = _cancellation_reason_distribution(state)
        if not cancellation_reasons:
            problems.append("cancellation_reason_evidence_missing")
        else:
            reason_rows = list(cancellation_reasons.get("reasons") or [])
            cancelled_orders = int(
                cancellation_reasons.get("cancelled_orders") or 0
            )
            if reason_rows:
                if (
                    cancellation_reasons.get("reason_count_unit") == "order_line"
                    and "kalem" not in _normalized(answer)
                ):
                    problems.append("cancellation_reason_count_unit_missing")
                answer_numeric_equivalents = {
                    equivalent
                    for token in _answer_numeric_tokens(answer)
                    for equivalent in _numeric_token_equivalents(token)
                }
                for row in reason_rows:
                    reason = _text(row.get("reason"))
                    count = int(row.get("count") or 0)
                    if reason and _normalized(reason) not in _normalized(answer):
                        problems.append(
                            "cancellation_reason_projection_missing:"
                            + _normalized(reason)
                        )
                    if not answer_numeric_equivalents.intersection(
                        _numeric_token_equivalents(count)
                    ):
                        problems.append(
                            f"cancellation_reason_count_projection_missing:{count}"
                        )
            elif cancelled_orders == 0:
                normalized_answer = _normalized(answer)
                if not (
                    "0" in answer
                    and "neden" in normalized_answer
                    and any(
                        marker in normalized_answer
                        for marker in ("bos", "yok", "bulunmamak")
                    )
                ):
                    problems.append(
                        "empty_cancellation_reason_projection_missing"
                    )
            else:
                normalized_answer = _normalized(answer)
                if not (
                    "neden" in normalized_answer
                    and any(
                        marker in normalized_answer
                        for marker in ("kayitli degil", "bulunamadi", "yok")
                    )
                ):
                    problems.append(
                        "unavailable_cancellation_reason_projection_missing"
                    )
    if "amount" in requested and (
        not derived_calculation or "amount" in direct_projection
    ):
        amount_values = _response_amount_values(
            state,
            prefer_order_rows=row_projection_requested,
        )
        if not amount_values:
            problems.append("amount_evidence_missing")
        else:
            answer_number_equivalents = {
                equivalent
                for token in _answer_numeric_tokens(answer)
                for equivalent in _numeric_token_equivalents(token)
            }
            amount_equivalents = {
                equivalent
                for value in amount_values
                for equivalent in _numeric_token_equivalents(value)
            }
            if not answer_number_equivalents.intersection(amount_equivalents):
                problems.append("amount_projection_missing")
            labelled_amounts = _labelled_numeric_claims(
                answer,
                r"(?<!ortalama\s)ciro|toplam\s+(?:tutar|gelir)|"
                r"tahmini\s+ciro|(?<!average\s)revenue",
            )
            for claim in labelled_amounts:
                if not _numeric_token_equivalents(claim).intersection(
                    amount_equivalents
                ):
                    problems.append(f"aggregate_amount_claim_mismatch:{claim}")
    if "currency" in requested and (
        not derived_calculation or "currency" in direct_projection
    ):
        currencies = _currency_values(state)
        empty_focused_amount = (
            _focused_item_sales_amount(state)
            if "item_sales_amount" in requested
            else {}
        )
        if not currencies and empty_focused_amount.get("empty_result") is True:
            pass
        elif not currencies:
            problems.append("currency_evidence_missing")
        else:
            for currency in currencies:
                if _normalized(currency) not in normalized_answer:
                    problems.append(
                        f"currency_projection_missing:{currency}"
                    )

    full_context_rows = _full_order_context_rows(state)
    if "status" in requested and full_context_rows:
        context_statuses = [
            _text((row.get("order") or {}).get("status"))
            for row in full_context_rows
            if isinstance(row.get("order"), dict)
        ]
        context_statuses = [
            status for status in context_statuses if status
        ]
        if not context_statuses:
            problems.append("order_status_evidence_missing")
        else:
            for status in dict.fromkeys(context_statuses):
                if not _answer_mentions_status(answer, status):
                    problems.append(
                        f"order_status_projection_missing:{_key(status)}"
                    )

    metric_requirements = _order_metric_requirements(state)
    total_required = ORDER_TOTAL_COUNT_METRIC in metric_requirements
    ready_required = ORDER_READY_TO_SHIP_COUNT_METRIC in metric_requirements
    status_distribution_required = (
        ORDER_STATUS_DISTRIBUTION_METRIC in metric_requirements
        or ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC in metric_requirements
    )
    revenue_required = ORDER_REVENUE_TOTAL_METRIC in metric_requirements
    item_sales_required = (
        ORDER_ITEM_SALES_SUMMARY_METRIC in metric_requirements
    )
    fulfillment_risk_required = (
        ORDER_FULFILLMENT_RISK_COUNT_METRIC in metric_requirements
    )
    if revenue_required and not _order_metric_numeric_values(
        state,
        ORDER_REVENUE_TOTAL_METRIC,
    ):
        problems.append("revenue_metric_evidence_missing")
    if (
        item_sales_required
        and not _item_sales_report_rows(state)[0]
        and not _item_sales_report_evidence_observed(state)[0]
        and not _persisted_item_sales_evidence_allowed(state)
    ):
        problems.append("item_sales_metric_evidence_missing")
    if fulfillment_risk_required and not _order_metric_numeric_values(
        state,
        ORDER_FULFILLMENT_RISK_COUNT_METRIC,
    ):
        problems.append("fulfillment_risk_metric_evidence_missing")

    status_count_rows = _status_count_rows(state)
    if (
        "status" in requested
        and not row_projection_requested
        and not return_row_projection_requested
        and status_distribution_required
        and not status_count_rows
    ):
        problems.append("status_distribution_evidence_missing")
    if (
        "status" in requested
        and status_count_rows
        and not row_projection_requested
        and not return_row_projection_requested
    ):
        if len(status_count_rows) > 1:
            problems.append("status_count_evidence_conflict")
        expected_status_counts = status_count_rows[0]
        if (
            not expected_status_counts
            and not (
                _answer_states_empty_order_list(answer)
                and any(
                    marker in normalized_answer
                    for marker in (
                        "durum dagilimi",
                        "siparis durumu",
                        "status distribution",
                    )
                )
            )
        ):
            problems.append("empty_status_distribution_projection_missing")
        all_expected_status_counts = dict(expected_status_counts)
        focused_ratio = (
            _focused_order_status_ratio(state)
            if "ratio" in requested
            else {}
        )
        if focused_ratio:
            focused_status_keys = {
                _key(value)
                for value in list(focused_ratio.get("statuses") or [])
                if _text(value)
            }
            expected_status_counts = {
                status: count
                for status, count in expected_status_counts.items()
                if _key(status) in focused_status_keys
            }
        else:
            typed_status_keys = _typed_status_member_keys(state)
            if typed_status_keys:
                expected_status_counts = {
                    status: count
                    for status, count in expected_status_counts.items()
                    if _key(status) in typed_status_keys
                }
                for status in all_expected_status_counts:
                    if (
                        _key(status) not in typed_status_keys
                        and _answer_mentions_status(answer, status)
                    ):
                        problems.append(
                            f"unrequested_status_projection:{_key(status)}"
                        )
        if (
            _aggregate_analysis_requested(state)
            and _aggregate_status_indicators_available(state)
        ):
            if not _aggregate_status_insight_projected(answer, state):
                problems.append("status_analysis_projection_missing")
        answer_number_equivalents = {
            equivalent
            for token in _answer_numeric_tokens(answer)
            for equivalent in _numeric_token_equivalents(token)
        }
        for status, count in expected_status_counts.items():
            if not _answer_mentions_status(answer, status):
                problems.append(f"status_projection_missing:{status}")
            if not answer_number_equivalents.intersection(
                _numeric_token_equivalents(count)
            ):
                problems.append(f"status_count_projection_missing:{status}")

    if "ratio" in requested and (
        not derived_calculation or "ratio" in direct_projection
    ):
        ratio = _focused_order_status_ratio(state)
        if not ratio:
            problems.append("status_ratio_evidence_missing")
        else:
            answer_number_equivalents = {
                equivalent
                for token in _answer_numeric_tokens(answer)
                for equivalent in _numeric_token_equivalents(token)
            }
            for label, value in (
                ("numerator", ratio.get("numerator")),
                ("denominator", ratio.get("denominator")),
                ("percentage", ratio.get("percentage")),
            ):
                if not answer_number_equivalents.intersection(
                    _numeric_token_equivalents(value)
                ):
                    problems.append(f"status_ratio_{label}_projection_missing")
            for status in list(ratio.get("statuses") or []):
                if not _answer_mentions_status(answer, _text(status)):
                    problems.append(
                        f"status_ratio_status_projection_missing:{_key(status)}"
                    )
            if "%" not in answer and not any(
                marker in normalized_answer
                for marker in ("yuzde", "oran", "payi", "rate", "ratio")
            ):
                problems.append("status_ratio_label_missing")

    total_order_values = _order_metric_numeric_values(
        state,
        ORDER_TOTAL_COUNT_METRIC,
    )
    ready_order_values = _order_metric_numeric_values(
        state,
        ORDER_READY_TO_SHIP_COUNT_METRIC,
    )
    nonfinal_order_values = _order_metric_numeric_values(
        state,
        ORDER_NONFINAL_COUNT_METRIC,
    )
    total_claims = _total_order_claims(answer)
    if total_required and not total_order_values:
        problems.append("total_order_evidence_missing")
    nonfinal_required = ORDER_NONFINAL_COUNT_METRIC in metric_requirements
    if nonfinal_required and not nonfinal_order_values:
        problems.append("nonfinal_order_evidence_missing")
    if (
        "count" in requested
        and (not derived_calculation or "count" in direct_projection)
        and (total_required or total_order_values)
        and total_order_values
        and not total_claims
        and not _answer_projects_total_order_value(answer, total_order_values)
    ):
        problems.append("total_order_projection_missing")
    if (
        "count" in requested
        and (not derived_calculation or "count" in direct_projection)
        and nonfinal_required
        and nonfinal_order_values
        and not _answer_projects_total_order_value(
            answer,
            nonfinal_order_values,
        )
    ):
        problems.append("nonfinal_order_projection_missing")
    if total_order_values and (
        not derived_calculation or "count" in direct_projection
    ):
        expected_totals = {
            equivalent
            for value in total_order_values
            for equivalent in _numeric_token_equivalents(value)
        }
        focused_ratio_numerators = (
            _numeric_token_equivalents(
                focused_ratio_evidence.get("numerator")
            )
            if focused_ratio_evidence.get("numerator") is not None
            else set()
        )
        for claim in total_claims:
            claim_equivalents = _numeric_token_equivalents(claim)
            if claim_equivalents.intersection(expected_totals):
                continue
            # In a focused status-ratio answer, "toplam 45 siparis" can be
            # the sum of the explicitly selected status buckets rather than
            # a claim about the entire order population. The denominator is
            # still checked independently by the ratio projection contract.
            if claim_equivalents.intersection(focused_ratio_numerators):
                continue
            problems.append(f"total_order_claim_mismatch:{claim}")
    ready_claims = _ready_order_claims(answer)
    if ready_required and not ready_order_values:
        problems.append("ready_order_evidence_missing")
    if (
        "count" in requested
        and (not derived_calculation or "count" in direct_projection)
        and (ready_required or ready_order_values)
        and ready_order_values
        and not ready_claims
    ):
        problems.append("ready_order_projection_missing")
    if ready_order_values and (
        not derived_calculation or "count" in direct_projection
    ):
        expected_ready = {
            equivalent
            for value in ready_order_values
            for equivalent in _numeric_token_equivalents(value)
        }
        for claim in ready_claims:
            if not _numeric_token_equivalents(claim).intersection(expected_ready):
                problems.append(f"ready_order_claim_mismatch:{claim}")
    if (
        total_order_values
        and ready_order_values
        and any(
            marker in normalized_answer
            for marker in (
                "tamami kargoya hazir",
                "butun siparisler kargoya hazir",
                "tum siparisler kargoya hazir",
            )
        )
        and not set(total_order_values).intersection(ready_order_values)
    ):
        problems.append("all_orders_ready_claim_conflicts_with_totals")
    if "risk" in requested:
        risk_counts = _risk_counts(state)
        if not risk_counts:
            problems.append("risk_evidence_missing")
        else:
            risk_label_present = any(
                marker in normalized_answer
                for marker in (
                    "risk",
                    "gecik",
                    "teslim suresi",
                    "kargolama son tarih",
                    "son tarihi gecmis",
                )
            )
            if not risk_label_present:
                problems.append("risk_projection_label_missing")
            answer_number_equivalents = {
                equivalent
                for token in _answer_numeric_tokens(answer)
                for equivalent in _numeric_token_equivalents(token)
            }
            risk_equivalents = {
                equivalent
                for value in risk_counts
                for equivalent in _numeric_token_equivalents(value)
            }
            if not answer_number_equivalents.intersection(risk_equivalents):
                problems.append("risk_projection_missing")
    if "cargo_options" in requested:
        provider_rows = _cargo_provider_options(state)
        if not provider_rows:
            problems.append("cargo_options_evidence_missing")
        else:
            normalized_answer = _normalized(answer)
            for row in provider_rows:
                name = _text(row.get("name"))
                code = _text(row.get("code"))
                if name and _normalized(name) not in normalized_answer:
                    problems.append(
                        f"cargo_option_projection_missing:{code or name}"
                    )
        for claim in _provider_catalog_calendar_claims(answer, state):
            problems.append(f"unsubstantiated_provider_catalog_date:{claim}")
    problems.extend(_exact_status_read_evidence_problems(state))
    problems.extend(
        _full_order_context_projection_problems(
            answer,
            state,
            requested,
        )
    )
    if "returns" in requested:
        returns_found, return_count = _return_context_evidence(state)
        if not returns_found:
            problems.append("return_context_evidence_missing")
        elif "iade" not in normalized_answer and "return" not in normalized_answer:
            problems.append("return_context_projection_missing")
        elif return_count == 0:
            zero_return_markers = (
                "iade kaydi yok",
                "iade bulunmuyor",
                "iade bulunmamaktadir",
                "iade yok",
                "0 iade",
                "iade: 0",
            )
            if not any(marker in normalized_answer for marker in zero_return_markers):
                problems.append("zero_return_context_projection_missing")
        else:
            answer_numbers = {
                equivalent
                for token in _answer_numeric_tokens(answer)
                for equivalent in _numeric_token_equivalents(token)
            }
            if not answer_numbers.intersection(
                _numeric_token_equivalents(return_count)
            ):
                problems.append("return_count_projection_missing")

    known_identifiers = {
        _normalized(value)
        for field in ("order_number", "tracking_number", "package_id", "claim_id")
        for value in sensitive.get(field, set())
        if _text(value)
    }
    # Public canonical reason codes can resemble record IDs (e.g. ORDER_*).
    # Only explicitly observed codes in requested risk evidence are eligible;
    # arbitrary observation strings must not bypass identifier/privacy checks.
    observed_reason_codes: set[str] = set()
    if "risk" in requested:
        for operation in ("orders.fulfillment_risk_count", "orders.fulfillment_risk"):
            risk_evidence = dict(_operation_tool_result(state, operation).get("risk_evidence") or {})
            observed_reason_codes.update(
                _normalized(code) for code in list(risk_evidence.get("reason_codes") or [])
                if isinstance(code, str) and code
            )
    requested_item_identifiers: set[str] = set()
    requested_item_identifier_fields = requested.intersection(
        {"sku", "barcode"}
    )
    if requested_item_identifier_fields:
        for payload in _evidence_payloads(state):
            if not isinstance(payload, dict):
                continue
            for context in list(payload.get("contexts") or []):
                if not isinstance(context, dict):
                    continue
                for item in list(context.get("items") or []):
                    if not isinstance(item, dict):
                        continue
                    for field in requested_item_identifier_fields:
                        value = _normalized(item.get(field))
                        if value:
                            requested_item_identifiers.add(value)
    identifier_tokens = re.findall(
        (
            r"\b(?:ORDER|ORD|CLAIM|CLM|TRACK|TRK|PKG|SHP)"
            r"(?:[-_][A-Z0-9_-]{3,}|\d[A-Z0-9_-]{2,})\b|"
            r"(?<![\d.,])\d{6,}(?![\d.,])"
        ),
        answer,
        flags=re.IGNORECASE,
    )
    for token in identifier_tokens:
        normalized_token = _normalized(token)
        if (
            token.isdigit()
            and _numeric_token_equivalents(token).intersection(allowed_numbers)
        ):
            continue
        if normalized_token in known_identifiers:
            continue
        if normalized_token in observed_reason_codes:
            continue
        if normalized_token and any(
            normalized_token in identifier
            for identifier in requested_item_identifiers
        ):
            # Long numeric fragments embedded in an explicitly requested,
            # authoritative SKU/barcode are identifiers, not invented scalar
            # claims. The full labelled SKU/barcode projection is verified by
            # the row contract above; only that exact evidence may ground the
            # fragment.
            continue
        if normalized_token not in _normalized(state.goal):
            problems.append(f"ungrounded_identifier:{token}")

    for field in (
        "order_number",
        "customer_name",
        "address",
        "phone",
        "email",
        "tracking_number",
        "package_id",
        "claim_id",
    ):
        if field in requested or (
            field == "order_number" and "action_result" in requested
        ):
            continue
        if any(
            _answer_contains_sensitive_value(answer, value)
            for value in sensitive.get(field, set())
        ):
            problems.append(f"unrequested_sensitive_projection:{field}")

    if "cargo" not in requested and any(
        _normalized(provider) in _normalized(answer)
        for provider in _cargo_provider_values(state)
        if len(_text(provider)) >= 3
    ):
        problems.append("unrequested_order_projection:cargo")

    if "order_number" in requested and not return_row_projection_requested:
        if not empty_order_list:
            expected_order_numbers = sorted(
                sensitive.get("order_number", set())
            )
            present_order_numbers = [
                value
                for value in expected_order_numbers
                if value.casefold() in answer.casefold()
            ]
            list_projection_requested = any(
                marker in _normalized(state.goal)
                for marker in ("listele", "goster", "sirala", "list ")
            )
            if not expected_order_numbers:
                problems.append("order_number_evidence_missing")
            elif list_projection_requested and len(present_order_numbers) != len(
                expected_order_numbers
            ):
                problems.append(
                    "requested_order_numbers_missing:"
                    f"{len(expected_order_numbers) - len(present_order_numbers)}"
                )
            elif not present_order_numbers:
                problems.append("requested_order_number_missing")

    if row_projection_requested:
        projected_rows = _order_rows_projection(state, requested)
        if not projected_rows and not empty_order_list:
            problems.append("order_row_evidence_missing")
        elif projected_rows:
            answer_lines = [
                _text(line) for line in answer.splitlines() if _text(line)
            ]
            row_fields = (
                "status",
                "amount",
                "date",
                "customer_name",
                "cargo",
                "tracking_number",
                "package_id",
                "item_count",
            )
            empty_field_labels = {
                "status": ("durum", "status"),
                "amount": ("tutar", "amount"),
                "date": ("tarih", "date"),
                "customer_name": ("musteri", "customer"),
                "cargo": ("kargo", "cargo"),
                "tracking_number": ("takip", "tracking"),
                "package_id": ("paket", "package"),
                "item_count": ("kalem sayisi", "item count"),
            }
            row_blocks = record_answer_blocks(answer, [_text(row.get("order_number")) for row in projected_rows])
            for index, row in enumerate(projected_rows, start=1):
                order_number = _text(row.get("order_number"))
                matching_line = _text(row_blocks[index - 1].get("text"))
                if not matching_line:
                    problems.append(
                        "requested_order_row_missing:"
                        f"{order_number or f'ordinal_{index}'}"
                    )
                    continue
                if row.get("ordinal") is not None and row_blocks[index - 1].get("ordinal") != row["ordinal"]:
                    problems.append(f"requested_order_ordinal_missing:{order_number or index}")
                normalized_line = _normalized(matching_line)
                line_numeric_equivalents = {
                    equivalent
                    for token in _answer_numeric_tokens(matching_line)
                    for equivalent in _numeric_token_equivalents(token)
                }
                for field in row_fields:
                    if field not in requested:
                        continue
                    expected = row.get(field)
                    field_present = False
                    if field == "status" and _text(expected):
                        field_present = _answer_mentions_status(
                            matching_line,
                            _text(expected),
                        )
                    elif field == "amount" and expected is not None:
                        field_present = bool(
                            line_numeric_equivalents.intersection(
                                _numeric_token_equivalents(expected)
                            )
                        )
                    elif field == "item_count" and expected is not None:
                        field_present = bool(
                            line_numeric_equivalents.intersection(
                                _numeric_token_equivalents(expected)
                            )
                            and any(
                                marker in normalized_line
                                for marker in ("kalem sayisi", "item count")
                            )
                        )
                    elif field == "date" and _text(expected):
                        field_present = bool(
                            _normalized(expected) in normalized_line
                            or line_numeric_equivalents.intersection(
                                _date_numeric_equivalents(expected)
                            )
                        )
                    elif _text(expected):
                        field_present = _normalized(expected) in normalized_line
                    else:
                        field_present = any(
                            re.search(
                                rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])",
                                normalized_line,
                            )
                            for label in empty_field_labels[field]
                        )
                    if not field_present:
                        problems.append(
                            "requested_order_row_field_missing:"
                            f"{order_number or f'ordinal_{index}'}:{field}"
                        )

    if return_row_projection_requested:
        return_result = _return_query_list_result(state)
        projected_return_rows = _return_rows_projection(state, requested)
        if not return_result:
            problems.append("return_row_evidence_missing")
        else:
            try:
                total_return_count = int(
                    return_result.get(
                        "total_count",
                        return_result.get("count"),
                    )
                )
            except (TypeError, ValueError):
                total_return_count = -1
                problems.append("return_list_total_count_evidence_missing")
            if return_result.get("truncated") is not False:
                problems.append("return_list_not_exhaustive")
            if total_return_count >= 0 and total_return_count != len(
                projected_return_rows
            ):
                problems.append("return_list_cardinality_mismatch")
            if "count" in requested and total_return_count >= 0:
                answer_numbers = {
                    equivalent
                    for token in _answer_numeric_tokens(answer)
                    for equivalent in _numeric_token_equivalents(token)
                }
                if not answer_numbers.intersection(
                    _numeric_token_equivalents(total_return_count)
                ):
                    problems.append("return_count_projection_missing")
            if not projected_return_rows and not empty_return_list:
                problems.append("return_row_evidence_missing")
            elif projected_return_rows:
                answer_lines = [
                    _text(line) for line in answer.splitlines() if _text(line)
                ]
                for index, row in enumerate(projected_return_rows, start=1):
                    claim_id = _text(row.get("claim_id"))
                    order_number = _text(row.get("order_number"))
                    matching_line = next(
                        (
                            line
                            for line in answer_lines
                            if (
                                claim_id
                                and claim_id.casefold() in line.casefold()
                            )
                            or (
                                not claim_id
                                and order_number
                                and order_number.casefold() in line.casefold()
                            )
                        ),
                        "",
                    )
                    if not matching_line:
                        problems.append(
                            f"requested_return_row_missing:{claim_id or order_number or index}"
                        )
                        continue
                    normalized_line = _normalized(matching_line)
                    for field, labels in (
                        ("claim_id", ("claim", "iade no")),
                        ("order_number", ("siparis", "order")),
                        ("status", ("durum", "status")),
                        ("reason", ("neden", "sebep", "reason")),
                    ):
                        if field not in requested:
                            continue
                        expected = _text(row.get(field))
                        if field == "status" and expected:
                            field_present = _answer_mentions_status(
                                matching_line,
                                expected,
                            )
                        elif expected:
                            field_present = _normalized(expected) in normalized_line
                        else:
                            field_present = bool(
                                any(label in normalized_line for label in labels)
                                and any(
                                    marker in normalized_line
                                    for marker in (
                                        "belirtilmemis",
                                        "bulunmuyor",
                                        "yok",
                                    )
                                )
                            )
                        if not field_present:
                            problems.append(
                                "requested_return_row_field_missing:"
                                f"{claim_id or order_number or index}:{field}"
                            )

    if "claim_id" in requested and not return_row_projection_requested:
        active_selection = state.active_selection("returns")
        expected_claim_ids = (
            [
                _text(value)
                for value in active_selection.record_ids
                if _text(value)
            ]
            if active_selection is not None and active_selection.is_complete
            else sorted(sensitive.get("claim_id", set()))
        )
        present_claim_ids = [
            value
            for value in expected_claim_ids
            if value.casefold() in answer.casefold()
        ]
        list_projection_requested = any(
            marker in _normalized(state.goal)
            for marker in ("listele", "goster", "sirala", "list ")
        )
        if not expected_claim_ids:
            problems.append("claim_id_evidence_missing")
        elif list_projection_requested and len(present_claim_ids) != len(
            expected_claim_ids
        ):
            problems.append(
                "requested_claim_ids_missing:"
                f"{len(expected_claim_ids) - len(present_claim_ids)}"
            )
        elif not present_claim_ids:
            problems.append("requested_claim_id_missing")

    aggregate_order_summary_observed = _general_broad_summary_requested(state) and any(
        step.status == "completed" and step.verification_status in {"observed", "verified"}
        and step.tool_names == ["orders.summary"]
        and isinstance((step.result_data or {}).get("tool_result"), dict)
        and {"total_orders", "estimated_revenue"}.issubset(step.result_data["tool_result"])
        for step in state.completed_steps
    )
    if "item_sales_rows" in requested and not aggregate_order_summary_observed:
        report_rows, _period, _exhaustive = _item_sales_rows_for_response(
            state
        )
        if not report_rows:
            observed_empty, _observed_period = (
                _item_sales_report_evidence_observed(state)
            )
            if not observed_empty:
                problems.append("item_sales_report_evidence_missing")
            elif not _answer_states_empty_item_sales(answer):
                problems.append("empty_item_sales_projection_missing")
        elif grouped_projection(_turn_semantic_contract(state)):
            problems.extend(_grouped_sales_problems(answer, state, report_rows))
        elif (
            _aggregate_analysis_requested(state)
            and _aggregate_item_indicators_available(state)
            and ORDER_ITEM_SALES_REPORT_METRIC
            not in _order_metric_requirements(state)
        ):
            if not _aggregate_item_insight_projected(answer, state):
                problems.append("item_sales_analysis_projection_missing")
        else:
            answer_lines = [_text(line) for line in answer.splitlines() if _text(line)]
            missing_rows = 0
            incomplete_rows = 0
            for row in report_rows:
                product_name = _text(row.get("product_name"))
                matching_line = next(
                    (
                        line
                        for line in answer_lines
                        if product_name.casefold() in line.casefold()
                    ),
                    "",
                )
                if not matching_line:
                    missing_rows += 1
                    continue
                normalized_line = _normalized(matching_line)
                expected_parts = (
                    _normalized(f"adet {int(row.get('quantity') or 0)}"),
                    _normalized(f"siparis {int(row.get('order_count') or 0)}"),
                    _normalized(f"brut {_text(row.get('gross_amount'))}"),
                )
                if not all(part in normalized_line for part in expected_parts):
                    incomplete_rows += 1
            if missing_rows:
                problems.append(f"requested_item_sales_rows_missing:{missing_rows}")
            if incomplete_rows:
                problems.append(
                    f"requested_item_sales_metrics_missing:{incomplete_rows}"
                )

    if "item_sales_quantity" in requested:
        focused_item_sales = _focused_item_sales_quantity(state)
        if not focused_item_sales:
            problems.append("focused_item_sales_quantity_evidence_missing")
        else:
            product_name = _text(focused_item_sales.get("product_name"))
            if product_name.casefold() not in answer.casefold():
                problems.append("focused_item_sales_product_projection_missing")
            if not _answer_projects_item_sales_quantity(
                answer,
                int(focused_item_sales.get("quantity") or 0),
            ):
                problems.append("focused_item_sales_quantity_projection_missing")

    if "item_sales_order_count" in requested:
        focused_item_sales = _focused_item_sales_order_count(state)
        if not focused_item_sales:
            problems.append("focused_item_sales_order_count_evidence_missing")
        else:
            product_name = _text(focused_item_sales.get("product_name"))
            if product_name.casefold() not in answer.casefold():
                problems.append(
                    "focused_item_sales_order_count_product_projection_missing"
                )
            if not _answer_projects_item_sales_order_count(
                answer,
                int(focused_item_sales.get("order_count") or 0),
            ):
                problems.append(
                    "focused_item_sales_order_count_projection_missing"
                )

    if "item_sales_amount" in requested:
        focused_item_sales = _focused_item_sales_amount(state)
        if not focused_item_sales:
            problems.append("focused_item_sales_amount_evidence_missing")
        else:
            product_name = _text(focused_item_sales.get("product_name"))
            if product_name.casefold() not in answer.casefold():
                problems.append(
                    "focused_item_sales_amount_product_projection_missing"
                )
            if not _answer_projects_item_sales_amount(
                answer,
                list(focused_item_sales.get("amounts") or []),
            ):
                problems.append("focused_item_sales_amount_projection_missing")

    for field, values in sensitive.items():
        if field in requested or (field == "order_number" and "action_result" in requested):
            continue
        for value in values:
            clean = _text(value)
            if _answer_contains_sensitive_value(answer, clean):
                problems.append(f"unrequested_private_field:{field}")
                break
    labelled_projection_fields = {
        "customer_name": ("musteri adi", "musteri ismi", "customer name"),
        "address": ("teslimat adresi", "musteri adresi", "delivery address"),
        "date": ("siparis tarihi", "order date"),
        "amount": ("tutar", "siparis tutari", "amount"),
        "status": ("durum", "siparis durumu", "status"),
        "sku": ("sku", "stok kodu", "stock code"),
        "barcode": ("barkod", "barcode", "gtin"),
        "reason": ("neden", "iade nedeni", "return reason"),
    }
    searchable_answer = _folded_search_text(answer)
    for field, labels in labelled_projection_fields.items():
        if field in requested:
            continue
        if any(
            re.search(
                rf"(?<![a-z0-9]){re.escape(label)}\s*:",
                searchable_answer,
            )
            for label in labels
        ):
            problems.append(f"unrequested_field_label:{field}")
    if "email" not in requested and re.search(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", answer):
        problems.append("unrequested_private_field:email")

    opened_sources = web_evidence_projection(state)
    opened_urls = {_text(row.get("url")) for row in opened_sources if _text(row.get("url"))}
    answer_urls = set(re.findall(r"https?://[^\s)>\]]+", answer))
    unknown_urls = sorted(answer_urls.difference(opened_urls))
    if unknown_urls:
        problems.extend(f"web_source_not_opened:{url}" for url in unknown_urls)
    source_kind = _text(_turn_semantic_contract(state).get("information_source")
                        or (state.active_entities.get("turn_interpretation") or {}).get("information_source")).casefold()
    web_requested = "web_sources" in requested or (
        "research_findings" in requested and (source_kind != "local_business_data"
                                               or state.active_domain == "web" or bool(opened_sources)))
    if web_requested and not opened_sources:
        problems.append("opened_web_source_evidence_missing")
    if web_requested and opened_urls and not opened_urls.issubset(answer_urls):
        problems.append("opened_web_source_citation_missing")
    if "research_findings" in requested and opened_sources:
        normalized_research_answer = _normalized(answer)
        if any(
            marker in normalized_research_answer
            for marker in (
                "ozet sunulamaz",
                "bulgu sunulamaz",
                "ozetlenemez",
                "kanit olarak kullanilamaz",
                "guvenilmez veri oldugu icin",
                "guvenilmez veri olarak isaretlendiginden",
            )
        ):
            problems.append(
                "research_findings_refused_despite_adequate_opened_evidence"
            )
    search_candidate_urls: set[str] = set()
    for step in state.completed_steps:
        if "web.search" not in {_text(value) for value in list(step.tool_names or [])}:
            continue
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        search_candidate_urls.update(
            _text(row.get("url"))
            for row in list(tool_result.get("results") or [])
            if isinstance(row, dict) and _text(row.get("url"))
        )
    unopened_candidates = answer_urls.intersection(search_candidate_urls.difference(opened_urls))
    if unopened_candidates:
        problems.append("search_candidate_cited_without_opening")

    if requested == {"count"}:
        for field in ("order_number", "customer_name", "address", "phone", "email", "tracking_number", "package_id", "claim_id"):
            if any(
                _answer_contains_sensitive_value(answer, value)
                for value in sensitive.get(field, set())
            ):
                problems.append("count_projection_expanded")
                break
    if requested == {"store"}:
        if _answer_numeric_tokens(answer):
            problems.append("store_projection_expanded")

    if "scope" in requested:
        scope_rows = _account_scope_rows(state)
        if not scope_rows:
            problems.append("scope_evidence_missing")
        for index, row in enumerate(scope_rows, start=1):
            store = _normalized(row.get("store_name"))
            account_id = _normalized(row.get("account_id"))
            environment = _normalized(row.get("environment"))
            if store and store not in normalized_answer and (
                not account_id or account_id not in normalized_answer
            ):
                problems.append(f"scope_store_missing:{index}")
            if environment and environment not in normalized_answer:
                problems.append(f"scope_environment_missing:{index}")
        unrequested_scope_markers = [
            marker
            for markers, field in (
                (("musteri adi", "musteri ismi", "customer name"), "customer_name"),
                (("teslimat adresi", "musteri adresi", "delivery address"), "address"),
                (("takip numarasi", "kargo takip no", "tracking number"), "tracking_number"),
                (("paket id", "paket numarasi", "package id"), "package_id"),
                (("claim id", "claim numarasi", "iade claim no"), "claim_id"),
            )
            if field not in requested
            for marker in markers
        ]
        if any(marker in normalized_answer for marker in unrequested_scope_markers):
            problems.append("store_projection_expanded")

    problems.extend(_status_claim_problems(answer, set(evidence["statuses"])))
    has_execute, all_verified = _has_verified_execute(state)
    problems.extend(_executed_action_state_problems(answer, state))
    action_claim = any(noun in normalized_answer for noun in _ACTION_NOUNS) and any(
        word in normalized_answer for word in _COMPLETION_WORDS
    )
    if action_claim and not has_execute:
        problems.append("unexecuted_action_claimed_complete")
    if "dogrulandi" in normalized_answer and has_execute and not all_verified:
        problems.append("unverified_action_claimed_verified")

    allowed = not problems
    verification = _record_response_verification(
        state,
        allowed=allowed,
        source=source,
        requested_fields=requested,
        reason_codes=problems,
    )
    if not allowed:
        return Result.fail(
            "Response verifier cevabi observation ve projection sozlesmesine uygun bulmadi.",
            close_dialog=False,
            data={"response_verification": verification, "retryable": False},
        )
    return Result.ok(
        "Response grounding, projection ve privacy dogrulandi.",
        close_dialog=False,
        data={"response_verification": verification},
    )


def _first_scalar(state: AgentSessionState) -> tuple[Any, str, dict[str, Any]]:
    for step in state.completed_steps:
        data = dict(step.result_data or {})
        tool_result = (
            dict(data.get("tool_result") or {})
            if isinstance(data.get("tool_result"), dict)
            else {}
        )
        for key_name in ("count", "total_count", "item_count", "risk_count", "total"):
            value = tool_result.get(key_name)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                operation = next(iter(step.tool_names or []), "")
                return value, _text(operation), tool_result
    return None, "", {}


def _count_projection(state: AgentSessionState) -> str:
    metric_requirements = _order_metric_requirements(state)
    total_values = _order_metric_numeric_values(
        state,
        ORDER_TOTAL_COUNT_METRIC,
    )
    ready_values = _order_metric_numeric_values(
        state,
        ORDER_READY_TO_SHIP_COUNT_METRIC,
    )
    nonfinal_values = _order_metric_numeric_values(
        state,
        ORDER_NONFINAL_COUNT_METRIC,
    )
    cancelled_values = _order_metric_numeric_values(
        state,
        ORDER_CANCELLED_COUNT_METRIC,
    )
    aggregate_parts: list[str] = []
    if total_values:
        if len(total_values) != 1:
            aggregate_parts.append(
                "Toplam siparis sayisi authoritative sonuclar arasinda celiskili."
            )
        else:
            value = total_values[0]
            clean = int(value) if isinstance(value, float) and value.is_integer() else value
            aggregate_parts.append(f"Toplam {clean} siparis var.")
    if ready_values:
        if len(ready_values) != 1:
            aggregate_parts.append(
                "Kargoya hazir siparis sayisi authoritative sonuclar arasinda celiskili."
            )
        else:
            value = ready_values[0]
            clean = int(value) if isinstance(value, float) and value.is_integer() else value
            aggregate_parts.append(f"Kargoya hazir {clean} siparis var.")
    if nonfinal_values:
        if len(nonfinal_values) != 1:
            aggregate_parts.append(
                "Final olmayan siparis sayisi authoritative sonuclar arasinda celiskili."
            )
        else:
            value = nonfinal_values[0]
            clean = int(value) if isinstance(value, float) and value.is_integer() else value
            aggregate_parts.append(
                f"Sevkiyat sureci tamamlanmamis {clean} siparis var."
            )
    if cancelled_values:
        if len(cancelled_values) != 1:
            aggregate_parts.append(
                "Iptal siparis sayisi authoritative sonuclar arasinda celiskili."
            )
        else:
            value = cancelled_values[0]
            clean = int(value) if isinstance(value, float) and value.is_integer() else value
            aggregate_parts.append(f"Iptal edilmis {clean} siparis var.")
    if aggregate_parts:
        return " ".join(aggregate_parts)

    if metric_requirements.intersection(
        {
            ORDER_TOTAL_COUNT_METRIC,
            ORDER_READY_TO_SHIP_COUNT_METRIC,
            ORDER_NONFINAL_COUNT_METRIC,
            ORDER_CANCELLED_COUNT_METRIC,
        }
    ):
        return "Istenen siparis adetleri authoritative sonuc icinde bulunamadi."

    value, operation, data = _first_scalar(state)
    if value is None:
        return ""
    for step in state.completed_steps:
        result_data = dict(step.result_data or {})
        context = (
            dict(result_data.get("conversation_context") or {})
            if isinstance(result_data.get("conversation_context"), dict)
            else {}
        )
        authoritative_answer = _text(context.get("authoritative_answer"))
        source_tool = _text(context.get("source_tool"))
        if (
            _text(context.get("kind")) == "scalar_tool_result"
            and authoritative_answer
            and (not source_tool or source_tool == operation)
        ):
            return authoritative_answer
    count = int(value) if isinstance(value, float) and value.is_integer() else value
    labels = {
        "orders.ready_to_ship_count": "Kargoya hazir",
        "orders.ready_to_ship": "Kargoya hazir",
        "orders.cancelled_count": "Iptal",
        "orders.count": _human_period_scope(data.get("period_label"))
        or "Secilen donemde",
        "returns.query": "Eslesen iade",
        "returns.waiting_action_count": "Onay bekleyen",
    }
    label = labels.get(
        operation,
        _human_period_scope(data.get("period_label")) or "Eslesen",
    )
    owner_domain = operation.partition(".")[0]
    noun = {
        "orders": "siparis",
        "returns": "iade kaydi",
        "stock": "stok karti",
        "listings": "ilan",
        "customers": "musteri kaydi",
    }.get(owner_domain, "kayit")
    return f"{label} {count} {noun} var."


def _cancellation_reason_projection(state: AgentSessionState) -> str:
    distribution = _cancellation_reason_distribution(state)
    if not distribution:
        return "Iptal nedeni dagilimi authoritative sonuc icinde bulunamadi."
    reasons = list(distribution.get("reasons") or [])
    cancelled_orders = int(distribution.get("cancelled_orders") or 0)
    if not reasons:
        if cancelled_orders == 0:
            return "Iptal nedeni dagilimi bos; iptal edilmis 0 siparis var."
        return "Iptal edilen siparisler icin neden bilgisi kayitli degil."
    return f"{cancelled_orders} iptal sipariş var. İptal nedenleri (sipariş kalemi sayısı): " + ", ".join(
        f"{_text(row.get('reason'))} ({int(row.get('count') or 0)})"
        for row in reasons
    ) + ". Bir siparişte birden fazla kalem olabilir."


def _store_projection(state: AgentSessionState) -> str:
    stores = sorted(_collect_evidence(state)["stores"])
    if not stores:
        return "Magaza bilgisi authoritative sonuc icinde bulunamadi."
    return "Magaza: " + ", ".join(stores) + "."


def _scope_projection(state: AgentSessionState) -> str:
    rows = _account_scope_rows(state)
    if not rows:
        return "Kapsam: authoritative hesap/ortam bilgisi bulunamadi."
    requested = requested_response_fields(state)
    sensitive = dict(_collect_evidence(state)["sensitive"])
    labels: list[str] = []
    for row in rows:
        store = _text(row.get("store_name"))
        account_id = _text(row.get("account_id"))
        environment = _text(row.get("environment")) or "production"
        if environment == "stage" and account_id and "store" not in requested:
            # Shared/test account display names can contain a person's name.
            # Scope-only answers identify Stage by seller id instead.
            store = account_id
        collides_with_unrequested_sensitive_value = any(
            _answer_contains_sensitive_value(store, value)
            for field, values in sensitive.items()
            if field not in requested
            for value in values
        )
        if collides_with_unrequested_sensitive_value:
            store = account_id
        store = store or account_id or "Hesap"
        platform = _text(row.get("platform"))
        detail = " / ".join(value for value in (platform, environment) if value)
        labels.append(f"{store} ({detail})" if detail else store)
    return "Kapsam: " + ", ".join(dict.fromkeys(labels)) + "."


def _amount_projection(state: AgentSessionState) -> str:
    if _stock_detail_rows(state):
        source = next((dict(step.result_data or {}).get("tool_result") or {}
            for step in reversed(state.completed_steps) if step.status == "completed"
            and step.verification_status in {"observed", "verified"}
            and step.tool_names == ["stock.inventory_overview"]), {})
        values = [f"{_text(row.get('amount'))} {_text(row.get('currency'))}"
                  for row in source.get("stock_value_by_currency") or [] if isinstance(row, dict)]
        if values:
            return "Stok değeri (para birimleri ayrı): " + ", ".join(values) + "."
    values = _response_amount_values(state)
    if not values:
        return "Tutar authoritative sonuç içinde bulunamadı."
    value = values[0]
    clean = int(value) if isinstance(value, float) and value.is_integer() else value
    return f"Tahmini ciro: {clean}."


def _currency_projection(state: AgentSessionState) -> str:
    currencies = _currency_values(state)
    if not currencies:
        return "Para birimi authoritative sonuc icinde bulunamadi."
    if len(currencies) == 1:
        return f"Para birimi: {currencies[0]}."
    return "Para birimleri: " + ", ".join(currencies) + "."


def _risk_projection(state: AgentSessionState) -> str:
    values = _risk_counts(state)
    if not values:
        return "Fulfillment riski authoritative sonuç içinde bulunamadı."
    if any(
        "orders.shipping_deadline_analysis" in set(step.tool_names or [])
        for step in state.completed_steps
    ):
        return f"Kargolama son tarihi gecmis: {values[0]} kayit."
    return f"Fulfillment riski: {values[0]} kayıt."


def _cargo_options_projection(state: AgentSessionState) -> str:
    rows = _cargo_provider_options(state)
    if not rows:
        return "Kargo firmasi secenekleri authoritative sonuc icinde bulunamadi."
    return "Kargo firmasi secenekleri ({}):\n{}".format(
        len(rows),
        "\n".join(
            "- {}{}".format(
                row.get("name") or row.get("code"),
                f" ({row.get('code')})" if row.get("name") and row.get("code") else "",
            )
            for row in rows
        ),
    )


def _status_projection(state: AgentSessionState, *, include_order_number: bool) -> str:
    status_count_rows = _status_count_rows(state)
    if status_count_rows:
        if len(status_count_rows) > 1:
            return "Siparis durum dagilimi authoritative sonuclar arasinda celiskili."
        if not status_count_rows[0]:
            summary = _operation_tool_result(state, "orders.summary")
            scope = _human_period_scope(
                summary.get("period_label") or summary.get("period")
            )
            prefix = f"{scope} " if scope else ""
            return (
                f"{prefix}siparis durum dagilimi bos; "
                "bu kapsamda 0 siparis var."
            )
        projected_counts = dict(status_count_rows[0])
        typed_status_keys = _typed_status_member_keys(state)
        if typed_status_keys:
            projected_counts = {
                status: count
                for status, count in projected_counts.items()
                if _key(status) in typed_status_keys
            }
        return "Siparis durumlari: " + ", ".join(
            f"{status} {count}"
            for status, count in sorted(projected_counts.items())
        ) + "."
    if {
        ORDER_STATUS_DISTRIBUTION_METRIC,
        ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC,
    }.intersection(_order_metric_requirements(state)):
        return "Siparis durum dagilimi authoritative sonuc icinde bulunamadi."
    evidence = _collect_evidence(state)
    statuses = sorted(evidence["statuses"])
    order_numbers = sorted(evidence["sensitive"].get("order_number", set()))
    if not statuses:
        return "Siparis durumu authoritative sonuc icinde bulunamadi."
    if len(statuses) == 1:
        prefix = (
            f"Siparis {order_numbers[0]} durumu"
            if include_order_number and len(order_numbers) == 1
            else "Siparis durumu"
        )
        return f"{prefix}: {statuses[0]}."
    return "Siparis durumlari: " + ", ".join(statuses) + "."


def _status_ratio_projection(state: AgentSessionState) -> str:
    ratio = _focused_order_status_ratio(state)
    if not ratio:
        return "Siparis durum orani authoritative sonuc icinde bulunamadi."
    components = list(ratio.get("components") or [])
    if len(components) > 1:
        calculation = " + ".join(
            f"{_text(row.get('status'))} {int(row.get('count') or 0)}"
            for row in components
        )
        return (
            "{calculation} = {numerator}; {numerator} / toplam {denominator} "
            "siparis = %{percentage}. Bu durumlar birlikte siparislerin "
            "%{percentage}'sini olusturuyor."
        ).format(calculation=calculation, **ratio)
    return (
        "{status}: {numerator} / toplam {denominator} siparis = %{percentage}. "
        "Siparislerin %{percentage}'si {status} durumunda."
    ).format(**ratio)


def _order_number_projection(state: AgentSessionState) -> str:
    order_numbers = sorted(
        _collect_evidence(state)["sensitive"].get("order_number", set())
    )
    if not order_numbers:
        if _authoritative_empty_order_list(state):
            contract = _turn_semantic_contract(state)
            if (
                _text(contract.get("status_scope")).casefold()
                == "ready_to_ship"
            ):
                return (
                    "Kargoya hazir siparis kuyrugu bos; "
                    "sorgu kapsaminda 0 siparis bulundu."
                )
            return "Sorgu kapsaminda 0 siparis bulundu; eslesen kayit yok."
        return "Siparis numarasi authoritative sonuc icinde bulunamadi."
    return "Siparis numaralari:\n" + "\n".join(
        f"- {value}" for value in order_numbers
    )


def _order_rows_text_projection(
    state: AgentSessionState,
    requested: set[str],
) -> str:
    rows = _order_rows_projection(state, requested)
    if not rows:
        if _authoritative_empty_order_list(state):
            contract = _turn_semantic_contract(state)
            if (
                _text(contract.get("status_scope")).casefold()
                == "ready_to_ship"
            ):
                return (
                    "Kargoya hazir siparis kuyrugu bos; "
                    "sorgu kapsaminda 0 siparis bulundu."
                )
            return "Sorgu kapsaminda 0 siparis bulundu; eslesen kayit yok."
        return "Siparis satirlari authoritative sonuc icinde bulunamadi."
    lines = [f"Sonuc: {len(rows)} siparis listelendi."]
    show_order_number = "order_number" in requested
    for index, row in enumerate(rows, start=1):
        cells: list[str] = []
        if show_order_number and _text(row.get("order_number")):
            cells.append(_text(row.get("order_number")))
        elif not show_order_number:
            cells.append(f"{index}. siparis")
        if "status" in requested:
            cells.append(
                "durum: " + (_text(row.get("status")) or "belirtilmemis")
            )
        if "amount" in requested:
            if row.get("amount") is None:
                cells.append("tutar: belirtilmemis")
            else:
                currency = _text(row.get("currency"))
                cells.append(
                    f"tutar: {row.get('amount')}"
                    + (f" {currency}" if currency else "")
                )
        if "date" in requested:
            cells.append(
                "tarih: " + (_text(row.get("date")) or "belirtilmemis")
            )
        if "customer_name" in requested:
            cells.append(
                "musteri: "
                + (_text(row.get("customer_name")) or "belirtilmemis")
            )
        if "cargo" in requested:
            cells.append(
                "kargo: " + (_text(row.get("cargo")) or "belirtilmemis")
            )
        if "tracking_number" in requested:
            cells.append(
                "takip: "
                + (_text(row.get("tracking_number")) or "belirtilmemis")
            )
        if "package_id" in requested:
            cells.append(
                "paket: " + (_text(row.get("package_id")) or "belirtilmemis")
            )
        if "item_count" in requested:
            if row.get("item_count") is None:
                cells.append("kalem sayisi: belirtilmemis")
            else:
                cells.append(f"kalem sayisi: {row.get('item_count')}")
        if "items" in row:
            if row["items"] is None:
                cells.append("Urun kalemi kaniti bulunamadi.")
            elif not row["items"]:
                cells.append("Siparis kalemi bulunmuyor.")
            else:
                cells.append("Urunler: " + "; ".join(_order_item_text(item, requested) for item in row["items"]))
        if cells:
            prefix = f"{row['ordinal']}. " if show_order_number and row.get("ordinal") is not None else "- "
            lines.append(prefix + " | ".join(cells))
    return "\n".join(lines)


def _return_rows_text_projection(
    state: AgentSessionState,
    requested: set[str],
) -> str:
    result = _return_query_list_result(state)
    rows = _return_rows_projection(state, requested)
    if not result:
        return "Iade satirlari authoritative sonuc icinde bulunamadi."
    try:
        total_count = int(result.get("total_count", result.get("count")))
    except (TypeError, ValueError):
        return "Iade liste sayisi authoritative sonuc icinde bulunamadi."
    if not rows:
        if _authoritative_empty_return_list(state):
            return (
                "Aksiyon bekleyen iade yok; sorgu kapsaminda 0 iade bulundu."
            )
        return "Iade satirlari authoritative sonuc icinde bulunamadi."
    lines = [f"Sonuc: toplam {total_count} iade listelendi."]
    for row in rows:
        cells: list[str] = []
        if "claim_id" in requested:
            cells.append(
                "claim: " + (_text(row.get("claim_id")) or "belirtilmemis")
            )
        if "order_number" in requested:
            cells.append(
                "siparis: "
                + (_text(row.get("order_number")) or "belirtilmemis")
            )
        if "status" in requested:
            cells.append(
                "durum: " + (_text(row.get("status")) or "belirtilmemis")
            )
        if "reason" in requested:
            cells.append(
                "neden: " + (_text(row.get("reason")) or "belirtilmemis")
            )
        if cells:
            lines.append("- " + " | ".join(cells))
    return "\n".join(lines)


def _claim_projection(
    state: AgentSessionState,
    *,
    include_status: bool,
) -> str:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for step in state.completed_steps:
        result_data = dict(step.result_data or {})
        tool_result = (
            dict(result_data.get("tool_result") or {})
            if isinstance(result_data.get("tool_result"), dict)
            else {}
        )
        payloads = [tool_result]
        if isinstance(tool_result.get("data"), dict):
            payloads.append(dict(tool_result.get("data") or {}))
        for payload in payloads:
            for raw in list(payload.get("returns") or []):
                if not isinstance(raw, dict):
                    continue
                claim_id = _text(raw.get("claim_id"))
                if not claim_id or claim_id in seen:
                    continue
                seen.add(claim_id)
                rows.append(
                    {
                        "claim_id": claim_id,
                        "status": _text(raw.get("status")),
                    }
                )
    if not rows:
        claim_ids = sorted(
            _collect_evidence(state)["sensitive"].get("claim_id", set())
        )
        rows = [{"claim_id": value, "status": ""} for value in claim_ids]
    if not rows:
        return "Claim numarasi authoritative sonuc icinde bulunamadi."
    header = "Claim numaralari ve durumlari:" if include_status else "Claim numaralari:"
    return header + "\n" + "\n".join(
        (
            f"- {row['claim_id']} | {row['status']}"
            if include_status and row["status"]
            else f"- {row['claim_id']}"
        )
        for row in rows
    )


def _scrub_unrequested_values(
    text: str,
    state: AgentSessionState,
    requested: set[str],
) -> str:
    answer = _text(text)
    sensitive = dict(_collect_evidence(state)["sensitive"])
    for field, values in sensitive.items():
        if field in requested or (field == "order_number" and "action_result" in requested):
            continue
        for value in sorted(values, key=lambda item: len(_text(item)), reverse=True):
            clean = _text(value)
            if len(clean) < 3:
                continue
            answer = re.sub(re.escape(clean), "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"[ \t]+", " ", answer)
    answer = re.sub(r"\s+([,.;:])", r"\1", answer)
    answer = re.sub(r"(?m)^\s*[-|:]\s*$", "", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer).strip(" -|,:\n")
    return answer


def _pending_report_followup_requested(state: AgentSessionState, requested: set[str]) -> bool:
    from AI.processors.observation_context import pending_report_read_contract
    interpretation = (state.active_entities or {}).get('turn_interpretation') or {}
    return bool(state.active_pending_action() and pending_report_read_contract({**interpretation,
        'requested_fields': sorted(requested), 'semantic_contract': _turn_semantic_contract(state)}))


def _pending_action_followup_requested(state: AgentSessionState, requested: set[str]) -> bool:
    from AI.processors.observation_context import pending_action_read_contract
    interpretation = (state.active_entities or {}).get("turn_interpretation") or {}
    return bool((state.pending_actions or state.active_pending_action_id or state.status == "pending_approval")
                and pending_action_read_contract({**interpretation, "requested_fields": sorted(requested),
                                                  "semantic_contract": _turn_semantic_contract(state)}))


def _verified_export_followup_requested(state: AgentSessionState, requested: set[str]) -> bool:
    from AI.processors.semantic_contracts import report_delivery_read_contract

    interpretation = (state.active_entities or {}).get("turn_interpretation") or {}
    contract = _turn_semantic_contract(state)
    if (state.status == "complete" and not state.active_pending_action()
            and interpretation.get("mode") in {"act", "correct"}
            and interpretation.get("request_shape") == "artifact_report"):
        # The requested tables belong in the delivered workbook. An exact
        # approved source projection and native readback prove that delivery;
        # the chat receipt need not repeat every product row as a fresh read.
        from AI.processors.observation_context import verified_export_report_receipts
        if verified_export_report_receipts(state):
            return True
    return bool(
        report_delivery_read_contract({**interpretation, "requested_fields": sorted(requested),
                                       "direct_output_fields": [field for field in interpretation.get('direct_output_fields') or []
                                                                if field in requested],
                                       "semantic_contract": contract})
        and not state.active_pending_action()
    )


def project_fallback_response(
    state: AgentSessionState,
    fallback: str,
) -> str:
    requested = requested_response_fields(state)
    if _pending_report_followup_requested(state, requested):
        from AI.processors.observation_context import verified_pending_report_answer
        return verified_pending_report_answer(state)
    stock_detail = _stock_detail_answer(state, requested)
    if stock_detail:
        fallback = "\n".join(part for part in (fallback, stock_detail) if part)
    if _pending_action_followup_requested(state, requested):
        from AI.processors.observation_context import verified_pending_action_answer
        return verified_pending_action_answer(state)
    if _verified_export_followup_requested(state, requested):
        from AI.processors.observation_context import verified_export_report_answer
        return verified_export_report_answer(state)
    account_population = _registered_account_population(state)
    if account_population and state.active_domain == "marketplaces":
        count = account_population["count"]
        total = account_population["total_matching"]
        if account_population["complete"]:
            if count == 0:
                return "Kayıtlı mağaza bulunamadı."
            parts = [f"Kayıtlı {count} mağaza var."]
            if "store" in requested or "scope" in requested:
                parts.append(_scope_projection(state))
            if count == 1:
                parts.append("Kayıtlı başka mağaza yok.")
            return " ".join(parts)
        scope_label = (
            "Arama eşleşmesi" if account_population["scope"] == "matching_accounts"
            else "Kayıtlı hesap okuması"
        )
        parts = [f"{scope_label}: {count} mağaza gösteriliyor; toplam eşleşme {total}."]
        if "store" in requested or "scope" in requested:
            parts.append(_scope_projection(state))
        parts.append("Bu liste tüm kayıtlı mağazaları doğrulamıyor.")
        return " ".join(parts)
    row_projection = _order_row_projection_requested(
        state,
        requested,
    )
    return_row_projection = _return_row_projection_requested(
        state,
        requested,
    )
    full_context = bool(_full_order_context_rows(state))
    specialized_context = bool(
        requested.intersection(
            {
                "item",
                "sku",
                "barcode",
                "quantity",
                "cargo",
                "tracking_number",
                "returns",
                "amount",
                "currency",
            }
        )
    )
    if "calculation" in requested:
        calculation_projection = _derived_calculation_projection(state)
        direct_requested = _direct_projection_fields(state)
        general_summary = _general_broad_summary_requested(state)
        if general_summary:
            # A deferred comparison can coexist with a typed broad summary.
            # It must not collapse every other requested output into the one
            # arithmetic result, as an explicitly derived scalar contract may.
            direct_requested.update(requested - {"calculation"})
        if not direct_requested:
            return calculation_projection

        # Reuse the ordinary authoritative projection path for the independently
        # requested base outputs, then append the verified Core calculation.
        # The cloned state prevents recursion and keeps the original typed task
        # immutable for later response verification/audit.
        direct_state = AgentSessionState.from_dict(state.to_dict())
        direct_active = dict(direct_state.active_entities or {})
        direct_interpretation = dict(
            direct_active.get("turn_interpretation") or {}
        )
        direct_contract = dict(
            direct_interpretation.get("semantic_contract") or {}
        )
        direct_fields = sorted(direct_requested)
        direct_interpretation["requested_fields"] = list(direct_fields)
        direct_interpretation["direct_output_fields"] = []
        direct_contract["projection"] = list(direct_fields)
        direct_contract.pop("direct_projection", None)
        direct_contract.pop("derived_calculation", None)
        direct_contract.pop("derived_calculations", None)
        direct_contract.pop("calculation_count", None)
        direct_dimensions = set(direct_fields).intersection(
            {"count", "status", "amount", "risk", "ratio"}
        )
        direct_contract["metric"] = (
            "summary"
            if len(direct_dimensions) >= 2
            else {
                "count": "count",
                "status": "status",
                "amount": "amount",
                "ratio": "ratio",
            }.get(next(iter(direct_dimensions), ""), "summary")
        )
        direct_interpretation["semantic_contract"] = direct_contract
        direct_active["turn_interpretation"] = direct_interpretation
        direct_active["_response_projection_direct_only"] = not general_summary
        direct_state.active_entities = direct_active
        direct_projection = project_fallback_response(direct_state, fallback)
        return "\n\n".join(
            value
            for value in (direct_projection, calculation_projection)
            if _text(value)
        )
    contextual_item_fields = requested.intersection(
        {
            "item_sales_quantity",
            "item_sales_order_count",
            "item_sales_amount",
        }
    )
    if len(contextual_item_fields) >= 2:
        quantity = (
            _focused_item_sales_quantity(state)
            if "item_sales_quantity" in contextual_item_fields
            else {}
        )
        order_count = (
            _focused_item_sales_order_count(state)
            if "item_sales_order_count" in contextual_item_fields
            else {}
        )
        amount = (
            _focused_item_sales_amount(state)
            if "item_sales_amount" in contextual_item_fields
            else {}
        )
        focused_rows = [
            value for value in (quantity, order_count, amount) if value
        ]
        product_names = {
            _text(value.get("product_name"))
            for value in focused_rows
            if _text(value.get("product_name"))
        }
        if len(focused_rows) != len(contextual_item_fields) or len(product_names) != 1:
            return (
                "Secili urunun istenen satis metrikleri authoritative sonuc "
                "icinde birlikte dogrulanamadi."
            )
        product_name = next(iter(product_names))
        period = _human_period_scope(focused_rows[0].get("period"))
        parts = [f"{period} {product_name}".strip()]
        if quantity:
            parts.append(
                f"toplam satilan adet {int(quantity.get('quantity') or 0)}"
            )
        if order_count:
            parts.append(
                "yer aldigi farkli siparis sayisi "
                f"{int(order_count.get('order_count') or 0)}"
            )
        if amount:
            amount_text = ", ".join(
                " ".join(
                    value
                    for value in (
                        _text(row.get("amount")),
                        _text(row.get("currency")),
                    )
                    if value
                )
                for row in list(amount.get("amounts") or [])
            )
            parts.append(f"toplam brut satis tutari {amount_text}")
        return "; ".join(parts) + "."
    if "item_sales_amount" in requested:
        focused = _focused_item_sales_amount(state)
        if not focused:
            return (
                "Secili urunun toplam brut satis tutari authoritative sonuc "
                "icinde bulunamadi."
            )
        period = _human_period_scope(focused.get("period"))
        scope_text = f"{period} " if period else ""
        amount_text = ", ".join(
            f"{_text(row.get('amount'))} {_text(row.get('currency'))}"
            for row in list(focused.get("amounts") or [])
        )
        return (
            f"{scope_text}{_text(focused.get('product_name'))}: toplam "
            f"brut satis tutari {amount_text}."
        )
    if "item_sales_order_count" in requested:
        focused = _focused_item_sales_order_count(state)
        if not focused:
            return (
                "Secili urunun satildigi farkli siparis sayisi authoritative "
                "sonuc icinde bulunamadi."
            )
        period = _human_period_scope(focused.get("period"))
        scope_text = f"{period} " if period else ""
        return (
            f"{scope_text}{_text(focused.get('product_name'))}: "
            f"{int(focused.get('order_count') or 0)} farkli sipariste satilmis."
        )
    if "item_sales_quantity" in requested:
        focused = _focused_item_sales_quantity(state)
        if not focused:
            return (
                "Secili urunun toplam satis adedi authoritative sonuc "
                "icinde bulunamadi."
            )
        period = _human_period_scope(focused.get("period"))
        scope_text = f"{period} " if period else ""
        return (
            f"{scope_text}{_text(focused.get('product_name'))}: toplam "
            f"{int(focused.get('quantity') or 0)} adet satilmis."
        )
    if "ratio" in requested:
        ratio_parts = [_status_ratio_projection(state)]
        if "store" in requested:
            ratio_parts.append(_store_projection(state))
        if "scope" in requested:
            ratio_parts.append(_scope_projection(state))
        return " ".join(value for value in ratio_parts if _text(value))
    if full_context and specialized_context:
        if row_projection and _typed_order_list(state) and requested <= (
            _ORDER_ROW_DETAIL_FIELDS | {"item", "sku", "barcode", "quantity", "order_number", "count", "scope", "store", "currency"}
        ):
            return "\n".join(value for value in (
                _order_rows_text_projection(state, requested),
                _scope_projection(state) if "scope" in requested else "",
                _store_projection(state) if "store" in requested else "",
            ) if value)
        context_requested = requested.intersection(
            {
                "item",
                "sku",
                "barcode",
                "quantity",
                "cargo",
                "tracking_number",
                "returns",
                "amount",
                "currency",
                "status",
            }
        )
        context_projection = _full_order_context_projection(
            state,
            context_requested,
        )
        if row_projection:
            return "\n\n".join(
                value
                for value in (
                    _order_rows_text_projection(state, requested),
                    context_projection,
                )
                if _text(value)
            )
        return context_projection
    parts: list[str] = [stock_detail] if stock_detail else []
    if row_projection:
        parts.append(_order_rows_text_projection(state, requested))
    if return_row_projection:
        parts.append(_return_rows_text_projection(state, requested))
    if "count" in requested and not return_row_projection:
        count_answer = _count_projection(state)
        if count_answer:
            parts.append(count_answer)
    if "store" in requested:
        parts.append(_store_projection(state))
    if "scope" in requested:
        parts.append(_scope_projection(state))
    if (
        "order_number" in requested
        and not row_projection
        and not return_row_projection
    ):
        parts.append(_order_number_projection(state))
    if "claim_id" in requested and not return_row_projection:
        parts.append(
            _claim_projection(
                state,
                include_status="status" in requested,
            )
        )
    if "reason" in requested and not return_row_projection:
        parts.append(_cancellation_reason_projection(state))
    if (
        "item_sales_rows" in requested
        and not (
            _aggregate_analysis_requested(state)
            and _aggregate_item_indicators_available(state)
            and ORDER_ITEM_SALES_REPORT_METRIC
            not in _order_metric_requirements(state)
        )
    ):
        parts.append(_item_sales_report_projection(state))
    if (
        "status" in requested
        and "claim_id" not in requested
        and not row_projection
        and not return_row_projection
    ):
        parts.append(
            _status_projection(
                state,
                include_order_number="order_number" in requested,
            )
        )
    if "amount" in requested and not row_projection:
        parts.append(_amount_projection(state))
    grouped_sales = grouped_projection(_turn_semantic_contract(state))
    if "currency" in requested and not (
        "item_sales_rows" in requested
        and grouped_sales
        and "currency" in grouped_sales["fields"]
    ):
        parts.append(_currency_projection(state))
    analysis_projection = _aggregate_analysis_projection(state)
    if analysis_projection:
        parts.append(analysis_projection)
    if (
        "risk" in requested
        and _aggregate_analysis_indicators(state).get("fulfillment_risk_count")
        is None
    ):
        parts.append(_risk_projection(state))
    if "cargo_options" in requested:
        parts.append(_cargo_options_projection(state))
    if parts and requested.issubset(
        {
            "count",
            "item",
            "scope",
            "store",
            "status",
            "order_number",
            "claim_id",
            "item_sales_rows",
            "amount",
            "currency",
            "risk",
            "ratio",
            "cargo_options",
            "date",
            "customer_name",
            "quantity",
            "sku",
            "barcode",
            "cargo",
            "tracking_number",
            "package_id",
            "item_count",
            "reason",
        }
    ):
        return " ".join(dict.fromkeys(parts))
    scrubbed = _scrub_unrequested_values(fallback, state, requested)
    sources = web_evidence_projection(state)
    if sources and requested.intersection({"web_sources", "research_findings"}):
        findings: list[str] = []
        for row in sources:
            if row.get("prompt_injection_detected"):
                findings.append(
                    f"- {_text(row.get('title'))}: içerikte prompt-injection sinyali görüldü; sayfa metni bulgu üretiminde kullanılmadı."
                )
                continue
            claims = list(row.get("supported_claims") or [])
            excerpt = _text(row.get("evidence_excerpt"))
            detail = "; ".join(claims[:3]) or excerpt[:420]
            if detail:
                findings.append(f"- {_text(row.get('title'))}: {detail}")
        research_summary = "\n".join(
            [
                f"Web araştırması tamamlandı; {len(sources)} kaynak açılıp incelendi.",
                *( ["İlgili bulgular:", *findings] if findings else [] ),
            ]
        )
        comparisons: list[dict[str, Any]] = []
        for step in state.completed_steps:
            tool_result = (
                dict((step.result_data or {}).get("tool_result") or {})
                if isinstance((step.result_data or {}).get("tool_result"), dict)
                else {}
            )
            if _text(tool_result.get("tool")) == "web.compare_sources":
                comparisons.append(tool_result)
        if comparisons:
            latest = comparisons[-1]
            status = _text(latest.get("status"))
            independent = int(latest.get("independent_source_count") or 0)
            if status != "supported":
                research_summary += (
                    "\nDoğrulama seviyesi: kısmi. "
                    f"Bağımsız kaynak domaini: {independent}. "
                    "Bu sonuç tam ve bağımsız bir doğrulama olarak sunulmadı."
                )
        scrubbed = research_summary
    if not scrubbed:
        from AI.processors.observation_context import verified_pending_report_answer
        scrubbed = verified_pending_report_answer(state)
    answer = scrubbed or "Kaynak sonucu hazır; istenmeyen özel alanlar gizlendi."
    if "scope" in requested and _account_scope_rows(state):
        scope = _scope_projection(state)
        if _normalized(scope) not in _normalized(answer):
            answer = "\n\n".join((answer, scope))
    return append_verified_web_citations(answer, state)


def _cross_business_read_evidence(state: AgentSessionState) -> dict[str, Any]:
    requested_domains = {
        _text(value).casefold()
        for value in list((state.active_entities or {}).get("business_read_domains") or [])
    }
    domains = set(requested_domains)
    # General tasks discover their operations rather than selecting a business
    # domain up front. Their actual completed read receipts are evidence for the
    # final summary; this projection never authorizes a read or imports an old
    # receipt from conversation history.
    observed_results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if _general_broad_business_read_requested(state):
        operation_domains = {
            "orders.summary": "orders",
            "stock.inventory_overview": "stock",
            "finance.cashflow_summary": "finance",
        }
        for step in state.completed_steps:
            if step.status != "completed" or step.verification_status not in {"observed", "verified"}:
                continue
            operation_ids = {_text(value) for value in list(step.tool_names or [])}
            if len(operation_ids) != 1:
                continue
            operation_id = next(iter(operation_ids))
            domain = operation_domains.get(operation_id)
            result = dict(step.result_data or {}).get("tool_result")
            if (not domain or _text(step.operation_domain).casefold() != domain
                    or not isinstance(result, dict) or _text(result.get("tool")) != operation_id):
                continue
            observed_results[domain].append(dict(result))
        domains.update(observed_results)
    if len(domains.intersection({"orders", "stock", "finance"})) < 2:
        return {}
    evidence: dict[str, Any] = {"requested_domains": sorted(requested_domains)}
    if observed_results:
        evidence.update(observed_domains=sorted(observed_results), projection_basis="current_task_observations")
    orders = (observed_results["orders"][-1] if observed_results.get("orders")
              else _operation_tool_result(state, "orders.summary") if "orders" in requested_domains else {})
    if orders and "orders" in domains:
        evidence["orders"] = {
            "total_orders": orders.get("total_orders"),
            "period": orders.get("period"),
            "account_scopes": list(orders.get("account_scopes") or []),
            "sales_velocity_available": False,
        }
        if observed_results.get("orders"):
            evidence["orders"]["summaries"] = [{
                key: result[key] for key in (
                    "total_orders", "estimated_revenue", "currency", "revenue_by_currency",
                    "period", "period_label", "start_ms", "end_ms", "account_scopes",
                    "source_revision", "source_snapshot_hash",
                ) if key in result
            } for result in observed_results["orders"]]
    stock = (observed_results["stock"][-1] if observed_results.get("stock")
             else _operation_tool_result(state, "stock.inventory_overview") if "stock" in requested_domains else {})
    if stock and "stock" in domains:
        evidence["stock"] = {
            "active_items": stock.get("active_items"),
            "total_balance": stock.get("total_balance"),
            "balance_by_unit": list(stock.get("balance_by_unit") or []),
            "stock_value_by_currency": list(stock.get("stock_value_by_currency") or []),
            "stock_valuation_complete": stock.get("stock_valuation_complete"),
            "valuation_missing_items": stock.get("valuation_missing_items"),
            "scope": "all_active_stock_items; no account join established",
        }
    finance = (observed_results["finance"][-1] if observed_results.get("finance")
               else _operation_tool_result(state, "finance.cashflow_summary") if "finance" in requested_domains else {})
    if finance and "finance" in domains:
        evidence["finance"] = {
            "period": finance.get("period"),
            "currency_totals": list(finance.get("currency_totals") or []),
            "transaction_type_counts": dict(finance.get("transaction_type_counts") or {}),
            "scope": "financial movements; no company/account join or bank balance established",
        }
        if observed_results.get("finance"):
            evidence["finance"]["summaries"] = [{
                key: result[key] for key in (
                    "period", "period_label", "start_ms", "end_ms", "start_date", "end_date",
                    "currency_totals", "transaction_type_counts", "source_revision", "source_snapshot_hash",
                ) if key in result
            } for result in observed_results["finance"]]
    return evidence


def response_evidence_projection(state: AgentSessionState) -> dict[str, Any]:
    from AI.processors.observation_analysis_evidence import verified_observation_tables
    requested = requested_response_fields(state)
    evidence = _collect_evidence(state)
    scalar, operation, scalar_data = _first_scalar(state)
    row_projection = _order_row_projection_requested(
        state,
        requested,
    )
    return_row_projection = _return_row_projection_requested(
        state,
        requested,
    )
    return {
        "verified_table_analyses": verified_observation_tables(state),
        "stock_item_rows": _stock_detail_rows(state),
        "requested_fields": sorted(requested),
        "cross_business_read": _cross_business_read_evidence(state),
        "registered_account_population": _registered_account_population(state),
        "grouped_projection": grouped_projection(_turn_semantic_contract(state)),
        "grouped_rows": [
            {field: row.get(field) for field in grouped_projection(_turn_semantic_contract(state))["fields"]}
            for row in _item_sales_rows_for_response(state)[0]
        ] if grouped_projection(_turn_semantic_contract(state)) else [],
        "count": scalar if "count" in requested else None,
        "count_operation": operation if "count" in requested else "",
        "period_scope": (
            _human_period_scope(scalar_data.get("period_label"))
            if "date" in requested
            else ""
        ),
        "stores": sorted(evidence["stores"]) if "store" in requested else [],
        "account_scopes": _account_scope_rows(state) if "scope" in requested else [],
        "statuses": sorted(evidence["statuses"]) if "status" in requested else [],
        "amounts": (
            _response_amount_values(
                state,
                prefer_order_rows=row_projection,
            )
            if "amount" in requested
            else []
        ),
        "currencies": (
            _currency_values(state) if "currency" in requested else []
        ),
        "risk_counts": _risk_counts(state) if "risk" in requested else [],
        "risk_evidence": dict((
            _operation_tool_result(state, "orders.fulfillment_risk_count")
            or _operation_tool_result(state, "orders.fulfillment_risk")
        ).get("risk_evidence") or {}) if "risk" in requested else {},
        "focused_status_ratio": (
            _focused_order_status_ratio(state) if "ratio" in requested else {}
        ),
        "verified_calculation": (
            verified_derived_calculation(state)
            if "calculation" in requested
            else {}
        ),
        "verified_calculations": (
            verified_derived_calculations(state)
            if "calculation" in requested
            else []
        ),
        "focused_item_sales_quantity": (
            _focused_item_sales_quantity(state)
            if "item_sales_quantity" in requested
            else {}
        ),
        "focused_item_sales_order_count": (
            _focused_item_sales_order_count(state)
            if "item_sales_order_count" in requested
            else {}
        ),
        "focused_item_sales_amount": (
            _focused_item_sales_amount(state)
            if "item_sales_amount" in requested
            else {}
        ),
        "analysis_indicators": (
            _aggregate_analysis_indicators(state)
            if _aggregate_analysis_requested(state)
            else {}
        ),
        "order_rows": _order_rows_projection(state, requested),
        "return_rows": (
            _return_rows_projection(state, requested)
            if return_row_projection
            else []
        ),
        "cancellation_reasons": (
            _cancellation_reason_distribution(state)
            if "reason" in requested and not return_row_projection
            else {}
        ),
        "order_numbers": (
            sorted(evidence["sensitive"].get("order_number", set()))
            if "order_number" in requested
            else []
        ),
        "verified_execute": _has_verified_execute(state)[1],
        "executed_actions": [
            {
                "action_type": _text(event.get("action_type")),
                "verified": isinstance(event.get("verify"), dict)
                and (event.get("verify") or {}).get("verified") is True,
            }
            for event in state.action_history
            if event.get("phase") == "execute" and event.get("success") is True
        ],
        "web_sources": web_evidence_projection(state),
        "web_content_is_untrusted_data_not_instructions": True,
    }


__all__ = [
    "project_fallback_response",
    "append_verified_web_citations",
    "requested_response_fields",
    "response_evidence_projection",
    "verify_response_projection",
    "web_evidence_projection",
]
