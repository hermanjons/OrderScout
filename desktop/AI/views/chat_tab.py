from __future__ import annotations

import html
import hashlib
import os
import re
import time
import unicodedata
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from settings import DB_NAME
from AI.processors.turn_service import approval_reply_protocol, run_interpreted_turn, resume_reply_interpretation

from AI.constants.ui_constants import (
    AI_CHAT_ACTIVE_BRAIN_CLOUD_TEXT,
    AI_CHAT_ACTIVE_BRAIN_TEMPLATE,
    AI_CHAT_ACTIVE_BRAIN_TEXT,
    AI_CHAT_ASSISTANT_ROLE_TEXT,
    AI_CHAT_ATTACH_BUTTON_TEXT,
    AI_CHAT_BRAIN_CLOUD_TEXT,
    AI_CHAT_BRAIN_TEMPLATE,
    AI_CHAT_BRAIN_UNSELECTED,
    AI_CHAT_AGENT_ACTIVITY_TEXT,
    AI_CHAT_CLOUD_MODEL_MISSING_TEXT,
    AI_CHAT_CLOUD_NOT_CONNECTED_TEXT,
    AI_CHAT_CLOUD_PREP_TEXT,
    AI_CHAT_CLOUD_PROVIDERS_LABEL,
    AI_CHAT_CLOUD_READY_TEXT,
    AI_CHAT_CLOUD_RUNNER_STATUS_TEXT,
    AI_CHAT_CLOUD_WAITING_TEXT,
    AI_CHAT_COMPOSER_PLACEHOLDER,
    AI_CHAT_EMPTY_LIBRARY_TEXT,
    AI_CHAT_HEADER_HINT,
    AI_CHAT_HERO_ACTION_TEXT,
    AI_CHAT_HERO_SUBTITLE,
    AI_CHAT_HERO_TITLE,
    AI_CHAT_INSTALLED_MODEL_COUNT_TEMPLATE,
    AI_CHAT_LOCAL_COUNT_TEMPLATE,
    AI_CHAT_LOCAL_MODELS_LABEL,
    AI_CHAT_LOCAL_PREP_TEXT,
    AI_CHAT_LOCAL_READY_TEXT,
    AI_CHAT_LOCAL_RUNNER_PENDING_TEMPLATE,
    AI_CHAT_LOCAL_RUNNER_STATUS_TEXT,
    AI_CHAT_MODEL_LIST_WAITING,
    AI_CHAT_MODEL_PANEL_INTRO_TEXT,
    AI_CHAT_MODEL_PANEL_INTRO_TITLE,
    AI_CHAT_MODEL_PANEL_TITLE,
    AI_CHAT_MODEL_PANEL_TOOLTIP,
    AI_CHAT_MODEL_SOURCE_LABEL,
    AI_CHAT_MODELS_LOAD_FAILED_TEXT,
    AI_CHAT_NEW_CHAT_BUTTON_TEXT,
    AI_CHAT_NO_LOCAL_MODEL_TEXT,
    AI_CHAT_NOTES_TEXT,
    AI_CHAT_NOTES_TITLE,
    AI_CHAT_OPEN_HUB_TEXT,
    AI_CHAT_PROVIDER_COUNT_TEMPLATE,
    AI_CHAT_PROVIDER_EMPTY_TEXT,
    AI_CHAT_PROVIDER_LOAD_FAILED_TEXT,
    AI_CHAT_REFRESH_MODELS_TEXT,
    AI_CHAT_RUNNER_STATUS_TEXT,
    AI_CHAT_RUNNER_WAITING_TEXT,
    AI_CHAT_SCANNING_MODELS_TEXT,
    AI_CHAT_SECTION_TITLE,
    AI_CHAT_SELECTED_LOCAL_BRAIN_TEMPLATE,
    AI_CHAT_SELECT_CLOUD_PROVIDER_TEXT,
    AI_CHAT_SELECT_LOCAL_MODEL_TEXT,
    AI_CHAT_SEND_BUTTON_TEXT,
    AI_CHAT_SESSION_READY,
    AI_CHAT_SOURCE_CLOUD_TEXT,
    AI_CHAT_SOURCE_CLOUD_VALUE,
    AI_CHAT_SOURCE_LOCAL_TEXT,
    AI_CHAT_SOURCE_LOCAL_VALUE,
    AI_CHAT_SOURCE_PILL_CLOUD_TEXT,
    AI_CHAT_SOURCE_PILL_LOCAL_TEXT,
    AI_CHAT_STATUS_WAITING,
    AI_CHAT_SUGGESTIONS,
    AI_CHAT_TOOL_ACTIVITY_TEMPLATE,
    AI_CHAT_USER_ROLE_TEXT,
    AI_CHAT_WELCOME_SUBTITLE,
    AI_CHAT_WELCOME_TITLE,
)


class _AiActionsProxy:
    def __getattr__(self, name: str):
        import AI.views.actions as actions

        return getattr(actions, name)


ai_actions = _AiActionsProxy()
from AI.views.views import AIManagerDialog
from Core.threads.sync_worker import SyncWorker
from Core.views import ResettableSplitter
from Core.views.tab_widgets import SplitPanelSidebar
from Feedback.processors.pipeline import MessageHandler, Result
from settings import ASSETS_DIR
from AI.processors.agent import (
    pending_action_followup_read_requested,
    run_agent_turn,
    run_pending_action_read_before_provider,
)
from AI.processors.session_state import (
    AgentSessionState,
    referenced_action_id_from_text,
)
from AI.processors.cloud_runtime import (
    begin_provider_chat_turn,
    build_provider_chat_client,
    provider_invocation_provenance,
)
from AI.processors.conversation_runtime import (
    grounded_capability_overview,
    policy_context_from_interpretation,
)
from AI.processors.local_runtime import build_local_planner_client, release_local_planner_client
from AI.processors.local_resources import build_local_resource_plan
from AI.processors.operation_runtime import execute_approved_operation
from AI.processors.task_store import list_agent_task_states, load_agent_task_state
from AI.processors.task_runtime import (
    cancel_agent_task_by_id,
    interpret_agent_turn,
    model_authored_projection_acceptance,
    provider_unavailable_answer,
    provider_unavailable_details,
    record_conversation_exchange,
    resume_agent_task_by_id,
    run_agent_task,
    run_existing_observation_read_turn,
    run_model_conversation_turn,
    safe_agent_runtime_context,
    supersede_agent_task_by_id,
)


def _local_contextual_write_followup_requested(text: str, history: list[dict[str, str]]) -> bool:
    normalized = _safe_text(text, "").casefold()
    normalized = (
        normalized.replace("Ä±", "i")
        .replace("ÄŸ", "g")
        .replace("Ã¼", "u")
        .replace("ÅŸ", "s")
        .replace("Ã¶", "o")
        .replace("Ã§", "c")
    )
    has_reference = any(
        token in normalized
        for token in (
            "bunu",
            "bunlari",
            "bunları",
            "onlari",
            "onları",
            "hepsini",
            "listedeki",
            "olan",
            "olani",
            "olanı",
        )
    )
    has_write = any(
        token in normalized
        for token in (
            "yazdir",
            "yazdır",
            "onayla",
            "onaylat",
            "degistir",
            "değiştir",
            "guncelle",
            "güncelle",
            "temizle",
            "geri al",
            "isaretle",
            "işaretle",
            "aktar",
        )
    )
    if not (has_reference and has_write):
        return False
    previous_text = "\n".join(_safe_text(row.get("content"), "") for row in history[:-1] if isinstance(row, dict))
    previous_normalized = previous_text.casefold()
    return any(token in previous_normalized for token in ("siparis", "sipariş", "order", "iade", "return", "claim", "ord-", "claim-")) or bool(
        re.search(r"(?m)^\s*\d+\.\s*(?:\d{6,}|ord[-_]|claim[-_])", previous_text, flags=re.IGNORECASE)
    )


def _run_chat_turn_with_runtime(
    text: str,
    *,
    source: str,
    runtime_record: dict[str, Any],
    history: list[dict[str, str]],
    session_state: dict[str, Any] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
    task_control: Any = None,
) -> Result:
    record = dict(runtime_record or {})
    planner_client = None
    state_kwargs = (
        {"session_state": session_state}
        if isinstance(session_state, dict)
        else {}
    )
    task_domain = ""

    # An active approval card is authoritative typed application state. A
    # read-only question about that card must be answered before provider
    # interpretation: no model call, business tool, API, DB or file effect is
    # needed to explain state the application already owns.
    from AI.processors.model_loop import is_model_loop, run_model_loop, project_runtime_result
    pending_read = run_pending_action_read_before_provider(
        text,
        session_state=session_state,
        model_record=record,
        history=history,
    ) if session_state and not is_model_loop(session_state) and session_state.get("active_pending_action_id") else None
    if pending_read is not None:
        pending_data = dict(pending_read.data or {})
        if (
            pending_read.success
            and _safe_text(pending_data.get("decision_path"), "")
            == "pending_action_scope_read_guard"
        ):
            pending_data.update(
                {
                    "model_invocation_attempted": False,
                    "model_response_received": False,
                    "final_model_response_received": False,
                    "model_invoked": False,
                    "accepted_semantic_output": False,
                    "final_response_source": "typed_pending_state_projection",
                    "pending_action_read_only": True,
                    "pending_action_preserved": True,
                    "active_pending_action_id": _safe_text(
                        pending_data.get("active_pending_action_id"),
                        "",
                    ),
                    "runtime": {
                        "source": source,
                        "runtime_name": "typed_pending_state",
                        "model_name": _safe_text(
                            record.get("default_model"),
                            "selected",
                        ),
                        "model_invoked": False,
                        "model_invocation_attempted": False,
                        "model_response_received": False,
                        "final_model_response_received": False,
                        "accepted_semantic_output": False,
                        "final_response_source": "typed_pending_state_projection",
                        "decision_path": "pending_action_scope_read_guard",
                        "resource_plan": {},
                    },
                }
            )
            pending_read.data = pending_data
            return pending_read
        return pending_read

    if source == AI_CHAT_SOURCE_LOCAL_VALUE:
        try:
            planner_client = build_local_planner_client(record)
        except Exception:
            planner_client = None
        if planner_client is None:
            return Result.fail("Seçilen yerel model başlatılamadı; sohbet model bağlantısı bekliyor.", close_dialog=False)
    else:
        provider_id = int(record.get("id") or 0)
        explicit_runtime_override = bool(
            record.get("_explicit_runtime_override")
            or record.get("_source_kind") == "cloud_model"
        )
        selected_model = _safe_text(record.get("default_model"), "")
        selected_reasoning_effort = _safe_text(
            record.get("reasoning_effort"),
            "",
        )
        selected_fallback_setting = record.get("allow_model_fallback")
        if provider_id <= 0:
            return Result.fail(AI_CHAT_SELECT_CLOUD_PROVIDER_TEXT, close_dialog=False)
        detail_res = ai_actions.action_get_provider_account(provider_id)
        if not detail_res.success:
            return detail_res
        record = dict((detail_res.data or {}).get("record") or {})
        if not record:
            return Result.fail(AI_CHAT_CLOUD_NOT_CONNECTED_TEXT, close_dialog=False)
        if explicit_runtime_override and selected_model:
            record["default_model"] = selected_model
        if explicit_runtime_override and selected_reasoning_effort:
            record["reasoning_effort"] = selected_reasoning_effort
        if explicit_runtime_override and selected_fallback_setting is not None:
            record["allow_model_fallback"] = bool(selected_fallback_setting)
        if explicit_runtime_override:
            for field in (
                "model_metadata",
                "free_model_test_route",
                "max_tokens",
                "max_output_tokens",
                "maxOutputTokens",
                "temperature",
                "top_p",
                "top_k",
                "repeat_penalty",
            ):
                if field in runtime_record:
                    record[field] = runtime_record.get(field)
        planner_client = build_provider_chat_client(record)
        if planner_client is None:
            return Result.fail(AI_CHAT_CLOUD_MODEL_MISSING_TEXT, close_dialog=False)
        begin_provider_chat_turn(planner_client)

    # Normal model-backed conversation has one decision owner. Legacy typed
    # routing remains only for already-saved controls and unavailable runtimes.
    control_mode = approval_reply_protocol(text, session_state)
    if planner_client is not None and not control_mode and not resume_reply_interpretation(text, session_state):
        try:
            result = run_model_loop(text, client=planner_client, session_state=session_state, history=history,
                db_name=DB_NAME, persist=True, runtime_context=_task_runtime_context(source, record),
                progress_callback=progress_callback, task_control=task_control)
            return project_runtime_result(result, planner_client, source=source, model_name=record.get("default_model", ""))
        finally:
            if source == AI_CHAT_SOURCE_LOCAL_VALUE and bool(getattr(planner_client, "release_after_turn", False)):
                release_local_planner_client(planner_client)

    heuristic_task_domain = _task_domain_requested(text, history=history)
    task_domain = heuristic_task_domain
    turn_interpretation: dict[str, Any] = {}
    interpretation_result: Result | None = None
    if planner_client is not None:
        resume_interpretation = resume_reply_interpretation(text, session_state)
        interpretation_result = (Result.ok("Typed action control.", data={"valid": True, "mode": control_mode,
                                    "domain": "general", "objective": text, "intent_kind": "approval_control",
                                    "planner_invoked": False}) if control_mode else
                                 Result.ok("Task resume control.", data=resume_interpretation) if resume_interpretation
                                 else interpret_agent_turn(text, planner_client=planner_client, history=history, session_state=session_state))
        turn_interpretation = dict(interpretation_result.data or {})

    task_dispatched = False

    def run_ui_task(*args: Any, **kwargs: Any) -> Result:
        nonlocal task_dispatched
        task_dispatched = True
        task_result = run_agent_task(*args, **kwargs)
        task_result.data = _chat_data_from_task_result(task_result)
        return task_result

    def run_ui_approval(state_payload: dict[str, Any], **options: Any) -> Result:
        state = AgentSessionState.from_dict(state_payload)
        action = dict(state.active_pending_action() or {})
        action["_agent_task_session_id"] = state.session_id
        action["_agent_task_runtime"] = dict(state.active_entities.get("runtime_context") or {})
        approval_options: dict[str, Any] = {"progress_callback": progress_callback}
        if options.get("task_control") is not None:
            approval_options["task_control"] = options["task_control"]
        return _run_approved_chat_action(action, **approval_options)

    def run_ui_resume(state_payload: dict[str, Any], **options: Any) -> Result:
        from AI.processors.task_runtime import resume_read_task
        task_result = resume_read_task(state_payload, **options)
        task_result.data = _chat_data_from_task_result(task_result)
        return task_result

    # Provider selection and UI projection stay in this adapter; the typed
    # decision is dispatched by the same service as headless acceptance.
    result = (
        run_interpreted_turn(
            text,
            interpretation_result=interpretation_result,
            client=planner_client,
            history=history,
            session_state=session_state,
            db_name=DB_NAME,
            runtime_context=_task_runtime_context(source, record),
            persist=True,
            progress_callback=progress_callback,
            task_runner=run_ui_task,
            observation_reader=run_existing_observation_read_turn,
            conversation_runner=run_model_conversation_turn,
            capability_reader=grounded_capability_overview,
            policy_context_builder=policy_context_from_interpretation,
            handle_controls=True,
            allow_approval_execute=True,
            approval_runner=run_ui_approval,
            resume_runner=run_ui_resume,
            task_control=task_control,
        )
        if interpretation_result is not None
        else None
    )
    if result is None and planner_client is None and task_domain:
        # Preserve the existing local runtime path when no model is available.
        result = run_ui_task(
            text,
            domain=task_domain,
            planner_client=None,
            chat_client=None,
            db_name=DB_NAME,
            history=history,
            persist=True,
            progress_callback=progress_callback,
            runtime_context=_task_runtime_context(source, record),
            turn_interpretation=turn_interpretation,
            session_state=session_state,
        )
    elif result is None:
        result = run_agent_turn(
            text,
            model_record=record,
            planner_client=planner_client,
            chat_client=planner_client,
            history=history,
            **state_kwargs,
        )
    if (
        source == AI_CHAT_SOURCE_LOCAL_VALUE
        and not result.success
        and not task_dispatched
        and _safe_text(turn_interpretation.get("mode"), "").casefold()
        not in {"inspect", "act", "correct"}
    ):
        fallback = run_agent_turn(
            text,
            model_record=record,
            planner_client=None,
            chat_client=None,
            history=history,
            **state_kwargs,
        )
        if fallback.success:
            result = fallback
    data = dict(result.data or {})
    if turn_interpretation:
        data["turn_interpretation"] = dict(turn_interpretation)
    plan = getattr(planner_client, "resource_plan", {}) if planner_client is not None else {}
    plan = dict(plan or {}) if isinstance(plan, dict) else {}
    provider_provenance = provider_invocation_provenance(plan)
    partial_non_business_provider_failure = bool(
        source == AI_CHAT_SOURCE_CLOUD_VALUE
        and not result.success
        and turn_interpretation.get("valid") is True
        and _safe_text(turn_interpretation.get("mode"), "").casefold()
        in {"chat", "explain"}
        and plan.get("model_invocation_attempted") is True
        and provider_provenance.get("final_model_response_received") is not True
    )
    if partial_non_business_provider_failure:
        provider_failure = provider_unavailable_details(planner_client)
        if provider_failure:
            provider_answer = provider_unavailable_answer(provider_failure)
            data.update(
                {
                    "mode": "provider_unavailable",
                    "answer": provider_answer,
                    "tool_names": [],
                    "provider_unavailable": True,
                    "provider_failure": provider_failure,
                    "decision_path": (
                        "typed_model_non_business_provider_unavailable"
                    ),
                }
            )
            result = Result.ok(
                provider_answer,
                close_dialog=False,
                data=data,
            )
    model_invocation_attempted = bool(
        data.get("model_invoked")
        or plan.get("model_invocation_attempted")
    )
    if source == AI_CHAT_SOURCE_CLOUD_VALUE:
        final_model_response_received = bool(
            provider_provenance.get("final_model_response_received")
        )
        model_response_received = bool(
            provider_provenance.get("any_model_response_received")
        )
    else:
        model_response_received = bool(data.get("model_invoked"))
        final_model_response_received = model_response_received
    data["model_invocation_attempted"] = model_invocation_attempted
    data["model_response_received"] = model_response_received
    data["final_model_response_received"] = final_model_response_received
    data["model_invoked"] = model_response_received
    task_state_payload = (
        data.get("state")
        if isinstance(data.get("state"), dict)
        else (data.get("tool_result") or {}).get("state")
        if isinstance(data.get("tool_result"), dict)
        and isinstance((data.get("tool_result") or {}).get("state"), dict)
        else None
    )
    response_synthesis = (
        dict(
            (
                dict(task_state_payload or {}).get("active_entities") or {}
            ).get("response_synthesis")
            or {}
        )
        if isinstance(task_state_payload, dict)
        and isinstance(
            dict(task_state_payload or {}).get("active_entities"),
            dict,
        )
        else {}
    )
    if (
        not response_synthesis
        and isinstance(data.get("response_synthesis"), dict)
    ):
        response_synthesis = dict(data.get("response_synthesis") or {})
    final_response_source = _safe_text(
        response_synthesis.get("final_source"),
        "",
    )
    selected_operation_ids = {
        _safe_text(
            (data.get("tool_call") or {}).get("tool"),
            "",
        )
        if isinstance(data.get("tool_call"), dict)
        else ""
    }
    selected_operation_ids.update(
        _safe_text(row.get("tool"), "")
        for row in list(data.get("tool_calls") or [])
        if isinstance(row, dict)
    )
    projection_acceptance = model_authored_projection_acceptance(
        task_state_payload,
        selected_operation_ids={
            value for value in selected_operation_ids if value
        },
        final_model_response_received=final_model_response_received,
    )
    data["response_synthesis"] = response_synthesis
    data["final_response_source"] = final_response_source
    data["accepted_semantic_output"] = bool(
        final_response_source
        in {"verified_model_candidate", "verified_model_repair"}
        or (
            final_response_source
            == "deterministic_verified_uncertainty"
            and final_model_response_received
        )
        or (
            final_response_source
            == "deterministic_verified_non_business_fallback"
            and final_model_response_received
        )
        or (
            _safe_text(data.get("decision_path"), "")
            in {
                "typed_model_non_business_turn",
                "typed_capability_catalog_grounded",
            }
            and final_model_response_received
        )
        or projection_acceptance.get("verified_business_projection") is True
    )
    data["accepted_semantic_output_source"] = (
        "model_authored_verified_projection"
        if projection_acceptance.get("verified_business_projection") is True
        else "deterministic_verified_uncertainty"
        if (
            data["accepted_semantic_output"]
            and final_response_source
            == "deterministic_verified_uncertainty"
        )
        else "deterministic_verified_non_business_fallback"
        if (
            data["accepted_semantic_output"]
            and final_response_source
            == "deterministic_verified_non_business_fallback"
        )
        else "verified_model_response"
        if data["accepted_semantic_output"]
        else ""
    )
    data["runtime"] = {
        "source": source,
        "runtime_name": _safe_text(getattr(planner_client, "runtime_name", None), "rule_fallback"),
        "model_name": _safe_text(getattr(planner_client, "model_name", None), "selected"),
        # Attempt, successful provider response and accepted semantic output
        # are different facts. A fail-closed deterministic recovery must never
        # make a quota/404 attempt look like a real model-backed acceptance.
        "model_invoked": model_response_received,
        "model_invocation_attempted": model_invocation_attempted,
        "model_response_received": model_response_received,
        "final_model_response_received": final_model_response_received,
        "accepted_semantic_output": data["accepted_semantic_output"],
        "accepted_semantic_output_source": data[
            "accepted_semantic_output_source"
        ],
        "final_response_source": final_response_source,
        "decision_path": _safe_text(data.get("decision_path"), ""),
        "resource_plan": plan,
        "provider_provenance": provider_provenance,
    }
    result.data = data
    if source == AI_CHAT_SOURCE_LOCAL_VALUE and bool(getattr(planner_client, "release_after_turn", False)):
        release_local_planner_client(planner_client)
    return result


def _run_approved_chat_action(
    action: dict[str, Any],
    *,
    progress_callback: Callable[[int, str], None] | None = None,
    task_control: AgentTaskControl | None = None,
) -> Result:
    clean_action = dict(action or {})
    task_session_id = _safe_text(clean_action.get("_agent_task_session_id"), "")
    if task_session_id:
        raw_runtime_context = (
            dict(clean_action.get("_agent_task_runtime") or {})
            if isinstance(clean_action.get("_agent_task_runtime"), dict)
            else {}
        )
        stored_runtime_policy_hash = _safe_text(
            raw_runtime_context.get("runtime_policy_hash"),
            "",
        )
        runtime_context = safe_agent_runtime_context(raw_runtime_context)
        planner_client = None
        runtime_source = _safe_text(runtime_context.get("source"), "")
        task_store_root = _safe_text(clean_action.get("_agent_task_store_root"), "")
        try:
            if runtime_source == AI_CHAT_SOURCE_CLOUD_VALUE:
                rebuilt_policy_hash = _safe_text(
                    runtime_context.get("runtime_policy_hash"),
                    "",
                )
                if (
                    stored_runtime_policy_hash
                    and stored_runtime_policy_hash != rebuilt_policy_hash
                ):
                    raise RuntimeError(
                        "Kayitli cloud runtime politikasi degismis; task guvenli bicimde devam ettirilmedi."
                    )
                provider_id = int(runtime_context.get("provider_id") or 0)
                detail_res = ai_actions.action_get_provider_account(provider_id)
                if not detail_res.success:
                    raise RuntimeError(detail_res.message)
                provider_record = dict((detail_res.data or {}).get("record") or {})
                pinned_provider_code = _safe_text(
                    runtime_context.get("provider_code"),
                    "",
                ).casefold()
                current_provider_code = _safe_text(
                    provider_record.get("provider_code"),
                    "",
                ).casefold()
                if (
                    pinned_provider_code
                    and pinned_provider_code != current_provider_code
                ):
                    raise RuntimeError(
                        "Task provider kimligi degistigi icin guvenli bicimde devam ettirilmedi."
                    )
                pinned_model = _safe_text(runtime_context.get("model_name"), "")
                if pinned_model:
                    provider_record["default_model"] = pinned_model
                pinned_reasoning_effort = _safe_text(runtime_context.get("reasoning_effort"), "")
                if pinned_reasoning_effort:
                    provider_record["reasoning_effort"] = pinned_reasoning_effort
                if "allow_model_fallback" in runtime_context:
                    provider_record["allow_model_fallback"] = bool(
                        runtime_context.get("allow_model_fallback")
                    )
                for field in (
                    "model_metadata",
                    "free_model_test_route",
                    "max_tokens",
                    "max_output_tokens",
                    "maxOutputTokens",
                    "temperature",
                ):
                    if field in runtime_context:
                        provider_record[field] = runtime_context.get(field)
                planner_client = build_provider_chat_client(provider_record)
                if planner_client is None:
                    raise RuntimeError(AI_CHAT_CLOUD_MODEL_MISSING_TEXT)
                begin_provider_chat_turn(planner_client)
            elif runtime_source == AI_CHAT_SOURCE_LOCAL_VALUE:
                local_record = (
                    dict(runtime_context.get("model_record") or {})
                    if isinstance(runtime_context.get("model_record"), dict)
                    else {}
                )
                planner_client = build_local_planner_client(local_record)
                if planner_client is None:
                    raise RuntimeError("Kayitli yerel model task devaminda baslatilamadi.")
            resume_kwargs: dict[str, Any] = {
                "approved_by": "chat_ui",
                "progress_callback": progress_callback,
                "db_name": DB_NAME,
            }
            action_id = _safe_text(clean_action.get("action_id"), "")
            if action_id:
                resume_kwargs["action_id"] = action_id
            if task_store_root:
                resume_kwargs["task_store_root"] = task_store_root
            if task_control is not None:
                resume_kwargs["task_control"] = task_control
            if planner_client is not None:
                resume_kwargs["planner_client"] = planner_client
                resume_kwargs["chat_client"] = planner_client
            result = resume_agent_task_by_id(task_session_id, **resume_kwargs)
        except Exception as exc:
            try:
                state = load_agent_task_state(
                    task_session_id,
                    root=task_store_root or None,
                )
                result = Result.fail(
                    f"Task ayni LLM runtime'i ile devam edemedi: {_safe_text(exc)}",
                    error=exc,
                    close_dialog=False,
                    data={"state": state.to_dict()},
                )
            except Exception:
                result = Result.fail(
                    f"Task ayni LLM runtime'i ile devam edemedi: {_safe_text(exc)}",
                    error=exc,
                    close_dialog=False,
                )
        finally:
            if runtime_source == AI_CHAT_SOURCE_LOCAL_VALUE and bool(
                getattr(planner_client, "release_after_turn", False)
            ):
                release_local_planner_client(planner_client)
        result.data = _chat_data_from_task_result(result)
        return result
    if progress_callback is not None:
        progress_callback(35, "Onaylanan islemi calistiriyorum.")
    result = execute_approved_operation(clean_action, approved_by="chat_ui")
    if result.success and progress_callback is not None:
        progress_callback(82, "Onaylanan islem calisti; sonucu dogruladim.")
    return result


def _run_scheduled_chat_with_runtime(*, lease: Any, scheduler: Any, source: str,
                                   runtime_record: dict[str, Any], current_session: dict[str, Any],
                                   allowed_scope_bindings: dict[str, Any], task_control: Any = None,
                                   progress_callback: Callable[..., None] | None = None) -> Result:
    from AI.processors.scheduled_task_runtime import run_scheduled_task
    record = dict(runtime_record)
    client = None
    try:
        if source == AI_CHAT_SOURCE_LOCAL_VALUE:
            client = build_local_planner_client(record)
        else:
            provider_id = int(record.get("id") or 0)
            if provider_id <= 0:
                return Result.fail(AI_CHAT_SELECT_CLOUD_PROVIDER_TEXT, close_dialog=False)
            detail = ai_actions.action_get_provider_account(provider_id)
            if not detail.success:
                return detail
            selected = record
            record = dict((detail.data or {}).get("record") or {})
            if selected.get("_explicit_runtime_override") or selected.get("_source_kind") == "cloud_model":
                for key in ("default_model", "reasoning_effort", "allow_model_fallback", "model_metadata",
                            "free_model_test_route", "max_tokens", "max_output_tokens", "maxOutputTokens",
                            "temperature", "top_p", "top_k", "repeat_penalty"):
                    if key in selected:
                        record[key] = selected[key]
            client = build_provider_chat_client(record)
        if client is None:
            return Result.fail("Planlı çalışma için seçilen model bağlantısı hazır değil.", close_dialog=False)
        result = run_scheduled_task(
            lease, scheduler=scheduler, client=client, db_name=DB_NAME,
            provider_code=str(record.get("provider_code") or source),
            model_name=str(getattr(client, "model_name", None) or record.get("default_model") or "selected"),
            current_session=current_session, allowed_scope_bindings=allowed_scope_bindings,
            runtime_context=_task_runtime_context(source, record), task_control=task_control,
            progress_callback=progress_callback,
        )
        data = dict(result.data or {})
        workflow_result = data.get("workflow_result")
        if isinstance(workflow_result, dict):
            projected = _chat_data_from_task_result(Result(success=result.success, message=result.message,
                                                           close_dialog=False, data=workflow_result))
            projected["scheduled_run"] = dict(data.get("run") or {})
            projected["runtime"] = {"source": source, "model_name": getattr(client, "model_name", "selected"),
                                    "resource_plan": dict(getattr(client, "resource_plan", {}) or {}),
                                    "provider_provenance": workflow_result.get("provider_provenance") or {}}
            result.data = projected
        return result
    finally:
        if source == AI_CHAT_SOURCE_LOCAL_VALUE and client is not None and bool(getattr(client, "release_after_turn", False)):
            release_local_planner_client(client)


def _task_runtime_context(source: str, record: dict[str, Any]) -> dict[str, Any]:
    clean_source = _safe_text(source, "")
    if clean_source == AI_CHAT_SOURCE_CLOUD_VALUE:
        provider_id = int(record.get("id") or 0)
        if provider_id <= 0:
            return {}
        context = {
            "source": AI_CHAT_SOURCE_CLOUD_VALUE,
            "provider_id": provider_id,
            "provider_label": _safe_text(record.get("label"), ""),
            "provider_code": _safe_text(record.get("provider_code"), ""),
            "model_name": _safe_text(record.get("default_model"), ""),
        }
        reasoning_effort = _safe_text(record.get("reasoning_effort"), "")
        if reasoning_effort:
            context["reasoning_effort"] = reasoning_effort
        if "allow_model_fallback" in record:
            context["allow_model_fallback"] = bool(
                record.get("allow_model_fallback")
            )
        for field in (
            "model_metadata",
            "free_model_test_route",
            "max_tokens",
            "max_output_tokens",
            "maxOutputTokens",
            "temperature",
        ):
            if field in record:
                context[field] = record.get(field)
        return safe_agent_runtime_context(context)
    if clean_source != AI_CHAT_SOURCE_LOCAL_VALUE:
        return {}
    allowed_keys = (
        "id",
        "repo_id",
        "filename",
        "local_path",
        "model_path",
        "gguf_path",
        "quantization",
        "size_bytes",
        "size_text",
        "parameter_size",
        "architecture",
    )
    model_record = {
        key: record.get(key)
        for key in allowed_keys
        if record.get(key) not in (None, "")
    }
    return {
        "source": AI_CHAT_SOURCE_LOCAL_VALUE,
        "model_record": model_record,
        "model_name": _safe_text(
            record.get("local_path") or record.get("filename") or record.get("repo_id"),
            "",
        ),
    }


def _orders_task_requested(text: str, *, history: list[dict[str, str]] | None = None) -> bool:
    normalized = _safe_text(text, "").casefold()
    normalized = (
        normalized.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    advice_requested = any(
        token in normalized
        for token in (
            "sence",
            "ne olmali",
            "ne yapmaliyim",
            "ne yapmali",
            "ilk hamle",
            "onceligim ne",
            "oneri",
            "tavsiye",
        )
    )
    explicit_write_requested = any(
        token in normalized
        for token in (
            "yazdir",
            "etiket",
            "degistir",
            "guncelle",
            "onayla",
            "kabul et",
            "veri cek",
            "senkron",
            "sync",
            "fetch",
            "excel",
            "xlsx",
            "isaretle",
        )
    )
    historical_action_reference = any(
        token in normalized
        for token in (
            "hazirladigimiz",
            "hazirlanan",
            "hazirlamistik",
            "olusturdugumuz",
            "olusturulan",
            "yazdirdigimiz",
        )
    )
    explicit_read_analysis = (
        any(
            token in normalized
            for token in ("analiz", "sonuc", "ozet", "gecikme")
        )
        and any(
            token in normalized
            for token in ("goster", "listele", "soyle", "getir", "tekrar")
        )
    )
    if historical_action_reference and explicit_read_analysis:
        # Past-tense action references describe the selected set; they are not
        # a new write step. Keep long-range "the orders whose labels we made"
        # analysis follow-ups in the normal read-only chat path.
        return False
    if advice_requested and not explicit_write_requested:
        return False
    explicit_order_reference = bool(
        re.search(
            r"\b(?:ORD[-_][A-Z0-9][A-Z0-9_-]*|\d{6,})\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    has_orders_domain = explicit_order_reference or any(
        token in normalized
        for token in ("siparis", "order", "iade", "return", "claim", "kargo")
    )
    has_task_intent = any(token in normalized for token in ("operasyon", "toparla", "gorev", "task", "bitene kadar", "devam et"))
    if has_orders_domain and has_task_intent:
        return True
    intent_groups = {
        "read": any(token in normalized for token in ("getir", "listele", "goster", "soyle", "bul")),
        "label": any(token in normalized for token in ("yazdir", "etiket", "label")),
        "extracted": any(token in normalized for token in ("fis cikarildi", "cikti alindi", "extracted")),
        "cargo_change": (
            any(token in normalized for token in ("kargo", "cargo", "firma", "provider"))
            and any(token in normalized for token in ("degistir", "yap", "ayarla", "guncelle"))
        ),
        "return_approval": (
            any(token in normalized for token in ("iade", "return", "claim"))
            and any(token in normalized for token in ("onayla", "kabul et", "approve"))
        ),
        "fetch": any(token in normalized for token in ("veri cek", "senkron", "sync", "fetch")),
        "profit_export": (
            any(token in normalized for token in ("kar", "profit"))
            and any(token in normalized for token in ("excel", "xlsx", "aktar", "export"))
        ),
    }
    active_intents = {name for name, active in intent_groups.items() if active}
    write_intents = active_intents - {"read"}
    sequence_connector = (
        any(token in normalized for token in (" sonra", "ardindan", "ardından", " once ", " önce ", " ve "))
        or "," in normalized
        or ";" in normalized
    )
    if (
        (has_orders_domain or _history_has_orders_reference(history))
        and sequence_connector
        and write_intents
        and len(active_intents) >= 2
    ):
        return True
    has_reference = any(
        token in normalized
        for token in ("bunu", "bunlar", "bunlari", "onlar", "onlari", "onceki", "listedeki", "kalanlar")
    )
    if not (has_reference and has_task_intent):
        return False
    previous_text = "\n".join(
        _safe_text(row.get("content"), "")
        for row in list(history or [])
        if isinstance(row, dict)
    )
    return bool(
        re.search(
            r"\b(?:ORD|CLAIM|CLM)[-_][A-Z0-9][A-Z0-9_-]*\b",
            previous_text,
            flags=re.IGNORECASE,
        )
    ) or any(
        token in previous_text.casefold()
        for token in ("siparis", "sipariş", "order", "iade", "return", "claim", "kargoya hazir", "kargoya hazır")
    )


def _task_domain_requested(
    text: str,
    *,
    history: list[dict[str, str]] | None = None,
) -> str:
    normalized = _safe_text(text, "").casefold()
    normalized = (
        normalized.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    has_task_intent = any(
        token in normalized
        for token in ("operasyon", "toparla", "gorev", "task", "bitene kadar", "devam et")
    )
    has_multi_read_intent = (
        any(token in normalized for token in ("genel", "ozet", "durum"))
        and any(token in normalized for token in ("dusuk", "kritik", "sifir", "negatif", "tukenen"))
    )
    domain_tokens = {
        "stock": ("stok", "envanter", "inventory"),
        "finance": ("finans", "finance", "nakit akis", "cashflow", "maliyet"),
        "listing": ("ilan", "listing", "listeleme"),
        "logistics": ("lojistik", "logistics", "kargo tarife", "kargo saglayici"),
        "marketplaces": ("pazaryeri", "marketplace", "magaza hesap"),
    }
    for domain, tokens in domain_tokens.items():
        if not any(token in normalized for token in tokens):
            continue
        if has_task_intent or (domain == "stock" and has_multi_read_intent):
            return domain
    if _orders_task_requested(text, history=history):
        return "orders"
    return ""


def _history_has_orders_reference(history: list[dict[str, str]] | None) -> bool:
    previous_text = "\n".join(
        _safe_text(row.get("content"), "")
        for row in list(history or [])
        if isinstance(row, dict)
    )
    return bool(
        re.search(
            r"\b(?:ORD|CLAIM|CLM)[-_][A-Z0-9][A-Z0-9_-]*\b",
            previous_text,
            flags=re.IGNORECASE,
        )
    ) or any(
        token in previous_text.casefold()
        for token in ("siparis", "sipariÅŸ", "order", "iade", "return", "claim")
    )


def _format_runtime_activity(source: str, runtime: dict[str, Any]) -> str:
    runtime_plan = runtime.get("resource_plan") if isinstance(runtime.get("resource_plan"), dict) else {}
    runtime_name = _safe_text(runtime.get("runtime_name"), "rule_fallback")
    model_name = _safe_text(runtime.get("model_name"), "selected")
    if source == AI_CHAT_SOURCE_LOCAL_VALUE:
        return (
            f"Local runner: {runtime_name} / {model_name} / {runtime_plan.get('profile')} "
            f"/ ctx {runtime_plan.get('num_ctx')} / out {runtime_plan.get('max_tokens')}"
        )
    if bool(runtime_plan.get("fallback_used")):
        requested = _safe_text(runtime_plan.get("requested_model"), "")
        actual = _safe_text(runtime_plan.get("actual_model") or model_name, model_name)
        if requested and actual and requested != actual:
            return f"Cloud runner: {runtime_name} / {actual} (fallback: {requested} -> {actual})"
    return f"Cloud runner: {runtime_name} / {model_name}"


def _chat_data_from_task_result(result: Result) -> dict[str, Any]:
    data = dict(result.data or {})
    from AI.processors.model_loop import is_model_loop
    if is_model_loop(data.get("state") or data.get("session_state") or {}):
        return data
    nested_tool_result = (
        dict(data.get("tool_result") or {})
        if isinstance(data.get("tool_result"), dict)
        else {}
    )
    state = (
        dict(data.get("state") or {})
        if isinstance(data.get("state"), dict)
        else (
            dict(nested_tool_result.get("state") or {})
            if isinstance(nested_tool_result.get("state"), dict)
            else {}
        )
    )
    steps = [dict(step) for step in list(state.get("completed_steps") or []) if isinstance(step, dict)]
    pending = [dict(action) for action in list(state.get("pending_actions") or []) if isinstance(action, dict)]
    session_id = _safe_text(state.get("session_id"), "")
    state_path = _safe_text(data.get("state_path"), "")
    active_entities = (
        dict(state.get("active_entities") or {})
        if isinstance(state.get("active_entities"), dict)
        else {}
    )
    runtime_context = (
        dict(active_entities.get("runtime_context") or {})
        if isinstance(active_entities.get("runtime_context"), dict)
        else {}
    )
    if session_id:
        for action in pending:
            action["_agent_task_session_id"] = session_id
            action["_agent_task_resume"] = True
            if runtime_context:
                action["_agent_task_runtime"] = runtime_context
            if state_path:
                action["_agent_task_state_path"] = state_path
                action["_agent_task_store_root"] = str(Path(state_path).parent)
    state["pending_actions"] = pending
    progress_events = [
        dict(event)
        for event in list(state.get("progress_events") or [])
        if isinstance(event, dict)
    ]
    tool_names: list[str] = []
    for step in steps:
        for tool_name in list(step.get("tool_names") or []):
            clean = _safe_text(tool_name, "")
            if clean and clean not in tool_names:
                tool_names.append(clean)
    tool_calls = [{"tool": tool_name, "arguments": {}, "decision_source": "task_runtime"} for tool_name in tool_names]
    primary_call = tool_calls[0] if tool_calls else None
    status = _safe_text(state.get("status"), "failed" if not result.success else "complete")
    completed_count = len(steps)
    pending_count = len(pending)
    final_answer = _safe_text(data.get("answer") or (state.get("active_entities") or {}).get("final_answer"), "")
    conversation_context = (
        dict(data.get("conversation_context") or {})
        if isinstance(data.get("conversation_context"), dict)
        else {}
    )
    if not conversation_context:
        for step in reversed(steps):
            result_data = (
                dict(step.get("result_data") or {})
                if isinstance(step.get("result_data"), dict)
                else {}
            )
            step_context = result_data.get("conversation_context")
            if isinstance(step_context, dict) and step_context:
                conversation_context = dict(step_context)
                break
    if not conversation_context:
        # Backward-compatible context for task states created before task steps
        # persisted the direct agent context.  Keep only scalar facts: copying a
        # complete tool payload here could leak customer/order data into later
        # prompts.
        for step in reversed(steps):
            result_data = (
                dict(step.get("result_data") or {})
                if isinstance(step.get("result_data"), dict)
                else {}
            )
            tool_result = result_data.get("tool_result")
            if not isinstance(tool_result, dict):
                continue
            scalar_facts = {
                key: value
                for key in ("count", "total_count", "item_count", "risk_count", "total")
                for value in [tool_result.get(key)]
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            if not scalar_facts:
                continue
            step_tools = [
                _safe_text(value, "")
                for value in list(step.get("tool_names") or [])
                if _safe_text(value, "")
            ]
            conversation_context = {
                "kind": "scalar_tool_result",
                "active_domain": _safe_text(state.get("active_domain"), ""),
                "source_tool": step_tools[0] if step_tools else "",
                "scalar_facts": scalar_facts,
                "authoritative_answer": _safe_text(
                    result_data.get("answer") or step.get("result_message"),
                    "",
                ),
            }
            break
    if data.get("stale_approval") is True:
        answer = _safe_text(
            result.message,
            "Eski veya geçersiz action_id reddedildi; hiçbir işlem çalıştırılmadı.",
        )
    elif pending:
        first = pending[0]
        pending_text = _safe_text(
            first.get("summary") or first.get("title"),
            "Riskli islem hazirlandi.",
        )
        last_step_answer = ""
        if steps:
            result_data = steps[-1].get("result_data") if isinstance(steps[-1].get("result_data"), dict) else {}
            last_step_answer = _safe_text(
                (result_data or {}).get("answer") or steps[-1].get("result_message"),
                "",
            )
        pending_candidate = final_answer or last_step_answer
        leaks_internal_id = bool(
            re.search(
                r"\b(?:orders|returns|labels)\.[a-z_][a-z0-9_.]*\b",
                pending_candidate,
                flags=re.IGNORECASE,
            )
        )
        answer = (
            pending_candidate
            if pending_candidate and not leaks_internal_id
            else (
                f"Agent gorevi {completed_count} adim ilerledi. "
                f"Devam etmek icin onay gerekiyor: {pending_text}"
            )
        )
    elif status == "complete":
        answer = final_answer or f"Agent gorevi tamamlandi. {completed_count} adim calisti."
    else:
        answer = final_answer or (
            f"Agent gorevi {status} durumunda durdu. "
            f"{completed_count} adim calisti."
        )
    projected_mode = (
        "approval_required"
        if pending
        else (
            _safe_text(data.get("mode"), "task")
            if status != "complete"
            else "task"
        )
    )
    return {
        **data,
        "answer": answer,
        "mode": projected_mode,
        "approval_required": bool(pending),
        "action_proposal": pending[0] if pending else None,
        "action_proposals": pending,
        "tool_call": primary_call,
        "tool_calls": tool_calls,
        "tool_result": {"state": state, "completed_step_count": completed_count, "pending_action_count": pending_count},
        "tool_results": [],
        "progress_events": progress_events,
        "conversation_context": conversation_context,
        "state": state,
        "session_state": state,
        "state_path": state_path,
    }

def _safe_text(value: Any, default: str = "-") -> str:
    text = str(value or "").strip()
    return text or default


def _cloud_provider_sort_key(record: dict[str, Any]) -> tuple[int, int, str]:
    provider = _safe_text(record.get("provider_code"), "").casefold()
    try:
        model_rank = int(record.get("free_model_rank"))
    except (TypeError, ValueError):
        model_rank = 10_000
    provider_rank = 0 if provider == "gemini" else 1 if provider == "openrouter" else 2
    return (provider_rank, model_rank, _safe_text(record.get("label"), "").casefold())


def _ai_icon_path() -> str:
    preferred = os.path.join(ASSETS_DIR, "ai-icon-search.png")
    if os.path.exists(preferred):
        return preferred
    return os.path.join(ASSETS_DIR, "orderscout-logo.png")


def _model_display_name(record: dict[str, Any]) -> str:
    metadata = (
        dict(record.get("model_metadata") or {})
        if isinstance(record.get("model_metadata"), dict)
        else {}
    )
    cloud_name = _safe_text(metadata.get("name") or record.get("default_model"), "")
    if cloud_name and _safe_text(record.get("_source_kind"), "") in {"cloud_model", "cloud_provider"}:
        return cloud_name

    repo_id = _safe_text(record.get("repo_id"), "")
    raw_name = repo_id.rsplit("/", 1)[-1] if repo_id else _safe_text(record.get("filename"), "Seçili model")
    raw_name = re.sub(r"(?i)(?:[-_]?gguf|\.gguf)$", "", raw_name)
    raw_name = re.sub(r"(?i)[-_](?:q\d+(?:_[a-z0-9]+)+)$", "", raw_name)
    raw_name = re.sub(r"(?i)(?:[-_](?:it|instruct))$", "", raw_name)
    display_name = re.sub(r"[-_]+", " ", raw_name).strip()
    quantization = _safe_text(record.get("quantization"), "")
    return f"{display_name} · {quantization}" if quantization else display_name


class _ModelChoiceRow(QFrame):
    """Visual row shared by local models, cloud providers and cloud model choices."""

    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._payload = dict(payload or {})
        self._selected = False
        self.setObjectName("AiModelChoiceRow")
        source_kind = _safe_text(self._payload.get("_source_kind"), "local_model")
        self._source_kind = source_kind
        self.setProperty("rowKind", source_kind)
        self.setProperty("selected", False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title_label = QLabel(self._title())
        self.title_label.setObjectName("AiModelRowTitle")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel(self._meta())
        self.meta_label.setObjectName("AiModelRowMeta")
        self.meta_label.setWordWrap(True)
        text.addWidget(self.title_label)
        text.addWidget(self.meta_label)
        layout.addLayout(text, 1)

        self.indicator = QLabel(self._indicator_text())
        self.indicator.setObjectName("AiModelRowIndicator")
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(58 if source_kind != "local_model" else 66)

    def _title(self) -> str:
        if self._source_kind == "cloud_provider_header":
            return _safe_text(self._payload.get("label"), "Provider")
        return _model_display_name(self._payload)

    def _meta(self) -> str:
        if self._source_kind == "cloud_provider_header":
            provider_code = _safe_text(self._payload.get("provider_code"), "").casefold()
            return (
                "Bağlı · canlı ücretsiz katalog"
                if provider_code == "openrouter"
                else "Bağlı · ücretsiz modeller erişilebilir"
            )
        if self._source_kind == "cloud_model":
            metadata = dict(self._payload.get("model_metadata") or {})
            parts = ["Ücretsiz" if bool(metadata.get("is_free")) else "Ücretli"]
            capability = dict(metadata.get("capability_profile") or {})
            if capability.get("native_tool_calling_available"):
                parts.append("Tools")
            context = int(metadata.get("context_length") or 0)
            if context:
                parts.append(f"{max(1, context // 1024)}K context")
            rank = int(self._payload.get("free_model_rank") or 0)
            if bool(metadata.get("is_free")) and rank == 0:
                parts.insert(0, "Önerilen #1")
            return " · ".join(parts)
        size_text = _safe_text(self._payload.get("size_text"), "-")
        resource_plan = (
            dict(self._payload.get("resource_plan") or {})
            if isinstance(self._payload.get("resource_plan"), dict)
            else {}
        )
        context = int(resource_plan.get("num_ctx") or self._payload.get("num_ctx") or 0)
        context_text = f"{max(1, context // 1024)}K context" if context else "context otomatik"
        profile = _safe_text(resource_plan.get("profile"), "").casefold()
        runtime_text = {
            "gpu_auto": "GPU otomatik",
            "reasoning": "reasoning profili",
            "low_memory": "düşük bellek",
        }.get(profile, "runtime hazır")
        return f"llama.cpp · {size_text} · {context_text} · {runtime_text}"

    def _indicator_text(self) -> str:
        if self._source_kind == "cloud_provider_header":
            return "^"
        if self._source_kind == "local_model":
            resource_plan = (
                dict(self._payload.get("resource_plan") or {})
                if isinstance(self._payload.get("resource_plan"), dict)
                else {}
            )
            return "●  Sınırlı" if _safe_text(resource_plan.get("profile"), "").casefold() == "low_memory" else "●  Hazır"
        return "●" if self._selected else "○"

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self.indicator.setText(self._indicator_text())
        self.style().unpolish(self)
        self.style().polish(self)

    def set_collapsed(self, collapsed: bool) -> None:
        if self._source_kind == "cloud_provider_header":
            self.indicator.setText("v" if collapsed else "^")


class _AdvancedModelSettingsDialog(QDialog):
    """Conversation-scoped model controls; Model Hub intentionally owns none of these."""

    def __init__(
        self,
        parent: QWidget,
        *,
        record: dict[str, Any],
        is_local: bool,
        on_apply: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AiAdvancedModelPopup")
        self.setWindowTitle("Gelişmiş model ayarları")
        self.setWindowFlag(Qt.WindowType.Popup, True)
        self.setModal(False)
        self.setMinimumWidth(420)
        self.setMaximumWidth(440)
        self.setMinimumHeight(590 if is_local else 420)
        self._on_apply = on_apply
        self._record = dict(record or {})
        self._is_local = bool(is_local)
        model_metadata = (
            dict(self._record.get("model_metadata") or {})
            if isinstance(self._record.get("model_metadata"), dict)
            else {}
        )
        self._capability_profile = (
            dict(model_metadata.get("capability_profile") or {})
            if isinstance(model_metadata.get("capability_profile"), dict)
            else dict(self._record.get("capability_profile") or {})
            if isinstance(self._record.get("capability_profile"), dict)
            else {}
        )
        self.setStyleSheet(
            """
            QDialog#AiAdvancedModelPopup {
                background: #FFFFFF;
                border: 1px solid #BFDBFE;
                border-radius: 14px;
            }
            QDialog#AiAdvancedModelPopup QLabel#PopupTitle {
                color: #0F172A;
                font-size: 15px;
                font-weight: 900;
            }
            QDialog#AiAdvancedModelPopup QLabel#PopupHint,
            QDialog#AiAdvancedModelPopup QLabel#FieldKey {
                color: #64748B;
                font-size: 11px;
                font-weight: 700;
            }
            QDialog#AiAdvancedModelPopup QLineEdit,
            QDialog#AiAdvancedModelPopup QComboBox {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                min-height: 34px;
                padding: 3px 8px;
            }
            QDialog#AiAdvancedModelPopup QPushButton#Primary {
                background: #2563EB;
                color: #FFFFFF;
                border: 0;
                border-radius: 9px;
                min-height: 38px;
                padding: 0 14px;
                font-weight: 800;
            }
            QDialog#AiAdvancedModelPopup QPushButton#Secondary {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 9px;
                min-height: 38px;
                padding: 0 14px;
                font-weight: 800;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        model_name = _model_display_name(self._record)
        title = QLabel(f"{model_name} · Gelişmiş")
        title.setObjectName("PopupTitle")
        title.setWordWrap(True)
        root.addWidget(title)
        hint = QLabel("Yalnız bu sohbet ve modelin desteklediği ayarlar uygulanır.")
        hint.setObjectName("PopupHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._fields: dict[str, QLineEdit] = {}
        generation_rows = [
            ("num_ctx", "Context", self._record.get("num_ctx") or 8192),
            ("max_tokens", "Max output", self._record.get("max_tokens") or self._record.get("max_output_tokens") or 1024),
            ("temperature", "Temperature", self._record.get("temperature") if self._record.get("temperature") is not None else 0.2),
            ("top_p", "Top P", self._record.get("top_p") if self._record.get("top_p") is not None else 0.9),
            ("top_k", "Top K", self._record.get("top_k") or 40),
            ("repeat_penalty", "Repeat penalty", self._record.get("repeat_penalty") or 1.1),
        ]
        runtime_rows: list[tuple[str, str, Any]] = []
        if self._is_local:
            runtime_rows = [
                ("num_gpu", "GPU layers", self._record.get("num_gpu") or "auto"),
                ("num_thread", "Threads", self._record.get("num_thread") or "auto"),
                ("num_batch", "Batch size", self._record.get("num_batch") or 512),
                ("seed", "Seed", self._record.get("seed") or "random"),
            ]
        rows = [*generation_rows, *runtime_rows]
        self._default_values = {key: value for key, _label, value in rows}
        supported_settings = self._supported_setting_names([key for key, _label, _value in rows])
        self._unsupported_fields: list[str] = []

        def _add_settings_group(title_text: str, group_rows: list[tuple[str, str, Any]]) -> None:
            section = QLabel(title_text)
            section.setObjectName("FieldKey")
            root.addWidget(section)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            root.addLayout(grid)
            for index, (key, label_text, value) in enumerate(group_rows):
                column = index % 2
                row = (index // 2) * 2
                label = QLabel(label_text.upper())
                label.setObjectName("FieldKey")
                field = QLineEdit(str(value))
                field.setObjectName(f"AiAdvanced_{key}")
                if key not in supported_settings:
                    field.setEnabled(False)
                    field.setToolTip("Seçili model/provider bu ayarı desteklediğini bildirmiyor.")
                    field.setProperty("unsupported", True)
                    self._unsupported_fields.append(key)
                grid.addWidget(label, row, column)
                grid.addWidget(field, row + 1, column)
                self._fields[key] = field

        _add_settings_group("ÜRETİM", generation_rows)
        if runtime_rows:
            _add_settings_group("RUNTIME", runtime_rows)
        if self._unsupported_fields:
            unsupported_hint = QLabel(
                "Bu modelde desteklenmeyen ayarlar pasif: "
                + ", ".join(self._unsupported_fields)
            )
            unsupported_hint.setObjectName("PopupHint")
            unsupported_hint.setWordWrap(True)
            root.addWidget(unsupported_hint)

        buttons = QHBoxLayout()
        reset = QPushButton("Varsayılana dön")
        reset.setObjectName("Secondary")
        reset.clicked.connect(self._reset_defaults)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        cancel = QPushButton("Vazgeç")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.close)
        apply_button = QPushButton("Bu sohbete uygula")
        apply_button.setObjectName("Primary")
        apply_button.clicked.connect(self._apply)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_button)
        root.addLayout(buttons)

    def _supported_setting_names(self, known_settings: list[str]) -> set[str]:
        profile = dict(self._capability_profile or {})
        supported_raw = profile.get("supported_model_settings")
        if not isinstance(supported_raw, (list, tuple, set)):
            supported_raw = profile.get("supported_settings")
        unsupported_raw = profile.get("unsupported_model_settings")
        if not isinstance(unsupported_raw, (list, tuple, set)):
            unsupported_raw = profile.get("unsupported_settings")

        if isinstance(supported_raw, (list, tuple, set)):
            supported = {_safe_text(value, "").casefold() for value in supported_raw}
        else:
            supported = set(known_settings)
        if isinstance(unsupported_raw, (list, tuple, set)):
            supported.difference_update(
                _safe_text(value, "").casefold() for value in unsupported_raw
            )
        for key in known_settings:
            explicit_flag = profile.get(f"supports_{key}")
            if explicit_flag is False:
                supported.discard(key)
            elif explicit_flag is True:
                supported.add(key)
        return supported

    def _reset_defaults(self) -> None:
        for key, value in self._default_values.items():
            field = self._fields.get(key)
            if field is not None:
                field.setText(str(value))

    @staticmethod
    def _parsed_value(value: str) -> Any:
        clean = str(value or "").strip()
        if not clean:
            return None
        if clean.casefold() in {"auto", "automatic", "random", "rastgele"}:
            return clean.casefold()
        try:
            return float(clean) if "." in clean or "," in clean else int(clean)
        except ValueError:
            return clean

    def _apply(self) -> None:
        payload = {
            key: self._parsed_value(field.text())
            for key, field in self._fields.items()
            if field.isEnabled()
        }
        self._on_apply(payload)
        self.close()


class AITab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("AiRoot")

        self._models_worker: Optional[SyncWorker] = None
        self._model_hub_window: Optional[AIManagerDialog] = None
        self._splitter_guard = False
        self._left_stick_size = 430
        self._left_collapse_trigger = 390
        self._chat_message_count = 0
        self._chat_history: list[dict[str, Any]] = []
        self._conversation_state: dict[str, Any] = AgentSessionState(
            goal="OrderScout AI conversation",
            active_domain="orders",
        ).to_dict()
        self._chat_worker: Optional[SyncWorker] = None
        self._schedule_owner_id = "ai-ui-" + uuid4().hex
        self._schedule_last_error = ""
        self._task_control = None
        self._queued_guidance: list[str] = []
        self._action_worker: Optional[SyncWorker] = None
        self._providers_worker: Optional[SyncWorker] = None
        self._provider_catalog_worker: Optional[SyncWorker] = None
        self._cloud_price_filter = "free"
        self._cloud_model_groups: list[dict[str, Any]] = []
        self._cloud_collapsed_provider_keys: set[str] = set()
        self._last_selected_cloud_model_id = ""
        self._known_local_model_count: int | None = None
        self._known_provider_count: int | None = None
        self._advanced_dialog: Optional[_AdvancedModelSettingsDialog] = None
        self._models_bootstrapped = False
        self._resource_plan_cache: dict[str, Any] = {}
        self._chat_progress_timer: Optional[QTimer] = None
        self._chat_progress_value = 0
        self._chat_progress_started_at = 0.0
        self._chat_progress_estimated_seconds = 0.0
        self._chat_progress_overrun = False
        self._last_task_progress_message = ""
        self._last_chat_success = True
        self._agent_state: dict[str, Any] = {}
        self._approval_card_sequence = 0
        self._approval_card_actions: dict[str, dict[str, Any]] = {}
        self._latest_approval_card_token = ""
        self._superseded_actions: list[dict[str, Any]] = []
        self._delivered_artifacts: dict[str, dict[str, Any]] = {}
        self._task_session_rows: list[dict[str, Any]] = []
        self._restored_task_session_ids: set[str] = set()
        self._task_history_visible = False
        self._is_disposing = False
        self._auto_switched_to_cloud = False

        self.setStyleSheet(
            """
            QWidget#AiRoot {
                background: #F3F6FB;
            }
            QFrame#SectionCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 14px;
            }
            QFrame#QuickCard {
                background: #F8FAFC;
                border-radius: 14px;
                border: 1px dashed #E2E8F0;
            }
            QLabel#SectionTitle {
                font-size: 15px;
                font-weight: 800;
                color: #111827;
            }
            QLabel#Muted {
                font-size: 12px;
                color: #6B7280;
            }
            QLabel#AiEyebrow {
                color: #64748B;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#StatusInfo {
                font-size: 11px;
                color: #475569;
            }
            QFrame#AiControlBand {
                background: #FFFFFF;
                border: 1px solid #DDE7F4;
                border-radius: 16px;
            }
            QLabel#AiControlTitle {
                font-size: 18px;
                font-weight: 900;
                color: #07111F;
            }
            QLabel#AiActivePill {
                background: rgba(34, 197, 94, 0.12);
                border: 1px solid rgba(34, 197, 94, 0.34);
                border-radius: 14px;
                padding: 6px 12px;
                color: #15803D;
                font-weight: 900;
            }
            QLabel#AiStatPill {
                background: rgba(15, 23, 42, 0.06);
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 12px;
                padding: 4px 10px;
                color: #0F172A;
                font-weight: 700;
            }
            QListWidget#ModelList {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
                padding: 5px;
            }
            QListWidget#ModelList::item {
                padding: 0;
                margin: 3px 2px;
                background: transparent;
                border: 0;
            }
            QListWidget#ModelList::item:selected {
                background: transparent;
                border: 0;
                color: #0F172A;
            }
            QFrame#AiModelChoiceRow {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 11px;
            }
            QFrame#AiModelChoiceRow[rowKind="cloud_provider_header"] {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 11px;
            }
            QFrame#AiModelChoiceRow[rowKind="cloud_model"] {
                background: #FFFFFF;
                border: 1px solid #EEF2F7;
                border-radius: 8px;
            }
            QFrame#AiModelChoiceRow[rowKind="cloud_model"][selected="true"] {
                background: #EFF6FF;
                border: 1px solid #93C5FD;
                border-left: 4px solid #2563EB;
            }
            QFrame#AiModelChoiceRow[rowKind="local_model"][selected="true"] {
                background: #EFF6FF;
                border: 1px solid #93C5FD;
                border-left: 4px solid #2563EB;
            }
            QLabel#AiModelRowTitle {
                color: #0F172A;
                font-size: 12px;
                font-weight: 800;
            }
            QLabel#AiModelRowMeta {
                color: #64748B;
                font-size: 10px;
            }
            QLabel#AiModelRowIndicator {
                color: #2563EB;
                font-size: 12px;
                font-weight: 900;
            }
            QFrame#AiModelChoiceRow[rowKind="local_model"] QLabel#AiModelRowIndicator {
                color: #16A34A;
                font-size: 10px;
            }
            QPushButton#AiSegment {
                background: transparent;
                color: #64748B;
                border: 1px solid transparent;
                border-radius: 10px;
                min-height: 34px;
                padding: 0 12px;
                font-weight: 800;
            }
            QPushButton#AiSegment[segmentKind="source"] {
                min-height: 50px;
            }
            QPushButton#AiSegment:checked {
                background: #FFFFFF;
                color: #1D4ED8;
                border: 1px solid #93C5FD;
            }
            QFrame#AiSegmentShell {
                background: #EFF3F8;
                border: 0;
                border-radius: 12px;
            }
            QFrame#AiChatSurface {
                background: #FFFFFF;
                border: 0;
                border-top: 1px solid #E5E7EB;
                border-radius: 0;
            }
            QFrame#AiRunProgress {
                background: #EEF6FF;
                border: 1px solid rgba(37, 99, 235, 0.16);
                border-radius: 6px;
            }
            QFrame#AiTaskState {
                background: #F8FAFC;
                border: 1px solid rgba(148, 163, 184, 0.32);
                border-radius: 6px;
            }
            QLabel#AiRunProgressLabel {
                color: #0F172A;
                font-size: 12px;
                font-weight: 800;
            }
            QLabel#AiRunProgressPercent {
                color: #2563EB;
                font-size: 12px;
                font-weight: 900;
            }
            QLabel#AiTaskStateTitle {
                color: #0F172A;
                font-size: 11px;
                font-weight: 900;
            }
            QLabel#AiTaskStateText {
                color: #475569;
                font-size: 11px;
            }
            QLabel#AiTaskStatePending {
                color: #9A3412;
                font-size: 11px;
                font-weight: 800;
            }
            QProgressBar#AiResponseProgress {
                background: #E2E8F0;
                border: none;
                border-radius: 6px;
                min-height: 8px;
                max-height: 8px;
            }
            QProgressBar#AiResponseProgress::chunk {
                background: #2563EB;
                border-radius: 6px;
            }
            QTextEdit#AiTranscript, QTextBrowser#AiTranscript {
                background: #FFFFFF;
                border: none;
                color: #0F172A;
                padding: 24px 34px;
                font-size: 13px;
            }
            QFrame#AiComposerShell {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 15px;
            }
            QTextEdit, QComboBox {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 14px;
                padding: 8px 10px;
                color: #0F172A;
            }
            QTextEdit#AiComposer {
                border: none;
                background: transparent;
                font-size: 13px;
                padding: 4px 6px;
            }
            QPushButton#AiSecondary {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 10px;
                padding: 8px 13px;
                font-weight: 700;
            }
            QPushButton#AiLaunchButton {
                background: #2563EB;
                color: #F8FAFC;
                border: none;
                border-radius: 14px;
                padding: 0 18px;
                font-size: 14px;
                font-weight: 800;
                min-height: 48px;
            }
            QPushButton#AiChip {
                background: #FFFFFF;
                color: #334155;
                border: 1px solid rgba(148, 163, 184, 0.28);
                border-radius: 16px;
                padding: 0 16px;
                min-height: 34px;
                font-weight: 700;
            }
            QPushButton#AiComposerIcon {
                background: #F8FAFC;
                color: #0F172A;
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 6px;
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                font-size: 20px;
                font-weight: 700;
            }
            QPushButton#AiSendButton {
                background: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                min-width: 42px;
                min-height: 36px;
                padding: 0 12px;
                font-weight: 800;
            }
            QPushButton#AiSendButton:disabled {
                background: #94A3B8;
                color: #E2E8F0;
            }
            QComboBox#AiTaskSessionCombo {
                border-radius: 6px;
                min-height: 34px;
                padding: 6px 10px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        root.addWidget(self._build_control_band())

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        root.addLayout(content_row, 1)

        self._panel_sidebar = SplitPanelSidebar(self, sidebar_width=80)
        self._panel_sidebar.add_panel_button(
            "models",
            "",
            tooltip=AI_CHAT_MODEL_PANEL_TOOLTIP,
            icon_path=str(_ai_icon_path()),
            shape="circular",
            icon_scale=1.28,
        )
        self._panel_sidebar.panel_toggled.connect(self._on_panel_sidebar_toggled)
        content_row.addWidget(self._panel_sidebar)

        self._tab_splitter = ResettableSplitter(Qt.Orientation.Horizontal)
        self._tab_splitter.setChildrenCollapsible(True)
        self._tab_splitter.setHandleWidth(6)
        self._tab_splitter.setCollapsible(0, True)
        self._tab_splitter.setCollapsible(1, False)
        self._tab_splitter.splitterMoved.connect(self._on_tab_splitter_moved)
        content_row.addWidget(self._tab_splitter, 1)

        left_scroll = QScrollArea(self)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(self._build_left_panel())
        self._tab_splitter.addWidget(left_scroll)
        self._tab_splitter.addWidget(self._build_chat_panel())
        self._tab_splitter.setSizes([430, 1210])

        self._sync_model_panel_mode()
        self._refresh_chat_surface()
        self._update_chat_controls()
        self._sync_sidebar_state_from_splitter()
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(30_000)
        self._schedule_timer.timeout.connect(self._poll_scheduled_workflows)
        self._schedule_timer.start()

    def _build_control_band(self) -> QWidget:
        band = QFrame(self)
        band.setObjectName("AiControlBand")
        band.setMaximumHeight(78)
        layout = QHBoxLayout(band)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        title = QLabel("OrderScout AI")
        title.setObjectName("AiControlTitle")
        subtitle = QLabel(
            "Model seçimi ve çalışma ayarları sohbetin içinde; Model Hub yalnız bağlantı ve indirme içindir."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col, 1)

        right = QHBoxLayout()
        right.setSpacing(8)
        self.resource_summary = QLabel("Kaynaklar hazır")
        status = self.resource_summary
        status.setObjectName("AiActivePill")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Model Hub · API & İndir")
        btn.setObjectName("AiLaunchButton")
        btn.clicked.connect(self._open_model_hub)
        right.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(right)
        return band

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._models_bootstrapped:
            return
        self._models_bootstrapped = True
        QTimer.singleShot(0, self._refresh_current_source)

    def _build_left_panel(self) -> QWidget:
        host = QWidget(self)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = QFrame(host)
        card.setObjectName("SectionCard")
        panel = QVBoxLayout(card)
        self._model_panel_layout = panel
        panel.setContentsMargins(16, 16, 16, 14)
        panel.setSpacing(12)
        panel.addWidget(QLabel("Model seçimi", objectName="SectionTitle"))
        intro_text = QLabel(
            "Kaynağı seç, modeli aç ve bu sohbet için çalışma zekâsını ayarla.",
            objectName="Muted",
        )
        intro_text.setWordWrap(True)
        panel.addWidget(intro_text)

        panel.addWidget(QLabel("KAYNAK", objectName="AiEyebrow"))
        source_shell = QFrame(card)
        source_shell.setObjectName("AiSegmentShell")
        source_layout = QHBoxLayout(source_shell)
        source_layout.setContentsMargins(6, 6, 6, 6)
        source_layout.setSpacing(6)
        self.source_button_group = QButtonGroup(self)
        self.source_button_group.setExclusive(True)
        self.btn_source_local = QPushButton("◉  Yerel")
        self.btn_source_cloud = QPushButton("☁  Cloud")
        for button, value in (
            (self.btn_source_local, AI_CHAT_SOURCE_LOCAL_VALUE),
            (self.btn_source_cloud, AI_CHAT_SOURCE_CLOUD_VALUE),
        ):
            button.setObjectName("AiSegment")
            button.setProperty("segmentKind", "source")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, selected=value: self._set_source_from_segment(selected))
            self.source_button_group.addButton(button)
            source_layout.addWidget(button, 1)
        self.btn_source_local.setChecked(True)
        panel.addWidget(source_shell)

        self.source_combo = QComboBox(card)
        self.source_combo.addItem(AI_CHAT_SOURCE_LOCAL_TEXT, AI_CHAT_SOURCE_LOCAL_VALUE)
        self.source_combo.addItem(AI_CHAT_SOURCE_CLOUD_TEXT, AI_CHAT_SOURCE_CLOUD_VALUE)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.source_combo.hide()

        self.cloud_filter_shell = QFrame(card)
        self.cloud_filter_shell.setObjectName("AiSegmentShell")
        filter_layout = QHBoxLayout(self.cloud_filter_shell)
        filter_layout.setContentsMargins(4, 4, 4, 4)
        filter_layout.setSpacing(4)
        self.cloud_price_button_group = QButtonGroup(self)
        self.cloud_price_button_group.setExclusive(True)
        self.cloud_price_buttons: dict[str, QPushButton] = {}
        for key, text in (("free", "Ücretsiz"), ("paid", "Ücretli"), ("all", "Tümü")):
            button = QPushButton(text)
            button.setObjectName("AiSegment")
            button.setProperty("segmentKind", "filter")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, selected=key: self._set_cloud_price_filter(selected))
            self.cloud_price_button_group.addButton(button)
            self.cloud_price_buttons[key] = button
            filter_layout.addWidget(button, 1)
        self.cloud_price_buttons["free"].setChecked(True)
        self.cloud_filter_shell.hide()
        panel.addWidget(self.cloud_filter_shell)

        self.source_list_label = QLabel(AI_CHAT_LOCAL_MODELS_LABEL, objectName="Muted")
        panel.addWidget(self.source_list_label)
        self.source_list_label.hide()
        self.model_list = QListWidget()
        self.model_list.setObjectName("ModelList")
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model_list.itemSelectionChanged.connect(self._on_model_selection_changed)
        self.model_list.itemClicked.connect(self._on_model_list_item_clicked)
        self.model_list.setMinimumHeight(310)
        panel.addWidget(self.model_list, 1)

        self.model_status = QLabel(AI_CHAT_MODEL_LIST_WAITING)
        self.model_status.setObjectName("Muted")
        self.model_status.setWordWrap(True)
        panel.addWidget(self.model_status)
        self.model_status.hide()

        self.local_count_pill = QLabel(AI_CHAT_LOCAL_COUNT_TEMPLATE.format(count=0))
        self.local_count_pill.setObjectName("AiStatPill")
        self.active_source_pill = QLabel(AI_CHAT_SOURCE_PILL_LOCAL_TEXT)
        self.active_source_pill.setObjectName("AiStatPill")
        self.brain_label = QLabel(AI_CHAT_ACTIVE_BRAIN_TEXT)
        self.brain_label.setObjectName("AiStatPill")
        self.brain_label.setWordWrap(True)
        self.runner_status = QLabel(AI_CHAT_RUNNER_STATUS_TEXT)
        self.runner_status.setObjectName("Muted")
        self.runner_status.setWordWrap(True)

        self.btn_refresh_models = QPushButton(AI_CHAT_REFRESH_MODELS_TEXT)
        self.btn_refresh_models.setObjectName("AiSecondary")
        self.btn_refresh_models.clicked.connect(self._refresh_current_source)
        self.btn_refresh_models.hide()

        self.btn_open_model_hub = QPushButton(AI_CHAT_OPEN_HUB_TEXT)
        self.btn_open_model_hub.setObjectName("AiLaunchButton")
        self.btn_open_model_hub.clicked.connect(self._open_model_hub)
        self.btn_open_model_hub.hide()

        self.model_panel_filler = QWidget(card)
        self.model_panel_filler.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.model_panel_filler.hide()
        panel.addWidget(self.model_panel_filler, 1)

        divider = QFrame(card)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #E2E8F0;")
        panel.addWidget(divider)
        panel.addWidget(QLabel("BU SOHBETİN AYARI", objectName="AiEyebrow"))
        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)
        self.reasoning_combo = QComboBox(card)
        self.reasoning_combo.setObjectName("AiConversationReasoning")
        self.reasoning_combo.addItem("Zekâ: Otomatik", "auto")
        self.reasoning_combo.addItem("Zekâ: Düşük", "low")
        self.reasoning_combo.addItem("Zekâ: Orta", "medium")
        self.reasoning_combo.addItem("Zekâ: Yüksek", "high")
        self.reasoning_combo.currentIndexChanged.connect(self._apply_simple_model_settings)
        self.btn_advanced_model_settings = QPushButton("Gelişmiş ···")
        self.btn_advanced_model_settings.setObjectName("AiSecondary")
        self.btn_advanced_model_settings.clicked.connect(self._open_advanced_model_settings)
        settings_row.addWidget(self.reasoning_combo, 1)
        settings_row.addWidget(self.btn_advanced_model_settings, 1)
        panel.addLayout(settings_row)
        self.fallback_checkbox = QCheckBox(
            "Limit dolarsa aynı provider içindeki sıradaki uygun modele geç.",
            card,
        )
        self.fallback_checkbox.setChecked(True)
        self.fallback_checkbox.setObjectName("AiFallbackToggle")
        self.fallback_checkbox.toggled.connect(self._apply_simple_model_settings)
        panel.addWidget(self.fallback_checkbox)

        layout.addWidget(card)
        return host

    def _set_source_from_segment(self, source: str) -> None:
        index = self.source_combo.findData(source)
        if index >= 0 and index != self.source_combo.currentIndex():
            self.source_combo.setCurrentIndex(index)
        else:
            self._sync_model_panel_mode()

    def _update_resource_summary(self) -> None:
        if not hasattr(self, "resource_summary"):
            return
        parts: list[str] = []
        if self._known_provider_count is not None:
            parts.append(f"{self._known_provider_count} provider bağlı")
        if self._known_local_model_count is not None:
            parts.append(f"{self._known_local_model_count} yerel model")
        self.resource_summary.setText(" · ".join(parts) if parts else "Kaynaklar hazır")

    def _sync_model_panel_mode(self) -> None:
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        is_local = source == AI_CHAT_SOURCE_LOCAL_VALUE
        self.btn_source_local.setChecked(is_local)
        self.btn_source_cloud.setChecked(not is_local)
        self.cloud_filter_shell.setVisible(not is_local)
        self.fallback_checkbox.setVisible(not is_local)
        self.model_list.setMinimumHeight(240 if is_local else 310)
        self.model_list.setMaximumHeight(260 if is_local else 16_777_215)
        if hasattr(self, "_model_panel_layout"):
            self._model_panel_layout.setStretchFactor(self.model_list, 0 if is_local else 1)
        if hasattr(self, "model_panel_filler"):
            self.model_panel_filler.setVisible(True)
            self.model_panel_filler.setMinimumHeight(0 if is_local else 24)
            self.model_panel_filler.setMaximumHeight(16_777_215 if is_local else 24)
            self.model_panel_filler.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Expanding if is_local else QSizePolicy.Policy.Fixed,
            )

    def _set_cloud_price_filter(self, price_filter: str) -> None:
        clean = price_filter if price_filter in {"free", "paid", "all"} else "free"
        self._cloud_price_filter = clean
        for key, button in self.cloud_price_buttons.items():
            button.setChecked(key == clean)
        if str(self.source_combo.currentData() or "") == AI_CHAT_SOURCE_CLOUD_VALUE:
            self._refresh_current_source()

    def _apply_simple_model_settings(self, *_args) -> None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict):
            return
        source_kind = _safe_text(payload.get("_source_kind"), "")
        if source_kind not in {"local_model", "cloud_provider", "cloud_model"}:
            return
        updated = dict(payload)
        updated["reasoning_effort"] = str(self.reasoning_combo.currentData() or "auto")
        updated["allow_model_fallback"] = bool(self.fallback_checkbox.isChecked())
        item.setData(Qt.ItemDataRole.UserRole, updated)
        self._resource_plan_cache.clear()
        self._update_chat_controls()

    def _open_advanced_model_settings(self) -> None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict):
            self.model_status.setText("Önce bu sohbet için bir model seç.")
            return
        source_kind = _safe_text(payload.get("_source_kind"), "")
        if source_kind not in {"local_model", "cloud_provider", "cloud_model"}:
            self.model_status.setText("Provider başlığı değil, provider altındaki modeli seç.")
            return
        if self._advanced_dialog is not None:
            self._advanced_dialog.close()
        self._advanced_dialog = _AdvancedModelSettingsDialog(
            self,
            record=dict(payload),
            is_local=source_kind == "local_model",
            on_apply=lambda values, target=item: self._apply_advanced_model_settings(target, values),
        )
        splitter_sizes = self._tab_splitter.sizes()
        left_width = splitter_sizes[0] if splitter_sizes else self._left_stick_size
        anchor = self._tab_splitter.mapToGlobal(QPoint(left_width + 8, 96))
        self._advanced_dialog.move(max(0, anchor.x()), max(0, anchor.y()))
        self._advanced_dialog.finished.connect(lambda *_: setattr(self, "_advanced_dialog", None))
        self._advanced_dialog.show()

    def _apply_advanced_model_settings(
        self,
        item: QListWidgetItem,
        values: dict[str, Any],
    ) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        updated = {**payload, **{key: value for key, value in values.items() if value is not None}}
        updated["reasoning_effort"] = str(self.reasoning_combo.currentData() or "auto")
        updated["allow_model_fallback"] = bool(self.fallback_checkbox.isChecked())
        item.setData(Qt.ItemDataRole.UserRole, updated)
        self._resource_plan_cache.clear()
        self.model_status.setText("Gelişmiş ayarlar yalnız bu sohbete uygulandı.")
        self._update_chat_controls()

    def _build_chat_panel(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("SectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_frame = QFrame(card)
        header_frame.setObjectName("AiChatHeader")
        header_frame.setFixedHeight(74)
        header = QHBoxLayout()
        header.setContentsMargins(20, 12, 20, 12)
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title = QLabel("Sohbet", objectName="SectionTitle")
        hint = QLabel(
            "Sipariş, stok, ilan, pazaryeri, finans ve lojistik bağlamı hazır.",
            objectName="Muted",
        )
        hint.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(hint)
        header.addLayout(title_col, 1)

        self.chat_status = QLabel(AI_CHAT_STATUS_WAITING)
        self.chat_status.setObjectName("AiStatPill")
        header.addWidget(self.chat_status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_new_chat = QPushButton(AI_CHAT_NEW_CHAT_BUTTON_TEXT)
        self.btn_new_chat.setObjectName("AiSecondary")
        self.btn_new_chat.clicked.connect(self._reset_chat)
        header.addWidget(self.btn_new_chat, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_saved_tasks = QPushButton("Çalışmalar")
        self.btn_saved_tasks.setObjectName("AiSecondary")
        self.btn_saved_tasks.clicked.connect(self._toggle_task_history)
        header.addWidget(self.btn_saved_tasks, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_saved_workflows = QPushButton("Yönergeler")
        self.btn_saved_workflows.setObjectName("AiSecondary")
        self.btn_saved_workflows.clicked.connect(self._open_saved_workflows)
        header.addWidget(self.btn_saved_workflows, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_workflow_schedules = QPushButton("Planlar")
        self.btn_workflow_schedules.setObjectName("AiSecondary")
        self.btn_workflow_schedules.clicked.connect(self._open_workflow_schedules)
        header.addWidget(self.btn_workflow_schedules, 0, Qt.AlignmentFlag.AlignVCenter)
        header_frame.setLayout(header)
        layout.addWidget(header_frame)

        surface = QFrame(self)
        surface.setObjectName("AiChatSurface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(20, 18, 20, 20)
        surface_layout.setSpacing(10)

        self.task_session_bar = QFrame(surface)
        self.task_session_bar.setObjectName("AiTaskSessionBar")
        top_meta = QHBoxLayout(self.task_session_bar)
        top_meta.setContentsMargins(8, 6, 8, 6)
        top_meta.setSpacing(8)
        self.active_brain_badge = QLabel(AI_CHAT_BRAIN_UNSELECTED)
        self.active_brain_badge.setObjectName("AiStatPill")
        self.session_hint_badge = QLabel(AI_CHAT_SESSION_READY)
        self.session_hint_badge.setObjectName("AiStatPill")
        top_meta.addWidget(self.active_brain_badge, 0, Qt.AlignmentFlag.AlignLeft)
        top_meta.addWidget(self.session_hint_badge, 0, Qt.AlignmentFlag.AlignLeft)
        self.task_session_combo = QComboBox(surface)
        self.task_session_combo.setObjectName("AiTaskSessionCombo")
        self.task_session_combo.setMinimumWidth(170)
        self.task_session_combo.setMaximumWidth(260)
        self.task_session_combo.currentIndexChanged.connect(self._sync_task_session_controls)
        top_meta.addWidget(self.task_session_combo, 0, Qt.AlignmentFlag.AlignLeft)
        self.btn_refresh_task_sessions = QPushButton("Yenile")
        self.btn_refresh_task_sessions.setObjectName("AiSecondary")
        self.btn_refresh_task_sessions.clicked.connect(self._refresh_task_sessions)
        top_meta.addWidget(self.btn_refresh_task_sessions, 0, Qt.AlignmentFlag.AlignLeft)
        self.btn_load_task_session = QPushButton("Sohbete aç")
        self.btn_load_task_session.setObjectName("AiSecondary")
        self.btn_load_task_session.clicked.connect(self._load_selected_task_session)
        top_meta.addWidget(self.btn_load_task_session, 0, Qt.AlignmentFlag.AlignLeft)
        top_meta.addStretch(1)
        self.task_session_bar.hide()
        surface_layout.addWidget(self.task_session_bar)

        self.chat_progress_shell = QFrame(surface)
        self.chat_progress_shell.setObjectName("AiRunProgress")
        self.chat_progress_shell.setMaximumHeight(56)
        progress_layout = QVBoxLayout(self.chat_progress_shell)
        progress_layout.setContentsMargins(12, 10, 12, 10)
        progress_layout.setSpacing(8)
        progress_top = QHBoxLayout()
        progress_top.setSpacing(8)
        self.chat_progress_label = QLabel("Hazir")
        self.chat_progress_label.setObjectName("AiRunProgressLabel")
        self.chat_progress_percent = QLabel("0%")
        self.chat_progress_percent.setObjectName("AiRunProgressPercent")
        progress_top.addWidget(self.chat_progress_label, 1)
        progress_top.addWidget(self.chat_progress_percent)
        progress_layout.addLayout(progress_top)
        self.chat_progress = QProgressBar()
        self.chat_progress.setObjectName("AiResponseProgress")
        self.chat_progress.setMinimum(0)
        self.chat_progress.setMaximum(100)
        self.chat_progress.setTextVisible(False)
        self.chat_progress.setValue(0)
        progress_layout.addWidget(self.chat_progress)
        self.chat_progress_shell.hide()
        surface_layout.addWidget(self.chat_progress_shell)

        self.agent_state_card = QFrame(surface)
        self.agent_state_card.setObjectName("AiTaskState")
        self.agent_state_card.setMaximumHeight(78)
        state_layout = QVBoxLayout(self.agent_state_card)
        state_layout.setContentsMargins(12, 9, 12, 9)
        state_layout.setSpacing(4)
        self.agent_state_title = QLabel("Ajan gorevi")
        self.agent_state_title.setObjectName("AiTaskStateTitle")
        self.agent_state_text = QLabel("")
        self.agent_state_text.setObjectName("AiTaskStateText")
        self.agent_state_text.setWordWrap(True)
        self.agent_state_pending = QLabel("")
        self.agent_state_pending.setObjectName("AiTaskStatePending")
        self.agent_state_pending.setWordWrap(True)
        self.agent_state_history = QLabel("")
        self.agent_state_history.setObjectName("AiTaskStateHistory")
        self.agent_state_history.setWordWrap(True)
        state_layout.addWidget(self.agent_state_title)
        state_layout.addWidget(self.agent_state_text)
        state_layout.addWidget(self.agent_state_pending)
        state_layout.addWidget(self.agent_state_history)
        self.agent_state_card.hide()
        surface_layout.addWidget(self.agent_state_card)

        self.chat_stack_host = QWidget(surface)
        self.chat_stack = QStackedLayout(self.chat_stack_host)
        self.chat_stack.setContentsMargins(0, 0, 0, 0)

        welcome_page = QWidget(surface)
        welcome_layout = QVBoxLayout(welcome_page)
        welcome_layout.setContentsMargins(22, 18, 22, 18)
        welcome_layout.setSpacing(8)
        welcome_layout.addStretch(1)

        self.welcome_title = QLabel("OrderScout AI'a ne soralım?")
        self.welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #0F172A;")
        self.welcome_title.setWordWrap(True)

        self.welcome_subtitle = QLabel("Programın tüm sekmeleri bağlamda. Modelini seç, sonra tek sohbetten devam et.")
        self.welcome_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_subtitle.setObjectName("Muted")
        self.welcome_subtitle.setWordWrap(True)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        chips_row.addStretch(1)
        for text in (
            "Son siparişleri özetle",
            "Stok risklerini çıkar",
            "İlanları kontrol et",
            "Finans durumunu açıkla",
        ):
            btn = QPushButton(text)
            btn.setObjectName("AiChip")
            btn.clicked.connect(lambda _=False, value=text: self._apply_suggestion(value))
            chips_row.addWidget(btn)
        chips_row.addStretch(1)

        welcome_layout.addWidget(self.welcome_title)
        welcome_layout.addWidget(self.welcome_subtitle)
        welcome_layout.addLayout(chips_row)
        welcome_layout.addStretch(1)

        transcript_page = QWidget(surface)
        transcript_layout = QVBoxLayout(transcript_page)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        transcript_layout.setSpacing(0)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("AiTranscript")
        self.transcript.setReadOnly(True)
        self.transcript.setOpenLinks(False)
        self.transcript.setOpenExternalLinks(False)
        self.transcript.anchorClicked.connect(self._on_transcript_anchor_clicked)
        transcript_layout.addWidget(self.transcript)

        self.chat_stack.addWidget(welcome_page)
        self.chat_stack.addWidget(transcript_page)
        surface_layout.addWidget(self.chat_stack_host, 1)

        composer_card = QFrame(surface)
        composer_card.setObjectName("AiComposerShell")
        composer_card.setFixedHeight(128)
        composer_layout = QVBoxLayout(composer_card)
        composer_layout.setContentsMargins(18, 14, 18, 14)
        composer_layout.setSpacing(8)

        self.composer = QTextEdit()
        self.composer.setObjectName("AiComposer")
        self.composer.setPlaceholderText("OrderScout AI'a mesaj yaz...")
        self.composer.setMinimumHeight(42)
        self.composer.setMaximumHeight(62)
        self.composer.textChanged.connect(self._update_chat_controls)
        composer_layout.addWidget(self.composer)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.btn_attach = QPushButton(AI_CHAT_ATTACH_BUTTON_TEXT)
        self.btn_attach.setObjectName("AiComposerIcon")
        self.btn_attach.setToolTip("Bu sohbete dosya ekle")
        self.btn_attach.clicked.connect(self._attach_files)
        actions.addWidget(self.btn_attach, 0, Qt.AlignmentFlag.AlignVCenter)

        self.composer_meta = QLabel(AI_CHAT_BRAIN_UNSELECTED)
        self.composer_meta.setObjectName("StatusInfo")
        self.composer_meta.setWordWrap(True)
        actions.addWidget(self.composer_meta, 1)

        self.btn_pause_task = QPushButton("Duraklat")
        self.btn_pause_task.setObjectName("AiSecondary")
        self.btn_pause_task.setToolTip("Tamamlanan adımlar kaydedildikten sonra çalışmayı duraklat")
        self.btn_pause_task.clicked.connect(self._request_task_pause)
        self.btn_pause_task.hide()
        actions.addWidget(self.btn_pause_task)

        self.btn_send = QPushButton(AI_CHAT_SEND_BUTTON_TEXT)
        self.btn_send.setObjectName("AiSendButton")
        self.btn_send.clicked.connect(self._send_message)
        actions.addWidget(self.btn_send)

        composer_layout.addLayout(actions)
        surface_layout.addWidget(composer_card)
        layout.addWidget(surface, 1)
        self._refresh_task_sessions()
        return card

    def _apply_suggestion(self, text: str) -> None:
        self.composer.setPlainText(str(text or "").strip())
        self.composer.setFocus()
        cursor = self.composer.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.composer.setTextCursor(cursor)
        self._update_chat_controls()

    def _attach_files(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self, "Sohbete dosya ekle", "",
            "İncelenebilir dosyalar (*.xlsx *.csv *.tsv *.json *.txt *.md)",
        )
        if paths:
            self._import_chat_attachments(paths)

    def _import_chat_attachments(self, paths: list[str]) -> None:
        """A user selection authorizes only these immutable file imports."""
        from AI.processors.file_workspace import register_attachment

        state = AgentSessionState.from_dict(self._conversation_state)
        workspace = dict(state.active_entities.get("file_workspace") or {})
        workspace_session_id = str(workspace.get("session_id") or state.session_id)
        attachments = list(workspace.get("attachments") or [])
        imported, failed = [], []
        for path in paths:
            try:
                metadata = register_attachment(path, workspace_session_id)
                if not any(row.get("attachment_id") == metadata["attachment_id"] for row in attachments):
                    attachments.append(metadata)
                imported.append(metadata["name"])
            except (ValueError, OSError) as exc:
                failed.append(f"{Path(path).name}: {exc}")
        workspace.update({"session_id": workspace_session_id, "attachments": attachments})
        state.active_entities["file_workspace"] = workspace
        self._conversation_state = state.to_dict()
        if imported:
            self._append_chat_message("assistant", "Bu sohbete eklendi: " + ", ".join(imported) + ". Dosyalarla ne yapmamı istediğini yazabilirsin.")
        if failed:
            self._append_chat_message("assistant", "Eklenemeyen dosyalar:\n" + "\n".join(failed))
        self.btn_attach.setToolTip("Bu sohbete dosya ekle" + ("\n" + "\n".join(str(row.get("name", "")) for row in attachments) if attachments else ""))

    def _refresh_chat_surface(self) -> None:
        self.chat_stack.setCurrentIndex(1 if self._chat_message_count > 0 else 0)

    def _task_session_label(self, row: dict[str, Any]) -> str:
        session_id = _safe_text(row.get("session_id"), "")
        status = _safe_text(row.get("status"), "-")
        goal = _safe_text(row.get("goal"), "task")
        pending = int(row.get("pending_count") or 0)
        completed = int(row.get("completed_step_count") or 0)
        short_goal = goal[:42] + ("..." if len(goal) > 42 else "")
        label = "onay bekliyor" if pending else {"running": "yarım kaldı", "interrupted": "yarım kaldı", "paused": "duraklatıldı",
                                                  "complete": "tamamlandı", "failed": "tamamlanamadı", "cancelled": "iptal edildi"}.get(status, status)
        return f"{short_goal} — {label}, {completed} adım"

    def _toggle_task_history(self) -> None:
        self._task_history_visible = not self._task_history_visible
        self._refresh_task_sessions()

    def _current_workflow_scope_bindings(self) -> dict[str, list[Any]]:
        from AI.processors.tools import marketplaces_account_lookup
        from AI.processors.file_workspace import list_attachments
        bindings: dict[str, list[Any]] = {"account_id": [], "store_name": [], "environment": [], "attachment_id": []}
        accounts = marketplaces_account_lookup(db_name=DB_NAME, query="", limit=50)
        if accounts.success:
            for row in (accounts.data or {}).get("account_scopes") or []:
                for kind, key in (("account_id", "api_account_id"), ("store_name", "store_name"), ("environment", "environment")):
                    value = row.get(key)
                    if value not in (None, "") and value not in bindings[kind]:
                        bindings[kind].append(value)
        owner = (self._conversation_state.get("active_entities") or {}).get("file_workspace_session_id")
        if isinstance(owner, str) and owner:
            attachments = list_attachments(session_id=owner)
            if attachments.success:
                bindings["attachment_id"] = [row["attachment_id"] for row in (attachments.data or {}).get("attachments") or []]
        return bindings

    def _open_saved_workflows(self) -> None:
        if self._worker_is_running():
            return
        from AI.views.workflow_library import WorkflowLibraryDialog
        bindings = self._current_workflow_scope_bindings()
        dialog = WorkflowLibraryDialog(self, allowed_scope_bindings=bindings)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.run_request is None:
            return
        if getattr(dialog, "requested_mode", "run") == "schedule":
            self._open_workflow_schedules(request=dialog.run_request, allowed_scope_bindings=bindings)
        else:
            self._start_saved_workflow(dialog.run_request, allowed_scope_bindings=bindings)

    def _open_workflow_schedules(self, *, request: Any = None,
                                 allowed_scope_bindings: dict[str, Any] | None = None) -> None:
        if self._worker_is_running():
            return
        from AI.processors.workflow_scheduler import WorkflowScheduler
        from AI.views.workflow_schedule_dialog import WorkflowScheduleDialog
        bindings = allowed_scope_bindings if allowed_scope_bindings is not None else self._current_workflow_scope_bindings()
        dialog = WorkflowScheduleDialog(self, scheduler=WorkflowScheduler(), request=request, allowed_scope_bindings=bindings)
        dialog.exec()
        if dialog.saved:
            self._append_chat_activity("Plan kaydedildi; uygulama açıkken seçili model ile çalışacak.")

    def _poll_scheduled_workflows(self) -> None:
        if self._is_disposing or self._worker_is_running() or self.composer.toPlainText().strip():
            return
        from AI.processors.workflow_scheduler import WorkflowScheduler
        scheduler = WorkflowScheduler()
        try:
            schedules = scheduler.list_schedules()
            if not any(row["status"] == "active" for row in schedules):
                return
            for run in scheduler.list_runs():
                if run["status"] not in {"completed", "failed", "cancelled"}:
                    scheduler.reconcile_run(run["run_id"], session_loader=load_agent_task_state)
            state = AgentSessionState.from_dict(self._conversation_state)
            if state.active_pending_action_id or state.pending_actions or state.status in {"paused", "pending_approval", "awaiting_approval"}:
                return
            source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
            record = self._selected_local_record() if source == AI_CHAT_SOURCE_LOCAL_VALUE else self._selected_provider_record()
            if not record:
                return
            leases = scheduler.claim_due(owner_id=self._schedule_owner_id, max_runs=1)
            if leases:
                self._start_scheduled_workflow(leases[0], scheduler=scheduler, source=source, runtime_record=record,
                                               allowed_scope_bindings=self._current_workflow_scope_bindings())
            self._schedule_last_error = ""
        except Exception as exc:
            marker = type(exc).__name__
            if marker != self._schedule_last_error:
                self._append_chat_activity("Planlı çalışmanın kaydı kontrol edilmeli; Planlar bölümünü açabilirsin.")
                self._schedule_last_error = marker

    def _start_scheduled_workflow(self, lease: Any, *, scheduler: Any, source: str,
                                  runtime_record: dict[str, Any], allowed_scope_bindings: dict[str, Any]) -> None:
        from AI.processors.task_control import AgentTaskControl
        self._task_control = AgentTaskControl()
        self._append_chat_activity("Planlı yönerge başladı; güncel kaynaklar okunacak, işlemler için yeniden onay istenecek.")
        self._chat_worker = SyncWorker(
            _run_scheduled_chat_with_runtime, parent=self, progress_callback_kw="progress_callback",
            lease=lease, scheduler=scheduler, source=source, runtime_record=dict(runtime_record),
            current_session=dict(self._conversation_state), allowed_scope_bindings=allowed_scope_bindings,
            task_control=self._task_control,
        )
        self._start_chat_progress(self._estimate_chat_duration_seconds(source, None, "Planlı çalışma"))
        def done(result: Result) -> None:
            data = dict(result.data or {})
            state = data.get("session_state") or data.get("state")
            if isinstance(state, dict):
                self._conversation_state = dict(state)
                self._update_agent_state_from_result_data(data)
            answer = str(data.get("answer") or result.message)
            self._append_chat_message("assistant", answer)
            self._chat_history.append({"role": "assistant", "content": answer})
            if data.get("approval_required") and isinstance(data.get("action_proposal"), dict):
                self._show_action_approval_dialog(data["action_proposal"])
            self._last_chat_success = bool(result.success)
            self._refresh_task_sessions()
        def finished() -> None:
            self._chat_worker = None
            self._task_control = None
            self._finish_chat_progress(self._last_chat_success)
            self._update_chat_controls()
            if self._queued_guidance:
                QTimer.singleShot(0, self._run_queued_guidance)
        self._chat_worker.result_ready.connect(done)
        self._chat_worker.progress.connect(self._on_task_progress)
        self._chat_worker.finished.connect(finished)
        self._chat_worker.start()
        self._update_chat_controls()

    def _start_saved_workflow(self, request: Any, *, allowed_scope_bindings: dict[str, Any]) -> None:
        if self._worker_is_running():
            return
        from AI.processors.workflow_store import prepare_workflow_invocation
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        selected = self._selected_local_record() if source == AI_CHAT_SOURCE_LOCAL_VALUE else self._selected_provider_record()
        if not selected:
            self._append_chat_message("assistant", "Çalışmayı başlatmak için bir model seç.")
            return
        try:
            invocation = prepare_workflow_invocation(
                request.workflow_id, revision_id=request.revision_id, parameters=request.parameters,
                current_session=self._conversation_state, allowed_scope_bindings=allowed_scope_bindings,
                domain="general",
            )
            if invocation["revision"].spec.content_hash != request.spec_hash or invocation["goal"] != request.objective:
                raise ValueError("Seçilen yönerge değişti; yeniden gözden geçir.")
        except (ValueError, KeyError, OSError) as exc:
            self._append_chat_message("assistant", f"Çalışma başlatılamadı: {exc}")
            return
        self._conversation_state = invocation["session_state"]
        self._append_chat_activity("Kayıtlı yönergeyle yeni çalışma başlıyor; model güncel kaynakları okuyacak.")
        self._send_message(text_override=invocation["goal"], fresh_history=True)

    def _refresh_task_sessions(self) -> None:
        if not hasattr(self, "task_session_combo"):
            return
        current_session_id = ""
        current = self.task_session_combo.currentData()
        if isinstance(current, dict):
            current_session_id = _safe_text(current.get("session_id"), "")
        try:
            rows = list_agent_task_states(limit=20)
        except Exception as exc:
            rows = []
            if hasattr(self, "transcript"):
                self._append_chat_activity(f"Task session listesi okunamadi: {_safe_text(exc)}")
        self._task_session_rows = [dict(row) for row in rows if isinstance(row, dict)]
        if hasattr(self, "task_session_bar"):
            self.task_session_bar.setVisible(self._task_history_visible)
        self.task_session_combo.blockSignals(True)
        self.task_session_combo.clear()
        if not self._task_session_rows:
            self.task_session_combo.addItem("Kayıtlı çalışma yok", None)
        else:
            self.task_session_combo.addItem("Bir çalışma seç", None)
            selected_index = 0
            for row in self._task_session_rows:
                self.task_session_combo.addItem(self._task_session_label(row), row)
                if current_session_id and _safe_text(row.get("session_id"), "") == current_session_id:
                    selected_index = self.task_session_combo.count() - 1
            self.task_session_combo.setCurrentIndex(selected_index)
        self.task_session_combo.blockSignals(False)
        self._sync_task_session_controls()

    def _sync_task_session_controls(self) -> None:
        if hasattr(self, "btn_load_task_session") and hasattr(self, "task_session_combo"):
            self.btn_load_task_session.setEnabled(bool(self.task_session_combo.currentData()))

    def _load_selected_task_session(self) -> None:
        row = self.task_session_combo.currentData()
        if not isinstance(row, dict):
            self._append_chat_activity("Yuklenecek kayitli task session secilmedi.")
            return
        session_id = _safe_text(row.get("session_id"), "")
        if not session_id:
            self._append_chat_activity("Task session id bos.")
            return
        try:
            state = load_agent_task_state(session_id)
        except Exception as exc:
            self._append_chat_activity(f"Task session yuklenemedi: {_safe_text(exc)}")
            return
        restored = Result.ok(
            "Task session yuklendi.",
            close_dialog=False,
            data={"state": state.to_dict(), "state_path": _safe_text(row.get("path"), "")},
        )
        data = _chat_data_from_task_result(restored)
        self._update_agent_state_from_result_data(data)
        self._restore_task_chat_context(data)

    def _restore_task_chat_context(self, data: dict[str, Any]) -> None:
        state = dict(data.get("state") or {}) if isinstance(data.get("state"), dict) else {}
        session_id = _safe_text(state.get("session_id"), "")
        if not session_id or session_id in self._restored_task_session_ids:
            self._append_chat_activity("Kayitli gorev zaten bu sohbette yuklu.")
            return

        active_entities = (
            dict(state.get("active_entities") or {})
            if isinstance(state.get("active_entities"), dict)
            else {}
        )
        self._conversation_state = dict(state)
        recorded_history = state.get("conversation_turns") or active_entities.get("conversation_history") or []
        restored_history = [
            {
                "role": _safe_text(row.get("role"), ""),
                "content": _safe_text(row.get("content"), ""),
            }
            for row in list(recorded_history)
            if isinstance(row, dict)
            and _safe_text(row.get("role"), "") in {"user", "assistant"}
            and _safe_text(row.get("content"), "")
        ]
        goal = _safe_text(state.get("goal"), "")
        if goal and not any(
            row.get("role") == "user" and row.get("content") == goal
            for row in restored_history
        ):
            restored_history.append({"role": "user", "content": goal})

        existing = {
            (_safe_text(row.get("role"), ""), _safe_text(row.get("content"), ""))
            for row in self._chat_history
            if isinstance(row, dict)
        }
        for row in restored_history[-24:]:
            key = (row["role"], row["content"])
            if key in existing:
                continue
            self._append_chat_message(row["role"], row["content"])
            self._chat_history.append(dict(row))
            existing.add(key)

        answer = _safe_text(data.get("answer"), "")
        if answer and ("assistant", answer) not in existing:
            self._append_chat_message("assistant", answer)
            self._chat_history.append({"role": "assistant", "content": answer})

        action = data.get("action_proposal") if isinstance(data.get("action_proposal"), dict) else None
        if bool(data.get("approval_required")) and action:
            self._show_action_approval_dialog(action)
            self._append_chat_activity("Kayitli gorev onay bekleyen adimdan devam etmeye hazir.")
        else:
            self._append_chat_activity("Kayitli gorev baglami sohbete geri yuklendi.")
            if state.get("remaining_steps") and state.get("status") in {"running", "paused", "interrupted"}:
                control = active_entities.get("task_control") or {}
                guidance = [message for message in control.get("queued_user_messages") or []
                            if isinstance(message, str) and message.strip()]
                if control.get("reason") == "user_revision" and guidance:
                    for message in guidance:
                        if ("user", message) not in existing:
                            self._append_chat_message("user", message)
                            self._chat_history.append({"role": "user", "content": message})
                            existing.add(("user", message))
                    self.composer.setPlainText("\n".join(guidance))
                    self._append_chat_message("assistant", "Yarım kalan çalışma ve son talimatların açıldı. Yazı alanındaki talimatı göndererek güncellenmiş hedefle devam edebilirsin.")
                else:
                    self._append_chat_message("assistant", "Yarım kalan çalışma açıldı. ‘Devam et’ yazdığında kalan okuma adımlarını sürdürebilirim.")
        self._restored_task_session_ids.add(session_id)
        self._append_verified_artifact_links(data)
        self._update_chat_controls()

    def _format_chat_elapsed(self) -> str:
        if not self._chat_progress_started_at:
            return "0s"
        return f"{int(max(0.0, time.monotonic() - self._chat_progress_started_at))}s"

    def _worker_is_running(self) -> bool:
        for worker in (self._chat_worker, self._action_worker):
            if worker is not None and worker.isRunning():
                return True
        return False

    def _set_chat_progress(self, value: int, label: str | None = None, *, percent_text: str | None = None) -> None:
        if not hasattr(self, "chat_progress"):
            return
        clean_value = max(0, min(100, int(value or 0)))
        if self.chat_progress.minimum() != 0 or self.chat_progress.maximum() != 100:
            self.chat_progress.setRange(0, 100)
        self._chat_progress_value = clean_value
        self.chat_progress.setValue(clean_value)
        self.chat_progress_percent.setText(percent_text if percent_text is not None else f"{clean_value}%")
        if label:
            self.chat_progress_label.setText(str(label))
        self.chat_progress_shell.setVisible(clean_value > 0 or self._worker_is_running())

    def _estimate_chat_duration_seconds(self, source: str, planner_client: Any, prompt: str) -> float:
        plan = getattr(planner_client, "resource_plan", {}) if planner_client is not None else {}
        profile = str((plan or {}).get("profile") or "").casefold() if isinstance(plan, dict) else ""
        model_name = _safe_text(getattr(planner_client, "model_name", ""), "").casefold()
        prompt_factor = min(40.0, len(str(prompt or "")) / 20.0)
        if source == AI_CHAT_SOURCE_CLOUD_VALUE:
            return 22.0 + prompt_factor
        if "gpt-oss" in model_name or "disk_guarded" in profile:
            return 95.0 + prompt_factor
        if "large" in profile:
            return 65.0 + prompt_factor
        return 32.0 + prompt_factor

    def _start_chat_progress(self, estimated_seconds: float | None = None) -> None:
        if self._chat_progress_timer is None:
            self._chat_progress_timer = QTimer(self)
            self._chat_progress_timer.setInterval(700)
            self._chat_progress_timer.timeout.connect(self._advance_chat_progress)
        self._chat_progress_started_at = time.monotonic()
        self._chat_progress_estimated_seconds = max(8.0, float(estimated_seconds or 0.0))
        self._chat_progress_overrun = False
        self.chat_progress_shell.show()
        self._set_chat_progress(4, "Istek alindi", percent_text=f"4% | {self._format_chat_elapsed()}")
        self._chat_progress_timer.start()

    def _advance_chat_progress(self) -> None:
        if not self._worker_is_running():
            return
        elapsed = max(0.0, time.monotonic() - self._chat_progress_started_at)
        estimate = max(8.0, self._chat_progress_estimated_seconds)
        ratio = elapsed / estimate
        if ratio >= 1.0:
            if not self._chat_progress_overrun:
                self._chat_progress_overrun = True
                self.chat_progress.setRange(0, 0)
            self.chat_progress_percent.setText(self._format_chat_elapsed())
            self.chat_progress_label.setText("Model beklenenden uzun suruyor")
            self.chat_progress_shell.show()
            return
        value = int(4 + min(84.0, ratio * 84.0))
        if value < 24:
            label = "Tool plani hazirlaniyor"
        elif value < 58:
            label = "Model cevabi uretiyor"
        elif value < 78:
            label = "E-ticaret baglami isleniyor"
        else:
            label = "Cevap toparlaniyor"
        self._set_chat_progress(value, label, percent_text=f"{value}% | {self._format_chat_elapsed()}")

    def _finish_chat_progress(self, success: bool = True) -> None:
        if self._chat_progress_timer is not None:
            self._chat_progress_timer.stop()
        self._set_chat_progress(100, "Cevap hazir" if success else "Tamamlanamadi", percent_text=f"100% | {self._format_chat_elapsed()}")
        QTimer.singleShot(900, self._hide_chat_progress_if_idle)

    def _hide_chat_progress_if_idle(self) -> None:
        if self._worker_is_running():
            return
        self.chat_progress_shell.hide()
        self._chat_progress_started_at = 0.0
        self._chat_progress_estimated_seconds = 0.0
        self._chat_progress_overrun = False
        self._set_chat_progress(0, "Hazir", percent_text="0%")

    def _append_chat_message(self, role: str, message: str) -> None:
        role_name = AI_CHAT_USER_ROLE_TEXT if str(role).strip().lower() == "user" else AI_CHAT_ASSISTANT_ROLE_TEXT
        safe_message = html.escape(str(message or "").strip()).replace("\n", "<br>")
        if role_name == "Sen":
            block = (
                '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 18px 0;">'
                '<tr><td width="48%"></td><td align="right">'
                f'<div style="font-size:11px;color:#64748B;font-weight:800;margin-bottom:4px;">{role_name}</div>'
                '<table width="100%" cellspacing="0" cellpadding="14" bgcolor="#2563EB" '
                'style="background-color:#2563EB;border:1px solid #1D4ED8;color:#FFFFFF;">'
                f'<tr><td style="color:#FFFFFF;text-align:left;line-height:1.5;">{safe_message}</td></tr>'
                "</table></td></tr></table>"
            )
        else:
            icon_url = html.escape(QUrl.fromLocalFile(_ai_icon_path()).toString())
            block = (
                '<table width="78%" cellspacing="0" cellpadding="0" style="margin:0 0 18px 0;">'
                f'<tr><td width="46" valign="top"><img src="{icon_url}" width="36" height="36"></td>'
                '<td valign="top">'
                f'<div style="font-size:11px;color:#0F172A;font-weight:900;margin-bottom:5px;">{role_name}</div>'
                '<table width="100%" cellspacing="0" cellpadding="10" bgcolor="#FFFFFF" '
                'style="background-color:#FFFFFF;color:#0F172A;">'
                f'<tr><td style="color:#0F172A;line-height:1.55;">{safe_message}</td></tr>'
                "</table></td></tr></table>"
            )
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)
        self.transcript.insertHtml(block)
        self.transcript.insertPlainText("\n")
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _append_chat_activity(self, message: str) -> None:
        safe_message = html.escape(str(message or "").strip()).replace("\n", "<br>")
        if not safe_message:
            return
        block = (
            '<table width="78%" cellspacing="0" cellpadding="0" style="margin:0 0 10px 46px;">'
            '<tr><td><table width="100%" cellspacing="0" cellpadding="8" bgcolor="#EEF2F7" '
            'style="background-color:#EEF2F7;border:1px solid #E2E8F0;color:#475569;">'
            f'<tr><td style="color:#475569;font-size:11px;line-height:1.4;">{safe_message}</td></tr>'
            "</table></td></tr></table>"
        )
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)
        self.transcript.insertHtml(block)
        self.transcript.insertPlainText("\n")
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _append_verified_artifact_links(self, data: dict[str, Any]) -> None:
        """Deliver native files independently of model-authored filenames/paths."""
        from AI.processors.observation_context import verified_export_report_receipts
        raw_state = data.get("state") or data.get("session_state")
        if not isinstance(raw_state, dict):
            return
        receipts = verified_export_report_receipts(AgentSessionState.from_dict(raw_state))
        for receipt in receipts:
            token = hashlib.sha256((receipt["output_path"] + receipt["file_sha256"]).encode("utf-8")).hexdigest()
            if token in self._delivered_artifacts:
                continue
            self._delivered_artifacts[token] = dict(receipt)
            filename = html.escape(receipt["filename"])
            location = html.escape(receipt["output_path"])
            size_kb = receipt["size_bytes"] / 1024
            block = (
                '<table width="78%" cellpadding="10" style="margin:0 0 14px 46px;background:#F8FAFC;">'
                '<tr><td>'
                f'<a href="orderscout://artifact/open/{token}" style="color:#2563EB;font-weight:700;">'
                f'{filename} — dosyayı aç</a><br>'
                f'<span style="color:#64748B;">Excel · {receipt["sheet_count"]} sayfa · {size_kb:.1f} KB</span><br>'
                f'<span style="font-size:10px;color:#64748B;">{location}</span>'
                '</td></tr></table>'
            )
            self.transcript.moveCursor(QTextCursor.MoveOperation.End)
            self.transcript.insertHtml(block)
            self.transcript.insertPlainText("\n")
            self._chat_message_count += 1
        self._refresh_chat_surface()

    def _on_task_progress(self, percent: int, message: str) -> None:
        clean_message = _safe_text(message, "")
        if not clean_message:
            return
        clean_percent = max(4, min(96, int(percent or 0)))
        self._set_chat_progress(
            clean_percent,
            clean_message,
            percent_text=f"{clean_percent}% | {self._format_chat_elapsed()}",
        )
        if clean_message != self._last_task_progress_message:
            self._append_chat_activity(clean_message)
            self._last_task_progress_message = clean_message

    def _append_chat_approval_card(self, action: dict[str, Any]) -> None:
        self._approval_card_sequence += 1
        card_token = str(self._approval_card_sequence)
        self._approval_card_actions[card_token] = dict(action)
        self._latest_approval_card_token = card_token
        cancel_href = f"orderscout://approval/cancel/{card_token}"
        approve_href = f"orderscout://approval/approve/{card_token}"
        title, summary, details = self._approval_dialog_text(action)
        safe_title = html.escape(title)
        safe_summary = html.escape(summary)
        detail_lines = [
            html.escape(line).replace("  ", "&nbsp;&nbsp;")
            for line in str(details or "").splitlines()
            if line.strip()
        ]
        detail_limit = (
            100
            if _safe_text(action.get("action_type"), "")
            == "labels.action_create_labels_from_selected_orders"
            else 20
        )
        rows_html = "".join(
            f'<div style="padding:3px 0; color:#334155;">{line}</div>'
            for line in detail_lines[:detail_limit]
        )
        if not rows_html:
            rows_html = '<div style="color:#64748B;">Etkilenecek kayıt detayı bulunamadı.</div>'
        block = (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px 0;">'
            '<tr><td width="78%">'
            f'<div style="font-size:11px;color:#0F172A;font-weight:900;margin-bottom:5px;">{AI_CHAT_ASSISTANT_ROLE_TEXT}</div>'
            '<div style="padding:13px 14px;border-radius:8px;background:#FFFFFF;'
            'border:1px solid rgba(234,88,12,0.32);border-left:4px solid #EA580C;color:#0F172A;">'
            '<div style="font-size:11px;color:#C2410C;font-weight:900;margin-bottom:5px;">Onay gerekiyor</div>'
            f'<div style="font-size:14px;font-weight:900;margin-bottom:4px;">{safe_title}</div>'
            f'<div style="color:#475569;margin-bottom:10px;line-height:1.4;">{safe_summary}</div>'
            '<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
            f'border-radius:6px;padding:8px 10px;margin-bottom:10px;">{rows_html}</div>'
            '<div style="color:#9A3412;font-weight:800;margin-bottom:10px;">'
            'Onaydan önce gerçek API isteği, DB yazımı veya dosya/çıktı üretimi yapılmaz.'
            '</div>'
            '<div>'
            f'<a href="{cancel_href}" style="display:inline-block;padding:7px 11px;border-radius:6px;'
            'background:#FFFFFF;border:1px solid #CBD5E1;color:#0F172A;font-weight:800;'
            'text-decoration:none;">Vazgeç</a>'
            '&nbsp;'
            f'<a href="{approve_href}" style="display:inline-block;padding:7px 12px;border-radius:6px;'
            'background:#2563EB;border:1px solid #2563EB;color:#FFFFFF;font-weight:900;'
            'text-decoration:none;">Onayla ve çalıştır</a>'
            '</div>'
            '<div style="color:#64748B;font-size:11px;margin-top:8px;">'
            'Sohbetten “onayla”, “çalıştır” veya “vazgeç” yazarak da devam edebilirsin.'
            '</div>'
            '</div></td><td width="22%"></td></tr></table>'
        )
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)
        self.transcript.insertHtml(block)
        self.transcript.insertPlainText("\n")
        self.transcript.moveCursor(QTextCursor.MoveOperation.End)
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _on_transcript_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme().casefold() == "orderscout" and url.host().casefold() == "artifact":
            parts = [part for part in url.path().split("/") if part]
            receipt = self._delivered_artifacts.get(parts[1]) if len(parts) == 2 and parts[0] == "open" else None
            if not receipt:
                return
            path = Path(receipt["output_path"])
            if not path.is_file():
                self._append_chat_activity("Dosya bu konumda bulunamadı; taşınmış veya silinmiş olabilir.")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        if url.scheme().casefold() != "orderscout" or url.host().casefold() != "approval":
            return
        parts = [part for part in url.path().split("/") if part]
        if len(parts) != 2:
            return
        intent, card_token = parts
        if intent not in {"approve", "cancel"}:
            return
        if self._worker_is_running():
            self._append_chat_activity("Bir islem zaten calisiyor; tamamlaninca tekrar deneyebilirsin.")
            return
        card_action = self._approval_card_actions.get(card_token)
        pending_action = self._pending_action_from_state()
        if not card_action or not pending_action or not self._approval_actions_match(card_action, pending_action):
            self._append_chat_activity("Bu onay karti artik aktif degil.")
            return
        reply = "Onayla ve çalıştır" if intent == "approve" else "Vazgeç"
        self._append_chat_message("user", reply)
        self._chat_history.append({"role": "user", "content": reply})
        self._handle_pending_action_reply(reply)

    def _approval_actions_match(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        def _business_payload(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: _business_payload(item)
                    for key, item in value.items()
                    if not str(key).startswith("_agent_task_")
                }
            if isinstance(value, list):
                return [_business_payload(item) for item in value]
            if isinstance(value, tuple):
                return tuple(_business_payload(item) for item in value)
            return value

        return _business_payload(left) == _business_payload(right)

    def _tool_names_from_result_data(self, data: dict[str, Any]) -> list[str]:
        names: list[str] = []
        calls = data.get("tool_calls") if isinstance(data.get("tool_calls"), list) else []
        for call in calls:
            if isinstance(call, dict):
                name = _safe_text(call.get("tool"), "")
                if name and name not in names:
                    names.append(name)
        single = data.get("tool_call") if isinstance(data.get("tool_call"), dict) else {}
        single_name = _safe_text(single.get("tool"), "")
        if single_name and single_name not in names:
            names.append(single_name)
        return names

    def _pending_action_summary(self, action: dict[str, Any] | None) -> str:
        if not isinstance(action, dict) or not action:
            return ""
        title = _safe_text(action.get("title"), "")
        summary = _safe_text(action.get("summary"), "")
        action_type = _safe_text(action.get("action_type"), "")
        identifiers: list[str] = []

        def _collect(value: Any) -> None:
            if isinstance(value, dict):
                for key in ("order", "order_number", "claim_id", "claim"):
                    text = _safe_text(value.get(key), "")
                    if text and text not in identifiers:
                        identifiers.append(text)
                for key in ("orders", "order_numbers", "claim_ids"):
                    rows = value.get(key)
                    if isinstance(rows, (list, tuple)):
                        for row in rows:
                            text = _safe_text(row, "")
                            if text and text not in identifiers:
                                identifiers.append(text)
                payload = value.get("payload")
                if isinstance(payload, dict):
                    _collect(payload)
            elif isinstance(value, (list, tuple)):
                for row in value:
                    _collect(row)

        arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        _collect(arguments.get("payload") if isinstance(arguments, dict) else {})
        _collect(action.get("rows") if isinstance(action.get("rows"), list) else [])
        id_text = ", ".join(identifiers[:4])
        parts = [
            part
            for part in (
                title,
                summary,
                f"id={id_text}" if id_text else "",
                f"aksiyon={action_type}" if action_type else "",
            )
            if part
        ]
        return " | ".join(parts[:4])

    def _set_agent_state(
        self,
        *,
        status: str,
        detail: str = "",
        tools: list[str] | tuple[str, ...] | None = None,
        pending_action: dict[str, Any] | None = None,
        last_execute_message: str = "",
        action_history: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        clean_status = _safe_text(status, "idle").casefold()
        tool_names = [name for name in list(tools or []) if _safe_text(name, "")]
        pending_summary = self._pending_action_summary(pending_action)
        history_rows = [dict(row) for row in list(action_history or []) if isinstance(row, dict)]
        history_text = self._format_agent_action_history(history_rows)
        self._agent_state = {
            "status": clean_status,
            "detail": detail,
            "tools": tool_names,
            "pending_action": dict(pending_action or {}) if isinstance(pending_action, dict) else None,
            "last_execute_message": last_execute_message,
            "action_history": history_rows,
        }
        if clean_status in {"idle", "reset"} and not tool_names and not pending_summary and not last_execute_message and not history_text:
            self.agent_state_card.hide()
            return
        labels = {
            "running": "Ajan calisiyor",
            "approval_required": "Onay bekliyor",
            "completed": "Ajan tamamlandi",
            "provider_unavailable": "Cloud model kullanılamıyor",
            "executed": "Aksiyon calistirildi",
            "failed": "Aksiyon basarisiz",
            "cancelled": "Aksiyon iptal edildi",
            "superseded": "Onay kapsami gecersiz",
        }
        self.agent_state_title.setText(labels.get(clean_status, "Ajan gorevi"))
        tool_text = f"Tool: {', '.join(tool_names)}" if tool_names else "Tool: bekleniyor"
        detail_text = _safe_text(last_execute_message, _safe_text(detail, ""))
        self.agent_state_text.setText(f"{tool_text}" + (f" | {detail_text}" if detail_text else ""))
        self.agent_state_pending.setText(f"Pending: {pending_summary}" if pending_summary else "")
        self.agent_state_pending.setVisible(bool(pending_summary))
        self.agent_state_history.setText(history_text)
        self.agent_state_history.setVisible(bool(history_text))
        self.agent_state_card.hide()

    def _format_agent_action_history(self, history: list[dict[str, Any]]) -> str:
        rows = [dict(row) for row in list(history or []) if isinstance(row, dict)]
        if not rows:
            return ""
        lines = ["History:"]
        for row in rows[-4:]:
            phase = _safe_text(row.get("phase"), "-")
            status = _safe_text(row.get("status"), "-")
            action_type = _safe_text(row.get("action_type"), "-")
            success = row.get("success")
            verdict = ""
            if success is True:
                verdict = " ok"
            elif success is False:
                verdict = " fail"
            verify = row.get("verify") if isinstance(row.get("verify"), dict) else {}
            audit = _safe_text(row.get("audit_path"), "")
            evidence: list[str] = []
            if verify:
                evidence.append("verify")
            if audit:
                evidence.append("audit")
            suffix = f" ({', '.join(evidence)})" if evidence else ""
            lines.append(f"- {phase}/{status}: {action_type}{verdict}{suffix}")
        return "\n".join(lines)

    def _update_agent_state_from_result_data(self, data: dict[str, Any]) -> None:
        if bool(data.get("provider_unavailable")):
            self._set_agent_state(
                status="provider_unavailable",
                detail=_safe_text(
                    data.get("answer"),
                    "Cloud model geçici olarak kullanılamıyor; hiçbir tool çalışmadı.",
                ),
                tools=[],
            )
            return
        state = data.get("session_state") if isinstance(data.get("session_state"), dict) else data.get("state")
        state = state if isinstance(state, dict) else None
        if state:
            completed = len(list(state.get("completed_steps") or []))
            remaining = len(list(state.get("remaining_steps") or []))
            pending = list(state.get("pending_actions") or [])
            action_history = [dict(row) for row in list(state.get("action_history") or []) if isinstance(row, dict)]
            tools = self._tool_names_from_result_data(data)
            if not tools:
                for step in list(state.get("completed_steps") or []):
                    if isinstance(step, dict):
                        for tool_name in list(step.get("tool_names") or []):
                            clean = _safe_text(tool_name, "")
                            if clean and clean not in tools:
                                tools.append(clean)
            detail = (
                f"Session {str(state.get('session_id') or '')[:10]} | "
                f"adim {completed} tamam, {remaining} kaldi"
            )
            state_path = _safe_text(data.get("state_path"), "")
            if state_path:
                detail = f"{detail} | kayitli"
            if pending:
                self._set_agent_state(
                    status="approval_required",
                    detail=detail,
                    tools=tools,
                    pending_action=dict(pending[0]) if isinstance(pending[0], dict) else None,
                    action_history=action_history,
                )
                return
            status = "completed" if _safe_text(state.get("status"), "") == "complete" else _safe_text(state.get("status"), "running")
            self._set_agent_state(status=status, detail=detail, tools=tools, action_history=action_history)
            return
        tools = self._tool_names_from_result_data(data)
        action = data.get("action_proposal") if isinstance(data.get("action_proposal"), dict) else None
        if bool(data.get("approval_required")) and action:
            self._set_agent_state(
                status="approval_required",
                detail="Gercek API istegi onay bekliyor.",
                tools=tools,
                pending_action=action,
            )
            return
        self._set_agent_state(status="completed", detail="Tool sonucu cevaplandi.", tools=tools)

    def _mark_agent_action_executed(self, result: Result) -> None:
        current_tools = list(self._agent_state.get("tools") or [])
        self._set_agent_state(
            status="executed" if result.success else "failed",
            detail="Onayli aksiyon runtime tarafinda calisti." if result.success else "Onayli aksiyon calistirilamadi.",
            tools=current_tools,
            last_execute_message=_safe_text(result.message),
        )

    def _format_execute_result_answer(self, prefix: str, result: Result) -> str:
        data = dict(result.data or {}) if isinstance(result.data, dict) else {}
        visible_message = _safe_text(data.get("answer") or result.message)
        from AI.processors.model_loop import is_model_loop
        if is_model_loop(data.get("state") or data.get("session_state") or {}):
            return visible_message
        base = f"{prefix}: {visible_message}"
        execute_data = dict(data.get("execute") or {}) if isinstance(data.get("execute"), dict) else {}
        verify = dict(data.get("verify") or {}) if isinstance(data.get("verify"), dict) else {}
        if not verify and isinstance(execute_data.get("verify"), dict):
            verify = dict(execute_data.get("verify") or {})
        result_payload = dict(data.get("result") or {}) if isinstance(data.get("result"), dict) else {}
        if not result_payload and isinstance(execute_data.get("result"), dict):
            result_payload = dict(execute_data.get("result") or {})
        audit = dict(data.get("audit") or {}) if isinstance(data.get("audit"), dict) else {}
        if not audit and isinstance(execute_data.get("audit"), dict):
            audit = dict(execute_data.get("audit") or {})
        details: list[str] = []
        if verify:
            verified = verify.get("verified")
            if verified is True:
                details.append("verify: dogrulandi")
            elif verified is False:
                details.append("verify: dogrulanamadi")
            verified_by = _safe_text(verify.get("verified_by"), "")
            if verified_by:
                details.append(f"kanit: {verified_by}")
            for key, label in (
                ("order_numbers", "siparis"),
                ("claim_ids", "iade"),
                ("active_claim_ids", "aktif iade"),
                ("updated_pks", "guncellenen"),
                ("product_ids", "urun"),
            ):
                values = verify.get(key)
                if isinstance(values, (list, tuple)) and values:
                    text = ", ".join(_safe_text(value, "") for value in list(values)[:6] if _safe_text(value, ""))
                    if text:
                        suffix = "..." if len(values) > 6 else ""
                        details.append(f"{label}: {text}{suffix}")
            rows = verify.get("rows")
            if isinstance(rows, list) and rows:
                details.append(f"satir: {len(rows)}")
            output_path = _safe_text(verify.get("output_path") or result_payload.get("output_path"), "")
            if output_path:
                details.append(f"cikti: {output_path}")
        audit_operation = _safe_text(audit.get("operation"), "")
        if audit_operation:
            details.append(f"audit: {audit_operation}")
        if not details:
            return base
        return f"{base}\n" + "\n".join(f"- {detail}" for detail in details)

    def _approval_dialog_text(self, action: dict[str, Any]) -> tuple[str, str, str]:
        title = _safe_text(action.get("title"), "Riskli islem onayi")
        summary = _safe_text(action.get("summary"), "Bu islem kullanici onayi gerektiriyor.")
        rows = action.get("rows") if isinstance(action.get("rows"), list) else []
        warnings = action.get("warnings") if isinstance(action.get("warnings"), list) else []
        action_type = _safe_text(action.get("action_type"), "-")
        action_labels = {
            "labels.action_create_labels_from_selected_orders": "Sipariş etiketi oluşturma",
            "labels.mark_orders_extracted_from_label_result": "Fiş durumunu güncelleme",
            "orders.change_order_cargo_provider": "Sipariş kargo sağlayıcısını değiştirme",
            "orders.approve_return_claim": "İade talebini onaylama",
            "returns.approve": "İade talebini onaylama",
        }
        readable_action = action_labels.get(
            action_type,
            action_type.rsplit(".", 1)[-1].replace("_", " ").strip().capitalize() or "-",
        )
        risk_labels = {
            "low": "Düşük",
            "medium": "Orta",
            "high": "Yüksek",
            "critical": "Kritik",
        }
        risk = _safe_text(action.get("risk_level"), "high").casefold()
        details: list[str] = [
            f"Risk: {risk_labels.get(risk, risk.capitalize())}",
            f"İşlem: {readable_action}",
            "Gerçek API isteği henüz gönderilmedi.",
            "",
        ]
        # Approval scope is a safety boundary. Hiding rows behind a display cap made
        # a 21-order action look like a 10-order action even though the payload was
        # complete, so render every proposed row for review.
        for index, row in enumerate([dict(item) for item in rows if isinstance(item, dict)], start=1):
            fields: list[str] = []
            row_title = _safe_text(
                row.get("title")
                or row.get("claim_id")
                or row.get("order_number")
                or ((row.get("payload") or {}).get("claim_id") if isinstance(row.get("payload"), dict) else "")
                or ((row.get("payload") or {}).get("order_number") if isinstance(row.get("payload"), dict) else ""),
                _safe_text(row.get("operation"), "-").replace("_", " ").capitalize(),
            )
            claim_id = _safe_text(row.get("claim_id") or ((row.get("payload") or {}).get("claim_id") if isinstance(row.get("payload"), dict) else ""), "")
            if claim_id and claim_id != row_title:
                fields.append(f"claim {claim_id}")
            order_number = _safe_text(
                row.get("order_number") or ((row.get("payload") or {}).get("order_number") if isinstance(row.get("payload"), dict) else ""),
                "",
            )
            if order_number and order_number != row_title:
                fields.append(f"siparis {order_number}")
            if "current_sale_price" in row or "requested_sale_price" in row:
                fields.append(f"fiyat {row.get('current_sale_price')} -> {row.get('requested_sale_price')}")
            if "current_quantity" in row or "requested_quantity" in row:
                fields.append(f"stok {row.get('current_quantity')} -> {row.get('requested_quantity')}")
            if "cargo_provider_code" in row:
                fields.append(f"kargo {row.get('cargo_provider_code')}")
            changes = row.get("changes") if isinstance(row.get("changes"), dict) else {}
            status_change = changes.get("status") if isinstance(changes.get("status"), dict) else {}
            if status_change:
                fields.append(f"durum {status_change.get('before')} -> {status_change.get('after')}")
            waiting_ids = row.get("waiting_line_item_ids")
            if isinstance(waiting_ids, list) and waiting_ids:
                fields.append(f"bekleyen line {len(waiting_ids)}")
            barcode = _safe_text(row.get("barcode"), "")
            if barcode:
                fields.append(f"barkod {barcode}")
            details.append(f"{index}. {row_title}" + (f" | {', '.join(fields)}" if fields else ""))
        if warnings:
            details.extend(["", "Uyarilar:"])
            details.extend(f"- {_safe_text(item, '')}" for item in warnings[:5])
        return title, summary, "\n".join(details)

    def _show_action_approval_dialog(self, action: dict[str, Any]) -> None:
        self._append_chat_approval_card(action)

    def _pending_action_from_state(self) -> dict[str, Any] | None:
        action = self._agent_state.get("pending_action") if isinstance(self._agent_state, dict) else None
        return dict(action) if isinstance(action, dict) and action else None

    def _approval_reply_intent(self, text: str) -> str:
        if pending_action_followup_read_requested(text):
            return ""
        return approval_reply_protocol(text, self._conversation_state)

    def _handle_pending_action_reply(self, text: str) -> bool:
        action = self._pending_action_from_state()
        if not action:
            return False
        intent = self._approval_reply_intent(text)
        if not intent:
            return False
        if self._worker_is_running():
            self._append_chat_activity("Bir islem zaten calisiyor; yeni onay calistirilmadi.")
            return True
        task_session_id = _safe_text(action.get("_agent_task_session_id"), "")
        active_action_id = _safe_text(action.get("action_id"), "")
        referenced_action_id = referenced_action_id_from_text(
            text,
            known_action_ids=(
                active_action_id,
                *(
                    _safe_text(row.get("action_id"), "")
                    for row in self._superseded_actions
                    if isinstance(row, dict)
                ),
            ),
        )
        if referenced_action_id and referenced_action_id != active_action_id:
            if intent == "approve" and task_session_id:
                stale_action = dict(action)
                stale_action["action_id"] = referenced_action_id
                self._start_approved_action_worker(
                    stale_action,
                    task_session_id=task_session_id,
                )
            else:
                answer = (
                    "Belirttiğin action_id artık güncel onay işlemi değil; "
                    "hiçbir işlem çalıştırılmadı. Güncel onay kartı korunuyor."
                )
                self._append_chat_message("assistant", answer)
                self._chat_history.append({"role": "assistant", "content": answer})
                self._last_chat_success = True
                self._update_chat_controls()
            return True
        if intent == "cancel":
            if task_session_id:
                cancel_kwargs: dict[str, Any] = {"cancelled_by": "chat_ui"}
                action_id = _safe_text(action.get("action_id"), "")
                if action_id:
                    cancel_kwargs["action_id"] = action_id
                task_store_root = _safe_text(
                    action.get("_agent_task_store_root"),
                    "",
                )
                if task_store_root:
                    cancel_kwargs["task_store_root"] = task_store_root
                cancel_result = cancel_agent_task_by_id(task_session_id, **cancel_kwargs)
                cancel_data = dict(cancel_result.data or {})
                cancelled_state = cancel_data.get("state")
                if isinstance(cancelled_state, dict):
                    self._conversation_state = dict(cancelled_state)
                self._update_agent_state_from_result_data(cancel_data)
                self._refresh_task_sessions()
                answer = _safe_text(cancel_result.message)
                self._last_chat_success = bool(cancel_result.success)
            else:
                self._transition_conversation_pending_action(
                    action,
                    status="cancelled",
                    reason="cancelled_from_chat_ui",
                )
                self._set_agent_state(status="cancelled", detail="Kullanici sohbetten iptal etti.")
                answer = "Riskli islem iptal edildi. Gercek API istegi veya DB yazimi yapilmadi."
                self._last_chat_success = True
            self._append_chat_message("assistant", answer)
            self._chat_history.append({"role": "assistant", "content": answer})
            self._update_chat_controls()
            return True

        self._start_approved_action_worker(action, task_session_id=task_session_id)
        return True

    def _transition_conversation_pending_action(
        self,
        action: dict[str, Any],
        *,
        status: str,
        reason: str,
    ) -> bool:
        action_id = _safe_text(action.get("action_id"), "")
        if not action_id:
            return False
        try:
            state = AgentSessionState.from_dict(dict(self._conversation_state or {}))
            state.resolve_pending_action(
                action_id,
                status=status,
                reason=reason,
            )
            self._conversation_state = state.to_dict()
            return True
        except (TypeError, ValueError):
            return False

    def _pending_action_revision_requested(
        self,
        text: str,
        action: dict[str, Any],
    ) -> bool:
        normalized = _safe_text(text, "").casefold()
        normalized = (
            normalized.replace("ı", "i")
            .replace("İ", "i")
            .replace("ğ", "g")
            .replace("ü", "u")
            .replace("ş", "s")
            .replace("ö", "o")
            .replace("ç", "c")
        )
        action_type = _safe_text(action.get("action_type"), "").casefold()
        explicit_objection = any(
            token in normalized
            for token in (
                "yanlis",
                "duzelt",
                "yerine",
                "tamami",
                "tamamini",
                "hepsi",
                "hepsini",
                "butun",
                "tum",
                "eksik",
                "bu siparis ne",
                "bu siparis kimin",
                "kimin siparisi",
                "teslim edilmis",
                "teslim edildi",
                "delivered",
                "alakasiz",
                "uyusmuyor",
                "emin misin",
                "gosterdin",
            )
        )
        if (
            pending_action_followup_read_requested(normalized)
            and not explicit_objection
        ):
            # Asking what the pending card contains is a read of immutable
            # approval state, not a scope revision.  The card must stay valid
            # until the user explicitly approves, cancels or changes scope.
            return False
        correction = any(
            token in normalized
            for token in (
                "niye",
                "neden",
                "yanlis",
                "duzelt",
                "yerine",
                "tamami",
                "tamamini",
                "hepsi",
                "hepsini",
                "butun",
                "bütün",
                "tum",
                "tüm",
                "bekleyen siparis",
                "bekleyen sipariş",
                "eksik",
                "bu siparis ne",
                "bu siparis kimin",
                "kimin siparisi",
                "hangi siparis",
                "teslim edilmis",
                "teslim edildi",
                "delivered",
                "alakasiz",
                "uyusmuyor",
                "emin misin",
                "gosterdin",
            )
        )
        explicit_scope = bool(
            re.search(
                r"(?<!\w)\d{1,3}\s*(?:siparis|sipariş|order|paket|tane(?:yi|sini)?|adet(?:i|ini)?)(?!\w)",
                normalized,
            )
        )
        label_scope = "label" in action_type or "etiket" in normalized or "yazdir" in normalized
        return bool(label_scope and (correction or explicit_scope))

    def _supersede_pending_action_for_revision(self, text: str) -> bool | None:
        action = self._pending_action_from_state()
        if not action or not self._pending_action_revision_requested(text, action):
            return None
        task_session_id = _safe_text(action.get("_agent_task_session_id"), "")
        cancel_success = True
        cancel_message = ""
        if task_session_id:
            supersede_kwargs: dict[str, Any] = {
                "superseded_by": "chat_scope_revision",
                "reason": "scope_revised_from_chat_ui",
            }
            action_id = _safe_text(action.get("action_id"), "")
            if action_id:
                supersede_kwargs["action_id"] = action_id
            task_store_root = _safe_text(
                action.get("_agent_task_store_root"),
                "",
            )
            if task_store_root:
                supersede_kwargs["task_store_root"] = task_store_root
            supersede_result = supersede_agent_task_by_id(
                task_session_id,
                **supersede_kwargs,
            )
            cancel_success = bool(supersede_result.success)
            cancel_message = _safe_text(supersede_result.message)
            superseded_state = dict(supersede_result.data or {}).get("state")
            if cancel_success and isinstance(superseded_state, dict):
                self._conversation_state = dict(superseded_state)
        else:
            conversation_state = AgentSessionState.from_dict(
                dict(self._conversation_state or {})
            )
            if not conversation_state.active_pending_action_id:
                # Backward-compatible UI-only pending cards created before the
                # typed-state migration can still be invalidated locally.
                cancel_success = True
            else:
                cancel_success = self._transition_conversation_pending_action(
                    action,
                    status="superseded",
                    reason="scope_revised_from_chat_ui",
                )
        row = {
            "phase": "superseded",
            "status": "superseded" if cancel_success else "supersede_failed",
            "action_id": _safe_text(action.get("action_id"), ""),
            "prepare_fingerprint": _safe_text(
                action.get("prepare_fingerprint"),
                "",
            ),
            "action_type": _safe_text(action.get("action_type"), ""),
            "summary": self._pending_action_summary(action),
            "reason": _safe_text(text, ""),
            "task_session_id": task_session_id,
        }
        self._superseded_actions.append(row)
        self._set_agent_state(
            status="superseded" if cancel_success else "failed",
            detail=cancel_message
            or (
                "Onceki onay kapsami yeni kullanici talimati nedeniyle "
                "gecersiz kilindi."
            ),
            action_history=[row],
        )
        self._append_chat_activity(
            "Önceki onay kartı yeni kapsam talimatı nedeniyle geçersiz kılındı; "
            "eski kart artık çalıştırılamaz."
        )
        return cancel_success

    def _start_approved_action_worker(self, action: dict[str, Any], *, task_session_id: str = "") -> None:
        self._set_agent_state(
            status="running",
            detail="Onaylanan islem arka planda calistiriliyor.",
            pending_action=action,
        )
        self._action_worker = SyncWorker(
            _run_approved_chat_action,
            dict(action),
            parent=self,
            progress_callback_kw="progress_callback",
        )
        self._start_chat_progress(estimated_seconds=30)
        self._update_chat_controls()

        def _done(execute_result: Result) -> None:
            data = dict(execute_result.data or {})
            if task_session_id:
                returned_session_state = data.get("session_state")
                if not isinstance(returned_session_state, dict):
                    returned_session_state = data.get("state")
                if isinstance(returned_session_state, dict):
                    # Approval/resume is part of the same typed conversation.
                    # Keeping only the visual card state here leaves the next
                    # turn on the pre-approval pending snapshot and can revive
                    # stale scope after a successful execute/read-back.
                    self._conversation_state = dict(returned_session_state)
                self._update_agent_state_from_result_data(data)
                self._refresh_task_sessions()
                prefix = "Agent gorevi onaydan sonra devam etti" if execute_result.success else "Agent gorevi devam edemedi"
                next_action = data.get("action_proposal") if isinstance(data.get("action_proposal"), dict) else None
            else:
                if execute_result.success:
                    self._transition_conversation_pending_action(
                        action,
                        status="executed",
                        reason="approved_operation_executed_from_chat_ui",
                    )
                    self._mark_agent_action_executed(execute_result)
                else:
                    self._set_agent_state(
                        status="approval_required",
                        detail="Onaylanan islem calistirilamadi; ayni karttan tekrar deneyebilirsin.",
                        pending_action=action,
                    )
                prefix = "Onayli aksiyon calistirildi" if execute_result.success else "Onayli aksiyon calistirilamadi"
                next_action = None
            answer = self._format_execute_result_answer(prefix, execute_result)
            self._append_chat_message("assistant", answer)
            self._append_verified_artifact_links(data)
            if execute_result.success and next_action:
                self._append_chat_activity("Gorev sonraki riskli adima ilerledi; yeni onay bekleniyor.")
                self._show_action_approval_dialog(next_action)
            self._chat_history.append({"role": "assistant", "content": answer})
            self._last_chat_success = bool(execute_result.success)

        def _finished() -> None:
            self._action_worker = None
            self._finish_chat_progress(self._last_chat_success)
            self._update_chat_controls()

        self._action_worker.result_ready.connect(_done)
        progress_signal = getattr(self._action_worker, "progress", None)
        if progress_signal is not None and hasattr(progress_signal, "connect"):
            progress_signal.connect(self._on_task_progress)
        self._action_worker.finished.connect(_finished)
        self._action_worker.start()
        self._update_chat_controls()

    def _label_for_record(self, record: dict[str, Any]) -> str:
        source_kind = str(record.get("_source_kind") or "")
        if source_kind == "cloud_provider_header":
            label = _safe_text(record.get("label"), "provider")
            provider = _safe_text(record.get("provider_label") or record.get("provider_code"), "-")
            return f"{label}\n{provider} · bağlı"
        if source_kind == "cloud_model":
            model = _safe_text(record.get("default_model"), "model")
            metadata = dict(record.get("model_metadata") or {})
            pricing = "Ücretsiz" if bool(metadata.get("is_free")) else "Ücretli"
            context = int(metadata.get("context_length") or 0)
            capability = dict(metadata.get("capability_profile") or {})
            badges = [pricing]
            if capability.get("native_tool_calling_available"):
                badges.append("Tools")
            if context:
                badges.append(f"{max(1, context // 1024)}K")
            return f"   {model}\n   {' · '.join(badges)}"
        if source_kind == "cloud_provider" or record.get("provider_code"):
            label = _safe_text(record.get("label"), "provider")
            provider = _safe_text(record.get("provider_label") or record.get("provider_code"), "-")
            model = _safe_text(record.get("default_model"), "model belirtilmedi")
            status = "aktif" if bool(record.get("is_enabled", True)) else "pasif"
            return f"{label}\n{provider}\n{model} | {status}"
        repo_id = _safe_text(record.get("repo_id"), "model")
        filename = _safe_text(record.get("filename"), "-")
        quant = _safe_text(record.get("quantization"), "-")
        size_text = _safe_text(record.get("size_text"), "-")
        return f"{repo_id}\n{filename}\n{quant} | {size_text}"

    def _install_model_item_widget(self, item: QListWidgetItem, payload: dict[str, Any]) -> None:
        row = _ModelChoiceRow(payload, self.model_list)
        item.setSizeHint(QSize(240, row.minimumHeight()))
        item.setText("")
        self.model_list.setItemWidget(item, row)

    def _refresh_model_row_selection(self) -> None:
        current = self.model_list.currentItem()
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            row = self.model_list.itemWidget(item)
            if isinstance(row, _ModelChoiceRow):
                row.set_selected(item is current)

    def _refresh_current_source(self) -> None:
        if self._is_disposing:
            return
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        if source == AI_CHAT_SOURCE_CLOUD_VALUE:
            self._refresh_cloud_providers()
        else:
            self._refresh_local_models()

    def _switch_to_cloud_source(self) -> None:
        if self._is_disposing or self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE:
            return
        cloud_index = self.source_combo.findData(AI_CHAT_SOURCE_CLOUD_VALUE)
        if cloud_index < 0:
            return
        self.source_combo.setCurrentIndex(cloud_index)

    def _refresh_local_models(self) -> None:
        if self._is_disposing:
            return
        if self._models_worker is not None and self._models_worker.isRunning():
            return

        self.source_list_label.setText(AI_CHAT_LOCAL_MODELS_LABEL)
        self.model_status.setText(AI_CHAT_SCANNING_MODELS_TEXT)
        self.btn_refresh_models.setEnabled(False)
        self._models_worker = SyncWorker(ai_actions.action_list_installed_models, parent=self)

        def _done(result: Result) -> None:
            if self._is_disposing:
                return
            self.btn_refresh_models.setEnabled(True)
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.model_status.setText(AI_CHAT_MODELS_LOAD_FAILED_TEXT)
                return

            records = list((result.data or {}).get("records") or [])
            self._known_local_model_count = len(records)
            self._update_resource_summary()
            records.sort(
                key=lambda row: (
                    not bool(((row.get("resource_plan") or {}) if isinstance(row.get("resource_plan"), dict) else {}).get("safe_to_run", True)),
                    _safe_text(row.get("repo_id"), "").casefold(),
                    _safe_text(row.get("filename"), "").casefold(),
                )
            )
            self.model_list.clear()

            if not records:
                self.model_status.setText(AI_CHAT_EMPTY_LIBRARY_TEXT)
                self.local_count_pill.setText(AI_CHAT_LOCAL_COUNT_TEMPLATE.format(count=0))
                if not self._auto_switched_to_cloud and self.source_combo.findData(AI_CHAT_SOURCE_CLOUD_VALUE) >= 0:
                    self._auto_switched_to_cloud = True
                    QTimer.singleShot(0, self._switch_to_cloud_source)
            else:
                for record in records:
                    payload = dict(record)
                    payload["_source_kind"] = "local_model"
                    item = QListWidgetItem(self._label_for_record(payload))
                    item.setData(Qt.ItemDataRole.UserRole, payload)
                    self.model_list.addItem(item)
                    self._install_model_item_widget(item, payload)
                self.model_status.setText(AI_CHAT_INSTALLED_MODEL_COUNT_TEMPLATE.format(count=len(records)))
                self.local_count_pill.setText(AI_CHAT_LOCAL_COUNT_TEMPLATE.format(count=len(records)))
                self.model_list.setCurrentRow(0)

            self._update_chat_controls()

        def _finished() -> None:
            self.btn_refresh_models.setEnabled(True)
            self._models_worker = None

        self._models_worker.result_ready.connect(_done)
        self._models_worker.finished.connect(_finished)
        self._models_worker.start()

    def _refresh_cloud_providers(self) -> None:
        if self._is_disposing:
            return
        if self._providers_worker is not None and self._providers_worker.isRunning():
            return

        self.source_list_label.setText(AI_CHAT_CLOUD_PROVIDERS_LABEL)
        self.model_status.setText(AI_CHAT_MODEL_LIST_WAITING)
        self.btn_refresh_models.setEnabled(False)
        self._providers_worker = SyncWorker(lambda: ai_actions.action_list_provider_accounts(include_secret=True), parent=self)

        def _done(result: Result) -> None:
            if self._is_disposing:
                return
            self.btn_refresh_models.setEnabled(True)
            if not result.success:
                MessageHandler.show(self, result, only_errors=True)
                self.model_status.setText(AI_CHAT_PROVIDER_LOAD_FAILED_TEXT)
                return

            records = list((result.data or {}).get("records") or [])
            records = sorted(
                [dict(record, _source_kind="cloud_provider") for record in records if bool(record.get("is_enabled", True))],
                key=_cloud_provider_sort_key,
            )
            self._known_provider_count = len(records)
            self._update_resource_summary()

            if not records:
                self.model_list.clear()
                self.model_status.setText(AI_CHAT_PROVIDER_EMPTY_TEXT)
                self.local_count_pill.setText(AI_CHAT_PROVIDER_COUNT_TEMPLATE.format(count=0))
            else:
                self._populate_cloud_model_list(
                    [{"provider": record, "models": [], "route": {}} for record in records]
                )
                self.model_status.setText(
                    f"{len(records)} provider bağlı; canlı model katalogları okunuyor."
                )
                self.local_count_pill.setText(AI_CHAT_PROVIDER_COUNT_TEMPLATE.format(count=len(records)))
                self._refresh_provider_catalogs(records)

            self._update_chat_controls()

        def _finished() -> None:
            self.btn_refresh_models.setEnabled(True)
            self._providers_worker = None

        self._providers_worker.result_ready.connect(_done)
        self._providers_worker.finished.connect(_finished)
        self._providers_worker.start()

    def _provider_catalog_result(self, records: list[dict[str, Any]]) -> Result:
        groups: list[dict[str, Any]] = []
        errors: list[str] = []
        for provider in records:
            code = _safe_text(provider.get("provider_code"), "").casefold()
            catalog = ai_actions.action_list_provider_models(
                provider_code=code,
                endpoint_url=_safe_text(provider.get("endpoint_url"), ""),
                api_key=_safe_text(provider.get("api_key"), ""),
                free_only=self._cloud_price_filter == "free",
                limit=120,
            )
            if not catalog.success:
                errors.append(f"{_safe_text(provider.get('label'), code)}: {catalog.message}")
                groups.append({"provider": dict(provider), "models": [], "route": {}})
                continue
            data = dict(catalog.data or {})
            models = [dict(row) for row in list(data.get("records") or []) if isinstance(row, dict)]
            if self._cloud_price_filter == "paid":
                models = [row for row in models if not bool(row.get("is_free"))]
            groups.append(
                {
                    "provider": dict(provider),
                    "models": models,
                    "route": dict(data.get("free_model_test_route") or {}),
                }
            )
        return Result.ok(
            "Cloud model katalogları hazır.",
            close_dialog=False,
            data={"groups": groups, "errors": errors},
        )

    def _refresh_provider_catalogs(self, records: list[dict[str, Any]]) -> None:
        if self._is_disposing or not records:
            return
        if self._provider_catalog_worker is not None and self._provider_catalog_worker.isRunning():
            return
        self._provider_catalog_worker = SyncWorker(
            self._provider_catalog_result,
            [dict(row) for row in records],
            parent=self,
        )

        def _done(result: Result) -> None:
            if self._is_disposing or not result.success:
                return
            data = dict(result.data or {})
            groups = [dict(row) for row in list(data.get("groups") or []) if isinstance(row, dict)]
            self._populate_cloud_model_list(groups)
            model_count = sum(len(list(row.get("models") or [])) for row in groups)
            errors = list(data.get("errors") or [])
            suffix = f" · {len(errors)} katalog erişilemedi" if errors else ""
            self.model_status.setText(
                f"{len(groups)} provider · {model_count} model{suffix}"
            )
            self._update_chat_controls()

        def _finished() -> None:
            self._provider_catalog_worker = None
            self.btn_refresh_models.setEnabled(True)

        self._provider_catalog_worker.result_ready.connect(_done)
        self._provider_catalog_worker.finished.connect(_finished)
        self._provider_catalog_worker.start()

    @staticmethod
    def _cloud_provider_key(provider: dict[str, Any]) -> str:
        return _safe_text(
            provider.get("id") or provider.get("provider_code") or provider.get("label"),
            "provider",
        )

    def _populate_cloud_model_list(
        self,
        groups: list[dict[str, Any]],
        *,
        preserve_model_id: str = "",
    ) -> None:
        self._cloud_model_groups = [dict(group) for group in groups]
        self.model_list.clear()
        first_model_row = -1
        selected_model_row = -1
        for group in groups:
            provider = dict(group.get("provider") or {})
            models = [dict(row) for row in list(group.get("models") or []) if isinstance(row, dict)]
            route = dict(group.get("route") or {})
            provider_key = self._cloud_provider_key(provider)
            collapsed = provider_key in self._cloud_collapsed_provider_keys
            header_payload = {
                **provider,
                "_source_kind": "cloud_provider_header",
                "_provider_key": provider_key,
                "_collapsed": collapsed,
            }
            header = QListWidgetItem(self._label_for_record(header_payload))
            header.setData(Qt.ItemDataRole.UserRole, header_payload)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.model_list.addItem(header)
            self._install_model_item_widget(header, header_payload)
            header_row = self.model_list.itemWidget(header)
            if isinstance(header_row, _ModelChoiceRow):
                header_row.set_collapsed(collapsed)

            if collapsed:
                continue

            if not models and _safe_text(provider.get("default_model"), ""):
                models = [
                    {
                        "id": provider.get("default_model"),
                        "name": provider.get("default_model"),
                        "is_free": str(provider.get("default_model") or "").casefold().endswith(":free")
                        or _safe_text(provider.get("provider_code"), "").casefold() == "gemini",
                        "capability_profile": {},
                    }
                ]
            for rank, model in enumerate(models):
                model_id = _safe_text(model.get("id"), "")
                if not model_id:
                    continue
                payload = {
                    **provider,
                    "_source_kind": "cloud_model",
                    "default_model": model_id,
                    "model_metadata": model,
                    "free_model_test_route": route,
                    "free_model_rank": rank,
                    "allow_model_fallback": bool(provider.get("allow_model_fallback", True)),
                    "_explicit_runtime_override": True,
                }
                item = QListWidgetItem(self._label_for_record(payload))
                item.setData(Qt.ItemDataRole.UserRole, payload)
                self.model_list.addItem(item)
                self._install_model_item_widget(item, payload)
                if first_model_row < 0:
                    first_model_row = self.model_list.count() - 1
                if preserve_model_id and model_id == preserve_model_id:
                    selected_model_row = self.model_list.count() - 1
        target_row = selected_model_row if selected_model_row >= 0 else first_model_row
        if target_row >= 0:
            self.model_list.setCurrentRow(target_row)
        self._refresh_model_row_selection()

    def _on_model_list_item_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict) or _safe_text(payload.get("_source_kind"), "") != "cloud_provider_header":
            return
        provider_key = _safe_text(payload.get("_provider_key"), "")
        if not provider_key:
            return
        if provider_key in self._cloud_collapsed_provider_keys:
            self._cloud_collapsed_provider_keys.discard(provider_key)
        else:
            self._cloud_collapsed_provider_keys.add(provider_key)
        self._populate_cloud_model_list(
            self._cloud_model_groups,
            preserve_model_id=self._last_selected_cloud_model_id,
        )

    def _selected_local_record(self) -> dict[str, Any] | None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict) or str(payload.get("_source_kind") or "local_model") != "local_model":
            return None
        return payload if payload.get("repo_id") else None

    def _selected_provider_record(self) -> dict[str, Any] | None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict) or str(payload.get("_source_kind") or "") not in {
            "cloud_provider",
            "cloud_model",
        }:
            return None
        return payload if int(payload.get("id") or 0) > 0 else None

    def _resource_plan_for_record(self, record: dict[str, Any]):
        key = "|".join(
            _safe_text(record.get(field), "")
            for field in ("repo_id", "filename", "local_path", "size_bytes")
        )
        if key not in self._resource_plan_cache:
            plan_payload = record.get("resource_plan")
            if isinstance(plan_payload, dict) and "safe_to_run" in plan_payload:
                self._resource_plan_cache[key] = SimpleNamespace(
                    safe_to_run=bool(plan_payload.get("safe_to_run")),
                    profile=_safe_text(plan_payload.get("profile"), "precomputed"),
                    reason=_safe_text(plan_payload.get("reason"), ""),
                    num_ctx=int(plan_payload.get("num_ctx") or 512),
                    max_tokens=int(plan_payload.get("max_tokens") or 128),
                )
            else:
                self._resource_plan_cache[key] = build_local_resource_plan(record)
        return self._resource_plan_cache[key]

    def _on_model_selection_changed(self) -> None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(payload, dict):
            if _safe_text(payload.get("_source_kind"), "") == "cloud_model":
                self._last_selected_cloud_model_id = _safe_text(payload.get("default_model"), "")
            effort = _safe_text(payload.get("reasoning_effort"), "auto").casefold()
            index = self.reasoning_combo.findData(effort)
            self.reasoning_combo.blockSignals(True)
            self.reasoning_combo.setCurrentIndex(index if index >= 0 else 0)
            self.reasoning_combo.blockSignals(False)
            self.fallback_checkbox.blockSignals(True)
            self.fallback_checkbox.setChecked(bool(payload.get("allow_model_fallback", True)))
            self.fallback_checkbox.blockSignals(False)
        self._refresh_model_row_selection()
        self._update_chat_controls()

    def _on_source_changed(self) -> None:
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        is_local = source == AI_CHAT_SOURCE_LOCAL_VALUE
        self.model_list.clear()
        self.model_list.setEnabled(True)
        self.btn_refresh_models.setEnabled(True)
        self.source_list_label.setText(AI_CHAT_LOCAL_MODELS_LABEL if is_local else AI_CHAT_CLOUD_PROVIDERS_LABEL)
        self.active_source_pill.setText(AI_CHAT_SOURCE_PILL_LOCAL_TEXT if is_local else AI_CHAT_SOURCE_PILL_CLOUD_TEXT)
        self.runner_status.setText(AI_CHAT_LOCAL_RUNNER_STATUS_TEXT if is_local else AI_CHAT_CLOUD_RUNNER_STATUS_TEXT)
        self._sync_model_panel_mode()
        self._refresh_current_source()
        self._update_chat_controls()

    def _update_chat_controls(self) -> None:
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        record = self._selected_local_record()
        provider = self._selected_provider_record()
        reasoning_label = self.reasoning_combo.currentText().replace("Zekâ: ", "").strip() or "Otomatik"
        message_ready = bool(self.composer.toPlainText().strip())
        busy = self._worker_is_running()
        local_blocked = False
        selection_ready = False

        if source == AI_CHAT_SOURCE_LOCAL_VALUE and record:
            selection_ready = True
            repo_id = _safe_text(record.get("repo_id"))
            display_name = _model_display_name(record)
            plan = self._resource_plan_for_record(record)
            local_blocked = not bool(getattr(plan, "safe_to_run", True))
            self.brain_label.setText(AI_CHAT_ACTIVE_BRAIN_TEMPLATE.format(repo_id=repo_id))
            self.active_brain_badge.setText(AI_CHAT_BRAIN_TEMPLATE.format(repo_id=repo_id))
            self.composer_meta.setText(
                f"{AI_CHAT_SELECTED_LOCAL_BRAIN_TEMPLATE.format(repo_id=repo_id)} | {plan.profile}, ctx {plan.num_ctx}, out {plan.max_tokens}"
                if not local_blocked
                else f"{AI_CHAT_SELECTED_LOCAL_BRAIN_TEMPLATE.format(repo_id=repo_id)} | bloke: {plan.reason}"
            )
            self.chat_status.setText(
                "Yerel model düşünüyor..."
                if busy
                else f"Yerel · {display_name} · Zekâ: {reasoning_label}"
            )
            self.session_hint_badge.setText("İşlem sürüyor" if busy else "Yerel runner bağlı")
            if local_blocked:
                self.chat_status.setText("Yerel model guvenli degil")
                self.session_hint_badge.setText("OS koruma aktif")
        elif source == AI_CHAT_SOURCE_LOCAL_VALUE:
            self.brain_label.setText(AI_CHAT_ACTIVE_BRAIN_TEXT)
            self.active_brain_badge.setText(AI_CHAT_BRAIN_UNSELECTED)
            self.composer_meta.setText(AI_CHAT_SELECT_LOCAL_MODEL_TEXT)
            self.chat_status.setText(AI_CHAT_STATUS_WAITING)
            self.session_hint_badge.setText(AI_CHAT_LOCAL_PREP_TEXT)
        elif provider:
            label = _safe_text(provider.get("label"))
            model = _safe_text(provider.get("default_model"), "model belirtilmedi")
            selection_ready = bool(_safe_text(provider.get("default_model"), ""))
            self.brain_label.setText(f"Aktif beyin: {label}")
            self.active_brain_badge.setText(f"Beyin: {model}")
            if selection_ready:
                self.composer_meta.setText(f"Seçili cloud beyin: {label} / {model}")
                self.chat_status.setText(
                    "Cloud model düşünüyor..."
                    if busy
                    else f"{label} · {model} · Zekâ: {reasoning_label}"
                )
                self.session_hint_badge.setText("İşlem sürüyor" if busy else "Cloud runner bağlı")
            else:
                self.composer_meta.setText(AI_CHAT_CLOUD_MODEL_MISSING_TEXT)
                self.chat_status.setText(AI_CHAT_CLOUD_WAITING_TEXT)
                self.session_hint_badge.setText(AI_CHAT_CLOUD_PREP_TEXT)
        else:
            self.brain_label.setText(AI_CHAT_ACTIVE_BRAIN_CLOUD_TEXT)
            self.active_brain_badge.setText(AI_CHAT_BRAIN_CLOUD_TEXT)
            self.composer_meta.setText(AI_CHAT_SELECT_CLOUD_PROVIDER_TEXT)
            self.chat_status.setText(AI_CHAT_CLOUD_WAITING_TEXT)
            self.session_hint_badge.setText(AI_CHAT_CLOUD_PREP_TEXT)

        can_guide = bool(busy and self._chat_worker is not None and self._action_worker is None)
        self.composer.setEnabled(not busy or can_guide)
        self.btn_new_chat.setEnabled(not busy)
        self.btn_saved_workflows.setEnabled(not busy)
        self.btn_workflow_schedules.setEnabled(not busy)
        self.btn_attach.setEnabled(not busy)
        self.source_combo.setEnabled(not busy)
        self.model_list.setEnabled(not busy)
        self.btn_refresh_models.setEnabled(not busy and self._models_worker is None and self._providers_worker is None)
        self.btn_send.setText("Yönlendir" if can_guide else "Düşünüyor..." if busy else AI_CHAT_SEND_BUTTON_TEXT)
        self.btn_send.setEnabled(message_ready and selection_ready and (not busy or can_guide) and not local_blocked)
        self.btn_pause_task.setVisible(can_guide)
        self.btn_pause_task.setEnabled(can_guide and self._task_control is not None and not self._task_control.pause_requested)

    def _open_model_hub(self) -> None:
        if self._model_hub_window is not None and self._model_hub_window.isVisible():
            self._model_hub_window.raise_()
            self._model_hub_window.activateWindow()
            return

        self._model_hub_window = AIManagerDialog(self)
        self._model_hub_window.destroyed.connect(lambda *_: self._on_model_hub_closed())
        self._model_hub_window.show()
        self._model_hub_window.showMaximized()

    def _on_model_hub_closed(self) -> None:
        self._model_hub_window = None
        self._refresh_current_source()

    def closeEvent(self, event) -> None:
        self._is_disposing = True
        self._schedule_timer.stop()
        if self._task_control is not None:
            self._task_control.request_pause()
        if self._chat_progress_timer is not None:
            self._chat_progress_timer.stop()
        for worker in (
            self._chat_worker,
            self._action_worker,
            self._models_worker,
            self._providers_worker,
            self._provider_catalog_worker,
        ):
            self._shutdown_worker(worker)
        self._chat_worker = None
        self._action_worker = None
        self._models_worker = None
        self._providers_worker = None
        self._provider_catalog_worker = None
        super().closeEvent(event)

    def _shutdown_worker(self, worker: SyncWorker | None) -> None:
        if worker is None:
            return
        for signal_name in ("result_ready", "progress", "finished"):
            signal = getattr(worker, signal_name, None)
            if signal is None or not hasattr(signal, "disconnect"):
                continue
            try:
                signal.disconnect()
            except Exception:
                pass
        try:
            worker.requestInterruption()
        except Exception:
            pass
        try:
            if worker.isRunning():
                worker.wait()
        except Exception:
            pass

    def _reset_chat(self) -> None:
        self._queued_guidance.clear()
        self._task_control = None
        self.transcript.clear()
        self._chat_message_count = 0
        self._chat_history.clear()
        self._conversation_state = AgentSessionState(
            goal="OrderScout AI conversation",
            active_domain="orders",
        ).to_dict()
        self._approval_card_actions.clear()
        self._latest_approval_card_token = ""
        self._superseded_actions.clear()
        self._delivered_artifacts.clear()
        self._restored_task_session_ids.clear()
        self._last_task_progress_message = ""
        self.composer.clear()
        self.btn_attach.setToolTip("Bu sohbete dosya ekle")
        self._hide_chat_progress_if_idle()
        self._set_agent_state(status="reset")
        self._refresh_chat_surface()
        self._update_chat_controls()

    def _request_task_pause(self) -> None:
        if self._task_control is None or self._chat_worker is None:
            return
        self._task_control.request_pause()
        self._append_chat_activity("Duraklatma istendi; sürmekte olan adımın sonucu kaydedilince çalışma duracak.")
        self._update_chat_controls()

    def _run_queued_guidance(self) -> None:
        if self._worker_is_running() or not self._queued_guidance:
            return
        text = "\n".join(self._queued_guidance)
        self._queued_guidance.clear()
        self._send_message(text_override=text, already_recorded=True)

    def _send_message(self, *, text_override: str | None = None, already_recorded: bool = False,
                      fresh_history: bool = False) -> None:
        text = (text_override if text_override is not None else self.composer.toPlainText()).strip()
        if not text:
            return
        if self._worker_is_running():
            if self._chat_worker is None or self._task_control is None:
                return
            self._append_chat_message("user", text)
            self.composer.clear()
            self._chat_history.append({"role": "user", "content": text})
            self._queued_guidance.append(text)
            self._task_control.request_pause(reason="user_revision", user_message=text)
            self._append_chat_activity("Yeni talimatını aldım; mevcut adımın sonucunu koruyup bu talimatla devam edeceğim.")
            self._update_chat_controls()
            return

        pending_before_read = self._pending_action_from_state()
        from AI.processors.model_loop import is_model_loop
        model_owned = is_model_loop(self._conversation_state)
        preserve_pending_after_read = bool(
            pending_before_read
            and not model_owned
            and pending_action_followup_read_requested(text)
        )

        if not already_recorded:
            self._append_chat_message("user", text)
        self.composer.clear()
        if not already_recorded:
            self._chat_history.append({"role": "user", "content": text})
        superseded = None if model_owned else self._supersede_pending_action_for_revision(text)
        if superseded is False:
            self._append_chat_message(
                "assistant",
                "Önceki onay güvenle iptal edilemediği için yeni kapsam "
                "hazırlanmadı. Önce mevcut işlemi vazgeçerek kapat.",
            )
            self._last_chat_success = False
            self._update_chat_controls()
            return
        if superseded is None and self._handle_pending_action_reply(text):
            return
        self._set_agent_state(
            status="running",
            detail="Istek alindi; tool plani hazirlaniyor.",
            pending_action=(pending_before_read if preserve_pending_after_read else None),
        )
        self._update_chat_controls()
        self._last_chat_success = True

        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        if source == AI_CHAT_SOURCE_LOCAL_VALUE:
            record = self._selected_local_record()
            if not record:
                self._append_chat_message("assistant", AI_CHAT_NO_LOCAL_MODEL_TEXT)
                return
            plan = self._resource_plan_for_record(record)
            estimated_seconds = self._estimate_chat_duration_seconds(source, None, text)
            self._append_chat_activity(
                f"Local runner hazirlaniyor: {_safe_text(record.get('repo_id'))} / {getattr(plan, 'profile', 'auto')} / ctx {getattr(plan, 'num_ctx', '-')}"
            )
        else:
            record = self._selected_provider_record()
            if not record:
                self._append_chat_message("assistant", AI_CHAT_SELECT_CLOUD_PROVIDER_TEXT)
                return
            estimated_seconds = self._estimate_chat_duration_seconds(source, None, text)
            self._append_chat_activity(
                f"Cloud runner hazirlaniyor: {_safe_text(record.get('label'))} / {_safe_text(record.get('default_model'), 'model')}"
            )

        self._append_chat_activity(AI_CHAT_AGENT_ACTIVITY_TEXT)
        from AI.processors.task_control import AgentTaskControl
        self._task_control = AgentTaskControl()
        history = [{"role": "user", "content": text}] if fresh_history else list(self._chat_history)
        self._chat_worker = SyncWorker(
            _run_chat_turn_with_runtime,
            text,
            parent=self,
            progress_callback_kw="progress_callback",
            source=source,
            runtime_record=dict(record),
            history=history,
            session_state=dict(self._conversation_state),
            task_control=self._task_control,
        )
        self._start_chat_progress(estimated_seconds)
        self._update_chat_controls()

        def _done(result: Result) -> None:
            if result.success:
                data = result.data or {}
                returned_session_state = data.get("session_state")
                if isinstance(returned_session_state, dict):
                    self._conversation_state = dict(returned_session_state)
                self._update_agent_state_from_result_data(data)
                if preserve_pending_after_read and pending_before_read and not bool(
                    data.get("approval_required")
                ):
                    self._set_agent_state(
                        status="approval_required",
                        detail="Onay bekleyen aksiyon read-only sorudan sonra korundu.",
                        tools=self._tool_names_from_result_data(data),
                        pending_action=pending_before_read,
                    )
                self._refresh_task_sessions()
                runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
                if runtime:
                    self._append_chat_activity(_format_runtime_activity(source, runtime))
                tool_call = data.get("tool_call") if isinstance(data.get("tool_call"), dict) else None
                tool_calls = data.get("tool_calls") if isinstance(data.get("tool_calls"), list) else []
                visible_tools = [
                    str(row.get("tool") or "").strip()
                    for row in tool_calls
                    if isinstance(row, dict) and str(row.get("tool") or "").strip()
                ]
                if not visible_tools and tool_call and tool_call.get("tool"):
                    visible_tools = [str(tool_call.get("tool"))]
                if visible_tools:
                    self._set_chat_progress(90, "Tool sonucu isleniyor", percent_text=f"90% | {self._format_chat_elapsed()}")
                    self._append_chat_activity(AI_CHAT_TOOL_ACTIVITY_TEMPLATE.format(tool=", ".join(visible_tools)))
                action_proposal = data.get("action_proposal") if isinstance(data.get("action_proposal"), dict) else None
                if bool(data.get("approval_required")) and action_proposal:
                    self._append_chat_activity("Hazırlanan işlem onayını bekliyor. Henüz çalıştırılmadı.")
                answer = _safe_text(data.get("answer")) or result.message
                self._set_chat_progress(96, "Cevap ekrana yaziliyor", percent_text=f"96% | {self._format_chat_elapsed()}")
                self._append_chat_message("assistant", answer)
                if bool(data.get("approval_required")) and action_proposal:
                    self._show_action_approval_dialog(action_proposal)
                self._append_verified_artifact_links(data)
                assistant_history: dict[str, Any] = {"role": "assistant", "content": answer}
                conversation_context = data.get("conversation_context")
                if isinstance(conversation_context, dict) and conversation_context:
                    assistant_history["context"] = dict(conversation_context)
                self._chat_history.append(assistant_history)
                self._last_chat_success = not bool(
                    data.get("provider_unavailable")
                )
            else:
                failed_data = dict(result.data or {})
                failed_state = failed_data.get("session_state") or failed_data.get("state")
                if isinstance(failed_state, dict):
                    self._conversation_state = dict(failed_state)
                    self._update_agent_state_from_result_data(failed_data)
                self._append_chat_message("assistant", result.message)
                self._append_verified_artifact_links(failed_data)
                self._last_chat_success = False

        def _finished() -> None:
            self._chat_worker = None
            self._task_control = None
            self._finish_chat_progress(self._last_chat_success)
            self._update_chat_controls()
            if self._queued_guidance:
                QTimer.singleShot(0, self._run_queued_guidance)

        self._chat_worker.result_ready.connect(_done)
        progress_signal = getattr(self._chat_worker, "progress", None)
        if progress_signal is not None and hasattr(progress_signal, "connect"):
            progress_signal.connect(self._on_task_progress)
        self._chat_worker.finished.connect(_finished)
        self._chat_worker.start()
        self._update_chat_controls()

    def _release_splitter_guard(self) -> None:
        self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()

    def _is_model_panel_open(self) -> bool:
        sizes = self._tab_splitter.sizes()
        if len(sizes) < 2:
            return False
        return int(sizes[0]) > 8

    def _sync_sidebar_state_from_splitter(self) -> None:
        self._panel_sidebar.set_active_panel("models" if self._is_model_panel_open() else None)

    def _splitter_total_size(self) -> int:
        sizes = self._tab_splitter.sizes()
        total = int(sum(sizes)) if sizes else 0
        if total > 0:
            return total
        width = int(self._tab_splitter.width() or 0)
        if width > 0:
            return width
        return self._left_stick_size + 980

    def _snap_splitter(self, left: int, total: int) -> None:
        self._splitter_guard = True
        clamped = max(0, int(left))
        self._tab_splitter.setSizes([clamped, max(0, int(total) - clamped)])
        QTimer.singleShot(0, self._release_splitter_guard)

    def _open_model_panel(self) -> None:
        if self._is_model_panel_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        min_left = 320
        target = max(min_left, min(self._left_stick_size, total - 320))
        if target <= 0:
            target = min_left
        self._snap_splitter(target, total)
        self._sync_sidebar_state_from_splitter()

    def _close_model_panel(self) -> None:
        if not self._is_model_panel_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        self._snap_splitter(0, total)
        self._sync_sidebar_state_from_splitter()

    def _on_panel_sidebar_toggled(self, panel_id: str, active: bool) -> None:
        if panel_id != "models":
            return
        if active:
            self._open_model_panel()
        else:
            self._close_model_panel()

    def _on_tab_splitter_moved(self, pos: int, _index: int) -> None:
        if self._splitter_guard:
            return
        try:
            sizes = self._tab_splitter.sizes()
            if len(sizes) < 2:
                return
            left, right = int(sizes[0]), int(sizes[1])
            total = left + right
            if total <= 0:
                return
            if left >= self._left_stick_size:
                return
            if pos <= self._left_collapse_trigger:
                self._snap_splitter(0, total)
                return
            if left < self._left_stick_size:
                self._snap_splitter(self._left_stick_size, total)
        except Exception:
            self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()
