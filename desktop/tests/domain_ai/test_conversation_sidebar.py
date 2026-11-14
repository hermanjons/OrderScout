from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from AI.views.conversation_sidebar import ConversationSidebar


@pytest.fixture
def sidebar(monkeypatch):
    app = QApplication.instance() or QApplication([])
    now = datetime(2026, 10, 20, 16, 0, tzinfo=timezone(timedelta(hours=3)))
    monkeypatch.setattr("AI.views.conversation_sidebar._local_now", lambda: now)
    widget = ConversationSidebar()
    widget.resize(242, 550)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _rows():
    return [
        {"session_id": "today", "title": "İlan fiyatları", "status": "complete", "updated_at": "2026-10-20T11:32:00Z"},
        {"session_id": "yesterday", "goal": "IŞIK stok raporu", "status": "paused", "updated_at": "2026-10-19T08:00:00Z"},
        {"session_id": "week", "goal": "Sipariş özeti", "status": "running", "updated_at": "2026-10-17T08:00:00Z"},
        {"session_id": "old", "goal": "İade incelemesi", "status": "pending_approval", "updated_at": "2026-10-01T08:00:00Z"},
    ]


def _items(sidebar):
    return [sidebar.session_list.item(index) for index in range(sidebar.session_list.count())
            if sidebar.session_list.item(index).data(Qt.ItemDataRole.UserRole)]


def _ids(sidebar):
    return [item.data(Qt.ItemDataRole.UserRole) for item in _items(sidebar)]


def _row(sidebar, session_id):
    item = next(item for item in _items(sidebar) if item.data(Qt.ItemDataRole.UserRole) == session_id)
    return sidebar.session_list.itemWidget(item)


def test_refresh_selects_active_session_without_requesting_a_load(sidebar):
    requested = QSignalSpy(sidebar.session_requested)
    sidebar.set_sessions(_rows(), active_session_id="yesterday")

    assert sidebar.session_list.currentItem().data(Qt.ItemDataRole.UserRole) == "yesterday"
    assert _row(sidebar, "yesterday").property("active") is True
    assert _row(sidebar, "today").property("active") is False
    sidebar.set_sessions(list(reversed(_rows())), active_session_id="today")
    assert sidebar.session_list.currentItem().data(Qt.ItemDataRole.UserRole) == "today"
    assert not requested

    sidebar.set_sessions(_rows(), active_session_id="missing")
    assert not sidebar.session_list.selectedItems()
    assert sidebar.session_list.currentItem() is None
    assert not requested


def test_clicking_the_current_session_requests_it_once_per_click(sidebar):
    sidebar.set_sessions(_rows(), active_session_id="today")
    QApplication.processEvents()
    requested = QSignalSpy(sidebar.session_requested)
    item = _items(sidebar)[0]
    point = sidebar.session_list.visualItemRect(item).center()

    QTest.mouseClick(sidebar.session_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert list(requested) == [["today"]]
    QTest.mouseClick(sidebar.session_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert list(requested) == [["today"], ["today"]]


def test_local_filter_handles_turkish_case_and_goal_fallback_without_loading(sidebar):
    sidebar.set_sessions(_rows(), active_session_id="today")
    requested = QSignalSpy(sidebar.session_requested)
    sidebar.search_field.setText("ilan")
    assert _ids(sidebar) == ["today"]
    sidebar.search_field.setText("ışık")
    assert _ids(sidebar) == ["yesterday"]
    sidebar.search_field.setText("SİPARİŞ")
    assert _ids(sidebar) == ["week"]
    sidebar.search_field.setText("bulunmayan")
    assert not _items(sidebar)
    assert sidebar._empty_label.text() == "Eşleşen sohbet bulunamadı."
    sidebar.search_field.clear()
    assert _ids(sidebar) == ["today", "yesterday", "week", "old"]
    assert sidebar.session_list.currentItem().data(Qt.ItemDataRole.UserRole) == "today"
    assert not requested


def test_busy_blocks_all_navigation_but_search_remains_usable(sidebar):
    sidebar.set_sessions(_rows(), active_session_id="today")
    spies = [QSignalSpy(signal) for signal in (
        sidebar.session_requested, sidebar.new_chat_requested, sidebar.workflows_requested, sidebar.schedules_requested,
    )]
    sidebar.set_busy(True)
    assert not sidebar.session_list.isEnabled()
    assert sidebar.search_field.isEnabled()
    for button in (sidebar.new_chat_button, sidebar.workflows_button, sidebar.schedules_button):
        assert not button.isEnabled()
        button.click()
        button.clicked.emit()  # A queued signal must also respect the busy guard.
    sidebar.session_list.itemClicked.emit(_items(sidebar)[0])
    sidebar.search_field.setText("ilan")
    assert _ids(sidebar) == ["today"]
    assert all(not spy for spy in spies)

    sidebar.set_busy(False)
    assert sidebar.session_list.isEnabled()
    for button in (sidebar.new_chat_button, sidebar.workflows_button, sidebar.schedules_button):
        button.click()
    assert [len(spy) for spy in spies] == [0, 1, 1, 1]


def test_groups_use_local_dates_and_do_not_label_old_running_sessions_live(sidebar):
    rows = _rows() + [
        {"session_id": "midnight", "goal": "Yerel gece", "status": "complete", "updated_at": "2026-10-19T22:30:00Z"},
        {"session_id": "unknown-date", "goal": "Eski kayıt", "status": "failed", "updated_at": "invalid"},
        {"session_id": "count-pending", "goal": "Onay işlemi", "status": "complete", "pending_count": 2,
         "updated_at": "2026-10-20T08:00:00Z"},
    ]
    sidebar.set_sessions(rows, active_session_id="today")
    headers = [sidebar.session_list.item(index) for index in range(sidebar.session_list.count())
               if not sidebar.session_list.item(index).data(Qt.ItemDataRole.UserRole)]
    assert [item.text() for item in headers] == ["BUGÜN", "DÜN", "BU HAFTA", "DAHA ESKİ"]
    assert all(not item.flags() & Qt.ItemFlag.ItemIsSelectable for item in headers)
    assert _ids(sidebar)[:3] == ["today", "count-pending", "midnight"]
    assert _row(sidebar, "midnight").meta_label.text() == "01:30 · Tamamlandı"
    assert _row(sidebar, "week").meta_label.text() == "17 Ekim · Yarım kaldı"
    assert _row(sidebar, "old").meta_label.text() == "1 Ekim · Onay bekliyor"
    assert _row(sidebar, "unknown-date").meta_label.text() == "Tarih yok · Tamamlanamadı"
    assert _row(sidebar, "count-pending").meta_label.property("pending") is True
    sidebar.set_busy(True)
    assert "Yarım kaldı" in _row(sidebar, "week").meta_label.text()


def test_only_the_active_running_session_can_display_live_status(sidebar):
    sidebar.set_sessions(_rows(), active_session_id="week")
    assert "Yarım kaldı" in _row(sidebar, "week").meta_label.text()
    sidebar.set_busy(True)
    assert "Çalışıyor" in _row(sidebar, "week").meta_label.text()
    sidebar.set_busy(False)
    assert "Yarım kaldı" in _row(sidebar, "week").meta_label.text()


def test_titles_are_plain_text_elided_and_accessible(sidebar):
    title = '<b>İlanlar</b> <img src="remote"> ' + "uzun başlık " * 14
    sidebar.set_sessions([{"session_id": "literal", "title": title, "status": "complete"}], "literal")
    QApplication.processEvents()
    row = _row(sidebar, "literal")
    assert row.title_label.textFormat() == Qt.TextFormat.PlainText
    assert row.meta_label.textFormat() == Qt.TextFormat.PlainText
    assert row.title_label.full_text == title.strip()
    assert row.title_label.text().startswith("<b>")
    assert row.title_label.text().endswith("…")
    assert "&lt;b&gt;" in row.title_label.toolTip()
    assert row.title_label.accessibleName() == title.strip()
    assert all(widget.accessibleName() for widget in (
        sidebar, sidebar.session_list, sidebar.search_field, sidebar.new_chat_button,
        sidebar.workflows_button, sidebar.schedules_button,
    ))
    assert sidebar.minimumWidth() == 200
    assert sidebar.maximumWidth() == 300
    assert sidebar.sizeHint().width() == 242


def test_same_filter_refresh_preserves_scroll_and_does_not_request_a_load(sidebar):
    rows = [{"session_id": f"row-{index}", "goal": f"Sipariş {index}", "status": "complete",
             "updated_at": "2026-10-20T08:00:00Z"} for index in range(60)]
    sidebar.set_sessions(rows, "row-0")
    sidebar.search_field.setText("sipariş")
    QApplication.processEvents()
    bar = sidebar.session_list.verticalScrollBar()
    bar.setValue(500)
    previous = bar.value()
    assert previous > 0
    requested = QSignalSpy(sidebar.session_requested)

    sidebar.set_sessions(rows, "row-0")
    QApplication.processEvents()
    assert sidebar.search_field.text() == "sipariş"
    assert bar.value() == previous
    assert not requested


def test_keyboard_activation_requests_one_session_and_empty_state_is_clear(sidebar):
    sidebar.set_sessions(_rows(), "today")
    requested = QSignalSpy(sidebar.session_requested)
    QTest.keyClick(sidebar.session_list, Qt.Key.Key_Return)
    assert list(requested) == [["today"]]
    sidebar.set_sessions([])
    assert not _items(sidebar)
    assert sidebar._empty_label.text() == "Henüz sohbet yok."
    assert sidebar._empty_label.textFormat() == Qt.TextFormat.PlainText
