"""Exercise the approved layout through real save/load and Qt selection paths."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from AI.views import chat_tab
from AI.processors import chat_session_store as store
from AI.processors.session_state import AgentSessionState


@pytest.fixture
def tab(monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = app.font()
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda self: None)
    monkeypatch.setattr(chat_tab, "list_agent_task_states", lambda **kw: [])
    widget = chat_tab.AITab()
    widget._schedule_timer.stop()
    widget.resize(1360, 850)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()
    app.setFont(original)


def exchange(tab, title, answer):
    tab._append_chat_message("user", title)
    tab._append_chat_message("assistant", answer)
    tab._chat_history.extend([{"role": "user", "content": title}, {"role": "assistant", "content": answer}])
    return tab._conversation_state["session_id"]


def test_new_chat_and_switch_restore_each_real_transcript_and_unsent_draft(tab):
    first = exchange(tab, "Siparişlerimi özetle", "İlk doğrulanmış cevap")
    tab.composer.setPlainText("İlk sohbetin yazılmamış devamı")
    tab._reset_chat()
    second = exchange(tab, "Stoklarımı göster", "İkinci doğrulanmış cevap")
    tab.composer.setPlainText("İkinci taslak")
    tab._open_chat_session(first)
    assert tab._conversation_state["session_id"] == first
    assert tab.composer.toPlainText() == "İlk sohbetin yazılmamış devamı"
    assert "İlk doğrulanmış cevap" in tab.transcript.toPlainText()
    assert "İkinci doğrulanmış cevap" not in tab.transcript.toPlainText()
    tab._open_chat_session(second)
    assert tab.composer.toPlainText() == "İkinci taslak"
    assert "İkinci doğrulanmış cevap" in tab.transcript.toPlainText()
    assert {row["session_id"] for row in store.list_chat_sessions()} == {first, second}
    assert tab.chat_title.text() == "Stoklarımı göster"


@pytest.mark.parametrize("action", ["new", "switch"])
def test_failed_save_keeps_current_history_and_draft(tab, action):
    other = AgentSessionState(goal="Başka sohbet")
    store.save_active_chat_session(other.to_dict(), [{"role":"user", "content":"Başka soru"}])
    current = exchange(tab, "Silinmemesi gereken soru", "Cevap")
    tab.composer.setPlainText("Korunacak taslak")
    with patch.object(chat_tab, "save_active_chat_session", side_effect=OSError("synthetic disk full")):
        tab._reset_chat() if action == "new" else tab._open_chat_session(other.session_id)
    assert tab._conversation_state["session_id"] == current
    assert tab.composer.toPlainText() == "Korunacak taslak"
    assert tab._chat_history[-1]["content"] == "Cevap"
    assert "Sohbet kaydedilemedi" in tab.transcript.toPlainText()


def test_missing_or_corrupt_chat_does_not_erase_current_conversation(tab):
    current = exchange(tab, "Mevcut sohbet", "Görünen yanıt")
    tab._open_chat_session("unknown-but-valid-id")
    assert tab._conversation_state["session_id"] == current
    assert "Sohbet kaydı bulunamadı" in tab.transcript.toPlainText()
    with patch.object(chat_tab, "load_chat_session", side_effect=ValueError("synthetic damaged entry")):
        tab._open_chat_session("damaged-id")
    assert tab._conversation_state["session_id"] == current
    assert "Görünen yanıt" in tab.transcript.toPlainText()


def test_picker_filters_real_selection_records_and_returns_selection_to_footer(tab):
    tab.source_combo.setCurrentIndex(tab.source_combo.findData("cloud"))
    tab._populate_cloud_model_list([{"provider":{"id":7,"provider_code":"openrouter","label":"Synthetic"},
                                    "models":[{"id":"synthetic/alpha","name":"Alpha"},
                                              {"id":"synthetic/beta","name":"Beta"}]}])
    tab._toggle_model_picker()
    assert tab._model_popup.isVisible()
    tab.model_search.setText("Beta")
    QTest.qWait(120)
    matches = [tab.model_list.item(i) for i in range(tab.model_list.count())
               if not tab.model_list.item(i).isHidden()
               and (tab.model_list.item(i).data(Qt.ItemDataRole.UserRole) or {}).get("_source_kind")=="cloud_model"]
    assert len(matches) == 1
    target = matches[0]
    tab.model_list.setCurrentItem(target)
    tab.model_list.itemClicked.emit(target)
    assert not tab._model_popup.isVisible()
    assert tab._selected_provider_record()["default_model"] == "synthetic/beta"
    assert "Beta" in tab.btn_model_picker.text()
    tab.reasoning_combo.setCurrentIndex(tab.reasoning_combo.findData("high"))
    assert tab._selected_provider_record()["reasoning_effort"] == "high"
    assert tab.reasoning_combo.parentWidget() is tab.composer.parentWidget()


def test_sidebar_toggle_gives_space_to_chat_without_moving_model_controls(tab):
    assert tab._is_conversation_list_open()
    before = tab._tab_splitter.widget(1).width()
    tab.btn_toggle_history.click()
    QApplication.processEvents()
    assert not tab._is_conversation_list_open()
    assert tab._tab_splitter.widget(1).width() > before
    assert tab.btn_model_picker.isVisible()
    assert tab.reasoning_combo.isVisible()
    tab.btn_toggle_history.click()
    QApplication.processEvents()
    assert tab._is_conversation_list_open()


def test_busy_worker_blocks_switch_new_chat_and_model_changes(tab):
    current = exchange(tab, "Devam eden soru", "Önceki cevap")
    class Busy:
        def isRunning(self): return True
    tab._chat_worker = Busy()
    try:
        tab._update_chat_controls()
        tab._toggle_model_picker()
        tab._open_chat_session("other")
        tab._reset_chat()
        assert tab._conversation_state["session_id"] == current
        assert not tab._model_popup.isVisible()
        assert not tab.btn_model_picker.isEnabled()
        assert not tab.reasoning_combo.isEnabled()
        assert not tab.btn_source_local.isEnabled()
        assert not tab.conversation_sidebar.new_chat_button.isEnabled()
    finally:
        tab._chat_worker = None


def test_selecting_archived_chat_never_executes_business_or_resumes_automatically(tab):
    saved = AgentSessionState(goal="Kayıtlı sohbet", status="paused")
    store.save_active_chat_session(saved.to_dict(), [{"role":"user","content":"Önceki istek"}])
    with patch.object(chat_tab, "_run_chat_turn_with_runtime", side_effect=AssertionError("must not run")), \
         patch.object(chat_tab, "_run_approved_chat_action", side_effect=AssertionError("must not resume")):
        tab._open_chat_session(saved.session_id)
    assert tab._conversation_state["session_id"] == saved.session_id
    assert tab._chat_worker is None and tab._action_worker is None


@pytest.mark.parametrize("action", ["new", "switch"])
def test_failure_at_target_commit_preserves_both_saved_drafts(tab, action):
    target = AgentSessionState(goal="Hedef sohbet")
    store.save_active_chat_session(target.to_dict(), [{"role":"user", "content":"Hedef soru"}],
                                   composer_text="Hedefte korunacak taslak")
    current = exchange(tab, "Kaynak soru", "Kaynak yanıt")
    tab.composer.setPlainText("Kaynakta korunacak taslak")
    real_save = store.save_active_chat_session
    calls = []
    def save_then_fail(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic target commit failure")
        return real_save(*args, **kwargs)
    with patch.object(chat_tab, "save_active_chat_session", side_effect=save_then_fail):
        tab._reset_chat() if action == "new" else tab._open_chat_session(target.session_id)
    assert tab._conversation_state["session_id"] == current
    assert tab.composer.toPlainText() == "Kaynakta korunacak taslak"
    assert store.load_chat_session(target.session_id)["composer_text"] == "Hedefte korunacak taslak"
    assert store.load_chat_session(current)["composer_text"] == "Kaynakta korunacak taslak"


def test_model_popup_dismisses_with_escape(tab):
    tab._toggle_model_picker()
    assert tab._model_popup.isVisible()
    QTest.keyClick(tab.model_search, Qt.Key.Key_Escape)
    assert not tab._model_popup.isVisible()


@pytest.mark.parametrize("width", [1000, 1360])
def test_footer_selection_and_send_remain_inside_composer_when_resized(tab, width):
    tab.resize(width, 760)
    QApplication.processEvents()
    assert tab.width() == width
    composer = tab.composer.parentWidget()
    for control in (tab.btn_model_picker, tab.reasoning_combo, tab.btn_attach, tab.btn_send):
        assert control.isVisible()
        assert control.mapTo(composer, control.rect().topLeft()).x() >= 0
        assert control.mapTo(composer, control.rect().bottomRight()).x() < composer.width()


def test_user_title_stays_plain_text_in_header_and_conversation_list(tab):
    text = '<img src="file:///not-an-attachment.png"> Sipariş'
    exchange(tab, text, "Yanıt")
    assert tab._persist_chat_session()
    assert tab.chat_title.textFormat() == Qt.TextFormat.PlainText
    assert '<img src=' in tab.chat_title.text()
