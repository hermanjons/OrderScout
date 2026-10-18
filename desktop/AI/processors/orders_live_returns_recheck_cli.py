from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from Account.processors import agentic_repository as account_repo
from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors.agent import (
    _should_use_deterministic_answer,
    run_agent_turn,
)
from AI.processors.cloud_runtime import build_provider_chat_client
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.orders_live_source_recheck_cli import (
    DEFAULT_OPENROUTER_MODEL,
    _append_history,
    _compact_text,
    _load_provider_record,
    _runtime_plan,
    _valid_source_identifier,
    _visible_answer_has_mojibake,
)
from AI.processors.tools import returns_query
from settings import DB_NAME


DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "source-db-live-recheck"
    / f"live-source-db-returns-conversation-recheck-{date.today().isoformat()}.json"
)


def _return_rows_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(data.get("returns") or [])
        if isinstance(row, dict)
    ]


def _claim_ids_from_tool_result(
    tool_name: str,
    data: dict[str, Any],
) -> list[str]:
    if tool_name not in {"returns.query", "returns.lookup"}:
        return []
    return [
        _compact_text(row.get("claim_id"))
        for row in _return_rows_from_data(data)
        if _compact_text(row.get("claim_id"))
    ]


def _claim_statuses(
    claim_ids: Sequence[str],
    *,
    db_name: str,
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for claim_id in claim_ids:
        result = returns_query(
            db_name=db_name,
            period="all",
            filters={"claim_id": claim_id},
            limit=5,
            mode="list",
        )
        if not result.success:
            raise RuntimeError(result.message)
        rows = _return_rows_from_data(dict(result.data or {}))
        exact = [
            row
            for row in rows
            if _compact_text(row.get("claim_id")) == claim_id
        ]
        if len(exact) != 1:
            raise RuntimeError(
                "Source claim read-back did not resolve exactly one row."
            )
        statuses[claim_id] = _compact_text(exact[0].get("status"))
    return statuses


def _select_source_seed(*, db_name: str = DB_NAME) -> dict[str, Any]:
    result = returns_query(
        db_name=db_name,
        period="all",
        filters={"status": "WaitingInAction"},
        sort="claim_date_desc",
        limit=100,
        mode="list",
    )
    if not result.success:
        raise RuntimeError(result.message)
    rows = _return_rows_from_data(dict(result.data or {}))
    valid_rows = [
        row
        for row in rows
        if _valid_source_identifier(row.get("claim_id"))
        and _valid_source_identifier(row.get("order_number"))
        and _compact_text(row.get("status")) == "WaitingInAction"
        and list(row.get("waiting_line_item_ids") or [])
    ]
    if not valid_rows:
        raise RuntimeError(
            "Source DB has no executable WaitingInAction return claim."
        )
    target = valid_rows[0]
    target_api_account_id = target.get("api_account_id")
    valid_rows = [
        row
        for row in valid_rows
        if row.get("api_account_id") == target_api_account_id
    ]
    account_environment = "production"
    account_store_name = ""
    if target_api_account_id not in (None, ""):
        account_result = account_repo.get_account(
            target_api_account_id,
            db_name=db_name,
        )
        if account_result.success:
            account = (account_result.data or {}).get("record")
            extra_config = getattr(account, "extra_config", None)
            extra = dict(extra_config or {}) if isinstance(extra_config, dict) else {}
            raw_environment = _compact_text(
                extra.get("environment") or "production"
            ).casefold()
            account_environment = (
                "stage"
                if raw_environment in {"stage", "staging", "test", "sandbox"}
                else "production"
            )
            account_store_name = _compact_text(getattr(account, "comp_name", ""))
    claim_ids = [
        _compact_text(row.get("claim_id"))
        for row in valid_rows
    ]
    customer_names = list(
        dict.fromkeys(
            " ".join(
                part
                for part in (
                    _compact_text(row.get("customer_first_name")),
                    _compact_text(row.get("customer_last_name")),
                )
                if part
            ).strip()
            for row in valid_rows
            if any(
                (
                    _compact_text(row.get("customer_first_name")),
                    _compact_text(row.get("customer_last_name")),
                )
            )
        )
    )
    return {
        "target_claim_id": _compact_text(target.get("claim_id")),
        "api_account_id": target.get("api_account_id"),
        "api_account_ids": [target.get("api_account_id")],
        "environment_scope": account_environment,
        "store_name": account_store_name,
        "target_order_number": _compact_text(target.get("order_number")),
        "waiting_claim_ids": claim_ids,
        "waiting_count": len(claim_ids),
        "customer_names": customer_names,
        "status_before": _claim_statuses(
            claim_ids,
            db_name=db_name,
        ),
    }


def _prepared_claim_ids(action: dict[str, Any]) -> list[str]:
    arguments = dict(action.get("arguments") or {})
    payload = dict(arguments.get("payload") or {})
    values = list(
        payload.get("claim_ids")
        or arguments.get("claim_ids")
        or []
    )
    single = _compact_text(
        payload.get("order")
        or payload.get("claim_id")
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


def _run_turn(
    prompt: str,
    *,
    client: Any,
    provider_code: str,
    model_name: str,
    db_name: str,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    result = run_agent_turn(
        prompt,
        planner_client=client,
        chat_client=client,
        db_name=db_name,
        history=history,
        model_record={
            "provider_code": provider_code,
            "default_model": model_name,
            "reasoning_effort": "auto",
        },
    )
    data = dict(result.data or {})
    answer = _compact_text(data.get("answer") or result.message)
    context = dict(data.get("conversation_context") or {})
    _append_history(
        history,
        user_message=prompt,
        answer=answer,
        conversation_context=context,
    )
    tool_results = [
        dict(row)
        for row in list(data.get("tool_results") or [])
        if isinstance(row, dict)
    ]
    tool_names = [
        _compact_text(row.get("tool"))
        for row in list(data.get("tool_calls") or [])
        if _compact_text(row.get("tool"))
    ]
    action = dict(data.get("action_proposal") or {})
    critical_read = any(
        tool_name in {"returns.query", "returns.lookup"}
        for tool_name in tool_names
    )
    return {
        "user": prompt,
        "success": bool(result.success),
        "mode": _compact_text(data.get("mode")),
        "tools": tool_names,
        "tool_arguments": [
            {
                "tool": _compact_text(row.get("tool")),
                "arguments": dict(row.get("arguments") or {}),
            }
            for row in list(data.get("tool_calls") or [])
            if _compact_text(row.get("tool"))
        ],
        "answer": answer,
        "visible_answer_quality": {
            "present": bool(answer),
            "no_mojibake": not _visible_answer_has_mojibake(answer),
        },
        "visible_answer_conflicts_with_tool_data": (
            critical_read
            and _should_use_deterministic_answer(
                answer,
                tool_results,
            )
        ),
        "conversation_context": context,
        "tool_claim_ids": [
            claim_id
            for row in tool_results
            for claim_id in _claim_ids_from_tool_result(
                _compact_text(row.get("tool")),
                dict(row.get("data") or {}),
            )
        ],
        "approval_required": bool(data.get("approval_required")),
        "action_type": _compact_text(
            action.get("operation")
            or action.get("action_type")
        ),
        "action_execute_enabled": action.get("execute_enabled"),
        "prepared_claim_ids": _prepared_claim_ids(action),
        "runtime_plan": _runtime_plan(client),
    }


def _provider_checks(
    turns: list[dict[str, Any]],
    *,
    seed: dict[str, Any],
) -> dict[str, bool]:
    target_claim_id = _compact_text(seed.get("target_claim_id"))
    expected_waiting = set(seed.get("waiting_claim_ids") or [])
    padded = list(turns) + [{}, {}, {}]
    list_turn, lookup_turn, prepare_turn = padded[:3]
    prepare_answer = _compact_text(prepare_turn.get("answer")).casefold()
    return {
        "all_turns_completed": (
            len(turns) == 3
            and all(bool(turn.get("success")) for turn in turns)
        ),
        "all_visible_answers_present": all(
            bool(_compact_text(turn.get("answer")))
            for turn in turns
        ),
        "all_visible_answers_no_mojibake": all(
            not _visible_answer_has_mojibake(turn.get("answer"))
            for turn in turns
        ),
        "read_answers_grounded_by_runtime_guard": all(
            not bool(turn.get("visible_answer_conflicts_with_tool_data"))
            for turn in turns[:2]
        ),
        "waiting_list_uses_filtered_query": (
            list(list_turn.get("tools") or []) == ["returns.query"]
            and (
                (
                    ((list_turn.get("tool_arguments") or [{}])[0] or {})
                    .get("arguments", {})
                    .get("filters", {})
                    .get("status")
                )
                == "WaitingInAction"
            )
        ),
        "waiting_list_matches_domain_scope": (
            bool(expected_waiting)
            and set(list_turn.get("tool_claim_ids") or [])
            == expected_waiting
        ),
        "waiting_list_context_is_structured": (
            (list_turn.get("conversation_context") or {}).get("kind")
            == "return_selection"
            and set(
                (list_turn.get("conversation_context") or {}).get(
                    "claim_ids"
                )
                or []
            )
            == expected_waiting
        ),
        "lookup_resolves_exact_target": (
            list(lookup_turn.get("tools") or []) == ["returns.lookup"]
            and list(lookup_turn.get("tool_claim_ids") or [])
            == [target_claim_id]
            and (
                (lookup_turn.get("conversation_context") or {}).get(
                    "claim_ids"
                )
                == [target_claim_id]
            )
        ),
        "approval_prepare_uses_exact_context_claim": (
            list(prepare_turn.get("tools") or [])
            == ["returns.approve.prepare"]
            and list(prepare_turn.get("prepared_claim_ids") or [])
            == [target_claim_id]
        ),
        "approval_prepare_waits_without_execute": (
            bool(prepare_turn.get("approval_required"))
            and prepare_turn.get("action_execute_enabled") is True
            and prepare_turn.get("action_type")
            == "orders.approve_return_claim"
        ),
        "approval_answer_is_safe_and_exact": (
            target_claim_id in _compact_text(prepare_turn.get("answer"))
            and "gercek api istegi veya db yazimi yapilmadi"
            in prepare_answer
            and "0 iade" not in prepare_answer
            and "onaylandi" not in prepare_answer
        ),
    }


def run_provider_returns_recheck(
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

    target_claim_id = _compact_text(seed.get("target_claim_id"))
    prompts = (
        "onay bekleyen iadelerin tamamini listele",
        f"claim kimligi {target_claim_id} olan iadenin detayini goster",
        "bunu onayla",
    )
    history: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    for prompt in prompts:
        turn = _run_turn(
            prompt,
            client=client,
            provider_code=provider_code,
            model_name=_compact_text(record.get("default_model")),
            db_name=db_name,
            history=history,
        )
        turns.append(turn)
        if not turn.get("success"):
            break

    plan = _runtime_plan(client)
    return {
        "provider_code": provider_code,
        "requested_model": _compact_text(record.get("default_model")),
        "actual_model": _compact_text(
            plan.get("actual_model") or getattr(client, "model_name", "")
        ),
        "reasoning_effort": "auto",
        "fallback_used": bool(plan.get("fallback_used")),
        "turns": turns,
        "checks": _provider_checks(turns, seed=seed),
    }


def run_source_db_returns_recheck(
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
                run_provider_returns_recheck(
                    provider_code,
                    seed=seed,
                    db_name=db_name,
                    timeout=timeout,
                    openrouter_model=openrouter_model,
                )
            )
        except Exception as exc:
            providers.append(
                {
                    "provider_code": provider_code,
                    "turns": [],
                    "checks": {"all_turns_completed": False},
                    "error": f"{type(exc).__name__}: {_compact_text(exc)}",
                }
            )
    status_after = _claim_statuses(
        list(seed.get("waiting_claim_ids") or []),
        db_name=db_name,
    )
    db_state_unchanged = status_after == dict(seed.get("status_before") or {})
    return {
        "name": (
            "live source DB Orders returns conversation recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": "orders_live_source_db_returns_conversation_recheck",
        "created_at": date.today().isoformat(),
        "db": "source-app-db",
        "seed": seed,
        "status_after": status_after,
        "safety": {
            "computer_use_used": False,
            "packaged_exe_used": False,
            "marketplace_write_performed": False,
            "db_write_performed": False,
            "execute_performed": False,
            "last_step_stops_at_prepare": True,
            "db_state_unchanged": db_state_unchanged,
        },
        "providers": providers,
        "passed": (
            db_state_unchanged
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
            "Run real source-DB Orders return list/lookup/approval-prepare "
            "conversations through configured cloud providers."
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

    payload = run_source_db_returns_recheck(
        provider_codes=tuple(args.providers or ("gemini", "openrouter")),
        timeout=max(10.0, float(args.timeout)),
        openrouter_model=args.openrouter_model,
    )
    target = write_live_evidence_file(Path(args.output), payload)
    print(f"artifact={target}")
    print(f"passed={bool(payload.get('passed'))}")
    print(
        "db_state_unchanged="
        f"{bool((payload.get('safety') or {}).get('db_state_unchanged'))}"
    )
    for provider in list(payload.get("providers") or []):
        print(
            "provider="
            f"{provider.get('provider_code')} "
            f"model={provider.get('actual_model') or '-'} "
            f"passed={all(dict(provider.get('checks') or {}).values())}"
        )
    return 0 if bool(payload.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
