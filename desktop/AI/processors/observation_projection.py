"""Pure projection and hashing for runtime-bound operation observations."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
from typing import Any, Mapping


OBSERVATION_ENTITY_SCOPE_KEYS = (
    "account_ids", "account_id", "api_account_ids", "api_account_id", "marketplace_account_ids", "marketplace_account_id",
    "account_scopes", "environment_by_account", "environment", "company_id", "warehouse_id",
    "selected_order_ids", "selection_id",
)


def normalize_projection_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("observation_projection_non_finite_number")
        return value
    if isinstance(value, Decimal):
        return normalize_projection_value(float(value))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): normalize_projection_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_projection_value(child) for child in value]
    raise ValueError("observation_projection_not_json_serializable")


def source_projection_hash(value: Any) -> str:
    body = json.dumps(normalize_projection_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def observed_source_payload(result: Mapping[str, Any], operation_id: str) -> tuple[str, Mapping[str, Any], dict[str, Any]]:
    """Recover original scope/time while binding and hashing the full wrapper.

    An imported historical snapshot remains historical through calculations
    and export. This pure projection supplies neither a result nor authority.
    """
    original, producer, chain = result, operation_id, []
    while producer == "artifacts.read":
        if len(chain) >= 16:
            raise ValueError("observation_projection_historical_chain_limit")
        ref, payload = original.get("artifact"), original.get("result")
        if (original.get("tool") != "artifacts.read" or original.get("verified") is not True
                or original.get("historical_observation") is not True or original.get("fresh_read") is not False
                or original.get("freshness") != "historical_snapshot" or not isinstance(ref, Mapping)
                or not isinstance(payload, Mapping) or not isinstance(ref.get("origin"), Mapping)
                or ref.get("result_hash") != source_projection_hash(payload)
                or ref.get("observed_at") != original.get("observed_at") or ref.get("scope") != original.get("scope")):
            raise ValueError("observation_projection_historical_receipt_invalid")
        origin = ref["origin"]
        if any(not isinstance(origin.get(key), str) or not origin[key] for key in ("task_id", "step_id", "operation_id")):
            raise ValueError("observation_projection_historical_origin_invalid")
        timestamp = original.get("observed_at")
        if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("observation_projection_historical_timestamp_invalid")
        chain.append({key: normalize_projection_value(ref.get(key)) for key in
                      ("artifact_id", "artifact_hash", "result_hash", "observed_at", "origin")})
        producer, original = origin["operation_id"], payload
    if not chain:
        inherited = []
        if producer in {"analysis.calculate", "analysis.table"} and original.get("verified") is True:
            for receipt in list(original.get("source_receipts") or [])[:64]:
                provenance = receipt.get("source_provenance") if isinstance(receipt, Mapping) else None
                if isinstance(provenance, Mapping) and provenance.get("fresh_read") is False:
                    rows = provenance.get("historical_sources") if provenance.get("contains_historical_observations") is True else [provenance]
                    if isinstance(rows, list):
                        inherited.extend(normalize_projection_value(row) for row in rows[:64]
                                         if isinstance(row, Mapping) and row.get("historical_observation") is True)
        if not inherited:
            return producer, original, {}
        inherited = list({source_projection_hash(row): row for row in inherited}.values())[:64]
        return producer, original, {
            "contains_historical_observations": True, "fresh_read": False,
            "freshness": "derived_from_historical_snapshot",
            "observed_at": list(dict.fromkeys(row["observed_at"] for row in inherited)),
            "original_operation_ids": list(dict.fromkeys(row["original_operation_id"] for row in inherited)),
            "historical_sources": inherited,
        }
    provenance = {
        "historical_observation": True, "fresh_read": False, "freshness": "historical_snapshot",
        "observed_at": chain[-1]["observed_at"], "original_operation_id": producer,
        "origin": chain[-1]["origin"], "artifact_chain": chain,
    }
    _, _, inherited = observed_source_payload(original, producer)
    if inherited:
        rows = [provenance, *inherited["historical_sources"]]
        return producer, original, {
            "contains_historical_observations": True, "fresh_read": False,
            "freshness": "derived_from_historical_snapshot",
            "observed_at": list(dict.fromkeys(row["observed_at"] for row in rows)),
            "original_operation_ids": list(dict.fromkeys(row["original_operation_id"] for row in rows)),
            "historical_sources": rows,
        }
    return producer, original, provenance


def observed_entity_scope(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep scopes of verified derived measurements through another analysis."""
    direct = {key: normalize_projection_value(result[key]) for key in OBSERVATION_ENTITY_SCOPE_KEYS if key in result}
    if direct or result.get("verified") is not True:
        return direct
    scopes = []
    for receipt in list(result.get("source_receipts") or [])[:64]:
        if isinstance(receipt, Mapping) and isinstance(receipt.get("scope"), Mapping) and receipt["scope"]:
            provenance = receipt.get("source_provenance") or {}
            producer = provenance.get("original_operation_id") or receipt.get("operation_id")
            if isinstance(producer, str):
                scopes.append({"owner_domain": producer.split(".")[0], "scope": normalize_projection_value(receipt["scope"])})
    unique = {source_projection_hash(scope): scope for scope in scopes}
    return {"source_scopes": [unique[key] for key in sorted(unique)]} if unique else {}


def source_path_value(value: Any, path: str) -> Any:
    if not path:
        return value
    tokens = path.split(".") if not path.startswith("/") else [
        token.replace("~1", "/").replace("~0", "~") for token in path[1:].split("/")
    ]
    current = value
    for token in tokens:
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, (list, tuple)) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"observation_projection_path_missing:{path}")
    return current
