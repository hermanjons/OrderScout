from __future__ import annotations

from typing import Any, Iterable
from AI.processors.grouped_projection import grouped_projection

from Orders.processors.agentic_metrics import (
    ORDER_CANCELLATION_REASON_DISTRIBUTION_METRIC,
    ORDER_ITEM_SALES_REPORT_METRIC,
    ORDER_ITEM_SALES_SUMMARY_METRIC,
    normalize_order_metric_requirements,
    order_metric_operation_ids,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def report_delivery_read_contract(interpretation: dict[str, Any] | None) -> bool:
    """Typed explanation of a recorded delivery, independent of user wording.

    This classifies the requested projection only. A caller must separately
    prove the exact completed report and approved export receipt; the model's
    contract cannot supply execution or current file-existence evidence.
    """
    if not isinstance(interpretation, dict):
        return False
    contract = interpretation.get("semantic_contract") or {}
    if not isinstance(contract, dict):
        return False
    values = interpretation.get("requested_fields") or []
    direct = interpretation.get("direct_output_fields") or []
    if not isinstance(values, list) or not isinstance(direct, list):
        return False
    fields = {_text(value).casefold() for value in [*values, *direct]}
    entities = {_text(value).casefold() for value in (
        interpretation.get("entity"), contract.get("entity"),
    )}
    return bool(
        interpretation.get("mode") == "inspect"
        and interpretation.get("intent_kind") == "data_read"
        and interpretation.get("operation_policy") == "existing_observations_only"
        and fields.intersection({"artifact", "action_result"})
        and fields.issubset({"artifact", "action_result", "count", "currency", "quantity", "unit", "date", "source",
                             "item_sales_rows", "amount", "status", "scope", "web_sources", "research_findings"})
        and entities.issubset({"", "none", "file", "artifact"})
        and not interpretation.get("requires_clarification")
        and not any(interpretation.get(key) or contract.get(key) for key in (
            "metric_requirements", "derived_calculation", "derived_calculations", "grouped_projection",
        ))
    )


def order_status_codes(semantic_contract: dict[str, Any] | None) -> tuple[str, ...]:
    """Exact, model-authored marketplace codes, distinct from business queues."""

    values = dict(semantic_contract or {}).get("status_codes")
    if not isinstance(values, list):
        return ()
    return tuple(dict.fromkeys(_text(value) for value in values if _text(value)))


def cancellation_reason_distribution_contract(
    semantic_contract: dict[str, Any] | None,
    *,
    requested_fields: Iterable[Any] = (),
) -> bool:
    """A cancelled-order reason aggregate is not an exact order-row list."""

    contract = dict(semantic_contract or {})
    fields = _read_projection_fields(contract, requested_fields)
    requirements = normalize_order_metric_requirements(
        contract.get("metric_requirements") or []
    )
    return bool(
        contract.get("entity") == "order"
        and {code.casefold() for code in order_status_codes(contract)} == {"cancelled"}
        and "reason" in fields
        and ORDER_CANCELLATION_REASON_DISTRIBUTION_METRIC in requirements
    )


def validate_orders_read_arguments(
    semantic_contract: dict[str, Any] | None,
    operation_id: str,
    arguments: dict[str, Any] | None,
) -> tuple[str, ...]:
    """Keep an exact status population intact at compile and execution boundaries."""

    contract = dict(semantic_contract or {})
    grouped = grouped_projection(contract)
    if grouped and operation_id in {"orders.item_sales_summary", "orders.item_sales_report"}:
        args = dict(arguments or {})
        if args.get("group_by", "product") != grouped["group_by"]:
            return ("grouped_projection_group_mismatch",)
        if int(args.get("limit") or 20) < grouped["limit"]:
            return ("grouped_projection_limit_insufficient",)
    codes = order_status_codes(contract)
    if not codes:
        return ()
    if (
        operation_id == "orders.cancellations"
        and cancellation_reason_distribution_contract(contract)
    ):
        # This Orders-owned aggregate filters to cancelled orders internally
        # and returns the complete reason counts even if its row sample is bounded.
        return ()
    if operation_id not in {"orders.query", "orders.full_context"}:
        return ("exact_status_read_operation_mismatch",)
    args = dict(arguments or {})
    filters = dict(args.get("filters") or {})
    actual = (
        [filters["status"]]
        if filters.get("status")
        else list(filters.get("statuses") or [])
    )
    problems: list[str] = []
    if {_text(value) for value in actual} != set(codes):
        problems.append("exact_status_filter_mismatch")
    if (
        operation_id == "orders.query"
        and _text(contract.get("metric")) in {"list", "detail"}
        and _text(args.get("mode") or "list") not in {"list", "top"}
    ):
        problems.append("exact_status_record_projection_missing")
    return tuple(problems)


def expected_business_read_operations(semantic_contract: dict[str, Any] | None) -> frozenset[str]:
    contract = dict(semantic_contract or {})
    if contract.get("entity") != "marketplace_account":
        return frozenset()
    allowed = {"marketplaces.account_lookup"}
    if contract.get("metric") in {"count", "summary"}:
        allowed.update({"marketplaces.account_count", "marketplaces.summary"})
    return frozenset(allowed)


def validate_business_read_arguments(
    semantic_contract: dict[str, Any] | None,
    operation_id: str,
    arguments: dict[str, Any] | None,
) -> tuple[str, ...]:
    contract = dict(semantic_contract or {})
    from AI.processors.child_task_runtime import current_child_policy, bind_child_read_arguments
    if current_child_policy() is not None:
        from AI.processors.tools import available_tools
        tool = available_tools().get(operation_id)
        if tool is None:
            return ("child_operation_outside_read_scope",)
        _, problems = bind_child_read_arguments(tool, dict(arguments or {}))
        if problems:
            return tuple(problems)
    allowed = expected_business_read_operations(contract)
    if allowed and operation_id not in allowed:
        return ("registered_account_population_source_mismatch",)
    return validate_orders_read_arguments(contract, operation_id, arguments)


def validate_orders_fetch_arguments(
    semantic_contract: dict[str, Any] | None,
    arguments: dict[str, Any] | None,
) -> tuple[str, ...]:
    """Validate optional sync dimensions against the typed action intent."""

    contract = dict(semantic_contract or {})
    if _text(contract.get("action_intent")).casefold() != "data_refresh":
        return ()
    expected_returns = contract.get("include_returns")
    if not isinstance(expected_returns, bool):
        return ()
    actual_returns = bool(dict(arguments or {}).get("fetch_returns"))
    if actual_returns and not expected_returns:
        return ("unrequested_return_fetch_expansion",)
    if expected_returns and not actual_returns:
        return ("requested_return_fetch_missing",)
    return ()


def _read_projection_fields(
    contract: dict[str, Any], requested_fields: Iterable[Any]
) -> set[str]:
    projection = contract.get("projection")
    values = (
        list(projection)
        if isinstance(projection, (list, tuple, set))
        else _text(projection).split()
    )
    return {
        _text(value).casefold() for value in [*requested_fields, *values]
        if _text(value)
    }


def business_read_plan_constraints(
    semantic_contract: dict[str, Any] | None,
    *,
    requested_fields: Iterable[Any] = (),
) -> dict[str, Any]:
    """Expose the verifier's evidence requirements before the model plans.

    These are constraints on evidence, not a generated plan. Operation order,
    arguments and dependencies remain model-authored in initial and repair turns.
    """
    contract = dict(semantic_contract or {})
    fields = _read_projection_fields(contract, requested_fields)
    operations = (
        expected_order_read_operations(contract, requested_fields=fields)
        if contract.get("entity") in {"order", "return_claim"}
        else expected_business_read_operations(contract)
    )
    if not operations:
        return {}
    constraints: dict[str, Any] = {
        "entity": contract.get("entity"),
        "operation_alternatives": sorted(operations),
        "record_scope": contract.get("record_scope"),
        "projection": sorted(fields),
    }
    codes = order_status_codes(contract)
    if codes and cancellation_reason_distribution_contract(contract, requested_fields=fields):
        constraints["implicit_status_population"] = "cancelled_orders"
    elif codes:
        constraints["exact_status_filter"] = {
            "codes": list(codes),
            "argument_alternatives": ["filters.status", "filters.statuses"],
            "comparison": "exact_set",
        }
    return constraints


def expected_order_read_operations(
    semantic_contract: dict[str, Any] | None,
    *,
    requested_fields: Iterable[Any] = (),
) -> frozenset[str]:
    """Return the atomic read operations allowed by one typed Orders contract.

    This is the shared semantic boundary used by both plan compilation and
    pre-execution verification.  Keeping the mapping here prevents the planner
    from accepting one operation shape (for example a count) while the runtime
    later enforces another (for example an exact list).
    """

    contract = dict(semantic_contract or {})
    fields = _read_projection_fields(contract, requested_fields)
    read_key = (
        _text(contract.get("entity")).casefold(),
        _text(contract.get("metric")).casefold(),
        _text(contract.get("status_scope")).casefold(),
    )
    if cancellation_reason_distribution_contract(contract, requested_fields=fields):
        return frozenset({"orders.cancellations"})
    if read_key[0] == "order" and order_status_codes(contract):
        rich_fields = {"item", "sku", "barcode", "quantity", "returns"}
        return frozenset(
            {"orders.full_context"}
            if read_key[1] in {"list", "detail"} and rich_fields.intersection(fields)
            else {"orders.query"}
        )
    record_scope = _text(contract.get("record_scope")).casefold()
    expected = {
        ("order", "count", "ready_to_ship"): {
            "orders.ready_to_ship_count",
        },
        ("order", "count", "all"): {"orders.count"},
        ("order", "count", "nonfinal"): {
            "orders.nonfinal_summary",
        },
        ("order", "list", "nonfinal"): {
            "orders.nonfinal_summary",
        },
        ("order", "summary", "nonfinal"): {
            "orders.nonfinal_summary",
        },
        ("order", "item_quantity_total", "all"): {
            "orders.item_sales_summary",
        },
        ("order", "item_order_count", "all"): {
            "orders.item_sales_summary",
        },
        ("order", "item_gross_amount", "all"): {
            "orders.item_sales_summary",
        },
        ("order", "status", "nonfinal"): {
            "orders.nonfinal_summary",
        },
        ("order", "list", "ready_to_ship"): {
            "orders.ready_to_ship",
        },
        ("return_claim", "count", "waiting_action"): {
            "returns.waiting_action_count",
        },
        ("return_claim", "list", "waiting_action"): {
            "returns.query",
        },
        ("return_claim", "list", "all"): {
            "returns.query",
        },
    }.get(read_key, set())
    if "risk" in fields:
        expected = {
            "orders.fulfillment_risk",
            "orders.fulfillment_risk_count",
            "orders.shipping_deadline_analysis",
        }
    # A carried population/status scope describes which records an exact
    # follow-up came from; it must not demote a record-detail request back to
    # the aggregate operation that originally produced the population.  The
    # exact identity scope and requested projection are the stronger semantic
    # signals here.  This keeps ordinal/deictic follow-ups model-independent:
    # any provider may phrase the plan differently, but rich fields for an
    # exact order always resolve through the canonical full-context read.
    order_detail_projection_fields = {
        "address",
        "barcode",
        "cargo",
        "customer_name",
        "email",
        "item",
        "quantity",
        "package",
        "phone",
        "product",
        "returns",
        "sku",
        "tracking_number",
    }
    if (
        read_key[0] == "order"
        and record_scope in {"exact_ids", "active_selection"}
        and bool(order_detail_projection_fields & fields)
    ):
        expected = {"orders.full_context"}
    item_sales_projection_fields = {
        "item_sales_rows",
        "item_sales_quantity",
        "item_sales_order_count",
        "item_sales_amount",
    }
    if read_key[0] == "order" and bool(item_sales_projection_fields & fields):
        # Product-sales rows are aggregate evidence even though each row also
        # has an ``item`` label.  That label must not make a provider-emitted
        # ``record_list / active_selection`` shape look like an exact order
        # detail read.  The Orders metric registry remains the sole owner of
        # which atomic operations can satisfy the typed aggregate contract.
        item_sales_requirements = tuple(
            metric_id
            for metric_id in normalize_order_metric_requirements(
                contract.get("metric_requirements") or []
            )
            if metric_id
            in {
                ORDER_ITEM_SALES_SUMMARY_METRIC,
                ORDER_ITEM_SALES_REPORT_METRIC,
            }
        )
        if not item_sales_requirements:
            item_sales_requirements = (ORDER_ITEM_SALES_SUMMARY_METRIC,)
        expected = {
            operation_id
            for metric_id in item_sales_requirements
            for operation_id in order_metric_operation_ids(metric_id)
        }
    order_row_projection_fields = {
        "order_number",
        "status",
        "customer_name",
        "date",
        "amount",
        "tracking_number",
        "cargo",
    }
    cargo_options_is_primary = bool(
        "cargo_options" in fields
        and not (
            read_key[:2] == ("order", "list")
            and bool(order_row_projection_fields & fields)
        )
    )
    if cargo_options_is_primary:
        expected = {"orders.cargo_provider_options"}
    if contract.get("contextual_public_product_web_research_required") is True:
        # A deictic Orders -> public-web goal must first cross the privacy
        # boundary through the Orders-owned public identity operation.  A
        # generic full-context read is neither safe search input nor a
        # substitute for that canonical projection.
        expected = {"orders.product_public_identities"}
    return frozenset(expected)
