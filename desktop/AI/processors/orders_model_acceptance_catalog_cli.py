from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.pipeline import (
    get_provider_account,
    list_provider_accounts,
    list_provider_models,
)
from AI.processors.provider_catalog_policy import provider_model_access


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact_coverage(artifact_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    coverage: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(artifact_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        provider = _text(payload.get("provider_code")).casefold()
        model = _text(payload.get("requested_model")).removeprefix("models/")
        if not provider or not model:
            continue
        row = {
            "artifact": path.name,
            "turn_count": int(payload.get("turn_count") or 0),
            "reviewed_turn_count": int(
                (payload.get("human_review") or {}).get("reviewed_turn_count") or 0
            ),
            "passed": bool(payload.get("passed")),
        }
        key = (provider, model)
        current = coverage.get(key)
        if current is None or (
            int(row["turn_count"]),
            int(row["reviewed_turn_count"]),
            bool(row["passed"]),
        ) > (
            int(current["turn_count"]),
            int(current["reviewed_turn_count"]),
            bool(current["passed"]),
        ):
            coverage[key] = row
    return coverage


def _probe_coverage(artifact_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    coverage: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(artifact_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (
            not isinstance(payload, dict)
            or _text(payload.get("artifact_type"))
            != "orders_exact_model_accessibility_probe"
        ):
            continue
        generated_at = _text(payload.get("generated_at"))
        for source in list(payload.get("records") or []):
            if not isinstance(source, dict):
                continue
            provider = _text(source.get("provider_code")).casefold()
            model = _text(source.get("requested_model")).removeprefix("models/")
            if not provider or not model:
                continue
            row = {
                "artifact": path.name,
                "generated_at": generated_at,
                "accessible": bool(source.get("accessible")),
                "exact_model_responded": bool(source.get("exact_model_responded")),
                "fallback_allowed": bool(source.get("fallback_allowed")),
                "actual_model": _text(source.get("actual_model")).removeprefix("models/"),
                "error_type": _text(source.get("error_type")),
                "error": _text(source.get("error")),
                "accessibility_status": _text(
                    source.get("accessibility_status")
                ),
                "error_category": _text(source.get("error_category")),
                "quota_scope": _text(source.get("quota_scope")),
                "status_code": source.get("status_code"),
                "model_fallback_allowed": source.get(
                    "model_fallback_allowed"
                ),
                "fallback_blocked_reason": _text(
                    source.get("fallback_blocked_reason")
                ),
                "retry_after_seconds": source.get("retry_after_seconds"),
            }
            key = (provider, model)
            current = coverage.get(key)
            if current is None or (
                row["generated_at"],
                row["artifact"],
            ) > (
                current["generated_at"],
                current["artifact"],
            ):
                coverage[key] = row
    return coverage


def _gemini_classification(model_id: str) -> tuple[str, str]:
    access = provider_model_access("gemini", model_id)
    if not access.chat_eligible:
        return (
            "excluded_specialized_non_chat",
            "Normal text-chat/Orders acceptance surface is not this model's primary API contract.",
        )
    if not access.is_free:
        return "excluded_not_verified_free", "Model is not in the reviewed free-tier policy."
    return "chat_candidate", "Verified-free general chat candidate returned by the enabled account catalog."


def _openrouter_classification(model_id: str) -> tuple[str, str]:
    lowered = model_id.casefold()
    if "content-safety" in lowered:
        return (
            "excluded_specialized_non_chat",
            "Safety classifier is not a general conversational Orders model.",
        )
    if "-vl" in lowered or "omni" in lowered:
        return "specialized_chat_candidate", "Vision/omni model that also exposes text generation."
    return "chat_candidate", "Free text-generation candidate returned by OpenRouter."


def build_catalog(*, artifact_dir: Path) -> dict[str, Any]:
    coverage = _artifact_coverage(artifact_dir)
    probes = _probe_coverage(artifact_dir)
    accounts_result = list_provider_accounts(include_secret=False)
    if not accounts_result.success:
        raise RuntimeError(accounts_result.message)
    providers: list[dict[str, Any]] = []
    for summary in list((accounts_result.data or {}).get("records") or []):
        if not isinstance(summary, dict) or not bool(summary.get("is_enabled")):
            continue
        provider = _text(summary.get("provider_code")).casefold()
        if provider not in {"gemini", "openrouter"}:
            continue
        detail = get_provider_account(int(summary.get("id") or 0))
        if not detail.success:
            raise RuntimeError(detail.message)
        record = dict((detail.data or {}).get("record") or {})
        catalog = list_provider_models(
            provider_code=provider,
            endpoint_url=_text(record.get("endpoint_url")),
            api_key=_text(record.get("api_key")),
            free_only=True,
            limit=500,
        )
        if not catalog.success:
            providers.append(
                {
                    "provider_code": provider,
                    "catalog_success": False,
                    "message": catalog.message,
                    "models": [],
                }
            )
            continue
        route_payload = dict(
            (catalog.data or {}).get("free_model_test_route") or {}
        )
        route_rows = [
            dict(row)
            for row in list(route_payload.get("models") or [])
            if isinstance(row, dict)
        ]
        route_by_model = {
            _text(row.get("model_id") or row.get("id")).removeprefix("models/"): {
                **row,
                "route_rank": index + 1,
            }
            for index, row in enumerate(route_rows)
            if _text(row.get("model_id") or row.get("id"))
        }
        models: list[dict[str, Any]] = []
        for source in list((catalog.data or {}).get("records") or []):
            if not isinstance(source, dict):
                continue
            model_id = _text(source.get("id")).removeprefix("models/")
            if not model_id:
                continue
            classification, reason = (
                _gemini_classification(model_id)
                if provider == "gemini"
                else _openrouter_classification(model_id)
            )
            evidence = coverage.get((provider, model_id), {})
            probe = probes.get((provider, model_id), {})
            capability = dict(source.get("capability_profile") or {})
            route_row = dict(route_by_model.get(model_id) or {})
            route_metadata = dict(route_row.get("metadata") or {})
            long_human_passed = bool(
                evidence.get("passed")
                and int(evidence.get("turn_count") or 0) >= 20
                and int(evidence.get("reviewed_turn_count") or 0)
                == int(evidence.get("turn_count") or 0)
            )
            if classification == "excluded_specialized_non_chat":
                acceptance = "excluded_specialized_non_chat"
            elif long_human_passed:
                acceptance = "long_human_passed"
            elif probe.get("accessible"):
                acceptance = "accessible_pending_long_human"
            elif probe:
                acceptance = "currently_unavailable_or_quota_limited"
            else:
                acceptance = "unprobed"
            accessibility_status = (
                _text(probe.get("accessibility_status"))
                or (
                    "accessible"
                    if probe.get("accessible")
                    else "currently_unavailable_or_quota_limited"
                    if probe
                    else "proven_by_long_human"
                    if long_human_passed
                    else "unprobed"
                )
            )
            models.append(
                {
                    "id": model_id,
                    "name": _text(source.get("name")),
                    "classification": classification,
                    "classification_reason": reason,
                    "acceptance_status": acceptance,
                    "accessibility_status": accessibility_status,
                    "accessibility_evidence": probe,
                    "human_evidence": evidence,
                    "free_tier_status": _text(source.get("free_tier_status")),
                    "pricing_policy_source": _text(source.get("pricing_policy_source")),
                    "pricing_policy_reviewed_at": _text(source.get("pricing_policy_reviewed_at")),
                    "supports_native_tools": bool(
                        capability.get("native_tool_calling_available")
                    ),
                    "supports_structured_output": bool(
                        capability.get("structured_output_available")
                    ),
                    "supports_reasoning": bool(
                        (capability.get("reasoning") or {}).get("supported")
                    ),
                    "quality_tier": int(route_row.get("quality_tier") or 0),
                    "quality_evidence_score": float(
                        route_row.get("quality_score") or 0.0
                    ),
                    "quality_source": _text(
                        route_metadata.get("quality_source")
                    ),
                    "quality_reviewed_at": _text(
                        route_metadata.get("quality_reviewed_at")
                    ),
                    "route_rank": int(route_row.get("route_rank") or 0),
                }
            )
        models.sort(
            key=lambda row: (
                int(row.get("route_rank") or 0) <= 0,
                int(row.get("route_rank") or 0) or 1_000_000,
                _text(row.get("id")).casefold(),
            )
        )
        current_chat_rows = [
            row for row in models if "chat_candidate" in row["classification"]
        ]
        providers.append(
            {
                "provider_code": provider,
                "catalog_success": True,
                "model_count": len(models),
                "chat_candidate_count": sum(
                    1 for row in models if "chat_candidate" in row["classification"]
                ),
                "long_human_passed_count": sum(
                    1 for row in models if row["acceptance_status"] == "long_human_passed"
                ),
                "accessible_pending_long_human_count": sum(
                    1
                    for row in models
                    if row["acceptance_status"] == "accessible_pending_long_human"
                ),
                "currently_unavailable_or_quota_limited_count": sum(
                    1
                    for row in models
                    if row["acceptance_status"]
                    == "currently_unavailable_or_quota_limited"
                ),
                "preferred_free_model": _text(
                    (route_payload.get("model_ids") or [""])[0]
                    if route_payload.get("model_ids")
                    else ""
                ),
                "free_model_route_state_hash": _text(
                    route_payload.get("state_hash")
                ),
                "free_model_route_generated_from_live_catalog": (
                    route_payload.get("generated_from_live_catalog") is True
                ),
                "current_accessible_acceptance_complete": bool(current_chat_rows)
                and all(
                    row["acceptance_status"]
                    in {"long_human_passed", "currently_unavailable_or_quota_limited"}
                    for row in current_chat_rows
                ),
                "models": models,
            }
        )
    return {
        "name": "orders-free-model-acceptance-catalog",
        "generated_at": _now(),
        "source": "enabled provider accounts via OrderScout provider catalog pipeline",
        "secrets_included": False,
        "minimum_human_turns": 20,
        "providers": providers,
        "completion_rule": (
            "Every accessible chat candidate needs an exact-model, fallback-disabled, "
            "human-directed Orders conversation of at least 20 reviewed turns. Specialized "
            "non-chat entries are cataloged but not misrepresented as chat acceptance."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the secret-free live free-model Orders acceptance catalog."
    )
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = build_catalog(artifact_dir=Path(args.artifact_dir))
    write_live_evidence_file(Path(args.output), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
