from __future__ import annotations

import os
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication, QWidget

from Testing.views import test_lab_dialog


def _widget_rect_in(widget: QWidget, root: QWidget) -> QRect:
    top_left = widget.mapTo(root, QPoint(0, 0))
    return QRect(top_left, widget.size())


class TestTestingViews(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_diagnostics_layout_keeps_controls_non_overlapping(self) -> None:
        old_load = test_lab_dialog.TestLabDialog.load_companies
        test_lab_dialog.TestLabDialog.load_companies = lambda self: None
        try:
            dlg = test_lab_dialog.TestLabDialog()
            dlg._open_diagnostics_window()
            wnd = dlg._feature_windows["diagnostics"]
            wnd.showNormal()
            wnd.resize(1880, 980)
            wnd.show()
            self._app.processEvents()

            widgets = [
                dlg.test_pattern,
                dlg.test_timeout,
                dlg.btn_run_unittests,
                dlg.btn_run_healthcheck_from_diag,
                dlg.btn_run_listing_order_smoke,
                dlg.btn_run_cargo_sandbox,
                dlg.btn_run_stock_depletion,
                dlg.btn_run_label_stress,
                dlg.cargo_platform_input,
                dlg.cargo_provider_input,
                dlg.cargo_sale_price_input,
                dlg.cargo_desi_input,
                dlg.stock_depletion_count,
                dlg.label_stress_count,
                dlg.chaos_mode_combo,
                dlg.chaos_rate_spin,
                dlg.btn_apply_chaos,
            ]
            rects = [
                (widget.objectName() or widget.__class__.__name__ or str(index), _widget_rect_in(widget, wnd))
                for index, widget in enumerate(widgets)
                if widget is not None and widget.isVisible()
            ]
            for idx, (name, rect) in enumerate(rects):
                for other_name, other_rect in rects[idx + 1 :]:
                    self.assertFalse(
                        rect.intersects(other_rect),
                        f"{name} overlaps {other_name}: {rect} vs {other_rect}",
                    )
        finally:
            test_lab_dialog.TestLabDialog.load_companies = old_load

    def test_stage_lab_is_available_from_ui_and_keeps_controls_visible(self) -> None:
        old_load = test_lab_dialog.TestLabDialog.load_companies
        old_stage_context = test_lab_dialog.TestLabDialog.load_stage_context
        test_lab_dialog.TestLabDialog.load_companies = lambda self: None
        test_lab_dialog.TestLabDialog.load_stage_context = lambda self: None
        try:
            dlg = test_lab_dialog.TestLabDialog()
            self.assertEqual(dlg.tabs.count(), 5)
            self.assertEqual(dlg.tabs.tabText(2), "Stage")

            dlg._open_stage_window()
            wnd = dlg._feature_windows["stage_lab"]
            wnd.showNormal()
            wnd.resize(1280, 860)
            wnd.show()
            self._app.processEvents()

            controls = [
                dlg.stage_listing_combo,
                dlg.stage_quantity,
                dlg.btn_stage_create_order,
                dlg.stage_order_combo,
                dlg.stage_status_combo,
                dlg.btn_stage_advance_order,
                dlg.btn_stage_create_return,
                dlg.stage_claim_combo,
                dlg.btn_stage_waiting_action,
                dlg.btn_stage_approve_return,
                dlg.btn_stage_full_lifecycle,
                dlg.btn_stage_refresh,
            ]
            for widget in controls:
                self.assertTrue(widget.isVisible())
                self.assertTrue(wnd.rect().contains(_widget_rect_in(widget, wnd)))
            self.assertGreaterEqual(dlg.stage_log.height(), 150)
        finally:
            test_lab_dialog.TestLabDialog.load_companies = old_load
            test_lab_dialog.TestLabDialog.load_stage_context = old_stage_context

    def test_stage_lab_ui_routes_every_control_through_actions(self) -> None:
        old_companies = test_lab_dialog.TestLabDialog.load_companies
        old_stage_context = test_lab_dialog.TestLabDialog.load_stage_context
        test_lab_dialog.TestLabDialog.load_companies = lambda self: None
        test_lab_dialog.TestLabDialog.load_stage_context = lambda self: None
        try:
            dlg = test_lab_dialog.TestLabDialog()
            dlg.company_combo.addItem("Stage QA", 7)
            dlg._open_stage_window()
            dlg.stage_listing_combo.addItem(
                "Official test product",
                {"barcode": "9900000000486", "official_test_product": True},
            )
            dlg.stage_order_combo.addItem(
                "QA-123 | Delivered",
                {"order_number": "QA-123", "status": "Delivered"},
            )
            dlg.stage_claim_combo.addItem(
                "claim-1 | WaitingInAction",
                {"claim_id": "claim-1", "status": "WaitingInAction"},
            )

            calls: list[tuple[object, dict]] = []
            dlg._run_worker = lambda func, *, done, **kwargs: calls.append((func, kwargs))

            dlg.btn_stage_create_order.click()
            dlg.btn_stage_advance_order.click()
            dlg.btn_stage_create_return.click()
            dlg.btn_stage_waiting_action.click()
            dlg.btn_stage_approve_return.click()
            dlg.btn_stage_full_lifecycle.click()

            self.assertEqual(
                [func for func, _kwargs in calls],
                [
                    test_lab_dialog.action_create_stage_test_order,
                    test_lab_dialog.action_advance_stage_order_status,
                    test_lab_dialog.action_create_stage_return_claim,
                    test_lab_dialog.action_advance_stage_claim_to_waiting_action,
                    test_lab_dialog.action_approve_stage_return,
                    test_lab_dialog.action_run_stage_return_lifecycle,
                ],
            )
            self.assertTrue(all(kwargs.get("api_account_id") == 7 for _func, kwargs in calls))
            self.assertEqual(calls[0][1]["barcode"], "9900000000486")
            self.assertEqual(calls[1][1]["order_number"], "QA-123")
            self.assertEqual(calls[3][1]["claim_id"], "claim-1")
        finally:
            test_lab_dialog.TestLabDialog.load_companies = old_companies
            test_lab_dialog.TestLabDialog.load_stage_context = old_stage_context

    def test_diagnostics_sandbox_controls_are_not_clipped_by_log_splitter(self) -> None:
        old_load = test_lab_dialog.TestLabDialog.load_companies
        test_lab_dialog.TestLabDialog.load_companies = lambda self: None
        try:
            dlg = test_lab_dialog.TestLabDialog()
            dlg._open_diagnostics_window()
            wnd = dlg._feature_windows["diagnostics"]
            wnd.showNormal()
            wnd.resize(1280, 860)
            wnd.show()
            self._app.processEvents()

            controls = dlg.diagnostics_controls_card
            controls_scroll = dlg.diagnostics_controls_scroll
            self.assertIsNotNone(controls)
            self.assertIsNotNone(controls_scroll)
            self.assertGreaterEqual(controls_scroll.viewport().height(), controls.minimumHeight())
            self.assertFalse(controls_scroll.verticalScrollBar().isVisible())

            apply_rect = _widget_rect_in(dlg.btn_apply_chaos, controls)
            parameter_widgets = [
                dlg.cargo_platform_input,
                dlg.cargo_provider_input,
                dlg.cargo_sale_price_input,
                dlg.cargo_desi_input,
                dlg.stock_depletion_count,
                dlg.label_stress_count,
                dlg.chaos_mode_combo,
                dlg.chaos_rate_spin,
            ]
            for widget in parameter_widgets:
                rect = _widget_rect_in(widget, controls)
                self.assertTrue(
                    controls.rect().contains(rect),
                    f"{widget.__class__.__name__} is clipped: {rect} outside {controls.rect()}",
                )
                self.assertLessEqual(
                    rect.bottom() + 8,
                    apply_rect.top(),
                    f"{widget.__class__.__name__} is too close to Chaos uygula: {rect} vs {apply_rect}",
                )

            log_rect = _widget_rect_in(dlg.diagnostics_log_card, wnd)
            controls_rect = _widget_rect_in(controls_scroll, wnd)
            self.assertLess(controls_rect.bottom(), log_rect.top())
            self.assertGreaterEqual(dlg.diagnostics_output.height(), 74)
        finally:
            test_lab_dialog.TestLabDialog.load_companies = old_load
