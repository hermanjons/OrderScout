"""A model-aware reasoning selector with a progressively detailed brain drawing."""
from __future__ import annotations

from PyQt6.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation, QSignalBlocker
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QSlider, QToolButton, QVBoxLayout, QWidget,
)


EFFORT_LABELS = {
    "auto": "Otomatik", "off": "Kapalı", "none": "Kapalı", "minimal": "En az",
    "low": "Düşük", "medium": "Orta", "high": "Yüksek", "xhigh": "Çok yüksek", "max": "En yüksek",
}
EFFORT_ORDER = ("off", "none", "minimal", "low", "medium", "high", "xhigh", "max")
DETAIL = {"off": 0.0, "none": 0.0, "minimal": .10, "low": .23,
          "medium": .46, "high": .70, "xhigh": .85, "max": 1.0, "auto": .46}
ACCENT = QColor("#2563EB")


def effort_label(effort):
    return EFFORT_LABELS.get(effort, str(effort))


def _path(start, *curves):
    path = QPainterPath()
    path.moveTo(*start)
    for curve in curves:
        path.cubicTo(*curve)
    return path


# Coordinates describe one hemisphere. Mirroring preserves the central fissure.
OUTLINE = _path((48, 18), (43, 8, 30, 8, 25, 18), (16, 15, 8, 25, 12, 35),
    (4, 40, 5, 54, 13, 60), (8, 71, 18, 83, 29, 81),
    (33, 91, 45, 90, 48, 81), (50, 65, 47, 36, 48, 18))
OUTLINE.closeSubpath()
FOLDS = (
    (.00, _path((25, 18), (33, 18, 37, 23, 34, 31), (31, 37, 22, 31, 18, 38))),
    (.00, _path((13, 60), (20, 60, 20, 51, 27, 50), (36, 49, 41, 57, 38, 64))),
    (.00, _path((29, 81), (26, 75, 30, 68, 35, 70), (41, 73, 44, 70, 47, 66))),
    (.16, _path((12, 35), (17, 28, 26, 34, 26, 41), (27, 46, 34, 47, 38, 43))),
    (.28, _path((37, 14), (39, 19, 43, 20, 47, 21))),
    (.28, _path((16, 72), (18, 66, 23, 70, 26, 66), (29, 62, 25, 57, 29, 54))),
    (.38, _path((17, 45), (11, 45, 12, 52, 16, 52), (22, 52, 24, 47, 23, 44))),
    (.43, _path((35, 31), (40, 26, 45, 30, 42, 36), (39, 40, 43, 42, 47, 41))),
    (.52, _path((38, 64), (33, 64, 31, 60, 35, 57), (38, 54, 44, 57, 47, 54))),
    (.60, _path((22, 24), (22, 19, 17, 22, 17, 26))),
    (.65, _path((30, 37), (33, 40, 31, 44, 29, 45))),
    (.72, _path((36, 80), (37, 83, 42, 82, 42, 77))),
    (.78, _path((8, 48), (10, 43, 13, 41, 17, 42))),
    (.83, _path((40, 48), (43, 46, 45, 48, 47, 47))),
    (.90, _path((20, 78), (20, 73, 24, 75, 25, 71))),
)
MIRROR = QTransform(-1, 0, 0, 1, 100, 0)


def paint_brain(painter, rect, detail, *, enabled=True, compact=False):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    painter.translate(rect.center().x()-side/2, rect.center().y()-side/2)
    painter.scale(side/100, side/100)
    outline = QColor("#245681" if enabled else "#94A3B8")
    painter.setPen(QPen(outline, 3.6 if compact else 1.6, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    fill = QColor("#EFF5FF" if enabled else "#F1F5F9")
    painter.setBrush(fill)
    painter.drawPath(OUTLINE)
    painter.drawPath(MIRROR.map(OUTLINE))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for threshold, fold in FOLDS:
        visibility = max(0.0, min(1.0, (detail-threshold)*6)) if threshold else .85
        if not visibility:
            continue
        color = QColor(outline if compact else ACCENT if enabled else outline)
        color.setAlphaF(visibility*(.86 if compact else .58))
        painter.setPen(QPen(color, 2.7 if compact else 1.25, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(fold)
        painter.drawPath(MIRROR.map(fold))
    if not compact and detail > .55:
        color = QColor(ACCENT if enabled else outline)
        color.setAlphaF(min(.8, (detail-.55)*1.8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x, y in ((34, 31), (27, 50), (38, 64), (25, 71), (42, 36), (40, 48)):
            painter.drawEllipse(QRectF(x-1.35, y-1.35, 2.7, 2.7))
            painter.drawEllipse(QRectF(100-x-1.35, y-1.35, 2.7, 2.7))
    painter.restore()


class BrainCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.detail = .46
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(190)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate)
        self.setMinimumSize(162, 158)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Seçili akıl yürütme düzeyinin beyin görseli")

    def _animate(self, value):
        self.detail = float(value)
        self.update()

    def set_detail(self, detail, *, animate=True):
        target = float(detail)
        if animate and self.isVisible():
            if abs(self.detail-target) < .0001:
                return
            if self._animation.state() == QAbstractAnimation.State.Running and self._animation.endValue() == target:
                return
        self._animation.stop()
        if animate and self.isVisible():
            self._animation.setStartValue(self.detail)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._animate(target)

    def paintEvent(self, event):
        painter = QPainter(self)
        paint_brain(painter, QRectF(self.rect()).adjusted(3, 0, -3, 0), self.detail,
                    enabled=self.isEnabled())


class _EffortSlider(QSlider):
    """Discrete model levels, with a visible stop and a short pulse at each step."""
    def __init__(self, parent=None, *, minimum_height=142, orientation=Qt.Orientation.Vertical):
        super().__init__(orientation, parent)
        self.setInvertedAppearance(False)
        self.setSingleStep(1)
        self.setPageStep(1)
        self._pulse_strength = 0.0
        self._pulse_animation = QVariantAnimation(self)
        self._pulse_animation.setDuration(150)
        self._pulse_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pulse_animation.valueChanged.connect(self._animate_pulse)
        self.valueChanged.connect(self._pulse)
        self.sliderPressed.connect(self._pulse)
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(20)
            self.setMinimumWidth(86)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAccessibleName("Akıl yürütme düzeyi; sağa artır, sola azalt")
        else:
            self.setFixedWidth(36)
            self.setMinimumHeight(minimum_height)
            self.setAccessibleName("Akıl yürütme düzeyi; yukarı artır, aşağı azalt")
        self.setStyleSheet("""
            QSlider::groove:vertical { background:#E7EDF5; width:4px; border-radius:2px; }
            QSlider::add-page:vertical { background:#2563EB; width:4px; border-radius:2px; }
            QSlider::sub-page:vertical { background:#E7EDF5; width:4px; border-radius:2px; }
            QSlider::handle:vertical { background:#2563EB; border:3px solid white;
                height:14px; width:14px; margin:0 -8px; border-radius:10px; }
            QSlider::handle:vertical:hover { background:#1D4ED8; border-color:#DBEAFE; }
            QSlider::handle:vertical:pressed { border-color:#BFDBFE; }
            QSlider::handle:vertical:focus { border-color:#BFDBFE; }
        """)

    def _animate_pulse(self, value):
        self._pulse_strength = float(value)
        self.update()

    def _pulse(self, *_args):
        if self.orientation() != Qt.Orientation.Horizontal or not self.isVisible():
            return
        self._pulse_animation.stop()
        self._pulse_animation.setStartValue(1.0)
        self._pulse_animation.setEndValue(0.0)
        self._pulse_animation.start()

    def _pick(self, event):
        if self.orientation() == Qt.Orientation.Horizontal:
            span = max(1, self.width()-20)
            position = (event.position().x()-10)/span
        else:
            span = max(1, self.height()-20)
            position = 1-(event.position().y()-10)/span
        ratio = max(0.0, min(1.0, position))
        self.setValue(self.minimum()+int(ratio*(self.maximum()-self.minimum())+.5))

    def paintEvent(self, event):
        if self.orientation() != Qt.Orientation.Horizontal:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, middle = 10.0, self.width()-10.0, self.height()/2
        count = self.maximum()-self.minimum()
        position = left+(right-left)*(self.value()-self.minimum())/count if count else left
        accent = QColor(ACCENT if self.isEnabled() else "#A5B2C3")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#DCE5F0"))
        painter.drawRoundedRect(QRectF(left, middle-1.5, right-left, 3), 1.5, 1.5)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(left, middle-1.5, position-left, 3), 1.5, 1.5)
        for step in range(count+1):
            x = left+(right-left)*step/count if count else left
            completed = step <= self.value()-self.minimum()
            painter.setPen(QPen(accent if completed else QColor("#B3C4D8"), 1.2))
            painter.setBrush(accent if completed else QColor("#F6F8FC"))
            painter.drawEllipse(QRectF(x-2.5, middle-2.5, 5, 5))
        # The handle snaps to the same coordinates as the painted level stops.
        halo = QColor(accent)
        halo.setAlphaF(.10+.14*self._pulse_strength if self.hasFocus() or self.isSliderDown() else .12*self._pulse_strength)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        radius = 7+2*self._pulse_strength
        painter.drawEllipse(QRectF(position-radius, middle-radius, 2*radius, 2*radius))
        painter.setBrush(accent)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.8))
        painter.drawEllipse(QRectF(position-5, middle-5, 10, 10))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick(event)
            # Even a click on the current handle switches Auto to manual.
            self.setSliderDown(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._pick(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick(event)
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class _ReasoningPopover(QFrame):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self.setObjectName("AiReasoningPopover")
        self.setAccessibleName("Akıl yürütme ayarı")
        self.setFixedWidth(324)
        self.setStyleSheet("""
            QFrame#AiReasoningPopover { background:white; border:1px solid #DCE5F0; border-radius:14px; }
            QLabel { background:transparent; border:0; color:#132438; }
            QLabel#ReasoningTitle { font-size:14px; font-weight:600; }
            QLabel#ReasoningModel { color:#75869B; font-size:11px; }
            QLabel#ReasoningValue { font-size:17px; font-weight:600; }
            QLabel#ReasoningHint { color:#75869B; font-size:11px; }
            QLabel#ReasoningExtent { color:#8A9AAF; font-size:10px; }
            QToolButton#ReasoningClose { border:0; background:transparent; color:#75869B; border-radius:6px; }
            QToolButton#ReasoningClose:hover { background:#F1F5F9; }
            QPushButton#ReasoningAuto { border:1px solid #E2E8F0; border-radius:8px;
                padding:7px 10px; color:#51647C; background:white; text-align:left; font-size:11px; }
            QPushButton#ReasoningAuto:hover { background:#F7FAFE; }
            QPushButton#ReasoningAuto:checked { background:#EFF5FF; color:#2563EB; border-color:#C9DAFA; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Akıl yürütme", objectName="ReasoningTitle"))
        heading.addStretch()
        close = QToolButton(objectName="ReasoningClose")
        close.setText("×")
        close.setFixedSize(26, 26)
        close.setAccessibleName("Akıl yürütme ayarını kapat")
        close.clicked.connect(owner.hidePopup)
        heading.addWidget(close)
        layout.addLayout(heading)
        self.model_label = QLabel(objectName="ReasoningModel")
        layout.addWidget(self.model_label)
        visual = QHBoxLayout()
        visual.setContentsMargins(6, 5, 6, 0)
        visual.setSpacing(18)
        self.brain = BrainCanvas(self)
        visual.addWidget(self.brain, 1)
        track = QVBoxLayout()
        track.setSpacing(2)
        track.addWidget(QLabel("Daha fazla", objectName="ReasoningExtent"), 0, Qt.AlignmentFlag.AlignHCenter)
        self.slider = _EffortSlider(self)
        track.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        track.addWidget(QLabel("Daha az", objectName="ReasoningExtent"), 0, Qt.AlignmentFlag.AlignHCenter)
        visual.addLayout(track)
        layout.addLayout(visual)
        self.value_label = QLabel(objectName="ReasoningValue")
        layout.addWidget(self.value_label)
        self.hint = QLabel(objectName="ReasoningHint")
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(34)
        layout.addWidget(self.hint)
        self.auto_button = QPushButton("Otomatik · modelin varsayılanı", objectName="ReasoningAuto")
        self.auto_button.setCheckable(True)
        self.auto_button.clicked.connect(lambda: owner.setCurrentIndex(owner.findData("auto")))
        layout.addWidget(self.auto_button)
        self.slider.valueChanged.connect(self._select_level)
        self.slider.sliderPressed.connect(lambda: self._select_level(self.slider.value()))

    def _select_level(self, value):
        levels = self.owner.manual_efforts()
        if levels and self.owner.isEnabled():
            self.owner.setCurrentIndex(self.owner.findData(levels[value]))

    def sync(self, *, animate=True):
        owner = self.owner
        efforts = owner.manual_efforts()
        effort = owner.currentData() or "auto"
        effective = owner.default_effort if effort == "auto" else effort
        if effective not in efforts:
            effective = "medium" if "medium" in efforts else efforts[-1] if efforts else "auto"
        with QSignalBlocker(self.slider):
            self.slider.setRange(0, max(0, len(efforts)-1))
            self.slider.setValue(efforts.index(effective) if effective in efforts else 0)
        self.slider.setEnabled(bool(efforts) and owner.isEnabled())
        self.slider.setAccessibleDescription(effort_label(effort))
        self.value_label.setText(effort_label(effort))
        self.model_label.setText(self.model_label.fontMetrics().elidedText(
            owner.model_name or "Seçili model", Qt.TextElideMode.ElideRight, 260))
        if effort == "auto":
            text = f"Modelin varsayılanı: {effort_label(owner.default_effort)}." if owner.default_effort else "Model kendi varsayılanını kullanır."
        elif effort in {"off", "none"}:
            text = "Ayarlanabilir akıl yürütme kapalı."
        elif effort in {"minimal", "low"}:
            text = "Daha kısa akıl yürütme için."
        elif effort == "medium":
            text = "Dengeli akıl yürütme için."
        else:
            text = "Daha kapsamlı akıl yürütme; yanıt süresi uzayabilir."
        self.hint.setText(text)
        self.auto_button.setVisible(owner.findData("auto") >= 0)
        self.auto_button.setChecked(effort == "auto")
        self.brain.set_detail(DETAIL.get(effective, .46), animate=animate)

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.owner.hidePopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.brain._animation.stop()
        self.owner.update()
        super().hideEvent(event)

    def showEvent(self, event):
        QApplication.instance().installEventFilter(self)
        super().showEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            owner_click = watched is self.owner or (isinstance(watched, QWidget) and self.owner.isAncestorOf(watched))
            if not owner_click and not self.geometry().contains(event.globalPosition().toPoint()):
                self.owner.hidePopup()
        return False


class ReasoningControl(QComboBox):
    """The brain and level slider stay directly inside the message composer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.default_effort = ""
        self.model_name = ""
        self._popover = None
        self.setFixedHeight(74)
        self.setMinimumWidth(218)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setAccessibleName("Akıl yürütme düzeyi")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 1, 8, 1)
        layout.setSpacing(10)
        visual = QVBoxLayout()
        visual.setContentsMargins(0, 0, 0, 0)
        visual.setSpacing(0)
        self.inline_brain = BrainCanvas(self)
        self.inline_brain.setMinimumSize(66, 52)
        self.inline_brain.setFixedSize(66, 52)
        visual.addWidget(self.inline_brain, 0, Qt.AlignmentFlag.AlignHCenter)
        self.inline_slider = _EffortSlider(self, orientation=Qt.Orientation.Horizontal)
        self.inline_slider.setFixedWidth(86)
        self.inline_slider.setToolTip("Kademeye tıkla veya sağa sürükle: daha fazla akıl yürütme")
        self.inline_slider.valueChanged.connect(self._select_inline_level)
        self.inline_slider.sliderPressed.connect(lambda: self._select_inline_level(self.inline_slider.value()))
        visual.addWidget(self.inline_slider, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(visual)
        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(1)
        self.inline_title = QLabel("Akıl yürütme", self)
        self.inline_title.setStyleSheet("QLabel { color:#75869B; font-size:10px; background:transparent; border:0; }"
                                       "QLabel:disabled { color:#94A3B8; }")
        labels.addWidget(self.inline_title)
        self.inline_value = QLabel("Otomatik", self)
        self.inline_value.setStyleSheet("QLabel { color:#29445F; font-size:12px; font-weight:600; background:transparent; border:0; }"
                                       "QLabel:disabled { color:#94A3B8; }")
        labels.addWidget(self.inline_value)
        self.inline_auto = QToolButton(self)
        self.inline_auto.setText("Otomatik")
        self.inline_auto.setCheckable(True)
        self.inline_auto.setAccessibleName("Modelin otomatik akıl yürütme ayarını kullan")
        self.inline_auto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inline_auto.setFixedHeight(18)
        self.inline_auto.setStyleSheet("""
            QToolButton { background:transparent; color:#75869B; border:0; border-radius:4px;
                padding:0 4px; font-size:10px; text-align:left; }
            QToolButton:hover { color:#2563EB; background:#E4EDFD; }
            QToolButton:checked { color:#2563EB; background:#E4EDFD; }
            QToolButton:disabled { color:#94A3B8; background:transparent; }
        """)
        self.inline_auto.clicked.connect(lambda: self.setCurrentIndex(self.findData("auto")))
        labels.addWidget(self.inline_auto, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(labels, 1)
        self.currentIndexChanged.connect(self._sync_visual)

    def effective_effort(self):
        efforts = self.manual_efforts()
        effort = self.currentData() or "auto"
        effective = self.default_effort if effort == "auto" else effort
        if effective not in efforts:
            effective = "medium" if "medium" in efforts else efforts[-1] if efforts else "auto"
        return effective

    def _select_inline_level(self, value):
        efforts = self.manual_efforts()
        if efforts and self.isEnabled():
            self.setCurrentIndex(self.findData(efforts[value]))

    def manual_efforts(self):
        available = {self.itemData(index) for index in range(self.count())}
        return [effort for effort in EFFORT_ORDER if effort in available]

    def configure_efforts(self, efforts, *, selected="auto", default_effort="", model_name=""):
        valid = set(efforts) & set(EFFORT_LABELS)
        if "off" in valid and "none" in valid:
            # These provider aliases describe the same disabled reasoning stop.
            valid.remove("none")
            selected = "off" if selected == "none" else selected
            default_effort = "off" if default_effort == "none" else default_effort
        ordered = (["auto"] if "auto" in valid else []) + [value for value in EFFORT_ORDER if value in valid]
        ordered = ordered or ["auto"]
        changed = ordered != [self.itemData(index) for index in range(self.count())]
        if changed or model_name != self.model_name:
            self.hidePopup()
        self.default_effort = default_effort if default_effort in valid and default_effort != "auto" else ""
        self.model_name = model_name
        with QSignalBlocker(self):
            if changed:
                self.clear()
                for effort in ordered:
                    self.addItem(effort_label(effort), effort)
            self.setCurrentIndex(max(0, self.findData(selected)))
        self._sync_visual()

    def setCurrentIndex(self, index):
        super().setCurrentIndex(index)
        self._sync_visual()

    def _sync_visual(self, *_args):
        if self._popover is not None:
            self._popover.sync()
        efforts = self.manual_efforts()
        effective = self.effective_effort()
        with QSignalBlocker(self.inline_slider):
            self.inline_slider.setRange(0, max(0, len(efforts)-1))
            self.inline_slider.setValue(efforts.index(effective) if effective in efforts else 0)
        self.inline_slider.setEnabled(bool(efforts))
        self.inline_value.setText(effort_label(self.currentData() or "auto"))
        self.inline_brain.set_detail(DETAIL.get(effective, .46))
        self.inline_auto.setChecked(self.currentData() == "auto")
        self.inline_auto.setVisible(self.findData("auto") >= 0)
        self.inline_slider.setAccessibleDescription(effort_label(self.currentData() or "auto"))
        self.setAccessibleDescription(f"Seçili düzey: {effort_label(self.currentData() or 'auto')}")
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(230, 74)

    def minimumSizeHint(self):
        return QSize(218, 74)

    def showPopup(self):
        if not self.isEnabled():
            return
        if self._popover is None:
            self._popover = _ReasoningPopover(self)
        self._popover.sync(animate=False)
        self._popover.adjustSize()
        bounds = self.screen().availableGeometry()
        anchor = self.mapToGlobal(QPoint(0, 0))
        x = max(bounds.left()+8, min(anchor.x(), bounds.right()-self._popover.width()-8))
        y = anchor.y()-self._popover.height()-8
        if y < bounds.top()+8:
            y = anchor.y()+self.height()+8
        y = max(bounds.top()+8, min(y, bounds.bottom()-self._popover.height()-8))
        self._popover.move(x, y)
        self._popover.show()
        self._popover.slider.setFocus(Qt.FocusReason.PopupFocusReason)
        self.update()

    def hidePopup(self):
        if self._popover is not None:
            self._popover.hide()
        super().hidePopup()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.hidePopup() if self._popover is not None and self._popover.isVisible() else self.showPopup()
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F4}:
            self.showPopup()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.hidePopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        event.ignore()

    def changeEvent(self, event):
        if not self.isEnabled():
            self.hidePopup()
        self.update()
        super().changeEvent(event)

    def hideEvent(self, event):
        self.hidePopup()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.underMouse() or self.hasFocus() or (self._popover is not None and self._popover.isVisible())
        painter.setPen(QPen(QColor("#BDD0F0"), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#EFF5FF" if active and self.isEnabled() else "#F6F8FC"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 9, 9)
