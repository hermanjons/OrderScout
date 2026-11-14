"""Exercise model-picker signals with real Qt input and synthetic catalog data.

The original header click caused a Windows access violation: its first signal
slot deleted the QListWidgetItem before the popup-close slot read item.data().
"""
from __future__ import annotations

import sys
import traceback

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from AI.views import chat_tab


@pytest.fixture
def picker(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda self: None)
    monkeypatch.setattr(chat_tab, "list_agent_task_states", lambda **kwargs: [])
    errors = []
    # Unhandled PyQt slots otherwise terminate the process, hiding the assertion.
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append("".join(traceback.format_exception(*exc))))
    widget = chat_tab.AITab()
    widget._schedule_timer.stop()
    widget.resize(1360, 850)
    widget.show()
    app.processEvents()
    widget.source_combo.setCurrentIndex(widget.source_combo.findData("cloud"))
    widget._populate_cloud_model_list([
        {
            "provider": {"id": 71, "provider_code": "openrouter", "label": "Synthetic OpenRouter"},
            "models": [
                {"id": "synthetic/alpha:free", "name": "Alpha", "is_free": True},
                {"id": "synthetic/beta:free", "name": "Beta", "is_free": True},
            ],
        },
    ])
    QTest.mouseClick(widget.btn_model_picker, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget._model_popup.isVisible()
    yield widget, errors
    widget.close()
    widget.deleteLater()
    app.processEvents()
    assert not errors, "\n".join(errors)


def click_row(widget, row, *, target="viewport", process_events=True):
    item = widget.model_list.item(row)
    if target == "label":
        receiver = widget.model_list.viewport()
        rect = widget.model_list.visualItemRect(item)
        point = QPoint(rect.left() + 30, rect.top() + 15)
    else:
        receiver = widget.model_list.viewport()
        point = widget.model_list.visualItemRect(item).center()
    QTest.mousePress(receiver, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(receiver, Qt.MouseButton.LeftButton, pos=point)
    if process_events:
        QApplication.processEvents()


@pytest.mark.parametrize("target", ["viewport", "label"])
def test_provider_click_expands_and_collapses_without_closing_popup(picker, target):
    widget, errors = picker
    delivered = []
    widget.model_list.itemClicked.connect(lambda item: delivered.append(item.data(Qt.ItemDataRole.UserRole)))
    assert widget.model_list.count() == 3
    for expected_count in (1, 3, 1, 3):
        click_row(widget, 0, target=target)
        assert not errors, "\n".join(errors)
        assert widget._model_popup.isVisible()
        assert sum(not widget.model_list.item(index).isHidden() for index in range(widget.model_list.count())) == expected_count
        assert widget.model_status.text() == "2 model · Tümü"
    assert len(delivered) == 4
    assert all(row["_source_kind"] == "cloud_provider_header" for row in delivered)


def test_clicking_model_selects_it_and_closes_popup(picker):
    widget, errors = picker
    click_row(widget, 2)
    assert not errors, "\n".join(errors)
    assert widget._selected_provider_record()["default_model"] == "synthetic/beta:free"
    assert "Beta" in widget.btn_model_picker.text()
    assert not widget._model_popup.isVisible()


def test_keyboard_provider_activation_keeps_popup_open_then_accepts_model(picker):
    widget, errors = picker
    widget.model_list.setFocus()
    widget.model_list.setCurrentRow(0)
    QTest.keyClick(widget.model_list, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert not errors, "\n".join(errors)
    assert widget.model_list.item(1).isHidden() and widget.model_list.item(2).isHidden()
    assert widget._model_popup.isVisible()
    QTest.keyClick(widget.model_list, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert widget.model_list.count() == 3
    assert widget._model_popup.isVisible()
    widget.model_list.setCurrentRow(2)
    QTest.keyClick(widget.model_list, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert widget._selected_provider_record()["default_model"] == "synthetic/beta:free"
    assert not widget._model_popup.isVisible()


def test_pending_provider_rebuild_is_cancelled_after_switching_source(picker):
    widget, errors = picker
    click_row(widget, 0, process_events=False)
    widget.source_combo.setCurrentIndex(widget.source_combo.findData("local"))
    QApplication.processEvents()
    assert not errors, "\n".join(errors)
    assert widget.source_combo.currentData() == "local"
    assert widget.model_list.count() == 0


def provider_header_row(widget, provider_id):
    return next(index for index in range(widget.model_list.count())
                if (widget.model_list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("_provider_key") == str(provider_id))


@pytest.mark.parametrize("activation", ["mouse", "keyboard"])
def test_header_navigation_preserves_selected_provider_model_and_settings(picker, activation):
    widget, errors = picker
    groups = widget._cloud_model_groups + [{
        "provider": {"id": 72, "provider_code": "openrouter", "label": "Second synthetic account"},
        "models": [{"id": "synthetic/beta:free", "name": "Beta on second account", "is_free": True}],
    }]
    widget._populate_cloud_model_list(groups)
    click_row(widget, 4)
    widget.reasoning_combo.setCurrentIndex(widget.reasoning_combo.findData("high"))
    widget.fallback_checkbox.setChecked(False)
    widget.composer.setPlainText("Synthetic test message")
    assert widget.btn_send.isEnabled()
    QTest.mouseClick(widget.btn_model_picker, Qt.MouseButton.LeftButton)
    for provider_id in (72, 71, 72, 71):
        row = provider_header_row(widget, provider_id)
        if activation == "mouse":
            click_row(widget, row)
        else:
            widget.model_list.setCurrentRow(row)
            QTest.keyClick(widget.model_list, Qt.Key.Key_Return)
            QApplication.processEvents()
        selected = widget._selected_provider_record()
        assert (selected["id"], selected["default_model"]) == (72, "synthetic/beta:free")
        assert selected["reasoning_effort"] == "high"
        assert selected["allow_model_fallback"] is False
        assert widget.composer_meta.text() == "Beta on second account"
        assert widget.reasoning_combo.currentData() == "high"
        assert not widget.fallback_checkbox.isChecked()
        assert widget.btn_send.isEnabled()
        assert widget._model_popup.isVisible()
    QTest.keyClick(widget._model_popup, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not widget._model_popup.isVisible()
    assert widget._selected_provider_record()["id"] == 72
    assert not errors, "\n".join(errors)


def test_collapsed_selected_model_accepts_settings_and_remains_searchable(picker):
    widget, errors = picker
    click_row(widget, 2)
    QTest.mouseClick(widget.btn_model_picker, Qt.MouseButton.LeftButton)
    click_row(widget, 0)
    assert not widget.model_list.item(0).isHidden()
    assert widget.model_list.item(2).isHidden()
    widget.model_search.setText("Beta")
    QTest.qWait(120)
    assert not widget.model_list.item(2).isHidden()
    widget.reasoning_combo.setCurrentIndex(widget.reasoning_combo.findData("high"))
    widget.fallback_checkbox.setChecked(False)
    QTest.mouseClick(widget.btn_advanced_model_settings, Qt.MouseButton.LeftButton)
    assert widget._advanced_dialog is not None
    assert widget._advanced_dialog._record["default_model"] == "synthetic/beta:free"
    widget._advanced_dialog.close()
    widget._apply_advanced_model_settings(None, {"temperature": 0.4})
    QTest.mouseClick(widget.btn_model_picker, Qt.MouseButton.LeftButton)
    click_row(widget, 0)
    selected = widget._selected_provider_record()
    assert selected["default_model"] == "synthetic/beta:free"
    assert selected["reasoning_effort"] == "high"
    assert selected["allow_model_fallback"] is False
    assert selected["temperature"] == 0.4
    assert not errors, "\n".join(errors)


def test_catalog_refresh_invalidates_removed_selected_model(picker):
    widget, errors = picker
    click_row(widget, 2)
    widget._populate_cloud_model_list([
        {"provider": {"id": 71, "provider_code": "openrouter", "label": "Synthetic OpenRouter"}, "models": []},
    ], preserve_model_id="synthetic/beta:free")
    assert widget._selected_provider_record() is None
    assert not errors, "\n".join(errors)


def test_advanced_apply_after_catalog_rebuild_rejects_deleted_target(picker):
    widget, errors = picker
    QTest.mouseClick(widget.btn_advanced_model_settings, Qt.MouseButton.LeftButton)
    dialog = widget._advanced_dialog
    assert dialog is not None
    dialog._fields["temperature"].setText("0.6")
    widget._populate_cloud_model_list(widget._cloud_model_groups)
    QTest.mouseClick(dialog.findChild(QPushButton, "Primary"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not errors, "\n".join(errors)
    assert widget._selected_provider_record().get("temperature") is None
    assert "Model listesi değişti" in widget.model_status.text()


def test_advanced_apply_for_collapsed_model_does_not_modify_replacement_model(picker):
    widget, errors = picker
    click_row(widget, 0)
    QTest.mouseClick(widget.btn_advanced_model_settings, Qt.MouseButton.LeftButton)
    dialog = widget._advanced_dialog
    assert dialog is not None
    dialog._fields["temperature"].setText("0.6")
    widget._populate_cloud_model_list([{
        "provider": {"id": 72, "provider_code": "openrouter", "label": "Replacement"},
        "models": [{"id": "synthetic/replacement:free", "name": "Replacement", "is_free": True}],
    }])
    QTest.mouseClick(dialog.findChild(QPushButton, "Primary"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not errors, "\n".join(errors)
    assert widget._selected_provider_record()["default_model"] == "synthetic/replacement:free"
    assert widget._selected_provider_record().get("temperature") is None
    assert "Model listesi değişti" in widget.model_status.text()
