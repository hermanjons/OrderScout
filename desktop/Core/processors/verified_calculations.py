from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Sequence

from Feedback.processors.pipeline import Result


CALCULATION_OPERATORS = frozenset(
    {
        "add",
        "subtract",
        "multiply",
        "divide",
        "percentage",
        "minimum",
        "maximum",
    }
)

COMPARISON_OPERATORS = frozenset(
    {
        "equal",
        "not_equal",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
    }
)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Calculation operands must be finite numbers.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Calculation operands must be finite numbers.")
    try:
        parsed = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError("Calculation operands must be finite numbers.") from exc
    if not parsed.is_finite():
        raise ValueError("Calculation operands must be finite numbers.")
    return parsed


def _plain_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def evaluate_verified_calculation(
    *,
    operator: str,
    operands: Sequence[Any],
    precision: int = 2,
    operand_scales: Sequence[Any] | None = None,
    result_scale: Any | None = None,
) -> Result:
    """Evaluate a bounded arithmetic contract with deterministic decimal rounding.

    Domain runtimes resolve authoritative operands before calling this function.
    Optional scales convert displayed magnitudes to a common base representation
    before arithmetic, and convert the result to its requested display unit.
    A percentage magnitude has scale 0.01. No intermediate result is rounded.
    Core owns only reusable arithmetic, validation and immutable calculation
    provenance; it never reads a database, a model response or conversation prose.
    """

    clean_operator = str(operator or "").strip().casefold()
    if clean_operator not in CALCULATION_OPERATORS:
        return Result.fail(
            "Desteklenmeyen hesaplama operatoru.",
            close_dialog=False,
            data={"reason": "unsupported_operator"},
        )
    try:
        clean_precision = int(precision)
    except (TypeError, ValueError):
        clean_precision = -1
    if clean_precision < 0 or clean_precision > 6:
        return Result.fail(
            "Hesaplama hassasiyeti 0 ile 6 arasinda olmali.",
            close_dialog=False,
            data={"reason": "invalid_precision"},
        )
    try:
        values = [_decimal(value) for value in list(operands or [])]
    except ValueError as exc:
        return Result.fail(
            str(exc),
            error=exc,
            close_dialog=False,
            data={"reason": "invalid_operand"},
        )
    if len(values) < 2:
        return Result.fail(
            "Hesaplama icin en az iki operand gerekli.",
            close_dialog=False,
            data={"reason": "insufficient_operands"},
        )
    if clean_operator in {"subtract", "divide", "percentage"} and len(values) != 2:
        return Result.fail(
            "Bu hesaplama operatoru tam olarak iki operand ister.",
            close_dialog=False,
            data={"reason": "invalid_operand_count"},
        )

    displayed_values = list(values)
    scaling: dict[str, Any] = {}
    if operand_scales is not None or result_scale is not None:
        try:
            scales = [_decimal(value) for value in list(operand_scales or [])]
            output_scale = _decimal(result_scale)
            if len(scales) != len(values) or any(value <= 0 for value in scales) or output_scale <= 0:
                raise ValueError("Quantity scales must be positive and match the operands.")
        except ValueError as exc:
            return Result.fail(str(exc), error=exc, close_dialog=False,
                data={"reason": "invalid_quantity_scale"})
        values = [value * scale for value, scale in zip(displayed_values, scales)]
        intrinsic_scale = Decimal("0.01") if clean_operator == "percentage" else Decimal("1")
        scaling = {
            "operand_scales": [_plain_decimal(value) for value in scales],
            "result_scale": _plain_decimal(output_scale),
            "intrinsic_result_scale": _plain_decimal(intrinsic_scale),
            "base_operands": [_plain_decimal(value) for value in values],
            "display_operand_multipliers": ["1"] * len(values),
            "display_result_multiplier": "1",
        }
        if clean_operator in {"add", "subtract", "minimum", "maximum"}:
            scaling["display_operand_multipliers"] = [
                _plain_decimal(scale / output_scale) for scale in scales
            ]
        elif clean_operator == "multiply":
            display_multiplier = Decimal("1") / output_scale
            for scale in scales:
                display_multiplier *= scale
            scaling["display_result_multiplier"] = _plain_decimal(display_multiplier)
        else:
            # Both quotient operators may be displayed as a ratio or percent;
            # the selected output unit owns this conversion, not a rewritten op.
            scaling["display_result_multiplier"] = _plain_decimal(scales[0] / scales[1] / output_scale)

    if clean_operator == "add":
        raw_result = sum(values, Decimal("0"))
        symbol = " + "
        expression_left = symbol.join(_plain_decimal(value) for value in values)
    elif clean_operator == "subtract":
        raw_result = values[0] - values[1]
        expression_left = " - ".join(_plain_decimal(value) for value in values)
    elif clean_operator == "multiply":
        raw_result = Decimal("1")
        for value in values:
            raw_result *= value
        expression_left = " × ".join(_plain_decimal(value) for value in values)
    elif clean_operator == "divide":
        if values[1] == 0:
            return Result.fail(
                "Sifira bolme yapilamaz.",
                close_dialog=False,
                data={"reason": "division_by_zero"},
            )
        raw_result = values[0] / values[1]
        expression_left = " / ".join(_plain_decimal(value) for value in values)
    elif clean_operator == "percentage":
        if values[1] == 0:
            return Result.fail(
                "Sifir tabanli yuzde hesabi yapilamaz.",
                close_dialog=False,
                data={"reason": "division_by_zero"},
            )
        raw_result = (values[0] / values[1]) * Decimal("100")
        expression_left = (
            f"{_plain_decimal(values[0])} / {_plain_decimal(values[1])} × 100"
        )
    elif clean_operator == "minimum":
        raw_result = min(values)
        expression_left = "min(" + ", ".join(
            _plain_decimal(value) for value in values
        ) + ")"
    else:
        raw_result = max(values)
        expression_left = "max(" + ", ".join(
            _plain_decimal(value) for value in values
        ) + ")"

    if scaling:
        conversion = intrinsic_scale / output_scale
        raw_result *= conversion
        if conversion != 1:
            expression_left = f"({expression_left}) × {_plain_decimal(conversion)}"
    quantum = Decimal("1").scaleb(-clean_precision)
    rounded = raw_result.quantize(quantum, rounding=ROUND_HALF_UP)
    operand_texts = [_plain_decimal(value) for value in displayed_values]
    result_text = format(rounded, f".{clean_precision}f")
    evidence_payload = {
        "operator": clean_operator,
        "operands": operand_texts,
        "precision": clean_precision,
        "rounding": "ROUND_HALF_UP",
        "result": result_text,
    }
    if scaling:
        evidence_payload["quantity_scaling"] = scaling
    evidence_hash = hashlib.sha256(
        json.dumps(
            evidence_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return Result.ok(
        "Hesaplama dogrulandi.",
        close_dialog=False,
        data={
            **evidence_payload,
            "expression": f"{expression_left} = {result_text}",
            "result_value": float(rounded),
            "evidence_hash": evidence_hash,
            "verified": True,
        },
    )


def evaluate_verified_comparison(
    *,
    operator: str,
    left: Any,
    right: Any,
) -> Result:
    """Compare two authoritative numeric values with immutable provenance.

    Domain runtimes remain responsible for resolving typed references. Core
    owns only the reusable numeric relation and its evidence hash, just as it
    owns bounded arithmetic above.
    """

    clean_operator = str(operator or "").strip().casefold()
    clean_operator = {
        "equals": "equal",
        "eq": "equal",
        "different": "not_equal",
        "not_equals": "not_equal",
        "ne": "not_equal",
        "gt": "greater_than",
        "gte": "greater_or_equal",
        "ge": "greater_or_equal",
        "lt": "less_than",
        "lte": "less_or_equal",
        "le": "less_or_equal",
    }.get(clean_operator, clean_operator)
    if clean_operator not in COMPARISON_OPERATORS:
        return Result.fail(
            "Desteklenmeyen karsilastirma operatoru.",
            close_dialog=False,
            data={"reason": "unsupported_comparison_operator"},
        )
    try:
        left_value = _decimal(left)
        right_value = _decimal(right)
    except ValueError as exc:
        return Result.fail(
            str(exc),
            error=exc,
            close_dialog=False,
            data={"reason": "invalid_comparison_operand"},
        )

    holds = {
        "equal": left_value == right_value,
        "not_equal": left_value != right_value,
        "greater_than": left_value > right_value,
        "greater_or_equal": left_value >= right_value,
        "less_than": left_value < right_value,
        "less_or_equal": left_value <= right_value,
    }[clean_operator]
    difference = left_value - right_value
    symbol = {
        "equal": "=",
        "not_equal": "≠",
        "greater_than": ">",
        "greater_or_equal": "≥",
        "less_than": "<",
        "less_or_equal": "≤",
    }[clean_operator]
    left_text = _plain_decimal(left_value)
    right_text = _plain_decimal(right_value)
    evidence_payload = {
        "operator": clean_operator,
        "left": left_text,
        "right": right_text,
        "holds": holds,
        "difference": _plain_decimal(difference),
        "absolute_difference": _plain_decimal(abs(difference)),
    }
    evidence_hash = hashlib.sha256(
        json.dumps(
            evidence_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return Result.ok(
        "Karsilastirma dogrulandi.",
        close_dialog=False,
        data={
            **evidence_payload,
            "expression": f"{left_text} {symbol} {right_text}",
            "evidence_hash": evidence_hash,
            "verified": True,
        },
    )
