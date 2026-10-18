from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from Core.constants.ui_constants import (
    APP_MESSAGE_CANCEL_TEXT,
    APP_MESSAGE_CLOSE_TEXT,
    APP_MESSAGE_DEFAULT_TITLES,
    APP_MESSAGE_DETAILS_HEIGHT,
    APP_MESSAGE_DETAILS_HIDE_TEXT,
    APP_MESSAGE_DETAILS_SHOW_TEXT,
    APP_MESSAGE_ICON_PALETTE,
    APP_MESSAGE_ICON_PIXMAP_SIZE,
    APP_MESSAGE_ICON_SIZE,
    APP_MESSAGE_MIN_WIDTH,
    APP_MESSAGE_NO_TEXT,
    APP_MESSAGE_OK_TEXT,
    APP_MESSAGE_STYLE,
    APP_MESSAGE_YES_TEXT,
)


class AppMessageResult(str, Enum):
    OK = "ok"
    YES = "yes"
    NO = "no"
    CANCEL = "cancel"
    CLOSED = "closed"


@dataclass(frozen=True)
class _DialogButtonSpec:
    result: AppMessageResult
    text: str
    primary: bool = False
    is_default: bool = False


class _IconBubble(QWidget):
    def __init__(self, *, level: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = str(level or "info").strip().lower()
        self.setFixedSize(APP_MESSAGE_ICON_SIZE, APP_MESSAGE_ICON_SIZE)

    def paintEvent(self, _event) -> None:  # noqa: N802
        background, foreground = APP_MESSAGE_ICON_PALETTE.get(
            self._level,
            APP_MESSAGE_ICON_PALETTE["info"],
        )
        icon = {
            "info": QStyle.StandardPixmap.SP_MessageBoxInformation,
            "success": QStyle.StandardPixmap.SP_DialogApplyButton,
            "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
            "error": QStyle.StandardPixmap.SP_MessageBoxCritical,
            "question": QStyle.StandardPixmap.SP_MessageBoxQuestion,
        }.get(self._level, QStyle.StandardPixmap.SP_MessageBoxInformation)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawEllipse(self.rect())

        pixmap = self.style().standardIcon(icon).pixmap(APP_MESSAGE_ICON_PIXMAP_SIZE, APP_MESSAGE_ICON_PIXMAP_SIZE)
        target = self.rect().adjusted(18, 18, -18, -18)
        painter.drawPixmap(target, pixmap)

        painter.setPen(QPen(QColor(foreground), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(self.rect().adjusted(0, 0, -1, -1))


class AppMessageDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        level: str,
        title: str,
        text: str,
        details: str | None = None,
        buttons: list[_DialogButtonSpec],
        default_result: AppMessageResult | None = None,
        escape_result: AppMessageResult | None = None,
    ) -> None:
        super().__init__(parent)
        self._result = AppMessageResult.CLOSED
        self._default_result = default_result
        self._escape_result = escape_result or (buttons[1].result if len(buttons) > 1 else buttons[0].result)
        self._buttons: dict[AppMessageResult, QPushButton] = {}
        self._details_visible = False

        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.Dialog, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("AppMessageDialog")
        self.setMinimumWidth(APP_MESSAGE_MIN_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("Card")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(15, 23, 42, 52))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        body = QWidget(card)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(34, 30, 34, 26)
        body_layout.setSpacing(20)

        icon = _IconBubble(level=level, parent=body)
        body_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        content = QWidget(body)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        title_label = QLabel(str(title or "").strip(), content)
        title_label.setObjectName("Title")
        title_label.setWordWrap(True)
        content_layout.addWidget(title_label)

        text_label = QLabel(str(text or "").strip(), content)
        text_label.setObjectName("Text")
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(text_label)

        self._details_toggle = QToolButton(content)
        self._details_toggle.setObjectName("DetailsToggle")
        self._details_toggle.setText(APP_MESSAGE_DETAILS_SHOW_TEXT)
        self._details_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._details_toggle.clicked.connect(self._toggle_details)
        self._details_toggle.setVisible(bool(str(details or "").strip()))
        content_layout.addWidget(self._details_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self._details_edit = QPlainTextEdit(content)
        self._details_edit.setObjectName("Details")
        self._details_edit.setReadOnly(True)
        self._details_edit.setPlainText(str(details or "").strip())
        self._details_edit.setVisible(False)
        self._details_edit.setFixedHeight(APP_MESSAGE_DETAILS_HEIGHT)
        content_layout.addWidget(self._details_edit)

        content_layout.addStretch(1)
        body_layout.addWidget(content, 1)
        card_layout.addWidget(body)

        footer = QFrame(card)
        footer.setObjectName("Footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 16, 24, 16)
        footer_layout.setSpacing(12)
        footer_layout.addStretch(1)

        for spec in buttons:
            button = QPushButton(spec.text, footer)
            button.setObjectName("PrimaryButton" if spec.primary else "SecondaryButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(bool(spec.is_default or spec.primary))
            button.setDefault(bool(spec.is_default or spec.primary))
            button.clicked.connect(lambda _checked=False, value=spec.result: self._finish(value))
            button.setMinimumHeight(46)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            footer_layout.addWidget(button)
            self._buttons[spec.result] = button

        card_layout.addWidget(footer)
        self.setStyleSheet(APP_MESSAGE_STYLE)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._recenter()
        focus_target = None
        if self._default_result is not None:
            focus_target = self._buttons.get(self._default_result)
        if focus_target is None and self._buttons:
            focus_target = next(iter(self._buttons.values()))
        if focus_target is not None:
            focus_target.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._default_result is not None:
                self._finish(self._default_result)
                return
        if event.key() == Qt.Key.Key_Escape:
            self._finish(self._escape_result)
            return
        super().keyPressEvent(event)

    def reject(self) -> None:
        self._finish(self._escape_result)

    def result_value(self) -> AppMessageResult:
        return self._result

    def _toggle_details(self) -> None:
        self._details_visible = not self._details_visible
        self._details_edit.setVisible(self._details_visible)
        self._details_toggle.setText(
            APP_MESSAGE_DETAILS_HIDE_TEXT if self._details_visible else APP_MESSAGE_DETAILS_SHOW_TEXT
        )
        self.adjustSize()
        self._recenter()

    def _finish(self, value: AppMessageResult) -> None:
        self._result = value
        self.done(0)

    def _recenter(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            center = parent.frameGeometry().center()
        else:
            active = QApplication.activeWindow()
            if active is not None and active is not self:
                center = active.frameGeometry().center()
            else:
                screen = QApplication.primaryScreen()
                if screen is None:
                    return
                center = screen.availableGeometry().center()
        geometry = self.frameGeometry()
        geometry.moveCenter(center)
        self.move(geometry.topLeft())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        super().paintEvent(event)


class AppMessageCenter:
    _DEFAULT_TITLES = APP_MESSAGE_DEFAULT_TITLES

    @staticmethod
    def _resolve_parent(parent: object | None) -> QWidget | None:
        return parent if isinstance(parent, QWidget) else None

    @staticmethod
    def _localize_button_text(button: QMessageBox.StandardButton) -> str:
        labels = {
            QMessageBox.StandardButton.Ok: APP_MESSAGE_OK_TEXT,
            QMessageBox.StandardButton.Yes: APP_MESSAGE_YES_TEXT,
            QMessageBox.StandardButton.No: APP_MESSAGE_NO_TEXT,
            QMessageBox.StandardButton.Cancel: APP_MESSAGE_CANCEL_TEXT,
            QMessageBox.StandardButton.Close: APP_MESSAGE_CLOSE_TEXT,
        }
        return labels.get(button, APP_MESSAGE_OK_TEXT)

    @classmethod
    def _button_specs(
        cls,
        buttons: QMessageBox.StandardButton,
        *,
        default_button: QMessageBox.StandardButton | None,
    ) -> list[_DialogButtonSpec]:
        order = [
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Close,
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Yes,
        ]
        specs: list[_DialogButtonSpec] = []
        for button in order:
            if not bool(buttons & button):
                continue
            result = {
                QMessageBox.StandardButton.Ok: AppMessageResult.OK,
                QMessageBox.StandardButton.Yes: AppMessageResult.YES,
                QMessageBox.StandardButton.No: AppMessageResult.NO,
                QMessageBox.StandardButton.Cancel: AppMessageResult.CANCEL,
                QMessageBox.StandardButton.Close: AppMessageResult.CANCEL,
            }.get(button, AppMessageResult.OK)
            specs.append(
                _DialogButtonSpec(
                    result=result,
                    text=cls._localize_button_text(button),
                    primary=button in {QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Yes},
                    is_default=button == default_button,
                )
            )
        if not specs:
            specs.append(
                _DialogButtonSpec(
                    result=AppMessageResult.OK,
                    text=APP_MESSAGE_OK_TEXT,
                    primary=True,
                    is_default=True,
                )
            )
        return specs

    @staticmethod
    def _result_to_button(result: AppMessageResult) -> QMessageBox.StandardButton:
        return {
            AppMessageResult.OK: QMessageBox.StandardButton.Ok,
            AppMessageResult.YES: QMessageBox.StandardButton.Yes,
            AppMessageResult.NO: QMessageBox.StandardButton.No,
            AppMessageResult.CANCEL: QMessageBox.StandardButton.Cancel,
            AppMessageResult.CLOSED: QMessageBox.StandardButton.Cancel,
        }.get(result, QMessageBox.StandardButton.Cancel)

    @classmethod
    def show(
        cls,
        parent: object | None,
        *,
        level: str = "info",
        title: str = "",
        text: str = "",
        details: str | None = None,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        default_button: QMessageBox.StandardButton | None = None,
    ) -> QMessageBox.StandardButton:
        resolved_level = str(level or "info").strip().lower()
        if resolved_level not in cls._DEFAULT_TITLES:
            resolved_level = "info"

        resolved_buttons = cls._button_specs(buttons, default_button=default_button)
        resolved_default = None
        if default_button is not None:
            resolved_default = {
                QMessageBox.StandardButton.Ok: AppMessageResult.OK,
                QMessageBox.StandardButton.Yes: AppMessageResult.YES,
                QMessageBox.StandardButton.No: AppMessageResult.NO,
                QMessageBox.StandardButton.Cancel: AppMessageResult.CANCEL,
                QMessageBox.StandardButton.Close: AppMessageResult.CANCEL,
            }.get(default_button)
        escape_result = AppMessageResult.CANCEL
        if resolved_default is None and resolved_buttons:
            resolved_default = next((spec.result for spec in resolved_buttons if spec.is_default), resolved_buttons[-1].result)
        if len(resolved_buttons) >= 2:
            escape_result = resolved_buttons[0].result
        elif resolved_buttons:
            escape_result = resolved_buttons[0].result

        dialog = AppMessageDialog(
            cls._resolve_parent(parent),
            level=resolved_level,
            title=str(title or cls._DEFAULT_TITLES[resolved_level]),
            text=str(text or ""),
            details=str(details or "").strip() or None,
            buttons=resolved_buttons,
            default_result=resolved_default,
            escape_result=escape_result,
        )
        dialog.exec()
        return cls._result_to_button(dialog.result_value())

    @classmethod
    def info(cls, parent: object | None, title: str, text: str) -> QMessageBox.StandardButton:
        return cls.show(parent, level="info", title=title, text=text, default_button=QMessageBox.StandardButton.Ok)

    @classmethod
    def success(cls, parent: object | None, title: str, text: str) -> QMessageBox.StandardButton:
        return cls.show(parent, level="success", title=title, text=text, default_button=QMessageBox.StandardButton.Ok)

    @classmethod
    def warning(cls, parent: object | None, title: str, text: str) -> QMessageBox.StandardButton:
        return cls.show(parent, level="warning", title=title, text=text, default_button=QMessageBox.StandardButton.Ok)

    @classmethod
    def error(
        cls,
        parent: object | None,
        title: str,
        text: str,
        *,
        details: str | None = None,
    ) -> QMessageBox.StandardButton:
        return cls.show(
            parent,
            level="error",
            title=title,
            text=text,
            details=details,
            default_button=QMessageBox.StandardButton.Ok,
        )

    @classmethod
    def question(
        cls,
        parent: object | None,
        title: str,
        text: str,
        *,
        default_yes: bool = False,
    ) -> QMessageBox.StandardButton:
        default_button = QMessageBox.StandardButton.Yes if default_yes else QMessageBox.StandardButton.No
        return cls.show(
            parent,
            level="question",
            title=title,
            text=text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=default_button,
        )

    @classmethod
    def confirm(
        cls,
        parent: object | None,
        title: str,
        text: str,
        *,
        default_yes: bool = False,
    ) -> bool:
        result = cls.question(parent, title, text, default_yes=default_yes)
        return result == QMessageBox.StandardButton.Yes
