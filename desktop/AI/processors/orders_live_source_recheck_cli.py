from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any, Sequence
import unicodedata

from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors.agent import (
    _answer_claims_unsupported_profit,
    _grounded_order_analysis_answer,
    run_agent_turn,
)
from AI.processors.cloud_runtime import build_provider_chat_client
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.pipeline import get_provider_account, list_provider_accounts
from settings import DB_NAME


DEFAULT_PROMPTS = (
    "son 8 gunde siparislerim nasil sence kapsamli degerlendir",
    "bu siparis sayisi iyi mi sence, onceki esit donemle karsilastir",
    "kargoya hazir kac siparis var",
    "listele bakim",
    "tamam simdi bunlari etikete yazdir",
)
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"
DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "source-db-live-recheck"
    / f"live-source-db-provider-conversation-recheck-{date.today().isoformat()}.json"
)


def _compact_text(value: Any) -> str:
    return str(value or "").strip()


def _valid_source_identifier(value: Any) -> bool:
    text = _compact_text(value)
    return bool(text and text.casefold() not in {"none", "null", "unknown", "-"} and len(text) <= 256)


def _normalized_visible_answer(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _compact_text(value).casefold())
    return " ".join(
        "".join(char for char in text if not unicodedata.combining(char)).split()
    )


def _visible_answer_has_mojibake(value: Any) -> bool:
    return any(marker in _compact_text(value) for marker in ("Ã", "Ä", "Å", "Â", "�"))


def _load_provider_record(
    provider_code: str,
    *,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
) -> dict[str, Any]:
    clean_code = _compact_text(provider_code).casefold()
    result = list_provider_accounts()
    if not result.success:
        raise RuntimeError(result.message)
    summaries = list((result.data or {}).get("records") or [])
    summary = next(
        (
            row
            for row in summaries
            if _compact_text(row.get("provider_code")).casefold() == clean_code
            and bool(row.get("is_enabled"))
        ),
        None,
    )
    if not summary:
        raise RuntimeError(f"{clean_code} provider is not configured or enabled")
    loaded = get_provider_account(int(summary.get("id") or 0))
    if not loaded.success:
        raise RuntimeError(loaded.message)
    record = dict((loaded.data or {}).get("record") or {})
    if not record:
        raise RuntimeError(f"{clean_code} provider record could not be loaded")
    if clean_code == "openrouter" and _compact_text(openrouter_model):
        record["default_model"] = _compact_text(openrouter_model)
    record["reasoning_effort"] = "auto"
    return record


def _runtime_plan(client: Any) -> dict[str, Any]:
    return dict(getattr(client, "resource_plan", {}) or {})


def _tool_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(data.get("tool_results") or [])
        if isinstance(row, dict)
    ]


def _named_tool_data(
    tool_rows: list[dict[str, Any]],
    tool_name: str,
) -> dict[str, Any]:
    for row in tool_rows:
        if _compact_text(row.get("tool")) == tool_name:
            return dict(row.get("data") or {})
    return {}


def _find_order_numbers(value: Any) -> list[str]:
    if isinstance(value, dict):
        for key in ("order_numbers", "selected_order_numbers"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [
                    _compact_text(item)
                    for item in rows
                    if _compact_text(item)
                ]
        for child in value.values():
            found = _find_order_numbers(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_order_numbers(child)
            if found:
                return found
    return []


def _append_history(
    history: list[dict[str, Any]],
    *,
    user_message: str,
    answer: str,
    conversation_context: dict[str, Any],
) -> None:
    history.append({"role": "user", "content": user_message})
    assistant_row: dict[str, Any] = {"role": "assistant", "content": answer}
    if conversation_context:
        assistant_row["context"] = dict(conversation_context)
    history.append(assistant_row)


def _provider_checks(
    turns: list[dict[str, Any]],
    *,
    first_answer_grounded: bool,
) -> dict[str, bool]:
    padded = list(turns) + [{}, {}, {}, {}, {}]
    first, second, third, fourth, fifth = padded[:5]
    first_answer = _compact_text(first.get("answer"))
    answers = [_compact_text(turn.get("answer")) for turn in padded[:5]]
    normalized_answers = [
        _normalized_visible_answer(answer)
        for answer in answers
    ]
    second_answer = normalized_answers[1]
    third_answer = normalized_answers[2]
    fourth_answer = normalized_answers[3]
    fifth_answer = normalized_answers[4]
    profit = dict(first.get("profit_evidence") or {})
    ready_total = int(
        dict(third.get("conversation_context") or {}).get("total_count") or 0
    )
    listed = list(
        dict(fourth.get("conversation_context") or {}).get("order_numbers") or []
    )
    prepared = list(fifth.get("prepared_order_numbers") or [])
    second_tools = list(second.get("tools") or [])
    return {
        "all_turns_completed": len(turns) == len(DEFAULT_PROMPTS)
        and all(bool(turn.get("success")) for turn in turns),
        "all_visible_answers_present": all(bool(answer) for answer in answers),
        "all_visible_answers_no_mojibake": all(
            not _visible_answer_has_mojibake(answer)
            for answer in answers
        ),
        "analysis_multi_tool": len(list(first.get("tools") or [])) >= 6,
        "analysis_answer_substantive": len(first_answer) >= 240,
        "analysis_answer_grounded_by_runtime_guard": first_answer_grounded,
        "profit_unavailable_when_cost_coverage_missing": (
            profit.get("amount") is None
            and profit.get("estimated_profit_ready") is False
            and int(profit.get("incomplete_order_count") or 0) > 0
        ),
        "answer_does_not_claim_unsupported_profit": (
            not _answer_claims_unsupported_profit(first_answer)
        ),
        "answer_explains_profit_limitation": (
            "kar" in first_answer.casefold()
            and "maliyet" in first_answer.casefold()
        ),
        "equivalent_period_followup_used_tools": (
            second_tools.count("orders.count") >= 2
            and second_tools.count("orders.revenue_total") >= 2
        ),
        "equivalent_period_answer_is_explicit": (
            "onceki es donem" in second_answer
            and "bu ay" not in second_answer
        ),
        "ready_count_used": (
            list(third.get("tools") or []) == ["orders.ready_to_ship_count"]
            and ready_total > 0
        ),
        "ready_count_answer_matches_context": (
            ready_total > 0
            and f"kargoya hazir {ready_total} siparis" in third_answer
        ),
        "ready_list_used": (
            list(fourth.get("tools") or []) == ["orders.ready_to_ship"]
            and len(listed) == ready_total
        ),
        "ready_list_answer_matches_context": (
            ready_total > 0
            and f"{ready_total} siparis buldum" in fourth_answer
            and (
                ready_total <= 20
                or f"{ready_total - 20} kayit daha var" in fourth_answer
            )
        ),
        "label_prepare_used": (
            list(fifth.get("tools") or [])
            == ["labels.create_from_orders.prepare"]
        ),
        "label_prepare_has_exact_list_scope": (
            bool(prepared) and set(prepared) == set(listed)
        ),
        "label_prepare_waits_for_approval": (
            bool(fifth.get("approval_required"))
            and fifth.get("action_execute_enabled") is True
        ),
        "label_prepare_answer_matches_scope": (
            bool(prepared)
            and f"{len(prepared)} siparis" in fifth_answer
            and "0 siparis" not in fifth_answer
            and "gercek api istegi veya db yazimi yapilmadi" in fifth_answer
        ),
        "approval_answer_discloses_preview_remainder": (
            len(prepared) <= 20
            or f"{len(prepared) - 20} kayit daha onay kapsaminda"
            in _compact_text(fifth.get("answer"))
        ),
        "no_execute_performed": True,
    }


def run_provider_recheck(
    provider_code: str,
    *,
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

    history: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    first_answer_grounded = False
    for index, prompt in enumerate(DEFAULT_PROMPTS):
        result = run_agent_turn(
            prompt,
            planner_client=client,
            chat_client=client,
            db_name=db_name,
            history=history,
            model_record={
                "provider_code": provider_code,
                "default_model": _compact_text(record.get("default_model")),
                "reasoning_effort": "auto",
            },
        )
        data = dict(result.data or {})
        answer = _compact_text(data.get("answer") or result.message)
        context = dict(data.get("conversation_context") or {})
        tool_rows = _tool_rows(data)
        if index == 0:
            first_answer_grounded = _grounded_order_analysis_answer(
                answer,
                tool_rows,
            )
        _append_history(
            history,
            user_message=prompt,
            answer=answer,
            conversation_context=context,
        )
        profit = _named_tool_data(tool_rows, "finance.profit_amount")
        action = dict(data.get("action_proposal") or {})
        turns.append(
            {
                "user": prompt,
                "success": bool(result.success),
                "mode": _compact_text(data.get("mode")),
                "tools": [
                    _compact_text(row.get("tool"))
                    for row in list(data.get("tool_calls") or [])
                    if _compact_text(row.get("tool"))
                ],
                "answer": answer,
                "answer_length": len(answer),
                "visible_answer_quality": {
                    "present": bool(answer),
                    "no_mojibake": not _visible_answer_has_mojibake(answer),
                },
                "conversation_context": context,
                "profit_evidence": (
                    {
                        "amount": profit.get("amount"),
                        "revenue": profit.get("revenue"),
                        "estimated_profit_ready": profit.get(
                            "estimated_profit_ready"
                        ),
                        "complete_order_count": profit.get(
                            "complete_order_count"
                        ),
                        "incomplete_order_count": profit.get(
                            "incomplete_order_count"
                        ),
                        "missing_reason_count": len(
                            list(profit.get("missing_reasons") or [])
                        ),
                    }
                    if profit
                    else {}
                ),
                "approval_required": bool(data.get("approval_required")),
                "action_type": _compact_text(
                    action.get("operation") or action.get("action_type")
                ),
                "action_execute_enabled": action.get("execute_enabled"),
                "prepared_order_numbers": _find_order_numbers(action),
                "runtime_plan": _runtime_plan(client),
            }
        )
        if not result.success:
            break

    checks = _provider_checks(
        turns,
        first_answer_grounded=first_answer_grounded,
    )
    plan = _runtime_plan(client)
    return {
        "provider_code": provider_code,
        "requested_model": _compact_text(record.get("default_model")),
        "reasoning_effort": "auto",
        "turns": turns,
        "checks": checks,
        "actual_model": _compact_text(
            plan.get("actual_model") or getattr(client, "model_name", "")
        ),
        "fallback_used": bool(plan.get("fallback_used")),
    }


def run_source_db_recheck(
    *,
    provider_codes: Sequence[str] = ("gemini", "openrouter"),
    db_name: str = DB_NAME,
    timeout: float = 180.0,
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL,
) -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for provider_code in provider_codes:
        try:
            providers.append(
                run_provider_recheck(
                    provider_code,
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
            "live source DB provider conversation recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": "orders_live_source_db_provider_conversation_recheck",
        "created_at": date.today().isoformat(),
        "db": "source-app-db",
        "safety": {
            "computer_use_used": False,
            "packaged_exe_used": False,
            "marketplace_write_performed": False,
            "db_write_performed": False,
            "execute_performed": False,
            "last_step_stops_at_prepare": True,
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
            "Run the safe Orders source-DB conversation against real configured "
            "cloud providers and persist redacted evidence."
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

    payload = run_source_db_recheck(
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
