"""Offline interaction checks for supplied run observations."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QLabel

from AI.views.run_activity import RunActivityPanel


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])
    widget = RunActivityPanel()
    widget.resize(240, 300)
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _flush():
    for _ in range(4):
        QApplication.processEvents()


def _records(panel):
    return [
        panel._records_layout.itemAt(index).widget()
        for index in range(panel._records_layout.count())
    ]


def test_panel_can_be_shown_and_load_supplied_metadata_and_empty_state(panel):
    assert not panel.isVisible()
    panel.set_run("run-empty", status="Bekliyor", elapsed="0 sn", messages=[])
    panel.show()
    _flush()

    assert panel.isVisible()
    assert 200 <= panel.width() <= 280
    assert panel.sizeHint().width() == 240
    assert panel.run_id == "run-empty"
    assert panel.title_label.text() == "İşlem ayrıntıları"
    assert panel.status_label.text() == "Bekliyor"
    assert panel.elapsed_label.text() == "0 sn"
    assert [label.text() for label in _records(panel)] == ["Henüz işlem kaydı yok."]
    panel.hide()
    assert not panel.isVisible()


def test_observations_are_plain_wrapped_text_with_only_consecutive_duplicates_removed(panel):
    markup = '<b>Gerçek kayıt & sonuç</b><img src="https://example.invalid/image.png">'
    panel.set_run(
        "plain", status="<b>Çalışıyor</b>", elapsed="<i>2 sn</i>",
        messages=[markup, markup, "İkinci kayıt", markup], active=True,
    )
    assert [label.text() for label in _records(panel)] == [markup, "İkinci kayıt", markup]
    assert all(label.wordWrap() for label in _records(panel))
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in panel.findChildren(QLabel))
    assert panel.status_label.text() == "<b>Çalışıyor</b>"
    assert panel.elapsed_label.text() == "<i>2 sn</i>"
    assert "#2563EB" in panel.status_label.styleSheet()


def test_only_the_latest_100_observations_are_kept_after_deduplication(panel):
    messages = [f"Gözlem {index}" for index in range(105)]
    panel.set_run("limited", status="Bitti", elapsed="3 sn", messages=messages + [messages[-1]])
    assert [label.text() for label in _records(panel)] == messages[-100:]
    panel.set_run("empty", status="Bekliyor", elapsed="0 sn", messages=["", "  "])
    assert [label.text() for label in _records(panel)] == ["Henüz işlem kaydı yok."]


def test_updates_follow_bottom_only_when_already_there_and_other_runs_open_at_top(panel):
    messages = [f"Gözlem {index}: Yerel sentetik işlem kaydı." for index in range(30)]
    panel.show()
    panel.set_run("one", status="Çalışıyor", elapsed="2 sn", messages=messages, active=True)
    _flush()
    bar = panel.scroll_area.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.value() == 0

    bar.setValue(bar.maximum())
    panel.set_run("one", status="Çalışıyor", elapsed="3 sn", messages=messages + ["Yeni kayıt"])
    _flush()
    assert bar.value() == bar.maximum()

    bar.setValue(bar.maximum() // 3)
    previous_value = bar.value()
    panel.set_run("one", status="Çalışıyor", elapsed="4 sn", messages=messages + ["Bir sonraki kayıt"])
    _flush()
    assert bar.value() == previous_value
    assert bar.value() < bar.maximum()

    panel.set_run("two", status="Tamamlandı", elapsed="5 sn", messages=messages)
    _flush()
    assert panel.run_id == "two"
    assert bar.value() == 0


def test_rapid_updates_do_not_override_new_run_top_position(panel):
    messages = [f"Sentetik gözlem {index}" for index in range(30)]
    panel.show()
    panel.set_run("new", status="Çalışıyor", elapsed="1 sn", messages=messages)
    panel.set_run("new", status="Çalışıyor", elapsed="2 sn", messages=messages + ["Son kayıt"])
    _flush()
    assert panel.scroll_area.verticalScrollBar().maximum() > 0
    assert panel.scroll_area.verticalScrollBar().value() == 0


def test_close_button_emits_request_with_accessible_description(panel):
    panel.show()
    _flush()
    closed = QSignalSpy(panel.close_requested)
    assert panel.close_button.toolTip()
    assert panel.close_button.accessibleName()
    QTest.mouseClick(panel.close_button, Qt.MouseButton.LeftButton)
    assert len(closed) == 1
