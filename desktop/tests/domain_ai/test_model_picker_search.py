"""Real Qt search/selection and delayed catalogue responses on isolated data."""
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QObject, QPersistentModelIndex, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from AI.views import chat_tab
from AI.views.model_picker import PRESENTATION_ROLE
from AI.processors.model_routing import build_free_model_test_route
from AI.processors import pipeline
from Feedback.processors.pipeline import Result


PROVIDER = {"id": 71, "provider_code": "openrouter", "label": "OpenRouter"}
GLM = {"id": "z-ai/glm-5.3-flash", "name": "Z.ai: GLM 5.3 Flash", "is_free": False,
       "context_length": 1048576, "pricing": {"prompt": "0.0000000052", "completion": "0.0000001985"},
       "capability_profile": {"native_tool_calling_available": True}}
FREE = {"id": "synthetic/free:free", "name": "Ücretsiz Model", "is_free": True}


def groups(models=None):
    return [{"provider": dict(PROVIDER), "models": models if models is not None else [FREE, GLM]}]


@pytest.fixture
def picker(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda self: None)
    monkeypatch.setattr(chat_tab, "list_agent_task_states", lambda **kwargs: [])
    widget = chat_tab.AITab()
    widget._schedule_timer.stop()
    widget.resize(1360, 850)
    widget.show()
    app.processEvents()
    widget.source_combo.setCurrentIndex(widget.source_combo.findData("cloud"))
    widget._populate_cloud_model_list(groups())
    widget._toggle_model_picker()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def visible_models(widget):
    return [widget.model_list.item(index).data(Qt.ItemDataRole.UserRole)["default_model"]
            for index in range(widget.model_list.count()) if not widget.model_list.item(index).isHidden()
            and (widget.model_list.item(index).data(PRESENTATION_ROLE) or {}).get("kind") == "cloud_model"]


def search(widget, query):
    widget.model_search.setText(query)
    QTest.qWait(120)


def test_default_all_exposes_paid_glm_and_truthful_price_and_accessible_name(picker):
    assert picker.cloud_price_buttons["all"].isChecked()
    assert GLM["id"] in visible_models(picker)
    item = picker.model_list.item(2)
    presentation = item.data(PRESENTATION_ROLE)
    assert item.text() == GLM["name"]
    assert "$0.0052 giriş" in presentation["meta"]
    assert "$0.1985 çıkış / 1M token" in presentation["meta"]
    assert "Araçlar" in presentation["meta"] and "1,05M bağlam" in presentation["meta"]
    assert picker.model_list.visualItemRect(item).height() > 0


def test_real_provider_catalogue_action_to_picker_keeps_late_glm_and_runtime_metadata(picker, monkeypatch):
    raw = [{"id": f"synthetic/model-{index:04}", "name": f"Model {index}",
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "context_length": 32000, "supported_parameters": ["tools"]} for index in range(620)]
    raw.append({**GLM, "supported_parameters": ["tools", "reasoning"],
                "top_provider": {"max_completion_tokens": 64000}})
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": raw}
    monkeypatch.setattr(pipeline.requests, "get", lambda *args, **kwargs: Response())
    result = picker._provider_catalog_result([PROVIDER])
    assert result.success and len(result.data["groups"][0]["models"]) == 621
    picker._populate_cloud_model_list(result.data["groups"])
    search(picker, "glm 5.3 flash")
    assert visible_models(picker) == [GLM["id"]]
    QTest.keyClick(picker.model_search, Qt.Key.Key_Return)
    selected = picker._selected_provider_record()
    assert selected["default_model"] == GLM["id"]
    assert selected["model_metadata"]["output_token_limit"] == 64000
    assert "tools" in selected["model_metadata"]["supported_parameters"]
    assert len(selected["free_model_test_route"]["models"]) == 621


def test_typing_and_provider_collapse_keep_items_and_selection_settings_alive(picker):
    picker.model_list.setCurrentRow(2)
    picker.reasoning_combo.setCurrentIndex(picker.reasoning_combo.findData("high"))
    picker.fallback_checkbox.setChecked(False)
    original = QPersistentModelIndex(picker.model_list.indexFromItem(picker.model_list.item(2)))
    picker._on_model_list_item_clicked(picker.model_list.item(0))
    assert picker.model_list.item(2).isHidden()
    search(picker, "GLM-5.3-FLASH")
    assert visible_models(picker) == [GLM["id"]]
    assert original.isValid() and original.row() == 2
    selected = picker._selected_provider_record()
    assert (selected["default_model"], selected["reasoning_effort"], selected["allow_model_fallback"]) == (GLM["id"], "high", False)
    search(picker, "")
    assert picker.model_list.item(2).isHidden()  # search did not erase collapse choice


def test_price_filters_and_search_stay_local_and_empty_free_search_offers_all(picker, monkeypatch):
    network = Mock(side_effect=AssertionError("price/search must not reload a provider"))
    monkeypatch.setattr(picker, "_refresh_current_source", network)
    picker._set_cloud_price_filter("free")
    assert visible_models(picker) == [FREE["id"]]
    search(picker, "glm 5.3 flash")
    assert visible_models(picker) == [] and picker.model_empty_state.isVisible()
    assert picker.btn_search_all_models.isVisible()
    QTest.mouseClick(picker.btn_search_all_models, Qt.MouseButton.LeftButton)
    assert visible_models(picker) == [GLM["id"]]
    assert not picker.model_empty_state.isVisible()
    assert picker._selected_provider_record()["default_model"] == FREE["id"]
    network.assert_not_called()


def test_search_keyboard_enter_flushes_pending_query_and_selects_exact_model(picker):
    picker.model_search.setText("glm 5.3 flash")
    QTest.keyClick(picker.model_search, Qt.Key.Key_Return)
    assert picker._selected_provider_record()["default_model"] == GLM["id"]
    assert not picker._model_popup.isVisible()


def test_search_arrow_moves_focus_to_matching_model_and_escape_closes(picker):
    picker.model_search.setText("glm")
    QTest.keyClick(picker.model_search, Qt.Key.Key_Down)
    assert picker.model_list.currentItem().data(Qt.ItemDataRole.UserRole)["default_model"] == GLM["id"]
    assert picker.model_list.hasFocus()
    QTest.keyClick(picker.model_list, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not picker._model_popup.isVisible()


def test_large_catalogue_rapid_typing_never_builds_row_widgets_or_replaces_items(picker):
    models = [dict(FREE, id=f"synthetic/model-{index}:free", name=f"Model {index}") for index in range(1200)] + [GLM]
    route = build_free_model_test_route("openrouter", models).to_dict()
    picker._populate_cloud_model_list([dict(groups(models)[0], route=route)])
    last = QPersistentModelIndex(picker.model_list.indexFromItem(picker.model_list.item(1201)))
    for query in ("g", "gl", "glm", "glm 5.3", "glm 5.3 flash"):
        picker.model_search.setText(query)
    QTest.qWait(120)
    assert visible_models(picker) == [GLM["id"]] and last.isValid()
    assert all(picker.model_list.itemWidget(picker.model_list.item(i)) is None for i in range(picker.model_list.count()))
    assert picker.model_list.count() == 1202
    assert all("free_model_test_route" not in (picker.model_list.item(i).data(Qt.ItemDataRole.UserRole) or {})
               for i in range(picker.model_list.count()))
    picker.model_list.setCurrentRow(1201)
    assert picker._selected_provider_record()["free_model_test_route"] is route
    picker._apply_advanced_model_settings(None, {"temperature": 0.4})
    assert "free_model_test_route" not in picker.model_list.currentItem().data(Qt.ItemDataRole.UserRole)
    assert picker._selected_provider_record()["free_model_test_route"] is route


def test_live_catalogue_refresh_preserves_exact_selected_model_and_conversation_settings(picker):
    picker.model_list.setCurrentRow(2)
    picker.reasoning_combo.setCurrentIndex(picker.reasoning_combo.findData("high"))
    picker.fallback_checkbox.setChecked(False)
    picker._populate_cloud_model_list(groups([GLM, FREE]))
    selected = picker._selected_provider_record()
    assert (selected["default_model"], selected["reasoning_effort"], selected["allow_model_fallback"]) == (GLM["id"], "high", False)


def test_account_edit_refresh_uses_current_endpoint_and_key_while_keeping_chat_overrides(picker):
    original = groups()
    original[0]["provider"].update(endpoint_url="https://synthetic-old.invalid", api_key="synthetic-old")
    picker._populate_cloud_model_list(original)
    picker.model_list.setCurrentRow(2)
    picker._apply_advanced_model_settings(picker.model_list.currentItem(), {"temperature": 0.4})
    refreshed = groups()
    refreshed[0]["provider"].update(endpoint_url="https://synthetic-new.invalid", api_key="synthetic-new")
    picker._populate_cloud_model_list(refreshed)
    selected = picker._selected_provider_record()
    assert selected["endpoint_url"] == "https://synthetic-new.invalid"
    assert selected["api_key"] == "synthetic-new" and selected["temperature"] == 0.4


def test_hub_edit_while_local_marks_cached_cloud_list_for_account_refresh(picker, monkeypatch):
    picker.source_combo.setCurrentIndex(picker.source_combo.findData("local"))
    picker._on_model_hub_closed()
    refresh = Mock()
    monkeypatch.setattr(picker, "_refresh_cloud_providers", refresh)
    picker.source_combo.setCurrentIndex(picker.source_combo.findData("cloud"))
    assert GLM["id"] in visible_models(picker)
    refresh.assert_called_once()


class DelayedWorker(QObject):
    result_ready = pyqtSignal(object)
    finished = pyqtSignal()
    instances = []

    def __init__(self, func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.running = False
        self.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def finish(self):
        self.running = False
        self.finished.emit()


def test_catalogue_finishing_after_source_switch_updates_cache_without_overwriting_local_list(picker, monkeypatch):
    monkeypatch.setattr(chat_tab, "SyncWorker", DelayedWorker)
    picker._refresh_provider_catalogs([PROVIDER])
    worker = picker._provider_catalog_worker
    picker.source_combo.setCurrentIndex(picker.source_combo.findData("local"))
    local = QListWidgetItem("Local selection")
    local.setData(Qt.ItemDataRole.UserRole, {"_source_kind": "local_model", "repo_id": "synthetic/local"})
    picker.model_list.addItem(local)
    worker.result_ready.emit(Result.ok(data={"groups": groups(), "errors": []}))
    worker.finish()
    assert picker.model_list.count() == 1 and picker.model_list.item(0).text() == "Local selection"
    assert picker._cloud_model_groups[0]["models"][1]["id"] == GLM["id"]
    picker.source_combo.setCurrentIndex(picker.source_combo.findData("cloud"))
    assert GLM["id"] in visible_models(picker)


def test_obsolete_catalogue_generation_cannot_overwrite_a_new_refresh(picker, monkeypatch):
    monkeypatch.setattr(chat_tab, "SyncWorker", DelayedWorker)
    picker._refresh_provider_catalogs([PROVIDER])
    old = picker._provider_catalog_worker
    picker._provider_catalog_generation += 1
    picker._refresh_provider_catalogs([PROVIDER])
    old.result_ready.emit(Result.ok(data={"groups": groups([dict(FREE, id="obsolete/model")]), "errors": []}))
    assert GLM["id"] in visible_models(picker)
    old.finish()
    latest = picker._provider_catalog_worker
    assert latest is not None and latest is not old
    latest.result_ready.emit(Result.ok(data={"groups": groups([GLM]), "errors": []}))
    latest.finish()
    assert visible_models(picker) == [GLM["id"]]


def test_failed_refresh_keeps_last_catalogue_with_visible_stale_notice_even_after_search(picker, monkeypatch):
    monkeypatch.setattr(chat_tab, "SyncWorker", DelayedWorker)
    picker._refresh_provider_catalogs([PROVIDER])
    worker = picker._provider_catalog_worker
    worker.result_ready.emit(Result.ok(data={"groups": [dict(groups([])[0], catalog_error=True)], "errors": ["unavailable"]}))
    worker.finish()
    search(picker, "glm")
    assert visible_models(picker) == [GLM["id"]]
    assert "Güncellenemedi" in picker.model_status.text()


def test_removed_provider_cannot_be_revived_by_an_older_queued_catalogue_refresh(picker, monkeypatch):
    monkeypatch.setattr(chat_tab, "SyncWorker", DelayedWorker)
    picker._refresh_provider_catalogs([PROVIDER])
    old_catalogue = picker._provider_catalog_worker
    picker._refresh_provider_catalogs([PROVIDER])  # older queued refresh
    picker._refresh_cloud_providers()  # newer account read disables/removes provider
    account_read = picker._providers_worker
    account_read.result_ready.emit(Result.ok(data={"records": []}))
    account_read.finish()
    old_catalogue.result_ready.emit(Result.ok(data={"groups": groups(), "errors": []}))
    old_catalogue.finish()
    assert picker._provider_catalog_worker is None
    assert picker._cloud_model_groups == [] and picker.model_list.count() == 0
    assert picker._selected_provider_record() is None and picker.selected_model_hint.text() == ""
