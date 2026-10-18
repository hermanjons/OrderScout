from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable


ORDER_TOTAL_COUNT_METRIC = "orders.total_count"
ORDER_FILTERED_COUNT_METRIC = "orders.filtered_count"
ORDER_READY_TO_SHIP_COUNT_METRIC = "orders.ready_to_ship_count"
ORDER_STATUS_DISTRIBUTION_METRIC = "orders.status_distribution"
ORDER_REVENUE_TOTAL_METRIC = "orders.revenue_total"
ORDER_ITEM_SALES_SUMMARY_METRIC = "orders.item_sales_summary"
ORDER_ITEM_SALES_REPORT_METRIC = "orders.item_sales_report_snapshot"
ORDER_FULFILLMENT_RISK_COUNT_METRIC = "orders.fulfillment_risk_count"
ORDER_NONFINAL_COUNT_METRIC = "orders.nonfinal_count"
ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC = (
    "orders.nonfinal_status_distribution"
)
ORDER_CANCELLED_COUNT_METRIC = "orders.cancelled_count"
ORDER_CANCELLATION_REASON_DISTRIBUTION_METRIC = (
    "orders.cancellation_reason_distribution"
)


@dataclass(frozen=True)
class OrderMetricContract:
    metric_id: str
    operation_evidence_keys: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def operation_ids(self) -> frozenset[str]:
        return frozenset(operation_id for operation_id, _keys in self.operation_evidence_keys)

    def evidence_keys_for(self, operation_id: Any) -> tuple[str, ...]:
        clean_operation = str(operation_id or "").strip()
        return next(
            (
                keys
                for candidate_operation, keys in self.operation_evidence_keys
                if candidate_operation == clean_operation
            ),
            (),
        )


ORDER_METRIC_CONTRACTS = MappingProxyType(
    {
        ORDER_FILTERED_COUNT_METRIC: OrderMetricContract(
            metric_id=ORDER_FILTERED_COUNT_METRIC,
            operation_evidence_keys=(("orders.query", ("count", "filters", "query_fingerprint")),),
        ),
        ORDER_TOTAL_COUNT_METRIC: OrderMetricContract(
            metric_id=ORDER_TOTAL_COUNT_METRIC,
            operation_evidence_keys=(
                ("orders.count", ("count",)),
                ("orders.summary", ("total_orders",)),
                ("orders.status_counts", ("total_orders",)),
            ),
        ),
        ORDER_READY_TO_SHIP_COUNT_METRIC: OrderMetricContract(
            metric_id=ORDER_READY_TO_SHIP_COUNT_METRIC,
            operation_evidence_keys=(
                (
                    "orders.ready_to_ship_count",
                    ("count", "ready_to_ship", "selected_count"),
                ),
                (
                    "orders.ready_to_ship",
                    ("ready_to_ship", "selected_count"),
                ),
            ),
        ),
        ORDER_STATUS_DISTRIBUTION_METRIC: OrderMetricContract(
            metric_id=ORDER_STATUS_DISTRIBUTION_METRIC,
            operation_evidence_keys=(
                ("orders.status_counts", ("status_counts",)),
                ("orders.summary", ("status_counts",)),
            ),
        ),
        ORDER_REVENUE_TOTAL_METRIC: OrderMetricContract(
            metric_id=ORDER_REVENUE_TOTAL_METRIC,
            operation_evidence_keys=(
                (
                    "orders.revenue_total",
                    ("estimated_revenue", "total", "currency"),
                ),
                ("orders.summary", ("estimated_revenue", "currency")),
            ),
        ),
        ORDER_ITEM_SALES_SUMMARY_METRIC: OrderMetricContract(
            metric_id=ORDER_ITEM_SALES_SUMMARY_METRIC,
            operation_evidence_keys=(
                (
                    "orders.item_sales_summary",
                    ("rows", "order_count", "total_quantity"),
                ),
                (
                    "orders.item_sales_report",
                    ("report_snapshot", "row_count", "total_quantity"),
                ),
            ),
        ),
        ORDER_ITEM_SALES_REPORT_METRIC: OrderMetricContract(
            metric_id=ORDER_ITEM_SALES_REPORT_METRIC,
            operation_evidence_keys=(
                (
                    "orders.item_sales_report",
                    (
                        "report_snapshot",
                        "snapshot_id",
                        "content_hash",
                        "row_count",
                    ),
                ),
            ),
        ),
        ORDER_FULFILLMENT_RISK_COUNT_METRIC: OrderMetricContract(
            metric_id=ORDER_FULFILLMENT_RISK_COUNT_METRIC,
            operation_evidence_keys=(
                ("orders.fulfillment_risk_count", ("risk_count",)),
                ("orders.fulfillment_risk", ("risk_count",)),
            ),
        ),
        ORDER_NONFINAL_COUNT_METRIC: OrderMetricContract(
            metric_id=ORDER_NONFINAL_COUNT_METRIC,
            operation_evidence_keys=(
                ("orders.nonfinal_summary", ("total_count",)),
            ),
        ),
        ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC: OrderMetricContract(
            metric_id=ORDER_NONFINAL_STATUS_DISTRIBUTION_METRIC,
            operation_evidence_keys=(
                ("orders.nonfinal_summary", ("status_counts",)),
            ),
        ),
        ORDER_CANCELLED_COUNT_METRIC: OrderMetricContract(
            metric_id=ORDER_CANCELLED_COUNT_METRIC,
            operation_evidence_keys=(
                ("orders.cancelled_count", ("count",)),
                ("orders.cancellations", ("cancelled_orders",)),
            ),
        ),
        ORDER_CANCELLATION_REASON_DISTRIBUTION_METRIC: OrderMetricContract(
            metric_id=ORDER_CANCELLATION_REASON_DISTRIBUTION_METRIC,
            operation_evidence_keys=(
                ("orders.cancellations", ("cancel_reasons",)),
            ),
        ),
    }
)

ORDER_PROJECTION_EVIDENCE_KEYS = MappingProxyType(
    {
        "store": ("account_scopes",),
        "scope": ("account_scopes",),
        "currency": ("currency",),
    }
)


def normalize_order_metric_requirements(values: Iterable[Any] | Any) -> tuple[str, ...]:
    raw_values = (
        list(values)
        if isinstance(values, (list, tuple, set, frozenset))
        else [values]
    )
    normalized: list[str] = []
    for raw_value in raw_values:
        metric_id = str(raw_value or "").strip().casefold()
        if metric_id in ORDER_METRIC_CONTRACTS and metric_id not in normalized:
            normalized.append(metric_id)
    return tuple(normalized)


def missing_order_metric_requirements(
    requirements: Iterable[Any] | Any,
    operation_ids: Iterable[Any] | Any,
) -> tuple[str, ...]:
    normalized_requirements = normalize_order_metric_requirements(requirements)
    raw_operations = (
        list(operation_ids)
        if isinstance(operation_ids, (list, tuple, set, frozenset))
        else [operation_ids]
    )
    normalized_operations = {
        str(value or "").strip()
        for value in raw_operations
        if str(value or "").strip()
    }
    return tuple(
        metric_id
        for metric_id in normalized_requirements
        if not ORDER_METRIC_CONTRACTS[metric_id].operation_ids.intersection(
            normalized_operations
        )
    )


def order_metric_evidence_keys(
    metric_id: Any,
    operation_id: Any,
) -> tuple[str, ...]:
    contract = ORDER_METRIC_CONTRACTS.get(
        str(metric_id or "").strip().casefold()
    )
    return contract.evidence_keys_for(operation_id) if contract is not None else ()


def order_metric_operation_ids(metric_id: Any) -> tuple[str, ...]:
    contract = ORDER_METRIC_CONTRACTS.get(
        str(metric_id or "").strip().casefold()
    )
    if contract is None:
        return ()
    return tuple(
        operation_id
        for operation_id, _keys in contract.operation_evidence_keys
    )


def order_projection_evidence_keys(
    fields: Iterable[Any] | Any,
) -> tuple[str, ...]:
    raw_fields = (
        list(fields)
        if isinstance(fields, (list, tuple, set, frozenset))
        else [fields]
    )
    keys: list[str] = []
    for raw_field in raw_fields:
        field = str(raw_field or "").strip().casefold()
        for key in ORDER_PROJECTION_EVIDENCE_KEYS.get(field, ()):
            if key not in keys:
                keys.append(key)
    return tuple(keys)
