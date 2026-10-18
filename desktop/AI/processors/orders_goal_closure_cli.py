from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors import (
    acceptance_manifest,
    architecture_boundary,
    domain_runtime_source_app_recheck_cli,
    operation_runtime,
    orders_source_ui_human_recheck_cli,
)
from Feedback.processors.pipeline import Result, map_error_to_message


DEFAULT_CHECKLIST_PATH = AI_PACKAGE_ROOT / "docs" / "orders_agentic_goal_closure_checklist.json"
COMPLETION_STATUSES = {"proven"}
READINESS_ONLY_STATUSES = {"proven_readiness_only"}
GOAL_SECTION_COMPLETION_STATUSES = {
    "proven",
    "proven_for_orders_scope",
    "proven_with_deferred_external",
    "honored_post_orders_scope",
}
REQUIRED_ORDERS_STAGING_ACTION_TYPES = (
    "orders.change_order_cargo_provider",
    "orders.change_orders_cargo_provider_bulk",
    "orders.approve_return_claim",
)
SOURCE_UI_ACCEPTANCE_ITEM_IDS = (
    "source_ui_real_conversation_reproduction",
    "source_ui_full_history_analysis_reproduction",
)
REAL_USER_REGRESSION_ARTIFACT_TYPE = "orders_real_user_regression"
REAL_USER_REGRESSION_OPEN_STATUSES = {"failed", "open", "reopened", "unresolved"}
REAL_USER_REGRESSION_RESOLVED_STATUSES = {"resolved", "verified"}


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _load_checklist(path: str | Path | None = None) -> dict[str, Any]:
    checklist_path = Path(path) if path not in (None, "") else DEFAULT_CHECKLIST_PATH
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Orders goal closure checklist JSON object olmali.")
    payload["_checklist_path"] = str(checklist_path)
    return payload


def _resolve_checklist_evidence_path(checklist_path: Path, reference: str) -> Path | None:
    relative = Path(reference)
    candidates = (
        checklist_path.parent / relative,
        checklist_path.parent / "live_llm_transcripts" / relative,
    )
    return next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)


def _parse_utc_timestamp(value: Any) -> datetime | None:
    text = _compact_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _validate_real_user_regression_evidence(checklist: dict[str, Any]) -> dict[str, Any]:
    config = (
        dict(checklist.get("real_user_regression_validation") or {})
        if isinstance(checklist.get("real_user_regression_validation"), dict)
        else {}
    )
    required = config.get("required") is True
    result: dict[str, Any] = {
        "required": required,
        "valid": not required,
        "artifacts": [],
        "unresolved_ids": [],
        "newest_observed_at": "",
        "problems": [],
    }
    if not required:
        return result

    references = [
        _compact_text(value)
        for value in list(config.get("artifacts") or [])
        if _compact_text(value)
    ]
    if not references:
        result["problems"].append("missing_artifact_references")
        return result

    checklist_path = Path(_compact_text(checklist.get("_checklist_path")))
    require_resolution_contract = (
        config.get("require_invariant_resolution_contract") is True
    )
    desktop_root = checklist_path.parent.parent.parent
    seen_ids: set[str] = set()
    newest_observed_at: datetime | None = None
    for reference in references:
        artifact_path = _resolve_checklist_evidence_path(checklist_path, reference)
        row: dict[str, Any] = {
            "reference": reference,
            "path": str(artifact_path) if artifact_path is not None else "",
            "valid": False,
            "problems": [],
        }
        if artifact_path is None:
            row["problems"].append("missing_artifact")
            result["artifacts"].append(row)
            continue
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception as exc:
            row["problems"].append(f"invalid_json:{type(exc).__name__}")
            result["artifacts"].append(row)
            continue
        if not isinstance(payload, dict):
            row["problems"].append("artifact_not_object")
            result["artifacts"].append(row)
            continue

        regression_id = _compact_text(payload.get("regression_id"))
        status = _compact_text(payload.get("status")).casefold()
        observed_at = _parse_utc_timestamp(payload.get("observed_at"))
        failures = [value for value in list(payload.get("invariant_failures") or []) if isinstance(value, dict)]
        failure_ids = {
            _compact_text(value.get("id"))
            for value in failures
            if _compact_text(value.get("id"))
        }
        resolution_contract = [
            dict(value)
            for value in list(payload.get("invariant_resolution_contract") or [])
            if isinstance(value, dict)
        ]
        row.update(
            {
                "artifact_type": _compact_text(payload.get("artifact_type")),
                "regression_id": regression_id,
                "status": status,
                "observed_at": _compact_text(payload.get("observed_at")),
                "redacted": payload.get("redacted") is True,
                "invariant_failure_count": len(failures),
                "invariant_resolution_contract_count": len(resolution_contract),
            }
        )
        if row["artifact_type"] != REAL_USER_REGRESSION_ARTIFACT_TYPE:
            row["problems"].append("artifact_type")
        if not regression_id:
            row["problems"].append("regression_id")
        elif regression_id in seen_ids:
            row["problems"].append("duplicate_regression_id")
        else:
            seen_ids.add(regression_id)
        if observed_at is None:
            row["problems"].append("observed_at")
        elif newest_observed_at is None or observed_at > newest_observed_at:
            newest_observed_at = observed_at
        if payload.get("redacted") is not True:
            row["problems"].append("redaction_required")
        if not failures:
            row["problems"].append("invariant_failures")
        if require_resolution_contract:
            contract_ids = [
                _compact_text(value.get("invariant_id"))
                for value in resolution_contract
                if _compact_text(value.get("invariant_id"))
            ]
            if not resolution_contract:
                row["problems"].append("invariant_resolution_contract")
            if len(contract_ids) != len(set(contract_ids)):
                row["problems"].append("duplicate_invariant_resolution_contract")
            if set(contract_ids) != failure_ids:
                row["problems"].append("invariant_resolution_contract_ids")
            guard_test_count = 0
            for contract in resolution_contract:
                invariant_id = _compact_text(contract.get("invariant_id")) or "unknown"
                if not _compact_text(contract.get("owner_layer")):
                    row["problems"].append(
                        f"invariant_resolution_owner_layer:{invariant_id}"
                    )
                if not _compact_text(contract.get("bounded_status")):
                    row["problems"].append(
                        f"invariant_resolution_bounded_status:{invariant_id}"
                    )
                if not _compact_text(contract.get("live_acceptance_gate")):
                    row["problems"].append(
                        f"invariant_resolution_live_gate:{invariant_id}"
                    )
                guard_tests = [
                    _compact_text(value)
                    for value in list(contract.get("guard_tests") or [])
                    if _compact_text(value)
                ]
                guard_test_count += len(guard_tests)
                if not guard_tests:
                    row["problems"].append(
                        f"invariant_resolution_guard_tests:{invariant_id}"
                    )
                for guard_test in guard_tests:
                    test_path_text = guard_test.split("::", 1)[0].replace("\\", "/")
                    test_path = desktop_root / test_path_text
                    if not test_path_text.startswith("tests/") or not test_path.is_file():
                        row["problems"].append(
                            f"invariant_resolution_guard_test_path:{invariant_id}"
                        )
            row["invariant_resolution_guard_test_count"] = guard_test_count
        if status not in REAL_USER_REGRESSION_OPEN_STATUSES | REAL_USER_REGRESSION_RESOLVED_STATUSES:
            row["problems"].append("status")
        if status in REAL_USER_REGRESSION_RESOLVED_STATUSES:
            resolution = payload.get("resolution") if isinstance(payload.get("resolution"), dict) else {}
            resolved_at = _parse_utc_timestamp(resolution.get("resolved_at"))
            evidence = [_compact_text(value) for value in list(resolution.get("evidence") or []) if _compact_text(value)]
            regression_tests = [
                _compact_text(value)
                for value in list(resolution.get("regression_tests") or [])
                if _compact_text(value)
            ]
            if resolved_at is None or (observed_at is not None and resolved_at <= observed_at):
                row["problems"].append("resolution_timestamp")
            if not evidence:
                row["problems"].append("resolution_evidence")
            if not regression_tests:
                row["problems"].append("resolution_regression_tests")
        elif status in REAL_USER_REGRESSION_OPEN_STATUSES and regression_id:
            result["unresolved_ids"].append(regression_id)

        row["valid"] = not row["problems"]
        result["artifacts"].append(row)

    result["problems"] = sorted(
        {
            problem
            for row in result["artifacts"]
            for problem in list(row.get("problems") or [])
        }
    )
    if newest_observed_at is not None:
        result["newest_observed_at"] = newest_observed_at.isoformat().replace("+00:00", "Z")
    result["unresolved_ids"] = sorted(set(result["unresolved_ids"]))
    result["valid"] = not result["problems"]
    return result


def _validate_source_ui_checklist_evidence(
    checklist: dict[str, Any],
    items: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    config = (
        dict(checklist.get("source_ui_acceptance_validation") or {})
        if isinstance(checklist.get("source_ui_acceptance_validation"), dict)
        else {}
    )
    required = config.get("required") is True
    result: dict[str, Any] = {"required": required, "items": {}, "problems": []}
    if not required:
        return result

    checklist_path = Path(_compact_text(checklist.get("_checklist_path")))
    docs_root = checklist_path.parent
    transcript_root = docs_root / "live_llm_transcripts"
    minimum_valid = max(1, int(config.get("minimum_valid_artifacts_per_item") or 3))
    minimum_models = max(1, int(config.get("minimum_distinct_models_per_item") or 3))
    configured_item_ids = [
        _compact_text(value)
        for value in list(config.get("item_ids") or [])
        if _compact_text(value)
    ]
    item_ids = tuple(configured_item_ids or SOURCE_UI_ACCEPTANCE_ITEM_IDS)
    required_provider_codes = {
        _compact_text(value).casefold()
        for value in list(config.get("required_provider_codes") or [])
        if _compact_text(value)
    }
    required_models = {
        _compact_text(value).casefold().removeprefix("models/")
        for value in list(config.get("required_models") or [])
        if _compact_text(value)
    }
    aggregate_problems: list[str] = []

    for item_id in item_ids:
        item = items.get(item_id) or {}
        minimum_turns = max(
            1,
            int(
                item.get("minimum_turns")
                or config.get("minimum_turns")
                or 20
            ),
        )
        require_fresh_execute = bool(
            item.get(
                "require_fresh_execute",
                config.get("require_fresh_execute", True),
            )
        )
        minimum_evidence_contract_version = max(
            3,
            int(
                item.get("minimum_evidence_contract_version")
                or config.get("minimum_evidence_contract_version")
                or 3
            ),
        )
        require_current_runtime_source = bool(
            item.get(
                "require_current_runtime_source",
                config.get(
                    "require_current_runtime_source",
                    bool(configured_item_ids),
                ),
            )
        )
        references = [
            _compact_text(value)
            for value in list(item.get("evidence") or [])
            if _compact_text(value).casefold().endswith(".json")
        ]
        candidates: list[Path] = []
        for reference in references:
            relative = Path(reference)
            for candidate in (docs_root / relative, transcript_root / relative):
                if candidate.exists() and candidate.is_file() and candidate not in candidates:
                    candidates.append(candidate)

        artifact_rows: list[dict[str, Any]] = []
        valid_models: set[str] = set()
        valid_model_sources: list[dict[str, str]] = []
        for candidate in candidates:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception as exc:
                artifact_rows.append(
                    {"path": str(candidate), "valid": False, "problems": [f"invalid_json:{type(exc).__name__}"]}
                )
                continue
            if not isinstance(payload, dict) or payload.get("artifact_type") != "real_source_ui_human_directed":
                continue
            artifact_problems = orders_source_ui_human_recheck_cli.validate_source_ui_acceptance_artifact(
                payload,
                require_fresh_execute=require_fresh_execute,
                require_current_runtime_source=require_current_runtime_source,
                minimum_turns=minimum_turns,
                semantic_contract=item_id,
            )
            if int(payload.get("evidence_contract_version") or 0) < minimum_evidence_contract_version:
                artifact_problems.append("minimum_evidence_contract_version")
            model = _compact_text(payload.get("requested_model")).casefold().removeprefix("models/")
            valid = not artifact_problems
            if valid and model:
                valid_models.add(model)
                valid_model_sources.append(
                    {
                        "model": model,
                        "provider_code": _compact_text(payload.get("provider_code")).casefold(),
                    }
                )
            artifact_rows.append(
                {
                    "path": str(candidate),
                    "requested_model": model,
                    "valid": valid,
                    "problems": artifact_problems,
                }
            )

        valid_count = sum(1 for row in artifact_rows if row.get("valid") is True)
        item_problems: list[str] = []
        if valid_count < minimum_valid:
            item_problems.append("minimum_valid_artifacts")
        if len(valid_models) < minimum_models:
            item_problems.append("minimum_distinct_models")
        if configured_item_ids:
            observed_provider_codes = {
                row.get("provider_code")
                for row in valid_model_sources
                if row.get("provider_code")
            }
            required_model_coverage = {
                "required_provider_codes": sorted(required_provider_codes),
                "observed_provider_codes": sorted(observed_provider_codes),
                "required_models": sorted(required_models),
                "observed_models": sorted(valid_models),
            }
            if not required_provider_codes.issubset(observed_provider_codes):
                item_problems.append("required_provider_coverage")
            if not required_models.issubset(valid_models):
                item_problems.append("required_model_coverage")
        else:
            required_exact_gemini = (
                "gemini-2.5-flash-lite"
                if item_id == "source_ui_real_conversation_reproduction"
                else "gemini-2.5-flash"
            )
            has_exact_gemini = any(
                row.get("provider_code") == "gemini" and row.get("model") == required_exact_gemini
                for row in valid_model_sources
            )
            has_stronger_gemini = any(
                row.get("provider_code") == "gemini" and row.get("model") != required_exact_gemini
                for row in valid_model_sources
            )
            has_openrouter = any(
                row.get("provider_code") == "openrouter"
                for row in valid_model_sources
            )
            required_model_coverage = {
                "exact_gemini": required_exact_gemini,
                "has_exact_gemini": has_exact_gemini,
                "has_stronger_gemini": has_stronger_gemini,
                "has_openrouter": has_openrouter,
            }
            if not all((has_exact_gemini, has_stronger_gemini, has_openrouter)):
                item_problems.append("required_model_coverage")
        if item_problems:
            aggregate_problems.append(item_id)
        result["items"][item_id] = {
            "valid": not item_problems,
            "minimum_valid_artifacts": minimum_valid,
            "minimum_distinct_models": minimum_models,
            "minimum_turns": minimum_turns,
            "minimum_evidence_contract_version": minimum_evidence_contract_version,
            "require_fresh_execute": require_fresh_execute,
            "require_current_runtime_source": require_current_runtime_source,
            "valid_artifact_count": valid_count,
            "valid_models": sorted(valid_models),
            "valid_model_sources": valid_model_sources,
            "required_model_coverage": required_model_coverage,
            "problems": item_problems,
            "artifacts": artifact_rows,
        }

    result["problems"] = aggregate_problems
    return result


def _truthy_env(name: str) -> bool:
    return _compact_text(os.environ.get(name)).casefold() in {"1", "true", "yes", "on"}


def _is_staging_evidence_artifact(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(payload, dict) and payload.get("artifact_type") == "orders_staging_marketplace_evidence"


def _staging_evidence_candidates(directory: str | Path | None) -> list[Path]:
    directory_text = _compact_text(directory)
    if not directory_text:
        return []
    root = Path(directory_text)
    if not root.exists() or not root.is_dir():
        return []
    ignored_suffixes = (
        ".external-proof.json",
        ".proof.json",
        ".template.json",
        ".prepared-action.json",
        ".action.json",
    )
    ignored_names = {"prepared-action.json", "external-proof-template.json", "closure.json", "checklist.json"}
    return sorted(
        (
            path
            for path in root.glob("*.json")
            if path.is_file()
            and path.name not in ignored_names
            and not any(path.name.endswith(suffix) for suffix in ignored_suffixes)
            and _is_staging_evidence_artifact(path)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _staging_evidence_dir_json_inventory(directory: str | Path | None, *, limit: int = 5) -> dict[str, Any]:
    directory_text = _compact_text(directory)
    if not directory_text:
        return {"json_file_count": 0, "ignored_json_file_count": 0, "ignored_json_files": []}
    root = Path(directory_text)
    if not root.exists() or not root.is_dir():
        return {"json_file_count": 0, "ignored_json_file_count": 0, "ignored_json_files": []}
    json_files = sorted((path for path in root.glob("*.json") if path.is_file()), key=lambda path: path.name.casefold())
    ignored: list[dict[str, str]] = []
    for path in json_files:
        if _is_staging_evidence_artifact(path):
            continue
        artifact_type = ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                artifact_type = _compact_text(payload.get("artifact_type"))
        except Exception as exc:
            artifact_type = f"invalid_json:{type(exc).__name__}"
        ignored.append({"name": path.name, "path": str(path), "artifact_type": artifact_type})
    return {
        "json_file_count": len(json_files),
        "ignored_json_file_count": len(ignored),
        "ignored_json_files": ignored[: max(0, int(limit))],
    }


def _json_file_summary(path: str | Path | None) -> dict[str, str]:
    path_text = _compact_text(path)
    if not path_text:
        return {"path": "", "artifact_type": ""}
    file_path = Path(path_text)
    summary = {"path": str(file_path), "artifact_type": ""}
    if not file_path.exists() or not file_path.is_file():
        summary["artifact_type"] = "missing"
        return summary
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        summary["artifact_type"] = f"invalid_json:{type(exc).__name__}"
        return summary
    if isinstance(payload, dict):
        summary["artifact_type"] = _compact_text(payload.get("artifact_type")) or "json_object_without_artifact_type"
    else:
        summary["artifact_type"] = type(payload).__name__
    return summary


def _verify_staging_evidence_candidate(
    path: Path,
    *,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    verified = operation_runtime.verify_staging_marketplace_evidence_artifact(
        path,
        idempotency_key=idempotency_key,
        staging_account_id=staging_account_id,
    )
    summary = {
        "path": str(path),
        "success": bool(verified.success),
        "message": verified.message,
    }
    if isinstance(verified.data, dict):
        data = verified.data
        summary["problems"] = list(data.get("problems") or [])
        summary["idempotency_key"] = _compact_text(data.get("idempotency_key"))
        summary["staging_account_id"] = _compact_text(data.get("staging_account_id"))
        summary["action_type"] = _compact_text(data.get("action_type"))
    return bool(verified.success), summary


def _default_manifest_path_for_evidence(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path.with_suffix(".manifest.json")


def _default_external_proof_path_for_evidence(path: str | Path | None) -> str:
    path_text = _compact_text(path)
    if not path_text:
        return ""
    return str(Path(path_text).with_suffix(".external-proof.json"))


def _default_staging_dropzone_path(*parts: str) -> str:
    return str(AI_PACKAGE_ROOT / "docs" / "live_llm_transcripts" / "staging-marketplace" / Path(*parts))


def _staging_plan_cli_args(staging_inputs: dict[str, Any]) -> list[str]:
    campaign_id = "<CAMPAIGN_ID>"
    staging_account_id = _compact_text(staging_inputs.get("staging_account_id")) or "<STAGING_SELLER_ID>"
    campaign_dir = _compact_text(staging_inputs.get("staging_evidence_dir")) or _default_staging_dropzone_path()
    plan_path = str(Path(campaign_dir) / f"{campaign_id}.campaign-plan.json")
    return [
        "--mode",
        "campaign-plan",
        "--plan-path",
        plan_path,
        "--campaign-id",
        campaign_id,
        "--campaign-dir",
        campaign_dir,
        "--staging-reason",
        "<CONTROLLED_STAGING_REASON>",
        "--staging-account-id",
        staging_account_id,
    ]


def _verify_staging_manifest(
    manifest_path: Path | None,
    *,
    evidence_path: Path | None,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    if manifest_path is None:
        return False, None
    verified = operation_runtime.verify_staging_marketplace_evidence_manifest(
        manifest_path,
        evidence_path=evidence_path,
        idempotency_key=idempotency_key,
        staging_account_id=staging_account_id,
    )
    return bool(verified.success), {
        "success": bool(verified.success),
        "message": verified.message,
        "data": verified.data if isinstance(verified.data, dict) else {"value": verified.data},
    }


def _closure_next_actions(
    *,
    ready_to_complete: bool,
    unresolved_blockers: list[str],
    readiness_only_items: list[dict[str, str]],
    incomplete_current_items: list[dict[str, str]],
    missing_scope_items: list[str],
    staging_inputs: dict[str, Any],
    staging_evidence_verified: bool,
    staging_evidence_result: dict[str, Any] | None,
    staging_manifest_verified: bool,
    staging_manifest_result: dict[str, Any] | None,
    staging_campaign_verified: bool,
    verified_staging_action_types: list[str],
    missing_staging_action_types: list[str],
    real_user_regression_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    if ready_to_complete:
        return []
    actions: list[dict[str, Any]] = []
    unresolved_regression_ids = list(real_user_regression_validation.get("unresolved_ids") or [])
    if unresolved_regression_ids:
        actions.append(
            {
                "id": "resolve_latest_real_user_regressions",
                "severity": "blocker",
                "summary": (
                    "Newer real-user failures override older passing evidence. Fix the root cause, add deterministic "
                    "regressions, and re-run the required exact and alternative model acceptance before closure."
                ),
                "regression_ids": unresolved_regression_ids,
                "newest_observed_at": _compact_text(real_user_regression_validation.get("newest_observed_at")),
            }
        )
    if missing_scope_items:
        actions.append(
            {
                "id": "fix_missing_current_scope_items",
                "severity": "error",
                "summary": "Checklist current scope contains ids that are missing from required_items.",
                "items": missing_scope_items,
            }
        )
    if incomplete_current_items:
        actions.append(
            {
                "id": "complete_current_scope_items",
                "severity": "error",
                "summary": "Current Orders scope has unproven items.",
                "items": incomplete_current_items,
            }
        )
    if readiness_only_items:
        readiness_action: dict[str, Any] = {
            "id": "replace_readiness_only_with_verified_evidence",
            "severity": "blocker",
            "summary": "Readiness-only Orders items must be replaced by verified completion evidence before closing.",
            "items": readiness_only_items,
        }
        if staging_campaign_verified:
            apply_args = [
                "--checklist-path",
                _compact_text(staging_inputs.get("checklist_path")),
                "--staging-evidence-dir",
                _compact_text(staging_inputs.get("staging_evidence_dir")),
                "--apply-verified-staging-evidence",
                "--require-complete",
            ]
            staging_account_arg = _compact_text(staging_inputs.get("staging_account_id"))
            if staging_account_arg:
                apply_args.extend(["--staging-account-id", staging_account_arg])
            readiness_action["apply_verified_staging_evidence_cli_args"] = apply_args
        actions.append(readiness_action)
    if "staging_marketplace_guard" in unresolved_blockers:
        if missing_staging_action_types:
            actions.append(
                {
                    "id": "complete_staging_action_evidence_matrix",
                    "severity": "blocker",
                    "summary": "Every external Orders mutation needs its own verified staging evidence and manifest.",
                    "required_action_types": list(REQUIRED_ORDERS_STAGING_ACTION_TYPES),
                    "verified_action_types": verified_staging_action_types,
                    "missing_action_types": missing_staging_action_types,
                }
            )
        if bool(staging_inputs.get("staging_evidence_path_provided")) and not bool(staging_inputs.get("staging_evidence_path_exists")):
            actions.append(
                {
                    "id": "fix_staging_evidence_path",
                    "severity": "blocker",
                    "summary": "The provided staging evidence path does not point to an existing JSON file.",
                    "path": _compact_text(staging_inputs.get("staging_evidence_path")),
                }
            )
        if bool(staging_inputs.get("staging_evidence_dir_provided")) and not bool(staging_inputs.get("staging_evidence_dir_exists")):
            actions.append(
                {
                    "id": "fix_staging_evidence_dir",
                    "severity": "blocker",
                    "summary": "The provided staging evidence directory does not exist or is not a directory.",
                    "path": _compact_text(staging_inputs.get("staging_evidence_dir")),
                }
            )
        if (
            bool(staging_inputs.get("staging_evidence_dir_provided"))
            and bool(staging_inputs.get("staging_evidence_dir_exists"))
            and int(staging_inputs.get("staging_evidence_candidate_count") or 0) == 0
        ):
            json_count = int(staging_inputs.get("staging_evidence_json_file_count") or 0)
            ignored_json_files = list(staging_inputs.get("staging_evidence_ignored_json_files") or [])
            actions.append(
                {
                    "id": "add_staging_evidence_to_dir",
                    "severity": "blocker",
                    "summary": (
                        "The staging evidence directory contains JSON files, but none are orders_staging_marketplace_evidence artifacts."
                        if json_count
                        else "The staging evidence directory exists but contains no JSON evidence artifacts."
                    ),
                    "json_file_count": json_count,
                    "ignored_json_files": ignored_json_files,
                }
            )
        if not bool(staging_inputs.get("env_enabled")):
            actions.append(
                {
                    "id": "enable_staging_marketplace_env",
                    "severity": "blocker",
                    "summary": f"Run the controlled staging shell with {operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV}=1.",
                }
            )
        if not bool(staging_inputs.get("staging_account_id_provided")):
            actions.append(
                {
                    "id": "provide_staging_account_id",
                    "severity": "blocker",
                    "summary": "Provide the controlled staging/sandbox account id and ensure it matches the action target.",
                }
            )
        evidence_available = bool(staging_inputs.get("staging_evidence_path_exists")) or int(staging_inputs.get("staging_evidence_candidate_count") or 0) > 0
        if not evidence_available:
            actions.append(
                {
                    "id": "choose_staging_campaign_id",
                    "severity": "blocker",
                    "summary": "Choose one unique campaign id; the planner derives three distinct action idempotency keys from it.",
                }
            )
            actions.append(
                {
                    "id": "run_staging_evidence_campaign",
                    "severity": "blocker",
                    "summary": "Generate the no-write three-action campaign plan, then execute each validated action package and apply campaign closure.",
                    "runbook": "AI/docs/orders_staging_marketplace_evidence_runbook.md",
                    "plan_cli_args": _staging_plan_cli_args(staging_inputs),
                }
            )
        elif not staging_evidence_verified:
            evidence_summary = _json_file_summary(staging_inputs.get("selected_staging_evidence_path") or staging_inputs.get("staging_evidence_path"))
            actions.append(
                {
                    "id": "fix_staging_evidence_validation",
                    "severity": "blocker",
                    "summary": (
                        "The selected JSON file is not an orders_staging_marketplace_evidence artifact."
                        if evidence_summary.get("artifact_type") and evidence_summary.get("artifact_type") != "orders_staging_marketplace_evidence"
                        else "A staging evidence artifact was provided or found but it did not validate."
                    ),
                    "evidence_file": evidence_summary,
                    "validation": staging_evidence_result,
                }
            )
        elif not staging_manifest_verified:
            if not bool(staging_inputs.get("staging_manifest_path_exists")):
                action_evidence_path = _compact_text(staging_inputs.get("selected_staging_evidence_path") or staging_inputs.get("staging_evidence_path"))
                external_proof_path_hint = _default_external_proof_path_for_evidence(action_evidence_path)
                action_manifest_path = _compact_text(staging_inputs.get("staging_manifest_path"))
                idempotency_arg = _compact_text(staging_inputs.get("idempotency_key"))
                staging_account_arg = _compact_text(staging_inputs.get("staging_account_id"))
                manifest_cli_args = [
                    "--mode",
                    "manifest",
                    "--evidence-path",
                    action_evidence_path,
                    "--external-proof-file",
                    external_proof_path_hint,
                    "--manifest-path",
                    action_manifest_path,
                ]
                verify_manifest_cli_args = [
                    "--mode",
                    "verify-manifest",
                    "--manifest-path",
                    action_manifest_path,
                    "--evidence-path",
                    action_evidence_path,
                ]
                if idempotency_arg:
                    manifest_cli_args.extend(["--idempotency-key", idempotency_arg])
                    verify_manifest_cli_args.extend(["--idempotency-key", idempotency_arg])
                if staging_account_arg:
                    manifest_cli_args.extend(["--staging-account-id", staging_account_arg])
                    verify_manifest_cli_args.extend(["--staging-account-id", staging_account_arg])
                actions.append(
                    {
                        "id": "write_staging_evidence_manifest",
                        "severity": "blocker",
                        "summary": "Write and verify a staging evidence hash manifest next to the evidence artifact.",
                        "manifest_path": action_manifest_path,
                        "evidence_path": action_evidence_path,
                        "external_proof_path_hint": external_proof_path_hint,
                        "external_proof_path_hint_exists": bool(external_proof_path_hint and Path(external_proof_path_hint).exists()),
                        "manifest_cli_args": manifest_cli_args,
                        "verify_manifest_cli_args": verify_manifest_cli_args,
                        "runbook": "AI/docs/orders_staging_marketplace_evidence_runbook.md",
                    }
                )
            else:
                manifest_summary = _json_file_summary(staging_inputs.get("staging_manifest_path"))
                action_manifest_path = _compact_text(staging_inputs.get("staging_manifest_path"))
                action_evidence_path = _compact_text(staging_inputs.get("selected_staging_evidence_path") or staging_inputs.get("staging_evidence_path"))
                verify_manifest_cli_args = [
                    "--mode",
                    "verify-manifest",
                    "--manifest-path",
                    action_manifest_path,
                    "--evidence-path",
                    action_evidence_path,
                ]
                idempotency_arg = _compact_text(staging_inputs.get("idempotency_key"))
                staging_account_arg = _compact_text(staging_inputs.get("staging_account_id"))
                if idempotency_arg:
                    verify_manifest_cli_args.extend(["--idempotency-key", idempotency_arg])
                if staging_account_arg:
                    verify_manifest_cli_args.extend(["--staging-account-id", staging_account_arg])
                actions.append(
                    {
                        "id": "fix_staging_manifest_validation",
                        "severity": "blocker",
                        "summary": (
                            "The selected manifest JSON file is not an orders_staging_marketplace_evidence_manifest artifact."
                            if manifest_summary.get("artifact_type")
                            and manifest_summary.get("artifact_type") != "orders_staging_marketplace_evidence_manifest"
                            else "A staging evidence manifest was found or provided but it did not validate."
                        ),
                        "manifest_file": manifest_summary,
                        "verify_manifest_cli_args": verify_manifest_cli_args,
                        "validation": staging_manifest_result,
                    }
                )
    return actions


def evaluate_orders_goal_closure(
    *,
    checklist_path: str | Path | None = None,
    staging_evidence_path: str | Path | None = None,
    staging_evidence_dir: str | Path | None = None,
    staging_manifest_path: str | Path | None = None,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
) -> Result:
    try:
        checklist = _load_checklist(checklist_path)
        problems: list[str] = []
        warnings: list[str] = []
        evidence_path_text = _compact_text(staging_evidence_path)
        evidence_path = Path(evidence_path_text) if evidence_path_text else None
        evidence_dir_text = _compact_text(staging_evidence_dir)
        manifest_path_text = _compact_text(staging_manifest_path)
        explicit_manifest_path = Path(manifest_path_text) if manifest_path_text else None
        evidence_candidates = _staging_evidence_candidates(evidence_dir_text)
        evidence_dir_inventory = _staging_evidence_dir_json_inventory(evidence_dir_text)
        selected_evidence_path: Path | None = evidence_path
        selected_manifest_path: Path | None = None
        staging_evidence_candidates: list[dict[str, Any]] = []
        scan_paths: list[Path] = []
        if evidence_path is not None:
            scan_paths.append(evidence_path)
        scan_paths.extend(candidate for candidate in evidence_candidates if candidate not in scan_paths)
        first_verified_evidence_path: Path | None = None
        first_verified_manifest_path: Path | None = None
        for candidate in scan_paths:
            is_explicit_candidate = evidence_path is not None and candidate == evidence_path
            expected_key = idempotency_key if is_explicit_candidate else None
            candidate_success, candidate_summary = _verify_staging_evidence_candidate(
                candidate,
                idempotency_key=expected_key,
                staging_account_id=staging_account_id,
            )
            candidate_manifest_path = (
                explicit_manifest_path
                if is_explicit_candidate and explicit_manifest_path is not None
                else _default_manifest_path_for_evidence(candidate)
            )
            candidate_manifest_success = False
            candidate_manifest_summary: dict[str, Any] | None = None
            if candidate_success:
                candidate_manifest_success, candidate_manifest_summary = _verify_staging_manifest(
                    candidate_manifest_path,
                    evidence_path=candidate,
                    idempotency_key=expected_key,
                    staging_account_id=staging_account_id,
                )
                if first_verified_evidence_path is None:
                    first_verified_evidence_path = candidate
                    first_verified_manifest_path = candidate_manifest_path
            candidate_summary["manifest_success"] = candidate_manifest_success
            candidate_summary["manifest_path"] = str(candidate_manifest_path) if candidate_manifest_path is not None else ""
            candidate_summary["manifest"] = candidate_manifest_summary
            staging_evidence_candidates.append(candidate_summary)
            if (
                selected_evidence_path is None
                and candidate_success
                and candidate_manifest_success
            ):
                selected_evidence_path = candidate
                selected_manifest_path = candidate_manifest_path
        if selected_evidence_path is None and first_verified_evidence_path is not None:
            selected_evidence_path = first_verified_evidence_path
            selected_manifest_path = first_verified_manifest_path
        if selected_manifest_path is None:
            selected_manifest_path = explicit_manifest_path or _default_manifest_path_for_evidence(selected_evidence_path)

        verified_staging_evidence_by_action: dict[str, dict[str, Any]] = {}
        for candidate_summary in staging_evidence_candidates:
            action_type = _compact_text(candidate_summary.get("action_type"))
            if (
                action_type in REQUIRED_ORDERS_STAGING_ACTION_TYPES
                and bool(candidate_summary.get("success"))
                and bool(candidate_summary.get("manifest_success"))
                and action_type not in verified_staging_evidence_by_action
            ):
                verified_staging_evidence_by_action[action_type] = {
                    "action_type": action_type,
                    "evidence_path": _compact_text(candidate_summary.get("path")),
                    "manifest_path": _compact_text(candidate_summary.get("manifest_path")),
                    "idempotency_key": _compact_text(candidate_summary.get("idempotency_key")),
                    "staging_account_id": _compact_text(candidate_summary.get("staging_account_id")),
                }
        verified_staging_action_types = [
            action_type
            for action_type in REQUIRED_ORDERS_STAGING_ACTION_TYPES
            if action_type in verified_staging_evidence_by_action
        ]
        missing_staging_action_types = [
            action_type
            for action_type in REQUIRED_ORDERS_STAGING_ACTION_TYPES
            if action_type not in verified_staging_evidence_by_action
        ]
        verified_campaign_rows = [
            verified_staging_evidence_by_action[action_type]
            for action_type in verified_staging_action_types
        ]
        campaign_account_ids = {
            _compact_text(row.get("staging_account_id"))
            for row in verified_campaign_rows
            if _compact_text(row.get("staging_account_id"))
        }
        campaign_idempotency_keys = [
            _compact_text(row.get("idempotency_key"))
            for row in verified_campaign_rows
            if _compact_text(row.get("idempotency_key"))
        ]
        staging_campaign_problems: list[str] = []
        if len(campaign_account_ids) > 1:
            staging_campaign_problems.append("staging_account_mismatch")
        if len(set(campaign_idempotency_keys)) != len(verified_campaign_rows):
            staging_campaign_problems.append("duplicate_idempotency_key")
        staging_campaign_verified = not missing_staging_action_types and not staging_campaign_problems
        staging_inputs = {
            "env": operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV,
            "env_enabled": _truthy_env(operation_runtime.STAGING_MARKETPLACE_MUTATION_ENV),
            "staging_evidence_path_provided": bool(evidence_path_text),
            "staging_evidence_path": evidence_path_text,
            "staging_evidence_path_exists": bool(evidence_path is not None and evidence_path.exists() and evidence_path.is_file()),
            "staging_evidence_dir_provided": bool(evidence_dir_text),
            "staging_evidence_dir": evidence_dir_text,
            "staging_evidence_dir_exists": bool(evidence_dir_text and Path(evidence_dir_text).exists() and Path(evidence_dir_text).is_dir()),
            "staging_evidence_candidate_count": len(evidence_candidates),
            "staging_evidence_json_file_count": int(evidence_dir_inventory.get("json_file_count") or 0),
            "staging_evidence_ignored_json_file_count": int(evidence_dir_inventory.get("ignored_json_file_count") or 0),
            "staging_evidence_ignored_json_files": list(evidence_dir_inventory.get("ignored_json_files") or []),
            "selected_staging_evidence_path": str(selected_evidence_path) if selected_evidence_path is not None else "",
            "staging_manifest_path_provided": bool(manifest_path_text),
            "staging_manifest_path": str(selected_manifest_path) if selected_manifest_path is not None else "",
            "staging_manifest_path_exists": bool(selected_manifest_path is not None and selected_manifest_path.exists() and selected_manifest_path.is_file()),
            "idempotency_key_provided": bool(_compact_text(idempotency_key)),
            "idempotency_key": _compact_text(idempotency_key),
            "staging_account_id_provided": bool(_compact_text(staging_account_id)),
            "staging_account_id": _compact_text(staging_account_id),
            "checklist_path": _compact_text(checklist.get("_checklist_path")),
        }
        current_focus = _compact_text(checklist.get("current_focus"))
        if current_focus != "orders_only":
            problems.append("current_focus")
        current_scope = [_compact_text(item) for item in list(checklist.get("current_orders_scope_required_items") or []) if _compact_text(item)]
        if not current_scope:
            problems.append("current_orders_scope_required_items")
        items = {
            _compact_text(row.get("id")): dict(row)
            for row in list(checklist.get("required_items") or [])
            if isinstance(row, dict) and _compact_text(row.get("id"))
        }
        missing_scope_items = [item_id for item_id in current_scope if item_id not in items]
        if missing_scope_items:
            problems.append("missing_current_scope_items")

        incomplete_current_items: list[dict[str, str]] = []
        readiness_only_items: list[dict[str, str]] = []
        for item_id in current_scope:
            row = items.get(item_id) or {}
            status = _compact_text(row.get("status"))
            if status in READINESS_ONLY_STATUSES:
                readiness_only_items.append({"id": item_id, "status": status})
                continue
            if status not in COMPLETION_STATUSES:
                incomplete_current_items.append({"id": item_id, "status": status or "missing"})
        if incomplete_current_items:
            problems.append("incomplete_current_scope_items")

        source_ui_evidence_validation = _validate_source_ui_checklist_evidence(checklist, items)
        if source_ui_evidence_validation.get("problems"):
            problems.append("source_ui_acceptance_evidence")

        real_user_regression_validation = _validate_real_user_regression_evidence(checklist)
        if real_user_regression_validation.get("problems"):
            problems.append("real_user_regression_evidence")
        if real_user_regression_validation.get("unresolved_ids"):
            problems.append("unresolved_real_user_regressions")

        acceptance_manifest_config = (
            dict(checklist.get("acceptance_manifest_validation") or {})
            if isinstance(checklist.get("acceptance_manifest_validation"), dict)
            else {}
        )
        acceptance_manifest_validation: dict[str, Any] = {
            "required": acceptance_manifest_config.get("required") is True,
            "valid": False,
            "problems": [],
        }
        if acceptance_manifest_validation["required"]:
            manifest_reference = _compact_text(acceptance_manifest_config.get("manifest"))
            checklist_path = Path(_compact_text(checklist.get("_checklist_path")))
            manifest_path = _resolve_checklist_evidence_path(checklist_path, manifest_reference)
            if manifest_path is None:
                acceptance_manifest_validation["problems"] = ["missing_manifest"]
            else:
                acceptance_manifest_validation.update(
                    acceptance_manifest.validate_current_acceptance_manifest(manifest_path)
                )
                acceptance_manifest_validation["path"] = str(manifest_path)
            if not acceptance_manifest_validation.get("valid"):
                problems.append("acceptance_manifest")
            if (
                acceptance_manifest_config.get("require_closure_ready") is True
                and acceptance_manifest_validation.get("ready_for_closure")
                is not True
            ):
                acceptance_manifest_validation.setdefault(
                    "closure_problems",
                    [],
                ).append("acceptance_manifest_not_ready")
                problems.append("acceptance_manifest_not_ready")
        else:
            acceptance_manifest_validation["valid"] = True

        domain_runtime_config = (
            dict(checklist.get("domain_runtime_source_app_validation") or {})
            if isinstance(checklist.get("domain_runtime_source_app_validation"), dict)
            else {}
        )
        domain_runtime_source_app_validation: dict[str, Any] = {
            "required": domain_runtime_config.get("required") is True,
            "valid": False,
            "problems": [],
        }
        if domain_runtime_source_app_validation["required"]:
            evidence_reference = _compact_text(domain_runtime_config.get("evidence"))
            checklist_path = Path(_compact_text(checklist.get("_checklist_path")))
            evidence_candidates = (
                checklist_path.parent / evidence_reference,
                checklist_path.parent / "live_llm_transcripts" / evidence_reference,
            )
            evidence_path = next(
                (candidate for candidate in evidence_candidates if candidate.exists() and candidate.is_file()),
                None,
            )
            if evidence_path is None:
                domain_runtime_source_app_validation["problems"] = ["missing_evidence"]
            else:
                try:
                    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
                    artifact_payload = (
                        dict(evidence_payload.get("data") or {})
                        if isinstance(evidence_payload, dict) and isinstance(evidence_payload.get("data"), dict)
                        else dict(evidence_payload or {})
                    )
                    domain_runtime_source_app_validation["problems"] = (
                        domain_runtime_source_app_recheck_cli.validate_domain_runtime_source_app_artifact(
                            artifact_payload
                        )
                    )
                    domain_runtime_source_app_validation["path"] = str(evidence_path)
                except Exception as exc:
                    domain_runtime_source_app_validation["problems"] = [
                        f"invalid_evidence:{type(exc).__name__}"
                    ]
            domain_runtime_source_app_validation["valid"] = not domain_runtime_source_app_validation["problems"]
            if not domain_runtime_source_app_validation["valid"]:
                problems.append("domain_runtime_source_app_evidence")

        atomic_config = (
            dict(checklist.get("atomic_dry_validation") or {})
            if isinstance(checklist.get("atomic_dry_validation"), dict)
            else {}
        )
        atomic_dry_validation: dict[str, Any] = {"required": atomic_config.get("required") is True}
        if atomic_dry_validation["required"]:
            ai_root = AI_PACKAGE_ROOT
            scan_paths = [ai_root / str(value) for value in list(atomic_config.get("files") or [])]
            atomic_dry_validation.update(architecture_boundary.audit_ai_domain_model_imports(scan_paths))
            if not atomic_dry_validation.get("valid"):
                problems.append("atomic_dry_boundary")

        goals_section_audit_required = bool(checklist.get("goals_section_audit_required"))
        goals_section_audit = [
            dict(row)
            for row in list(checklist.get("goals_section_audit") or [])
            if isinstance(row, dict)
        ]
        goals_section_audit_problems: list[str] = []
        if goals_section_audit_required:
            checklist_path = Path(_compact_text(checklist.get("_checklist_path")))
            goals_path = checklist_path.with_name("goals.md")
            expected_headings: dict[int, str] = {}
            if not goals_path.exists() or not goals_path.is_file():
                goals_section_audit_problems.append("goals_file_missing")
            else:
                goals_text = goals_path.read_text(encoding="utf-8")
                expected_headings = {
                    int(number): _compact_text(title)
                    for number, title in re.findall(
                        r"^##\s+(\d+)\.\s+(.+)$",
                        goals_text,
                        flags=re.MULTILINE,
                    )
                }
                expected_section_numbers = sorted(expected_headings)
                if (
                    not expected_section_numbers
                    or expected_section_numbers != list(range(1, max(expected_section_numbers) + 1))
                ):
                    goals_section_audit_problems.append("goals_headings")

            rows_by_section: dict[int, dict[str, Any]] = {}
            for row in goals_section_audit:
                try:
                    section_number = int(row.get("section"))
                except (TypeError, ValueError):
                    goals_section_audit_problems.append("invalid_section_number")
                    continue
                if section_number in rows_by_section:
                    goals_section_audit_problems.append(f"duplicate_section:{section_number}")
                    continue
                rows_by_section[section_number] = row

            expected_section_number_set = set(expected_headings)
            missing_sections = sorted(expected_section_number_set - set(rows_by_section))
            if missing_sections:
                goals_section_audit_problems.append(
                    "missing_sections:" + ",".join(str(number) for number in missing_sections)
                )
            extra_sections = sorted(set(rows_by_section) - expected_section_number_set)
            if extra_sections:
                goals_section_audit_problems.append(
                    "extra_sections:" + ",".join(str(number) for number in extra_sections)
                )

            for section_number, row in sorted(rows_by_section.items()):
                expected_title = expected_headings.get(section_number)
                if expected_title and _compact_text(row.get("title")) != expected_title:
                    goals_section_audit_problems.append(
                        f"title_mismatch:{section_number}"
                    )
                status = _compact_text(row.get("status"))
                if status not in GOAL_SECTION_COMPLETION_STATUSES:
                    goals_section_audit_problems.append(
                        f"incomplete_section:{section_number}:{status or 'missing'}"
                    )
                evidence = [
                    _compact_text(value)
                    for value in list(row.get("evidence") or [])
                    if _compact_text(value)
                ]
                if not evidence:
                    goals_section_audit_problems.append(
                        f"missing_evidence:{section_number}"
                    )
                if (
                    status == "proven_with_deferred_external"
                    and "staging_marketplace_guard" not in evidence
                ):
                    goals_section_audit_problems.append(
                        f"missing_deferred_external_link:{section_number}"
                    )

            if goals_section_audit_problems:
                problems.append("goals_section_audit")

        checklist_blockers = [_compact_text(item) for item in list(checklist.get("blocking_items") or []) if _compact_text(item)]
        unresolved_blockers = list(checklist_blockers)
        for regression_id in list(real_user_regression_validation.get("unresolved_ids") or []):
            if regression_id not in unresolved_blockers:
                unresolved_blockers.append(regression_id)
        staging_evidence_verified = False
        staging_evidence_result: dict[str, Any] | None = None
        staging_manifest_verified = False
        staging_manifest_result: dict[str, Any] | None = None
        if selected_evidence_path is not None:
            verified = operation_runtime.verify_staging_marketplace_evidence_artifact(
                selected_evidence_path,
                idempotency_key=idempotency_key,
                staging_account_id=staging_account_id,
            )
            staging_evidence_verified = bool(verified.success)
            staging_evidence_result = {
                "success": bool(verified.success),
                "message": verified.message,
                "data": verified.data if isinstance(verified.data, dict) else {"value": verified.data},
            }
            staging_manifest_verified, staging_manifest_result = _verify_staging_manifest(
                selected_manifest_path,
                evidence_path=selected_evidence_path,
                idempotency_key=idempotency_key,
                staging_account_id=staging_account_id,
            )
            if staging_campaign_verified and "staging_marketplace_guard" in unresolved_blockers:
                unresolved_blockers.remove("staging_marketplace_guard")
            elif not staging_evidence_verified:
                problems.append("staging_evidence_invalid")
            elif not staging_manifest_verified:
                problems.append("staging_manifest_invalid")
        elif "staging_marketplace_guard" in checklist_blockers:
            warnings.append("staging_evidence_missing")
        staging_guard_required = "staging_marketplace_guard" in current_scope
        if staging_guard_required and not staging_campaign_verified:
            if "staging_marketplace_guard" not in unresolved_blockers:
                unresolved_blockers.append("staging_marketplace_guard")
            problems.append("staging_action_evidence_incomplete")
            problems.extend(staging_campaign_problems)

        overall_status = _compact_text(checklist.get("overall_status"))
        ready_to_complete = (
            not problems
            and not unresolved_blockers
            and not readiness_only_items
            and overall_status in {"ready", "complete", "proven"}
        )
        if unresolved_blockers:
            problems.append("blocking_items")
        if readiness_only_items:
            problems.append("readiness_only_current_scope_items")
        if not ready_to_complete and overall_status in {"ready", "complete", "proven"} and (problems or unresolved_blockers):
            problems.append("overall_status_premature")
        next_actions = _closure_next_actions(
            ready_to_complete=ready_to_complete,
            unresolved_blockers=unresolved_blockers,
            readiness_only_items=readiness_only_items,
            incomplete_current_items=incomplete_current_items,
            missing_scope_items=missing_scope_items,
            staging_inputs=staging_inputs,
            staging_evidence_verified=staging_evidence_verified,
            staging_evidence_result=staging_evidence_result,
            staging_manifest_verified=staging_manifest_verified,
            staging_manifest_result=staging_manifest_result,
            staging_campaign_verified=staging_campaign_verified,
            verified_staging_action_types=verified_staging_action_types,
            missing_staging_action_types=missing_staging_action_types,
            real_user_regression_validation=real_user_regression_validation,
        )

        data = {
            "ready_to_complete": ready_to_complete,
            "checklist_path": checklist.get("_checklist_path"),
            "overall_status": overall_status,
            "current_focus": current_focus,
            "current_scope": current_scope,
            "blocking_items": checklist_blockers,
            "unresolved_blockers": unresolved_blockers,
            "readiness_only_items": readiness_only_items,
            "incomplete_current_items": incomplete_current_items,
            "missing_current_scope_items": missing_scope_items,
            "source_ui_evidence_validation": source_ui_evidence_validation,
            "real_user_regression_validation": real_user_regression_validation,
            "acceptance_manifest_validation": acceptance_manifest_validation,
            "domain_runtime_source_app_validation": domain_runtime_source_app_validation,
            "atomic_dry_validation": atomic_dry_validation,
            "goals_section_audit_required": goals_section_audit_required,
            "goals_section_audit_count": len(goals_section_audit),
            "goals_section_audit_problems": goals_section_audit_problems,
            "staging_evidence_verified": staging_evidence_verified,
            "staging_evidence": staging_evidence_result,
            "staging_manifest_verified": staging_manifest_verified,
            "staging_manifest": staging_manifest_result,
            "required_staging_action_types": list(REQUIRED_ORDERS_STAGING_ACTION_TYPES),
            "verified_staging_action_types": verified_staging_action_types,
            "missing_staging_action_types": missing_staging_action_types,
            "staging_campaign_verified": staging_campaign_verified,
            "staging_campaign_problems": staging_campaign_problems,
            "staging_campaign_evidence": verified_campaign_rows,
            "staging_evidence_candidates": staging_evidence_candidates,
            "staging_inputs": staging_inputs,
            "warnings": warnings,
            "problems": sorted(set(problems)),
            "next_actions": next_actions,
        }
        message = "Orders goal closure tamamlanmaya hazir." if ready_to_complete else "Orders goal closure henuz tamam degil."
        return Result.ok(message, close_dialog=False, data=data)
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def apply_verified_staging_evidence_to_checklist(
    *,
    checklist_path: str | Path | None = None,
    staging_evidence_path: str | Path | None = None,
    staging_evidence_dir: str | Path | None = None,
    staging_manifest_path: str | Path | None = None,
    idempotency_key: str | None = None,
    staging_account_id: str | None = None,
) -> Result:
    try:
        checklist_target = Path(checklist_path) if checklist_path not in (None, "") else DEFAULT_CHECKLIST_PATH
        before = evaluate_orders_goal_closure(
            checklist_path=checklist_target,
            staging_evidence_path=staging_evidence_path,
            staging_evidence_dir=staging_evidence_dir,
            staging_manifest_path=staging_manifest_path,
            idempotency_key=idempotency_key,
            staging_account_id=staging_account_id,
        )
        if not before.success:
            return before
        before_data = before.data if isinstance(before.data, dict) else {}
        if not bool(before_data.get("staging_campaign_verified")):
            return Result.fail(
                "Uc Orders dis mutasyonunun tamamini kapsayan dogrulanmis staging evidence kampanyasi olmadan checklist guncellenmez.",
                close_dialog=False,
                data={
                    "checklist_path": str(checklist_target),
                    "staging_evidence": before_data.get("staging_evidence"),
                    "required_staging_action_types": before_data.get("required_staging_action_types"),
                    "verified_staging_action_types": before_data.get("verified_staging_action_types"),
                    "missing_staging_action_types": before_data.get("missing_staging_action_types"),
                    "staging_campaign_problems": before_data.get("staging_campaign_problems"),
                    "staging_inputs": before_data.get("staging_inputs"),
                    "next_actions": before_data.get("next_actions"),
                },
            )
        staging_inputs = dict(before_data.get("staging_inputs") or {})
        campaign_evidence = [
            dict(row)
            for row in list(before_data.get("staging_campaign_evidence") or [])
            if isinstance(row, dict)
        ]
        if len(campaign_evidence) != len(REQUIRED_ORDERS_STAGING_ACTION_TYPES):
            return Result.fail(
                "Dogrulanan staging evidence kampanyasi eksik.",
                close_dialog=False,
                data={
                    "checklist_path": str(checklist_target),
                    "staging_campaign_evidence": campaign_evidence,
                    "staging_inputs": staging_inputs,
                },
            )

        checklist = _load_checklist(checklist_target)
        items = list(checklist.get("required_items") or [])
        target_item: dict[str, Any] | None = None
        staging_item_ids = (
            "staging_marketplace_guard",
            "stage_marketplace_campaign_acceptance",
            "stage_bulk_cargo_acceptance",
        )
        for item_id in staging_item_ids:
            target_item = next(
                (
                    row
                    for row in items
                    if isinstance(row, dict)
                    and _compact_text(row.get("id")) == item_id
                ),
                None,
            )
            if target_item is not None:
                break
        if target_item is None:
            return Result.fail(
                "Checklist staging marketplace acceptance item'i icermiyor.",
                close_dialog=False,
                data={
                    "checklist_path": str(checklist_target),
                    "accepted_item_ids": list(staging_item_ids),
                },
            )

        evidence_entries = list(target_item.get("evidence") or [])
        campaign_entries: list[str] = []
        for row in campaign_evidence:
            action_type = _compact_text(row.get("action_type"))
            evidence_path_text = _compact_text(row.get("evidence_path"))
            manifest_path_value = _compact_text(row.get("manifest_path"))
            campaign_entries.extend(
                (
                    f"verified staging evidence ({action_type}): {evidence_path_text}",
                    f"verified staging manifest ({action_type}): {manifest_path_value}",
                )
            )
        for entry in (
            *campaign_entries,
            "AI.processors.staging_marketplace_evidence_cli --mode verify-manifest",
            "AI.processors.orders_goal_closure_cli --apply-verified-staging-evidence",
            "AI.processors.orders_goal_closure_cli --require-complete",
        ):
            if _compact_text(entry) and entry not in evidence_entries:
                evidence_entries.append(entry)
        target_item["status"] = "proven"
        target_item["evidence"] = evidence_entries
        target_item["verified_action_types"] = list(
            REQUIRED_ORDERS_STAGING_ACTION_TYPES
        )
        target_item.pop("missing_to_complete", None)

        blockers = [_compact_text(item) for item in list(checklist.get("blocking_items") or []) if _compact_text(item)]
        checklist["blocking_items"] = [
            item for item in blockers if item not in staging_item_ids
        ]
        checklist["next_evidence_needed"] = [
            item
            for item in list(checklist.get("next_evidence_needed") or [])
            if "staging" not in _compact_text(item).casefold() or "marketplace" not in _compact_text(item).casefold()
        ]
        checklist["updated"] = datetime.now(timezone.utc).date().isoformat()
        checklist.pop("_checklist_path", None)

        current_scope = [_compact_text(item) for item in list(checklist.get("current_orders_scope_required_items") or []) if _compact_text(item)]
        item_by_id = {
            _compact_text(row.get("id")): row
            for row in items
            if isinstance(row, dict) and _compact_text(row.get("id"))
        }
        current_complete = bool(current_scope) and all(
            _compact_text((item_by_id.get(item_id) or {}).get("status")) in COMPLETION_STATUSES
            for item_id in current_scope
        )
        if current_complete and not checklist["blocking_items"]:
            checklist["overall_status"] = "ready"

        checklist_target.write_text(json.dumps(checklist, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

        after = evaluate_orders_goal_closure(
            checklist_path=checklist_target,
            staging_evidence_dir=staging_evidence_dir,
            staging_account_id=staging_account_id,
        )
        after_data = dict(after.data or {}) if isinstance(after.data, dict) else {}
        after_data["checklist_applied"] = True
        after_data["applied_checklist_path"] = str(checklist_target)
        after_data["applied_staging_campaign_evidence"] = campaign_evidence
        return Result.ok(
            "Dogrulanmis staging marketplace evidence checklist'e uygulandi.",
            close_dialog=False,
            data=after_data,
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Orders agentic goal closure readiness.")
    parser.add_argument("--checklist-path", default="", help="Defaults to AI/docs/orders_agentic_goal_closure_checklist.json.")
    parser.add_argument("--staging-evidence-path", default="", help="Optional staging evidence JSON to validate.")
    parser.add_argument("--staging-evidence-dir", default="", help="Optional directory to scan for valid staging evidence JSON artifacts.")
    parser.add_argument("--staging-manifest-path", default="", help="Optional staging evidence manifest JSON; defaults to <evidence>.manifest.json.")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--staging-account-id", default="")
    parser.add_argument("--report-path", default="", help="Optional path to write the closure audit JSON payload.")
    parser.add_argument(
        "--apply-verified-staging-evidence",
        action="store_true",
        help="Only after all required Orders staging actions validate from --staging-evidence-dir: mark the guard proven and re-audit closure.",
    )
    parser.add_argument("--require-complete", action="store_true", help="Exit non-zero unless the Orders goal is ready to mark complete.")
    return parser


def _result_payload(result: Result) -> dict[str, Any]:
    return {
        "success": bool(result.success),
        "message": result.message,
        "data": result.data if isinstance(result.data, dict) else {"value": result.data},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.apply_verified_staging_evidence:
        result = apply_verified_staging_evidence_to_checklist(
            checklist_path=args.checklist_path or None,
            staging_evidence_path=args.staging_evidence_path or None,
            staging_evidence_dir=args.staging_evidence_dir or None,
            staging_manifest_path=args.staging_manifest_path or None,
            idempotency_key=args.idempotency_key or None,
            staging_account_id=args.staging_account_id or None,
        )
    else:
        result = evaluate_orders_goal_closure(
            checklist_path=args.checklist_path or None,
            staging_evidence_path=args.staging_evidence_path or None,
            staging_evidence_dir=args.staging_evidence_dir or None,
            staging_manifest_path=args.staging_manifest_path or None,
            idempotency_key=args.idempotency_key or None,
            staging_account_id=args.staging_account_id or None,
        )
    payload = _result_payload(result)
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    sys.stdout.write("\n")
    if not result.success:
        return 1
    ready = bool((result.data or {}).get("ready_to_complete")) if isinstance(result.data, dict) else False
    if args.require_complete and not ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
