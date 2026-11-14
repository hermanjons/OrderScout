"""A saved conversation keeps its exact model while current accounts load."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from AI.processors.session_state import AgentSessionState
from AI.views import chat_tab


LUNA = {"id": "openai/gpt-6-luna", "name": "GPT-6 Luna",
        "supported_parameters": ["tools", "reasoning"],
        "reasoning": {"mandatory": False, "default_effort": "medium",
                      "supported_efforts": ["max", "xhigh", "high", "medium", "low", "none"]}}
OTHER = {"id": "synthetic/other", "name": "Other", "supported_parameters": ["tools", "reasoning"],
         "reasoning": {"supported_efforts": ["low", "medium", "high"]}}
PROVIDER = {"id": 71, "provider_code": "openrouter", "label": "Synthetic current account",
            "default_model": None, "reasoning_capabilities": {"supported": False, "efforts": ["auto"]}}


def saved_state():
    state = AgentSessionState(goal="Sentetik sohbet", status="complete")
    state.record_turn(role="user", content="Önceki sentetik mesaj")
    state.record_turn(role="assistant", content="Önceki sentetik yanıt")
    state.active_entities["runtime_context"] = {
        "source": "cloud", "provider_id": 71, "provider_code": "openrouter",
        "model_name": LUNA["id"], "reasoning_effort": "high", "model_metadata": deepcopy(LUNA),
        "api_key": "untrusted-saved-credential-must-not-be-restored",
    }
    return state.to_dict()


@pytest.fixture
def tab(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda self: None)
    monkeypatch.setattr(chat_tab.AITab, "_refresh_cloud_providers", lambda self: None)
    monkeypatch.setattr(chat_tab.AITab, "_refresh_task_sessions", lambda self: None)
    monkeypatch.setattr(chat_tab.AITab, "_refresh_conversations", lambda self: None)
    widget = chat_tab.AITab()
    widget._schedule_timer.stop()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def load(tab):
    tab._restore_task_chat_context({"state": saved_state()}, persist=False)


def test_restore_selects_saved_source_then_exact_account_and_model_with_fresh_reasoning_metadata(tab):
    assert tab.source_combo.currentData() == "local"
    load(tab)
    assert tab.source_combo.currentData() == "cloud"
    placeholder = tab._selected_provider_record()
    assert (placeholder["id"], placeholder["default_model"], placeholder["reasoning_effort"]) == (71, LUNA["id"], "high")
    assert "api_key" not in placeholder
    assert not tab.reasoning_combo.isEnabled()  # Wait for the current account/catalogue.
    tab._populate_cloud_model_list([
        {"provider": {**PROVIDER, "id": 72}, "models": [LUNA]},
        {"provider": PROVIDER, "models": [OTHER, LUNA]},
    ], catalog_complete=True)
    selected = tab._selected_provider_record()
    assert (selected["id"], selected["default_model"], selected["reasoning_effort"]) == (71, LUNA["id"], "high")
    assert selected["label"] == PROVIDER["label"]
    assert tab.reasoning_combo.isEnabled()
    assert tab.reasoning_combo.currentData() == "high"
    assert tab.reasoning_combo.findData("max") >= 0 and tab.reasoning_combo.findData("xhigh") >= 0
    assert tab.reasoning_combo.default_effort == "medium"


def test_user_model_choice_ends_restore_intent_and_survives_later_catalogue_refresh(tab):
    load(tab)
    groups = [{"provider": PROVIDER, "models": [LUNA, OTHER]}]
    tab._populate_cloud_model_list(groups, catalog_complete=True)
    for row in range(tab.model_list.count()):
        payload = tab.model_list.item(row).data(Qt.ItemDataRole.UserRole)
        if payload.get("_source_kind") == "cloud_model" and payload.get("default_model") == OTHER["id"]:
            tab.model_list.setCurrentRow(row)
            break
    assert tab._restored_model_choice is None
    tab.reasoning_combo.setCurrentIndex(tab.reasoning_combo.findData("low"))
    tab._populate_cloud_model_list(groups, catalog_complete=True)
    assert tab._selected_provider_record()["default_model"] == OTHER["id"]
    assert tab.reasoning_combo.currentData() == "low"


@pytest.mark.parametrize("groups", [
    [{"provider": PROVIDER, "models": [OTHER]}],
    [{"provider": {**PROVIDER, "id": 72}, "models": [LUNA]}],
    [{"provider": PROVIDER, "models": []}],
])
def test_unavailable_saved_model_is_visible_and_cannot_silently_run_another_model(tab, monkeypatch, groups):
    load(tab)
    tab._populate_cloud_model_list(groups, catalog_complete=True)
    selected = tab._selected_provider_record()
    assert selected["default_model"] == LUNA["id"] and selected["id"] == 71
    assert selected["_selection_unavailable"]
    assert "Kullanılamıyor" in tab.composer_meta.text()
    assert not tab.reasoning_combo.isEnabled()
    tab.composer.setPlainText("Sentetik yeni istek")
    worker = Mock(side_effect=AssertionError("Unavailable model must not start inference"))
    monkeypatch.setattr(chat_tab, "_make_chat_worker", worker)
    tab._send_message()
    worker.assert_not_called()
    assert tab.composer.toPlainText() == "Sentetik yeni istek"
    tab._populate_cloud_model_list([{"provider": PROVIDER, "models": [LUNA]}], catalog_complete=True)
    assert tab._selected_provider_record()["default_model"] == LUNA["id"]
    assert tab.reasoning_combo.isEnabled() and tab.reasoning_combo.currentData() == "high"


def test_active_chat_without_visible_history_still_restores_its_model(tab, monkeypatch):
    state = saved_state()
    state["conversation_turns"] = []
    monkeypatch.setattr(chat_tab, "load_active_chat_session", lambda: {
        "state": state, "history": [], "composer_text": "Kayıtlı taslak"})
    tab._restore_active_chat_session()
    assert tab.source_combo.currentData() == "cloud"
    assert tab._selected_provider_record()["default_model"] == LUNA["id"]
    assert tab.composer.toPlainText() == "Kayıtlı taslak"


def test_disabled_reasoning_control_explains_selection_loading_busy_and_planning(tab):
    assert "Önce" in tab.reasoning_combo.toolTip()
    load(tab)
    assert "yükleniyor" in tab.reasoning_combo.toolTip()
    tab._populate_cloud_model_list([{"provider": PROVIDER, "models": [LUNA]}], catalog_complete=True)
    assert tab.reasoning_combo.isEnabled() and "ayarla" in tab.reasoning_combo.toolTip()
    tab._chat_worker = Mock(isRunning=lambda: True)
    tab._update_chat_controls()
    assert not tab.reasoning_combo.isEnabled() and "tamamlanınca" in tab.reasoning_combo.toolTip()
    tab._chat_worker = None
    tab._resource_plan_worker = Mock()
    tab._update_chat_controls()
    assert not tab.reasoning_combo.isEnabled() and "hazırlanıyor" in tab.reasoning_combo.toolTip()
    tab._resource_plan_worker = None
    tab._update_chat_controls()
    assert tab.reasoning_combo.isEnabled()
