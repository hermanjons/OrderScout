"""Bounded arithmetic over exact runtime observations, with source receipts.

The runtime authorizes and binds observations. This tool resolves numeric
operands from those observations; models supply expressions and paths only.
Currency and quantity units come from the observed schema, never model values.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping

from AI.processors.observation_projection import (
    normalize_projection_value, observed_entity_scope, observed_source_payload, source_path_value, source_projection_hash,
)
from Core.processors.verified_calculations import (
    CALCULATION_OPERATORS, COMPARISON_OPERATORS,
    evaluate_verified_calculation, evaluate_verified_comparison,
)
from Feedback.processors.pipeline import Result


_REFERENCE_SCHEMA = {
    "type": "object", "properties": {
        "source_id": {"type": "string", "minLength": 1},
        "path": {"type": "string", "minLength": 1,
                 "description": "Exact observed NUMERIC field path. Both calculations and comparisons require numeric values. Currency/unit labels are metadata, not arithmetic operands; do not compare strings. Quantity needs an observed unit; an unavailable unit cannot be invented."},
    }, "required": ["source_id", "path"], "additionalProperties": False,
}
OBSERVATION_ANALYSIS_SCHEMA = {
    "type": "object", "properties": {
        "sources": {"type": "array", "minItems": 1, "maxItems": 64, "items": {
            "type": "object", "properties": {
                "source_id": {"type": "string", "minLength": 1},
                "source_step_id": {"type": "string", "minLength": 1},
                "operation_id": {"type": "string", "minLength": 1},
                "result": {"type": "object", "description": "Bind the actual completed source tool_result via $from_step/path; never invent a result body or copy guessed values."},
            }, "required": ["source_id", "source_step_id", "operation_id", "result"],
            "additionalProperties": False,
        }},
        "calculations": {"type": "array", "maxItems": 32, "items": {
            "type": "object", "properties": {
                "calculation_id": {"type": "string", "minLength": 1},
                "operator": {"type": "string", "enum": sorted(CALCULATION_OPERATORS),
                             "description": "percentage means first operand / second operand * 100, not percentage change. For change percentage, first subtract the baseline and then divide that observed difference by the baseline."},
                "operands": {"type": "array", "minItems": 2, "maxItems": 16, "items": _REFERENCE_SCHEMA},
                "precision": {"type": "integer", "minimum": 0, "maximum": 6},
                "result_unit": {"type": "string", "enum": ["native", "ratio", "percentage"],
                                "description": "A same-unit divide may be displayed as ratio or percentage. A percentage operator already produces percent and may explicitly repeat result_unit=percentage."},
            }, "required": ["calculation_id", "operator", "operands"], "additionalProperties": False,
        }},
        "comparisons": {"type": "array", "maxItems": 32, "items": {
            "type": "object", "properties": {
                "comparison_id": {"type": "string", "minLength": 1},
                "operator": {"type": "string", "enum": sorted(COMPARISON_OPERATORS)},
                "left": _REFERENCE_SCHEMA, "right": _REFERENCE_SCHEMA,
            }, "required": ["comparison_id", "operator", "left", "right"], "additionalProperties": False,
        }},
    }, "required": ["sources"], "additionalProperties": False,
}
OBSERVATION_ANALYSIS_OUTPUT_SCHEMA = {
    "type": "object", "properties": {
        "verified": {"type": "boolean"}, "arithmetic_only": {"type": "boolean"},
        "evidence_hash": {"type": "string"},
        "verified_calculations": {"type": "array", "items": {"type": "object"}},
        "verified_comparisons": {"type": "array", "items": {"type": "object"}},
        "source_receipts": {"type": "array", "items": {"type": "object"}},
        "operand_receipts": {"type": "array", "items": {"type": "object"}},
    }, "required": ["verified", "evidence_hash", "verified_calculations", "verified_comparisons", "source_receipts"],
}

_MONEY_FIELDS = frozenset({
    "total", "estimated_revenue", "revenue", "item_gross_amount", "gross_amount",
    "total_gross_amount", "amount", "net_amount", "marketplace_net", "manual_in",
    "manual_out", "combined_net", "stock_value", "avg_cost", "price", "unit_price",
    "shipping_cost", "total_cost", "total_revenue", "profit", "expense", "income",
})
_UNIT_FIELDS = {"total_orders": "order", "cancelled_orders": "order", "order_count": "order", "matched_order_count": "order",
                "population_order_count": "order", "total_items": "item", "active_items": "item",
                "product_count": "product", "total_products": "product"}
_SCOPE_KEYS = (
    "account_ids", "account_id", "api_account_ids", "api_account_id", "marketplace_account_ids", "marketplace_account_id",
    "account_scopes", "environment_by_account", "environment", "company_id", "warehouse_id",
    "selected_order_ids", "selection_id",
)
_PERIOD_KEYS = ("period", "start_ms", "end_ms", "start_date_ms", "end_date_ms", "start_date", "end_date")


def _tokens(path: str) -> list[str]:
    return path.split(".") if not path.startswith("/") else [
        part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")
    ]


def _unit(result: Mapping[str, Any], path: str, parents: list[Mapping[str, Any]], operation_id: str) -> str:
    tokens = _tokens(path)
    leaf = tokens[-1]
    # Currency maps carry their unit in the observed map key.
    if len(tokens) > 1 and tokens[-2].endswith("by_currency"):
        if re.fullmatch(r"[A-Z]{3}", leaf) and leaf != "XXX":
            return leaf
        raise ValueError("analysis_currency_unknown")
    if leaf in {"result", "result_value"} and result.get("verified") is True:
        for parent in reversed(parents):
            if parent.get("verified") is True and parent.get("unit"):
                return str(parent["unit"])
    if leaf == "value" and result.get("tool") == "analysis.table" and result.get("verified") is True:
        for parent in reversed(parents):
            if parent.get("unit_basis") in {"observed_row_field", "record_count"} and parent.get("unit"):
                return str(parent["unit"])
        raise ValueError("analysis_table_unit_unspecified")
    if leaf in _UNIT_FIELDS:
        return _UNIT_FIELDS[leaf]
    if leaf in {"count", "row_count", "record_count"}:
        # Generic records do not inherit an Orders unit merely because their
        # count has the same field name. Producer identity is runtime-bound.
        return ("order" if leaf == "count" and operation_id.startswith("orders.")
                else "return" if leaf == "count" and operation_id.startswith("returns.") else "record")
    if leaf.endswith("_count"):
        return leaf[:-6]  # A return count cannot silently become an order count.
    if leaf in {"balance", "quantity", "total_quantity", "total_balance"}:
        for parent in reversed(parents):
            unit = parent.get("unit") or parent.get("quantity_unit")
            if isinstance(unit, str) and unit.strip():
                return unit.strip()
        raise ValueError("analysis_quantity_unit_unknown")
    if leaf in _MONEY_FIELDS or leaf.endswith("_amount"):
        for parent in reversed(parents):
            currency = parent.get(f"{leaf}_currency") or parent.get("currency")
            if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency) and currency != "XXX":
                return currency
        raise ValueError("analysis_currency_unknown")
    if leaf in {"percentage", "percent", "profit_margin"} or leaf.endswith("_percent"):
        return "%"
    raise ValueError(f"analysis_measure_unit_unknown:{path}")


def _operand(ref: Mapping[str, Any], bound: dict[str, dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    if not isinstance(ref, Mapping) or set(ref) != {"source_id", "path"}:
        raise ValueError("analysis_operand_requires_source_reference")
    source_id, path = ref.get("source_id"), ref.get("path")
    if source_id not in bound or not isinstance(path, str) or not path:
        raise ValueError("analysis_operand_source_not_bound")
    source = bound[source_id]
    result = source["result"]
    try:
        value = source_path_value(result, path)
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("analysis_operand_not_observed_numeric")
        normalized = normalize_projection_value(value)
        parents = [result]
        tokens = _tokens(path)
        for end in range(1, len(tokens)):
            parent = source_path_value(result, "/" + "/".join(
                token.replace("~", "~0").replace("/", "~1") for token in tokens[:end]
            ))
            if isinstance(parent, Mapping):
                parents.append(parent)
        producer, original, _ = observed_source_payload(result, source["operation_id"])
        unit = _unit(original, path, parents, producer)
    except ValueError as exc:
        exc.operand_context = {"source_id": source_id, "source_step_id": source["source_step_id"],
                               "operation_id": source["operation_id"], "path": path}
        raise
    return value, {"source_id": source_id, "source_step_id": source["source_step_id"],
                   "operation_id": source["operation_id"], "path": path, "value": normalized,
                   "unit": unit, "source_result_hash": source_projection_hash(result)}


def _result_unit(operator: str, receipts: list[dict[str, Any]]) -> str:
    units = [receipt["unit"] for receipt in receipts]
    if operator in {"add", "subtract", "minimum", "maximum", "percentage", "compare"}:
        if len(set(units)) != 1:
            raise ValueError("analysis_incompatible_units")
        return "%" if operator == "percentage" else units[0]
    if operator == "divide":
        return "ratio" if units[0] == units[1] else f"{units[0]}/{units[1]}"
    return "*".join(units)


def _assert_same_entity_scope(receipts: list[dict[str, Any]], bound: dict[str, dict[str, Any]]) -> None:
    # Periods may differ for comparison; identity/environment/selection may not.
    # Across domains, absence of shared scope does not imply a business join.
    originals = [observed_source_payload(bound[receipt["source_id"]]["result"], receipt["operation_id"])
                 for receipt in receipts]
    if len({producer.split(".")[0] for producer, _, _ in originals}) > 1:
        return
    scope = [observed_entity_scope(original) for _, original, _ in originals]
    if any(source_projection_hash(row) != source_projection_hash(scope[0]) for row in scope[1:]):
        raise ValueError("analysis_source_entity_scope_mismatch")


def _result_kind(unit: str, *, comparison: bool = False) -> str:
    if comparison:
        return "boolean"
    if unit == "%":
        return "percentage"
    if re.fullmatch(r"[A-Z]{3}", unit):
        return "amount"
    if unit.endswith("/order") and re.fullmatch(r"[A-Z]{3}/order", unit):
        return "amount_per_order"
    if "/" in unit and re.fullmatch(r"[A-Z]{3}/.+", unit):
        return "amount_per_quantity"
    if unit.endswith("/order"):
        return "quantity_per_order"
    if unit in {"order", "item", "marketplace_item", "product", "return", "claim"}:
        return "count"
    return "scalar"


def calculate_observations(*, sources: list[dict[str, Any]],
                           calculations: list[dict[str, Any]] | None = None,
                           comparisons: list[dict[str, Any]] | None = None) -> Result:
    """Evaluate model-chosen paths with exact decimal math and source provenance."""
    try:
        if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
            raise ValueError("analysis_sources_required")
        calculations, comparisons = calculations or [], comparisons or []
        if (not isinstance(calculations, list) or not isinstance(comparisons, list)
                or len(calculations) > 32 or len(comparisons) > 32 or not (calculations or comparisons)):
            raise ValueError("analysis_expression_limit_or_empty")
        bound, source_receipts = {}, []
        for source in sources:
            if (not isinstance(source, Mapping) or not isinstance(source.get("result"), Mapping)
                    or any(not isinstance(source.get(key), str) or not source[key].strip()
                           for key in ("source_id", "source_step_id", "operation_id"))):
                raise ValueError("analysis_source_identity_and_result_required")
            source_id = source["source_id"]
            if source_id in bound:
                raise ValueError("analysis_source_ids_must_be_unique")
            bound[source_id] = source
            _, original, provenance = observed_source_payload(source["result"], source["operation_id"])
            source_receipts.append({
                **{key: source[key] for key in ("source_id", "source_step_id", "operation_id")},
                "source_result_hash": source_projection_hash(source["result"]),
                "scope": observed_entity_scope(original),
                "period": normalize_projection_value({key: original[key] for key in _PERIOD_KEYS if key in original}),
                "coverage": normalize_projection_value(original.get("data_coverage", original.get("coverage"))),
                **({"source_provenance": provenance} if provenance else {}),
            })
        verified_calculations, verified_comparisons, operand_receipts, expression_ids = [], [], [], set()
        for expression in [*calculations, *comparisons]:
            is_calculation = "calculation_id" in expression
            expression_id = expression.get("calculation_id" if is_calculation else "comparison_id")
            if not isinstance(expression_id, str) or not expression_id.strip() or expression_id in expression_ids:
                raise ValueError("analysis_expression_ids_must_be_unique")
            expression_ids.add(expression_id)
            operator = expression.get("operator")
            precision = expression.get("precision", 2)
            if is_calculation and (isinstance(precision, bool) or not isinstance(precision, int)):
                raise ValueError("analysis_invalid_precision")
            references = expression.get("operands") if is_calculation else [expression.get("left"), expression.get("right")]
            if not isinstance(references, list) or not 2 <= len(references) <= 16:
                raise ValueError("analysis_operand_count_invalid")
            resolved = [_operand(ref, bound) for ref in references]
            values, receipts = [row[0] for row in resolved], [row[1] for row in resolved]
            _assert_same_entity_scope(receipts, bound)
            unit = _result_unit(operator if is_calculation else "compare", receipts)
            display_unit = expression.get("result_unit", "native")
            scaling = {}
            if display_unit != "native":
                if is_calculation and operator == "percentage" and display_unit == "percentage" and unit == "%":
                    pass  # Explicitly repeating the intrinsic unit is equivalent.
                elif not is_calculation or operator != "divide" or unit != "ratio" or display_unit not in {"ratio", "percentage"}:
                    raise ValueError("analysis_result_unit_incompatible")
                elif display_unit == "percentage":
                    unit = "%"
                    scaling = {"operand_scales": [1] * len(values), "result_scale": "0.01"}
            calculation = (evaluate_verified_calculation(operator=operator, operands=values, precision=precision, **scaling)
                           if is_calculation else evaluate_verified_comparison(operator=operator, left=values[0], right=values[1]))
            if not calculation.success:
                raise ValueError(f"analysis_{calculation.data.get('reason', 'calculation_invalid')}")
            receipt = {**calculation.data, "unit": unit, "result_unit": display_unit, "result_kind": _result_kind(unit, comparison=not is_calculation), "operand_receipts": receipts,
                       "source_receipts": [row for row in source_receipts if row["source_id"] in {ref["source_id"] for ref in receipts}],
                       "arithmetic_only": True, "business_relationship_verified": False,
                       "calculation_id" if is_calculation else "comparison_id": expression_id}
            receipt["arithmetic_evidence_hash"] = receipt.pop("evidence_hash")
            receipt["evidence_hash"] = source_projection_hash(receipt)
            (verified_calculations if is_calculation else verified_comparisons).append(receipt)
            operand_receipts.extend(receipts)
        payload = {"verified": True, "arithmetic_only": True, "business_relationship_verified": False,
                   "verified_calculations": verified_calculations, "verified_comparisons": verified_comparisons,
                   "source_receipts": source_receipts, "operand_receipts": operand_receipts}
        payload["evidence_hash"] = source_projection_hash(payload)
        return Result.ok("Kaynaklara bağlı hesaplamalar doğrulandı.", close_dialog=False, data=payload)
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, OverflowError) as exc:
        context = getattr(exc, "operand_context", None)
        detail = {"reason": str(exc), "verified": False}
        if isinstance(context, dict):
            detail["failed_operand"] = context
            detail["repair_policy"] = "Use an actually observed numeric field with a known unit. Reading the same source again does not repair an absent unit or make a currency string numeric. Preserve unsupported information as an explicit limitation; do not invent it."
        return Result.fail("Hesaplama için doğrulanmış ve uyumlu kaynaklar gerekli.", close_dialog=False,
                           data=detail)
