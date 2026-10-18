from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import tempfile
from typing import Any, Sequence

from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors.cloud_runtime import build_provider_chat_client
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.orders_live_source_recheck_cli import (
    DEFAULT_OPENROUTER_MODEL,
    _compact_text,
    _load_provider_record,
    _runtime_plan,
    _valid_source_identifier,
    _visible_answer_has_mojibake,
)
from AI.processors.task_runtime import (
    resume_agent_task_with_approval,
    run_agent_task,
)
from AI.processors.tools import returns_query
from Orders.processors.agentic_repository import (
    list_return_claims,
    restore_return_claim_sync_snapshots,
)
from settings import DB_NAME


DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "source-db-live-recheck"
    / f"live-source-db-stale-cycle-recheck-{date.today().isoformat()}.json"
)


def _claim_snapshots(
    claim_id: str,
    *,
    db_name: str,
) -> list[dict[str, Any]]:
    result = list_return_claims(
        claim_ids=[claim_id],
        active=None,
        db_name=db_name,
    )
    if not result.success:
        raise RuntimeError(result.message)
    rows = list((result.data or {}).get("records") or [])
    return [
        {
            "pk": int(getattr(row, "pk", 0) or 0),
            "api_account_id": getattr(row, "api_account_id", None),
            "claim_id": _compact_text(
                getattr(row, "claimId", "")
            ),
            "order_number": _compact_text(
                getattr(row, "orderNumber", "")
            ),
            "status": _compact_text(getattr(row, "status", "")),
            "sync_deleted_at": getattr(
                row,
                "sync_deleted_at",
                None,
            ),
        }
        for row in rows
        if int(getattr(row, "pk", 0) or 0) > 0
    ]


def _restore_claim_snapshots(
    snapshots: Sequence[dict[str, Any]],
    *,
    db_name: str,
) -> None:
    result = restore_return_claim_sync_snapshots(
        list(snapshots),
        db_name=db_name,
    )
    if not result.success:
        raise RuntimeError(result.message)


def _select_source_seed(*, db_name: str = DB_NAME) -> dict[str, Any]:
    for status in ("Cancelled", "Accepted"):
        result = returns_query(
            db_name=db_name,
            period="all",
            filters={"status": status},
            sort="claim_date_asc",
            limit=100,
            mode="list",
        )
        if not result.success:
            raise RuntimeError(result.message)
        for row in list((result.data or {}).get("returns") or []):
            if not isinstance(row, dict):
                continue
            claim_id = _compact_text(row.get("claim_id"))
            if not _valid_source_identifier(claim_id):
                continue
            snapshots = _claim_snapshots(
                claim_id,
                db_name=db_name,
            )
            if not snapshots:
                continue
            if any(
                snapshot.get("sync_deleted_at")
                for snapshot in snapshots
            ):
                continue
            return {
                "claim_id": claim_id,
                "order_number": _compact_text(
                    row.get("order_number")
                ),
                "status": status,
                "snapshot_count": len(snapshots),
                "state_before": snapshots,
            }
    raise RuntimeError(
        "Source DB has no closed active return claim for a stale cycle."
    )


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
            f"Expected one pending stale action, got {len(pending)}."
        )
    return pending[0]


def _action_type(action: dict[str, Any]) -> str:
    return _compact_text(
        action.get("operation")
        or action.get("action_type")
    )


def _action_claim_ids(action: dict[str, Any]) -> list[str]:
    arguments = dict(action.get("arguments") or {})
    payload = dict(arguments.get("payload") or {})
    values = list(
        payload.get("claim_ids")
        or arguments.get("claim_ids")
        or []
    )
    single = _compact_text(
        payload.get("claim_id")
        or payload.get("order")
        or arguments.get("claim_id")
    )
    if single:
        values.insert(0, single)
    return list(
        dict.fromkeys(
            _compact_text(value)
            for value in values
            if _compact_text(value)
        )
    )


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


def _snapshot_matches(
    left: Sequence[dict[str, Any]],
    right: Sequence[dict[str, Any]],
) -> bool:
    fields = (
        "pk",
        "api_account_id",
        "claim_id",
        "order_number",
        "status",
        "sync_deleted_at",
    )
    normalize = lambda rows: sorted(
        [
            tuple(row.get(field) for field in fields)
            for row in rows
        ],
        key=lambda row: row[0],
    )
    return normalize(left) == normalize(right)


def run_provider_stale_cycle_recheck(
    provider_code: str,
    *,
    seed: dict[str, Any],
    db_name: str = DB_NAME,
    timeout: float = 180.0,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
) -> dict[str, Any]:
    record = _load_provider_record(
        provider_code,
        openrouter_model=openrouter_model,
    )
    client = build_provider_chat_client(record, timeout=timeout)
    if client is None:
        raise RuntimeError(f"{provider_code} client could not be built")

    claim_id = _compact_text(seed.get("claim_id"))
    original = [
        dict(row)
        for row in list(seed.get("state_before") or [])
    ]
    _restore_claim_snapshots(original, db_name=db_name)
    with tempfile.TemporaryDirectory(
        prefix="orderscout-live-stale-cycle-"
    ) as temp_dir:
        root = Path(temp_dir)
        mark_audit_path = root / f"{provider_code}-mark-audit.jsonl"
        restore_audit_path = (
            root / f"{provider_code}-restore-audit.jsonl"
        )
        state_after_mark_prepare: list[dict[str, Any]] = []
        state_after_mark: list[dict[str, Any]] = []
        state_after_restore_prepare: list[dict[str, Any]] = []
        state_after_restore: list[dict[str, Any]] = []
        mark: dict[str, Any] = {}
        restore: dict[str, Any] = {}
        mark_audit_text = ""
        restore_audit_text = ""
        try:
            mark_goal = (
                f"{claim_id} webde yok, stale iade kaydini temizle"
            )
            mark_prepared = run_agent_task(
                mark_goal,
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
            mark_prepared_state = _state_from_result(mark_prepared)
            mark_action = _pending_action(mark_prepared_state)
            state_after_mark_prepare = _claim_snapshots(
                claim_id,
                db_name=db_name,
            )
            mark_resumed = resume_agent_task_with_approval(
                mark_prepared_state,
                approved_by="live-source-db-evaluator",
                planner_client=client,
                chat_client=client,
                db_name=db_name,
                audit_path=str(mark_audit_path),
                idempotency_key=(
                    f"source-db-stale-{provider_code}-mark-"
                    f"{date.today().isoformat()}"
                ),
                persist=False,
            )
            mark_resumed_state = _state_from_result(mark_resumed)
            mark_execute = dict(
                (mark_resumed.data or {}).get("execute") or {}
            )
            state_after_mark = _claim_snapshots(
                claim_id,
                db_name=db_name,
            )
            mark_audit_text = (
                mark_audit_path.read_text(encoding="utf-8")
                if mark_audit_path.exists()
                else ""
            )
            mark = {
                "goal": mark_goal,
                "prepare_answer": _compact_text(
                    (mark_prepared.data or {}).get("answer")
                    or mark_prepared.message
                ),
                "final_answer": _compact_text(
                    (mark_resumed.data or {}).get("answer")
                    or mark_resumed.message
                ),
                "prepare_status": mark_prepared_state.get("status"),
                "final_status": mark_resumed_state.get("status"),
                "task_plan": _task_plan(mark_prepared_state),
                "tool_names": _completed_tool_names(
                    mark_prepared_state
                ),
                "action_type": _action_type(mark_action),
                "claim_ids": _action_claim_ids(mark_action),
                "verify": dict(mark_execute.get("verify") or {}),
                "progress_phases": [
                    _compact_text(row.get("phase"))
                    for row in list(
                        mark_resumed_state.get("progress_events")
                        or []
                    )
                    if isinstance(row, dict)
                    and _compact_text(row.get("phase"))
                ],
                "prepared_success": bool(mark_prepared.success),
                "resumed_success": bool(mark_resumed.success),
            }

            restore_goal = f"{claim_id} stale iadesini geri al"
            restore_prepared = run_agent_task(
                restore_goal,
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
            restore_prepared_state = _state_from_result(
                restore_prepared
            )
            restore_action = _pending_action(
                restore_prepared_state
            )
            state_after_restore_prepare = _claim_snapshots(
                claim_id,
                db_name=db_name,
            )
            restore_resumed = resume_agent_task_with_approval(
                restore_prepared_state,
                approved_by="live-source-db-evaluator",
                planner_client=client,
                chat_client=client,
                db_name=db_name,
                audit_path=str(restore_audit_path),
                idempotency_key=(
                    f"source-db-stale-{provider_code}-restore-"
                    f"{date.today().isoformat()}"
                ),
                persist=False,
            )
            restore_resumed_state = _state_from_result(
                restore_resumed
            )
            restore_execute = dict(
                (restore_resumed.data or {}).get("execute") or {}
            )
            state_after_restore = _claim_snapshots(
                claim_id,
                db_name=db_name,
            )
            restore_audit_text = (
                restore_audit_path.read_text(encoding="utf-8")
                if restore_audit_path.exists()
                else ""
            )
            restore = {
                "goal": restore_goal,
                "prepare_answer": _compact_text(
                    (restore_prepared.data or {}).get("answer")
                    or restore_prepared.message
                ),
                "final_answer": _compact_text(
                    (restore_resumed.data or {}).get("answer")
                    or restore_resumed.message
                ),
                "prepare_status": restore_prepared_state.get(
                    "status"
                ),
                "final_status": restore_resumed_state.get("status"),
                "task_plan": _task_plan(restore_prepared_state),
                "tool_names": _completed_tool_names(
                    restore_prepared_state
                ),
                "action_type": _action_type(restore_action),
                "claim_ids": _action_claim_ids(restore_action),
                "verify": dict(
                    restore_execute.get("verify") or {}
                ),
                "progress_phases": [
                    _compact_text(row.get("phase"))
                    for row in list(
                        restore_resumed_state.get(
                            "progress_events"
                        )
                        or []
                    )
                    if isinstance(row, dict)
                    and _compact_text(row.get("phase"))
                ],
                "prepared_success": bool(restore_prepared.success),
                "resumed_success": bool(restore_resumed.success),
            }
        finally:
            _restore_claim_snapshots(original, db_name=db_name)
        final_state = _claim_snapshots(
            claim_id,
            db_name=db_name,
        )
        mark_audit_path.unlink(missing_ok=True)
        restore_audit_path.unlink(missing_ok=True)

    mark_prepare_lower = _compact_text(
        mark.get("prepare_answer")
    ).casefold()
    mark_final_lower = _compact_text(
        mark.get("final_answer")
    ).casefold()
    restore_prepare_lower = _compact_text(
        restore.get("prepare_answer")
    ).casefold()
    restore_final_lower = _compact_text(
        restore.get("final_answer")
    ).casefold()
    required_progress = {
        "pending_approval",
        "execute_started",
        "execute_completed",
        "completed",
    }
    checks = {
        "mark_prepare_succeeded": bool(mark.get("prepared_success")),
        "mark_task_plan_is_exact": (
            list((mark.get("task_plan") or {}).get("step_ids") or [])
            == ["returns.stale.mark.prepare"]
            and mark.get("tool_names")
            == ["returns.mark_stale.prepare"]
        ),
        "mark_action_is_exact": (
            mark.get("action_type")
            == "orders.mark_return_claims_stale"
            and mark.get("claim_ids") == [claim_id]
        ),
        "mark_prepare_waits_without_write": (
            mark.get("prepare_status") == "pending_approval"
            and _snapshot_matches(
                original,
                state_after_mark_prepare,
            )
        ),
        "mark_prepare_answer_is_safe_and_exact": (
            claim_id in _compact_text(mark.get("prepare_answer"))
            and "onay" in mark_prepare_lower
            and "yapilmadi" in mark_prepare_lower
        ),
        "mark_execute_and_verify_succeeded": (
            bool(mark.get("resumed_success"))
            and mark.get("final_status") == "complete"
            and (mark.get("verify") or {}).get("verified") is True
        ),
        "mark_independent_readback_is_stale": (
            bool(state_after_mark)
            and all(
                bool(row.get("sync_deleted_at"))
                for row in state_after_mark
            )
        ),
        "mark_final_answer_is_grounded": (
            claim_id in _compact_text(mark.get("final_answer"))
            and "dogrulan" in mark_final_lower
            and "agent gorevi tamamlandi" not in mark_final_lower
            and not _visible_answer_has_mojibake(
                mark.get("final_answer")
            )
        ),
        "mark_audit_contains_action": (
            "orders.mark_return_claims_stale"
            in mark_audit_text
        ),
        "mark_progress_is_complete": required_progress.issubset(
            set(mark.get("progress_phases") or [])
        ),
        "restore_prepare_succeeded": bool(
            restore.get("prepared_success")
        ),
        "restore_task_plan_is_exact": (
            list(
                (restore.get("task_plan") or {}).get("step_ids")
                or []
            )
            == ["returns.stale.restore.prepare"]
            and restore.get("tool_names")
            == ["returns.restore_stale.prepare"]
        ),
        "restore_action_is_exact": (
            restore.get("action_type")
            == "orders.restore_return_claims_from_stale"
            and restore.get("claim_ids") == [claim_id]
        ),
        "restore_prepare_waits_without_write": (
            restore.get("prepare_status") == "pending_approval"
            and _snapshot_matches(
                state_after_mark,
                state_after_restore_prepare,
            )
        ),
        "restore_prepare_answer_is_safe_and_exact": (
            claim_id
            in _compact_text(restore.get("prepare_answer"))
            and "onay" in restore_prepare_lower
            and "yapilmadi" in restore_prepare_lower
        ),
        "restore_execute_and_verify_succeeded": (
            bool(restore.get("resumed_success"))
            and restore.get("final_status") == "complete"
            and (restore.get("verify") or {}).get("verified") is True
        ),
        "restore_independent_readback_matches_original": (
            _snapshot_matches(original, state_after_restore)
        ),
        "restore_final_answer_is_grounded": (
            claim_id
            in _compact_text(restore.get("final_answer"))
            and "dogrulan" in restore_final_lower
            and "agent gorevi tamamlandi"
            not in restore_final_lower
            and not _visible_answer_has_mojibake(
                restore.get("final_answer")
            )
        ),
        "restore_audit_contains_action": (
            "orders.restore_return_claims_from_stale"
            in restore_audit_text
        ),
        "restore_progress_is_complete": required_progress.issubset(
            set(restore.get("progress_phases") or [])
        ),
        "source_db_restored_exactly": _snapshot_matches(
            original,
            final_state,
        ),
        "temporary_audits_removed": (
            not mark_audit_path.exists()
            and not restore_audit_path.exists()
        ),
    }
    plan = _runtime_plan(client)
    return {
        "provider_code": provider_code,
        "requested_model": _compact_text(record.get("default_model")),
        "actual_model": _compact_text(
            plan.get("actual_model")
            or getattr(client, "model_name", "")
        ),
        "reasoning_effort": "auto",
        "fallback_used": bool(plan.get("fallback_used")),
        "mark": {
            **mark,
            "state_after_prepare": state_after_mark_prepare,
            "state_after_execute": state_after_mark,
            "audit_action_present": (
                "orders.mark_return_claims_stale"
                in mark_audit_text
            ),
        },
        "restore": {
            **restore,
            "state_after_prepare": state_after_restore_prepare,
            "state_after_execute": state_after_restore,
            "audit_action_present": (
                "orders.restore_return_claims_from_stale"
                in restore_audit_text
            ),
        },
        "cleanup": {
            "final_state": final_state,
            "source_db_restored_exactly": _snapshot_matches(
                original,
                final_state,
            ),
            "temporary_audits_removed": (
                not mark_audit_path.exists()
                and not restore_audit_path.exists()
            ),
        },
        "checks": checks,
    }


def run_source_db_stale_cycle_recheck(
    *,
    provider_codes: Sequence[str] = ("gemini", "openrouter"),
    db_name: str = DB_NAME,
    timeout: float = 180.0,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
) -> dict[str, Any]:
    seed = _select_source_seed(db_name=db_name)
    providers: list[dict[str, Any]] = []
    for provider_code in provider_codes:
        try:
            providers.append(
                run_provider_stale_cycle_recheck(
                    provider_code,
                    seed=seed,
                    db_name=db_name,
                    timeout=timeout,
                    openrouter_model=openrouter_model,
                )
            )
        except Exception as exc:
            _restore_claim_snapshots(
                list(seed.get("state_before") or []),
                db_name=db_name,
            )
            providers.append(
                {
                    "provider_code": provider_code,
                    "checks": {"completed": False},
                    "error": f"{type(exc).__name__}: {_compact_text(exc)}",
                }
            )
    final_state = _claim_snapshots(
        _compact_text(seed.get("claim_id")),
        db_name=db_name,
    )
    source_db_restored = _snapshot_matches(
        list(seed.get("state_before") or []),
        final_state,
    )
    return {
        "name": (
            "live source DB Orders stale-return cycle recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": (
            "orders_live_source_db_stale_mark_restore_execute_recheck"
        ),
        "created_at": date.today().isoformat(),
        "db": "source-app-db",
        "seed": seed,
        "final_state": final_state,
        "safety": {
            "computer_use_used": False,
            "packaged_exe_used": False,
            "marketplace_write_performed": False,
            "db_write_performed": True,
            "db_write_was_reversible_test": True,
            "waiting_in_action_claim_used": False,
            "source_db_restored_exactly": source_db_restored,
        },
        "providers": providers,
        "passed": (
            source_db_restored
            and len(providers) == len(provider_codes)
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
            "Run a reversible stale mark/restore cycle on one closed "
            "source-DB return through configured cloud providers."
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
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = run_source_db_stale_cycle_recheck(
        provider_codes=tuple(
            args.providers or ("gemini", "openrouter")
        ),
        timeout=max(10.0, float(args.timeout)),
        openrouter_model=args.openrouter_model,
    )
    target = write_live_evidence_file(Path(args.output), payload)
    print(f"artifact={target}")
    print(f"passed={bool(payload.get('passed'))}")
    print(
        "source_db_restored_exactly="
        f"{bool((payload.get('safety') or {}).get('source_db_restored_exactly'))}"
    )
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
