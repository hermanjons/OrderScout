from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from AI.constants.paths import AI_PACKAGE_ROOT


DEFAULT_MANIFEST_PATH = AI_PACKAGE_ROOT / "docs" / "current_acceptance_manifest.json"
EXPECTED_ARTIFACT_TYPE = "orderscout_ai_current_acceptance_manifest"
EXPECTED_SCHEMA_VERSION = 2
EXPECTED_SCOPE_STATUS = "orders_phase_8a_open_ai_goal_open"


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_model_id(value: Any) -> str:
    return _compact_text(value).casefold().removeprefix("models/")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_turn_model_provenance(
    runtime: Mapping[str, Any] | None,
    *,
    requested_model: str = "",
    require_outcome_history: bool = False,
    require_normalized_error_evidence: bool = False,
) -> list[str]:
    """Validate append-only provider facts for one multi-invocation turn."""

    payload = dict(runtime or {})
    outcomes = [
        dict(row)
        for row in list(payload.get("invocation_outcome_history") or [])
        if isinstance(row, dict)
    ]
    attempted = payload.get("model_invocation_attempted") is True
    if require_outcome_history and attempted and not outcomes:
        return ["invocation_outcome_history_missing"]
    if not outcomes:
        if not require_outcome_history:
            return []
        problems: list[str] = []
        if (
            payload.get("model_invoked") is True
            or payload.get("any_model_response_received") is True
            or int(payload.get("model_response_count") or 0) != 0
            or _compact_text(payload.get("actual_model"))
            or _compact_text(payload.get("final_actual_model"))
        ):
            problems.append("model_response_without_outcome_history")
        if payload.get("final_model_response_received") is True:
            problems.append("final_response_without_outcome_history")
        if payload.get("any_model_fallback_used") is True:
            problems.append("fallback_without_outcome_history")
        return problems

    problems: list[str] = []
    contracts = [
        _compact_text(row.get("contract"))
        for row in outcomes
    ]
    if any(not value for value in contracts):
        problems.append("invocation_outcome_contract")
    contract_history = [
        _compact_text(value)
        for value in list(payload.get("invocation_contract_history") or [])
        if _compact_text(value)
    ]
    if contract_history != contracts:
        problems.append("invocation_contract_outcome_mismatch")

    requested = _normalized_model_id(requested_model)
    response_rows: list[dict[str, Any]] = []
    outcome_normalized_errors: list[dict[str, Any]] = []
    for row in outcomes:
        row_requested = _normalized_model_id(row.get("requested_model"))
        actual = _normalized_model_id(row.get("actual_model"))
        received = row.get("response_received") is True
        error = _compact_text(row.get("error_reason"))
        if requested and row_requested != requested:
            problems.append("invocation_requested_model_mismatch")
        if received:
            response_rows.append(row)
            if not actual:
                problems.append("invocation_response_actual_model_missing")
            if error:
                problems.append("invocation_response_with_error")
        elif not error:
            problems.append("invocation_failure_reason_missing")
        if require_normalized_error_evidence:
            required_error_fields = {
                "error_category",
                "quota_scope",
                "status_code",
                "model_fallback_allowed",
                "fallback_blocked_reason",
                "retry_after_seconds",
                "normalized_error_history",
                "fallback_attempts",
            }
            if not required_error_fields.issubset(set(row)):
                problems.append("invocation_normalized_error_fields_missing")
            normalized_errors = [
                dict(value)
                for value in list(row.get("normalized_error_history") or [])
                if isinstance(value, dict)
            ]
            outcome_normalized_errors.extend(normalized_errors)
            safe_error_fields = {
                "provider_code",
                "category",
                "retryable",
                "quota_scope",
                "status_code",
                "safe_message",
                "model_fallback_allowed",
                "retry_after_seconds",
            }
            if any(
                set(value).difference(safe_error_fields)
                for value in normalized_errors
            ):
                problems.append("invocation_normalized_error_unsafe_fields")
            if error == "http_429":
                scope = _compact_text(row.get("quota_scope")).casefold()
                if (
                    _compact_text(row.get("error_category")).casefold()
                    != "quota"
                    or _optional_int(row.get("status_code")) != 429
                    or scope
                    not in {
                        "model",
                        "project",
                        "account",
                        "provider",
                        "unknown",
                    }
                ):
                    problems.append("invocation_429_scope_evidence")
                if not normalized_errors:
                    problems.append("invocation_429_normalized_history")
                if (
                    scope == "model"
                    and row.get("model_fallback_allowed") is not True
                ):
                    problems.append("invocation_model_quota_fallback_policy")
                if (
                    scope != "model"
                    and row.get("model_fallback_allowed") is not False
                ):
                    problems.append("invocation_provider_quota_fallback_policy")
                if (
                    scope != "model"
                    and not _compact_text(row.get("fallback_blocked_reason"))
                ):
                    problems.append("invocation_quota_block_reason")
            if received and (
                _compact_text(row.get("error_category"))
                or _compact_text(row.get("quota_scope"))
                or row.get("status_code") is not None
                or row.get("model_fallback_allowed") is not None
                or _compact_text(row.get("fallback_blocked_reason"))
                or row.get("retry_after_seconds") is not None
            ):
                problems.append("invocation_success_with_final_error")

    response_count = len(response_rows)
    if int(payload.get("model_response_count") or 0) != response_count:
        problems.append("model_response_count")
    any_response = bool(response_rows)
    if bool(payload.get("any_model_response_received")) != any_response:
        problems.append("any_model_response_received")
    if bool(payload.get("model_invoked")) != any_response:
        problems.append("model_invoked_any_response")

    final_received = outcomes[-1].get("response_received") is True
    if bool(payload.get("final_model_response_received")) != final_received:
        problems.append("final_model_response_received")
    if _compact_text(payload.get("invocation_error_reason")) != _compact_text(
        outcomes[-1].get("error_reason")
    ):
        problems.append("final_invocation_error_reason")
    final_actual = _normalized_model_id(payload.get("final_actual_model"))
    expected_final_actual = (
        _normalized_model_id(outcomes[-1].get("actual_model"))
        if final_received
        else ""
    )
    if final_actual != expected_final_actual:
        problems.append("final_actual_model")

    successful_actual = [
        _normalized_model_id(row.get("actual_model"))
        for row in response_rows
        if _normalized_model_id(row.get("actual_model"))
    ]
    expected_actual = successful_actual[-1] if successful_actual else ""
    if _normalized_model_id(payload.get("actual_model")) != expected_actual:
        problems.append("last_successful_actual_model")

    any_fallback = any(bool(row.get("fallback_used")) for row in outcomes)
    if bool(payload.get("any_model_fallback_used")) != any_fallback:
        problems.append("any_model_fallback_used")
    if require_normalized_error_evidence:
        final_row = outcomes[-1]
        required_runtime_fields = {
            "error_category",
            "quota_scope",
            "status_code",
            "model_fallback_allowed",
            "fallback_blocked_reason",
            "retry_after_seconds",
            "normalized_error_history",
        }
        if not required_runtime_fields.issubset(set(payload)):
            problems.append("normalized_error_runtime_fields_missing")
        runtime_normalized_errors = [
            dict(value)
            for value in list(payload.get("normalized_error_history") or [])
            if isinstance(value, dict)
        ]
        if runtime_normalized_errors != outcome_normalized_errors:
            problems.append("normalized_error_runtime_history")
        if _compact_text(payload.get("error_category")).casefold() != _compact_text(
            final_row.get("error_category")
        ).casefold():
            problems.append("final_error_category")
        if _compact_text(payload.get("quota_scope")).casefold() != _compact_text(
            final_row.get("quota_scope")
        ).casefold():
            problems.append("final_quota_scope")
        payload_status = _optional_int(payload.get("status_code"))
        row_status = _optional_int(final_row.get("status_code"))
        if payload_status != row_status:
            problems.append("final_status_code")
        if payload.get("model_fallback_allowed") != final_row.get(
            "model_fallback_allowed"
        ):
            problems.append("final_model_fallback_allowed")
        if _compact_text(
            payload.get("fallback_blocked_reason")
        ) != _compact_text(final_row.get("fallback_blocked_reason")):
            problems.append("final_fallback_blocked_reason")
        if _optional_int(payload.get("retry_after_seconds")) != _optional_int(
            final_row.get("retry_after_seconds")
        ):
            problems.append("final_retry_after_seconds")
    return list(dict.fromkeys(problems))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_evidence_path(
    reference: str,
    *,
    manifest_path: Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    text = _compact_text(reference).replace("\\", "/")
    local_app_data = _compact_text(env.get("LOCALAPPDATA"))
    prefix = "%LOCALAPPDATA%/"
    if text.upper().startswith(prefix):
        if not local_app_data:
            raise ValueError("LOCALAPPDATA is not available.")
        return Path(local_app_data) / text[len(prefix) :]
    if "%" in text:
        raise ValueError(f"Unsupported evidence path variable: {reference}")
    path = Path(text)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path


def _validate_hash_file(path: Path, row: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    if not path.exists() or not path.is_file():
        return ["missing_file"]
    minimum_size = int(row.get("minimum_size_bytes") or 1)
    if path.stat().st_size < minimum_size:
        problems.append("file_too_small")
    expected_hash = _compact_text(row.get("sha256")).lower()
    if not expected_hash:
        problems.append("missing_sha256")
    elif _sha256(path) != expected_hash:
        problems.append("sha256_mismatch")
    return problems


def _validate_long_conversation(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    turns = [row for row in list(payload.get("turns") or []) if isinstance(row, dict)]
    turn_count = int(payload.get("turn_count") or 0)
    message_count = int(payload.get("message_count") or 0)
    user_turn_count = int(payload.get("user_turn_count") or 0)
    assistant_turn_count = int(payload.get("assistant_turn_count") or 0)
    minimum_turn_count = int(expected.get("minimum_turn_count") or 0)
    minimum_message_count = int(expected.get("minimum_message_count") or 0)

    if payload.get("artifact_type") != expected.get("artifact_type"):
        problems.append("artifact_type")
    if payload.get("passed") is not True:
        problems.append("not_passed")
    if turn_count < minimum_turn_count or len(turns) != turn_count:
        problems.append("turn_count")
    if (
        message_count < minimum_message_count
        or user_turn_count != turn_count
        or assistant_turn_count != turn_count
        or user_turn_count + assistant_turn_count != message_count
    ):
        problems.append("message_count")

    expected_providers = {
        _compact_text(value) for value in list(expected.get("providers") or []) if _compact_text(value)
    }
    actual_providers = {
        _compact_text(value) for value in list(payload.get("providers_used") or []) if _compact_text(value)
    }
    if not expected_providers.issubset(actual_providers):
        problems.append("provider_coverage")
    minimum_domain_count = int(expected.get("minimum_domain_count") or 0)
    if len(set(payload.get("domains_observed") or [])) < minimum_domain_count:
        problems.append("domain_coverage")

    review = payload.get("human_review") if isinstance(payload.get("human_review"), dict) else {}
    if (
        review.get("complete") is not True
        or int(review.get("reviewed_turn_count") or 0) != turn_count
        or int(review.get("failed_turn_count") or 0) != 0
        or int(review.get("partial_turn_count") or 0) != 0
    ):
        problems.append("human_review_summary")
    if any(
        row.get("success") is not True
        or row.get("application_quality_passed") is not True
        or row.get("model_evaluation_passed") is not True
        or row.get("visible_answer_conflicts_with_tool_data") is True
        or not isinstance(row.get("human_review"), dict)
        or row["human_review"].get("status") != "accepted"
        or row["human_review"].get("reviewed_directly_by_closing_codex") is not True
        for row in turns
    ):
        problems.append("turn_review")

    contract = (
        payload.get("evaluation_contract")
        if isinstance(payload.get("evaluation_contract"), dict)
        else {}
    )
    if contract.get("fixed_prompt_list") is not False:
        problems.append("adaptive_prompt_selection")
    if contract.get("every_assistant_answer_directly_reviewed_by_closing_codex") is not True:
        problems.append("direct_codex_review")
    if contract.get("production_marketplace_mutations_allowed") is not False:
        problems.append("production_mutation_guard")
    if payload.get("runtime_transition_integrity_complete") is not True:
        problems.append("runtime_transition_integrity")
    transitions = [
        row for row in list(payload.get("runtime_transitions") or []) if isinstance(row, dict)
    ]
    if int(expected.get("minimum_provider_transition_count") or 0) > len(transitions):
        problems.append("provider_transition_count")
    if any(
        _compact_text(row.get("history_state_hash_before_switch"))
        != _compact_text(row.get("history_state_hash_at_runtime_start"))
        for row in transitions
    ):
        problems.append("provider_transition_state_hash")

    privacy = (
        payload.get("privacy_redaction")
        if isinstance(payload.get("privacy_redaction"), dict)
        else {}
    )
    if (
        privacy.get("redacted") is not True
        or privacy.get("original_values_persisted") is not False
        or int(privacy.get("version") or 0) < int(expected.get("minimum_privacy_version") or 0)
    ):
        problems.append("privacy_redaction")
    return problems


def _validate_source_ui_regression(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    turns = [row for row in list(payload.get("turns") or []) if isinstance(row, dict)]
    minimum_turn_count = int(expected.get("minimum_turn_count") or 0)
    requested_model = _compact_text(expected.get("requested_model"))
    acceptance = (
        payload.get("acceptance_validation")
        if isinstance(payload.get("acceptance_validation"), dict)
        else {}
    )
    if payload.get("artifact_type") != "real_source_ui_human_directed":
        problems.append("artifact_type")
    minimum_evidence_contract_version = int(
        expected.get("minimum_evidence_contract_version") or 0
    )
    if int(payload.get("evidence_contract_version") or 0) < minimum_evidence_contract_version:
        problems.append("evidence_contract_version")
    if minimum_evidence_contract_version >= 4 and (
        not _compact_text(payload.get("runtime_source_fingerprint"))
        or not _compact_text(payload.get("runtime_source_fingerprint_current"))
        or payload.get("runtime_source_stale") is not False
        or _compact_text(payload.get("runtime_source_fingerprint"))
        != _compact_text(payload.get("runtime_source_fingerprint_current"))
    ):
        problems.append("runtime_source_fingerprint")
    if (
        payload.get("final_status") != "passed"
        or acceptance.get("accepted") is not True
        or list(acceptance.get("problems") or [])
    ):
        problems.append("acceptance_status")
    if len(turns) < minimum_turn_count:
        problems.append("turn_count")
    if (
        payload.get("source_entrypoint") != "desktop/main.py"
        or payload.get("ui_mode") != "full_source_app"
        or payload.get("source_surface_constructed") is not True
        or payload.get("render_mode") != "offscreen"
    ):
        problems.append("source_app_surface")
    if (
        payload.get("human_selects_each_next_prompt_after_reading_previous_turn") is not True
        or payload.get("fixed_prompt_list") is not False
    ):
        problems.append("adaptive_human_review")
    if any(
        row.get("success") is not True
        or not _compact_text(row.get("selection_reason"))
        or (
            index > 0
            and (
                not isinstance(row.get("review_previous"), dict)
                or row["review_previous"].get("read_confirmed") is not True
                or _compact_text(row["review_previous"].get("assessment")) != "pass"
            )
        )
        for index, row in enumerate(turns)
    ):
        problems.append("turn_review")
    invoked = [
        row
        for row in turns
        if isinstance(row.get("runtime"), dict)
        and row["runtime"].get("model_invoked") is True
    ]
    if not invoked or (
        requested_model
        and not any(
            _compact_text(row["runtime"].get("actual_model")) == requested_model
            for row in invoked
        )
    ):
        problems.append("exact_model")
    evidence_contract_version = int(
        payload.get("evidence_contract_version") or 0
    )
    for row in turns:
        runtime = row.get("runtime") if isinstance(row.get("runtime"), dict) else {}
        turn_number = int(row.get("turn") or 0)
        for problem in validate_turn_model_provenance(
            runtime,
            requested_model=requested_model,
            require_outcome_history=evidence_contract_version >= 5,
        ):
            problems.append(
                f"turn_model_provenance:{turn_number}:{problem}"
            )
    if (
        evidence_contract_version >= 5
        and invoked
        and not any(
            (row.get("runtime") or {}).get("accepted_semantic_output") is True
            for row in invoked
            if isinstance(row.get("runtime"), dict)
        )
    ):
        problems.append("model_semantic_output_not_proven")
    if payload.get("fallback_allowed") is not False or any(
        isinstance(row.get("runtime"), dict)
        and (
            row["runtime"].get("fallback_used") is True
            or row["runtime"].get("any_model_fallback_used") is True
        )
        for row in turns
    ):
        problems.append("fallback_guard")
    if "fresh_execute_required" in expected and payload.get("fresh_execute_required") is not expected.get(
        "fresh_execute_required"
    ):
        problems.append("fresh_execute_contract")
    privacy = (
        payload.get("privacy_redaction")
        if isinstance(payload.get("privacy_redaction"), dict)
        else {}
    )
    if (
        privacy.get("redacted") is not True
        or privacy.get("original_values_persisted") is not False
        or int(privacy.get("version") or 0) < int(expected.get("minimum_privacy_version") or 0)
    ):
        problems.append("privacy_redaction")

    all_tool_names = [
        _compact_text(call.get("tool"))
        for row in turns
        for call in list(row.get("tool_calls") or [])
        if isinstance(call, dict) and _compact_text(call.get("tool"))
    ]
    required_tool_names = {
        _compact_text(value)
        for value in list(expected.get("required_tool_names") or [])
        if _compact_text(value)
    }
    if not required_tool_names.issubset(set(all_tool_names)):
        problems.append("required_tool_coverage")
    forbidden_tool_names = {
        _compact_text(value)
        for value in list(expected.get("forbidden_tool_names") or [])
        if _compact_text(value)
    }
    if forbidden_tool_names.intersection(all_tool_names):
        problems.append("forbidden_tool_invocation")
    if all_tool_names.count("operations.manual_action.prepare") < int(
        expected.get("minimum_prepare_count") or 0
    ):
        problems.append("prepare_count")
    if sum(row.get("turn_outcome") == "cancelled" for row in turns) < int(
        expected.get("minimum_cancelled_turn_count") or 0
    ):
        problems.append("cancelled_turn_count")
    if expected.get("require_no_execute_success") is True and any(
        isinstance(row.get("execute"), dict) and row["execute"].get("success") is True
        for row in turns
    ):
        problems.append("unexpected_execute")

    turn_by_number = {int(row.get("turn") or 0): row for row in turns}
    for contract in list(expected.get("required_turn_contracts") or []):
        if not isinstance(contract, dict):
            problems.append("turn_contract")
            continue
        turn_number = int(contract.get("turn") or 0)
        row = turn_by_number.get(turn_number)
        if row is None:
            problems.append(f"turn_contract:{turn_number}:missing")
            continue
        actual_tools = [
            _compact_text(call.get("tool"))
            for call in list(row.get("tool_calls") or [])
            if isinstance(call, dict) and _compact_text(call.get("tool"))
        ]
        exact_tools = [
            _compact_text(value)
            for value in list(contract.get("exact_tools") or [])
            if _compact_text(value)
        ]
        if "exact_tools" in contract and actual_tools != exact_tools:
            problems.append(f"turn_contract:{turn_number}:tools")
        answer = _compact_text(row.get("answer")).casefold()
        if any(
            _compact_text(value).casefold() not in answer
            for value in list(contract.get("answer_contains") or [])
            if _compact_text(value)
        ):
            problems.append(f"turn_contract:{turn_number}:answer")
        if any(
            _compact_text(value).casefold() in answer
            for value in list(contract.get("answer_excludes") or [])
            if _compact_text(value)
        ):
            problems.append(f"turn_contract:{turn_number}:answer_excludes")
        for field in ("turn_outcome", "approval_required"):
            if field in contract and row.get(field) != contract.get(field):
                problems.append(f"turn_contract:{turn_number}:{field}")
        if "pending_action_status" in contract:
            pending = row.get("pending_action") if isinstance(row.get("pending_action"), dict) else {}
            if _compact_text(pending.get("status")) != _compact_text(
                contract.get("pending_action_status")
            ):
                problems.append(f"turn_contract:{turn_number}:pending_action_status")
        if "model_invoked" in contract:
            runtime = row.get("runtime") if isinstance(row.get("runtime"), dict) else {}
            if runtime.get("model_invoked") is not contract.get("model_invoked"):
                problems.append(f"turn_contract:{turn_number}:model_invoked")
    required_invocation_sequence = [
        _compact_text(value)
        for value in list(expected.get("required_invocation_contract_sequence") or [])
        if _compact_text(value)
    ]
    if required_invocation_sequence and not any(
        [
            _compact_text(value)
            for value in list((row.get("runtime") or {}).get("invocation_contract_history") or [])
            if _compact_text(value)
        ]
        == required_invocation_sequence
        for row in turns
        if isinstance(row.get("runtime"), dict)
    ):
        problems.append("invocation_contract_sequence")
    return problems


def _validate_provider_fallback(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    requested_model = _compact_text(expected.get("requested_model"))
    actual_model = _compact_text(expected.get("actual_model"))
    attempts = [
        row
        for row in list(payload.get("fallback_attempts") or [])
        if isinstance(row, dict)
    ]
    request_hashes = [
        row
        for row in list(payload.get("request_prompt_hashes") or [])
        if isinstance(row, dict)
    ]
    if payload.get("artifact_type") != "provider_live_fallback_state_evidence":
        problems.append("artifact_type")
    if payload.get("valid") is not True or payload.get("live_catalog") is not True:
        problems.append("acceptance_status")
    if (
        _compact_text(payload.get("requested_model")) != requested_model
        or _compact_text(payload.get("actual_model")) != actual_model
        or payload.get("fallback_used") is not True
    ):
        problems.append("model_transition")
    if (
        not attempts
        or _compact_text(attempts[0].get("model")) != requested_model
        or not _compact_text(attempts[0].get("reason"))
    ):
        problems.append("fallback_reason")
    prompt_hashes = {
        _compact_text(row.get("prompt_sha256"))
        for row in request_hashes
        if _compact_text(row.get("prompt_sha256"))
    }
    if (
        len(request_hashes) < 2
        or len(prompt_hashes) != 1
        or payload.get("same_prompt_hash_for_every_network_attempt") is not True
    ):
        problems.append("prompt_state_continuity")
    if (
        payload.get("state_preserved") is not True
        or not _compact_text(payload.get("state_hash_before"))
        or _compact_text(payload.get("state_hash_before"))
        != _compact_text(payload.get("state_hash_after"))
    ):
        problems.append("state_hash")
    profile = (
        payload.get("capability_profile_after")
        if isinstance(payload.get("capability_profile_after"), dict)
        else {}
    )
    if _compact_text(profile.get("model_id")) != actual_model:
        problems.append("actual_capability_profile")
    privacy = (
        payload.get("privacy_redaction")
        if isinstance(payload.get("privacy_redaction"), dict)
        else {}
    )
    if (
        privacy.get("original_values_persisted") is not False
        or int(privacy.get("version") or 0)
        < int(expected.get("minimum_privacy_version") or 0)
    ):
        problems.append("privacy_redaction")
    return problems


def _validate_ui_v3(payload: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    acceptance = payload.get("acceptance") if isinstance(payload.get("acceptance"), dict) else {}
    state_matrix = (
        payload.get("state_matrix") if isinstance(payload.get("state_matrix"), dict) else {}
    )
    visual = [row for row in list(acceptance.get("visual") or []) if isinstance(row, dict)]
    geometry = [
        row for row in list(acceptance.get("geometry") or []) if isinstance(row, dict)
    ]
    if payload.get("contract") != expected.get("contract"):
        problems.append("contract")
    if payload.get("render_mode") != "offscreen":
        problems.append("render_mode")
    if acceptance.get("passed") is not True:
        problems.append("acceptance")
    if len(visual) < 3 or any(
        row.get("passed") is not True
        or float(row.get("similarity") or 0) < float(row.get("threshold") or 1)
        for row in visual
    ):
        problems.append("visual")
    if not geometry or any(row.get("passed") is not True for row in geometry):
        problems.append("geometry")
    if (
        state_matrix.get("passed") is not True
        or state_matrix.get("complete") is not True
        or int(state_matrix.get("rendered_case_count") or 0)
        < int(expected.get("minimum_rendered_case_count") or 0)
        or list(state_matrix.get("pending_states") or [])
    ):
        problems.append("state_matrix")
    return problems


def _validate_core_dry_architecture(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    evidence_contract = (
        payload.get("evidence_contract")
        if isinstance(payload.get("evidence_contract"), dict)
        else {}
    )
    if payload.get("artifact_type") != "orderscout_core_dry_architecture_audit":
        problems.append("artifact_type")
    if payload.get("valid") is not True or int(payload.get("violation_count") or 0) != 0:
        problems.append("audit_status")
    if int(payload.get("product_python_file_count") or 0) < int(
        expected.get("minimum_product_python_file_count") or 0
    ):
        problems.append("product_python_file_count")
    required_checks = [
        _compact_text(value)
        for value in list(expected.get("required_checks") or [])
        if _compact_text(value)
    ]
    if any(
        check_name not in checks
        or not isinstance(checks.get(check_name), dict)
        or checks[check_name].get("valid") is not True
        or int(checks[check_name].get("violation_count") or 0) != 0
        for check_name in required_checks
    ):
        problems.append("required_checks")
    parity = checks.get("manual_ai_operation_parity") if isinstance(
        checks.get("manual_ai_operation_parity"), dict
    ) else {}
    if int(parity.get("manual_total") or 0) < int(
        expected.get("minimum_manual_operation_total") or 0
    ) or int(parity.get("manual_total") or 0) != int(
        parity.get("operation_contract_valid_total") or 0
    ):
        problems.append("manual_ai_operation_parity")
    if (
        evidence_contract.get("customer_data_included") is not False
        or evidence_contract.get("credentials_included") is not False
        or evidence_contract.get("local_paths_included") is not False
        or evidence_contract.get("source_tree_mutated_by_audit") is not False
    ):
        problems.append("evidence_contract")
    return problems


def _validate_tanex_2610(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    review = (
        payload.get("direct_visual_review")
        if isinstance(payload.get("direct_visual_review"), dict)
        else {}
    )
    checks = review.get("checks") if isinstance(review.get("checks"), dict) else {}
    gate = (
        payload.get("remaining_supervised_gate")
        if isinstance(payload.get("remaining_supervised_gate"), dict)
        else {}
    )
    product = (
        payload.get("official_product_contract")
        if isinstance(payload.get("official_product_contract"), dict)
        else {}
    )
    if payload.get("contract") != expected.get("contract") or payload.get("passed") is not True:
        problems.append("contract")
    if int(review.get("page_count") or 0) != 1 or review.get("all_pages_reviewed") is not True:
        problems.append("page_review")
    required_checks = {
        _compact_text(value)
        for value in list(expected.get("required_checks") or [])
        if _compact_text(value)
    }
    if not required_checks or any(checks.get(name) is not True for name in required_checks):
        problems.append("visual_checks")
    if _compact_text(product.get("reference")) != "TW-2610":
        problems.append("product_reference")
    if _compact_text(gate.get("physical_sheet_print_alignment")) != "deferred_supervised":
        problems.append("physical_gate")
    return problems


def _validate_stage_mutation(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    external = (
        payload.get("external_verification")
        if isinstance(payload.get("external_verification"), dict)
        else {}
    )
    if payload.get("artifact_type") != "orders_staging_marketplace_evidence":
        problems.append("artifact_type")
    if _compact_text(action.get("action_type")) != _compact_text(expected.get("action_type")):
        problems.append("action_type")
    minimum_selected = int(expected.get("minimum_selected_record_count") or 0)
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    verify_payload = (
        result_payload.get("verify")
        if isinstance(result_payload.get("verify"), dict)
        else {}
    )
    if minimum_selected and (
        int(action.get("selected_record_count") or 0) < minimum_selected
        or len(list(action.get("record_refs") or [])) < minimum_selected
        or len(list(verify_payload.get("rows") or [])) < minimum_selected
    ):
        problems.append("selected_record_scope")
    if (
        payload.get("execute_success") is not True
        or payload.get("runtime_verify_success") is not True
        or payload.get("api_call_performed") is not True
    ):
        problems.append("execute_verify")
    if (
        external.get("verified") is not True
        or external.get("operation_matches") is not True
        or external.get("staging_account_only") is not True
    ):
        problems.append("external_verification")
    if _compact_text(payload.get("staging_account_id")) != _compact_text(
        expected.get("staging_account_id")
    ):
        problems.append("staging_account")
    return problems


def _validate_production_read_sync(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    problems: list[str] = []
    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    providers = [
        row for row in list(payload.get("providers") or []) if isinstance(row, dict)
    ]
    if payload.get("artifact_type") != expected.get("artifact_type"):
        problems.append("artifact_type")
    if payload.get("passed") is not True or payload.get("environment_scope") != "production":
        problems.append("production_scope")
    if (
        safety.get("marketplace_read_performed") is not True
        or safety.get("marketplace_mutation_performed") is not False
        or safety.get("source_db_upsert_performed") is not True
    ):
        problems.append("safety")
    if not providers:
        problems.append("providers")
    expected_providers = {
        _compact_text(value)
        for value in list(expected.get("providers") or [])
        if _compact_text(value)
    }
    actual_providers = {_compact_text(row.get("provider_code")) for row in providers}
    if not expected_providers.issubset(actual_providers):
        problems.append("provider_coverage")
    for provider in providers:
        checks = provider.get("checks") if isinstance(provider.get("checks"), dict) else {}
        source_state = (
            provider.get("source_state")
            if isinstance(provider.get("source_state"), dict)
            else {}
        )
        execute = provider.get("execute") if isinstance(provider.get("execute"), dict) else {}
        readback = (
            execute.get("db_readback")
            if isinstance(execute.get("db_readback"), dict)
            else {}
        )
        before = [
            row
            for row in list(source_state.get("accounts_before") or [])
            if isinstance(row, dict)
        ]
        after = [
            row
            for row in list(source_state.get("accounts_after") or [])
            if isinstance(row, dict)
        ]
        payload_ids = {
            int(value)
            for value in list(
                ((provider.get("prepare") or {}).get("payload") or {}).get(
                    "api_account_ids"
                )
                or []
            )
        }
        before_ids = {int(row.get("pk") or 0) for row in before}
        if (
            provider.get("environment_scope") != "production"
            or not checks
            or any(value is not True for value in checks.values())
            or not before
            or payload_ids != before_ids
            or any(row.get("environment") != "production" for row in before + after)
        ):
            problems.append(f"provider_scope:{_compact_text(provider.get('provider_code'))}")
        if (
            readback.get("all_orders_found") is not True
            or readback.get("all_claims_found") is not True
        ):
            problems.append(f"readback:{_compact_text(provider.get('provider_code'))}")
    privacy = (
        payload.get("privacy_redaction")
        if isinstance(payload.get("privacy_redaction"), dict)
        else {}
    )
    if privacy.get("redacted") is not True or privacy.get("original_values_persisted") is not False:
        problems.append("privacy_redaction")
    return problems


def _validate_json_semantics(
    kind: str, payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    validators = {
        "long_conversation": _validate_long_conversation,
        "source_ui_regression": _validate_source_ui_regression,
        "provider_fallback": _validate_provider_fallback,
        "ui_v3": _validate_ui_v3,
        "core_dry_architecture": _validate_core_dry_architecture,
        "tanex_2610": _validate_tanex_2610,
        "stage_mutation": _validate_stage_mutation,
        "production_read_sync": _validate_production_read_sync,
    }
    validator = validators.get(kind)
    return [] if validator is None else validator(payload, expected)


def validate_current_acceptance_manifest(
    manifest_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    path = Path(manifest_path) if manifest_path not in (None, "") else DEFAULT_MANIFEST_PATH
    result: dict[str, Any] = {
        "valid": False,
        "manifest_path": str(path),
        "artifact_results": [],
        "regression_results": [],
        "problems": [],
    }
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["problems"].append(f"manifest_load:{type(exc).__name__}")
        return result
    if not isinstance(manifest, dict):
        result["problems"].append("manifest_not_object")
        return result
    if manifest.get("artifact_type") != EXPECTED_ARTIFACT_TYPE:
        result["problems"].append("artifact_type")
    schema_version = int(manifest.get("schema_version") or 0)
    if schema_version != EXPECTED_SCHEMA_VERSION:
        result["problems"].append("schema_version")
    if manifest.get("scope_status") != EXPECTED_SCOPE_STATUS:
        result["problems"].append("scope_status")
    acceptance_status = _compact_text(manifest.get("acceptance_status")).casefold()
    if acceptance_status not in {"open", "proven"}:
        result["problems"].append("acceptance_status")
    if not _compact_text(manifest.get("current_phase")):
        result["problems"].append("current_phase")
    latest_binding_regression_id = _compact_text(
        manifest.get("latest_binding_regression_id")
    )
    if not latest_binding_regression_id:
        result["problems"].append("latest_binding_regression_id")
    if not isinstance(manifest.get("closure_ready"), bool):
        result["problems"].append("closure_ready_type")
    if acceptance_status == "open" and manifest.get("closure_ready") is not False:
        result["problems"].append("closure_ready_open_status")
    if acceptance_status == "proven" and manifest.get("closure_ready") is not True:
        result["problems"].append("closure_ready_proven_status")
    if not list(manifest.get("open_gates") or []):
        result["problems"].append("open_gates")

    artifact_ids: set[str] = set()
    valid_artifact_ids: set[str] = set()
    for artifact in list(manifest.get("artifacts") or []):
        if not isinstance(artifact, dict):
            result["problems"].append("artifact_not_object")
            continue
        artifact_id = _compact_text(artifact.get("id"))
        row_result: dict[str, Any] = {
            "id": artifact_id,
            "kind": _compact_text(artifact.get("kind")),
            "valid": False,
            "problems": [],
        }
        if not artifact_id or artifact_id in artifact_ids:
            row_result["problems"].append("duplicate_or_missing_id")
        artifact_ids.add(artifact_id)
        try:
            artifact_path = resolve_evidence_path(
                _compact_text(artifact.get("path")),
                manifest_path=path,
                environ=environ,
            )
            row_result["resolved_path"] = str(artifact_path)
            row_result["problems"].extend(_validate_hash_file(artifact_path, artifact))
            if not row_result["problems"] and artifact.get("kind") != "file":
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    row_result["problems"].append("json_not_object")
                else:
                    row_result["problems"].extend(
                        _validate_json_semantics(
                            _compact_text(artifact.get("kind")),
                            payload,
                            artifact.get("expect")
                            if isinstance(artifact.get("expect"), dict)
                            else {},
                        )
                    )
            for related in list(artifact.get("related_files") or []):
                if not isinstance(related, dict):
                    row_result["problems"].append("related_file_not_object")
                    continue
                related_path = resolve_evidence_path(
                    _compact_text(related.get("path")),
                    manifest_path=path,
                    environ=environ,
                )
                for problem in _validate_hash_file(related_path, related):
                    row_result["problems"].append(
                        f"related:{_compact_text(related.get('id'))}:{problem}"
                    )
        except Exception as exc:
            row_result["problems"].append(f"validation:{type(exc).__name__}")
        row_result["valid"] = not row_result["problems"]
        if row_result["valid"]:
            valid_artifact_ids.add(artifact_id)
        elif artifact.get("required") is not False:
            result["problems"].append(f"artifact:{artifact_id}")
        result["artifact_results"].append(row_result)

    required_ids = {
        _compact_text(value)
        for value in list(manifest.get("current_proven_slice_artifact_ids") or [])
        if _compact_text(value)
    }
    missing_required = sorted(required_ids - valid_artifact_ids)
    if missing_required:
        result["problems"].append("required_artifacts")
        result["missing_required_artifact_ids"] = missing_required
    diagnostic_ids = {
        _compact_text(value)
        for value in list(manifest.get("current_diagnostic_artifact_ids") or [])
        if _compact_text(value)
    }
    historical_ids = {
        _compact_text(value)
        for value in list(manifest.get("historical_baseline_artifact_ids") or [])
        if _compact_text(value)
    }
    if not diagnostic_ids:
        result["problems"].append("current_diagnostic_artifact_ids")
    if not diagnostic_ids.issubset(artifact_ids):
        result["problems"].append("unknown_diagnostic_artifact_ids")
    if not historical_ids.issubset(artifact_ids):
        result["problems"].append("unknown_historical_artifact_ids")

    desktop_root = path.parents[2]
    current_regression_ids = {
        _compact_text(value)
        for value in list(manifest.get("current_regression_ids") or [])
        if _compact_text(value)
    }
    seen_regression_ids: set[str] = set()
    unresolved_regression_ids: list[str] = []
    for regression in list(manifest.get("regressions") or []):
        if not isinstance(regression, dict):
            result["problems"].append("regression_not_object")
            continue
        regression_id = _compact_text(regression.get("id"))
        seen_regression_ids.add(regression_id)
        regression_problems: list[str] = []
        if not regression_id:
            regression_problems.append("missing_id")
        regression_status = _compact_text(regression.get("status")).casefold()
        if regression_status not in {
            "open",
            "reopened",
            "unresolved",
            "resolved",
            "verified",
        }:
            regression_problems.append("status")
        if regression_status in {"open", "reopened", "unresolved"}:
            unresolved_regression_ids.append(regression_id)
            if regression_id not in current_regression_ids:
                regression_problems.append("unresolved_not_current")
        guard_tests = [
            _compact_text(value)
            for value in list(regression.get("guard_tests") or [])
            if _compact_text(value)
        ]
        if len(guard_tests) < 2:
            regression_problems.append("guard_tests")
        for reference in guard_tests:
            test_file = desktop_root / reference.split("::", 1)[0]
            if not test_file.exists() or not test_file.is_file():
                regression_problems.append(f"missing_guard:{reference}")
        evidence_ids = {
            _compact_text(value)
            for value in list(regression.get("current_evidence_ids") or [])
            if _compact_text(value)
        }
        if not evidence_ids or not evidence_ids.issubset(valid_artifact_ids):
            regression_problems.append("current_evidence")
        result["regression_results"].append(
            {
                "id": regression_id,
                "status": regression_status,
                "current": regression_id in current_regression_ids,
                "resolved": regression_status in {"resolved", "verified"},
                "valid": not regression_problems,
                "problems": regression_problems,
            }
        )
        if regression_problems:
            result["problems"].append(f"regression:{regression_id}")
    if not current_regression_ids:
        result["problems"].append("current_regression_ids")
    if not current_regression_ids.issubset(seen_regression_ids):
        result["problems"].append("unknown_current_regression_ids")
    if (
        latest_binding_regression_id
        and latest_binding_regression_id not in current_regression_ids
    ):
        result["problems"].append("latest_binding_regression_not_current")
    if acceptance_status == "proven" and unresolved_regression_ids:
        result["problems"].append("proven_with_unresolved_regressions")

    result["artifact_count"] = len(result["artifact_results"])
    result["valid_artifact_count"] = len(valid_artifact_ids)
    result["open_gate_count"] = len(list(manifest.get("open_gates") or []))
    result["scope_status"] = manifest.get("scope_status")
    result["schema_version"] = schema_version
    result["acceptance_status"] = acceptance_status
    result["current_phase"] = manifest.get("current_phase")
    result["latest_binding_regression_id"] = latest_binding_regression_id
    result["unresolved_regression_ids"] = sorted(
        set(unresolved_regression_ids)
    )
    result["current_proven_slice_artifact_ids"] = sorted(required_ids)
    result["current_diagnostic_artifact_ids"] = sorted(diagnostic_ids)
    result["historical_baseline_artifact_count"] = len(historical_ids)
    result["closure_ready"] = manifest.get("closure_ready") is True
    result["problems"] = sorted(set(result["problems"]))
    result["valid"] = not result["problems"]
    result["ready_for_closure"] = bool(
        result["valid"]
        and result["closure_ready"]
        and acceptance_status == "proven"
        and not result["unresolved_regression_ids"]
        and required_ids
    )
    return result
