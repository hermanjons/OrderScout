from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from AI.processors.cloud_runtime import provider_invocation_provenance
from AI.processors.orders_live_human_eval_cli import _build_exact_client


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_error(exc: Exception) -> str:
    text = _compact_text(exc)
    text = re.sub(
        r"(?i)\b(key|api_key|token|authorization)=([^&\s]+)",
        r"\1=***",
        text,
    )
    text = re.sub(
        r"(?i)\b(authorization\s*:\s*bearer)\s+([^\s,;]+)",
        r"\1 ***",
        text,
    )
    return text[:1200]


def _safe_invocation_evidence(client: Any) -> dict[str, Any]:
    """Project only normalized, secret-safe provider facts from the exact probe."""

    if client is None:
        return {}
    runtime_plan = dict(getattr(client, "resource_plan", {}) or {})
    provenance = provider_invocation_provenance(runtime_plan)
    normalized_errors = [
        {
            key: value
            for key, value in dict(row).items()
            if key
            in {
                "provider_code",
                "category",
                "retryable",
                "quota_scope",
                "status_code",
                "safe_message",
                "model_fallback_allowed",
                "retry_after_seconds",
            }
        }
        for row in list(provenance.get("normalized_error_history") or [])
        if isinstance(row, dict)
    ]
    same_model_retries = [
        {
            key: value
            for key, value in dict(row).items()
            if key
            in {
                "model",
                "attempt",
                "reason",
                "quota_scope",
                "wait_seconds",
            }
        }
        for row in list(runtime_plan.get("same_model_retry_events") or [])
        if isinstance(row, dict)
    ]
    return {
        "invocation_error_reason": _compact_text(
            provenance.get("final_invocation_error_reason")
        ),
        "error_category": _compact_text(provenance.get("final_error_category")),
        "quota_scope": _compact_text(provenance.get("final_quota_scope")),
        "status_code": provenance.get("final_status_code"),
        "model_fallback_allowed": provenance.get(
            "final_model_fallback_allowed"
        ),
        "fallback_blocked_reason": _compact_text(
            provenance.get("final_fallback_blocked_reason")
        ),
        "retry_after_seconds": provenance.get("final_retry_after_seconds"),
        "normalized_error_history": normalized_errors,
        "same_model_retry_events": same_model_retries,
        "invocation_outcome_count": len(
            list(provenance.get("invocation_outcome_history") or [])
        ),
    }


def _accessibility_status(row: dict[str, Any]) -> str:
    if row.get("accessible") is True:
        return "accessible"
    status_code = row.get("status_code")
    category = _compact_text(row.get("error_category")).casefold()
    scope = _compact_text(row.get("quota_scope")).casefold()
    if status_code == 402 or category == "billing":
        return "billing_limited"
    if status_code == 429 or category == "quota" or scope:
        return "quota_limited"
    return "unavailable"


def probe_models(
    *,
    provider: str,
    models: Sequence[str],
    timeout: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for model in models:
        started = datetime.now(timezone.utc)
        client: Any = None
        row: dict[str, Any] = {
            "provider_code": provider,
            "requested_model": model,
            "fallback_allowed": False,
        }
        try:
            client, _record, is_local = _build_exact_client(
                provider,
                model,
                timeout=timeout,
                max_rate_limit_wait_seconds=0,
            )
            response = _compact_text(
                client(
                    'Bu bir erişilebilirlik kontrolüdür. Yalnızca "ERİŞİLEBİLİR" yaz.'
                )
            )
            runtime_plan = dict(getattr(client, "resource_plan", {}) or {})
            actual_model = _compact_text(runtime_plan.get("actual_model"))
            exact = (
                bool(actual_model)
                and actual_model.removeprefix("models/")
                == model.removeprefix("models/")
            )
            row.update(
                {
                    "accessible": bool(response) and exact,
                    "exact_model_responded": exact,
                    "actual_model": actual_model,
                    "fallback_used": bool(runtime_plan.get("fallback_used")),
                    "response_present": bool(response),
                    "response_preview": response[:120],
                    "is_local": bool(is_local),
                }
            )
            row.update(_safe_invocation_evidence(client))
        except Exception as exc:
            row.update(
                {
                    "accessible": False,
                    "exact_model_responded": False,
                    "error_type": type(exc).__name__,
                    "error": _safe_error(exc),
                }
            )
            row.update(_safe_invocation_evidence(client))
        row["accessibility_status"] = _accessibility_status(row)
        row["elapsed_seconds"] = round(
            (datetime.now(timezone.utc) - started).total_seconds(),
            3,
        )
        rows.append(row)
    return {
        "artifact_type": "orders_exact_model_accessibility_probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_code": provider,
        "fallback_allowed": False,
        "probe_is_long_acceptance": False,
        "records": rows,
        "summary": {
            "probed": len(rows),
            "accessible": sum(bool(row.get("accessible")) for row in rows),
            "quota_limited": sum(
                row.get("accessibility_status") == "quota_limited" for row in rows
            ),
            "billing_limited": sum(
                row.get("accessibility_status") == "billing_limited" for row in rows
            ),
            "unavailable": sum(
                row.get("accessibility_status") == "unavailable" for row in rows
            ),
            "unavailable_or_quota_limited": sum(
                not bool(row.get("accessible")) for row in rows
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe exact provider models without fallback and persist redacted evidence."
    )
    parser.add_argument("--provider", required=True, choices=("gemini", "openrouter"))
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = probe_models(
        provider=args.provider,
        models=args.models,
        timeout=max(5.0, float(args.timeout)),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
