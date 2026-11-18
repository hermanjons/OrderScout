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

from PyQt6.QtCore import QEvent, QPersistentModelIndex, QPoint, QSignalBlocker, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap, QTextCursor
from PyQt6.QtSvg import QSvgRenderer
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
from AI.processors.turn_service import (
    approval_reply_protocol, model_turn_control_mode, run_interpreted_turn, resume_reply_interpretation,
)
from AI.views.model_picker import (ModelChoiceDelegate, PRESENTATION_ROLE, SEARCH_ROLE,
                                  model_identity, model_presentation, search_text)
from AI.views.reasoning_control import ReasoningControl

from AI.constants.ui_constants import (
    AI_BRAND_ICON_NAME,
    AI_CHAT_ACTIVE_BRAIN_CLOUD_TEXT,
    AI_CHAT_ACTIVE_BRAIN_TEMPLATE,
    AI_CHAT_ACTIVE_BRAIN_TEXT,
    AI_CHAT_ASSISTANT_ROLE_TEXT,
    AI_CHAT_ATTACH_BUTTON_TEXT,
    AI_CHAT_BRAIN_CLOUD_TEXT,
    AI_CHAT_BRAIN_TEMPLATE,
    AI_CHAT_BRAIN_UNSELECTED,
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
from AI.views.stream_worker import ChatStreamWorker
from AI.views.run_activity import RunActivityPanel
from AI.views.conversation_sidebar import ConversationSidebar
from Core.views import ResettableSplitter
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
    provider_reasoning_capabilities,
)
from AI.processors.conversation_runtime import (
    grounded_capability_overview,
    policy_context_from_interpretation,
)
from AI.processors.local_runtime import build_local_planner_client, release_local_planner_client
from AI.processors.local_resources import build_local_resource_plan
from AI.processors.operation_runtime import execute_approved_operation
from AI.processors.task_store import list_agent_task_states, load_agent_task_state
from AI.processors.chat_session_store import (
    conversation_history,
    load_active_chat_session,
    save_active_chat_session,
    list_chat_sessions,
    load_chat_session,
)
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


_DEFAULT_SYNC_WORKER = SyncWorker


def _make_chat_worker(*args, **kwargs):
    # Keep the existing injectable worker factory for offline UI tests.
    worker_type = ChatStreamWorker if SyncWorker is _DEFAULT_SYNC_WORKER else SyncWorker
    return worker_type(*args, **kwargs)


def _assistant_message_block(safe_message: str, role_name: str = AI_CHAT_ASSISTANT_ROLE_TEXT,
                             *, activity_html: str = "") -> str:
    icon_url = html.escape(QUrl.fromLocalFile(_ai_icon_path()).toString())
    return (
        '<table width="78%" cellspacing="0" cellpadding="0" style="margin:0 0 18px 0;">'
        f'<tr><td width="46" valign="top"><img src="{icon_url}" width="36" height="36"></td>'
        '<td valign="top">'
        f'<div style="font-size:11px;color:#0F172A;font-weight:900;margin-bottom:5px;">{role_name}</div>'
        '<table width="100%" cellspacing="0" cellpadding="10" bgcolor="#FFFFFF" '
        'style="background-color:#FFFFFF;color:#0F172A;">'
        f'<tr><td style="color:#0F172A;line-height:1.55;">{safe_message}</td></tr>'
        f'</table>{activity_html}</td></tr></table>'
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
    history_includes_current: bool = False,
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
        local_startup_error = "Seçilen yerel model dosyası veya motor bulunamadı."
        try:
            planner_client = build_local_planner_client(record)
        except Exception as error:
            local_startup_error = str(error).splitlines()[0][:300] or "Yerel motor başlatılamadı."
            planner_client = None
        if planner_client is None:
            message = "Yerel model açılamadı: " + local_startup_error
            state = AgentSessionState.from_dict(session_state) if session_state else AgentSessionState(goal=text)
            state.goal, state.status = text, "paused"
            state.record_turn(role="user", content=text, mode="local_startup")
            state.record_turn(role="assistant", content=message, mode="runtime_error")
            from AI.processors.task_store import save_agent_task_state
            path = save_agent_task_state(state)
            return Result.fail(message, close_dialog=False, data={"session_state": state.to_dict(),
                "state": state.to_dict(), "state_path": str(path), "model_invoked": False,
                "runtime_error": {"phase": "local_startup"}})
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
    control_mode = model_turn_control_mode(text, session_state)
    if planner_client is not None and not control_mode and not resume_reply_interpretation(text, session_state):
        try:
            result = run_model_loop(text, client=planner_client, session_state=session_state, history=history,
                db_name=DB_NAME, persist=True, runtime_context=_task_runtime_context(source, record),
                progress_callback=progress_callback, task_control=task_control,
                history_includes_current=history_includes_current)
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
        text = (
            f"Local runner: {runtime_name} / {model_name} / {runtime_plan.get('profile')} "
            f"/ ctx {runtime_plan.get('num_ctx')} / out {runtime_plan.get('max_tokens')}"
        )
    else:
        text = f"Cloud runner: {runtime_name} / {model_name}"
    if source != AI_CHAT_SOURCE_LOCAL_VALUE and bool(runtime_plan.get("fallback_used")):
        requested = _safe_text(runtime_plan.get("requested_model"), "")
        actual = _safe_text(runtime_plan.get("actual_model") or model_name, model_name)
        if requested and actual and requested != actual:
            text = f"Cloud runner: {runtime_name} / {actual} (fallback: {requested} -> {actual})"
    usage = runtime_plan.get("provider_usage_totals")
    if isinstance(usage, dict) and usage.get("responses_with_usage"):
        def count(value: Any) -> str:
            return f"{int(value):,}" if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else "?"
        text += (f" | Token toplamı: giriş {count(usage.get('input_tokens'))}, çıkış {count(usage.get('output_tokens'))}"
                 f" | {count(usage.get('response_count'))} model yanıtı")
    return text


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
    preferred = os.path.join(ASSETS_DIR, AI_BRAND_ICON_NAME)
    if os.path.exists(preferred):
        return preferred
    return os.path.join(ASSETS_DIR, "orderscout-logo.png")


def _chat_icon(name: str, color: str = "#64748B") -> QIcon:
    paths = {
        "panel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
        "plus": '<path d="M12 5v14M5 12h14"/>',
        "arrow": '<path d="M12 19V5m-6 6 6-6 6 6"/>',
        "steps": '<path d="m3 7 2 2 3-4m3 2h10M3 15l2 2 3-4m3 2h10"/>',
        "chevron": '<path d="m6 9 6 6 6-6"/>',
    }
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
           + paths[name] + '</svg>')
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    return QIcon(pixmap)


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


def _local_plan_description(plan: dict[str, Any]) -> str:
    """Translate the effective resource plan into a decision, without promising speed."""
    if not plan:
        return "Kaynak planı henüz hesaplanmadı."
    if not bool(plan.get("safe_to_run", True)) or plan.get("suitability") == "blocked":
        status = "Bu model başlatılamaz"
    elif plan.get("requires_paging") or plan.get("suitability") == "slow":
        status = "Çalışabilir · yavaş yanıt bekleniyor"
    elif plan.get("suitability") == "recommended":
        status = "Bu cihaz için önerilen"
    else:
        status = "Kaynak planı hazır"
    mode = str(plan.get("capacity_label") or plan.get("reason") or "").strip()
    if plan.get("suitability") == "recommended" and plan.get("capacity_label"):
        status, mode = str(plan["capacity_label"]), ""
    parts = [status, mode]
    context = int(plan.get("num_ctx") or 0)
    output = int(plan.get("max_tokens") or 0)
    if context:
        parts.append(f"Bağlam {context:,} · yanıt en çok {output:,} token")
    runtime_bytes = int(plan.get("estimated_runtime_bytes") or 0)
    if runtime_bytes:
        parts.append(f"Tahmini çalışma belleği {runtime_bytes / (1024 ** 3):.1f} GiB")
    parts.extend(str(item) for item in list(plan.get("warnings") or [])[:2])
    return "\n".join(dict.fromkeys(part for part in parts if part))


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
        self.setWindowTitle("Model çalışma ayarları")
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
            else dict(self._record.get("runtime_capabilities") or {})
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
            QDialog#AiAdvancedModelPopup QScrollArea,
            QWidget#AiAdvancedBody {
                background: #FFFFFF;
                border: 0;
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
        title = QLabel(model_name)
        title.setObjectName("PopupTitle")
        title.setWordWrap(True)
        root.addWidget(title)
        hint = QLabel("Bu sohbetin çalışma ayarları. Kaynak planı uygularken yeniden hesaplanır." if is_local else "Yalnız bu sohbet ve modelin desteklediği ayarlar uygulanır.")
        hint.setObjectName("PopupHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        body.setObjectName("AiAdvancedBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(10)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._performance_preset = None
        runtime_config = dict(self._record.get("runtime_config") or {})
        resource_plan = dict(self._record.get("resource_plan") or {})

        def _default(key: str, fallback: Any) -> Any:
            for source in (self._record, runtime_config, resource_plan, resource_plan.get("sampling_defaults") or {}):
                value = source.get(key)
                if value is not None and value != "":
                    return value
            return fallback

        if self._is_local:
            plan_hint = QLabel(_local_plan_description(resource_plan))
            plan_hint.setObjectName("PopupHint")
            plan_hint.setWordWrap(True)
            content.addWidget(plan_hint)
            content.addWidget(QLabel("ÇALIŞMA PROFİLİ", objectName="FieldKey"))
            self._performance_preset = QComboBox(body)
            for label, value in (
                ("Otomatik · cihaz kaynaklarına göre", "auto"),
                ("Ekonomik · daha az kaynak", "eco"),
                ("Dengeli", "balanced"),
                ("Hız öncelikli", "fast"),
                ("Kalite öncelikli · gerekirse yavaş", "quality"),
            ):
                self._performance_preset.addItem(label, value)
            self._default_profile = _default("performance_preset", "auto")
            profile_index = self._performance_preset.findData(self._default_profile)
            self._performance_preset.setCurrentIndex(max(0, profile_index))
            content.addWidget(self._performance_preset)

        self._fields: dict[str, QLineEdit] = {}
        generation_rows = [
            ("num_ctx", "Başlangıç bağlamı (token)" if self._is_local else "Bağlam (token)", _default("num_ctx", 8192)),
            ("max_tokens", "Yanıt sınırı (token)", _default("max_tokens", self._record.get("max_output_tokens") or 1024)),
            ("temperature", "Sıcaklık", _default("temperature", 0.2)),
            ("top_p", "Top P", _default("top_p", 0.9)),
            ("top_k", "Top K", _default("top_k", 40)),
            ("repeat_penalty", "Tekrar cezası", _default("repeat_penalty", 1.1)),
        ]
        runtime_rows: list[tuple[str, str, Any]] = []
        if self._is_local:
            runtime_rows = [
                ("num_gpu", "GPU katmanı", _default("num_gpu", "auto")),
                ("num_thread", "CPU iş parçacığı", _default("num_thread", "auto")),
                ("num_batch", "İşleme grubu", _default("num_batch", 128)),
                ("seed", "Rastgelelik tohumu", _default("seed", "random")),
            ]
        rows = [*generation_rows, *runtime_rows]
        self._default_values = {key: value for key, _label, value in rows}
        self._active_resource_defaults = dict(self._default_values)
        supported_settings = self._supported_setting_names([key for key, _label, _value in rows])
        self._unsupported_fields: list[str] = []

        def _add_settings_group(target: QVBoxLayout, title_text: str, group_rows: list[tuple[str, str, Any]]) -> None:
            section = QLabel(title_text)
            section.setObjectName("FieldKey")
            target.addWidget(section)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            target.addLayout(grid)
            for index, (key, label_text, value) in enumerate(group_rows):
                column = index % 2
                row = (index // 2) * 2
                label = QLabel(label_text.upper())
                label.setObjectName("FieldKey")
                field = QLineEdit(str(value))
                field.setObjectName(f"AiAdvanced_{key}")
                field.setToolTip({
                    "num_ctx": "Sohbet geçmişi, talimatlar ve yanıtın toplam token bütçesi. Daha büyük bağlam daha fazla bellek kullanır.",
                    "max_tokens": "Tek yanıtta üretilebilecek en fazla token. Bağlam alanında yanıt için yer bırakın.",
                    "num_gpu": "GPU'ya aktarılacak katman sayısı. 0 yalnız CPU kullanır; auto kaynak planına bırakır.",
                    "num_thread": "CPU iş parçacığı sayısı. auto cihaz kaynaklarına göre seçer.",
                    "num_batch": "Birlikte işlenen token sayısı. Daha büyük değer daha çok bellek kullanır.",
                }.get(key, ""))
                if key not in supported_settings:
                    field.setEnabled(False)
                    field.setToolTip("Seçili model/provider bu ayarı desteklediğini bildirmiyor.")
                    field.setProperty("unsupported", True)
                    self._unsupported_fields.append(key)
                grid.addWidget(label, row, column)
                grid.addWidget(field, row + 1, column)
                self._fields[key] = field
                if self._performance_preset is not None and key in {"num_ctx", "max_tokens", "num_gpu", "num_thread", "num_batch"}:
                    field.textEdited.connect(self._mark_manual_resource_settings)

        _add_settings_group(content, "BAĞLAM VE YANIT", generation_rows[:2])
        advanced_button = QPushButton("Diğer üretim ve donanım ayarları ▸")
        advanced_button.setObjectName("Secondary")
        advanced_button.setCheckable(True)
        content.addWidget(advanced_button)
        self._advanced_fields_panel = QWidget(body)
        advanced_layout = QVBoxLayout(self._advanced_fields_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(10)
        _add_settings_group(advanced_layout, "ÜRETİM", generation_rows[2:])
        if runtime_rows:
            _add_settings_group(advanced_layout, "DONANIM", runtime_rows)
        content.addWidget(self._advanced_fields_panel)
        self._advanced_fields_panel.hide()
        advanced_button.toggled.connect(self._advanced_fields_panel.setVisible)
        advanced_button.toggled.connect(lambda checked: advanced_button.setText(
            "Diğer üretim ve donanım ayarları ▾" if checked else "Diğer üretim ve donanım ayarları ▸"
        ))
        if self._performance_preset is not None:
            self._performance_preset.currentIndexChanged.connect(self._apply_preset_defaults)
        if self._unsupported_fields:
            unsupported_hint = QLabel(
                "Bu modelde desteklenmeyen ayarlar pasif: "
                + ", ".join(self._unsupported_fields)
            )
            unsupported_hint.setObjectName("PopupHint")
            unsupported_hint.setWordWrap(True)
            content.addWidget(unsupported_hint)
        content.addStretch(1)
        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #B91C1C; font-size: 12px;")
        self.validation_label.hide()
        root.addWidget(self.validation_label)

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
        if self._performance_preset is not None:
            self._performance_preset.setCurrentIndex(max(0, self._performance_preset.findData(self._default_profile)))
        for key, value in self._default_values.items():
            field = self._fields.get(key)
            if field is not None:
                field.setText(str(value))
        self._active_resource_defaults = dict(self._default_values)
        self.validation_label.hide()

    def _mark_manual_resource_settings(self, *_args) -> None:
        if self._performance_preset is not None and self._performance_preset.currentData() == "auto":
            self._performance_preset.setCurrentIndex(self._performance_preset.findData("quality"))

    def _apply_preset_defaults(self, *_args) -> None:
        if self._performance_preset is None:
            return
        preset = self._performance_preset.currentData()
        if preset in {"auto", "eco", "balanced", "fast", "quality"}:
            context, output = {"eco": (4096, 1024), "fast": (4096, 1024),
                "balanced": (8192, 2048), "quality": (16384, 4096), "auto": (16384, 4096)}[preset]
            self._fields["num_ctx"].setText(str(context))
            self._fields["max_tokens"].setText(str(output))
            for key in ("num_ctx", "max_tokens"):
                self._active_resource_defaults[key] = self._fields[key].text()

    @staticmethod
    def _parsed_value(value: str) -> Any:
        clean = str(value or "").strip()
        if not clean:
            return None
        if clean.casefold() in {"auto", "automatic", "random", "rastgele"}:
            return clean.casefold()
        try:
            return float(clean.replace(",", ".")) if "." in clean or "," in clean else int(clean)
        except ValueError:
            return clean

    def _apply(self) -> None:
        payload = {
            key: self._parsed_value(field.text())
            for key, field in self._fields.items()
            if field.isEnabled()
        }
        ranges = {
            "num_ctx": (512, 1_048_576), "max_tokens": (1, 1_048_576),
            "temperature": (0, 2), "top_p": (0, 1), "top_k": (0, 10_000),
            "repeat_penalty": (0.01, 10), "num_gpu": (0, 999),
            "num_thread": (1, 1024), "num_batch": (1, 8192), "seed": (-1, 2 ** 32 - 1),
        }
        integer_fields = {"num_ctx", "max_tokens", "top_k", "num_gpu", "num_thread", "num_batch", "seed"}
        if self._is_local:
            ranges["num_ctx"] = (2048, 32768)
            ranges["max_tokens"] = (128, 8192)
        for key, value in payload.items():
            if key in {"num_gpu", "num_thread"} and value in {"auto", "automatic"}:
                continue
            if key == "seed" and value in {"random", "rastgele"}:
                continue
            lower, upper = ranges[key]
            if not isinstance(value, (int, float)) or not lower <= value <= upper or (key in integer_fields and not isinstance(value, int)):
                self.validation_label.setText(f"{key}: {lower:,} ile {upper:,} arasında geçerli bir sayı girin.")
                self.validation_label.show()
                self._fields[key].setFocus()
                return
        if payload.get("max_tokens", 0) >= payload.get("num_ctx", 1_048_577):
            self.validation_label.setText("Yanıt sınırı bağlamdan küçük olmalı; talimatlar ve mesajlar için yer bırakın.")
            self.validation_label.show()
            return
        if self._performance_preset is not None:
            if any(self._fields[key].text().strip() != str(self._active_resource_defaults[key]) for key in ("num_ctx", "max_tokens", "num_gpu", "num_thread", "num_batch")):
                self._mark_manual_resource_settings()
            payload["performance_preset"] = self._performance_preset.currentData()
        self._on_apply(payload)
        self.close()


class AITab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("AiRoot")

        self._models_worker: Optional[SyncWorker] = None
        self._model_hub_window: Optional[AIManagerDialog] = None
        self._splitter_guard = False
        self._left_stick_size = 242
        self._left_collapse_trigger = 90
        self._chat_message_count = 0
        self._chat_history: list[dict[str, Any]] = []
        self._conversation_state: dict[str, Any] = AgentSessionState(
            goal="OrderScout AI conversation",
            active_domain="orders",
        ).to_dict()
        self._chat_worker: Optional[SyncWorker] = None
        self._response_generation = 0
        self._response_active_token: int | None = None
        self._response_stream_id = ""
        self._response_closed_stream_ids: set[str] = set()
        self._response_pending: list[str] = []
        self._response_draft_text = ""
        self._response_draft_table = None
        self._response_draft_cell = None
        self._response_draft_label = None
        self._response_flush_timer = QTimer(self)
        self._response_flush_timer.setSingleShot(True)
        self._response_flush_timer.setInterval(40)
        self._response_flush_timer.timeout.connect(self._flush_chat_response)
        self._schedule_owner_id = "ai-ui-" + uuid4().hex
        self._schedule_last_error = ""
        self._task_control = None
        self._queued_guidance: list[str] = []
        self._action_worker: Optional[SyncWorker] = None
        self._providers_worker: Optional[SyncWorker] = None
        self._provider_catalog_worker: Optional[SyncWorker] = None
        self._cloud_price_filter = "all"
        self._provider_catalog_generation = 0
        self._pending_provider_records = None
        self._model_catalog_warning = ""
        self._cloud_catalog_stale = False
        self._model_filter_timer = QTimer(self)
        self._model_filter_timer.setSingleShot(True)
        self._model_filter_timer.setInterval(90)
        self._model_filter_timer.timeout.connect(self._filter_model_choices)
        self._cloud_model_groups: list[dict[str, Any]] = []
        self._cloud_routes_by_provider: dict[str, dict[str, Any]] = {}
        self._cloud_collapsed_provider_keys: set[str] = set()
        self._last_selected_cloud_model_id = ""
        self._selected_cloud_model_record: dict[str, Any] | None = None
        self._restored_model_choice: dict[str, Any] | None = None
        self._restoring_model_choice = False
        self._known_local_model_count: int | None = None
        self._known_provider_count: int | None = None
        self._advanced_dialog: Optional[_AdvancedModelSettingsDialog] = None
        self._models_bootstrapped = False
        self._resource_plan_cache: dict[str, Any] = {}
        self._resource_plan_worker: Optional[SyncWorker] = None
        self._chat_progress_timer: Optional[QTimer] = None
        self._chat_progress_started_at = 0.0
        self._activity_runs: dict[str, dict[str, Any]] = {}
        self._activity_run_id = ""
        self._last_task_progress_message = ""
        self._last_chat_success = True
        self._agent_state: dict[str, Any] = {}
        self._approval_card_sequence = 0
        self._approval_card_actions: dict[str, dict[str, Any]] = {}
        self._latest_approval_card_token = ""
        self._superseded_actions: list[dict[str, Any]] = []
        self._delivered_artifacts: dict[str, dict[str, Any]] = {}
        self._shown_artifact_cards: set[str] = set()
        self._task_session_rows: list[dict[str, Any]] = []
        self._restored_task_session_ids: set[str] = set()
        self._is_disposing = False
        self._chat_persistence_error = ""
        self._chat_restore_failed = False
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
            QFrame#AiTaskState {
                background: #F8FAFC;
                border: 1px solid rgba(148, 163, 184, 0.32);
                border-radius: 6px;
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

        self.setStyleSheet(self.styleSheet() + """
            QFrame#AiControlBand { border-radius:13px; }
            QLabel#AiControlTitle { font-size:17px; font-weight:700; }
            QFrame#AiChatHeader QLabel#SectionTitle { font-size:13px; font-weight:600; }
            QPushButton#AiPlainButton { border:0; border-radius:7px; background:transparent;
                color:#64748B; font-size:11px; padding:5px 7px; }
            QPushButton#AiPlainButton:hover, QPushButton#AiModelPicker:hover { background:#EFF3F8; }
            QPushButton#AiPlainButton:disabled { color:#94A3B8; }
            QPushButton#AiModelPicker { background:transparent; border:0; border-radius:7px;
                color:#0F172A; font-size:12px; padding:6px 8px; font-weight:600; }
            QComboBox#AiConversationReasoning { background:transparent; border:0; border-radius:7px;
                color:#64748B; font-size:11px; padding:5px 7px; }
            QComboBox#AiConversationReasoning::drop-down { border:0; width:18px; }
            QFrame#AiModelPopup { background:#FFFFFF; border:1px solid #DDE5F0; border-radius:12px; }
            QFrame#AiModelPopup QLabel#SectionTitle { font-size:13px; font-weight:600; }
            QFrame#AiModelPopup QPushButton#AiSegment { min-height:28px; padding:0 8px; font-size:12px; }
            QLineEdit#AiModelSearch { border:1px solid #E2E8F0; border-radius:7px;
                background:#FFFFFF; color:#0F172A; padding:7px 9px; font-size:12px; }
            QFrame#AiModelPopup QListWidget#ModelList { border:0; padding:0; }
            QPushButton#AiComposerIcon { min-width:30px; max-width:30px; min-height:30px;
                max-height:30px; background:transparent; border:0; color:#64748B; font-weight:400; }
            QPushButton#AiSendButton { min-width:32px; max-width:32px; min-height:32px;
                max-height:32px; padding:0; border-radius:8px; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        root.addWidget(self._build_control_band())

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)
        root.addLayout(content_row, 1)

        self._model_popup = self._build_model_popup()
        self._tab_splitter = ResettableSplitter(Qt.Orientation.Horizontal)
        self._tab_splitter.setChildrenCollapsible(True)
        self._tab_splitter.setHandleWidth(6)
        self._tab_splitter.setCollapsible(0, True)
        self._tab_splitter.setCollapsible(1, False)
        self._tab_splitter.splitterMoved.connect(self._on_tab_splitter_moved)
        content_row.addWidget(self._tab_splitter, 1)

        self.conversation_sidebar = ConversationSidebar(self)
        self.conversation_sidebar.session_requested.connect(self._open_chat_session)
        self.conversation_sidebar.new_chat_requested.connect(self._reset_chat)
        self.conversation_sidebar.workflows_requested.connect(self._open_saved_workflows)
        self.conversation_sidebar.schedules_requested.connect(self._open_workflow_schedules)
        self._tab_splitter.addWidget(self.conversation_sidebar)
        self._tab_splitter.addWidget(self._build_chat_panel())
        self._tab_splitter.setStretchFactor(0, 0)
        self._tab_splitter.setStretchFactor(1, 1)
        self._tab_splitter.setSizes([242, 1000])

        self._sync_model_panel_mode()
        self._refresh_chat_surface()
        self._update_chat_controls()
        self._sync_sidebar_state_from_splitter()
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(30_000)
        self._schedule_timer.timeout.connect(self._poll_scheduled_workflows)
        self._schedule_timer.start()
        self._restore_active_chat_session()
        self._refresh_conversations()

    def _build_control_band(self) -> QWidget:
        band = QFrame(self)
        band.setObjectName("AiControlBand")
        band.setFixedHeight(55)
        layout = QHBoxLayout(band)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(10)
        icon = QLabel(band)
        icon.setPixmap(QPixmap(_ai_icon_path()).scaled(29, 29, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)
        layout.addWidget(QLabel("OrderScout AI", objectName="AiControlTitle"))
        layout.addStretch(1)
        self.resource_summary = QLabel("Kaynaklar hazır", objectName="StatusInfo")
        layout.addWidget(self.resource_summary)
        self.btn_model_hub = QPushButton("Model Hub", objectName="AiSecondary")
        self.btn_model_hub.clicked.connect(self._open_model_hub)
        self.btn_model_hub.setToolTip("Bağlantıları ve model indirmelerini yönet")
        layout.addWidget(self.btn_model_hub)
        return band

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._models_bootstrapped:
            return
        self._models_bootstrapped = True
        QTimer.singleShot(0, self._refresh_current_source)

    def _build_model_popup(self) -> QFrame:
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("AiModelPopup")
        popup.setFixedWidth(480)
        panel = QVBoxLayout(popup)
        self._model_panel_layout = panel
        panel.setContentsMargins(14, 12, 14, 12)
        panel.setSpacing(9)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Model seçimi", objectName="SectionTitle"), 1)
        close = QPushButton("×", objectName="AiPlainButton")
        close.setFixedSize(25, 25)
        close.setAccessibleName("Model menüsünü kapat")
        close.clicked.connect(popup.hide)
        heading.addWidget(close)
        panel.addLayout(heading)
        self.model_search = QLineEdit(popup)
        self.model_search.setObjectName("AiModelSearch")
        self.model_search.setPlaceholderText("Model veya geliştirici ara…")
        self.model_search.setAccessibleName("Model ara")
        self.model_search.setClearButtonEnabled(True)
        self.model_search.textChanged.connect(lambda: self._model_filter_timer.start())
        self.model_search.installEventFilter(self)
        panel.addWidget(self.model_search)
        source_shell = QFrame(popup, objectName="AiSegmentShell")
        source_layout = QHBoxLayout(source_shell)
        source_layout.setContentsMargins(3, 3, 3, 3)
        source_layout.setSpacing(4)
        self.source_button_group = QButtonGroup(self)
        self.source_button_group.setExclusive(True)
        self.btn_source_local = QPushButton("Yerel", objectName="AiSegment")
        self.btn_source_cloud = QPushButton("Bulut", objectName="AiSegment")
        for button, value in ((self.btn_source_cloud, AI_CHAT_SOURCE_CLOUD_VALUE),
                              (self.btn_source_local, AI_CHAT_SOURCE_LOCAL_VALUE)):
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, selected=value: self._set_source_from_segment(selected))
            self.source_button_group.addButton(button)
            source_layout.addWidget(button, 1)
        self.btn_source_local.setChecked(True)
        panel.addWidget(source_shell)
        self.source_combo = QComboBox(popup)
        self.source_combo.addItem(AI_CHAT_SOURCE_LOCAL_TEXT, AI_CHAT_SOURCE_LOCAL_VALUE)
        self.source_combo.addItem(AI_CHAT_SOURCE_CLOUD_TEXT, AI_CHAT_SOURCE_CLOUD_VALUE)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.source_combo.hide()
        self.cloud_filter_shell = QFrame(popup, objectName="AiSegmentShell")
        filters = QHBoxLayout(self.cloud_filter_shell)
        filters.setContentsMargins(3, 3, 3, 3)
        filters.setSpacing(3)
        self.cloud_price_button_group = QButtonGroup(self)
        self.cloud_price_button_group.setExclusive(True)
        self.cloud_price_buttons = {}
        for key, label in (("all", "Tümü"), ("free", "Ücretsiz"), ("paid", "Ücretli")):
            button = QPushButton(label, objectName="AiSegment")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, selected=key: self._set_cloud_price_filter(selected))
            self.cloud_price_button_group.addButton(button)
            self.cloud_price_buttons[key] = button
            filters.addWidget(button, 1)
        self.cloud_price_buttons["all"].setChecked(True)
        panel.addWidget(self.cloud_filter_shell)
        self.model_list = QListWidget(popup)
        self.model_list.setObjectName("ModelList")
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model_list.setAccessibleName("Modeller")
        self.model_list.setMouseTracking(True)
        self.model_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._model_choice_delegate = ModelChoiceDelegate(self.model_list)
        self.model_list.setItemDelegate(self._model_choice_delegate)
        self.model_list.itemSelectionChanged.connect(self._on_model_selection_changed)
        self.model_list.itemClicked.connect(self._on_model_list_item_clicked)
        self.model_list.itemActivated.connect(
            lambda item: self._on_model_list_item_clicked(item, keep_provider_focus=True)
        )
        panel.addWidget(self.model_list, 1)
        self.model_empty_state = QLabel("Aramana uygun model bulunamadı.", objectName="Muted")
        self.model_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.model_empty_state.setWordWrap(True)
        self.model_empty_state.hide()
        panel.addWidget(self.model_empty_state)
        self.btn_search_all_models = QPushButton("Tüm modellerde ara", objectName="AiPlainButton")
        self.btn_search_all_models.clicked.connect(lambda: self._set_cloud_price_filter("all"))
        self.btn_search_all_models.hide()
        panel.addWidget(self.btn_search_all_models)
        self.model_status = QLabel(AI_CHAT_MODEL_LIST_WAITING, objectName="Muted")
        self.model_status.setWordWrap(True)
        panel.addWidget(self.model_status)
        self.selected_model_hint = QLabel("", objectName="Muted")
        self.selected_model_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        panel.addWidget(self.selected_model_hint)
        self.selected_local_plan = QLabel("", objectName="Muted")
        self.selected_local_plan.setWordWrap(True)
        self.selected_local_plan.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel.addWidget(self.selected_local_plan)
        self.fallback_checkbox = QCheckBox("Limitte uygun modele geç", popup)
        self.fallback_checkbox.setChecked(True)
        self.fallback_checkbox.setToolTip("Limit dolarsa aynı sağlayıcı içindeki sıradaki uygun modele geç.")
        self.fallback_checkbox.toggled.connect(self._apply_simple_model_settings)
        panel.addWidget(self.fallback_checkbox)
        footer = QHBoxLayout()
        self.btn_advanced_model_settings = QPushButton("Gelişmiş ayarlar", objectName="AiPlainButton")
        self.btn_advanced_model_settings.clicked.connect(self._open_advanced_model_settings)
        footer.addWidget(self.btn_advanced_model_settings)
        footer.addStretch(1)
        self.btn_refresh_models = QPushButton("Yenile", objectName="AiPlainButton")
        self.btn_refresh_models.clicked.connect(self._refresh_current_source)
        footer.addWidget(self.btn_refresh_models)
        self.btn_open_model_hub = QPushButton("Model Hub ↗", objectName="AiPlainButton")
        self.btn_open_model_hub.clicked.connect(self._open_model_hub)
        footer.addWidget(self.btn_open_model_hub)
        panel.addLayout(footer)
        # Hidden metadata retains the shared selection/acceptance interfaces.
        for name, label in (("source_list_label", AI_CHAT_LOCAL_MODELS_LABEL),
                            ("local_count_pill", ""), ("active_source_pill", ""),
                            ("brain_label", ""), ("runner_status", "")):
            widget = QLabel(label, popup)
            widget.hide()
            setattr(self, name, widget)
        popup.hide()
        return popup

    def _filter_model_choices(self, *_args) -> None:
        if self._is_disposing:
            return
        self._model_filter_timer.stop()
        terms = search_text(self.model_search.text()).split()
        headers, group_matches = [], {}
        available = matched = 0
        updates = self.model_list.updatesEnabled()
        self.model_list.setUpdatesEnabled(False)
        try:
            for index in range(self.model_list.count()):
                item = self.model_list.item(index)
                presentation = item.data(PRESENTATION_ROLE) or {}
                kind = presentation.get("kind")
                if kind == "cloud_provider_header":
                    headers.append(item)
                    continue
                # The small cached presentation avoids decoding full provider /
                # model metadata on every keystroke. Raw legacy rows still work.
                if not kind:
                    payload = item.data(Qt.ItemDataRole.UserRole) or {}
                    kind = payload.get("_source_kind", "local_model")
                    haystack = search_text(_model_display_name(payload))
                    is_free = bool((payload.get("model_metadata") or {}).get("is_free"))
                    group = self._cloud_provider_key(payload)
                else:
                    haystack = item.data(SEARCH_ROLE) or ""
                    is_free = presentation.get("is_free", False)
                    group = presentation.get("group", "")
                price_match = (kind != "cloud_model" or self._cloud_price_filter == "all"
                               or (self._cloud_price_filter == "free") == is_free)
                available += bool(price_match)
                match = price_match and all(term in haystack for term in terms)
                matched += bool(match)
                group_matches[group] = group_matches.get(group, False) or match
                # A search temporarily reveals matching models inside collapsed
                # providers without changing the user's saved collapse choice.
                visible = match and (bool(terms) or group not in self._cloud_collapsed_provider_keys or kind != "cloud_model")
                if item.isHidden() == visible:
                    item.setHidden(not visible)
            for header in headers:
                presentation = header.data(PRESENTATION_ROLE) or {}
                visible = not terms or group_matches.get(presentation.get("group"), False)
                if header.isHidden() == visible:
                    header.setHidden(not visible)
        finally:
            self.model_list.setUpdatesEnabled(updates)
        is_cloud = self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE
        empty = matched == 0 and (self.model_list.count() > 0 or bool(terms))
        self.model_empty_state.setVisible(empty)
        filtered = is_cloud and self._cloud_price_filter != "all"
        self.model_empty_state.setText("Bu filtrede aramana uygun model bulunamadı." if filtered else "Aramana uygun model bulunamadı.")
        self.btn_search_all_models.setVisible(empty and filtered)
        if self.model_list.count():
            label = {"all": "Tümü", "free": "Ücretsiz", "paid": "Ücretli"}.get(self._cloud_price_filter, "Tümü") if is_cloud else "Yerel"
            count_text = f"{matched} / {available} model · {label}" if terms else f"{available} model · {label}"
            warning = self._model_catalog_warning if is_cloud else ""
            self.model_status.setText(count_text + (" · " + warning if warning else ""))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.model_search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in {Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self._filter_model_choices()
                rows = [self.model_list.item(index) for index in range(self.model_list.count())
                        if not self.model_list.item(index).isHidden()
                        and (self.model_list.item(index).data(PRESENTATION_ROLE) or {}).get("kind") != "cloud_provider_header"]
                if rows:
                    target = rows[-1] if key == Qt.Key.Key_Up else rows[0]
                    self.model_list.setCurrentItem(target)
                    self.model_list.scrollToItem(target)
                    if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                        self._on_model_list_item_clicked(target)
                    else:
                        self.model_list.setFocus()
                return True
        return super().eventFilter(watched, event)

    def _toggle_model_picker(self) -> None:
        if self._worker_is_running():
            return
        if self._model_popup.isVisible():
            self._model_popup.hide()
            return
        self._model_popup.adjustSize()
        anchor = self.btn_model_picker.mapToGlobal(QPoint(0, 0))
        screen = self.screen().availableGeometry()
        width = min(480, max(280, self.window().width() - 24), screen.width() - 24)
        self._model_popup.setFixedWidth(width)
        height = min(620, screen.height() - 24, max(320, self.window().height() - 96))
        self._model_popup.resize(width, height)
        x = min(max(screen.left() + 8, anchor.x()), screen.right() - width - 7)
        y = max(screen.top() + 8, anchor.y() - height - 9)
        self._model_popup.move(x, y)
        self._model_popup.show()
        # Establish viewport geometry before its first paint after a hidden
        # catalogue refresh.
        self.model_list.doItemsLayout()
        self.model_search.setFocus()

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
        is_local = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE) == AI_CHAT_SOURCE_LOCAL_VALUE
        self.btn_source_local.setChecked(is_local)
        self.btn_source_cloud.setChecked(not is_local)
        self.cloud_filter_shell.setVisible(not is_local)
        self.fallback_checkbox.setVisible(not is_local)
        self.selected_local_plan.setVisible(is_local)
        self.model_list.setMinimumHeight(150)
        self.model_list.setMaximumHeight(380)

    def _set_cloud_price_filter(self, price_filter: str) -> None:
        clean = price_filter if price_filter in {"free", "paid", "all"} else "all"
        self._cloud_price_filter = clean
        for key, button in self.cloud_price_buttons.items():
            button.setChecked(key == clean)
        self._filter_model_choices()

    def _model_settings_target(self) -> tuple[QListWidgetItem | None, dict[str, Any] | None]:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(payload, dict) and payload.get("_source_kind") in {"local_model", "cloud_provider", "cloud_model"}:
            return item, payload
        payload = self._selected_provider_record()
        if payload is not None:
            for index in range(self.model_list.count()):
                candidate = self.model_list.item(index)
                record = candidate.data(Qt.ItemDataRole.UserRole) or {}
                if record.get("_source_kind") == "cloud_model" and record.get("id") == payload.get("id") and record.get("default_model") == payload.get("default_model"):
                    return candidate, record
        return None, payload

    def _apply_simple_model_settings(self, *_args) -> None:
        item, payload = self._model_settings_target()
        if not isinstance(payload, dict):
            return
        source_kind = _safe_text(payload.get("_source_kind"), "")
        if source_kind not in {"local_model", "cloud_provider", "cloud_model"}:
            return
        updated = dict(payload)
        if source_kind in {"cloud_provider", "cloud_model"}:
            updated.pop("free_model_test_route", None)
        updated["reasoning_effort"] = str(self.reasoning_combo.currentData() or "auto")
        updated["allow_model_fallback"] = bool(self.fallback_checkbox.isChecked())
        if source_kind == "local_model":
            updated["runtime_config"] = {**dict(updated.get("runtime_config") or {}), "reasoning_effort": updated["reasoning_effort"]}
            if isinstance(updated.get("resource_plan"), dict):
                updated["resource_plan"] = {**updated["resource_plan"], "reasoning_effort": updated["reasoning_effort"]}
        if item is not None:
            item.setData(Qt.ItemDataRole.UserRole, updated)
        if source_kind in {"cloud_provider", "cloud_model"}:
            self._selected_cloud_model_record = updated
        self._resource_plan_cache.clear()
        self._update_chat_controls()

    def _open_advanced_model_settings(self) -> None:
        self._model_popup.hide()
        item, payload = self._model_settings_target()
        if not isinstance(payload, dict):
            self.model_status.setText("Önce bu sohbet için bir model seç.")
            return
        source_kind = _safe_text(payload.get("_source_kind"), "")
        if source_kind not in {"local_model", "cloud_provider", "cloud_model"}:
            self.model_status.setText("Provider başlığı değil, provider altındaki modeli seç.")
            return
        if self._advanced_dialog is not None:
            self._advanced_dialog.close()
        target_index = QPersistentModelIndex(self.model_list.indexFromItem(item)) if item is not None else None
        target_identity = (payload.get("_source_kind"), payload.get("id"), payload.get("default_model"))

        def _apply_to_original_selection(values: dict[str, Any]) -> None:
            # A catalogue refresh can replace the list while this dialog is open.
            # Never retain a QListWidgetItem across that asynchronous boundary.
            if target_index is not None:
                if not target_index.isValid():
                    self.model_status.setText("Model listesi değişti; ayarları yeniden aç.")
                    return
                target = self.model_list.item(target_index.row())
            else:
                selected = self._selected_provider_record() or {}
                if (selected.get("_source_kind"), selected.get("id"), selected.get("default_model")) != target_identity:
                    self.model_status.setText("Seçili model değişti; ayarları yeniden aç.")
                    return
                target = None
            self._apply_advanced_model_settings(target, values)

        self._advanced_dialog = _AdvancedModelSettingsDialog(
            self,
            record=dict(payload),
            is_local=source_kind == "local_model",
            on_apply=_apply_to_original_selection,
        )
        anchor = self.btn_model_picker.mapToGlobal(QPoint(0, -8))
        self._advanced_dialog.adjustSize()
        bounds = self.window().frameGeometry()
        self._advanced_dialog.move(
            max(bounds.left(), min(anchor.x(), bounds.right() - self._advanced_dialog.width() + 1)),
            max(bounds.top(), min(anchor.y() - self._advanced_dialog.height(), bounds.bottom() - self._advanced_dialog.height() + 1)),
        )
        self._advanced_dialog.finished.connect(lambda *_: setattr(self, "_advanced_dialog", None))
        self._advanced_dialog.show()

    def _apply_advanced_model_settings(
        self,
        item: QListWidgetItem | None,
        values: dict[str, Any],
    ) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else self._selected_provider_record()
        if not isinstance(payload, dict):
            return
        updated = {**payload, **{key: value for key, value in values.items() if value is not None}}
        if _safe_text(payload.get("_source_kind"), "") in {"cloud_provider", "cloud_model"}:
            updated.pop("free_model_test_route", None)
        if _safe_text(payload.get("_source_kind"), "") == "local_model":
            runtime_keys = {"num_ctx", "max_tokens", "num_gpu", "num_thread", "num_batch", "performance_preset"}
            config = dict(payload.get("runtime_config") or {})
            config.update({key: value for key, value in values.items() if key in runtime_keys and value is not None})
            for key in ("num_gpu", "num_thread"):
                if str(config.get(key) or "").casefold() in {"auto", "automatic"}:
                    config.pop(key, None)
            updated["runtime_config"] = config
            updated["resource_plan"] = {
                "safe_to_run": False, "profile": "planning", "reason": "Kaynak planı hesaplanıyor…",
                "num_ctx": values.get("num_ctx") or 8192, "max_tokens": values.get("max_tokens") or 1024,
            }
        updated["reasoning_effort"] = str(self.reasoning_combo.currentData() or "auto")
        updated["allow_model_fallback"] = bool(self.fallback_checkbox.isChecked())
        if _safe_text(payload.get("_source_kind"), "") == "local_model":
            updated["runtime_config"]["reasoning_effort"] = updated["reasoning_effort"]
        if item is not None:
            item.setData(Qt.ItemDataRole.UserRole, updated)
        if _safe_text(payload.get("_source_kind"), "") in {"cloud_provider", "cloud_model"}:
            self._selected_cloud_model_record = updated
        self._resource_plan_cache.clear()
        self.model_status.setText("Gelişmiş ayarlar yalnız bu sohbete uygulandı.")
        self._update_chat_controls()
        if _safe_text(payload.get("_source_kind"), "") == "local_model":
            self._rebuild_local_plan_preview(updated)

    def _rebuild_local_plan_preview(self, updated: dict[str, Any]) -> None:
        """Keep hardware inspection off the Qt thread, and reject stale list results."""
        if self._resource_plan_worker is not None:
            return
        record = dict(updated)
        record.pop("resource_plan", None)
        key = tuple(str(record.get(field) or "") for field in ("repo_id", "filename", "local_path"))
        self._resource_plan_worker = SyncWorker(
            lambda: Result.ok(close_dialog=False, data={"plan": build_local_resource_plan(record).to_dict()}),
            parent=self,
        )

        def _done(result: Result) -> None:
            if self._is_disposing:
                return
            plan = dict((result.data or {}).get("plan") or {}) if result.success else {
                "safe_to_run": False, "profile": "plan_failed", "reason": result.message,
                "num_ctx": record.get("num_ctx") or 8192, "max_tokens": record.get("max_tokens") or 1024,
            }
            for index in range(self.model_list.count()):
                target = self.model_list.item(index)
                payload = target.data(Qt.ItemDataRole.UserRole)
                if not isinstance(payload, dict):
                    continue
                candidate = tuple(str(payload.get(field) or "") for field in ("repo_id", "filename", "local_path"))
                if candidate != key or payload.get("runtime_config") != record.get("runtime_config"):
                    continue
                payload["resource_plan"] = plan
                target.setData(Qt.ItemDataRole.UserRole, payload)
                self._install_model_item_widget(target, payload)
            self._resource_plan_cache.clear()
            self._refresh_model_row_selection()
            self._update_chat_controls()

        def _finished() -> None:
            self._resource_plan_worker = None
            if not self._is_disposing:
                self._update_chat_controls()

        self._resource_plan_worker.result_ready.connect(_done)
        self._resource_plan_worker.finished.connect(_finished)
        self._resource_plan_worker.start()
        self._update_chat_controls()

    def _build_chat_panel(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("SectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_frame = QFrame(card)
        header_frame.setObjectName("AiChatHeader")
        header_frame.setFixedHeight(56)
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(15, 8, 15, 8)
        header.setSpacing(10)
        self.btn_toggle_history = QPushButton(objectName="AiPlainButton")
        self.btn_toggle_history.setIcon(_chat_icon("panel"))
        self.btn_toggle_history.setFixedSize(32, 32)
        self.btn_toggle_history.clicked.connect(self._toggle_task_history)
        header.addWidget(self.btn_toggle_history)
        self.chat_title = QLabel("Yeni sohbet", objectName="SectionTitle")
        self.chat_title.setTextFormat(Qt.TextFormat.PlainText)
        self.chat_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.chat_title.setMinimumWidth(0)
        header.addWidget(self.chat_title, 1)
        self.btn_run_details = QPushButton("İşlem ayrıntıları", objectName="AiPlainButton")
        self.btn_run_details.setIcon(_chat_icon("steps"))
        self.btn_run_details.clicked.connect(self._toggle_current_run_details)
        self.btn_run_details.setEnabled(False)
        header.addWidget(self.btn_run_details)
        self.btn_new_chat = QPushButton(objectName="AiPlainButton")
        self.btn_new_chat.setIcon(_chat_icon("plus"))
        self.btn_new_chat.setFixedSize(32, 32)
        self.btn_new_chat.setAccessibleName("Yeni sohbet")
        self.btn_new_chat.setToolTip("Yeni sohbet")
        self.btn_new_chat.clicked.connect(self._reset_chat)
        header.addWidget(self.btn_new_chat)
        self.chat_status = QLabel(AI_CHAT_STATUS_WAITING, card)
        self.chat_status.hide()
        self.btn_saved_tasks = self.btn_toggle_history
        self.btn_saved_workflows = self.conversation_sidebar.workflows_button
        self.btn_workflow_schedules = self.conversation_sidebar.schedules_button
        layout.addWidget(header_frame)

        work_body = QWidget(card)
        work_body_layout = QHBoxLayout(work_body)
        work_body_layout.setContentsMargins(0, 0, 0, 0)
        work_body_layout.setSpacing(0)
        surface = QFrame(work_body)
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
        self.transcript.setMaximumWidth(1120)
        transcript_row = QHBoxLayout()
        transcript_row.setContentsMargins(0, 0, 0, 0)
        transcript_row.addStretch(1)
        transcript_row.addWidget(self.transcript, 100)
        transcript_row.addStretch(1)
        transcript_layout.addLayout(transcript_row)

        self.chat_stack.addWidget(welcome_page)
        self.chat_stack.addWidget(transcript_page)
        surface_layout.addWidget(self.chat_stack_host, 1)

        composer_card = QFrame(surface)
        composer_card.setObjectName("AiComposerShell")
        composer_card.setFixedHeight(166)
        composer_card.setMaximumWidth(1000)
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

        self.composer_meta = QLabel(AI_CHAT_BRAIN_UNSELECTED, composer_card)
        self.composer_meta.setObjectName("StatusInfo")
        self.composer_meta.hide()
        self.btn_model_picker = QPushButton("Model seç", objectName="AiModelPicker")
        self.btn_model_picker.setIcon(_chat_icon("chevron"))
        self.btn_model_picker.setIconSize(QSize(13, 13))
        self.btn_model_picker.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.btn_model_picker.setAccessibleName("Model seçimi")
        self.btn_model_picker.setMinimumWidth(0)
        self.btn_model_picker.setMaximumWidth(260)
        self.btn_model_picker.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.btn_model_picker.clicked.connect(self._toggle_model_picker)
        actions.addWidget(self.btn_model_picker)
        self.reasoning_combo = ReasoningControl(composer_card)
        self.reasoning_combo.setObjectName("AiConversationReasoning")
        self.reasoning_combo.configure_efforts(["auto", "low", "medium", "high"])
        self.reasoning_combo.currentIndexChanged.connect(self._apply_simple_model_settings)
        self.reasoning_combo.setMaximumWidth(240)
        self.reasoning_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.reasoning_combo.setAccessibleName("Akıl yürütme düzeyi")
        self.reasoning_combo.show()
        actions.addWidget(self.reasoning_combo)
        actions.addStretch(1)

        self.btn_pause_task = QPushButton("Duraklat")
        self.btn_pause_task.setObjectName("AiSecondary")
        self.btn_pause_task.setToolTip("Tamamlanan adımlar kaydedildikten sonra çalışmayı duraklat")
        self.btn_pause_task.clicked.connect(self._request_task_pause)
        self.btn_pause_task.hide()
        actions.addWidget(self.btn_pause_task)

        self.btn_send = QPushButton()
        self.btn_send.setIcon(_chat_icon("arrow", "#FFFFFF"))
        self.btn_send.setAccessibleName("Gönder")
        self.btn_send.setToolTip("Gönder")
        self.btn_send.setObjectName("AiSendButton")
        self.btn_send.clicked.connect(self._send_message)
        actions.addWidget(self.btn_send)

        composer_layout.addLayout(actions)
        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(0, 0, 0, 0)
        composer_row.addStretch(1)
        composer_row.addWidget(composer_card, 100)
        composer_row.addStretch(1)
        surface_layout.addLayout(composer_row)
        work_body_layout.addWidget(surface, 1)
        self.run_activity_panel = RunActivityPanel(work_body)
        self.run_activity_panel.setFixedWidth(240)
        self.run_activity_panel.close_requested.connect(self.run_activity_panel.hide)
        self.run_activity_panel.hide()
        work_body_layout.addWidget(self.run_activity_panel)
        layout.addWidget(work_body, 1)
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
        self._refresh_chat_title()

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
        if self._is_conversation_list_open():
            self._close_conversation_list()
        else:
            self._open_conversation_list()

    def _toggle_current_run_details(self) -> None:
        if self._activity_run_id:
            self._on_transcript_anchor_clicked(QUrl("orderscout://activity/" + self._activity_run_id))

    def _refresh_conversations(self) -> None:
        if not hasattr(self, "conversation_sidebar"):
            return
        try:
            saved = list_chat_sessions(limit=100)
        except Exception as exc:
            self.conversation_sidebar.setToolTip("Sohbet listesi okunamadı: " + _safe_text(exc))
            return
        by_id = {str(row["session_id"]): dict(row) for row in self._task_session_rows if row.get("session_id")}
        by_id.update({str(row["session_id"]): dict(row) for row in saved})
        self._conversation_rows = by_id
        self.conversation_sidebar.set_sessions(list(by_id.values()),
                                              active_session_id=str(self._conversation_state.get("session_id") or ""))
        self._refresh_chat_title()

    def _refresh_chat_title(self) -> None:
        if not hasattr(self, "chat_title"):
            return
        first = next((str(row["content"]) for row in self._chat_history if row.get("role") == "user"), "")
        title = " ".join(first.split()) or "Yeni sohbet"
        self.chat_title.setText(title[:80] + ("…" if len(title) > 80 else ""))
        self.chat_title.setToolTip("<qt>" + html.escape(title) + "</qt>")

    def _open_chat_session(self, session_id: str) -> None:
        if self._worker_is_running() or session_id == self._conversation_state.get("session_id"):
            return
        if not self._persist_chat_session():
            return
        try:
            saved = load_chat_session(session_id)
            if saved is None:
                row = getattr(self, "_conversation_rows", {}).get(session_id)
                if not row:
                    raise FileNotFoundError(session_id)
                state = load_agent_task_state(session_id).to_dict()
                saved = {"state": state, "history": conversation_history(state), "composer_text": ""}
            data = _chat_data_from_task_result(Result.ok("Sohbet açıldı.", data={"state": saved["state"]}))
            # Commit the complete target snapshot before changing visible UI.
            # A failed switch must not erase either conversation's unsent draft.
            save_active_chat_session(saved["state"], saved["history"], composer_text=saved["composer_text"])
        except FileNotFoundError:
            self._append_chat_activity("Sohbet kaydı bulunamadı.", notice=True)
            return
        except Exception as exc:
            self._append_chat_activity("Sohbet açılamadı: " + _safe_text(exc), notice=True)
            return
        self._restore_task_chat_context(data, history=saved["history"], composer_text=saved["composer_text"], persist=False)
        self._refresh_conversations()

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
        self._chat_worker = _make_chat_worker(
            _run_scheduled_chat_with_runtime, parent=self, progress_callback_kw="progress_callback",
            lease=lease, scheduler=scheduler, source=source, runtime_record=dict(runtime_record),
            current_session=dict(self._conversation_state), allowed_scope_bindings=allowed_scope_bindings,
            task_control=self._task_control,
        )
        response_token = self._begin_chat_response(self._chat_worker)
        self._start_chat_progress()
        self._append_chat_activity("Planlı yönerge başladı; güncel kaynaklar okunacak, işlemler için yeniden onay istenecek.")
        def done(result: Result) -> None:
            if not self._complete_chat_response(response_token):
                return
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
            self._persist_chat_session()
        def finished() -> None:
            if not self._response_token_current(response_token):
                return
            self._finish_chat_response(response_token)
            self._chat_worker = None
            self._task_control = None
            self._finish_chat_progress(self._last_chat_success)
            self._update_chat_controls()
            if self._queued_guidance:
                QTimer.singleShot(0, self._run_queued_guidance)
        self._chat_worker.result_ready.connect(done)
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
            self.task_session_bar.hide()
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
        self._refresh_conversations()

    def _sync_task_session_controls(self) -> None:
        if hasattr(self, "btn_load_task_session") and hasattr(self, "task_session_combo"):
            self.btn_load_task_session.setEnabled(bool(self.task_session_combo.currentData()) and not self._worker_is_running())

    def _persist_chat_session(self) -> bool:
        if self._chat_restore_failed and not self._chat_history and not self.composer.toPlainText():
            return False
        try:
            save_active_chat_session(
                self._conversation_state, self._chat_history,
                composer_text=self.composer.toPlainText(), queued_guidance=self._queued_guidance,
            )
            self._chat_persistence_error = ""
            self._chat_restore_failed = False
            self._refresh_conversations()
            return True
        except Exception as exc:
            message = _safe_text(exc)
            if message != self._chat_persistence_error:
                self._append_chat_activity("Sohbet kaydedilemedi: " + message)
                self._chat_persistence_error = message
            return False

    def _restore_active_chat_session(self) -> None:
        try:
            saved = load_active_chat_session()
        except Exception as exc:
            self._chat_restore_failed = True
            self._append_chat_activity("Önceki sohbet açılamadı: " + _safe_text(exc))
            return
        if saved is None:
            return
        state = saved["state"]
        if not saved["history"] and not state.get("pending_actions"):
            self._conversation_state = dict(state)
            self.composer.setPlainText(saved["composer_text"])
            self._restore_chat_model_choice((state.get("active_entities") or {}).get("runtime_context") or {})
            return
        # Restore only data and current approval cards. Opening the tab never
        # submits a resume command or replays a saved tool call.
        data = _chat_data_from_task_result(Result.ok("Sohbet açıldı.", data={"state": state}))
        self._restore_task_chat_context(data, history=saved["history"], composer_text=saved["composer_text"])
        if saved.get("checkpoint_error"):
            self._append_chat_activity("Son görev kaydı okunamadı; sohbet yedeği açıldı.")
        if saved.get("recovered_user_messages"):
            self._append_chat_activity("Son gönderdiğin talimatlar korundu; devam etmek için yeni bir mesaj gönderebilirsin.")
        elif saved.get("resubmit_user_messages"):
            self._append_chat_activity("Son isteğin yazı alanında yeniden göndermeni bekliyor.")

    def _load_selected_task_session(self) -> None:
        if self._worker_is_running():
            self._append_chat_activity("Süren çalışma tamamlanınca başka bir sohbet açabilirsin.")
            return
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
        self._restore_task_chat_context(data)

    def _restore_task_chat_context(self, data: dict[str, Any], *, history: list[dict[str, Any]] | None = None,
                                   composer_text: str | None = None, persist: bool = True) -> None:
        if self._worker_is_running():
            self._append_chat_activity("Süren çalışma tamamlanınca başka bir sohbet açabilirsin.")
            return
        state = dict(data.get("state") or {}) if isinstance(data.get("state"), dict) else {}
        session_id = _safe_text(state.get("session_id"), "")
        if not session_id:
            self._append_chat_activity("Kayitli sohbet kimligi eksik.")
            return
        if (session_id == self._conversation_state.get("session_id") and session_id in self._restored_task_session_ids
                and state == self._conversation_state):
            self._append_chat_activity("Kayitli gorev zaten bu sohbette yuklu.")
            return
        try:
            restored_history = conversation_history(state) if history is None else [dict(row) for row in history]
            typed_state = AgentSessionState.from_dict(state)
        except Exception as exc:
            self._append_chat_activity("Kayitli sohbet açılamadı: " + _safe_text(exc))
            return

        active_entities = (
            dict(state.get("active_entities") or {})
            if isinstance(state.get("active_entities"), dict)
            else {}
        )
        self._invalidate_chat_response()
        self.transcript.clear()
        self._activity_runs.clear()
        self._chat_message_count = 0
        self._chat_history.clear()
        self._approval_card_actions.clear()
        self._latest_approval_card_token = ""
        self._superseded_actions.clear()
        self._delivered_artifacts.clear()
        self._shown_artifact_cards.clear()
        self._queued_guidance.clear()
        self.composer.clear()
        self._conversation_state = dict(state)
        self._restore_chat_model_choice(active_entities.get("runtime_context") or {})
        goal = _safe_text(state.get("goal"), "")
        if history is None and goal and not any(
            row.get("role") == "user" and row.get("content") == goal
            for row in restored_history
        ):
            restored_history.append({"role": "user", "content": goal})

        self._chat_history.extend(restored_history)
        answer = _safe_text(data.get("answer"), "")
        if answer and (not self._chat_history or self._chat_history[-1].get("role") != "assistant"
                       or self._chat_history[-1].get("content") != answer):
            self._chat_history.append({"role": "assistant", "content": answer})
        self._render_restored_chat_history(typed_state)

        action = typed_state.active_pending_action()
        presentation_state = {**state, "pending_actions": [action] if action else []}
        self._update_agent_state_from_result_data({**data, "state": presentation_state, "session_state": presentation_state})
        if action:
            self._show_action_approval_dialog(action)
            self._append_chat_activity("Kayitli gorev onay bekleyen adimdan devam etmeye hazir.")
        else:
            self._append_chat_activity("Kayitli gorev baglami sohbete geri yuklendi.")
            if state.get("status") in {"running", "paused", "interrupted"} and self._chat_history:
                control = active_entities.get("task_control") or {}
                guidance = [message for message in control.get("queued_user_messages") or []
                            if isinstance(message, str) and message.strip()]
                if control.get("reason") == "user_revision" and guidance:
                    self.composer.setPlainText("\n".join(guidance))
                    self._append_chat_message("assistant", "Yarım kalan çalışma ve son talimatların açıldı. Yazı alanındaki talimatı göndererek güncellenmiş hedefle devam edebilirsin.")
                else:
                    self._append_chat_message("assistant", "Yarım kalan çalışma açıldı. ‘Devam et’ yazdığında kalan okuma adımlarını sürdürebilirim.")
        self._restored_task_session_ids.add(session_id)
        self._append_verified_artifact_links(data)
        if composer_text is not None:
            self.composer.setPlainText(composer_text)
        self._update_chat_controls()
        if persist:
            self._persist_chat_session()

    def _render_restored_chat_history(self, state: AgentSessionState) -> None:
        from AI.processors.observation_context import verified_export_report_receipts

        receipts = verified_export_report_receipts(state)
        document = self.transcript.document()
        cursor = QTextCursor(document)
        document.setLayoutEnabled(False)
        cursor.beginEditBlock()
        try:
            for row in self._chat_history:
                cursor.insertHtml(self._chat_message_html(row["role"], row["content"], receipts=receipts))
                cursor.insertText("\n")
        finally:
            cursor.endEditBlock()
            document.setLayoutEnabled(True)
        self._chat_message_count = len(self._chat_history)
        self._refresh_chat_surface()
        self._restore_transcript_scroll((0, True))

    def _format_chat_elapsed(self) -> str:
        run = self._activity_runs.get(self._activity_run_id, {})
        started = run.get("started_at") or self._chat_progress_started_at
        elapsed = time.monotonic() - started if started else 0.0
        return f"{int(max(0, run.get('elapsed_seconds', elapsed)))} sn"

    def _worker_is_running(self) -> bool:
        for worker in (self._chat_worker, self._action_worker):
            if worker is not None and worker.isRunning():
                return True
        return False

    def _new_activity_run(self) -> None:
        self._activity_run_id = uuid4().hex
        self._activity_runs[self._activity_run_id] = {
            "status": "Yanıt bekleniyor", "started_at": time.monotonic(),
            "active": True, "messages": [], "cursor": None,
        }
        self._last_task_progress_message = ""
        # Bound presentation-only records; model history is managed separately.
        while len(self._activity_runs) > 100:
            del self._activity_runs[next(iter(self._activity_runs))]
        self.run_activity_panel.hide()

    def _activity_marker_html(self) -> str:
        if not self._activity_run_id:
            return ""
        return ("<div style='font-size:11px;color:#64748B;margin-top:10px;'>"
                f"activity-status-{self._activity_run_id}</div>")

    def _bind_activity_cursor(self) -> None:
        run = self._activity_runs.get(self._activity_run_id)
        if run is None:
            return
        cursor = self.transcript.document().find("activity-status-" + self._activity_run_id)
        if not cursor.isNull():
            run["cursor"] = cursor
            self._render_activity_status()

    def _render_activity_status(self) -> None:
        run = self._activity_runs.get(self._activity_run_id)
        if not run:
            return
        cursor = run.get("cursor")
        if cursor is not None and not cursor.isNull():
            scroll_state = self._transcript_scroll_state()
            status = html.escape(str(run["status"]))
            elapsed = self._format_chat_elapsed()
            href = "orderscout://activity/" + self._activity_run_id
            indicator = "◌" if run["active"] else "·"
            start = cursor.selectionStart()
            cursor.insertHtml(
                f'<span style="font-size:11px;color:#64748B;">{indicator} &nbsp;{status}'
                f' &nbsp;· {elapsed} &nbsp;&nbsp; '
                f'<a href="{href}" style="color:#64748B;text-decoration:none;">İşlem ayrıntıları ›</a></span>'
            )
            cursor.setPosition(start, QTextCursor.MoveMode.KeepAnchor)
            self._restore_transcript_scroll(scroll_state)
        if self.run_activity_panel.isVisible() and self.run_activity_panel.run_id == self._activity_run_id:
            self._load_activity_panel(self._activity_run_id)

    def _load_activity_panel(self, run_id: str) -> None:
        run = self._activity_runs.get(run_id)
        if not run:
            return
        seconds = run.get("elapsed_seconds", max(0, time.monotonic() - run["started_at"]))
        self.run_activity_panel.set_run(
            run_id, status=run["status"], elapsed=f"{int(seconds)} sn",
            messages=list(run["messages"]), active=run["active"],
        )

    def _set_run_status(self, label: str) -> None:
        run = self._activity_runs.get(self._activity_run_id)
        if run and run["status"] != label:
            run["status"] = label
            self._render_activity_status()

    def _record_run_activity(self, message: str) -> None:
        run = self._activity_runs.get(self._activity_run_id)
        if not run:
            return
        messages = run["messages"]
        message = message[:4000]
        if not messages or messages[-1] != message:
            messages.append(message)
            del messages[:-100]
        self._render_activity_status()

    def _start_chat_progress(self, estimated_seconds: float | None = None) -> None:
        # The optional argument is accepted for older callers; no time-based
        # completion estimate or invented phases are presented to the user.
        if not self._activity_runs.get(self._activity_run_id, {}).get("active"):
            self._new_activity_run()
        if self._chat_progress_timer is None:
            self._chat_progress_timer = QTimer(self)
            self._chat_progress_timer.setInterval(1000)
            self._chat_progress_timer.timeout.connect(self._advance_chat_progress)
        self._chat_progress_started_at = time.monotonic()
        self._ensure_chat_response_draft()
        self._chat_progress_timer.start()

    def _advance_chat_progress(self) -> None:
        run = self._activity_runs.get(self._activity_run_id)
        if run and run["active"]:
            self._render_activity_status()

    def _finish_chat_progress(self, success: bool = True) -> None:
        if self._chat_progress_timer is not None:
            self._chat_progress_timer.stop()
        run = self._activity_runs.get(self._activity_run_id)
        if run:
            run["active"] = False
            run["elapsed_seconds"] = max(0, time.monotonic() - run["started_at"])
            state = str(self._conversation_state.get("status") or "")
            label = "Tamamlandı" if success else "Tamamlanamadı"
            if success and (self._pending_action_from_state() or state == "approval_required"):
                label = "Onay bekliyor"
            elif state == "paused":
                label = "Duraklatıldı"
            elif state == "interrupted":
                label = "Çalışma kesildi"
            run["status"] = label
            self._render_activity_status()

    def _hide_chat_progress_if_idle(self) -> None:
        if self._worker_is_running():
            return
        if self._chat_progress_timer is not None:
            self._chat_progress_timer.stop()
        self._chat_progress_started_at = 0.0

    def _transcript_scroll_state(self) -> tuple[int, bool]:
        scroll = self.transcript.verticalScrollBar()
        return scroll.value(), scroll.maximum() - scroll.value() <= 8

    def _restore_transcript_scroll(self, state: tuple[int, bool]) -> None:
        scroll = self.transcript.verticalScrollBar()
        scroll.setValue(scroll.maximum() if state[1] else state[0])

    def _append_transcript_html(self, block: str) -> None:
        scroll_state = self._transcript_scroll_state()
        cursor = QTextCursor(self.transcript.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(block)
        cursor.insertText("\n")
        self._restore_transcript_scroll(scroll_state)

    def _begin_chat_response(self, worker: SyncWorker) -> int:
        self._invalidate_chat_response()
        self._new_activity_run()
        token = self._response_generation
        self._response_active_token = token
        signal = getattr(worker, "response_event", None)
        if signal is not None and hasattr(signal, "connect"):
            callback = lambda event: self._on_response_stream_event(event, token=token)
            try:
                signal.connect(callback, Qt.ConnectionType.QueuedConnection)
            except TypeError:
                signal.connect(callback)
        progress_signal = getattr(worker, "progress", None)
        if progress_signal is not None and hasattr(progress_signal, "connect"):
            def progress(percent: int, message: str) -> None:
                if self._response_active_token == token and self._response_token_current(token):
                    self._on_task_progress(percent, message)
            try:
                progress_signal.connect(progress, Qt.ConnectionType.QueuedConnection)
            except TypeError:
                progress_signal.connect(progress)
        return token

    def _invalidate_chat_response(self) -> None:
        self._response_generation += 1
        self._response_active_token = None
        self._drop_chat_response_draft()
        self._response_stream_id = ""
        self._response_closed_stream_ids.clear()
        if self._chat_progress_timer is not None:
            self._chat_progress_timer.stop()
        run = self._activity_runs.get(self._activity_run_id)
        if run and run["active"]:
            run["active"] = False
            run["elapsed_seconds"] = max(0, time.monotonic() - run["started_at"])
        self._activity_run_id = ""
        self.run_activity_panel.hide()

    def _response_token_current(self, token: int) -> bool:
        return token == self._response_generation and not self._is_disposing

    def _complete_chat_response(self, token: int) -> bool:
        if token != self._response_active_token or not self._response_token_current(token):
            return False
        self._flush_chat_response()
        self._drop_chat_response_draft()
        self._response_active_token = None
        return True

    def _finish_chat_response(self, token: int) -> None:
        if not self._response_token_current(token) or self._response_active_token is None:
            return
        self._flush_chat_response()
        self._set_chat_response_label("Yanıt tamamlanamadı")
        self._last_chat_success = False
        self._response_active_token = None

    def _on_response_stream_event(self, event: dict[str, Any], *, token: int | None = None) -> None:
        token = self._response_active_token if token is None else token
        if token is None or token != self._response_active_token or not self._response_token_current(token):
            return
        if not isinstance(event, dict):
            return
        stream_id = str(event.get("stream_id") or "")
        kind = event.get("event")
        if not stream_id:
            return
        if kind == "start":
            if stream_id == self._response_stream_id or stream_id in self._response_closed_stream_ids:
                return
            if self._response_stream_id:
                self._response_closed_stream_ids.add(self._response_stream_id)
            self._drop_chat_response_draft()
            self._response_stream_id = stream_id
            self._set_run_status("Yanıt bekleniyor")
            if self._chat_progress_timer is not None and self._chat_progress_timer.isActive():
                self._ensure_chat_response_draft()
            return
        if stream_id != self._response_stream_id or stream_id in self._response_closed_stream_ids:
            return
        if kind == "delta":
            text = event.get("text")
            if not isinstance(text, str) or not text:
                return
            self._response_pending.append(text)
            if not self._response_draft_text:
                # Show the first actual fragment immediately. Subsequent fragments
                # share a timer, so a fast provider does not repaint each token.
                self._flush_chat_response()
            elif not self._response_flush_timer.isActive():
                self._response_flush_timer.start()
            self._set_run_status("Yanıt geliyor")
        elif kind in {"end", "error", "cancelled"}:
            self._flush_chat_response()
            self._response_closed_stream_ids.add(stream_id)
            label = {"end": "Yanıt kontrol ediliyor", "error": "Yanıt kesildi", "cancelled": "Yanıt durduruldu"}[kind]
            self._set_chat_response_label(label)

    def _ensure_chat_response_draft(self) -> None:
        if self._response_draft_cell is not None:
            return
        marker = "stream-draft-" + uuid4().hex
        label_marker = marker + "-label"
        self._append_transcript_html(_assistant_message_block(marker, label_marker,
                                                              activity_html=self._activity_marker_html()))
        document = self.transcript.document()
        # The label also contains marker, so find the body after the label.
        label = document.find(label_marker)
        content = document.find(marker, label.selectionEnd())
        inner_table = content.currentTable()
        self._response_draft_cell = inner_table.cellAt(content)
        table = inner_table
        while table.parentFrame() != document.rootFrame():
            table = table.parentFrame()
        self._response_draft_table = table
        content.removeSelectedText()
        self._response_draft_label = label
        label.insertText(AI_CHAT_ASSISTANT_ROLE_TEXT)
        self._bind_activity_cursor()
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _set_chat_response_label(self, label: str) -> None:
        self._set_run_status(label)

    def _flush_chat_response(self) -> None:
        self._response_flush_timer.stop()
        if not self._response_pending:
            return
        scroll_state = self._transcript_scroll_state()
        text = "".join(self._response_pending)
        self._response_pending.clear()
        self._ensure_chat_response_draft()
        # Plain text insertion escapes HTML and never creates approval/file links.
        cursor = self._response_draft_cell.lastCursorPosition()
        cursor.insertText(text)
        self._response_draft_text += text
        self._restore_transcript_scroll(scroll_state)

    def _drop_chat_response_draft(self) -> None:
        self._response_flush_timer.stop()
        self._response_pending.clear()
        table = self._response_draft_table
        if table is not None:
            run = self._activity_runs.get(self._activity_run_id)
            if run:
                run["cursor"] = None
            scroll_state = self._transcript_scroll_state()
            cursor = QTextCursor(self.transcript.document())
            cursor.setPosition(table.firstPosition() - 1)
            cursor.setPosition(table.lastPosition() + 1, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            self._chat_message_count = max(0, self._chat_message_count - 1)
            self._restore_transcript_scroll(scroll_state)
        self._response_draft_table = None
        self._response_draft_cell = None
        self._response_draft_label = None
        self._response_draft_text = ""

    def _append_chat_message(self, role: str, message: str) -> None:
        role = str(role).strip().lower()
        receipts = []
        if role == "assistant" and any(
            isinstance(row, dict) and row.get("tool_names") == ["execute_approved_operation"]
            for row in (self._conversation_state.get("last_tool_results") or ())
        ):
            from AI.processors.observation_context import verified_export_report_receipts
            receipts = verified_export_report_receipts(AgentSessionState.from_dict(self._conversation_state))
        self._append_transcript_html(self._chat_message_html(role, message, receipts=receipts))
        if role == "assistant":
            self._bind_activity_cursor()
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _chat_message_html(self, role: str, message: str, *, receipts: list[dict[str, Any]]) -> str:
        role = str(role).strip().lower()
        if role == "assistant" and receipts:
            from AI.runtime.artifact_delivery import verified_file_message_html
            safe_message, linked = verified_file_message_html(message, receipts)
            self._delivered_artifacts.update(linked)
        else:
            safe_message = html.escape(str(message or "").strip()).replace("\n", "<br>")
        if role == "user":
            return (
                '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 18px 0;">'
                '<tr><td width="48%"></td><td align="right">'
                f'<div style="font-size:11px;color:#64748B;font-weight:800;margin-bottom:4px;">{AI_CHAT_USER_ROLE_TEXT}</div>'
                '<table width="100%" cellspacing="0" cellpadding="14" bgcolor="#2563EB" '
                'style="background-color:#2563EB;border:1px solid #1D4ED8;color:#FFFFFF;">'
                f'<tr><td style="color:#FFFFFF;text-align:left;line-height:1.5;">{safe_message}</td></tr>'
                "</table></td></tr></table>"
            )
        run = self._activity_runs.get(self._activity_run_id)
        activity = self._activity_marker_html() if run and run["active"] and run.get("cursor") is None else ""
        return _assistant_message_block(safe_message, activity_html=activity)

    def _append_chat_activity(self, message: str, *, notice: bool = False) -> None:
        safe_message = html.escape(str(message or "").strip()).replace("\n", "<br>")
        if not safe_message:
            return
        run = self._activity_runs.get(self._activity_run_id)
        if run and run["active"]:
            self._record_run_activity(str(message).strip())
            if not notice:
                return
        # Notices outside a running task remain visible, with no activity cards.
        block = f'<p style="color:#64748B;font-size:11px;margin:6px 0 10px 46px;">{safe_message}</p>'
        self._append_transcript_html(block)
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _append_verified_artifact_links(self, data: dict[str, Any]) -> None:
        """Deliver native files independently of model-authored filenames/paths."""
        from AI.processors.observation_context import verified_export_report_receipts
        raw_state = data.get("state") or data.get("session_state")
        if not isinstance(raw_state, dict):
            return
        receipts = verified_export_report_receipts(AgentSessionState.from_dict(raw_state))
        from AI.runtime.artifact_delivery import artifact_link_token
        for receipt in receipts:
            token = artifact_link_token(receipt)
            if token in self._shown_artifact_cards:
                continue
            self._delivered_artifacts[token] = dict(receipt)
            self._shown_artifact_cards.add(token)
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
            self._append_transcript_html(block)
            self._chat_message_count += 1
        self._refresh_chat_surface()

    def _on_task_progress(self, percent: int, message: str) -> None:
        clean_message = _safe_text(message, "")
        if not clean_message:
            return
        # Callback percentages describe orchestration, not measurable completion.
        # Only observed messages and elapsed wall time are shown.
        if not self._activity_run_id:
            self._start_chat_progress()
        label = clean_message
        if re.match(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\s", label):
            label = "İşlem yürütülüyor"
        self._set_run_status(label[:88] + ("…" if len(label) > 88 else ""))
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
        self._append_transcript_html(block)
        self._chat_message_count += 1
        self._refresh_chat_surface()

    def _on_transcript_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme().casefold() == "orderscout" and url.host().casefold() == "activity":
            run_id = url.path().strip("/")
            if run_id in self._activity_runs:
                if self.run_activity_panel.isVisible() and self.run_activity_panel.run_id == run_id:
                    self.run_activity_panel.hide()
                else:
                    self._load_activity_panel(run_id)
                    self.run_activity_panel.show()
            return
        if url.scheme().casefold() == "orderscout" and url.host().casefold() == "artifact":
            parts = [part for part in url.path().split("/") if part]
            receipt = self._delivered_artifacts.get(parts[1]) if len(parts) == 2 and parts[0] == "open" else None
            if not receipt:
                return
            path = Path(receipt["output_path"])
            if not path.is_file():
                self._append_chat_activity("Dosya bu konumda bulunamadı; taşınmış veya silinmiş olabilir.", notice=True)
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
            self._append_chat_activity("Bir islem zaten calisiyor; tamamlaninca tekrar deneyebilirsin.", notice=True)
            return
        card_action = self._approval_card_actions.get(card_token)
        pending_action = self._pending_action_from_state()
        if not card_action or not pending_action or not self._approval_actions_match(card_action, pending_action):
            self._append_chat_activity("Bu onay karti artik aktif degil.", notice=True)
            return
        reply = "Onayla ve çalıştır" if intent == "approve" else "Vazgeç"
        self._append_chat_message("user", reply)
        self._chat_history.append({"role": "user", "content": reply})
        self._handle_pending_action_reply(reply)
        self._persist_chat_session()

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
            self._append_chat_activity("Bir islem zaten calisiyor; yeni onay calistirilmadi.", notice=True)
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
        self._action_worker = _make_chat_worker(
            _run_approved_chat_action,
            dict(action),
            parent=self,
            progress_callback_kw="progress_callback",
        )
        response_token = self._begin_chat_response(self._action_worker)
        self._start_chat_progress()
        self._update_chat_controls()

        def _done(execute_result: Result) -> None:
            if not self._complete_chat_response(response_token):
                return
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
            self._persist_chat_session()

        def _finished() -> None:
            if not self._response_token_current(response_token):
                return
            self._finish_chat_response(response_token)
            self._action_worker = None
            self._finish_chat_progress(self._last_chat_success)
            self._update_chat_controls()

        self._action_worker.result_ready.connect(_done)
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
        kind = payload.get("_source_kind", "local_model")
        title = str(payload.get("label") or "Bağlantı") if kind == "cloud_provider_header" else _model_display_name(payload)
        plan = payload.get("resource_plan") or {}
        context = plan.get("num_ctx") or payload.get("num_ctx")
        local_meta = " · ".join(str(value) for value in (
            payload.get("size_text"), f"{context:,} bağlam" if context else None, plan.get("capacity_label")) if value)
        presentation = model_presentation(payload, title, local_meta)
        presentation.update(group=self._cloud_provider_key(payload),
                            is_free=bool((payload.get("model_metadata") or {}).get("is_free")))
        item.setData(PRESENTATION_ROLE, presentation)
        item.setData(SEARCH_ROLE, search_text(" ".join(str(value or "") for value in (
            title, payload.get("default_model"), payload.get("repo_id"), payload.get("filename"),
            payload.get("label"), payload.get("provider_code")))))
        # Native text retains accessibility; the delegate draws the visible row.
        item.setText(title)
        item.setToolTip("<br>".join(html.escape(str(value)) for value in (
            title, payload.get("default_model") or payload.get("repo_id") or "", presentation["meta"]) if value))

    def _refresh_model_row_selection(self) -> None:
        self._filter_model_choices()
        current = self.model_list.currentItem()
        payload = (self._selected_cloud_model_record if self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE
                   else current.data(Qt.ItemDataRole.UserRole) if current else None)
        self._model_choice_delegate.selected_identity = model_identity(payload) if payload else None
        self.selected_model_hint.setText("Seçili: " + _model_display_name(payload) if payload else "")
        self.selected_model_hint.setToolTip(_model_display_name(payload) if payload else "")
        self.model_list.viewport().update()

    def _refresh_current_source(self) -> None:
        if self._is_disposing:
            return
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        if source == AI_CHAT_SOURCE_CLOUD_VALUE:
            self._refresh_cloud_providers()
        else:
            self._refresh_local_models()

    def _restore_chat_model_choice(self, runtime: dict[str, Any]) -> None:
        """Restore a model identity; accounts and credentials still come from the current catalogue."""
        runtime = safe_agent_runtime_context(dict(runtime or {}))
        source = _safe_text(runtime.get("source"), "")
        model = _safe_text(runtime.get("model_name"), "")
        if source not in {AI_CHAT_SOURCE_CLOUD_VALUE, AI_CHAT_SOURCE_LOCAL_VALUE} or not model:
            self._restored_model_choice = None
            return
        choice = {"source": source, "model_name": model}
        if source == AI_CHAT_SOURCE_CLOUD_VALUE:
            provider_id = int(runtime.get("provider_id") or 0)
            if provider_id <= 0:
                self._restored_model_choice = None
                return
            choice["provider_id"] = provider_id
            self._selected_cloud_model_record = {
                "id": provider_id, "provider_code": _safe_text(runtime.get("provider_code"), ""),
                "label": _safe_text(runtime.get("provider_label") or runtime.get("provider_code"), ""),
                "default_model": model, "_source_kind": "cloud_model", "_explicit_runtime_override": True,
                "reasoning_effort": _safe_text(runtime.get("reasoning_effort"), "auto"),
                "model_metadata": dict(runtime.get("model_metadata") or {}),
                "allow_model_fallback": bool(runtime.get("allow_model_fallback", False)),
                "_selection_unavailable": "Kayıtlı modelin bağlantısı yükleniyor.",
            }
        else:
            choice["model_record"] = dict(runtime.get("model_record") or {})
        self._restored_model_choice = choice
        self._restoring_model_choice = True
        try:
            index = self.source_combo.findData(source)
            if index != self.source_combo.currentIndex():
                self.source_combo.setCurrentIndex(index)
            else:
                self._on_source_changed()
        finally:
            self._restoring_model_choice = False

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
            if self.source_combo.currentData() != AI_CHAT_SOURCE_LOCAL_VALUE:
                return
            from AI.processors.local_resources import local_model_sort_key
            records.sort(key=local_model_sort_key)
            previous = self.model_list.currentItem()
            selected_path = str((previous.data(Qt.ItemDataRole.UserRole) or {}).get("local_path") or "") if previous else ""
            restored = self._restored_model_choice or {}
            if restored.get("source") == AI_CHAT_SOURCE_LOCAL_VALUE:
                selected_path = str((restored.get("model_record") or {}).get("local_path") or restored["model_name"])
            self.model_list.clear()

            if not records:
                self.model_status.setText(AI_CHAT_EMPTY_LIBRARY_TEXT)
                self.local_count_pill.setText(AI_CHAT_LOCAL_COUNT_TEMPLATE.format(count=0))
                if restored.get("source") == AI_CHAT_SOURCE_LOCAL_VALUE:
                    self.model_status.setText("Kayıtlı yerel model bulunamadı; başka bir model seçin.")
                elif not self._auto_switched_to_cloud and self.source_combo.findData(AI_CHAT_SOURCE_CLOUD_VALUE) >= 0:
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
                selected_index = next((index for index, row in enumerate(records)
                    if selected_path and str(row.get("local_path") or "") == selected_path),
                    -1 if restored.get("source") == AI_CHAT_SOURCE_LOCAL_VALUE else 0)
                self.model_list.setCurrentRow(selected_index)
                if selected_index < 0:
                    self.model_status.setText("Kayıtlı yerel model bulunamadı; başka bir model seçin.")

            self._update_chat_controls()

        def _finished() -> None:
            self._models_worker = None
            self._update_chat_controls()

        self._models_worker.result_ready.connect(_done)
        self._models_worker.finished.connect(_finished)
        self._models_worker.start()

    def _refresh_cloud_providers(self) -> None:
        if self._is_disposing:
            return
        if self._providers_worker is not None and self._providers_worker.isRunning():
            return

        self._provider_catalog_generation += 1
        self._pending_provider_records = None
        self._cloud_catalog_stale = False
        generation = self._provider_catalog_generation

        self.source_list_label.setText(AI_CHAT_CLOUD_PROVIDERS_LABEL)
        self.model_status.setText(AI_CHAT_MODEL_LIST_WAITING)
        self.btn_refresh_models.setEnabled(False)
        self._providers_worker = SyncWorker(lambda: ai_actions.action_list_provider_accounts(include_secret=True), parent=self)

        def _done(result: Result) -> None:
            if self._is_disposing or generation != self._provider_catalog_generation:
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
            is_cloud = self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE

            if not records:
                if self._restored_model_choice and self._selected_cloud_model_record:
                    self._selected_cloud_model_record["_selection_unavailable"] = "Kayıtlı modelin bağlantısı bulunamadı; başka bir model seçin."
                else:
                    self._selected_cloud_model_record = None
                self._cloud_model_groups = []
                self._cloud_routes_by_provider = {}
                if is_cloud:
                    with QSignalBlocker(self.model_list):
                        self.model_list.clear()
                    self._refresh_model_row_selection()
                    self.model_status.setText(AI_CHAT_PROVIDER_EMPTY_TEXT)
                self.local_count_pill.setText(AI_CHAT_PROVIDER_COUNT_TEMPLATE.format(count=0))
            else:
                cached = {self._cloud_provider_key(group.get("provider") or {}): group for group in self._cloud_model_groups}
                groups = [{**cached.get(self._cloud_provider_key(record), {"models": [], "route": {}}),
                           "provider": record} for record in records]
                if is_cloud:
                    self._populate_cloud_model_list(groups)
                    self.model_status.setText("Model listesi güncelleniyor…")
                else:
                    self._cloud_model_groups = groups
                self.local_count_pill.setText(AI_CHAT_PROVIDER_COUNT_TEMPLATE.format(count=len(records)))
                self._refresh_provider_catalogs(records)

            self._update_chat_controls()

        def _finished() -> None:
            self._providers_worker = None
            self._update_chat_controls()

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
                free_only=False,
                limit=None,
            )
            if not catalog.success:
                errors.append(f"{_safe_text(provider.get('label'), code)}: {catalog.message}")
                groups.append({"provider": dict(provider), "models": [], "route": {}, "catalog_error": True})
                continue
            data = dict(catalog.data or {})
            models = [dict(row) for row in list(data.get("records") or []) if isinstance(row, dict)]
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
            self._pending_provider_records = (self._provider_catalog_generation, [dict(row) for row in records])
            return
        generation = self._provider_catalog_generation
        self._provider_catalog_worker = SyncWorker(
            self._provider_catalog_result,
            [dict(row) for row in records],
            parent=self,
        )

        def _done(result: Result) -> None:
            if self._is_disposing or not result.success or generation != self._provider_catalog_generation:
                return
            data = dict(result.data or {})
            groups = [dict(row) for row in list(data.get("groups") or []) if isinstance(row, dict)]
            cached = {self._cloud_provider_key(group.get("provider") or {}): group for group in self._cloud_model_groups}
            groups = [{**group, "models": cached.get(self._cloud_provider_key(group.get("provider") or {}), {}).get("models", [])}
                      if group.get("catalog_error") else group for group in groups]
            errors = list(data.get("errors") or [])
            self._model_catalog_warning = "Güncellenemedi; son liste" if errors else ""
            if self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE:
                self._populate_cloud_model_list(groups, catalog_complete=True)
            else:
                self._cloud_model_groups = groups
            self._update_chat_controls()

        def _finished() -> None:
            self._provider_catalog_worker = None
            if self._is_disposing:
                return
            pending = self._pending_provider_records
            self._pending_provider_records = None
            if pending and pending[0] == self._provider_catalog_generation:
                self._refresh_provider_catalogs(pending[1])
            self._update_chat_controls()

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
        catalog_complete: bool = False,
    ) -> None:
        selection_blocker = QSignalBlocker(self.model_list)
        preserve_model_id = preserve_model_id or str((self._selected_cloud_model_record or {}).get("default_model") or "")
        self._cloud_model_groups = [dict(group) for group in groups]
        self._cloud_routes_by_provider = {self._cloud_provider_key(group.get("provider") or {}): group.get("route") or {}
                                          for group in groups}
        preserved = dict(self._selected_cloud_model_record or {}) if preserve_model_id else {}
        if preserved.get("default_model") != preserve_model_id:
            preserved = {}
        restored = self._restored_model_choice or {}
        restoring_cloud = restored.get("source") == AI_CHAT_SOURCE_CLOUD_VALUE
        if preserved and not restoring_cloud and not any(
            self._cloud_provider_key(dict(group.get("provider") or {})) == self._cloud_provider_key(preserved)
            and (
                any(isinstance(model, dict) and model.get("id") == preserve_model_id for model in group.get("models") or [])
                or not group.get("models") and dict(group.get("provider") or {}).get("default_model") == preserve_model_id
            )
            for group in groups
        ):
            preserved = {}
        self._selected_cloud_model_record = preserved or None
        self.model_list.clear()
        first_model_row = -1
        selected_model_row = -1
        selected_provider_row = -1
        catalog_model_count = 0
        for group in groups:
            provider = dict(group.get("provider") or {})
            models = [dict(row) for row in list(group.get("models") or []) if isinstance(row, dict)]
            provider_key = self._cloud_provider_key(provider)
            collapsed = provider_key in self._cloud_collapsed_provider_keys
            header_payload = {
                **provider,
                "_source_kind": "cloud_provider_header",
                "_provider_key": provider_key,
                "_collapsed": collapsed,
                "_model_count": len(models),
            }
            header = QListWidgetItem(self._label_for_record(header_payload))
            header.setData(Qt.ItemDataRole.UserRole, header_payload)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.model_list.addItem(header)
            if preserved and provider_key == self._cloud_provider_key(preserved):
                selected_provider_row = self.model_list.count() - 1
            self._install_model_item_widget(header, header_payload)

            if not models and _safe_text(provider.get("default_model"), ""):
                models = [
                    {
                        "id": provider.get("default_model"),
                        "name": provider.get("default_model"),
                        # A configured name is not current pricing evidence.
                        "is_free": False,
                        "capability_profile": {},
                    }
                ]
            catalog_model_count += sum(bool(_safe_text(model.get("id"), "")) for model in models)
            for rank, model in enumerate(models):
                model_id = _safe_text(model.get("id"), "")
                if not model_id:
                    continue
                payload = {
                    **provider,
                    "_source_kind": "cloud_model",
                    "default_model": model_id,
                    "model_metadata": model,
                    "free_model_rank": rank,
                    "allow_model_fallback": bool(provider.get("allow_model_fallback", True)),
                    "_explicit_runtime_override": True,
                }
                if preserved and model_id == preserve_model_id and provider_key == self._cloud_provider_key(preserved):
                    # Keep this conversation's controls, while account fields
                    # (including refreshed credentials/endpoint) stay current.
                    payload.update({key: preserved[key] for key in (
                        "reasoning_effort", "allow_model_fallback", "num_ctx", "max_tokens",
                        "temperature", "top_p", "top_k", "repeat_penalty") if key in preserved})
                item = QListWidgetItem(self._label_for_record(payload))
                item.setData(Qt.ItemDataRole.UserRole, payload)
                self.model_list.addItem(item)
                self._install_model_item_widget(item, payload)
                if first_model_row < 0:
                    first_model_row = self.model_list.count() - 1
                if preserve_model_id and model_id == preserve_model_id and (not preserved or provider_key == self._cloud_provider_key(preserved)):
                    selected_model_row = self.model_list.count() - 1
        target_row = selected_model_row if selected_model_row >= 0 else selected_provider_row if selected_provider_row >= 0 else first_model_row
        if restoring_cloud:
            target_row = selected_model_row
            if selected_model_row < 0 and self._selected_cloud_model_record:
                matching = next((group for group in groups if self._cloud_provider_key(group.get("provider") or {})
                                 == str(restored["provider_id"])), None)
                if matching is None:
                    message = "Kayıtlı modelin bağlantısı bulunamadı; başka bir model seçin."
                elif matching.get("catalog_error"):
                    message = "Kayıtlı modelin kataloğu doğrulanamadı; listeyi yenileyin veya başka bir model seçin."
                elif catalog_complete or matching.get("models"):
                    message = "Kayıtlı model katalogda bulunamadı; başka bir model seçin."
                else:
                    message = "Kayıtlı modelin bağlantısı yükleniyor."
                self._selected_cloud_model_record["_selection_unavailable"] = message
        if target_row >= 0:
            self.model_list.setCurrentRow(target_row)
        elif restoring_cloud:
            self.model_list.setCurrentRow(-1)
        count = catalog_model_count
        self.model_status.setText(f"{count} model listeleniyor" if count else "Bu kaynakta uygun model bulunamadı.")
        selection_blocker.unblock()
        self._on_model_selection_changed()

    def _on_model_list_item_clicked(
        self, item: QListWidgetItem, *, keep_provider_focus: bool = False
    ) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict) or _safe_text(payload.get("_source_kind"), "") != "cloud_provider_header":
            self._model_popup.hide()
            return
        provider_key = _safe_text(payload.get("_provider_key"), "")
        if not provider_key:
            return
        if provider_key in self._cloud_collapsed_provider_keys:
            self._cloud_collapsed_provider_keys.discard(provider_key)
        else:
            self._cloud_collapsed_provider_keys.add(provider_key)
        # Keep every item alive through Qt's remaining click/activation slots.
        # Collapsing only changes visibility; it never rebuilds the catalogue.
        payload["_collapsed"] = provider_key in self._cloud_collapsed_provider_keys
        item.setData(Qt.ItemDataRole.UserRole, payload)
        presentation = item.data(PRESENTATION_ROLE) or {}
        presentation["collapsed"] = payload["_collapsed"]
        item.setData(PRESENTATION_ROLE, presentation)
        self._filter_model_choices()
        self.model_list.viewport().update()

    def _selected_local_record(self) -> dict[str, Any] | None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict) or str(payload.get("_source_kind") or "local_model") != "local_model":
            return None
        return payload if payload.get("repo_id") else None

    def _selected_provider_record(self) -> dict[str, Any] | None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict) or payload.get("_source_kind") == "cloud_provider_header":
            payload = self._selected_cloud_model_record if self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE else None
        if not isinstance(payload, dict):
            return None
        if str(payload.get("_source_kind") or "") not in {
            "cloud_provider",
            "cloud_model",
        }:
            return None
        if int(payload.get("id") or 0) <= 0:
            return None
        self._selected_cloud_model_record = {key: value for key, value in payload.items() if key != "free_model_test_route"}
        # Routing metadata describes the whole provider catalogue. Keep it once
        # in Python, never N times in Qt's per-row QVariant trees.
        selected = dict(self._selected_cloud_model_record)
        route = self._cloud_routes_by_provider.get(self._cloud_provider_key(payload))
        if route is not None:
            selected["free_model_test_route"] = route
        return selected

    def _resource_plan_for_record(self, record: dict[str, Any]):
        key = "|".join(
            _safe_text(record.get(field), "")
            for field in ("repo_id", "filename", "local_path", "size_bytes")
        )
        if key not in self._resource_plan_cache:
            plan_payload = record.get("resource_plan")
            if isinstance(plan_payload, dict) and "safe_to_run" in plan_payload:
                effective = {**plan_payload, "safe_to_run": bool(plan_payload.get("safe_to_run")),
                    "profile": _safe_text(plan_payload.get("profile"), "precomputed"),
                    "reason": _safe_text(plan_payload.get("reason"), ""),
                    "num_ctx": int(plan_payload.get("num_ctx") or 512),
                    "max_tokens": int(plan_payload.get("max_tokens") or 128)}
                self._resource_plan_cache[key] = SimpleNamespace(**effective)
            else:
                self._resource_plan_cache[key] = build_local_resource_plan(record)
        return self._resource_plan_cache[key]

    def _on_model_selection_changed(self) -> None:
        item = self.model_list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(payload, dict) and payload.get("_source_kind") == "cloud_provider_header":
            payload = self._selected_provider_record()
        if isinstance(payload, dict):
            restored = self._restored_model_choice or {}
            if payload.get("_source_kind") == "cloud_model" and restored.get("source") == AI_CHAT_SOURCE_CLOUD_VALUE:
                if (int(payload.get("id") or 0), payload.get("default_model")) != (restored["provider_id"], restored["model_name"]):
                    self._restored_model_choice = None
            elif payload.get("_source_kind") == "local_model" and restored.get("source") == AI_CHAT_SOURCE_LOCAL_VALUE:
                expected = (restored.get("model_record") or {}).get("local_path") or restored["model_name"]
                if payload.get("local_path") != expected:
                    self._restored_model_choice = None
            if _safe_text(payload.get("_source_kind"), "") == "cloud_model":
                self._last_selected_cloud_model_id = _safe_text(payload.get("default_model"), "")
                self._selected_cloud_model_record = dict(payload)
            self._sync_reasoning_choices(payload)
            self.fallback_checkbox.blockSignals(True)
            self.fallback_checkbox.setChecked(bool(payload.get("allow_model_fallback", True)))
            self.fallback_checkbox.blockSignals(False)
        self._refresh_model_row_selection()
        self._update_chat_controls()

    def _on_source_changed(self) -> None:
        if not self._restoring_model_choice:
            self._restored_model_choice = None
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        is_local = source == AI_CHAT_SOURCE_LOCAL_VALUE
        self._model_filter_timer.stop()
        with QSignalBlocker(self.model_search):
            self.model_search.clear()
        with QSignalBlocker(self.model_list):
            self.model_list.clear()
        self.model_list.setEnabled(True)
        self.btn_refresh_models.setEnabled(True)
        self.source_list_label.setText(AI_CHAT_LOCAL_MODELS_LABEL if is_local else AI_CHAT_CLOUD_PROVIDERS_LABEL)
        self.active_source_pill.setText(AI_CHAT_SOURCE_PILL_LOCAL_TEXT if is_local else AI_CHAT_SOURCE_PILL_CLOUD_TEXT)
        self.runner_status.setText(AI_CHAT_LOCAL_RUNNER_STATUS_TEXT if is_local else AI_CHAT_CLOUD_RUNNER_STATUS_TEXT)
        self._sync_model_panel_mode()
        if not is_local and self._cloud_model_groups:
            self._populate_cloud_model_list(self._cloud_model_groups)
            if self._cloud_catalog_stale:
                self._refresh_cloud_providers()
        else:
            self._refresh_current_source()
        self._update_chat_controls()

    def _sync_reasoning_choices(self, payload: dict[str, Any] | None) -> bool:
        """Use the same model capability contract as the provider transport."""
        payload = dict(payload or {})
        selected = _safe_text(payload.get("reasoning_effort") or
            dict(payload.get("runtime_config") or {}).get("reasoning_effort"), "auto").casefold()
        model_name = _model_display_name(payload) if payload else ""
        default_effort = ""
        if self.source_combo.currentData() == AI_CHAT_SOURCE_LOCAL_VALUE:
            capabilities = dict(payload.get("runtime_capabilities") or {})
            supported = capabilities.get("supports_reasoning_effort") is not False
            efforts = ["auto", "low", "medium", "high"] if supported else ["auto"]
        else:
            metadata = dict(payload.get("model_metadata") or {})
            reasoning = dict(metadata["reasoning"]) if isinstance(metadata.get("reasoning"), dict) else {}
            fresh_metadata = "supported_parameters" in metadata or bool(reasoning)
            resolved = provider_reasoning_capabilities(
                _safe_text(payload.get("provider_code"), ""),
                _safe_text(payload.get("default_model"), ""), model_metadata=metadata
            ) if fresh_metadata else dict(payload.get("reasoning_capabilities") or {}) or provider_reasoning_capabilities(
                _safe_text(payload.get("provider_code"), ""),
                _safe_text(payload.get("default_model"), ""), model_metadata=metadata)
            # A legacy/manual model entry without catalogue capabilities is
            # unknown, rather than evidence that reasoning is unsupported.
            known = bool(payload.get("reasoning_capabilities")) or "supported_parameters" in metadata or bool(reasoning)
            if known or resolved.get("supported"):
                supported = bool(resolved.get("supported"))
                efforts = list(resolved.get("efforts") or ["auto"])
            else:
                supported = True
                efforts = ["auto", "low", "medium", "high"]
            default_effort = _safe_text(resolved.get("default_effort") or reasoning.get("default_effort"), "")
        self.reasoning_combo.configure_efforts(efforts, selected=selected,
            default_effort=default_effort, model_name=model_name)
        return supported

    def _update_chat_controls(self) -> None:
        source = str(self.source_combo.currentData() or AI_CHAT_SOURCE_LOCAL_VALUE)
        record = self._selected_local_record()
        provider = self._selected_provider_record()
        supports_effort = self._sync_reasoning_choices(record if source == AI_CHAT_SOURCE_LOCAL_VALUE else provider)
        reasoning_label = self.reasoning_combo.currentText().strip() or "Otomatik"
        message_ready = bool(self.composer.toPlainText().strip())
        busy = self._worker_is_running()
        self._sync_task_session_controls()
        local_blocked = False
        selection_ready = False

        if source == AI_CHAT_SOURCE_LOCAL_VALUE and record:
            selection_ready = True
            repo_id = _safe_text(record.get("repo_id"))
            display_name = _model_display_name(record)
            plan = self._resource_plan_for_record(record)
            local_blocked = not bool(getattr(plan, "safe_to_run", True)) or not record.get("exists_on_disk", True)
            plan_data = plan.to_dict() if hasattr(plan, "to_dict") else {
                **dict(vars(plan)),
                **{key: getattr(plan, key) for key in ("safe_to_run", "profile", "reason", "num_ctx", "max_tokens") if hasattr(plan, key)},
            }
            self.selected_local_plan.setText(_local_plan_description(plan_data))
            self.selected_local_plan.setStyleSheet("color: #B91C1C;" if local_blocked else "")
            if not record.get("exists_on_disk", True):
                self.selected_local_plan.setText("Model dosyası bulunamadı. Model Hub'dan yeniden indirin.")
            self.brain_label.setText(AI_CHAT_ACTIVE_BRAIN_TEMPLATE.format(repo_id=repo_id))
            self.active_brain_badge.setText(AI_CHAT_BRAIN_TEMPLATE.format(repo_id=repo_id))
            self.composer_meta.setText(
                f"{display_name} · Yerel"
                if not local_blocked
                else f"{display_name} · Kaynak kontrolü gerekli"
            )
            self.composer_meta.setToolTip(
                f"{repo_id}\nBağlam: {plan.num_ctx:,} · Yanıt: {plan.max_tokens:,} token"
                if not local_blocked else str(plan.reason)
            )
            self.chat_status.setText(
                "İşlem sürüyor"
                if busy
                else f"Yerel · {display_name} · Akıl yürütme: {reasoning_label}"
            )
            self.session_hint_badge.setText("İşlem sürüyor" if busy else "Yerel runner bağlı")
            if local_blocked:
                self.chat_status.setText("Yerel model başlatılamaz")
                self.session_hint_badge.setText("Kaynak kontrolü")
        elif source == AI_CHAT_SOURCE_LOCAL_VALUE:
            self.selected_local_plan.setStyleSheet("")
            self.selected_local_plan.setText("Yerel model bulunamadı. Model Hub'dan GGUF model indirin, ardından bu listeyi yenileyin.")
            self.brain_label.setText(AI_CHAT_ACTIVE_BRAIN_TEXT)
            self.active_brain_badge.setText(AI_CHAT_BRAIN_UNSELECTED)
            self.composer_meta.setText(AI_CHAT_SELECT_LOCAL_MODEL_TEXT)
            self.chat_status.setText(AI_CHAT_STATUS_WAITING)
            self.session_hint_badge.setText(AI_CHAT_LOCAL_PREP_TEXT)
        elif provider:
            label = _safe_text(provider.get("label"))
            model = _safe_text(provider.get("default_model"), "model belirtilmedi")
            unavailable = _safe_text(provider.get("_selection_unavailable"), "")
            selection_ready = bool(_safe_text(provider.get("default_model"), "")) and not unavailable
            self.brain_label.setText(f"Aktif beyin: {label}")
            self.active_brain_badge.setText(f"Beyin: {model}")
            if selection_ready:
                metadata = dict(provider.get("model_metadata") or {})
                name = _safe_text(metadata.get("name"), model)
                pricing = dict(metadata.get("pricing") or {})
                free = bool(pricing) and all(str(pricing.get(key, "")) in {"0", "0.0"} for key in ("prompt", "completion"))
                self.composer_meta.setText(f"{name} · Ücretsiz" if free else name)
                self.composer_meta.setToolTip(f"{label}\n{model}\nAkıl yürütme: {reasoning_label}")
                self.chat_status.setText(
                    "İşlem sürüyor"
                    if busy
                    else f"{label} · {model} · Akıl yürütme: {reasoning_label}"
                )
                self.session_hint_badge.setText("İşlem sürüyor" if busy else "Cloud runner bağlı")
            elif unavailable:
                self.composer_meta.setText(model + " · Kullanılamıyor")
                self.composer_meta.setToolTip(unavailable)
                self.chat_status.setText(unavailable)
                self.session_hint_badge.setText("Model seçimi gerekli")
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
        self.btn_advanced_model_settings.setEnabled(selection_ready and not busy)
        if self._resource_plan_worker is not None:
            self.btn_advanced_model_settings.setEnabled(False)
        self.reasoning_combo.setEnabled(selection_ready and not busy and supports_effort and self._resource_plan_worker is None)
        if busy:
            reasoning_hint = "İşlem tamamlanınca akıl yürütme düzeyini ayarlayabilirsiniz."
        elif self._resource_plan_worker is not None:
            reasoning_hint = "Modelin kaynak planı hazırlanıyor."
        elif not selection_ready:
            reasoning_hint = _safe_text((provider or {}).get("_selection_unavailable"), "Önce bu sohbet için bir model seçin.")
        elif not supports_effort:
            reasoning_hint = "Bu model ayarlanabilir akıl yürütme düzeyi sunmuyor."
        else:
            reasoning_hint = "Akıl yürütme düzeyini ayarla"
        self.reasoning_combo.setToolTip(reasoning_hint)
        self.btn_refresh_models.setEnabled(not busy and self._models_worker is None and self._providers_worker is None
                                          and self._provider_catalog_worker is None)
        self.btn_send.setText("")
        self.btn_send.setToolTip("Yönlendir" if can_guide else "Gönder")
        self.btn_send.setAccessibleName("Yönlendir" if can_guide else "Gönder")
        self.btn_send.setEnabled(message_ready and selection_ready and (not busy or can_guide) and not local_blocked)
        if source == AI_CHAT_SOURCE_LOCAL_VALUE and self._resource_plan_worker is not None:
            self.selected_local_plan.setText("Kaynak planı hesaplanıyor…")
            self.btn_send.setEnabled(False)
        self.btn_pause_task.setVisible(can_guide)
        self.btn_pause_task.setEnabled(can_guide and self._task_control is not None and not self._task_control.pause_requested)
        display = self.composer_meta.text().split(" · ")[0]
        self.btn_model_picker.setText(self.btn_model_picker.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, 215))
        self.btn_model_picker.setToolTip(self.composer_meta.toolTip() or self.composer_meta.text())
        self.btn_model_picker.setEnabled(not busy)
        self.btn_source_local.setEnabled(not busy)
        self.btn_source_cloud.setEnabled(not busy)
        for button in self.cloud_price_buttons.values():
            button.setEnabled(not busy)
        self.fallback_checkbox.setEnabled(selection_ready and not busy)
        self.conversation_sidebar.set_busy(busy)
        self.btn_run_details.setEnabled(bool(self._activity_run_id))
        self._refresh_chat_title()
        if busy:
            self._model_popup.hide()

    def _open_model_hub(self) -> None:
        self._model_popup.hide()
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
        self._cloud_catalog_stale = True
        self._refresh_current_source()

    def closeEvent(self, event) -> None:
        self._model_popup.close()
        self._is_disposing = True
        self._model_filter_timer.stop()
        self._invalidate_chat_response()
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
            self._resource_plan_worker,
        ):
            self._shutdown_worker(worker)
        self._chat_worker = None
        self._action_worker = None
        self._models_worker = None
        self._providers_worker = None
        self._provider_catalog_worker = None
        self._resource_plan_worker = None
        self._persist_chat_session()
        super().closeEvent(event)

    def _shutdown_worker(self, worker: SyncWorker | None) -> None:
        if worker is None:
            return
        for signal_name in ("result_ready", "progress", "response_event", "finished"):
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
        if self._worker_is_running():
            return
        if (self._chat_history or self.composer.toPlainText() or self._queued_guidance) and not self._persist_chat_session():
            return
        new_state = AgentSessionState(goal="OrderScout AI conversation", active_domain="orders").to_dict()
        try:
            save_active_chat_session(new_state, [])
        except Exception as exc:
            self._append_chat_activity("Yeni sohbet açılamadı: " + _safe_text(exc), notice=True)
            return
        self._chat_restore_failed = False
        self._invalidate_chat_response()
        self._activity_runs.clear()
        self._queued_guidance.clear()
        self._task_control = None
        self.transcript.clear()
        self._chat_message_count = 0
        self._chat_history.clear()
        self._conversation_state = new_state
        self._approval_card_actions.clear()
        self._latest_approval_card_token = ""
        self._superseded_actions.clear()
        self._delivered_artifacts.clear()
        self._shown_artifact_cards.clear()
        self._restored_task_session_ids.clear()
        self._last_task_progress_message = ""
        self.composer.clear()
        self.btn_attach.setToolTip("Bu sohbete dosya ekle")
        self._hide_chat_progress_if_idle()
        self._set_agent_state(status="reset")
        self._refresh_chat_surface()
        self._update_chat_controls()
        self._refresh_conversations()

    def _request_task_pause(self) -> None:
        if self._task_control is None or self._chat_worker is None:
            return
        self._task_control.request_pause()
        self._flush_chat_response()
        self._set_chat_response_label("Duraklatma isteniyor")
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
            self._flush_chat_response()
            self._set_chat_response_label("Talimatınla devam edilecek")
            self._persist_chat_session()
            self._append_chat_activity("Yeni talimatını aldım; mevcut adımın sonucunu koruyup bu talimatla devam edeceğim.")
            self._update_chat_controls()
            return

        provider = self._selected_provider_record() if self.source_combo.currentData() == AI_CHAT_SOURCE_CLOUD_VALUE else None
        if provider and provider.get("_selection_unavailable") and not self._approval_reply_intent(text):
            self._append_chat_activity(str(provider["_selection_unavailable"]), notice=True)
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
        self._persist_chat_session()
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
            self._persist_chat_session()
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
            preparation = f"Yerel model: {_safe_text(record.get('repo_id'))} / {getattr(plan, 'profile', 'auto')} / ctx {getattr(plan, 'num_ctx', '-')}"
        else:
            record = self._selected_provider_record()
            if not record:
                self._append_chat_message("assistant", AI_CHAT_SELECT_CLOUD_PROVIDER_TEXT)
                return
            preparation = f"Cloud model: {_safe_text(record.get('label'))} / {_safe_text(record.get('default_model'), 'model')}"

        from AI.processors.task_control import AgentTaskControl
        self._task_control = AgentTaskControl()
        history = [{"role": "user", "content": text}] if fresh_history else list(self._chat_history)
        self._chat_worker = _make_chat_worker(
            _run_chat_turn_with_runtime,
            text,
            parent=self,
            progress_callback_kw="progress_callback",
            source=source,
            runtime_record=dict(record),
            history=history,
            session_state=dict(self._conversation_state),
            task_control=self._task_control,
            history_includes_current=True,
        )
        response_token = self._begin_chat_response(self._chat_worker)
        self._start_chat_progress()
        self._append_chat_activity(preparation)
        self._update_chat_controls()

        def _done(result: Result) -> None:
            if not self._complete_chat_response(response_token):
                return
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
                    self._append_chat_activity(AI_CHAT_TOOL_ACTIVITY_TEMPLATE.format(tool=", ".join(visible_tools)))
                action_proposal = data.get("action_proposal") if isinstance(data.get("action_proposal"), dict) else None
                if bool(data.get("approval_required")) and action_proposal:
                    self._append_chat_activity("Hazırlanan işlem onayını bekliyor. Henüz çalıştırılmadı.")
                answer = _safe_text(data.get("answer")) or result.message
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
                self._chat_history.append({"role": "assistant", "content": result.message})
                self._append_verified_artifact_links(failed_data)
                self._last_chat_success = False
            self._persist_chat_session()

        def _finished() -> None:
            if not self._response_token_current(response_token):
                return
            self._finish_chat_response(response_token)
            self._chat_worker = None
            self._task_control = None
            self._finish_chat_progress(self._last_chat_success)
            self._update_chat_controls()
            if self._queued_guidance:
                QTimer.singleShot(0, self._run_queued_guidance)

        self._chat_worker.result_ready.connect(_done)
        self._chat_worker.finished.connect(_finished)
        self._chat_worker.start()
        self._update_chat_controls()

    def _release_splitter_guard(self) -> None:
        self._splitter_guard = False
        self._sync_sidebar_state_from_splitter()

    def _is_conversation_list_open(self) -> bool:
        sizes = self._tab_splitter.sizes()
        if len(sizes) < 2:
            return False
        return int(sizes[0]) > 8

    def _sync_sidebar_state_from_splitter(self) -> None:
        if hasattr(self, "btn_toggle_history"):
            label = "Sohbet listesini gizle" if self._is_conversation_list_open() else "Sohbet listesini göster"
            self.btn_toggle_history.setToolTip(label)
            self.btn_toggle_history.setAccessibleName(label)

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

    def _open_conversation_list(self) -> None:
        if self._is_conversation_list_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        min_left = 200
        target = max(min_left, min(self._left_stick_size, total - 320))
        if target <= 0:
            target = min_left
        self._snap_splitter(target, total)
        self._sync_sidebar_state_from_splitter()

    def _close_conversation_list(self) -> None:
        if not self._is_conversation_list_open():
            self._sync_sidebar_state_from_splitter()
            return
        total = self._splitter_total_size()
        self._snap_splitter(0, total)
        self._sync_sidebar_state_from_splitter()

    def _on_tab_splitter_moved(self, pos: int, _index: int) -> None:
        if self._splitter_guard:
            return
        sizes = self._tab_splitter.sizes()
        if sizes and sizes[0] > 0 and pos < self._left_collapse_trigger:
            self._snap_splitter(0, sum(sizes))
        self._sync_sidebar_state_from_splitter()
