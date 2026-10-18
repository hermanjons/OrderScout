"""Model-authored grouped result columns, independent of population metrics."""
from __future__ import annotations

from typing import Any


GROUPED_PROJECTION_SCHEMA = {
    "type": ["object", "null"],
    "description": "Explicit user-requested grouped output rows only. Null for general assessment, even when product statistics support the analysis. Never invent a row limit or mandatory columns for a broad analysis.",
    "properties": {
        "group_by": {"type": "string", "enum": ["product"]},
        "fields": {"type": "array", "items": {"type": "string", "enum": [
            "product_name", "quantity", "order_count", "gross_amount", "currency",
        ]}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
    "required": ["group_by", "fields", "limit"],
    "additionalProperties": False,
}


def normalize_grouped_projection(value: Any) -> dict[str, Any]:
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict) or set(value) != {"group_by", "fields", "limit"}:
        raise ValueError("grouped_projection:shape")
    fields = value["fields"]
    allowed = GROUPED_PROJECTION_SCHEMA["properties"]["fields"]["items"]["enum"]
    if value["group_by"] != "product" or not isinstance(fields, list):
        raise ValueError("grouped_projection:group_or_fields")
    if "product_name" not in fields or any(not isinstance(f, str) or f not in allowed for f in fields):
        raise ValueError("grouped_projection:columns")
    limit = value["limit"]
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("grouped_projection:limit")
    fields = list(dict.fromkeys(fields))
    if "gross_amount" in fields and "currency" not in fields:
        fields.append("currency")
    return {"group_by": "product", "fields": fields, "limit": limit}


def grouped_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return normalize_grouped_projection(contract.get("grouped_projection"))
