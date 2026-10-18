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
    _visible_answer_has_mojibake,
)
from AI.processors.task_runtime import (
    resume_agent_task_with_approval,
    run_agent_task,
)
from AI.processors.tools import ready_to_ship_orders
from Orders.processors.agentic_repository import (
    list_order_headers,
    restore_order_header_extraction_snapshots,
)
from settings import DB_NAME


DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "source-db-live-recheck"
    / f"live-source-db-extracted-recheck-{date.today().isoformat()}.json"
)


def _header_snapshots(
    order_number: str,
    *,
    db_name: str,
) -> list[dict[str, Any]]:
    result = list_order_headers([order_number], db_name=db_name)
    if not result.success:
        raise RuntimeError(result.message)
    rows = list((result.data or {}).get("records") or [])
    return [
        {
            "pk": int(getattr(row, "pk", 0) or 0),
            "order_number": _compact_text(
                getattr(row, "orderNumber", "")
            ),
            "api_account_id": getattr(row, "api_account_id", None),
            "is_extracted": bool(
                getattr(row, "is_extracted", False)
            ),
            "extracted_at": getattr(row, "extracted_at", None),
        }
        for row in rows
        if int(getattr(row, "pk", 0) or 0) > 0
    ]


def _restore_header_snapshots(
    snapshots: Sequence[dict[str, Any]],
    *,
    db_name: str,
) -> None:
    result = restore_order_header_extraction_snapshots(
        list(snapshots),
        db_name=db_name,
    )
    if not result.success:
        raise RuntimeError(result.message)


def _select_source_seed(*, db_name: str = DB_NAME) -> dict[str, Any]:
    result = ready_to_ship_orders(
        db_name=db_name,
        period="all",
        limit=100,
    )
    if not result.success:
        raise RuntimeError(result.message)
    for row in list((result.data or {}).get("orders") or []):
        if not isinstance(row, dict) or bool(row.get("extracted")):
            continue
        order_number = _compact_text(row.get("order_number"))
        snapshots = _header_snapshots(
            order_number,
            db_name=db_name,
        )
        if not snapshots:
            continue
        if any(
            bool(snapshot.get("is_extracted"))
            for snapshot in snapshots
        ):
            continue
        return {
            "order_number": order_number,
            "header_count": len(snapshots),
            "status": _compact_text(row.get("status")),
            "state_before": snapshots,
        }
    raise RuntimeError(
        "Source DB has no ready order with an unextracted header."
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
            f"Expected one pending extracted action, got {len(pending)}."
        )
    return pending[0]


def _action_type(action: dict[str, Any]) -> str:
    return _compact_text(
        action.get("operation")
        or action.get("action_type")
    )


def _action_order_numbers(action: dict[str, Any]) -> list[str]:
    arguments = dict(action.get("arguments") or {})
    payload = dict(arguments.get("payload") or {})
    values = list(
        payload.get("order_numbers")
        or payload.get("orders")
        or arguments.get("order_numbers")
        or []
    )
    values.extend(
        _compact_text(ref.get("orderNumber"))
        for ref in list(payload.get("order_refs") or [])
        if isinstance(ref, dict)
    )
    return list(
        dict.fromkeys(
            _compact_text(value)
            for value in values
            if _compact_text(value)
        )
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
        "order_number",
        "api_account_id",
        "is_extracted",
        "extracted_at",
    )
    normalize = lambda rows: sorted(
        [
            tuple(row.get(field) for field in fields)
            for row in rows
        ],
        key=lambda row: row[0],
    )
    return normalize(left) == normalize(right)


def run_provider_extracted_recheck(
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

    order_number = _compact_text(seed.get("order_number"))
    original = [
        dict(row)
        for row in list(seed.get("state_before") or [])
    ]
    _restore_header_snapshots(original, db_name=db_name)
    with tempfile.TemporaryDirectory(
        prefix="orderscout-live-extracted-"
    ) as temp_dir:
        audit_path = Path(temp_dir) / f"{provider_code}-audit.jsonl"
        goal = (
            f"{order_number} numarali siparisi fis cikarildi "
            "olarak isaretle"
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
        state_after_prepare = _header_snapshots(
            order_number,
            db_name=db_name,
        )
        prepare_answer = _compact_text(
            (prepared.data or {}).get("answer")
            or prepared.message
        )

        resumed: Any = None
        state_after_execute: list[dict[str, Any]] = []
        audit_text = ""
        try:
            resumed = resume_agent_task_with_approval(
                prepared_state,
                approved_by="live-source-db-evaluator",
                planner_client=client,
                chat_client=client,
                db_name=db_name,
                audit_path=str(audit_path),
                idempotency_key=(
                    f"source-db-extracted-{provider_code}-"
                    f"{date.today().isoformat()}"
                ),
                persist=False,
            )
            state_after_execute = _header_snapshots(
                order_number,
                db_name=db_name,
            )
            audit_text = (
                audit_path.read_text(encoding="utf-8")
                if audit_path.exists()
                else ""
            )
        finally:
            _restore_header_snapshots(original, db_name=db_name)
        state_after_restore = _header_snapshots(
            order_number,
            db_name=db_name,
        )
        audit_path.unlink(missing_ok=True)

    if resumed is None:
        raise RuntimeError("Extracted action did not return a resume result.")
    resumed_state = _state_from_result(resumed)
    execute_data = dict((resumed.data or {}).get("execute") or {})
    verify = dict(execute_data.get("verify") or {})
    final_answer = _compact_text(
        (resumed.data or {}).get("answer")
        or resumed.message
    )
    progress = [
        dict(row)
        for row in list(resumed_state.get("progress_events") or [])
        if isinstance(row, dict)
    ]
    task_plan = dict(
        (prepared_state.get("active_entities") or {}).get(
            "task_plan"
        )
        or {}
    )
    plan = _runtime_plan(client)
    prepare_lower = prepare_answer.casefold()
    final_lower = final_answer.casefold()
    checks = {
        "prepare_succeeded": bool(prepared.success),
        "task_plan_selected_extracted_prepare": (
            "orders.labels.extracted.prepare"
            in list(task_plan.get("step_ids") or [])
            and "operations.manual_action.route"
            in _completed_tool_names(prepared_state)
        ),
        "prepare_uses_exact_source_order": (
            _action_order_numbers(action) == [order_number]
        ),
        "prepare_waits_for_approval": (
            prepared_state.get("status") == "pending_approval"
            and _action_type(action)
            == "labels.mark_orders_extracted_from_label_result"
        ),
        "prepare_did_not_write_db": _snapshot_matches(
            original,
            state_after_prepare,
        ),
        "prepare_answer_explains_exact_pending_action": (
            order_number in prepare_answer
            and "onay" in prepare_lower
            and "yapilmadi" in prepare_lower
            and "agent task runtime ara durumda durdu"
            not in prepare_lower
        ),
        "execute_succeeded": bool(resumed.success),
        "task_completed_after_approval": (
            resumed_state.get("status") == "complete"
            and not list(resumed_state.get("pending_actions") or [])
        ),
        "runtime_verify_succeeded": verify.get("verified") is True,
        "independent_db_readback_is_extracted": (
            bool(state_after_execute)
            and all(
                bool(row.get("is_extracted"))
                for row in state_after_execute
            )
        ),
        "audit_contains_action": (
            "labels.mark_orders_extracted_from_label_result"
            in audit_text
        ),
        "final_answer_names_verified_order": (
            order_number in final_answer
            and "dogrulan" in final_lower
            and "agent gorevi tamamlandi" not in final_lower
            and not _visible_answer_has_mojibake(final_answer)
        ),
        "source_db_restored_exactly": _snapshot_matches(
            original,
            state_after_restore,
        ),
        "temporary_audit_removed": not audit_path.exists(),
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
    }
    return {
        "provider_code": provider_code,
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
            "order_numbers": _action_order_numbers(action),
            "db_state_unchanged": _snapshot_matches(
                original,
                state_after_prepare,
            ),
        },
        "execute": {
            "answer": final_answer,
            "task_status": resumed_state.get("status"),
            "verify": verify,
            "db_readback": state_after_execute,
            "audit_action_present": (
                "labels.mark_orders_extracted_from_label_result"
                in audit_text
            ),
        },
        "cleanup": {
            "restored_state": state_after_restore,
            "source_db_restored_exactly": _snapshot_matches(
                original,
                state_after_restore,
            ),
            "temporary_audit_removed": not audit_path.exists(),
        },
        "progress_phases": [
            _compact_text(row.get("phase"))
            for row in progress
            if _compact_text(row.get("phase"))
        ],
        "checks": checks,
    }


def run_source_db_extracted_recheck(
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
                run_provider_extracted_recheck(
                    provider_code,
                    seed=seed,
                    db_name=db_name,
                    timeout=timeout,
                    openrouter_model=openrouter_model,
                )
            )
        except Exception as exc:
            _restore_header_snapshots(
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
    final_state = _header_snapshots(
        _compact_text(seed.get("order_number")),
        db_name=db_name,
    )
    source_db_restored = _snapshot_matches(
        list(seed.get("state_before") or []),
        final_state,
    )
    return {
        "name": (
            "live source DB Orders extracted-state recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": (
            "orders_live_source_db_extracted_execute_recheck"
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
            "Run real source-DB Orders extracted-state tasks through "
            "configured cloud providers, verify DB state, then restore it."
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

    payload = run_source_db_extracted_recheck(
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
