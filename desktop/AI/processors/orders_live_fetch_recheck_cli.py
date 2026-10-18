from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import tempfile
from typing import Any, Sequence

from Account.processors.agentic_repository import list_accounts
from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors.cloud_runtime import build_provider_chat_client
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.orders_live_source_recheck_cli import (
    DEFAULT_OPENROUTER_MODEL,
    _compact_text,
    _load_provider_record,
    _runtime_plan,
    _visible_answer_has_mojibake,
)
from AI.processors.task_runtime import (
    resume_agent_task_with_approval,
    run_agent_task,
)
from AI.processors.tools import orders_count, returns_count
from Marketplaces.processors.catalog import normalize_marketplace_environment
from Orders.processors.agentic_repository import list_orders, list_return_claims
from settings import DB_NAME


DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "source-db-live-recheck"
    / f"live-source-db-fetch-recheck-{date.today().isoformat()}.json"
)


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else ""


def _active_trendyol_accounts(
    *,
    db_name: str,
    environment: str = "all",
) -> list[dict[str, Any]]:
    result = list_accounts(active_only=True, db_name=db_name)
    if not result.success:
        raise RuntimeError(result.message)
    rows = list((result.data or {}).get("records") or [])
    normalized_scope = _compact_text(environment).casefold() or "all"
    accounts: list[dict[str, Any]] = []
    for row in rows:
        if (
            int(getattr(row, "pk", 0) or 0) <= 0
            or not bool(getattr(row, "is_active", False))
            or _compact_text(getattr(row, "platform", "")).casefold() != "trendyol"
        ):
            continue
        raw_extra = getattr(row, "extra_config", None)
        extra = dict(raw_extra or {}) if isinstance(raw_extra, dict) else {}
        raw_environment = _compact_text(extra.get("environment")).casefold()
        account_environment = normalize_marketplace_environment(raw_environment or "production")
        if normalized_scope != "all" and account_environment != normalized_scope:
            continue
        accounts.append(
            {
                "pk": int(getattr(row, "pk", 0) or 0),
                "platform": _compact_text(getattr(row, "platform", "")),
                "environment": account_environment,
                "last_used_at": _iso(getattr(row, "last_used_at", None)),
            }
        )
    return accounts


def _source_counts(*, db_name: str) -> dict[str, int]:
    order_result = orders_count(db_name=db_name, period="all")
    return_result = returns_count(db_name=db_name, period="all")
    if not order_result.success:
        raise RuntimeError(order_result.message)
    if not return_result.success:
        raise RuntimeError(return_result.message)
    return {
        "latest_orders": int(
            (order_result.data or {}).get("count") or 0
        ),
        "active_returns": int(
            (return_result.data or {}).get("count") or 0
        ),
    }


def _state_from_result(result: Any) -> dict[str, Any]:
    return dict((result.data or {}).get("state") or {})


def _pending_action(state: dict[str, Any]) -> dict[str, Any]:
    pending = [
        dict(row)
        for row in list(state.get("pending_actions") or [])
        if isinstance(row, dict)
    ]
    if len(pending) != 1:
        raise RuntimeError(
            f"Expected one pending fetch action, got {len(pending)}."
        )
    return pending[0]


def _action_type(action: dict[str, Any]) -> str:
    return _compact_text(
        action.get("operation")
        or action.get("action_type")
    )


def _action_payload(action: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(action.get("arguments") or {})
    return dict(arguments.get("payload") or {})


def _task_plan(state: dict[str, Any]) -> dict[str, Any]:
    return dict(
        (state.get("active_entities") or {}).get("task_plan")
        or {}
    )


def _completed_tool_names(state: dict[str, Any]) -> list[str]:
    return [
        _compact_text(name)
        for step in list(state.get("completed_steps") or [])
        if isinstance(step, dict)
        for name in list(step.get("tool_names") or [])
        if _compact_text(name)
    ]


def _order_number_from_row(row: Any) -> str:
    if isinstance(row, dict):
        return _compact_text(
            row.get("orderNumber")
            or row.get("order_number")
        )
    return _compact_text(getattr(row, "orderNumber", ""))


def _claim_id_from_row(row: Any) -> str:
    if isinstance(row, dict):
        return _compact_text(
            row.get("claimId")
            or row.get("claim_id")
        )
    return _compact_text(getattr(row, "claimId", ""))


def _fetched_identifiers(
    result_data: dict[str, Any],
) -> tuple[list[str], list[str]]:
    safe_identifiers = dict(result_data.get("fetched_identifiers") or {})
    if safe_identifiers:
        return (
            list(
                dict.fromkeys(
                    _compact_text(value)
                    for value in list(safe_identifiers.get("order_numbers") or [])
                    if _compact_text(value)
                )
            ),
            list(
                dict.fromkeys(
                    _compact_text(value)
                    for value in list(safe_identifiers.get("claim_ids") or [])
                    if _compact_text(value)
                )
            ),
        )
    fetch = dict(result_data.get("fetch") or {})
    returns_fetch = dict(result_data.get("returns_fetch") or {})
    order_numbers = list(
        dict.fromkeys(
            _order_number_from_row(row)
            for row in list(fetch.get("order_data_list") or [])
            if _order_number_from_row(row)
        )
    )
    claim_ids = list(
        dict.fromkeys(
            _claim_id_from_row(row)
            for row in list(
                returns_fetch.get("return_claim_list") or []
            )
            if _claim_id_from_row(row)
        )
    )
    return order_numbers, claim_ids


def _db_identifier_readback(
    *,
    order_numbers: Sequence[str],
    claim_ids: Sequence[str],
    db_name: str,
) -> dict[str, Any]:
    found_orders: set[str] = set()
    found_claims: set[str] = set()
    if order_numbers:
        order_result = list_orders(order_numbers=list(order_numbers), db_name=db_name)
        if not order_result.success:
            raise RuntimeError(order_result.message)
        found_orders = {
            _compact_text(getattr(row, "orderNumber", ""))
            for row in list((order_result.data or {}).get("records") or [])
        }
    if claim_ids:
        claim_result = list_return_claims(
            claim_ids=list(claim_ids),
            active=True,
            db_name=db_name,
        )
        if not claim_result.success:
            raise RuntimeError(claim_result.message)
        found_claims = {
            _compact_text(getattr(row, "claimId", ""))
            for row in list((claim_result.data or {}).get("records") or [])
        }
    return {
        "requested_order_numbers": list(order_numbers),
        "found_order_numbers": sorted(found_orders),
        "all_orders_found": set(order_numbers) <= found_orders,
        "requested_claim_ids": list(claim_ids),
        "found_claim_ids": sorted(found_claims),
        "all_claims_found": set(claim_ids) <= found_claims,
    }


def _last_used_advanced(
    before: Sequence[dict[str, Any]],
    after: Sequence[dict[str, Any]],
) -> bool:
    before_map = {
        int(row.get("pk") or 0): _compact_text(
            row.get("last_used_at")
        )
        for row in before
    }
    after_map = {
        int(row.get("pk") or 0): _compact_text(
            row.get("last_used_at")
        )
        for row in after
    }
    if not before_map or set(before_map) != set(after_map):
        return False
    for account_id, after_value in after_map.items():
        if not after_value:
            return False
        before_value = before_map.get(account_id)
        if before_value and after_value <= before_value:
            return False
    return True


def run_provider_fetch_recheck(
    provider_code: str,
    *,
    db_name: str = DB_NAME,
    timeout: float = 240.0,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
    environment: str = "all",
) -> dict[str, Any]:
    record = _load_provider_record(
        provider_code,
        openrouter_model=openrouter_model,
    )
    client = build_provider_chat_client(record, timeout=timeout)
    if client is None:
        raise RuntimeError(f"{provider_code} client could not be built")

    accounts_before = _active_trendyol_accounts(
        db_name=db_name,
        environment=environment,
    )
    if not accounts_before:
        raise RuntimeError(
            "Source DB has no active Trendyol account."
        )
    counts_before = _source_counts(db_name=db_name)
    with tempfile.TemporaryDirectory(
        prefix="orderscout-live-fetch-"
    ) as temp_dir:
        audit_path = Path(temp_dir) / f"{provider_code}-audit.jsonl"
        scope_prefix = (
            "Yalniz production "
            if environment == "production"
            else "Yalniz stage "
            if environment == "stage"
            else ""
        )
        goal = (
            f"{scope_prefix}Trendyol siparis ve iade verilerini cek, kaydet "
            "ve lokal kayitlarla senkronize et"
        )
        prepared = run_agent_task(
            goal,
            planner_client=client,
            chat_client=client,
            db_name=db_name,
            persist=False,
            runtime_context={
                "provider_code": provider_code,
                "provider_id": record.get("pk"),
                "actual_model": record.get("default_model"),
                "reasoning_effort": "auto",
            },
        )
        prepared_state = _state_from_result(prepared)
        action = _pending_action(prepared_state)
        payload = _action_payload(action)
        prepare_answer = _compact_text(
            (prepared.data or {}).get("answer")
            or prepared.message
        )
        accounts_after_prepare = _active_trendyol_accounts(
            db_name=db_name,
            environment=environment,
        )
        counts_after_prepare = _source_counts(db_name=db_name)

        resumed = resume_agent_task_with_approval(
            prepared_state,
            approved_by="live-source-db-evaluator",
            planner_client=client,
            chat_client=client,
            db_name=db_name,
            audit_path=str(audit_path),
            idempotency_key=(
                f"source-db-fetch-{provider_code}-"
                f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            ),
            persist=False,
        )
        resumed_state = _state_from_result(resumed)
        execute_data = dict((resumed.data or {}).get("execute") or {})
        result_data = dict(execute_data.get("result") or {})
        verify = dict(execute_data.get("verify") or {})
        final_answer = _compact_text(
            (resumed.data or {}).get("answer")
            or resumed.message
        )
        accounts_after = _active_trendyol_accounts(
            db_name=db_name,
            environment=environment,
        )
        counts_after = _source_counts(db_name=db_name)
        order_numbers, claim_ids = _fetched_identifiers(
            result_data
        )
        readback = _db_identifier_readback(
            order_numbers=order_numbers,
            claim_ids=claim_ids,
            db_name=db_name,
        )
        audit_text = (
            audit_path.read_text(encoding="utf-8")
            if audit_path.exists()
            else ""
        )
        audit_path.unlink(missing_ok=True)

    task_plan = _task_plan(prepared_state)
    progress = [
        dict(row)
        for row in list(resumed_state.get("progress_events") or [])
        if isinstance(row, dict)
    ]
    prepare_lower = prepare_answer.casefold()
    final_lower = final_answer.casefold()
    expected_account_ids = sorted(
        int(row.get("pk") or 0)
        for row in accounts_before
    )
    payload_account_ids = sorted(
        int(value)
        for value in list(payload.get("api_account_ids") or [])
    )
    last_used_verify = dict(
        verify.get("last_used_update") or {}
    )
    reconciliation = dict(
        verify.get("return_reconciliation") or {}
    )
    checks = {
        "prepare_succeeded": bool(prepared.success),
        "task_plan_selected_fetch": (
            list(task_plan.get("step_ids") or [])
            == ["orders.fetch.prepare"]
            and _completed_tool_names(prepared_state)
            == ["operations.manual_action.route"]
        ),
        "prepare_uses_all_active_trendyol_accounts": (
            payload_account_ids == expected_account_ids
        ),
        "prepare_enables_order_return_save_and_reconciliation": (
            payload.get("save_to_db") is True
            and payload.get("fetch_returns") is True
            and payload.get("save_returns_to_db") is True
            and payload.get("verify_return_reconciliation") is True
        ),
        "prepare_waits_for_approval": (
            prepared_state.get("status") == "pending_approval"
            and _action_type(action)
            == "orders.get_orders_from_companies"
        ),
        "prepare_did_not_change_source_state": (
            accounts_after_prepare == accounts_before
            and counts_after_prepare == counts_before
        ),
        "prepare_answer_is_safe": (
            "onay" in prepare_lower
            and "yapilmadi" in prepare_lower
            and "agent task runtime ara durumda durdu"
            not in prepare_lower
            and not _visible_answer_has_mojibake(
                prepare_answer
            )
        ),
        "execute_succeeded": bool(resumed.success),
        "task_completed_after_approval": (
            resumed_state.get("status") == "complete"
            and not list(resumed_state.get("pending_actions") or [])
        ),
        "runtime_verify_succeeded": verify.get("verified") is True,
        "real_order_fetch_result_present": (
            isinstance(result_data.get("fetch"), dict)
            and (
                "order_snapshot_count" in dict(result_data.get("fetch") or {})
                or "order_data_list" in dict(result_data.get("fetch") or {})
            )
        ),
        "real_return_fetch_result_present": (
            isinstance(result_data.get("returns_fetch"), dict)
            and (
                "return_claim_count" in dict(result_data.get("returns_fetch") or {})
                or "return_claim_list" in dict(result_data.get("returns_fetch") or {})
            )
            and not _compact_text(
                result_data.get("returns_fetch_error")
            )
        ),
        "reconciliation_ran_with_fresh_snapshot": (
            bool(reconciliation)
            and reconciliation.get("needs_remote_snapshot")
            is not True
            and reconciliation.get("snapshot_complete") is True
            and reconciliation.get("period")
            == "exact_epoch_window"
            and reconciliation.get("window_field")
            == "lastModifiedDate"
        ),
        "reconciliation_matches_saved_remote_scope": (
            int(reconciliation.get("observed_count") or 0)
            == len(claim_ids)
            and int(reconciliation.get("confirmed_count") or 0)
            == len(claim_ids)
            and int(
                reconciliation.get("unexpected_remote_count")
                or 0
            )
            == 0
        ),
        "reconciliation_findings_are_reported_when_actionable": (
            int(reconciliation.get("stale_count") or 0) == 0
            or (
                "stale" in final_lower
                and str(
                    int(reconciliation.get("stale_count") or 0)
                )
                in final_answer
                and "aksiyon gerekmiyor" not in final_lower
            )
        ),
        "last_used_runtime_verify_succeeded": (
            last_used_verify.get("verified") is True
            and sorted(
                int(value)
                for value in list(
                    last_used_verify.get(
                        "requested_account_ids"
                    )
                    or []
                )
            )
            == expected_account_ids
        ),
        "last_used_independent_readback_advanced": (
            _last_used_advanced(
                accounts_before,
                accounts_after,
            )
        ),
        "fetched_orders_exist_in_source_db": (
            bool(order_numbers)
            and readback.get("all_orders_found") is True
        ),
        "fetched_returns_exist_in_source_db_when_present": (
            not claim_ids
            or readback.get("all_claims_found") is True
        ),
        "audit_contains_action": (
            "orders.get_orders_from_companies" in audit_text
        ),
        "final_answer_reports_verified_sync": (
            "dogrulan" in final_lower
            and "agent gorevi tamamlandi" not in final_lower
            and not _visible_answer_has_mojibake(final_answer)
        ),
        "progress_exposes_prepare_execute_verify": {
            "pending_approval",
            "execute_started",
            "execute_completed",
            "completed",
        }.issubset(
            {
                _compact_text(row.get("phase"))
                for row in progress
            }
        ),
        "temporary_audit_removed": not audit_path.exists(),
    }
    plan = _runtime_plan(client)
    return {
        "provider_code": provider_code,
        "environment_scope": environment,
        "requested_model": _compact_text(record.get("default_model")),
        "actual_model": _compact_text(
            plan.get("actual_model")
            or getattr(client, "model_name", "")
        ),
        "reasoning_effort": "auto",
        "fallback_used": bool(plan.get("fallback_used")),
        "goal": goal,
        "prepare": {
            "answer": prepare_answer,
            "task_status": prepared_state.get("status"),
            "task_plan": task_plan,
            "tool_names": _completed_tool_names(prepared_state),
            "action_type": _action_type(action),
            "payload": {
                "api_account_ids": payload_account_ids,
                "save_to_db": payload.get("save_to_db"),
                "fetch_returns": payload.get("fetch_returns"),
                "save_returns_to_db": payload.get(
                    "save_returns_to_db"
                ),
                "verify_return_reconciliation": payload.get(
                    "verify_return_reconciliation"
                ),
            },
            "source_state_unchanged": (
                accounts_after_prepare == accounts_before
                and counts_after_prepare == counts_before
            ),
        },
        "execute": {
            "answer": final_answer,
            "task_status": resumed_state.get("status"),
            "verify": verify,
            "fetch_counts": {
                "orders": len(order_numbers),
                "returns": len(claim_ids),
            },
            "fetched_order_numbers": order_numbers,
            "fetched_claim_ids": claim_ids,
            "db_readback": readback,
            "audit_action_present": (
                "orders.get_orders_from_companies" in audit_text
            ),
        },
        "source_state": {
            "counts_before": counts_before,
            "counts_after": counts_after,
            "accounts_before": accounts_before,
            "accounts_after": accounts_after,
            "last_used_advanced": _last_used_advanced(
                accounts_before,
                accounts_after,
            ),
        },
        "progress_phases": [
            _compact_text(row.get("phase"))
            for row in progress
            if _compact_text(row.get("phase"))
        ],
        "checks": checks,
    }


def run_source_db_fetch_recheck(
    *,
    provider_codes: Sequence[str] = ("gemini", "openrouter"),
    db_name: str = DB_NAME,
    timeout: float = 240.0,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
    environment: str = "all",
) -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for provider_code in provider_codes:
        try:
            providers.append(
                run_provider_fetch_recheck(
                    provider_code,
                    db_name=db_name,
                    timeout=timeout,
                    openrouter_model=openrouter_model,
                    environment=environment,
                )
            )
        except Exception as exc:
            providers.append(
                {
                    "provider_code": provider_code,
                    "checks": {"completed": False},
                    "error": f"{type(exc).__name__}: {_compact_text(exc)}",
                }
            )
    return {
        "name": (
            "live source DB Orders marketplace fetch recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": (
            "orders_live_source_db_marketplace_fetch_execute_recheck"
        ),
        "created_at": date.today().isoformat(),
        "db": "source-app-db",
        "environment_scope": environment,
        "safety": {
            "computer_use_used": False,
            "packaged_exe_used": False,
            "marketplace_read_performed": True,
            "marketplace_mutation_performed": False,
            "source_db_upsert_performed": True,
        },
        "providers": providers,
        "passed": (
            len(providers) == len(provider_codes)
            and all(
                bool(provider.get("checks"))
                and all(dict(provider.get("checks") or {}).values())
                for provider in providers
            )
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run real source-DB Orders/returns marketplace fetch tasks "
            "through configured cloud providers and verify DB read-back."
        )
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=("gemini", "openrouter"),
        dest="providers",
        help="Provider to run. Repeat for both; defaults to both.",
    )
    parser.add_argument(
        "--openrouter-model",
        default=DEFAULT_OPENROUTER_MODEL,
    )
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument(
        "--environment",
        choices=("all", "production", "stage"),
        default="all",
        help="Scope active Trendyol accounts; production excludes every explicit Stage account.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = run_source_db_fetch_recheck(
        provider_codes=tuple(
            args.providers or ("gemini", "openrouter")
        ),
        timeout=max(30.0, float(args.timeout)),
        openrouter_model=args.openrouter_model,
        environment=args.environment,
    )
    target = write_live_evidence_file(Path(args.output), payload)
    print(f"artifact={target}")
    print(f"passed={bool(payload.get('passed'))}")
    for provider in list(payload.get("providers") or []):
        print(
            "provider="
            f"{provider.get('provider_code')} "
            f"model={provider.get('actual_model') or '-'} "
            f"passed={all(dict(provider.get('checks') or {}).values())}"
        )
        if provider.get("error"):
            print(f"error={provider.get('error')}")
    return 0 if bool(payload.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
