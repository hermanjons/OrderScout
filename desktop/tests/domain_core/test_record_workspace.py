from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QRect
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from Core.views import (
    RecordWorkspaceBehaviorAdapter,
    RecordWorkspaceCardRecord,
    CurrencyAmountInput,
    ListLoadingOverlay,
    RecordWorkspaceEditorActionBar,
    RecordWorkspaceListDelegate,
    RecordWorkspaceListWidget,
    RecordWorkspaceScaffold,
    SwitchButton,
    SwitchSelectWidget,
)


class _WorkspaceTestAdapter(RecordWorkspaceBehaviorAdapter):
    def __init__(self, list_widget: RecordWorkspaceListWidget) -> None:
        self._list_widget = list_widget
        self.mode = "edit"
        self.active_record = None

    @property
    def list_widget(self):
        return self._list_widget

    @list_widget.setter
    def list_widget(self, widget) -> None:
        self._list_widget = widget

    def get_mode(self) -> str:
        return self.mode

    def set_mode(self, mode: str) -> None:
        self.mode = str(mode or "edit")

    def get_active_key(self) -> str:
        if self.active_record is None:
            return ""
        return self.get_record_key(self.active_record)

    def get_selected_count(self) -> int:
        return len(self._list_widget.get_selected_records()) if self._list_widget is not None else 0

    def get_record_key(self, record) -> str:
        return str(getattr(record, "recordKey", getattr(record, "orderNumber", "")) or "")

    def prepare_new(self) -> None:
        self.active_record = None
        if self._list_widget is not None:
            self._list_widget.clear_active_record()

    def activate_record(self, record) -> None:
        self.active_record = record
        if self._list_widget is not None:
            self._list_widget.set_active_record(record)

    def clear_active(self) -> None:
        self.active_record = None
        if self._list_widget is not None:
            self._list_widget.clear_active_record()

    def apply_selection(self, record, selected: bool) -> None:
        if self._list_widget is not None:
            self._list_widget.set_record_selected(record, bool(selected))

    def set_select_button_guide_enabled(self, enabled: bool) -> None:
        if self._list_widget is not None:
            self._list_widget.set_select_button_guide_enabled(enabled)

    def on_state_changed(self) -> None:
        return

    def edit_guidance_message(self) -> str:
        return "edit"

    def bulk_guidance_message(self) -> str:
        return "bulk"


class TestRecordWorkspaceScaffold(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_editor_actions_card_can_be_disabled_by_flag(self) -> None:
        widget = RecordWorkspaceScaffold(show_editor_actions_card=False)
        self.assertFalse(widget._show_editor_actions_card)
        self.assertFalse(widget.editor_actions_host.isVisible())
        self.assertFalse(widget.editor_actions_card.isVisible())
        widget.set_editor_actions_widget(QLabel("ignored"))
        self.assertFalse(widget.editor_actions_host.isVisible())
        self.assertFalse(widget.editor_actions_card.isVisible())

    def test_scaffold_exposes_default_editor_action_bar(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        self.assertIsInstance(widget.editor_action_bar, RecordWorkspaceEditorActionBar)
        self.assertIs(widget.editor_action_bar.parentWidget(), widget.editor_actions_card)
        self.assertEqual(widget.editor_action_bar.clear_button.text(), "Temizle")
        self.assertEqual(widget.editor_action_bar.save_button.text(), "Kaydet")
        self.assertTrue(widget.editor_action_bar.delete_button.isHidden())

        widget.set_editor_action_mode("edit")
        self.assertEqual(widget.editor_action_bar.save_button.text(), "Güncelle")
        self.assertFalse(widget.editor_action_bar.delete_button.isHidden())
        widget.set_editor_action_delete_available(False)
        self.assertTrue(widget.editor_action_bar.delete_button.isHidden())
        widget.set_editor_action_delete_available(True)
        self.assertFalse(widget.editor_action_bar.delete_button.isHidden())

    def test_scaffold_controls_editor_action_visibility_by_mode(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        widget.set_editor_action_mode("bulk")
        self.assertTrue(widget.editor_actions_host.isHidden())

        widget.set_editor_action_mode("edit")
        self.assertFalse(widget.editor_actions_host.isHidden())

        widget.set_editor_actions_visible_modes({"new", "edit", "bulk"})
        widget.set_editor_action_mode("bulk")
        self.assertFalse(widget.editor_actions_host.isHidden())

    def test_editor_content_inset_preserves_outer_glow_space(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        margins = widget.editor_layout.contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (8, 6, 8, 6))

    def test_editor_host_does_not_force_inline_background_style(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        self.assertIn("QWidget#EditorCanvas", widget.editor_host.styleSheet())
        self.assertIn("transparent", widget.editor_host.styleSheet())

    def test_editor_canvas_color_styles_viewport_and_canvas_only(self) -> None:
        widget = RecordWorkspaceScaffold(editor_canvas_color="#FFFFFF")
        self.addCleanup(widget.close)

        self.assertIn("QWidget#EditorCanvas", widget.editor_host.styleSheet())
        self.assertIn("#FFFFFF", widget.editor_host.styleSheet())
        self.assertIn("QScrollArea::viewport", widget.editor_scroll.styleSheet())
        self.assertIn("#FFFFFF", widget.editor_scroll.styleSheet())

    def test_editor_surface_color_styles_wrapper_only(self) -> None:
        widget = RecordWorkspaceScaffold(editor_surface_color="#FFFFFF")
        self.addCleanup(widget.close)

        self.assertIn("QWidget#EditorCanvas", widget.editor_host.styleSheet())
        self.assertIn("transparent", widget.editor_host.styleSheet())
        self.assertIn("QFrame#EditorSurface", widget.editor_surface.styleSheet())
        self.assertIn("#FFFFFF", widget.editor_surface.styleSheet())

    def test_editor_scroll_styles_only_viewport_and_not_descendant_widgets(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        scroll_qss = widget.editor_scroll.styleSheet()
        self.assertIn("QScrollArea::viewport", scroll_qss)
        self.assertNotIn("QScrollArea > QWidget", scroll_qss)
        self.assertNotIn("QScrollArea > QWidget > QWidget", scroll_qss)

    def test_hook_rect_helper_centers_against_card_height(self) -> None:
        delegate = RecordWorkspaceListDelegate()
        rect = QRect(0, 0, 520, 176)
        hook_rect = delegate._build_hook_rect(rect, content_right=500)
        self.assertLessEqual(abs(hook_rect.center().y() - rect.center().y()), 1)

    def test_hook_content_right_respects_right_margin(self) -> None:
        delegate = RecordWorkspaceListDelegate()
        rect = QRect(0, 0, 520, 176)
        self.assertEqual(delegate._hook_content_right(rect, right_margin=12), rect.right() - 12)

    def test_footer_binding_preserves_current_page(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        list_widget = RecordWorkspaceListWidget(empty_placeholder_text="x")
        list_widget.page_size = 50
        list_widget.current_page = 3

        widget.footer_bar.bind_list_widget(list_widget)

        self.assertEqual(list_widget.current_page, 3)
        self.assertEqual(widget.footer_bar.page_size_combo.currentData(), 50)

    def test_controller_uses_record_identity_when_keys_collide(self) -> None:
        widget = RecordWorkspaceScaffold()
        widget.resize(1280, 800)
        widget.show()
        self.addCleanup(widget.close)
        self._app.processEvents()

        list_widget = RecordWorkspaceListWidget(empty_placeholder_text="x")
        widget.set_list_widget(list_widget)
        adapter = _WorkspaceTestAdapter(list_widget)
        controller = widget.create_behavior_controller(adapter=adapter)

        first = RecordWorkspaceCardRecord(orderNumber="dup", title="A", subtitle="", extra="", logo_path="")
        second = RecordWorkspaceCardRecord(orderNumber="dup", title="B", subtitle="", extra="", logo_path="")
        list_widget.set_records([first, second])
        adapter.activate_record(first)
        widget.shell.open_left_panel()
        controller.sync_state()
        self._app.processEvents()

        controller.handle_record_clicked(second)
        self._app.processEvents()

        self.assertTrue(widget.shell.is_left_panel_open())
        self.assertIs(adapter.active_record, second)
        self.assertEqual(list_widget._model._active_row, 1)
        self.assertTrue(list_widget.is_active_record(second))
        self.assertFalse(list_widget.is_active_record(first))

        controller.handle_record_clicked(second)
        self._app.processEvents()
        self.assertFalse(widget.shell.is_left_panel_open())

    def test_row_click_switches_active_record_instead_of_closing_panel(self) -> None:
        widget = RecordWorkspaceScaffold()
        widget.resize(1280, 800)
        widget.show()
        self.addCleanup(widget.close)
        self._app.processEvents()

        list_widget = RecordWorkspaceListWidget(empty_placeholder_text="x")
        widget.set_list_widget(list_widget)
        adapter = _WorkspaceTestAdapter(list_widget)
        controller = widget.create_behavior_controller(adapter=adapter)

        first = RecordWorkspaceCardRecord(orderNumber="1", title="A", subtitle="", extra="", logo_path="")
        second = RecordWorkspaceCardRecord(orderNumber="2", title="B", subtitle="", extra="", logo_path="")
        list_widget.set_records([first, second])
        adapter.activate_record(first)
        widget.shell.open_left_panel()
        controller.sync_state()
        self._app.processEvents()

        second_index = list_widget.model().index(1, 0)
        list_widget._on_row_clicked(second_index)
        self._app.processEvents()

        self.assertTrue(widget.shell.is_left_panel_open())
        self.assertIs(adapter.active_record, second)
        self.assertTrue(list_widget.is_active_record(second))
        self.assertFalse(list_widget.is_active_record(first))

    def test_shell_event_filter_tolerates_missing_host_attribute(self) -> None:
        widget = RecordWorkspaceScaffold()
        self.addCleanup(widget.close)

        shell = widget.shell
        del shell.host

        handled = shell.eventFilter(widget, QEvent(QEvent.Type.Resize))

        self.assertFalse(bool(handled))

    def test_list_loading_overlay_suppresses_target_without_graphics_effect(self) -> None:
        host = QWidget()
        host.resize(320, 180)
        target = QLabel("Rows", host)
        target.setGeometry(10, 10, 240, 120)
        overlay = ListLoadingOverlay(host, target=target, hide_target_content_while_busy=True)
        self.addCleanup(host.close)
        host.show()
        self._app.processEvents()

        overlay.set_busy(True, message="Loading")
        self._app.processEvents()

        self.assertTrue(overlay.isVisible())
        self.assertFalse(target.updatesEnabled())
        self.assertIsNone(target.graphicsEffect())

        overlay.set_busy(False)
        self._app.processEvents()

        self.assertTrue(target.updatesEnabled())

    def test_replacing_list_widget_replays_controller_state(self) -> None:
        widget = RecordWorkspaceScaffold()
        widget.resize(1280, 800)
        widget.show()
        self.addCleanup(widget.close)
        self._app.processEvents()

        first_list = RecordWorkspaceListWidget(empty_placeholder_text="x")
        widget.set_list_widget(first_list)
        adapter = _WorkspaceTestAdapter(first_list)
        adapter.set_mode("bulk")
        controller = widget.create_behavior_controller(adapter=adapter)
        widget.shell.open_left_panel()
        controller.sync_state()
        self._app.processEvents()
        self.assertTrue(first_list._guide_select_animation_enabled)

        second_list = RecordWorkspaceListWidget(empty_placeholder_text="x")
        adapter.list_widget = second_list
        widget.set_list_widget(second_list)
        self._app.processEvents()

        self.assertTrue(second_list._guide_select_animation_enabled)

    def test_core_widgets_do_not_create_disabled_lock_badges(self) -> None:
        widgets = (
            SwitchSelectWidget(multi=False, search_enabled=False),
            CurrencyAmountInput(),
            SwitchButton(),
        )
        for widget in widgets:
            self.addCleanup(widget.deleteLater)
            if hasattr(widget, "setLockOnDisabled"):
                widget.setLockOnDisabled(True)
            widget.setEnabled(False)
            widget.show()
            self._app.processEvents()

            self.assertFalse(getattr(widget, "lockOnDisabled", lambda: False)())
            self.assertIsNone(getattr(widget, "_disabled_lock_badge", None))
            self.assertEqual(widget.findChildren(QLabel, "DisabledLockReasonLabel"), [])


if __name__ == "__main__":
    unittest.main()
