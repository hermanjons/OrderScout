from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from AI.processors.task_control import AgentTaskControl
from AI.views.chat_tab import AITab


@pytest.fixture
def tab():
    app = QApplication.instance() or QApplication([])
    widget = AITab()
    try:
        yield widget
    finally:
        widget._chat_worker = None
        widget._task_control = None
        widget.close()
        widget.deleteLater()
        assert app is not None


def test_guidance_during_worker_pauses_at_boundary_without_starting_another_worker(tab):
    tab._chat_worker = Mock()
    tab._task_control = AgentTaskControl()
    before = deepcopy(tab._conversation_state)
    with patch.object(tab, "_worker_is_running", return_value=True), patch("AI.views.chat_tab.SyncWorker") as worker:
        tab.composer.setPlainText("Önce diğer mağazayı incele ve aynı sonuçları koru.")
        tab._send_message()
    worker.assert_not_called()
    assert tab._conversation_state == before
    assert tab._task_control.pause_requested and tab._task_control.reason == "user_revision"
    assert tab._task_control.queued_user_messages == tab._queued_guidance
    assert tab._queued_guidance == ["Önce diğer mağazayı incele ve aynı sonuçları koru."]
    assert tab._chat_history[-1]["content"] == tab._queued_guidance[0]
    assert tab.composer.toPlainText() == ""
    assert tab.transcript.toPlainText().count(tab._queued_guidance[0]) == 1


def test_pause_button_does_not_claim_ongoing_work_was_killed_or_rewrite_state(tab):
    tab._chat_worker = Mock()
    tab._task_control = AgentTaskControl()
    before = deepcopy(tab._conversation_state)
    with patch.object(tab, "_worker_is_running", return_value=True):
        tab._request_task_pause()
    assert tab._task_control.pause_requested
    assert tab._conversation_state == before and tab._queued_guidance == []
    assert not tab.btn_pause_task.isEnabled()
    assert "sonucu kaydedilince" in tab.transcript.toPlainText()


def test_queued_human_guidance_is_dispatched_once_after_worker_settles(tab):
    tab._queued_guidance = ["Diğer mağazayı kullan.", "USD ve TRY ayrı kalsın."]
    with patch.object(tab, "_worker_is_running", return_value=True), patch.object(tab, "_send_message") as send:
        tab._run_queued_guidance()
    send.assert_not_called()
    with patch.object(tab, "_worker_is_running", return_value=False), patch.object(tab, "_send_message") as send:
        tab._run_queued_guidance()
        tab._run_queued_guidance()
    send.assert_called_once_with(text_override="Diğer mağazayı kullan.\nUSD ve TRY ayrı kalsın.", already_recorded=True)
    assert tab._queued_guidance == []


def test_human_pause_control_does_not_have_model_approval_or_execute_methods():
    control = AgentTaskControl()
    control.request_pause(reason="user_revision")
    control.request_pause()
    assert control.reason == "user_revision"
    assert not hasattr(control, "approve") and not hasattr(control, "execute")
    with pytest.raises(ValueError):
        control.request_pause(reason="model_approval")


def test_restoring_paused_human_revision_preserves_exact_instruction_and_disables_old_resume_bypass(tab):
    from AI.processors.session_state import AgentSessionState, AgentTaskStep
    from AI.processors.turn_service import resume_reply_interpretation

    state = AgentSessionState(goal="Original work", active_domain="general", status="paused")
    state.remaining_steps = [AgentTaskStep(index=1, step_id="read", prompt="Original read")]
    state.active_entities["task_control"] = {"pause_requested": True, "reason": "user_revision",
                                              "queued_user_messages": ["USD ve TRY ayrı kalsın."]}
    tab._restore_task_chat_context({"state": state.to_dict()})
    assert tab.composer.toPlainText() == "USD ve TRY ayrı kalsın."
    assert tab._chat_history[-1]["content"] == "USD ve TRY ayrı kalsın."
    assert resume_reply_interpretation("Devam et", state) is None
