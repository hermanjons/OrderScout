from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from AI.processors.cloud_runtime import build_provider_chat_client
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.model_routing import build_free_model_test_route, stable_state_hash
from AI.processors.pipeline import get_provider_account, list_provider_models


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_model(value: Any) -> str:
    return _text(value).removeprefix("models/")


def run_live_fallback_evidence(
    *,
    provider_id: int,
    provider_code: str,
    requested_model: str,
    fallback_model: str,
    output: str | Path,
    timeout: float = 90.0,
) -> dict[str, Any]:
    account_result = get_provider_account(int(provider_id))
    if not account_result.success:
        raise RuntimeError(account_result.message)
    account = dict((account_result.data or {}).get("record") or {})
    catalog_result = list_provider_models(
        provider_code=provider_code,
        endpoint_url=_text(account.get("endpoint_url")),
        api_key=_text(account.get("api_key")),
        free_only=True,
        limit=500,
    )
    if not catalog_result.success:
        raise RuntimeError(catalog_result.message)
    catalog = dict(catalog_result.data or {})
    records = [
        dict(row)
        for row in list(catalog.get("records") or [])
        if isinstance(row, dict)
    ]
    by_id = {
        _normalized_model(row.get("id") or row.get("model_id")): row
        for row in records
        if _normalized_model(row.get("id") or row.get("model_id"))
    }
    requested = _normalized_model(requested_model)
    fallback = _normalized_model(fallback_model)
    missing = [model for model in (requested, fallback) if model not in by_id]
    if missing:
        raise RuntimeError(f"Canli ucretsiz katalogda model bulunamadi: {', '.join(missing)}")

    state = {
        "message_index": 47,
        "selection": ["synthetic-order-a", "synthetic-order-b"],
        "task_state": {"domain": "orders", "phase": "analysis_complete"},
        "pending_action": {
            "operation_id": "labels.create_from_orders.prepare",
            "status": "approval_required",
        },
    }
    state_hash = stable_state_hash(state)
    prompt = (
        "Bu bir fallback durum-butunlugu kontroludur. Asagidaki sentetik conversation "
        "checkpoint'ini degistirmeden oku ve yalnizca FALLBACK_STATE_OK yaz:\n"
        + json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    route = build_free_model_test_route(
        provider_code,
        [by_id[requested], by_id[fallback]],
        state_payload=state,
        generated_from_live_catalog=True,
    ).to_dict()
    route["model_ids"] = [requested, fallback]

    runtime_record = dict(account)
    runtime_record.update(
        {
            "provider_code": provider_code,
            "default_model": requested,
            "model_metadata": dict(by_id[requested]),
            "free_model_test_route": route,
            "allow_model_fallback": True,
            "max_tokens": 64,
            "temperature": 0,
            "is_enabled": True,
        }
    )
    client = build_provider_chat_client(runtime_record, timeout=max(5.0, float(timeout)))
    if client is None:
        raise RuntimeError("Provider fallback istemcisi olusturulamadi.")
    answer = _text(client(prompt))
    plan = dict(getattr(client, "resource_plan", {}) or {})
    request_hashes = [
        dict(row)
        for row in list(plan.get("request_prompt_hashes") or [])
        if isinstance(row, dict)
    ]
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    requested_hashes_match = bool(request_hashes) and all(
        _text(row.get("prompt_sha256")) == prompt_sha256 for row in request_hashes
    )
    actual_model = _normalized_model(plan.get("actual_model"))
    valid = bool(
        answer
        and actual_model == fallback
        and plan.get("fallback_used") is True
        and requested_hashes_match
        and state_hash == stable_state_hash(state)
    )
    payload = {
        "artifact_type": "provider_live_fallback_state_evidence",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_code": provider_code,
        "live_catalog": True,
        "free_model_count": int(catalog.get("free_total") or 0),
        "requested_model": requested,
        "configured_fallback_model": fallback,
        "actual_model": actual_model,
        "fallback_used": plan.get("fallback_used") is True,
        "fallback_attempts": list(plan.get("fallback_attempts") or []),
        "request_prompt_hashes": request_hashes,
        "prompt_sha256": prompt_sha256,
        "same_prompt_hash_for_every_network_attempt": requested_hashes_match,
        "message_index": int(state["message_index"]),
        "state_hash_before": state_hash,
        "state_hash_after": stable_state_hash(state),
        "state_preserved": state_hash == stable_state_hash(state),
        "capability_profile_after": dict(plan.get("capability_profile") or {}),
        "response_present": bool(answer),
        "response_preview": answer[:240],
        "valid": valid,
    }
    target = write_live_evidence_file(output, payload)
    payload["output"] = str(target)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a redacted live same-provider fallback/state-integrity proof."
    )
    parser.add_argument("--provider-id", type=int, required=True)
    parser.add_argument("--provider-code", required=True)
    parser.add_argument("--requested-model", required=True)
    parser.add_argument("--fallback-model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_live_fallback_evidence(
        provider_id=args.provider_id,
        provider_code=args.provider_code,
        requested_model=args.requested_model,
        fallback_model=args.fallback_model,
        output=args.output,
        timeout=args.timeout,
    )
    print(
        json.dumps(
            {
                key: payload.get(key)
                for key in (
                    "artifact_type",
                    "provider_code",
                    "requested_model",
                    "configured_fallback_model",
                    "actual_model",
                    "fallback_used",
                    "fallback_attempts",
                    "same_prompt_hash_for_every_network_attempt",
                    "state_preserved",
                    "valid",
                    "output",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
