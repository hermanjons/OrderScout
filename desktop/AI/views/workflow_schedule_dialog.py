"""Review and confirm local workflow schedules with exact saved parameters."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any

from PyQt6.QtCore import QDateTime, QTime, Qt
from PyQt6.QtWidgets import (QComboBox, QDateTimeEdit, QDialog, QFormLayout, QHBoxLayout, QLabel,
                            QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QVBoxLayout)

from AI.processors.workflow_scheduler import WorkflowScheduler
from AI.processors.workflow_store import render_workflow_review


class WorkflowScheduleDialog(QDialog):
    def __init__(self, parent=None, *, scheduler: WorkflowScheduler, request: Any = None,
                 allowed_scope_bindings: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Planlı çalışmalar")
        self.resize(690, 610)
        self.scheduler, self.request = scheduler, request
        self.bindings = deepcopy(dict(allowed_scope_bindings or {}))
        self.proposal: dict[str, Any] | None = None
        self._reviewed_proposal_json: str | None = None
        self._reviewed_request_json: str | None = None
        self.saved = False
        layout = QVBoxLayout(self)
        note = QLabel("Uygulama açıkken seçili modelle çalışır. Her çalıştırma güncel verileri okur; gerçek işlemler ayrıca onayını bekler.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.list = QListWidget()
        self.list.setMaximumHeight(125)
        layout.addWidget(self.list)
        self.review = QTextBrowser()
        layout.addWidget(self.review, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        if request is not None:
            form = QFormLayout()
            self.interval = QComboBox()
            for label, seconds in (("Her saat", 3600), ("Her gün", 86400), ("Her hafta", 604800)):
                self.interval.addItem(label, seconds)
            self.interval.setCurrentIndex(1)
            self.first_due = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
            initial = self.first_due.dateTime()
            self.first_due.setTime(QTime(initial.time().hour(), initial.time().minute(), 0))
            self.first_due.setCalendarPopup(True)
            self.first_due.setDisplayFormat("dd.MM.yyyy HH:mm")
            form.addRow("Tekrar", self.interval)
            form.addRow("İlk çalışma (yerel saat)", self.first_due)
            layout.addLayout(form)
            self.prepare_button = QPushButton("Planı gözden geçir")
            self.prepare_button.clicked.connect(self._prepare)
            layout.addWidget(self.prepare_button)
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        actions.addStretch(1)
        self.confirm = QPushButton("Onayla ve planı kaydet")
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self._confirm)
        actions.addWidget(self.confirm)
        layout.addLayout(actions)
        self.list.currentItemChanged.connect(self._select)
        if request is not None:
            self.interval.currentIndexChanged.connect(self._invalidate_review)
            self.first_due.dateTimeChanged.connect(self._invalidate_review)
        self._refresh()

    @staticmethod
    def _exact_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _request_json(self) -> str | None:
        if self.request is None:
            return None
        return self._exact_json({"workflow_id": self.request.workflow_id, "revision_id": self.request.revision_id,
                                 "spec_hash": self.request.spec_hash, "parameters": self.request.parameters})

    def _invalidate_review(self, *_args) -> None:
        had_review = self._reviewed_proposal_json is not None
        self.proposal = None
        self._reviewed_proposal_json = None
        self._reviewed_request_json = None
        self.confirm.setEnabled(False)
        if had_review:
            self.error.setText("Plan değişti. Kaydetmeden önce yeniden gözden geçir.")

    def _retain_review(self, proposal: dict[str, Any], *, request_json: str | None = None) -> None:
        self._reviewed_proposal_json = self._exact_json(proposal)
        self._reviewed_request_json = request_json
        self.proposal = json.loads(self._reviewed_proposal_json)

    def _refresh(self) -> None:
        self.list.clear()
        try:
            for row in self.scheduler.list_schedules():
                configuration = row["schedule"]
                item = QListWidgetItem(f'{configuration["pinned_spec"]["name"]} · {"aktif" if row["status"] == "active" else "iptal edildi"}')
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.list.addItem(item)
            if not self.list.count() and self.request is None:
                self.review.setPlainText("Henüz planlı çalışma yok. Yönergelerden bir iş seçip Zamanla düğmesini kullanabilirsin.")
        except (ValueError, OSError) as exc:
            self.error.setText(f"Planlar okunamadı: {exc}")

    def _prepare(self) -> None:
        self._invalidate_review()
        try:
            due = self.first_due.dateTime()
            if not due.isValid():
                raise ValueError("Geçerli bir ilk çalışma zamanı seç.")
            # Qt's LocalTime toPyDateTime is naïve. Its epoch preserves the
            # selected local timezone/offset and daylight-saving conversion.
            due_utc = datetime.fromtimestamp(due.toMSecsSinceEpoch() / 1000, tz=timezone.utc)
            request_json = self._request_json()
            request = json.loads(request_json)
            proposal = self.scheduler.prepare_schedule_save(
                request["workflow_id"], revision_id=request["revision_id"], parameters=request["parameters"],
                interval_seconds=self.interval.currentData(), first_due_at=due_utc,
                allowed_scope_bindings=self.bindings, budget={"max_steps": 24, "max_replans": 4},
            )
            configuration = proposal["schedule"]
            if configuration["spec_hash"] != request["spec_hash"]:
                raise ValueError("Seçilen yönerge değişti; yeniden seç.")
            self.review.setPlainText(render_workflow_review(configuration["pinned_spec"]) +
                                     f'\n\nParametreler: {configuration["parameters"]}\nİlk çalışma (yerel saat): {due.toString("dd.MM.yyyy HH:mm t")}\nİlk çalışma (UTC): {configuration["first_due_at"]}\nTekrar: {self.interval.currentText()}')
            self._retain_review(proposal, request_json=request_json)
            self.confirm.setText("Onayla ve planı kaydet")
            self.confirm.setEnabled(True)
            self.error.clear()
        except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
            self._invalidate_review()
            self.error.setText(f"Plan hazırlanamadı: {exc}")

    def _select(self, item, _previous=None) -> None:
        self._invalidate_review()
        self.error.clear()
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        configuration = row["schedule"]
        self.review.setPlainText(render_workflow_review(configuration["pinned_spec"]) +
                                 f'\n\nParametreler: {configuration["parameters"]}\nSonraki çalışma (UTC): {row["next_due_at"]}\nDurum: {row["status"]}')
        if row["status"] == "active":
            self._retain_review(self.scheduler.prepare_schedule_cancel(row["schedule_id"], expected_schedule_hash=row["schedule_hash"]))
            self.confirm.setText("Onayla ve planı iptal et")
            self.confirm.setEnabled(True)

    def _confirm(self) -> None:
        if self.proposal is None or self._reviewed_proposal_json is None:
            return
        try:
            if self._exact_json(self.proposal) != self._reviewed_proposal_json:
                raise ValueError("Gözden geçirilen teklif değişti; yeniden gözden geçir.")
            if self._reviewed_request_json is not None and self._request_json() != self._reviewed_request_json:
                raise ValueError("Yönerge parametreleri değişti; yeniden gözden geçir.")
            proposal = json.loads(self._reviewed_proposal_json)
            method = self.scheduler.cancel_prepared_schedule if proposal["action_type"] == "workflow.schedule.cancel" else self.scheduler.save_prepared_schedule
            result = method(proposal, confirmed_action_hash=proposal["action_hash"], approved_by="user_schedule_dialog")
            if not result.success:
                raise ValueError(result.message)
            self.saved = True
            self.accept()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self._invalidate_review()
            self.error.setText(f"Plan kaydedilemedi: {exc}")
