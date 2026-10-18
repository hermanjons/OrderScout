"""Bounded table analysis over runtime-bound observations, without code execution."""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Mapping

from AI.processors.observation_projection import normalize_projection_value, observed_entity_scope, observed_source_payload, source_path_value, source_projection_hash
from Feedback.processors.pipeline import Result


_OPERATORS = ["sum", "average", "minimum", "maximum", "count", "count_non_null"]
_FORMATS = ["native", "decimal_dot", "decimal_comma", "decimal_dot_group_comma", "decimal_comma_group_dot"]
TABULAR_ANALYSIS_SCHEMA = {
    "type": "object", "properties": {
        "sources": {"type": "array", "minItems": 1, "maxItems": 64, "items": {
            "type": "object", "properties": {
                "source_id": {"type": "string", "minLength": 1},
                "source_step_id": {"type": "string", "minLength": 1},
                "operation_id": {"type": "string", "minLength": 1}, "result": {"type": "object"},
            }, "required": ["source_id", "source_step_id", "operation_id", "result"], "additionalProperties": False,
        }},
        "source_id": {"type": "string", "minLength": 1},
        "rows_path": {"type": "string", "minLength": 1},
        "group_by": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1}},
        "measures": {"type": "array", "minItems": 1, "maxItems": 32, "items": {
            "type": "object", "properties": {
                "name": {"type": "string", "minLength": 1},
                "operator": {"type": "string", "enum": _OPERATORS},
                "path": {"type": "string"},
                "unit_path": {"type": "string", "description": "Observed row field holding currency/quantity unit. Missing unit remains unspecified."},
                "number_format": {"type": "string", "enum": _FORMATS},
                "precision": {"type": "integer", "minimum": 0, "maximum": 6},
            }, "required": ["name", "operator"], "additionalProperties": False,
        }},
    }, "required": ["sources", "source_id", "rows_path", "measures"], "additionalProperties": False,
}
TABULAR_ANALYSIS_OUTPUT_SCHEMA = {
    "type": "object", "properties": {
        "verified": {"type": "boolean"}, "evidence_hash": {"type": "string"},
        "rows": {"type": "array", "items": {"type": "object"}},
        "group_count": {"type": "integer"}, "source_row_count": {"type": "integer"},
        "source_receipts": {"type": "array", "items": {"type": "object"}},
        "conversion_receipts": {"type": "array", "items": {"type": "object"}},
        "data_coverage": {"type": "object"}, "arithmetic_only": {"type": "boolean"},
    }, "required": ["verified", "evidence_hash", "rows", "source_receipts", "source_row_count", "data_coverage"],
}


def _number(value: Any, number_format: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("table_boolean_is_not_number")
    if number_format == "native":
        if not isinstance(value, (int, float, Decimal)):
            raise ValueError("table_numeric_strings_require_explicit_format")
        text = str(value)
    else:
        if not isinstance(value, str):
            raise ValueError("table_lexical_format_requires_string")
        text = value.strip()
        patterns = {
            "decimal_dot": r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)",
            "decimal_comma": r"[-+]?(?:\d+(?:,\d+)?|,\d+)",
            "decimal_dot_group_comma": r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
            "decimal_comma_group_dot": r"[-+]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?",
        }
        if not re.fullmatch(patterns.get(number_format, r"(?!)"), text):
            raise ValueError("table_numeric_format_mismatch")
        if number_format == "decimal_dot_group_comma":
            text = text.replace(",", "")
        elif number_format == "decimal_comma_group_dot":
            text = text.replace(".", "").replace(",", ".")
        elif number_format == "decimal_comma":
            text = text.replace(",", ".")
    parsed = Decimal(text)
    if not parsed.is_finite() or abs(parsed) > Decimal("1e24"):
        raise ValueError("table_number_out_of_bounds")
    return parsed


def analyze_observation_table(*, sources: list[dict[str, Any]], source_id: str, rows_path: str,
                              measures: list[dict[str, Any]], group_by: list[str] | None = None) -> Result:
    try:
        if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
            raise ValueError("table_sources_required")
        bound = {}
        for source in sources:
            if (not isinstance(source, Mapping) or not isinstance(source.get("result"), Mapping)
                    or any(not isinstance(source.get(key), str) or not source[key].strip()
                           for key in ("source_id", "source_step_id", "operation_id"))):
                raise ValueError("table_source_identity_and_result_required")
            if source["source_id"] in bound:
                raise ValueError("table_source_ids_must_be_unique")
            bound[source["source_id"]] = source
        if source_id not in bound or not isinstance(rows_path, str) or not rows_path:
            raise ValueError("table_source_not_bound")
        source = bound[source_id]
        _, original_source, provenance = observed_source_payload(source["result"], source["operation_id"])
        rows = source_path_value(source["result"], rows_path)
        if not isinstance(rows, list) or len(rows) > 10_000 or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("table_bounded_records_required")
        group_by = group_by or []
        if not isinstance(group_by, list) or len(group_by) > 8 or len(set(group_by)) != len(group_by):
            raise ValueError("table_group_paths_invalid")
        if not isinstance(measures, list) or not 1 <= len(measures) <= 32:
            raise ValueError("table_measures_required")
        names = set()
        for measure in measures:
            name, operator = measure.get("name"), measure.get("operator")
            if not isinstance(name, str) or not name or name in names or operator not in _OPERATORS:
                raise ValueError("table_measure_contract_invalid")
            names.add(name)
            precision = measure.get("precision", 2)
            if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 6:
                raise ValueError("table_precision_invalid")
            if operator != "count" and not measure.get("path"):
                raise ValueError("table_measure_source_path_required")
            if measure.get("number_format", "native") not in _FORMATS:
                raise ValueError("table_number_format_invalid")
        groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
        conversions = []
        for index, row in enumerate(rows):
            keys = {path: normalize_projection_value(source_path_value(row, path)) for path in group_by}
            if any(isinstance(value, (dict, list)) for value in keys.values()):
                raise ValueError("table_group_values_must_be_scalar")
            key_hash = source_projection_hash(keys)
            if key_hash not in groups:
                if len(groups) >= 500:
                    raise ValueError("table_group_limit_use_narrower_source")
                groups[key_hash] = {"group": keys, "record_count": 0,
                                    "metrics": {name: {"values": [], "units": set(), "null_count": 0} for name in names}}
            group = groups[key_hash]
            group["record_count"] += 1
            for measure in measures:
                metric = group["metrics"][measure["name"]]
                operator = measure["operator"]
                if operator == "count":
                    continue
                raw = source_path_value(row, measure["path"])
                if raw is None:
                    metric["null_count"] += 1
                    continue
                if operator == "count_non_null":
                    metric["values"].append(Decimal(1))
                    continue
                parsed = _number(raw, measure.get("number_format", "native"))
                metric["values"].append(parsed)
                if measure.get("unit_path"):
                    unit = source_path_value(row, measure["unit_path"])
                    if not isinstance(unit, str) or not unit.strip():
                        raise ValueError("table_observed_unit_required")
                    metric["units"].add(unit.strip())
                if isinstance(raw, str):
                    conversions.append({"source_row_index": index, "source_path": measure["path"],
                                        "original": raw, "parsed_decimal": str(parsed),
                                        "number_format": measure["number_format"]})
        output_rows = []
        # Empty sources still return a verified zero count; numeric sums remain
        # null because no amount/unit was observed.
        if not groups and not group_by:
            groups["empty"] = {"group": {}, "record_count": 0,
                                "metrics": {name: {"values": [], "units": set(), "null_count": 0} for name in names}}
        for group in groups.values():
            output = {"group": group["group"], "record_count": group["record_count"], "metrics": {}}
            for measure in measures:
                metric = group["metrics"][measure["name"]]
                values, units, operator = metric["values"], metric["units"], measure["operator"]
                if len(units) > 1:
                    raise ValueError("table_incompatible_units_group_by_currency_or_unit")
                raw_value = (Decimal(group["record_count"]) if operator == "count"
                             else Decimal(len(values)) if operator == "count_non_null"
                             else None if not values
                             else sum(values, Decimal(0)) if operator == "sum"
                             else sum(values, Decimal(0)) / len(values) if operator == "average"
                             else min(values) if operator == "minimum" else max(values))
                rounded = raw_value.quantize(Decimal(1).scaleb(-measure.get("precision", 2)), rounding=ROUND_HALF_UP) if raw_value is not None else None
                output["metrics"][measure["name"]] = {
                    "value": int(rounded) if rounded is not None and operator in {"count", "count_non_null"} else float(rounded) if rounded is not None else None,
                    "exact_value": str(rounded) if rounded is not None else None,
                    "operator": operator, "source_path": measure.get("path"),
                    "unit": "record" if operator in {"count", "count_non_null"} else next(iter(units), None),
                    "unit_basis": "record_count" if operator in {"count", "count_non_null"} else "observed_row_field" if units else "unspecified",
                    "observed_value_count": len(values), "null_count": metric["null_count"],
                }
            output_rows.append(output)
        payload = {"tool": "analysis.table", "verified": True, "arithmetic_only": True, "business_relationship_verified": False,
                   "rows": output_rows, "group_count": len(output_rows), "source_row_count": len(rows),
                   "source_receipts": [{"source_id": source_id, "source_step_id": source["source_step_id"],
                                        "operation_id": source["operation_id"], "source_result_hash": source_projection_hash(source["result"]),
                                        "rows_path": rows_path, "scope": observed_entity_scope(original_source),
                                        **({"source_provenance": provenance} if provenance else {})}],
                   "conversion_receipts": conversions,
                   "data_coverage": normalize_projection_value(original_source.get("data_coverage") or {"status": "unspecified"}),
                   "analysis_contract": {"source_id": source_id, "rows_path": rows_path, "group_by": group_by, "measures": normalize_projection_value(measures)}}
        if len(str(payload)) > 1_000_000:
            raise ValueError("table_output_size_limit_use_narrower_source")
        payload["evidence_hash"] = source_projection_hash(payload)
        return Result.ok("Tablo hesapları kaynak satırlarına bağlı olarak doğrulandı.", close_dialog=False, data=payload)
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, OverflowError) as exc:
        return Result.fail("Tablo analizi kaynak alanları ve birimleriyle doğrulanamadı.", close_dialog=False,
                           data={"verified": False, "reason": str(exc)})
