"""Real pointer/keyboard reasoning selection reaches the native model payload."""
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QAbstractAnimation, QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout

from AI.views import chat_tab
from AI.views.reasoning_control import ReasoningControl


GLM = {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash",
       "supported_parameters": ["tools", "reasoning"],
       "reasoning": {"mandatory": True, "supported_efforts": ["max", "high", "low"], "default_effort": "max"}}


@pytest.fixture
def control():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    control = ReasoningControl(host)
    control.configure_efforts(["auto", "max", "high", "low"], default_effort="max", model_name=GLM["name"])
    layout.addWidget(control)
    host.resize(500, 400)
    host.show()
    app.processEvents()
    yield control
    control.hidePopup()
    host.close()
    host.deleteLater()
    app.processEvents()


def test_pointer_moves_up_to_max_and_down_to_low_with_distinct_brain_detail(control):
    QTest.mouseClick(control, Qt.MouseButton.LeftButton)
    popup = control._popover
    assert popup.isVisible()
    assert "En yüksek" in popup.hint.text()  # Auto uses the actual model default.
    slider = popup.slider
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//2, slider.height()-10))
    QTest.qWait(210)
    assert control.currentData() == "low"
    low = popup.brain.detail
    assert popup.value_label.text() == "Düşük"
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//2, slider.height()-10))
    QTest.mouseMove(slider, QPoint(slider.width()//2, 10))
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//2, 10))
    QTest.qWait(210)
    assert control.currentData() == "max"
    assert popup.brain.detail > low and popup.brain.detail == pytest.approx(1)
    assert popup.value_label.text() == "En yüksek"
    assert control.findData("medium") == -1 and control.findData("off") == -1
    QTest.mouseClick(popup.auto_button, Qt.MouseButton.LeftButton)
    assert control.currentData() == "auto"
    assert popup.auto_button.isChecked()


def test_keyboard_escape_busy_lock_and_model_switch_dismiss_popup(control):
    QTest.keyClick(control, Qt.Key.Key_Space)
    popup = control._popover
    assert popup.isVisible()
    control.setCurrentIndex(control.findData("low"))
    QTest.keyClick(popup.slider, Qt.Key.Key_Up)
    assert control.currentData() == "high"
    QTest.keyClick(popup.slider, Qt.Key.Key_Escape)
    assert not popup.isVisible()
    control.showPopup()
    control.setEnabled(False)
    assert not popup.isVisible()
    control.setEnabled(True)
    control.showPopup()
    control.configure_efforts(["auto", "low", "medium", "high"], model_name="Local reasoning model")
    assert not popup.isVisible()
    assert control.findData("max") == -1 and control.findData("medium") >= 0


def test_popup_stays_in_screen_and_outside_click_dismisses_it(control):
    control.showPopup()
    bounds = control.screen().availableGeometry()
    assert bounds.contains(control._popover.geometry())
    QTest.mouseClick(control.window(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QApplication.processEvents()
    assert not control._popover.isVisible()
    assert control.currentData() == "auto"


@pytest.fixture
def tab(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(chat_tab.AITab, "_refresh_current_source", lambda self: None)
    monkeypatch.setattr(chat_tab, "list_agent_task_states", lambda **kwargs: [])
    widget = chat_tab.AITab()
    widget._schedule_timer.stop()
    widget.resize(1360, 850)
    widget.show()
    widget.source_combo.setCurrentIndex(widget.source_combo.findData("cloud"))
    widget._populate_cloud_model_list([{"provider": {"id": 1, "provider_code": "openrouter", "label": "OpenRouter"},
                                        "models": [GLM]}])
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_real_glm_choice_uses_supported_levels_and_persists_selected_max_into_transport(tab):
    assert [tab.reasoning_combo.itemData(i) for i in range(tab.reasoning_combo.count())] == ["auto", "low", "high", "max"]
    QTest.mouseClick(tab.reasoning_combo, Qt.MouseButton.LeftButton)
    popup = tab.reasoning_combo._popover
    QTest.mouseClick(popup.slider, Qt.MouseButton.LeftButton, pos=QPoint(popup.slider.width()//2, 10))
    selected = tab._selected_provider_record()
    assert selected["reasoning_effort"] == "max"
    assert selected["model_metadata"]["reasoning"]["mandatory"]
    from AI.processors.cloud_runtime import build_provider_chat_client
    from AI.processors import cloud_runtime
    client = build_provider_chat_client({**selected, "api_key": "synthetic-test-key", "allow_model_fallback": False})
    captured = []
    def response(endpoint, **kwargs):
        captured.append(kwargs["payload"])
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    with patch.object(cloud_runtime, "_provider_request_payload", response):
        client("A synthetic UI setting check")
    assert captured and captured[0]["reasoning"]["effort"] == "max"
    assert captured[0]["model"] == GLM["id"]


def test_brain_and_slider_are_visible_and_directly_selectable_inside_the_composer(tab):
    control = tab.reasoning_combo
    composer = tab.composer.parentWidget()
    assert control.parentWidget() is composer
    assert not tab._model_popup.isAncestorOf(control)
    assert control.inline_brain.isVisible() and control.inline_slider.isVisible()
    slider = control.inline_slider
    assert slider.orientation() == Qt.Orientation.Horizontal
    assert slider.geometry().top() > control.inline_brain.geometry().bottom()
    assert abs(slider.geometry().center().x()-control.inline_brain.geometry().center().x()) <= 1
    assert control.inline_title.geometry().left() > slider.geometry().right()
    assert control.manual_efforts() == ["low", "high", "max"]
    assert (slider.minimum(), slider.maximum(), slider.singleStep()) == (0, 2, 1)
    assert control.findData("medium") == -1 and control.findData("off") == -1
    assert control._popover is None
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(10, slider.height()//2))
    QTest.qWait(210)
    assert tab._selected_provider_record()["reasoning_effort"] == "low"
    low_detail = control.inline_brain.detail
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()//2, slider.height()//2))
    assert tab._selected_provider_record()["reasoning_effort"] == "high"
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()-10, slider.height()//2))
    QTest.qWait(210)
    assert tab._selected_provider_record()["reasoning_effort"] == "max"
    assert control.inline_brain.detail > low_detail
    assert control._popover is None  # Selecting needs no separate panel.
    tab.composer.setPlainText("A draft must not restart an unchanged brain animation")
    assert control.inline_brain._animation.state() == QAbstractAnimation.State.Stopped
    QTest.mouseClick(control.inline_auto, Qt.MouseButton.LeftButton)
    assert tab._selected_provider_record()["reasoning_effort"] == "auto"
    # Auto already places the handle at max; clicking that same stop must still
    # select an explicit effort rather than leaving the control in Auto.
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()-10, slider.height()//2))
    assert tab._selected_provider_record()["reasoning_effort"] == "max"


def test_inline_drag_snaps_to_supported_stops_with_brief_feedback_and_horizontal_keyboard_steps(tab):
    control = tab.reasoning_combo
    slider = control.inline_slider
    for ratio, expected, index in ((.62, "high", 1), (.89, "max", 2), (.24, "low", 0)):
        destination = QPoint(round(10+(slider.width()-20)*ratio), slider.height()//2)
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(10, slider.height()//2))
        QTest.mouseMove(slider, destination)
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=destination)
        assert slider.value() == index and not slider.isSliderDown()
        assert tab._selected_provider_record()["reasoning_effort"] == expected
        assert slider._pulse_animation.state() == QAbstractAnimation.State.Running
    QTest.qWait(170)
    assert slider._pulse_animation.state() == QAbstractAnimation.State.Stopped
    assert slider._pulse_strength == pytest.approx(0)
    slider.setFocus()
    for key, expected in ((Qt.Key.Key_Right, "high"), (Qt.Key.Key_Right, "max"),
                          (Qt.Key.Key_Right, "max"), (Qt.Key.Key_Left, "high"),
                          (Qt.Key.Key_Left, "low"), (Qt.Key.Key_Left, "low")):
        QTest.keyClick(slider, key)
        assert tab._selected_provider_record()["reasoning_effort"] == expected
    assert control._popover is None


def test_catalogue_refresh_keeps_high_and_nonreasoning_model_locks_control(tab):
    tab.reasoning_combo.setCurrentIndex(tab.reasoning_combo.findData("high"))
    tab._populate_cloud_model_list([{"provider": {"id": 1, "provider_code": "openrouter", "label": "OpenRouter"},
                                    "models": [GLM]}])
    assert tab.reasoning_combo.currentData() == "high"
    assert tab._selected_provider_record()["reasoning_effort"] == "high"
    plain = {"id": "synthetic/plain", "name": "Plain", "supported_parameters": ["tools"]}
    tab._populate_cloud_model_list([{"provider": {"id": 1, "provider_code": "openrouter", "label": "OpenRouter"},
                                    "models": [plain]}])
    assert not tab.reasoning_combo.isEnabled()
    assert tab.reasoning_combo.count() == 1 and tab.reasoning_combo.currentData() == "auto"
