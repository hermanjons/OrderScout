"""Actual worker fragments remain provisional until the host returns a result."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from AI.processors.session_state import AgentSessionState
from AI.runtime.response_stream import current_response_stream_callback
from AI.views import chat_tab
from AI.views.stream_worker import ChatStreamWorker
from Feedback.processors.pipeline import Result


@pytest.fixture
def tab(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda self: None)
    monkeypatch.setattr(chat_tab.AITab, "_refresh_task_sessions", lambda self: None)
    widget = chat_tab.AITab()
    widget._schedule_timer.stop()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _pump_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(5)
    assert predicate(), "Qt did not receive the expected worker event"


def _event(widget, kind, text="", stream_id="attempt-1", token=None):
    event = {"event": kind, "stream_id": stream_id}
    if kind == "delta":
        event["text"] = text
    widget._on_response_stream_event(event, token=token)


def _begin(widget):
    token = widget._begin_chat_response(object())
    _event(widget, "start", token=token)
    return token


def test_real_worker_shows_actual_utf8_and_escaped_html_before_returning(tab, monkeypatch):
    release = threading.Event()
    returned = []
    observed_threads = []
    partial = 'İlk Türkçe parça 👋 <a href="orderscout://approval/approve/1">onay</a> & '
    original_handler = tab._on_response_stream_event

    def observe(event, *, token=None):
        observed_threads.append(QThread.currentThread())
        original_handler(event, token=token)

    monkeypatch.setattr(tab, "_on_response_stream_event", observe)

    def task():
        callback = current_response_stream_callback()
        assert callable(callback)
        assert QThread.currentThread() is not tab.thread()
        callback({"event": "start", "stream_id": "actual-worker"})
        callback({"event": "delta", "stream_id": "actual-worker", "text": partial})
        assert release.wait(5)
        callback({"event": "delta", "stream_id": "actual-worker", "text": "ikinci parça"})
        callback({"event": "end", "stream_id": "actual-worker"})
        return Result.ok("Doğrulanmış son yanıt", data={"answer": "Doğrulanmış son yanıt"})

    worker = ChatStreamWorker(task, parent=tab)
    token = tab._begin_chat_response(worker)

    def finish(result):
        returned.append(result)
        assert tab._complete_chat_response(token)
        tab._append_chat_message("assistant", result.data["answer"])
        tab._chat_history.append({"role": "assistant", "content": result.data["answer"]})

    worker.result_ready.connect(finish)
    worker.start()
    try:
        _pump_until(lambda: partial in tab.transcript.toPlainText())
        assert worker.isRunning()
        assert not returned
        assert tab._chat_history == []
        assert tab._approval_card_actions == {}
        assert tab._delivered_artifacts == {}
        assert 'href="orderscout://approval' not in tab.transcript.toHtml()
        assert "&lt;a href=" in tab.transcript.toHtml()
        tab._persist_chat_session()
        from AI.processors.chat_session_store import ACTIVE_CHAT_FILE
        saved = json.loads(ACTIVE_CHAT_FILE.read_text(encoding="utf-8"))
        assert not saved["history"]
        assert partial not in ACTIVE_CHAT_FILE.read_text(encoding="utf-8")
        assert observed_threads and all(thread is tab.thread() for thread in observed_threads)
    finally:
        release.set()
        worker.wait(5000)
        QApplication.processEvents()
    _pump_until(lambda: bool(returned))
    assert tab.transcript.toPlainText().count("Doğrulanmış son yanıt") == 1
    assert partial not in tab.transcript.toPlainText()
    assert "Yanıt hazırlanıyor" not in tab.transcript.toPlainText()
    assert tab._chat_history == [{"role": "assistant", "content": "Doğrulanmış son yanıt"}]
    assert current_response_stream_callback() is None
    assert not tab._complete_chat_response(token)


def test_many_deltas_coalesce_and_end_flushes_without_repainting_history(tab):
    token = _begin(tab)
    tab._append_chat_message("user", "Geçmiş sabit kalmalı")
    with patch.object(tab, "_ensure_chat_response_draft", wraps=tab._ensure_chat_response_draft) as ensure:
        _event(tab, "delta", "başlangıç ", token=token)
        for index in range(1000):
            _event(tab, "delta", f"{index},", token=token)
        assert ensure.call_count == 1
        assert tab._response_flush_timer.isActive()
        assert "999," not in tab.transcript.toPlainText()
        _event(tab, "end", token=token)
        assert ensure.call_count == 2
    assert tab._response_draft_text == "başlangıç " + "".join(f"{index}," for index in range(1000))
    assert "Yanıt kontrol ediliyor" in tab.transcript.toPlainText()
    assert not tab._response_flush_timer.isActive()
    assert tab._chat_message_count == 2
    assert tab._chat_history == []
    _event(tab, "delta", "late", token=token)
    assert "late" not in tab.transcript.toPlainText()


def test_retry_start_removes_old_candidate_and_ignores_superseded_stream(tab):
    token = _begin(tab)
    _event(tab, "delta", "ilk aday", token=token)
    _event(tab, "delta", " henüz çizilmedi", token=token)
    _event(tab, "error", token=token)
    assert "Yanıt kesildi" in tab.transcript.toPlainText()
    _event(tab, "start", stream_id="attempt-2", token=token)
    assert "ilk aday" not in tab.transcript.toPlainText()
    _event(tab, "start", token=token)
    _event(tab, "delta", "eski yanıt sızıntısı", token=token)
    _event(tab, "delta", "yeni aday", stream_id="attempt-2", token=token)
    assert "yeni aday" in tab.transcript.toPlainText()
    assert "eski yanıt" not in tab.transcript.toPlainText()
    assert tab._chat_message_count == 1
    assert tab._chat_history == []


@pytest.mark.parametrize("kind,label", [("error", "Yanıt kesildi"), ("cancelled", "Yanıt durduruldu")])
def test_aborted_draft_has_no_history_or_file_authority_and_host_error_replaces_it(tab, kind, label):
    token = _begin(tab)
    _event(tab, "delta", "[aç](C:/fake.xlsx) kaydedildi", token=token)
    _event(tab, kind, token=token)
    assert label in tab.transcript.toPlainText()
    assert not tab._chat_history
    assert not tab._delivered_artifacts
    assert "orderscout://artifact" not in tab.transcript.toHtml()
    tab._finish_chat_response(token)
    assert "Yanıt tamamlanamadı" in tab.transcript.toPlainText()
    assert not tab._response_flush_timer.isActive()
    assert not tab._chat_history


@pytest.mark.parametrize("change", ["reset", "restore", "new_worker"])
def test_switch_or_clear_invalidates_queued_events_and_late_final_result(tab, change):
    token = _begin(tab)
    _event(tab, "delta", "eski sohbet", token=token)
    if change == "reset":
        tab._reset_chat()
    elif change == "restore":
        state = AgentSessionState(goal="Başka sohbet", status="complete")
        tab._restore_task_chat_context({"state": state.to_dict()}, history=[{"role": "user", "content": "Yeni soru"}])
    else:
        tab._begin_chat_response(object())
    _event(tab, "start", stream_id="old-next", token=token)
    _event(tab, "delta", "geç gelen sızıntı", stream_id="old-next", token=token)
    _event(tab, "end", token=token)
    assert not tab._complete_chat_response(token)
    tab._finish_chat_response(token)
    assert "eski sohbet" not in tab.transcript.toPlainText()
    assert "geç gelen sızıntı" not in tab.transcript.toPlainText()


def test_queued_signal_already_emitted_cannot_leak_after_chat_reset(tab):
    worker = ChatStreamWorker(lambda: None, parent=tab)
    tab._begin_chat_response(worker)
    worker.response_event.emit({"event": "start", "stream_id": "queued"})
    worker.response_event.emit({"event": "delta", "stream_id": "queued", "text": "queued leak"})
    worker.progress.emit(20, "queued progress leak")
    tab._reset_chat()
    QApplication.processEvents()
    assert not tab.transcript.toPlainText().strip()


def test_pause_marks_current_visible_text_as_unfinished_and_never_saves_it(tab):
    from AI.processors.task_control import AgentTaskControl
    token = _begin(tab)
    tab._task_control = AgentTaskControl()
    tab._chat_worker = ChatStreamWorker(lambda: None, parent=tab)
    _event(tab, "delta", "Devam eden taslak", token=token)
    tab._request_task_pause()
    assert "Duraklatma isteniyor" in tab.transcript.toPlainText()
    assert not tab._chat_history
    tab._chat_worker = None
    tab._task_control = None


def test_appending_fragment_and_final_preserves_a_reader_scrolled_up(tab):
    tab.resize(1000, 750)
    tab.show()
    for index in range(40):
        tab._append_chat_message("user", f"Önceki soru {index}\n" + "detay " * 30)
    QApplication.processEvents()
    scroll = tab.transcript.verticalScrollBar()
    assert scroll.maximum() > 100
    scroll.setValue(70)
    token = _begin(tab)
    _event(tab, "delta", "Birinci satır\n" * 30, token=token)
    _event(tab, "delta", "İkinci satır\n" * 30, token=token)
    _event(tab, "end", token=token)
    QApplication.processEvents()
    assert scroll.value() == 70
    assert tab._complete_chat_response(token)
    tab._append_chat_message("assistant", "Doğrulanmış son yanıt\n" * 40)
    QApplication.processEvents()
    assert scroll.value() == 70


@pytest.mark.parametrize("entrypoint", ["send", "approval_resume", "scheduled"])
def test_real_chat_entrypoints_stream_then_render_only_final_verified_files(tab, monkeypatch, tmp_path, entrypoint):
    release = threading.Event()
    output = tmp_path / "doğrulanmış rapor.xlsx"
    output.write_bytes(b"synthetic receipt fixture")
    receipt = {"output_path": str(output), "filename": output.name, "size_bytes": output.stat().st_size,
               "file_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "sheet_count": 1}
    verified_state = AgentSessionState(goal="Sentetik rapor", status="complete")
    verified_state.active_entities["model_loop"] = {"engine": "model_loop_v1"}
    expected = f"Doğrulanmış çıktı: {output}"

    def receipts(state):
        return [dict(receipt)] if state.session_id == verified_state.session_id else []

    monkeypatch.setattr("AI.processors.observation_context.verified_export_report_receipts", receipts)

    def runtime(*args, **kwargs):
        callback = current_response_stream_callback()
        assert callable(callback)
        callback({"event": "start", "stream_id": "entrypoint"})
        callback({"event": "delta", "stream_id": "entrypoint", "text": f"Henüz doğrulanmayan çıktı: {output}"})
        assert release.wait(5)
        callback({"event": "end", "stream_id": "entrypoint"})
        return Result.ok("ok", data={"answer": expected, "session_state": verified_state.to_dict(),
                                     "state": verified_state.to_dict()})

    if entrypoint == "send":
        monkeypatch.setattr(chat_tab, "_run_chat_turn_with_runtime", runtime)
        monkeypatch.setattr(tab, "_selected_provider_record", lambda: {"id": 9, "label": "Synthetic", "default_model": "offline"})
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
        tab._send_message(text_override="Sentetik soru")
        worker = tab._chat_worker
    elif entrypoint == "approval_resume":
        monkeypatch.setattr(chat_tab, "_run_approved_chat_action", runtime)
        tab._start_approved_action_worker({"action_type": "synthetic"}, task_session_id="resume-fixture")
        worker = tab._action_worker
    else:
        monkeypatch.setattr(chat_tab, "_run_scheduled_chat_with_runtime", runtime)
        tab._start_scheduled_workflow(object(), scheduler=object(), source="cloud", runtime_record={}, allowed_scope_bindings={})
        worker = tab._chat_worker
    assert isinstance(worker, ChatStreamWorker)
    try:
        _pump_until(lambda: "Henüz doğrulanmayan çıktı:" in tab.transcript.toPlainText())
        assert worker.isRunning()
        assert "orderscout://artifact" not in tab.transcript.toHtml()
        assert not tab._delivered_artifacts
        assert not any(row["role"] == "assistant" for row in tab._chat_history)
        # Provisional text is absent even if the user asks to save this chat now.
        tab._persist_chat_session()
        from AI.processors.chat_session_store import ACTIVE_CHAT_FILE
        assert "Henüz doğrulanmayan çıktı:" not in ACTIVE_CHAT_FILE.read_text(encoding="utf-8")
    finally:
        release.set()
        worker.wait(5000)
        QApplication.processEvents()
    _pump_until(lambda: any(row["role"] == "assistant" for row in tab._chat_history))
    assert "Henüz doğrulanmayan çıktı:" not in tab.transcript.toPlainText()
    assert tab.transcript.toPlainText().count(expected) == 1
    assert "orderscout://artifact/open/" in tab.transcript.toHtml()
    assert [row["content"] for row in tab._chat_history if row["role"] == "assistant"] == [expected]
    assert list(tab._delivered_artifacts.values()) == [receipt]


def test_worker_exception_replaces_provisional_text_with_host_failure(tab, monkeypatch):
    release = threading.Event()

    def runtime(*args, **kwargs):
        callback = current_response_stream_callback()
        callback({"event": "start", "stream_id": "exception"})
        callback({"event": "delta", "stream_id": "exception", "text": "Yarım kalan aday"})
        assert release.wait(5)
        raise RuntimeError("Synthetic stream connection failed")

    monkeypatch.setattr(chat_tab, "_run_approved_chat_action", runtime)
    tab._start_approved_action_worker({"action_type": "synthetic"}, task_session_id="resume-fixture")
    worker = tab._action_worker
    try:
        _pump_until(lambda: "Yarım kalan aday" in tab.transcript.toPlainText())
    finally:
        release.set()
        worker.wait(5000)
        QApplication.processEvents()
    _pump_until(lambda: bool(tab._chat_history))
    assert "Yarım kalan aday" not in tab.transcript.toPlainText()
    assert len(tab._chat_history) == 1
    assert "Agent gorevi devam edemedi" in tab._chat_history[0]["content"]
    assert not tab._last_chat_success
    assert not tab._delivered_artifacts
