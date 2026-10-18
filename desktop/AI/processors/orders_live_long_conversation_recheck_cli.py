from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any, Callable, Sequence

from AI.constants.paths import AI_PACKAGE_ROOT
from AI.processors.agent import (
    _answer_echoes_user_message,
    _answer_claims_unsupported_profit,
    _direct_answer_semantically_relevant,
    _degenerate_repetition_answer,
    _deterministic_tool_answer,
    _should_use_deterministic_answer,
    run_agent_turn,
)
from AI.processors.cloud_runtime import (
    build_provider_chat_client,
    provider_invocation_provenance,
)
from AI.processors.live_evidence import write_live_evidence_file
from AI.processors.local_runtime import (
    build_local_planner_client,
    shutdown_managed_llama_servers,
)
from AI.processors.model_routing import stable_state_hash
from AI.processors.orders_live_lookup_recheck_cli import (
    _order_numbers_from_tool_result,
    _select_source_seed as _select_order_seed,
)
from AI.processors.orders_live_returns_recheck_cli import (
    _claim_ids_from_tool_result,
    _claim_statuses,
    _prepared_claim_ids,
    _select_source_seed as _select_return_seed,
)
from AI.processors.orders_live_source_recheck_cli import (
    _append_history,
    _compact_text,
    _find_order_numbers,
    _load_provider_record,
    _normalized_visible_answer,
    _runtime_plan,
    _visible_answer_has_mojibake,
)
from AI.processors.pipeline import list_installed_models
from settings import DB_NAME


DEFAULT_OUTPUT_PATH = (
    AI_PACKAGE_ROOT
    / "docs"
    / "live_llm_transcripts"
    / "long-adaptive-conversations"
    / f"live-orders-long-adaptive-conversation-{date.today().isoformat()}.json"
)
MIN_LONG_TURNS = 20
STRONG_LOCAL_REPO_PRIORITY = (
    "jc-builds/gemma-4-e4b-it-gguf",
    "igorls/gemma-4-12b-it-heretic-gguf",
    "ggml-org/gpt-oss-20b-gguf",
)
WEAK_LOCAL_REPO_PRIORITY = (
    "hugging-quants/llama-3.2-1b-instruct-q8_0-gguf",
    "andycurrent/gemma-3-1b-it-glm-4.7-flash-heretic-uncensored-thinking_gguf",
)


TURN_PHASES = (
    "greeting",
    "emotional_chat",
    "identity",
    "ecommerce_opinion",
    "orders_capabilities",
    "recent_orders",
    "customer_refinement",
    "interlude_1",
    "interlude_2",
    "interlude_3",
    "interlude_4",
    "interlude_5",
    "interlude_6",
    "interlude_7",
    "interlude_8",
    "long_range_context_return",
    "tracking_lookup",
    "ready_count",
    "ready_list",
    "label_prepare",
    "label_cancel",
    "post_prepare_chat",
    "orders_analysis",
    "equal_period_followup",
    "profit_limitation",
    "waiting_returns",
    "return_lookup",
    "return_prepare",
    "return_cancel",
    "closing_chat",
)

FREE_CHAT_PHASES = {
    "greeting",
    "emotional_chat",
    "identity",
    "ecommerce_opinion",
    "orders_capabilities",
    "interlude_1",
    "interlude_2",
    "interlude_3",
    "interlude_4",
    "interlude_5",
    "interlude_6",
    "interlude_7",
    "interlude_8",
    "label_cancel",
    "post_prepare_chat",
    "return_cancel",
    "closing_chat",
}

RESPONDER_CHAT_PHASES = {
    "greeting",
    "emotional_chat",
    "ecommerce_opinion",
    "interlude_2",
    "interlude_3",
    "interlude_4",
    "interlude_5",
    "interlude_6",
    "interlude_7",
    "post_prepare_chat",
    "closing_chat",
}


def _tool_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(data.get("tool_results") or [])
        if isinstance(row, dict)
    ]


def _tool_names(data: dict[str, Any]) -> list[str]:
    return [
        _compact_text(row.get("tool"))
        for row in list(data.get("tool_calls") or [])
        if isinstance(row, dict) and _compact_text(row.get("tool"))
    ]


def _selected_order_numbers(context: dict[str, Any]) -> list[str]:
    return [
        _compact_text(value)
        for value in list(context.get("order_numbers") or [])
        if _compact_text(value)
    ]


def _selected_claim_ids(context: dict[str, Any]) -> list[str]:
    return [
        _compact_text(value)
        for value in list(context.get("claim_ids") or [])
        if _compact_text(value)
    ]


def _action_type(action: dict[str, Any]) -> str:
    return _compact_text(action.get("operation") or action.get("action_type"))


def _run_turn(
    prompt: str,
    *,
    phase: str,
    selection_reason: str,
    client: Callable[[str], str],
    provider_code: str,
    model_name: str,
    db_name: str,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    history_message_count_before_turn = len(history)
    history_state_hash_before_turn = stable_state_hash({"history": history})
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
    tool_rows = _tool_rows(data)
    tools = _tool_names(data)
    action = dict(data.get("action_proposal") or {})
    deterministic_answer = (
        _deterministic_tool_answer(prompt, tool_rows)
        if tool_rows
        else ""
    )
    _append_history(
        history,
        user_message=prompt,
        answer=answer,
        conversation_context=context,
    )
    history_state_hash_after_turn = stable_state_hash({"history": history})
    critical_grounding = bool(tools) and any(
        name.startswith(("orders.", "returns.", "finance."))
        for name in tools
    )
    normalized_answer = _normalized_visible_answer(answer)
    normalized_deterministic_answer = _normalized_visible_answer(
        deterministic_answer
    )
    return {
        "turn": len(history) // 2,
        "phase": phase,
        "user": prompt,
        "next_prompt_selection_reason": selection_reason,
        "success": bool(result.success),
        "mode": _compact_text(data.get("mode")),
        "answer_origin": _compact_text(data.get("answer_origin")),
        "decision_path": _compact_text(data.get("decision_path")),
        "model_invoked": data.get("model_invoked"),
        "tools": tools,
        "tool_arguments": [
            {
                "tool": _compact_text(row.get("tool")),
                "arguments": dict(row.get("arguments") or {}),
            }
            for row in list(data.get("tool_calls") or [])
            if isinstance(row, dict) and _compact_text(row.get("tool"))
        ],
        # A live acceptance artifact must let the closing Codex agent compare
        # the visible answer with the authoritative operation envelope.  Tool
        # names and arguments alone cannot prove grounding, scope or read-back.
        # The evidence writer applies the shared secret/PII redactor before the
        # public artifact is persisted.
        "tool_results": tool_rows,
        "answer": answer,
        "answer_length": len(answer),
        "visible_answer_quality": {
            "present": bool(answer),
            "no_mojibake": not _visible_answer_has_mojibake(answer),
            "not_generic_fallback": _normalized_visible_answer(answer)
            not in {
                "buradayim ne yapalim",
                "tabii nasil yardimci olabilirim",
            },
            "not_user_echo": not _answer_echoes_user_message(prompt, answer),
            "not_degenerate_repetition": not _degenerate_repetition_answer(
                answer
            ),
            "semantically_relevant": _direct_answer_semantically_relevant(
                prompt,
                answer,
            ),
        },
        "conversation_context": context,
        "action_proposal": action,
        "selected_order_numbers": _selected_order_numbers(context),
        "selected_claim_ids": _selected_claim_ids(context),
        "tool_order_numbers": [
            order_number
            for row in tool_rows
            for order_number in _order_numbers_from_tool_result(
                _compact_text(row.get("tool")),
                dict(row.get("data") or {}),
            )
        ],
        "tool_claim_ids": [
            claim_id
            for row in tool_rows
            for claim_id in _claim_ids_from_tool_result(
                _compact_text(row.get("tool")),
                dict(row.get("data") or {}),
            )
        ],
        "approval_required": bool(data.get("approval_required")),
        "action_type": _action_type(action),
        "action_execute_enabled": action.get("execute_enabled"),
        "prepared_order_numbers": _find_order_numbers(action),
        "prepared_claim_ids": _prepared_claim_ids(action) if action else [],
        "visible_answer_conflicts_with_tool_data": (
            critical_grounding
            and _should_use_deterministic_answer(answer, tool_rows)
            and normalized_deterministic_answer not in normalized_answer
        ),
        "unsupported_profit_claim": _answer_claims_unsupported_profit(answer),
        "history_message_count_before_turn": history_message_count_before_turn,
        "history_message_count_after_turn": len(history),
        "history_state_hash_before_turn": history_state_hash_before_turn,
        "history_state_hash_after_turn": history_state_hash_after_turn,
        "runtime_plan": _runtime_plan(client),
    }


def _turn_by_phase(turns: Sequence[dict[str, Any]], phase: str) -> dict[str, Any]:
    return next(
        (dict(turn) for turn in turns if _compact_text(turn.get("phase")) == phase),
        {},
    )


def _adaptive_prompt(
    phase: str,
    *,
    turns: Sequence[dict[str, Any]],
    order_seed: dict[str, Any],
    return_seed: dict[str, Any] | None,
) -> tuple[str, str]:
    previous = dict(turns[-1]) if turns else {}
    previous_answer = _normalized_visible_answer(previous.get("answer"))
    customer = _compact_text(order_seed.get("customer_name"))
    tracking = _compact_text(order_seed.get("tracking_number"))
    target_claim = _compact_text((return_seed or {}).get("target_claim_id"))

    if phase == "greeting":
        return "naber dayi, nasil gidiyor", "Start with natural chat and no tool."
    if phase == "emotional_chat":
        if "ne yapalim" in previous_answer or "nasil yardimci" in previous_answer:
            return (
                "hemen ise gecmeyelim ya, biraz keyfim yok iki laf edelim",
                "Previous answer tried to close chat; test conversational recovery.",
            )
        return (
            "benim biraz keyfim yok acikcasi, iki laf edelim",
            "Continue naturally from the greeting.",
        )
    if phase == "identity":
        return "bu arada adin neydi senin", "Ask identity inside the same chat."
    if phase == "ecommerce_opinion":
        return (
            "sence e ticaret iyi bir is mi, ezbere degil kendi yorumunu soyle",
            "Test substantive free-form opinion without domain tools.",
        )
    if phase == "orders_capabilities":
        return (
            "peki siparislerim tarafinda beraber neler yapabiliriz",
            "Move naturally from opinion to Orders capability help.",
        )
    if phase == "recent_orders":
        missing = [
            token
            for token in ("etiket", "iade", "kargo")
            if token not in previous_answer
        ]
        if missing:
            return (
                "anladim, simdi son gelen 5 siparisi getir; sonra eksik anlattigin kisimlara doneriz",
                f"Capability answer omitted {', '.join(missing)}; continue with a real read and retain the gap.",
            )
        return (
            "tamam o zaman son gelen 5 siparisi getir",
            "Capability answer was broad enough; start real Orders work.",
        )
    if phase == "customer_refinement":
        recent = _turn_by_phase(turns, "recent_orders")
        if recent.get("tool_order_numbers"):
            if not bool(order_seed.get("customer_is_unique_in_recent")):
                return (
                    f"bu listedekilerden siparis numarasi {order_seed.get('order_number')} olanin kalemlerini ve iade durumunu getir",
                    "The source customer is duplicated; narrow with the exact authoritative order number instead.",
                )
            return (
                f"bu listedekilerden {customer} olanin kalemlerini ve iade durumunu getir",
                "Use the actual recent result and its unique source customer to narrow the set.",
            )
        return (
            "liste gelmedi galiba, son gelen siparislerden birini detayli ac",
            "Recent result was empty; adapt by asking for a recoverable detail read.",
        )

    interludes = {
        "interlude_1": ("bu arada adin neydi, unuttum yine", "Begin an eight-message non-record interlude."),
        "interlude_2": ("e ticaret insani cok yorar mi sence", "Keep free chat without replacing selected record context."),
        "interlude_3": ("bugun biraz moralim bozuk, kisa ama samimi konus", "Test tone adaptation."),
        "interlude_4": ("musteri memnuniyetinde sence en kritik sey ne", "Ask a general ecommerce opinion, not private data."),
        "interlude_5": ("iyi bir e ticaret yoneticisinin en guclu tarafi ne olmali", "Continue topic drift without a tool."),
        "interlude_6": ("bazen sayilara fazla takiliyorum, bu normal mi sence", "Test reflective conversation."),
        "interlude_7": ("cevaplari hep tek cumleye sikistirma, gerektigi kadar anlat", "Test response-length adaptation."),
        "interlude_8": ("tamam biraz toparlandim, az onceki ise donebiliriz", "Signal an upcoming return to old structured context."),
    }
    if phase in interludes:
        return interludes[phase]
    if phase == "long_range_context_return":
        if not bool(order_seed.get("customer_is_unique_in_recent")):
            return (
                f"sekiz mesaj once siparis numarasi {order_seed.get('order_number')} olan kaydi ayirmistik ya, onun kalemlerini tekrar goster",
                "The source customer is duplicated; prove long-range recall with the exact authoritative order number.",
            )
        return (
            f"sekiz mesaj once {customer} icin ayirdigimiz siparis vardi ya, onun kalemlerini tekrar goster",
            "Return to the exact selected order after eight unrelated user messages.",
        )
    if phase == "tracking_lookup":
        return (
            f"bir de takip numarasi {tracking} olan siparisi bul, ayni kayit mi kontrol et",
            "Cross-check the selected order using its real tracking identifier.",
        )
    if phase == "ready_count":
        return (
            "simdi kargoya hazir toplam kac siparis var",
            "Switch to a new real record scope.",
        )
    if phase == "ready_list":
        ready_count = int(
            dict(
                _turn_by_phase(turns, "ready_count").get("conversation_context")
                or {}
            ).get("total_count")
            or 0
        )
        return (
            f"o {ready_count} siparisin hepsini listele" if ready_count else "kargoya hazirlarin hepsini listele",
            "Use the actual count returned by the previous turn.",
        )
    if phase == "label_prepare":
        listed = _turn_by_phase(turns, "ready_list").get("tool_order_numbers") or []
        if listed:
            return (
                f"tamam bu {len(set(listed))} siparisin tamamini etikete yazdirmaya hazirla",
                "Carry the exact actual ready-list set into prepare.",
            )
        return (
            "liste bos geldi, once kargoya hazir siparisleri bul sonra etikete hazirla",
            "Ready list was empty; ask the agent to recover instead of preparing zero records.",
        )
    if phase == "label_cancel":
        prepared = _turn_by_phase(turns, "label_prepare").get("prepared_order_numbers") or []
        return (
            "yok simdilik vazgec, hicbir dosya ya da cikti uretme",
            (
                f"Cancel a valid {len(prepared)}-record prepare without execute."
                if prepared
                else "Prepare failed; explicitly prevent any write."
            ),
        )
    if phase == "post_prepare_chat":
        return (
            "tamam, sorun degil. sence bugun neye oncelik vermeliyim",
            "Verify conversation remains natural after a cancelled risky action.",
        )
    if phase == "orders_analysis":
        return (
            "son 8 gunde siparislerim nasil, onceki esit donem ve operasyon riskleriyle kapsamli anlat",
            "Request a multi-signal, multi-tool analysis.",
        )
    if phase == "equal_period_followup":
        analysis = _turn_by_phase(turns, "orders_analysis")
        if analysis.get("unsupported_profit_claim"):
            return (
                "kar dedin ama maliyet verisi tam mi, bunu nereden cikardin",
                "Challenge an unsupported profit claim found in the visible answer.",
            )
        return (
            "siparis sayisi iyi mi yani, sadece onceki esit sureli donemle karsilastir",
            "Ask a natural follow-up based on the completed analysis.",
        )
    if phase == "profit_limitation":
        return (
            "peki bu verilerle gercekten karliyiz diyebilir misin, eksik veriyi acikca soyle",
            "Test that the agent does not turn revenue into profit.",
        )
    if phase == "waiting_returns":
        return_environment = _compact_text(
            (return_seed or {}).get("environment_scope")
        ).casefold()
        environment_prefix = (
            "Stage ortamindaki "
            if return_environment == "stage"
            else "Production ortamindaki "
            if return_environment == "production"
            else ""
        )
        return (
            f"{environment_prefix}onay bekleyen iadelerin tamamini getir",
            "Move to the real returns surface with the independent seed's exact environment boundary.",
        )
    if phase == "return_lookup":
        if target_claim:
            return (
                f"claim id {target_claim} olan iadeyi tek basina goster",
                "Use the actual WaitingInAction claim selected independently from the source DB.",
            )
        return (
            "listedeki ilk iadeyi tek basina goster",
            "No executable source claim was available; narrow the visible list safely.",
        )
    if phase == "return_prepare":
        return (
            "tamam bunu onaylamaya hazirla ama benden onay almadan islem yapma",
            "Prepare the exact prior claim and require approval.",
        )
    if phase == "return_cancel":
        return (
            "bunu da simdilik iptal et, pazaryerine istek gonderme",
            "Cancel return approval before any marketplace mutation.",
        )
    if phase == "closing_chat":
        return (
            "eyvallah, son olarak bugunku sohbetimizi bir cumleyle nasil buldun",
            "End with natural chat after multiple data and prepare phases.",
        )
    raise ValueError(f"Unknown long-conversation phase: {phase}")


def _provider_checks(
    turns: Sequence[dict[str, Any]],
    *,
    order_seed: dict[str, Any],
    return_seed: dict[str, Any] | None,
    return_status_after: dict[str, str],
) -> dict[str, bool]:
    by_phase = {
        _compact_text(turn.get("phase")): dict(turn)
        for turn in turns
        if _compact_text(turn.get("phase"))
    }
    target_order = _compact_text(order_seed.get("order_number"))
    target_customer = _compact_text(order_seed.get("customer_name"))
    expected_ready = set(
        order_seed.get("all_ready_order_numbers")
        or order_seed.get("last_8_days_ready_order_numbers")
        or []
    )
    target_claim = _compact_text((return_seed or {}).get("target_claim_id"))
    waiting_claims = set((return_seed or {}).get("waiting_claim_ids") or [])
    ready_listed = set(by_phase.get("ready_list", {}).get("tool_order_numbers") or [])
    label_prepared = set(by_phase.get("label_prepare", {}).get("prepared_order_numbers") or [])
    ready_list_answer = _compact_text(
        by_phase.get("ready_list", {}).get("answer")
    )
    label_prepare_answer = _compact_text(
        by_phase.get("label_prepare", {}).get("answer")
    )
    analysis_tools = list(by_phase.get("orders_analysis", {}).get("tools") or [])
    comparison_tools = list(by_phase.get("equal_period_followup", {}).get("tools") or [])
    return_prepared = set(by_phase.get("return_prepare", {}).get("prepared_claim_ids") or [])
    status_before = dict((return_seed or {}).get("status_before") or {})
    style_answer = _normalized_visible_answer(
        by_phase.get("interlude_7", {}).get("answer")
    )
    emotional_answer = _normalized_visible_answer(
        by_phase.get("emotional_chat", {}).get("answer")
    )
    context_return_answer = _compact_text(
        by_phase.get("interlude_8", {}).get("answer")
    ).casefold()
    priority_answer = _normalized_visible_answer(
        by_phase.get("post_prepare_chat", {}).get("answer")
    )
    closing_answer = _normalized_visible_answer(
        by_phase.get("closing_chat", {}).get("answer")
    )
    responder_turns = [
        turn
        for turn in turns
        if turn.get("phase") in RESPONDER_CHAT_PHASES
    ]
    direct_responder_turns = [
        turn
        for turn in responder_turns
        if _compact_text(turn.get("answer_origin")).startswith("direct_llm")
    ]
    responder_answers = [
        _normalized_visible_answer(turn.get("answer"))
        for turn in responder_turns
        if _normalized_visible_answer(turn.get("answer"))
    ]

    return {
        "minimum_turn_count_reached": len(turns) >= MIN_LONG_TURNS,
        "all_planned_turns_completed": len(turns) == len(TURN_PHASES),
        "all_turns_successful": all(bool(turn.get("success")) for turn in turns),
        "all_visible_answers_present": all(
            bool(_compact_text(turn.get("answer"))) for turn in turns
        ),
        "all_visible_answers_no_mojibake": all(
            not _visible_answer_has_mojibake(turn.get("answer"))
            for turn in turns
        ),
        "all_visible_answers_avoid_user_echo": all(
            bool(
                dict(turn.get("visible_answer_quality") or {}).get(
                    "not_user_echo"
                )
            )
            for turn in turns
        ),
        "all_visible_answers_avoid_degenerate_repetition": all(
            bool(
                dict(turn.get("visible_answer_quality") or {}).get(
                    "not_degenerate_repetition"
                )
            )
            for turn in turns
        ),
        "all_visible_answers_are_semantically_relevant": all(
            bool(
                dict(turn.get("visible_answer_quality") or {}).get(
                    "semantically_relevant"
                )
            )
            for turn in turns
        ),
        "responder_answers_do_not_repeat_across_topics": (
            len(responder_answers) == len(set(responder_answers))
        ),
        "all_prompt_choices_explain_adaptation": all(
            bool(_compact_text(turn.get("next_prompt_selection_reason")))
            for turn in turns
        ),
        "conversational_answers_use_llm_responder": (
            bool(responder_turns)
            and len(direct_responder_turns) * 100
            >= len(responder_turns) * 60
        ),
        "free_chat_turns_do_not_use_tools": all(
            not list(turn.get("tools") or [])
            for turn in turns
            if turn.get("phase") in FREE_CHAT_PHASES
        ),
        "free_chat_avoids_fixed_generic_fallback": all(
            bool(
                dict(turn.get("visible_answer_quality") or {}).get(
                    "not_generic_fallback"
                )
            )
            for turn in turns
            if turn.get("phase") in FREE_CHAT_PHASES
        ),
        "free_chat_does_not_invent_empty_data_state": all(
            not any(
                token
                in _normalized_visible_answer(turn.get("answer"))
                for token in (
                    "kayit bulunmadigi",
                    "kayıt bulunmadığı",
                    "kayit bulunmuyor",
                    "kayıt bulunmuyor",
                    "siparis numaranizi paylas",
                    "sipariş numaranızı paylaş",
                    "siparis numarani paylas",
                    "sipariş numaranı paylaş",
                )
            )
            for turn in turns
            if turn.get("phase") in FREE_CHAT_PHASES
        ),
        "emotional_chat_acknowledges_user_tone": any(
            token in emotional_answer
            for token in (
                "anliyorum",
                "anlıyorum",
                "uzuldum",
                "üzüldüm",
                "dinliyorum",
                "buradayim",
                "buradayım",
                "zor",
                "moral",
                "keyif",
                "canin",
                "canini",
            )
        ),
        "style_preference_is_not_reversed": (
            "tek cumleyle" not in style_answer
            and "tek cumle olarak" not in style_answer
            and any(
                token in style_answer
                for token in (
                    "gerektigi kadar",
                    "gerektiği kadar",
                    "ayrintili",
                    "ayrıntılı",
                    "detayli",
                    "detaylı",
                    "sikistirmadan",
                    "sıkıştırmadan",
                )
            )
        ),
        "return_to_work_recalls_prior_scope": any(
            value and value.casefold() in context_return_answer
            for value in (target_order, target_customer)
        ),
        "all_grounded_turns_pass_runtime_guard": all(
            not bool(turn.get("visible_answer_conflicts_with_tool_data"))
            for turn in turns
        ),
        "recent_orders_read_used": bool(
            by_phase.get("recent_orders", {}).get("tool_order_numbers")
        ),
        "recent_orders_matches_independent_domain_scope": (
            list(by_phase.get("recent_orders", {}).get("tools") or [])
            == ["orders.recent"]
            and set(
                by_phase.get("recent_orders", {}).get("tool_order_numbers")
                or []
            )
            == set(order_seed.get("recent_order_numbers") or [])
        ),
        "customer_refinement_keeps_exact_order": set(
            by_phase.get("customer_refinement", {}).get("tool_order_numbers")
            or []
        )
        == {target_order},
        "long_range_context_survives_eight_interludes": set(
            by_phase.get("long_range_context_return", {}).get(
                "tool_order_numbers"
            )
            or []
        )
        == {target_order},
        "tracking_lookup_returns_same_order": set(
            by_phase.get("tracking_lookup", {}).get("tool_order_numbers") or []
        )
        == {target_order},
        "ready_count_is_positive": int(
            dict(
                by_phase.get("ready_count", {}).get("conversation_context") or {}
            ).get("total_count")
            or 0
        )
        > 0,
        "ready_list_matches_independent_domain_scope": bool(expected_ready)
        and ready_listed == expected_ready,
        "ready_list_visible_answer_is_complete": bool(ready_listed)
        and all(order_number in ready_list_answer for order_number in ready_listed),
        "label_prepare_keeps_exact_ready_scope": bool(ready_listed)
        and label_prepared == ready_listed,
        "label_prepare_visible_answer_is_complete": bool(label_prepared)
        and all(
            order_number in label_prepare_answer
            for order_number in label_prepared
        ),
        "label_prepare_waits_for_approval": bool(
            by_phase.get("label_prepare", {}).get("approval_required")
        )
        and by_phase.get("label_prepare", {}).get("action_execute_enabled") is True,
        "label_cancel_does_not_execute": not bool(
            by_phase.get("label_cancel", {}).get("approval_required")
        ),
        "post_prepare_chat_remains_tool_free": not bool(
            by_phase.get("post_prepare_chat", {}).get("tools")
        ),
        "post_prepare_priority_uses_recent_order_context": (
            any(
                token in priority_answer
                for token in (
                    "siparis",
                    "sipariş",
                    "kargo",
                    "etiket",
                    "sevkiyat",
                    "paket",
                )
            )
            and (
                str(len(ready_listed)) in priority_answer
                or "hazir" in priority_answer
                or "hazır" in priority_answer
                or "sectigimiz" in priority_answer
                or "seçtiğimiz" in priority_answer
            )
        ),
        "orders_analysis_is_multi_tool": len(analysis_tools) >= 6,
        "analysis_does_not_claim_unsupported_profit": not bool(
            by_phase.get("orders_analysis", {}).get("unsupported_profit_claim")
        ),
        "equal_period_followup_uses_two_periods": (
            comparison_tools.count("orders.count") >= 2
            and comparison_tools.count("orders.revenue_total") >= 2
        ),
        "profit_answer_does_not_claim_unsupported_profit": not bool(
            by_phase.get("profit_limitation", {}).get("unsupported_profit_claim")
        ),
        "waiting_returns_match_independent_domain_scope": (
            not waiting_claims
            or set(
                by_phase.get("waiting_returns", {}).get("tool_claim_ids") or []
            )
            == waiting_claims
        ),
        "return_lookup_keeps_exact_claim": (
            not target_claim
            or set(
                by_phase.get("return_lookup", {}).get("tool_claim_ids") or []
            )
            == {target_claim}
        ),
        "return_prepare_keeps_exact_claim": (
            not target_claim or return_prepared == {target_claim}
        ),
        "return_prepare_waits_for_approval": (
            not target_claim
            or (
                bool(by_phase.get("return_prepare", {}).get("approval_required"))
                and by_phase.get("return_prepare", {}).get(
                    "action_execute_enabled"
                )
                is True
            )
        ),
        "return_status_unchanged_without_execute": (
            status_before == return_status_after
        ),
        "closing_chat_is_tool_free": not bool(
            by_phase.get("closing_chat", {}).get("tools")
        ),
        "closing_chat_summarizes_conversation_context": sum(
            1
            for token in (
                "siparis",
                "sipariş",
                "kargo",
                "etiket",
                "iade",
                "kar",
                "kâr",
                "ciro",
            )
            if token in closing_answer
        )
        >= 2,
    }


def _installed_local_records() -> list[dict[str, Any]]:
    result = list_installed_models()
    if not result.success:
        raise RuntimeError(result.message)
    return [
        dict(row)
        for row in list((result.data or {}).get("records") or [])
        if isinstance(row, dict)
        and bool(row.get("exists_on_disk"))
        and _compact_text(row.get("local_path"))
    ]


def _select_local_record(tier: str) -> dict[str, Any]:
    records = _installed_local_records()
    priority = (
        STRONG_LOCAL_REPO_PRIORITY
        if tier == "local-best"
        else WEAK_LOCAL_REPO_PRIORITY
    )
    for repo_id in priority:
        found = next(
            (
                record
                for record in records
                if _compact_text(record.get("repo_id")).casefold() == repo_id
            ),
            None,
        )
        if found:
            selected = dict(found)
            runtime = dict(selected.get("runtime_config") or {})
            runtime.update(
                {
                    "performance_preset": "balanced",
                    "num_ctx": 4096,
                    "max_tokens": 384 if tier == "local-best" else 256,
                    "keep_alive": "15m",
                }
            )
            selected["runtime_config"] = runtime
            return selected
    raise RuntimeError(f"No installed model matches {tier} priority.")


def _build_runner(
    provider_code: str,
    *,
    timeout: float,
    gemini_model: str,
    openrouter_model: str,
) -> tuple[Callable[[str], str], dict[str, Any], str]:
    if provider_code in {"gemini", "openrouter"}:
        record = _load_provider_record(
            provider_code,
            openrouter_model=(
                openrouter_model if provider_code == "openrouter" else ""
            ),
        )
        if provider_code == "gemini" and _compact_text(gemini_model):
            record["default_model"] = _compact_text(gemini_model)
        client = build_provider_chat_client(record, timeout=timeout)
        if client is None:
            raise RuntimeError(f"{provider_code} client could not be built")
        return client, record, _compact_text(record.get("default_model"))

    record = _select_local_record(provider_code)
    client = build_local_planner_client(record)
    if client is None:
        raise RuntimeError(f"{provider_code} local client could not be built")
    return (
        client,
        record,
        _compact_text(record.get("repo_id") or record.get("filename")),
    )


def run_long_provider_conversation(
    provider_code: str,
    *,
    order_seed: dict[str, Any],
    return_seed: dict[str, Any] | None,
    db_name: str = DB_NAME,
    timeout: float = 180.0,
    gemini_model: str = "",
    openrouter_model: str = "",
) -> dict[str, Any]:
    client, record, requested_model = _build_runner(
        provider_code,
        timeout=timeout,
        gemini_model=gemini_model,
        openrouter_model=openrouter_model,
    )
    history: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    try:
        for phase in TURN_PHASES:
            prompt, selection_reason = _adaptive_prompt(
                phase,
                turns=turns,
                order_seed=order_seed,
                return_seed=return_seed,
            )
            turn = _run_turn(
                prompt,
                phase=phase,
                selection_reason=selection_reason,
                client=client,
                provider_code=provider_code,
                model_name=requested_model,
                db_name=db_name,
                history=history,
            )
            turns.append(turn)
            if not turn.get("success"):
                break
    finally:
        if provider_code.startswith("local-"):
            shutdown_managed_llama_servers()

    return_status_after = (
        _claim_statuses(
            list((return_seed or {}).get("waiting_claim_ids") or []),
            db_name=db_name,
        )
        if return_seed
        else {}
    )
    checks = _provider_checks(
        turns,
        order_seed=order_seed,
        return_seed=return_seed,
        return_status_after=return_status_after,
    )
    plan = _runtime_plan(client)
    provenance = provider_invocation_provenance(plan)
    return {
        "provider_code": provider_code,
        "requested_model": requested_model,
        "actual_model": _compact_text(
            provenance.get("last_successful_actual_model")
            or getattr(client, "model_name", "")
            or requested_model
        ),
        "fallback_used": bool(provenance.get("any_model_fallback_used")),
        "reasoning_effort": _compact_text(record.get("reasoning_effort"))
        or "auto",
        "turn_count": len(turns),
        "turns": turns,
        "checks": checks,
        "machine_passed": bool(checks) and all(checks.values()),
        "human_review": {
            "required": True,
            "status": "pending",
            "rubric": [
                "naturalness",
                "contextual relevance",
                "tool restraint",
                "grounding and correctness",
                "step-by-step continuity",
                "recovery behavior",
                "post-action conversational continuity",
            ],
        },
    }


def run_long_conversation_recheck(
    *,
    provider_codes: Sequence[str] = (
        "gemini",
        "openrouter",
        "local-best",
        "local-weak",
    ),
    db_name: str = DB_NAME,
    timeout: float = 180.0,
    gemini_model: str = "",
    openrouter_model: str = "",
) -> dict[str, Any]:
    order_seed = _select_order_seed(db_name=db_name)
    try:
        return_seed: dict[str, Any] | None = _select_return_seed(
            db_name=db_name
        )
    except Exception:
        return_seed = None

    providers: list[dict[str, Any]] = []
    for provider_code in provider_codes:
        try:
            providers.append(
                run_long_provider_conversation(
                    provider_code,
                    order_seed=order_seed,
                    return_seed=return_seed,
                    db_name=db_name,
                    timeout=timeout,
                    gemini_model=gemini_model,
                    openrouter_model=openrouter_model,
                )
            )
        except Exception as exc:
            if provider_code.startswith("local-"):
                shutdown_managed_llama_servers()
            providers.append(
                {
                    "provider_code": provider_code,
                    "turn_count": 0,
                    "turns": [],
                    "checks": {"all_planned_turns_completed": False},
                    "machine_passed": False,
                    "human_review": {
                        "required": True,
                        "status": "blocked_by_runtime_error",
                    },
                    "error": f"{type(exc).__name__}: {_compact_text(exc)}",
                }
            )

    return {
        "name": (
            "live Orders long adaptive conversation recheck "
            f"{date.today().isoformat()}"
        ),
        "artifact_type": "orders_live_long_adaptive_conversation_recheck",
        "created_at": date.today().isoformat(),
        "db": "source-app-db",
        "turn_contract": {
            "minimum_turns": MIN_LONG_TURNS,
            "planned_turns": len(TURN_PHASES),
            "adaptive_next_prompt": True,
            "eight_message_context_interlude": True,
            "fixed_short_prompt_list_is_insufficient": True,
        },
        "safety": {
            "computer_use_used": False,
            "packaged_exe_used": False,
            "marketplace_write_performed": False,
            "db_write_performed": False,
            "execute_performed": False,
            "risky_actions_stop_at_prepare_or_cancel": True,
        },
        "order_seed": order_seed,
        "return_seed": return_seed or {},
        "providers": providers,
        "machine_passed": (
            len(providers) == len(provider_codes)
            and all(bool(provider.get("machine_passed")) for provider in providers)
        ),
        "passed": False,
        "completion_note": (
            "Human review is mandatory. Set passed only after every provider "
            "transcript is reviewed, failures are fixed and the rerun passes."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run long adaptive Orders conversations against the real source DB "
            "through configured cloud and installed local models."
        )
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=("gemini", "openrouter", "local-best", "local-weak"),
        dest="providers",
        help="Repeat to select providers; defaults to all four tiers.",
    )
    parser.add_argument(
        "--gemini-model",
        default="",
        help="Optional exact Gemini model selected from the live free catalog.",
    )
    parser.add_argument(
        "--openrouter-model",
        default="",
        help="Optional override; empty uses the configured OpenRouter model.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--db", default=DB_NAME)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = run_long_conversation_recheck(
        provider_codes=tuple(
            args.providers
            or ("gemini", "openrouter", "local-best", "local-weak")
        ),
        db_name=args.db,
        timeout=max(10.0, float(args.timeout)),
        gemini_model=args.gemini_model,
        openrouter_model=args.openrouter_model,
    )
    target = write_live_evidence_file(Path(args.output), payload)
    print(f"artifact={target}")
    print(f"machine_passed={bool(payload.get('machine_passed'))}")
    print("human_review=pending")
    for provider in list(payload.get("providers") or []):
        checks = dict(provider.get("checks") or {})
        failed = [key for key, value in checks.items() if not bool(value)]
        print(
            "provider="
            f"{provider.get('provider_code')} "
            f"model={provider.get('actual_model') or provider.get('requested_model') or '-'} "
            f"turns={provider.get('turn_count') or 0} "
            f"machine_passed={bool(provider.get('machine_passed'))} "
            f"failed={','.join(failed) or '-'}"
        )
    return 0 if bool(payload.get("machine_passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
