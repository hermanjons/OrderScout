"""Review reusable instructions and choose parameters for a fresh model task."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                            QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                            QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from AI.processors.workflow_store import (WorkflowRevision, list_workflows, read_workflow,
                                          render_workflow, render_workflow_review)


@dataclass(frozen=True)
class WorkflowRunRequest:
    workflow_id: str
    revision_id: str
    spec_hash: str
    parameters: dict[str, Any]
    objective: str


class WorkflowLibraryDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, root: str | Path | None = None,
                 allowed_scope_bindings: Mapping[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kayıtlı iş yönergeleri")
        self.resize(720, 620)
        self._root = root
        self._bindings = dict(allowed_scope_bindings or {})
        self._revision: WorkflowRevision | None = None
        self._fields: dict[str, tuple[dict[str, Any], QWidget]] = {}
        self.run_request: WorkflowRunRequest | None = None
        self.requested_mode = "run"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Bir yönerge seç. Her çalıştırmada seçili model güncel kaynaklarla yeni bir plan kurar."))
        self.workflow_list = QListWidget()
        self.workflow_list.setMaximumHeight(130)
        layout.addWidget(self.workflow_list)
        self.review = QTextBrowser()
        layout.addWidget(self.review, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        scroll.setWidget(self.form_host)
        layout.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        actions.addStretch(1)
        self.schedule_button = QPushButton("Zamanla")
        self.schedule_button.setEnabled(False)
        self.schedule_button.clicked.connect(self._accept_schedule)
        actions.addWidget(self.schedule_button)
        self.run_button = QPushButton("Yeni çalışma başlat")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._accept_run)
        actions.addWidget(self.run_button)
        layout.addLayout(actions)
        try:
            for row in list_workflows(root=root):
                item = QListWidgetItem(row["name"])
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.workflow_list.addItem(item)
        except (ValueError, KeyError, OSError) as exc:
            self.error.setText(f"Yönergeler okunamadı: {exc}")
        if not self.workflow_list.count() and not self.error.text():
            self.review.setPlainText("Henüz kayıtlı yönerge yok. Sohbette yapmak istediğin işi tarif edip yönerge olarak kaydetmesini isteyebilirsin.")
        self.workflow_list.currentItemChanged.connect(self._select_workflow)
        if self.workflow_list.count():
            self.workflow_list.setCurrentRow(0)

    def _select_workflow(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        self._revision = None
        self._fields.clear()
        self.run_request = None
        self.requested_mode = "run"
        self.run_button.setEnabled(False)
        self.schedule_button.setEnabled(False)
        self.error.clear()
        while self.form.rowCount():
            self.form.removeRow(0)
        if item is None:
            return
        try:
            row = item.data(Qt.ItemDataRole.UserRole)
            revision = read_workflow(row["workflow_id"], revision_id=row["revision_id"], root=self._root)
            if revision.spec.content_hash != row["spec_hash"]:
                raise ValueError("Yönerge seçildikten sonra değişti; yeniden açın.")
            self._revision = revision
            self.review.setPlainText(render_workflow_review(revision.spec))
            for name, definition in revision.spec.to_dict()["parameter_schema"]["properties"].items():
                kind, scope = definition["type"], definition.get("scope")
                choices = definition.get("enum")
                if scope:
                    choices = [value for value in self._bindings.get(scope, [])
                               if choices is None or value in choices]
                if kind == "boolean":
                    field: QWidget = QCheckBox()
                elif choices is not None and kind != "array":
                    field = QComboBox()
                    for value in choices:
                        field.addItem(str(value), value)
                elif kind == "array" and scope:
                    field = QListWidget()
                    field.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
                    for value in choices or []:
                        option = QListWidgetItem(str(value))
                        option.setData(Qt.ItemDataRole.UserRole, value)
                        field.addItem(option)
                else:
                    field = QLineEdit()
                    field.setPlaceholderText("Virgülle ayır" if kind == "array" else
                                             "YYYY-AA-GG" if definition.get("format") == "date" else "")
                self._fields[name] = (definition, field)
                self.form.addRow(definition.get("description") or name.replace("_", " "), field)
            self.run_button.setEnabled(True)
            self.schedule_button.setEnabled(True)
        except (ValueError, KeyError, OSError) as exc:
            self.error.setText(f"Yönerge doğrulanamadı: {exc}")

    def _accept_run(self) -> None:
        self._accept_request("run")

    def _accept_schedule(self) -> None:
        self._accept_request("schedule")

    def _accept_request(self, mode: str) -> None:
        self.run_request = None
        if self._revision is None:
            return
        parameters: dict[str, Any] = {}
        required = set(self._revision.spec.to_dict()["parameter_schema"]["required"])
        try:
            for name, (definition, field) in self._fields.items():
                if isinstance(field, QCheckBox):
                    value: Any = field.isChecked()
                elif isinstance(field, QComboBox):
                    if field.currentIndex() < 0:
                        if name not in required:
                            continue
                        raise ValueError(f"{name}: bu sohbet için yetkili bir kapsam seçilmedi.")
                    value = field.currentData()
                elif isinstance(field, QListWidget):
                    value = [option.data(Qt.ItemDataRole.UserRole) for option in field.selectedItems()]
                else:
                    text = field.text().strip()
                    if not text and name not in required:
                        continue
                    kind = definition["type"]
                    convert = int if kind == "integer" else float if kind == "number" else str
                    if kind == "array":
                        convert = int if definition["items"]["type"] == "integer" else str
                        value = [convert(part.strip()) for part in text.split(",") if part.strip()]
                    else:
                        value = convert(text)
                parameters[name] = value
            objective = render_workflow(self._revision.spec, parameters, allowed_scope_bindings=self._bindings)
            self.run_request = WorkflowRunRequest(self._revision.workflow_id, self._revision.revision_id,
                                                  self._revision.spec.content_hash, parameters, objective)
            self.requested_mode = mode
            self.accept()
        except (ValueError, KeyError, TypeError) as exc:
            self.error.setText(f"Parametreleri kontrol et: {exc}")
