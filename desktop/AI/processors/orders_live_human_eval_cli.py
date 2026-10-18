from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from AI.processors.cloud_runtime import (
    build_provider_chat_client,
    provider_invocation_provenance,
)
from AI.processors.live_evidence import (
    redact_live_evidence,
    write_live_evidence_file,
)
from AI.processors.local_runtime import (
    build_local_planner_client,
    shutdown_managed_llama_servers,
)
from AI.processors.model_routing import stable_state_hash
from AI.processors.conversation_runtime import run_contextual_conversation_turn
from AI.processors.pipeline import (
    get_provider_account,
    list_installed_models,
    list_provider_accounts,
    list_provider_models,
)
from settings import DB_NAME


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_REVIEW_STATUS_ALIASES = {
    "accepted": "accepted",
    "pass": "accepted",
    "needs_review": "needs_review",
    "partial": "needs_review",
    "failed": "failed",
    "fail": "failed",
}
_FINAL_STATUS_ALIASES = {
    "accepted": "pass",
    "pass": "pass",
    "needs_review": "partial",
    "partial": "partial",
    "failed": "fail",
    "fail": "fail",
}
_ACCEPTANCE_DOMAINS = {
    "orders",
    "returns",
    "labels",
    "stock",
    "finance",
    "listing",
    "logistics",
    "marketplaces",
}


def _run_turn(
    prompt: str,
    *,
    phase: str,
    selection_reason: str,
    client: Any,
    provider_code: str,
    model_name: str,
    db_name: str,
    history: list[dict[str, Any]],
    session_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run human-directed acceptance through the current typed control plane."""

    turn = run_contextual_conversation_turn(
        prompt,
        client=client,
        provider_code=provider_code,
        model_name=model_name,
        db_name=db_name,
        history=history,
        session_state=session_state,
        allow_approval_execute=False,
    )
    turn["phase"] = _compact_text(phase)
    turn["next_prompt_selection_reason"] = _compact_text(selection_reason)
    return turn


def _canonical_review_status(value: Any) -> str:
    return _REVIEW_STATUS_ALIASES.get(_compact_text(value).casefold(), "")


def _canonical_final_status(value: Any) -> str:
    return _FINAL_STATUS_ALIASES.get(_compact_text(value).casefold(), "")


def _normalized_required_domains(value: Sequence[str] | str | None) -> list[str]:
    if isinstance(value, str):
        rows = value.split(",")
    else:
        rows = list(value or [])
    normalized: list[str] = []
    for row in rows:
        domain = _compact_text(row).casefold()
        if domain == "marketplace":
            domain = "marketplaces"
        if domain in _ACCEPTANCE_DOMAINS and domain not in normalized:
            normalized.append(domain)
    return normalized


def _domain_from_identifier(value: Any) -> str:
    identifier = _compact_text(value).casefold()
    if not identifier:
        return ""
    prefix = identifier.split(".", 1)[0].replace("-", "_")
    if prefix == "marketplace":
        prefix = "marketplaces"
    return prefix if prefix in _ACCEPTANCE_DOMAINS else ""


def _structured_domains(payload: Any) -> set[str]:
    domains: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = _compact_text(key).casefold()
            if normalized_key in {
                "domain",
                "active_domain",
                "task_domain",
                "tool",
                "operation",
                "capability_id",
                "step_id",
            }:
                domain = _domain_from_identifier(value)
                if domain:
                    domains.add(domain)
            if isinstance(value, (dict, list, tuple)):
                domains.update(_structured_domains(value))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            domains.update(_structured_domains(value))
    return domains


def _turn_domains(turn: dict[str, Any]) -> list[str]:
    domains = _structured_domains(
        {
            "task_domain": turn.get("task_domain"),
            "tools": [
                {"tool": tool_name}
                for tool_name in list(turn.get("tools") or [])
            ],
            "tool_arguments": turn.get("tool_arguments"),
            "tool_results": turn.get("tool_results"),
            "action_proposal": turn.get("action_proposal"),
            "task_state": turn.get("task_state"),
        }
    )
    return sorted(domains)


def _provider_model_domain_matrix(
    turns: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    matrix: dict[tuple[str, str, str], dict[str, Any]] = {}
    for turn in turns:
        provider = _compact_text(turn.get("provider_code")).casefold()
        model = _compact_text(turn.get("requested_model"))
        for domain in _turn_domains(turn):
            key = (provider, model, domain)
            row = matrix.setdefault(
                key,
                {
                    "provider_code": provider,
                    "requested_model": model,
                    "domain": domain,
                    "turn_count": 0,
                    "reviewed_turn_count": 0,
                    "failed_turn_count": 0,
                },
            )
            row["turn_count"] += 1
            review = dict(turn.get("human_review") or {})
            status = _canonical_review_status(review.get("status"))
            if status:
                row["reviewed_turn_count"] += 1
            if status == "failed":
                row["failed_turn_count"] += 1
    return [matrix[key] for key in sorted(matrix)]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _write_raw_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _provider_record(provider_code: str, model: str) -> dict[str, Any]:
    accounts_result = list_provider_accounts(include_secret=False)
    if not accounts_result.success:
        raise RuntimeError(accounts_result.message)
    provider = _compact_text(provider_code).casefold()
    summary = next(
        (
            dict(row)
            for row in list((accounts_result.data or {}).get("records") or [])
            if isinstance(row, dict)
            and _compact_text(row.get("provider_code")).casefold() == provider
            and bool(row.get("is_enabled"))
        ),
        {},
    )
    if not summary:
        raise RuntimeError(f"Etkin provider hesabi bulunamadi: {provider}")
    detail_result = get_provider_account(int(summary.get("id") or 0))
    if not detail_result.success:
        raise RuntimeError(detail_result.message)
    record = dict((detail_result.data or {}).get("record") or {})
    selected_model = _compact_text(model) or _compact_text(record.get("default_model"))
    if not selected_model:
        raise RuntimeError("Canli degerlendirme icin model gerekir.")

    catalog_result = list_provider_models(
        provider_code=provider,
        endpoint_url=_compact_text(record.get("endpoint_url")),
        api_key=_compact_text(record.get("api_key")),
        free_only=True,
        limit=500,
    )
    if catalog_result.success:
        model_metadata = next(
            (
                dict(row)
                for row in list((catalog_result.data or {}).get("records") or [])
                if isinstance(row, dict)
                and _compact_text(row.get("id")) == selected_model
            ),
            {},
        )
        if model_metadata:
            record["model_metadata"] = model_metadata
    record["default_model"] = selected_model
    record["reasoning_effort"] = "auto"
    record["allow_model_fallback"] = False
    return record


def _local_record(model: str) -> dict[str, Any]:
    result = list_installed_models()
    if not result.success:
        raise RuntimeError(result.message)
    requested = _compact_text(model).casefold()
    record = next(
        (
            dict(row)
            for row in list((result.data or {}).get("records") or [])
            if isinstance(row, dict)
            and requested
            in {
                _compact_text(row.get("repo_id")).casefold(),
                _compact_text(row.get("filename")).casefold(),
                _compact_text(row.get("id")).casefold(),
            }
            and bool(row.get("exists_on_disk"))
        ),
        {},
    )
    if not record:
        raise RuntimeError(f"Yuklu local model bulunamadi: {model}")
    runtime = dict(record.get("runtime_config") or {})
    runtime.update(
        {
            "performance_preset": "balanced",
            "num_ctx": min(4096, max(512, int(runtime.get("num_ctx") or 4096))),
            "max_tokens": min(384, max(128, int(runtime.get("max_tokens") or 256))),
            "keep_alive": "0s",
        }
    )
    record["runtime_config"] = runtime
    return record


def _build_exact_client(
    provider_code: str,
    model: str,
    *,
    timeout: float,
    max_rate_limit_wait_seconds: int | None = None,
) -> tuple[Any, dict[str, Any], bool]:
    provider = _compact_text(provider_code).casefold()
    if provider in {"local-best", "local-weak", "local"}:
        record = _local_record(model)
        base_client = build_local_planner_client(record)
        if base_client is None:
            raise RuntimeError("Local planner client olusturulamadi.")
        selected_model = _compact_text(record.get("repo_id") or record.get("filename"))
        initial_plan = dict(getattr(base_client, "resource_plan", {}) or {})
        initial_plan.update(
            {
                "profile": "local_model",
                "provider_code": provider,
                "requested_model": selected_model,
                "fallback_allowed": False,
            }
        )

        def tracked_client(prompt: str) -> str:
            response = base_client(prompt)
            plan = dict(getattr(base_client, "resource_plan", {}) or {})
            plan.update(
                {
                    "profile": "local_model",
                    "provider_code": provider,
                    "requested_model": selected_model,
                    "fallback_allowed": False,
                }
            )
            plan["actual_model"] = selected_model
            setattr(tracked_client, "resource_plan", plan)
            return response

        setattr(tracked_client, "resource_plan", initial_plan)
        for attribute in ("runtime_name", "model_name", "server_url", "server_key"):
            if hasattr(base_client, attribute):
                setattr(tracked_client, attribute, getattr(base_client, attribute))
        return tracked_client, record, True

    record = _provider_record(provider, model)
    if max_rate_limit_wait_seconds is not None:
        record["max_exact_model_rate_limit_wait_seconds"] = max(
            0,
            int(max_rate_limit_wait_seconds),
        )
    client = build_provider_chat_client(record, timeout=timeout)
    if client is None:
        raise RuntimeError("Provider chat client olusturulamadi.")
    return client, record, False


def _review_previous(
    state: dict[str, Any],
    *,
    status: str,
    notes: str,
) -> None:
    turns = list(state.get("turns") or [])
    if not turns:
        raise RuntimeError("Incelenecek onceki tur yok.")
    normalized_status = _canonical_review_status(status)
    if not normalized_status:
        raise RuntimeError(
            "Review status accepted, needs_review veya failed olmali."
        )
    clean_notes = _compact_text(notes)
    if not clean_notes:
        raise RuntimeError("Her tur icin dogrudan inceleme gerekcesi gerekir.")
    turn = dict(turns[-1])
    turn["human_review"] = {
        "status": normalized_status,
        "notes": clean_notes,
        "reviewed_at": _utcnow_iso(),
        "reviewed_directly_by_closing_codex": True,
        "rubric": [
            "naturalness",
            "contextual relevance",
            "tool restraint",
            "grounding and correctness",
            "planning and continuity",
            "recovery behavior",
            "codex-like agentic feel",
        ],
    }
    turns[-1] = turn
    state["turns"] = turns


def _artifact_payload(state: dict[str, Any]) -> dict[str, Any]:
    turns = [dict(turn) for turn in list(state.get("turns") or [])]
    user_turn_count = len(turns)
    assistant_turn_count = sum(
        1 for turn in turns if _compact_text(turn.get("answer"))
    )
    message_count = user_turn_count + assistant_turn_count
    target_message_count = max(
        0,
        int(state.get("target_message_count") or 0),
    )
    minimum_turns = max(
        1,
        int(state.get("minimum_turns") or 20),
    )
    reviews = [dict(turn.get("human_review") or {}) for turn in turns]
    final_assessment = (
        dict(state.get("final_assessment") or {})
        if isinstance(state.get("final_assessment"), dict)
        else {}
    )
    review_complete = bool(turns) and all(
        _canonical_review_status(review.get("status"))
        and _compact_text(review.get("notes"))
        for review in reviews
    )
    all_turns_accepted = review_complete and all(
        _canonical_review_status(review.get("status")) == "accepted"
        for review in reviews
    )
    required_domains = _normalized_required_domains(
        state.get("required_domains") or []
    )
    domains_observed = sorted(
        {
            domain
            for turn in turns
            for domain in _turn_domains(turn)
        }
    )
    domain_coverage_complete = all(
        domain in domains_observed for domain in required_domains
    )
    runtime_transitions = [
        dict(row)
        for row in list(state.get("runtime_transitions") or [])
        if isinstance(row, dict)
    ]
    runtime_transition_integrity_complete = all(
        bool(_compact_text(row.get("history_state_hash_before_switch")))
        and row.get("history_state_hash_before_switch")
        == row.get("history_state_hash_at_runtime_start")
        for row in runtime_transitions
    )
    final_status = _canonical_final_status(final_assessment.get("status"))
    passed = (
        len(turns) >= minimum_turns
        and (
            target_message_count <= 0
            or message_count >= target_message_count
        )
        and review_complete
        and all_turns_accepted
        and domain_coverage_complete
        and runtime_transition_integrity_complete
        and final_status == "pass"
    )
    return {
        "name": _compact_text(state.get("name")),
        "artifact_type": _compact_text(state.get("artifact_type"))
        or "orders_live_human_directed_conversation",
        "created_at": state.get("created_at"),
        "updated_at": _utcnow_iso(),
        "provider_code": (
            state.get("initial_provider_code") or state.get("provider_code")
        ),
        "requested_model": (
            state.get("initial_requested_model")
            or state.get("requested_model")
        ),
        "active_provider_code": state.get("provider_code"),
        "active_requested_model": state.get("requested_model"),
        "providers_used": list(
            dict.fromkeys(
                _compact_text(turn.get("provider_code"))
                for turn in turns
                if _compact_text(turn.get("provider_code"))
            )
        ),
        "models_used": list(
            dict.fromkeys(
                _compact_text(turn.get("requested_model"))
                for turn in turns
                if _compact_text(turn.get("requested_model"))
            )
        ),
        "runtime_transitions": runtime_transitions,
        "runtime_transition_integrity_complete": (
            runtime_transition_integrity_complete
        ),
        "checkpoint_source": (
            dict(state.get("checkpoint_source") or {})
            if isinstance(state.get("checkpoint_source"), dict)
            else {}
        ),
        "required_domains": required_domains,
        "domains_observed": domains_observed,
        "domain_coverage_complete": domain_coverage_complete,
        "provider_model_domain_matrix": _provider_model_domain_matrix(turns),
        "db": "source-app-db",
        "evaluation_contract": {
            "human_selects_each_next_prompt_after_reading_previous_turn": True,
            "fixed_prompt_list": False,
            "minimum_turns": minimum_turns,
            "target_message_count": target_message_count,
            "continue_beyond_minimum_until_confident": True,
            "production_marketplace_mutations_allowed": False,
            "every_assistant_answer_directly_reviewed_by_closing_codex": True,
            "canonical_turn_review_statuses": [
                "accepted",
                "needs_review",
                "failed",
            ],
            "authoritative_tool_results_and_state_required": True,
            "provider_switch_must_preserve_history_hash": True,
        },
        "turn_count": len(turns),
        "message_count": message_count,
        "user_turn_count": user_turn_count,
        "assistant_turn_count": assistant_turn_count,
        "target_message_count": target_message_count,
        "turns": turns,
        "human_review": {
            "reviewed_turn_count": sum(
                1
                for row in reviews
                if _canonical_review_status(row.get("status"))
                and _compact_text(row.get("notes"))
            ),
            "failed_turn_count": sum(
                1
                for row in reviews
                if _canonical_review_status(row.get("status")) == "failed"
            ),
            "partial_turn_count": sum(
                1
                for row in reviews
                if _canonical_review_status(row.get("status")) == "needs_review"
            ),
            "complete": review_complete,
            "all_turns_accepted": all_turns_accepted,
            "final_assessment": final_assessment,
        },
        "passed": passed,
        "completion_note": (
            _compact_text(final_assessment.get("notes"))
            or f"Set passed only after at least {minimum_turns} human-directed turns, "
            "every turn is reviewed, discovered failures are fixed and the "
            "conversation is rerun."
        ),
    }


def _normalize_turn_model_evaluation(
    turn: dict[str, Any],
    *,
    requested_model: str,
) -> None:
    runtime_plan = dict(turn.get("runtime_plan") or {})
    provenance = provider_invocation_provenance(runtime_plan)
    actual_model = _compact_text(
        provenance.get("last_successful_actual_model")
    ).removeprefix("models/")
    requested_value = _compact_text(
        turn.get("requested_model")
        or runtime_plan.get("requested_model")
        or requested_model
    )
    requested = requested_value.removeprefix("models/")
    turn["provider_code"] = _compact_text(
        turn.get("provider_code") or runtime_plan.get("provider_code")
    )
    turn["requested_model"] = requested_value
    model_invoked = bool(
        provenance.get("any_model_response_received")
        or turn.get("model_invoked") is True
    )
    exact_model_responded = model_invoked and bool(actual_model) and actual_model == requested
    application_quality_passed = (
        bool(turn.get("success"))
        and not bool(turn.get("visible_answer_conflicts_with_tool_data"))
        and not bool(turn.get("unsupported_profit_claim"))
    )
    turn["model_invoked"] = model_invoked
    turn["exact_model_responded"] = exact_model_responded
    turn["application_quality_passed"] = application_quality_passed
    turn["model_evaluation_applicable"] = model_invoked
    turn["model_evaluation_passed"] = application_quality_passed and (
        exact_model_responded or not model_invoked
    )
    turn.pop("model_evaluation_note", None)
    turn.pop("model_evaluation_failure", None)
    if not model_invoked:
        turn["model_evaluation_note"] = (
            "No exact provider response was accepted for this turn; the "
            "application completed it deterministically."
        )
    elif not exact_model_responded:
        turn["model_evaluation_failure"] = (
            "The accepted provider response did not come from the exact requested "
            "model; provider fallback remains disallowed."
        )


def finalize_conversation(
    *,
    state_path: Path,
    artifact_path: Path,
    status: str,
    notes: str,
) -> dict[str, Any]:
    state = _load_json(state_path)
    if not state:
        raise RuntimeError("Finalize edilecek canli degerlendirme state'i bulunamadi.")
    _review_previous(state, status=status, notes=notes)
    turns = [dict(turn) for turn in list(state.get("turns") or [])]
    requested_model = _compact_text(state.get("requested_model"))
    for turn in turns:
        _normalize_turn_model_evaluation(
            turn,
            requested_model=requested_model,
        )
    state["turns"] = turns
    reviewed_count = sum(
        1
        for turn in turns
        if isinstance(turn.get("human_review"), dict)
        and _canonical_review_status(
            dict(turn.get("human_review") or {}).get("status")
        )
        and _compact_text(dict(turn.get("human_review") or {}).get("notes"))
    )
    normalized_status = _canonical_final_status(status)
    if not normalized_status:
        raise RuntimeError(
            "Final status accepted, needs_review veya failed olmali."
        )
    target_message_count = max(
        0,
        int(state.get("target_message_count") or 0),
    )
    minimum_turns = max(
        1,
        int(state.get("minimum_turns") or 20),
    )
    message_count = len(turns) + sum(
        1 for turn in turns if _compact_text(turn.get("answer"))
    )
    if normalized_status == "pass" and len(turns) < minimum_turns:
        raise RuntimeError(
            "Pass final assessment icin kampanya sozlesmesindeki minimum tur "
            "sayisina ulasilmalidir."
        )
    if (
        normalized_status == "pass"
        and target_message_count > 0
        and message_count < target_message_count
    ):
        raise RuntimeError(
            "Pass final assessment icin hedef gorunur mesaj sayisina ulasilmalidir."
        )
    if normalized_status == "pass" and reviewed_count != len(turns):
        raise RuntimeError("Pass final assessment icin her tur insan tarafindan incelenmelidir.")
    if normalized_status == "pass" and any(
        _canonical_review_status(
            dict(turn.get("human_review") or {}).get("status")
        )
        != "accepted"
        for turn in turns
    ):
        raise RuntimeError(
            "Pass final assessment icin her tur accepted olmalidir; needs_review veya failed tur kalamaz."
        )
    if normalized_status == "pass" and not _compact_text(notes):
        raise RuntimeError("Pass final assessment icin recovery/kalite notu gerekir.")
    state["final_assessment"] = {
        "status": normalized_status,
        "notes": _compact_text(notes),
        "reviewed_at": _utcnow_iso(),
    }
    state["updated_at"] = _utcnow_iso()
    _write_raw_state(state_path, state)
    artifact = _artifact_payload(state)
    write_live_evidence_file(artifact_path, artifact)
    redacted_assessment, _ = redact_live_evidence(state["final_assessment"])
    return {
        "success": bool(artifact.get("passed")) if normalized_status == "pass" else True,
        "turn_count": len(turns),
        "reviewed_turn_count": reviewed_count,
        "passed": bool(artifact.get("passed")),
        "final_assessment": redacted_assessment,
        "state_path": str(state_path),
        "artifact_path": str(artifact_path),
    }


def review_last_turn(
    *,
    state_path: Path,
    artifact_path: Path,
    status: str,
    notes: str,
) -> dict[str, Any]:
    """Review the current visible answer without generating another model turn."""

    state = _load_json(state_path)
    if not state:
        raise RuntimeError("Incelenecek canli degerlendirme state'i bulunamadi.")
    _review_previous(state, status=status, notes=notes)
    requested_model = _compact_text(state.get("requested_model"))
    turns = [dict(turn) for turn in list(state.get("turns") or [])]
    for turn in turns:
        _normalize_turn_model_evaluation(
            turn,
            requested_model=requested_model,
        )
    state["turns"] = turns
    state["updated_at"] = _utcnow_iso()
    _write_raw_state(state_path, state)
    artifact = _artifact_payload(state)
    write_live_evidence_file(artifact_path, artifact)
    review = dict(turns[-1].get("human_review") or {})
    redacted_review, _ = redact_live_evidence(review)
    return {
        "turn": int(turns[-1].get("turn") or len(turns)),
        "status": _canonical_review_status(review.get("status")),
        "review": redacted_review,
        "state_path": str(state_path),
        "artifact_path": str(artifact_path),
    }


def run_turn(
    *,
    state_path: Path,
    artifact_path: Path,
    provider_code: str,
    model: str,
    prompt: str,
    selection_reason: str,
    review_previous_status: str = "",
    review_previous_notes: str = "",
    db_name: str = DB_NAME,
    timeout: float = 180.0,
    target_message_count: int = 0,
    minimum_turns: int = 0,
    required_domains: Sequence[str] | str | None = None,
    switch_runtime: bool = False,
    switch_reason: str = "",
    client_override: Any = None,
    is_local_override: bool = False,
    shutdown_local_after: bool = True,
) -> dict[str, Any]:
    state = _load_json(state_path)
    requested_required_domains = _normalized_required_domains(required_domains)
    if not state:
        cross_domain = len(requested_required_domains) > 1 or any(
            domain not in {"orders", "returns", "labels"}
            for domain in requested_required_domains
        )
        state = {
            "name": (
                "human-directed Orders conversation "
                f"{provider_code}/{model} {_utcnow_iso()}"
            ),
            "created_at": _utcnow_iso(),
            "provider_code": _compact_text(provider_code).casefold(),
            "requested_model": _compact_text(model),
            "initial_provider_code": _compact_text(provider_code).casefold(),
            "initial_requested_model": _compact_text(model),
            "runtime_transitions": [],
            "artifact_type": (
                "ai_cross_domain_live_human_directed_conversation"
                if cross_domain
                else "orders_live_human_directed_conversation"
            ),
            "required_domains": requested_required_domains,
            "target_message_count": max(0, int(target_message_count or 0)),
            "minimum_turns": max(1, int(minimum_turns or 20)),
            "runtime_contract": "typed_goalplan_conversation_v2",
            "history": [],
            "session_state": {},
            "turns": [],
        }
    elif requested_required_domains:
        existing_domains = _normalized_required_domains(
            state.get("required_domains") or []
        )
        if existing_domains and existing_domains != requested_required_domains:
            raise RuntimeError(
                "Baslatilmis kampanyanin zorunlu domain kapsami degistirilemez."
            )
        state["required_domains"] = requested_required_domains
    elif target_message_count > 0:
        existing_target = max(0, int(state.get("target_message_count") or 0))
        if existing_target not in {0, int(target_message_count)}:
            raise RuntimeError(
                "Baslatilmis kampanyanin hedef mesaj sayisi degistirilemez."
            )
        state["target_message_count"] = int(target_message_count)
    if state and minimum_turns > 0:
        existing_minimum = max(1, int(state.get("minimum_turns") or 20))
        if existing_minimum != int(minimum_turns):
            raise RuntimeError(
                "Baslatilmis kampanyanin minimum tur sayisi degistirilemez."
            )
        state["minimum_turns"] = int(minimum_turns)
    requested_provider = _compact_text(provider_code).casefold()
    requested_model = _compact_text(model)
    current_provider = _compact_text(state.get("provider_code")).casefold()
    current_model = _compact_text(state.get("requested_model"))
    runtime_transition: dict[str, Any] = {}
    runtime_changed = (
        bool(current_provider or current_model)
        and (
            requested_provider != current_provider
            or requested_model != current_model
        )
    )
    if runtime_changed:
        if not switch_runtime:
            raise RuntimeError(
                "Baslatilmis kampanyada provider/model degisimi icin "
                "--switch-runtime gerekir."
            )
        if not _compact_text(switch_reason):
            raise RuntimeError(
                "Provider/model degisimi icin --switch-reason gerekir."
            )
        history_before_switch = [
            dict(row)
            for row in list(state.get("history") or [])
            if isinstance(row, dict)
        ]
        history_state_hash_before_switch = stable_state_hash(
            {"history": history_before_switch}
        )
        runtime_transition = {
            "effective_turn": len(list(state.get("turns") or [])) + 1,
            "from_provider_code": current_provider,
            "from_model": current_model,
            "to_provider_code": requested_provider,
            "to_model": requested_model,
            "reason": _compact_text(switch_reason),
            "history_message_count_before_switch": len(
                history_before_switch
            ),
            "history_state_hash_before_switch": (
                history_state_hash_before_switch
            ),
            # Runtime selection is allowed to change only provider/model
            # metadata.  The conversation and structured context hash must be
            # byte-for-byte identical when the next runtime starts.
            "history_state_hash_at_runtime_start": (
                history_state_hash_before_switch
            ),
            "changed_at": _utcnow_iso(),
        }
        state["runtime_transitions"] = [
            *list(state.get("runtime_transitions") or []),
            runtime_transition,
        ]
        state["provider_code"] = requested_provider
        state["requested_model"] = requested_model
    requested_model_for_evaluation = (
        current_model
        or _compact_text(state.get("initial_requested_model"))
        or requested_model
    )
    prior_turns = [
        dict(turn)
        for turn in list(state.get("turns") or [])
        if isinstance(turn, dict)
    ]
    for prior_turn in prior_turns:
        _normalize_turn_model_evaluation(
            prior_turn,
            requested_model=requested_model_for_evaluation,
        )
    state["turns"] = prior_turns
    if review_previous_status:
        _review_previous(
            state,
            status=review_previous_status,
            notes=review_previous_notes,
        )

    if client_override is None:
        client, record, is_local = _build_exact_client(
            _compact_text(state.get("provider_code") or provider_code),
            _compact_text(state.get("requested_model") or model),
            timeout=timeout,
        )
    else:
        client = client_override
        record = {}
        is_local = bool(is_local_override)
    history = [
        dict(row)
        for row in list(state.get("history") or [])
        if isinstance(row, dict)
    ]
    if runtime_transition:
        runtime_transition["history_state_hash_at_runtime_start"] = (
            stable_state_hash({"history": history})
        )
        transitions = list(state.get("runtime_transitions") or [])
        transitions[-1] = runtime_transition
        state["runtime_transitions"] = transitions
    try:
        turn = _run_turn(
            prompt,
            phase=f"human_directed_{len(state.get('turns') or []) + 1}",
            selection_reason=selection_reason,
            client=client,
            provider_code=_compact_text(state.get("provider_code")),
            model_name=_compact_text(state.get("requested_model")),
            db_name=db_name,
            history=history,
            session_state=(
                dict(state.get("session_state") or {})
                if isinstance(state.get("session_state"), dict)
                else {}
            ),
        )
    finally:
        if is_local and shutdown_local_after:
            shutdown_managed_llama_servers()
    _normalize_turn_model_evaluation(
        turn,
        requested_model=_compact_text(state.get("requested_model")),
    )
    turn["provider_code"] = _compact_text(state.get("provider_code"))
    turn["requested_model"] = _compact_text(state.get("requested_model"))
    turn["domains_observed"] = _turn_domains(turn)
    next_session_state = (
        dict(turn.pop("session_state", {}) or {})
        if isinstance(turn.get("session_state"), dict)
        else {}
    )
    if next_session_state:
        state["session_state"] = next_session_state
        turn["typed_state_summary"] = {
            "session_state_hash": stable_state_hash(next_session_state),
            "conversation_turn_count": len(
                list(next_session_state.get("conversation_turns") or [])
            ),
            "selection_snapshot_count": len(
                list(next_session_state.get("selection_snapshots") or [])
            ),
            "observation_count": len(
                list(next_session_state.get("observations") or [])
            ),
            "active_selection_ids": dict(
                next_session_state.get("active_selection_ids") or {}
            ),
            "active_pending_action_id": _compact_text(
                next_session_state.get("active_pending_action_id")
            ),
            "pending_action_count": len(
                list(next_session_state.get("pending_actions") or [])
            ),
        }
    if runtime_transition:
        turn["runtime_transition"] = runtime_transition
    state["history"] = history
    state["turns"] = [*list(state.get("turns") or []), turn]
    state["updated_at"] = _utcnow_iso()
    _write_raw_state(state_path, state)
    artifact = _artifact_payload(state)
    write_live_evidence_file(artifact_path, artifact)
    redacted_artifact, _ = redact_live_evidence(artifact)
    redacted_turns = list((redacted_artifact or {}).get("turns") or [])
    redacted_turn = dict(redacted_turns[-1]) if redacted_turns else {}
    return {
        "success": bool(turn.get("model_evaluation_passed")),
        "application_turn_success": bool(turn.get("success")),
        "turn": redacted_turn,
        "state_path": str(state_path),
        "artifact_path": str(artifact_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run exactly one human-selected Orders conversation turn. "
            "The evaluator must read the result before choosing the next prompt."
        )
    )
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument(
        "--provider",
        choices=("gemini", "openrouter", "local-best", "local-weak", "local"),
        default="",
    )
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument(
        "--final-status",
        choices=(
            "accepted",
            "needs_review",
            "failed",
            "pass",
            "partial",
            "fail",
        ),
        default="",
    )
    parser.add_argument("--final-notes", default="")
    parser.add_argument(
        "--review-previous-status",
        choices=(
            "accepted",
            "needs_review",
            "failed",
            "pass",
            "partial",
            "fail",
        ),
        default="",
    )
    parser.add_argument("--review-previous-notes", default="")
    parser.add_argument("--db-name", default=DB_NAME)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--target-message-count",
        type=int,
        default=0,
        help=(
            "Optional visible user+assistant message target. The target is persisted "
            "on the first turn and must be reached before a pass finalization."
        ),
    )
    parser.add_argument(
        "--minimum-turns",
        type=int,
        default=0,
        help=(
            "Focused regression campaigns may persist an explicit minimum turn "
            "contract. Omit to retain the 20-turn long-campaign default."
        ),
    )
    parser.add_argument(
        "--required-domains",
        default="",
        help=(
            "Comma-separated binding domain coverage for this campaign. The "
            "scope is immutable after the first turn and pass finalization is "
            "blocked until every domain has authoritative structured evidence."
        ),
    )
    parser.add_argument(
        "--switch-runtime",
        action="store_true",
        help="Explicitly preserve the conversation while switching provider/model.",
    )
    parser.add_argument(
        "--switch-reason",
        default="",
        help="Required audit reason when --switch-runtime changes provider/model.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.finalize:
        if not args.final_status:
            raise RuntimeError("--finalize icin --final-status gerekir.")
        result = finalize_conversation(
            state_path=Path(args.state_path),
            artifact_path=Path(args.artifact_path),
            status=args.final_status,
            notes=args.final_notes,
        )
    else:
        if not args.provider or not args.model or not args.prompt or not args.reason:
            raise RuntimeError(
                "Yeni tur icin --provider, --model, --prompt ve --reason gerekir."
            )
        result = run_turn(
            state_path=Path(args.state_path),
            artifact_path=Path(args.artifact_path),
            provider_code=args.provider,
            model=args.model,
            prompt=args.prompt,
            selection_reason=args.reason,
            review_previous_status=args.review_previous_status,
            review_previous_notes=args.review_previous_notes,
            db_name=args.db_name,
            timeout=args.timeout,
            target_message_count=max(0, int(args.target_message_count or 0)),
            minimum_turns=max(0, int(args.minimum_turns or 0)),
            required_domains=args.required_domains,
            switch_runtime=bool(args.switch_runtime),
            switch_reason=args.switch_reason,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
