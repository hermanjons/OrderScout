from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors.agent import (
    _answer_claims_unsupported_full_context_risk,
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
from AI.processors.tools import (
    orders_lookup,
    ready_to_ship_orders,
    recent_orders,
    resolve_active_api_account_scope_for_query,
)
from settings import DB_NAME


DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "source-db-live-recheck"
    / f"live-source-db-lookup-conversation-recheck-{date.today().isoformat()}.json"
)


def _order_rows_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("orders")
    return [dict(row) for row in list(rows or []) if isinstance(row, dict)]


def _order_numbers_from_tool_result(tool_name: str, data: dict[str, Any]) -> list[str]:
    if tool_name in {"orders.recent", "orders.lookup", "orders.query", "orders.ready_to_ship"}:
        return [
            _compact_text(row.get("order_number"))
            for row in _order_rows_from_data(data)
            if _compact_text(row.get("order_number"))
        ]
    if tool_name == "orders.full_context":
        return [
            _compact_text((dict(row.get("order") or {})).get("order_number"))
            for row in list(data.get("contexts") or [])
            if isinstance(row, dict)
            and _compact_text((dict(row.get("order") or {})).get("order_number"))
        ]
    return []


def _select_source_seed(*, db_name: str = DB_NAME) -> dict[str, Any]:
    scope_result = resolve_active_api_account_scope_for_query(
        db_name=db_name,
        query="siparislerim",
    )
    if not scope_result.success:
        raise RuntimeError(scope_result.message)
    scope = dict(scope_result.data or {})
    api_account_ids = [
        int(value)
        for value in list(scope.get("api_account_ids") or [])
        if str(value or "").isdigit() and int(value) > 0
    ]
    recent_result = recent_orders(
        db_name=db_name,
        period="all",
        limit=5,
        api_account_ids=api_account_ids or None,
    )
    if not recent_result.success:
        raise RuntimeError(recent_result.message)
    recent_rows = _order_rows_from_data(dict(recent_result.data or {}))
    customer_counts: dict[str, int] = {}
    for row in recent_rows:
        customer_key = _compact_text(row.get("customer")).casefold()
        if customer_key:
            customer_counts[customer_key] = customer_counts.get(customer_key, 0) + 1

    candidates = sorted(
        recent_rows,
        key=lambda row: customer_counts.get(
            _compact_text(row.get("customer")).casefold(),
            0,
        )
        != 1,
    )
    for row in candidates:
        order_number = _compact_text(row.get("order_number"))
        customer_name = _compact_text(row.get("customer"))
        if (
            not _valid_source_identifier(order_number)
            or len(customer_name) < 3
        ):
            continue
        lookup_result = orders_lookup(
            db_name=db_name,
            query=order_number,
            limit=5,
            api_account_ids=api_account_ids or None,
        )
        if not lookup_result.success:
            continue
        exact_rows = [
            item
            for item in _order_rows_from_data(dict(lookup_result.data or {}))
            if _compact_text(item.get("order_number")) == order_number
        ]
        if len(exact_rows) != 1:
            continue
        tracking_number = _compact_text(exact_rows[0].get("cargo_tracking_number"))
        if not _valid_source_identifier(tracking_number):
            continue
        ready_result = ready_to_ship_orders(
            db_name=db_name,
            period="all",
            limit=500,
            api_account_ids=api_account_ids or None,
        )
        if not ready_result.success:
            raise RuntimeError(ready_result.message)
        return {
            "order_number": order_number,
            "api_account_id": exact_rows[0].get("api_account_id"),
            "tracking_number": tracking_number,
            "customer_name": customer_name,
            "customer_is_unique_in_recent": customer_counts.get(customer_name.casefold()) == 1,
            "api_account_ids": api_account_ids,
            "environment_scope": _compact_text(
                scope.get("effective_environment")
                or scope.get("requested_environment")
            ),
            "recent_order_numbers": [
                _compact_text(item.get("order_number"))
                for item in recent_rows
                if _compact_text(item.get("order_number"))
            ],
            "all_ready_order_numbers": [
                _compact_text(item.get("order_number"))
                for item in _order_rows_from_data(dict(ready_result.data or {}))
                if _compact_text(item.get("order_number"))
            ],
        }
    raise RuntimeError(
        "Source DB has no unique recent customer with valid order and tracking identifiers."
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
    critical_synthesis_grounding = any(
        tool_name in {"orders.lookup", "orders.full_context"}
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
        "conversation_context": context,
        "tool_order_numbers": [
            order_number
            for row in tool_results
            for order_number in _order_numbers_from_tool_result(
                _compact_text(row.get("tool")),
                dict(row.get("data") or {}),
            )
        ],
        "approval_required": bool(data.get("approval_required")),
        "action_proposal_present": bool(data.get("action_proposal")),
        "unsupported_full_context_risk_claim": (
            _answer_claims_unsupported_full_context_risk(
                answer,
                tool_results,
            )
        ),
        "visible_answer_conflicts_with_tool_data": (
            critical_synthesis_grounding
            and _should_use_deterministic_answer(
                answer,
                tool_results,
            )
        ),
        "runtime_plan": _runtime_plan(client),
    }


def _provider_checks(
    turns: list[dict[str, Any]],
    *,
    seed: dict[str, Any],
) -> dict[str, bool]:
    order_number = _compact_text(seed.get("order_number"))
    recent_order_numbers = set(seed.get("recent_order_numbers") or [])
    expected_ready_numbers = set(
        seed.get("all_ready_order_numbers")
        or seed.get("last_8_days_ready_order_numbers")
        or []
    )
    padded = list(turns) + [{}, {}, {}, {}, {}, {}]
    (
        recent_turn,
        customer_turn,
        tracking_turn,
        order_turn,
        pronoun_turn,
        period_ready_turn,
    ) = padded[:6]
    period_ready_arguments = dict(
        (
            (period_ready_turn.get("tool_arguments") or [{}])[0]
            or {}
        ).get("arguments")
        or {}
    )

    def _exact_seed(turn: dict[str, Any]) -> bool:
        return list(dict.fromkeys(turn.get("tool_order_numbers") or [])) == [
            order_number
        ]

    return {
        "all_turns_completed": (
            len(turns) == 6
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
        "all_turns_read_only": all(
            not bool(turn.get("approval_required"))
            and not bool(turn.get("action_proposal_present"))
            for turn in turns
        ),
        "no_unsupported_full_context_risk_claims": all(
            not bool(turn.get("unsupported_full_context_risk_claim"))
            for turn in turns
        ),
        "all_visible_answers_grounded_by_runtime_guard": all(
            not bool(turn.get("visible_answer_conflicts_with_tool_data"))
            for turn in turns
        ),
        "recent_list_used": list(recent_turn.get("tools") or []) == [
            "orders.recent"
        ],
        "recent_list_matches_source_scope": (
            set(recent_turn.get("tool_order_numbers") or [])
            == recent_order_numbers
            and order_number in set(recent_turn.get("tool_order_numbers") or [])
        ),
        "customer_refinement_used_full_context": (
            list(customer_turn.get("tools") or []) == ["orders.full_context"]
            and _exact_seed(customer_turn)
        ),
        "tracking_lookup_exact_seed": (
            list(tracking_turn.get("tools") or []) == ["orders.lookup"]
            and _exact_seed(tracking_turn)
        ),
        "order_number_lookup_exact_seed": (
            list(order_turn.get("tools") or []) == ["orders.lookup"]
            and _exact_seed(order_turn)
        ),
        "pronoun_followup_keeps_exact_seed": (
            list(pronoun_turn.get("tools") or []) == ["orders.full_context"]
            and _exact_seed(pronoun_turn)
        ),
        "visible_exact_answers_name_target_order": all(
            order_number in _compact_text(turn.get("answer"))
            for turn in (customer_turn, tracking_turn, order_turn, pronoun_turn)
        ),
        "period_ready_filter_uses_exact_period": (
            list(period_ready_turn.get("tools") or [])
            == ["orders.ready_to_ship"]
            and period_ready_arguments.get("period") == "last_8_days"
        ),
        "period_ready_filter_matches_domain_scope": (
            bool(expected_ready_numbers)
            and set(period_ready_turn.get("tool_order_numbers") or [])
            == expected_ready_numbers
        ),
    }


def run_provider_lookup_recheck(
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

    customer_name = _compact_text(seed.get("customer_name"))
    tracking_number = _compact_text(seed.get("tracking_number"))
    order_number = _compact_text(seed.get("order_number"))
    prompts = (
        "son gelen 5 siparisi getir",
        (
            f"bu listedekilerden {customer_name} olanin kalemlerini "
            "ve iade durumunu getir"
        ),
        f"takip numarasi {tracking_number} olan siparisi bul",
        f"siparis numarasi {order_number} olan siparisi goster",
        "bunun kalemlerini ve iade durumunu tekrar ozetle",
        "son 8 gunde kargoya hazir siparislerin tamamini listele",
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


def run_source_db_lookup_recheck(
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
                run_provider_lookup_recheck(
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
    return {
        "name": (
            "live source DB Orders lookup conversation recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": "orders_live_source_db_lookup_conversation_recheck",
        "created_at": date.today().isoformat(),
        "db": "source-app-db",
        "seed": seed,
        "safety": {
            "computer_use_used": False,
            "packaged_exe_used": False,
            "marketplace_write_performed": False,
            "db_write_performed": False,
            "execute_performed": False,
            "read_only_conversation": True,
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
            "Run real source-DB Orders lookup/refinement conversations through "
            "configured cloud providers and persist redacted evidence."
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

    payload = run_source_db_lookup_recheck(
        provider_codes=tuple(args.providers or ("gemini", "openrouter")),
        timeout=max(10.0, float(args.timeout)),
        openrouter_model=args.openrouter_model,
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
    return 0 if bool(payload.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
