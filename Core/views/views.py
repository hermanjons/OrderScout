from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QAbstractButton,
    QLabel, QHBoxLayout, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal, \
    QAbstractAnimation
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPixmap, QPalette
from Feedback.processors.pipeline import Result, map_error_to_message


# ========================
# 🎨 PackageButton
# ========================
class PackageButton(QAbstractButton):
    """
    Sipariş Paketi görünümünde özel buton.
    Hem ikon hem başlık içerir. Hover'da animasyon ve parlama efekti verir.
    """

    clicked = pyqtSignal()

    def __init__(
            self,
            text="Siparişler",
            icon_path=None,
            bg_color="#f0f0f0",
            border_color="#999999",
            hover_color="#e0ffe0",
            radius=12,
            parent=None
    ):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(200, 80)

        self._hover_progress = 0.0
        self._text = text
        self._icon = QPixmap(icon_path) if icon_path else None
        self._bg_color = QColor(bg_color)
        self._border_color = QColor(border_color)
        self._hover_color = QColor(hover_color)
        self._radius = radius

        self._is_hovered = False
        self._anim = QPropertyAnimation(self, b"hover_progress", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)

    def enterEvent(self, event):
        try:
            self._is_hovered = True
            self._anim.stop()
            self._anim.setStartValue(self._hover_progress)
            self._anim.setEndValue(1.0)
            self._anim.start()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def leaveEvent(self, event):
        try:
            self._is_hovered = False
            self._anim.stop()
            self._anim.setStartValue(self._hover_progress)
            self._anim.setEndValue(0.0)
            self._anim.start()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = self.rect().adjusted(1, 1, -1, -1)
            bg = QColor(self._bg_color)
            if self._is_hovered:
                bg = self._bg_color.lighter(100 + int(20 * self._hover_progress))

            painter.setBrush(bg)
            painter.setPen(QPen(self._border_color, 1))
            painter.drawRoundedRect(rect, self._radius, self._radius)

            if self._icon:
                icon_size = 36
                icon_x = 20
                icon_y = (self.height() - icon_size) // 2
                painter.drawPixmap(icon_x, icon_y, icon_size, icon_size, self._icon)

            font = QFont()
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#333333"))

            text_x = 70 if self._icon else 20
            text_y = self.height() // 2 + 5
            painter.drawText(QPointF(text_x, text_y), self._text)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def get_hover_progress(self):
        return self._hover_progress

    def set_hover_progress(self, value):
        self._hover_progress = value
        self.update()

    hover_progress = pyqtProperty(float, fget=get_hover_progress, fset=set_hover_progress)


# ========================
# 📋 ListSmartItemWidget
# ========================
class ListSmartItemWidget(QWidget):
    """
    Kart görünümünde çok amaçlı liste öğesi.
    """

    interaction = pyqtSignal(str, object)  # (identifier, value)
    selectionRequested = pyqtSignal(QWidget)

    def __init__(
            self,
            title: str,
            identifier: str = None,
            subtitle: str = None,
            extra: str = None,
            icon_path: str = None,
            optional_widget: QWidget = None
    ):
        super().__init__()
        try:
            self.identifier = identifier or title
            self._hover = False
            self._selected = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(12)

            if icon_path:
                self.icon = QLabel()
                pixmap = QPixmap(icon_path).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)
                self.icon.setPixmap(pixmap)
                self.icon.setFixedSize(28, 28)
                layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignTop)
            else:
                self.icon = None

            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)

            self.label_title = QLabel(title)
            self.label_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #222;")
            self.label_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_layout.addWidget(self.label_title)

            self.label_subtitle = None
            if subtitle:
                self.label_subtitle = QLabel(subtitle)
                self.label_subtitle.setStyleSheet("color: #444; font-size: 12px;")
                self.label_subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text_layout.addWidget(self.label_subtitle)

            self.label_extra = None
            if extra:
                self.label_extra = QLabel(extra)
                self.label_extra.setStyleSheet("color: #666; font-size: 12px;")
                self.label_extra.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text_layout.addWidget(self.label_extra)

            layout.addLayout(text_layout, stretch=1)

            self.right_widget = optional_widget
            if self.right_widget:
                self.right_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                layout.addWidget(self.right_widget,
                                 alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._connect_right_widget()

            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(12)
            self._shadow.setXOffset(0)
            self._shadow.setYOffset(2)
            self._shadow.setColor(QColor(0, 0, 0, 50))
            self.setGraphicsEffect(self._shadow)
            self._shadow.setEnabled(False)

            self.setAutoFillBackground(True)
            self._apply_background("#ffffff")

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _connect_right_widget(self):
        if hasattr(self.right_widget, "clicked"):
            self.right_widget.clicked.connect(self._on_right_widget_clicked)
        if hasattr(self.right_widget, "stateChanged"):
            self.right_widget.stateChanged.connect(self._on_right_widget_state_changed)

    def _on_right_widget_clicked(self, value):
        self.interaction.emit(self.identifier, value)

    def _on_right_widget_state_changed(self, state):
        self.interaction.emit(self.identifier, state)

    def mousePressEvent(self, event):
        if self.right_widget and self.right_widget.geometry().contains(event.pos()):
            return super().mousePressEvent(event)
        self._selected = True
        self.update_style()
        self.selectionRequested.emit(self)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update_style()

    def enterEvent(self, event):
        self._hover = True
        self.update_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update_style()
        super().leaveEvent(event)

    def _apply_background(self, hex_color: str):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(hex_color))
        self.setPalette(pal)

    def update_style(self):
        self.update()

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            base_color = QColor("#ffffff")
            hover_color = QColor("#fafafa")
            selected_color = QColor("#f0f6ff")

            if self._selected:
                bg = selected_color
                border = QColor("#3399ff")
                border_width = 2
            elif self._hover:
                bg = hover_color
                border = QColor("#cccccc")
                border_width = 1
            else:
                bg = base_color
                border = QColor(Qt.GlobalColor.transparent)
                border_width = 0

            rect = self.rect()
            painter.setBrush(bg)
            painter.setPen(QPen(border, border_width))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

            super().paintEvent(event)

        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))


# ========================
# ⭕ CircularProgressButton
# ========================
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt, QRectF, QPointF, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase

from PyQt6.QtCore import (
    Qt, QEasingCurve, QPropertyAnimation, pyqtProperty,
    pyqtSignal, QTimer, QAbstractAnimation, QPointF, QRectF
)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase
from PyQt6.QtWidgets import QPushButton

from Feedback.processors.pipeline import Result, map_error_to_message


class CircularProgressButton(QPushButton):
    started = pyqtSignal()
    finished = pyqtSignal()
    scaleChanged = pyqtSignal(float)

    def __init__(self, text="Başlat", parent=None):
        try:
            super().__init__(text, parent)

            self._progress = 0
            self._is_running = False
            self._scale = 1.0

            self.setFixedSize(120, 120)
            self.default_color = QColor("#3498db")  # normal mavi
            self.running_color = QColor("#2ecc71")  # çalışırken yeşil
            self.text_color = QColor("white")
            self.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.setCursor(Qt.CursorShape.PointingHandCursor)

            # font
            self.progress_font_family = self._pick_decorative_font()
            self.progress_font_base = QFont(self.progress_font_family, 10, QFont.Weight.Black)
            self.progress_font_base.setStretch(100)

            # ölçek animasyonu
            self._scale_anim = QPropertyAnimation(self, b"scale")
            self._scale_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    # ----------------
    def _pick_decorative_font(self) -> str:
        try:
            prefer = ["Orbitron", "Russo One", "Digital-7", "Bahnschrift SemiBold"]
            available = QFontDatabase.families()
            for fam in prefer:
                if fam in available:
                    return fam
            return "Segoe UI"
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)
            return "Segoe UI"

    # ----------------
    def getScale(self) -> float:
        return self._scale

    def setScale(self, value: float):
        try:
            if self._scale == value:
                return
            self._scale = value
            self.scaleChanged.emit(value)
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    scale = pyqtProperty(float, fget=getScale, fset=setScale, notify=scaleChanged)

    # ----------------
    def start(self):
        try:
            if self._is_running:
                return
            self._is_running = True
            self._is_failed = False  # 🔄 fail state sıfırlansın
            self._progress = 0
            self.running_color = QColor("#2ecc71")  # 🟢 yeşil
            self._animate_to(0.85, duration=200)  # basılı hale geç
            self.started.emit()
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def reset(self):
        try:
            if not self._is_running and self._progress == 0 and self._scale == 1.0 and not self._is_failed:
                return
            self._is_running = False
            self._progress = 0
            self._is_failed = False  # 🔄 hata modu sıfırlanır
            self.running_color = QColor("#2ecc71")
            self._animate_to(1.0, duration=250)
            self.finished.emit()
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def setProgress(self, value: int):
        try:
            v = max(0, min(100, int(value)))

            if not self._is_running and v > 0:
                self.start()

            if self._progress == v and self._is_running:
                return

            self._progress = v
            self.update()

            if v >= 100:
                QTimer.singleShot(120, self.reset)
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    # ----------------
    def _animate_to(self, end_value: float, duration: int = 200):
        try:
            if self._scale_anim.state() == QAbstractAnimation.State.Running:
                self._scale_anim.stop()
            self._scale_anim.setDuration(duration)
            self._scale_anim.setStartValue(self._scale)
            self._scale_anim.setEndValue(end_value)
            self._scale_anim.start()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def mousePressEvent(self, event):
        try:
            if not self._is_running:
                self.start()
            super().mousePressEvent(event)
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    # ----------------
    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = self.rect()
            radius = min(rect.width(), rect.height()) / 2 - 6
            center = QPointF(rect.center())

            painter.save()
            painter.translate(center)
            painter.scale(self._scale, self._scale)
            painter.translate(-center)

            # dış çember
            pen = QPen(QColor("#bdc3c7"), 6)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)

            # 1) Fail state → kırmızı + Retry
            if getattr(self, "_is_failed", False):
                painter.setBrush(QColor("#e74c3c"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, radius - 8, radius - 8)

                painter.setPen(self.text_color)
                painter.setFont(self.font())
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Retry")

            # 2) Running state → progress + yüzde
            elif self._is_running:
                # progress çemberi
                if self._progress > 0:
                    pen.setColor(self.running_color)
                    painter.setPen(pen)
                    span_angle = int(360 * self._progress / 100)
                    painter.drawArc(
                        QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
                        -90 * 16,
                        -span_angle * 16
                    )

                # iç dolgu
                painter.setBrush(self.running_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, radius - 8, radius - 8)

                # yüzde metni
                painter.setPen(self.text_color)
                progress_font = QFont(self.progress_font_base)
                progress_font.setPointSize(20)
                progress_font.setWeight(QFont.Weight.Black)
                painter.setFont(progress_font)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._progress}%")

            # 3) Idle state → mavi + Başlat
            else:
                painter.setBrush(self.default_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, radius - 8, radius - 8)

                painter.setPen(self.text_color)
                painter.setFont(self.font())
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

            painter.restore()

        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)

    def fail(self):
        try:
            self._is_running = False
            self._progress = 0
            self._is_failed = True  # fail state aktif

            self.running_color = QColor("#e74c3c")  # 🔴 kırmızı
            self._animate_to(1.0, duration=250)  # çıkık hale dön
            self.update()
        except Exception as e:
            Result.fail(map_error_to_message(e), error=e)


# ========================
# 🔘 SwitchButton
# ========================
class SwitchButton(QAbstractButton):
    def __init__(self, parent=None, checked_color="#1abc9c", unchecked_color="#cccccc", thumb_color="white", animation_duration=150):
        super().__init__(parent)
        try:
            self.setCheckable(True)
            self._checked_color = QColor(checked_color)
            self._unchecked_color = QColor(unchecked_color)
            self._thumb_color = QColor(thumb_color)

            self._thumb_pos = 3
            self._anim = QPropertyAnimation(self, b"thumb_pos", self)
            self._anim.setDuration(animation_duration)

            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFixedSize(50, 28)
            self.setThumbInitial()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    # 🔑 BURASI YENİ: animasyonun takip edeceği property
    def getThumbPos(self):
        return self._thumb_pos

    def setThumbPos(self, pos):
        self._thumb_pos = pos
        self.update()  # repaint tetikle
    thumb_pos = pyqtProperty(int, fget=getThumbPos, fset=setThumbPos)

    def paintEvent(self, event):
        try:
            radius = self.height() / 2
            bg_color = self._checked_color if self.isChecked() else self._unchecked_color

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_color)
            painter.drawRoundedRect(self.rect(), radius, radius)

            r = self.height() - 6
            painter.setBrush(self._thumb_color)
            painter.drawEllipse(QRectF(self._thumb_pos, 3, r, r))
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def mouseReleaseEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self.toggle()
                self._animate()
                self.clicked.emit(self.isChecked())
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def _animate(self):
        try:
            start = self._thumb_pos
            end = self.width() - self.height() + 3 if self.isChecked() else 3
            self._anim.stop()
            self._anim.setStartValue(start)
            self._anim.setEndValue(end)
            self._anim.start()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def setThumbInitial(self):
        try:
            self._thumb_pos = self.width() - self.height() + 3 if self.isChecked() else 3
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))

    def setChecked(self, checked: bool):
        try:
            super().setChecked(checked)
            self.setThumbInitial()
            self.update()
        except Exception as e:
            print(Result.fail(map_error_to_message(e), error=e))