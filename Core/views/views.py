from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton,QAbstractButton,\
    QLabel,QHBoxLayout,QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase,QPalette,QPixmap
import sys



class ListSmartItemWidget(QWidget):
    """
    Çok amaçlı liste öğesi bileşeni.
    Sol ikon, orta metin ve sağa yerleştirilebilir widget (toggle, checkbox, buton vs) destekler.
    """
    interaction = pyqtSignal(str, object)  # identifier, value

    def __init__(
        self,
        title: str,
        identifier: str = None,
        icon_path: str = None,
        optional_widget: QWidget = None,
        initial_active: bool = True
    ):
        super().__init__()
        self.identifier = identifier or title

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)

        # Sol ikon (isteğe bağlı)
        if icon_path:
            self.icon = QLabel()
            pixmap = QPixmap(icon_path).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.icon.setPixmap(pixmap)
            self.icon.setFixedSize(20, 20)
            layout.addWidget(self.icon)
        else:
            self.icon = None

        # Orta metin
        self.label = QLabel(title)
        self.label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label)

        # Sağ widget (toggle, buton, checkbox vs)
        self.right_widget = optional_widget
        if self.right_widget:
            layout.addWidget(self.right_widget)
            self._connect_right_widget()

        # Başlangıç stili
        self.set_active_style(initial_active)

    def _connect_right_widget(self):
        if hasattr(self.right_widget, "clicked"):  # QPushButton, QCheckBox, SwitchButton
            self.right_widget.clicked.connect(self._on_widget_clicked)
        elif hasattr(self.right_widget, "stateChanged"):
            self.right_widget.stateChanged.connect(self._on_widget_state_changed)

    def _on_widget_clicked(self, value):
        self.interaction.emit(self.identifier, value)

    def _on_widget_state_changed(self, state):
        self.interaction.emit(self.identifier, state)

    def set_active_style(self, active: bool):
        if active:
            self.label.setStyleSheet("color: black; font-weight: bold; font-size: 13px;")
            self.setAutoFillBackground(False)
        else:
            self.label.setStyleSheet("color: gray; font-weight: normal; font-size: 13px;")
            pal = self.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor("#f0f0f0"))
            self.setAutoFillBackground(True)
            self.setPalette(pal)




class CircularProgressButton(QPushButton):
    def __init__(self, text="Başlat", parent=None):
        super().__init__(text, parent)
        self._progress = 0
        self._is_running = False
        self._scale = 1.0

        self.setFixedSize(120, 120)
        self.default_color = QColor("#3498db")   # mavi
        self.running_color = QColor("#2ecc71")   # yeşil
        self.text_color = QColor("white")
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        self.progress_font_family = self._pick_decorative_font()
        self.progress_font_base = QFont(self.progress_font_family, 10, QFont.Weight.Black)
        self.progress_font_base.setStretch(100)

        self._scale_anim = QPropertyAnimation(self, b"scale")
        self._scale_anim.setDuration(120)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.pressed.connect(self.animate_press_in)
        self.released.connect(self.animate_press_out)
        self.clicked.connect(self.toggle)

    def _pick_decorative_font(self) -> str:
        prefer = ["Orbitron", "Audiowide", "Russo One", "Stencil", "Impact", "Comic Sans MS", "Bahnschrift SemiBold"]
        available = QFontDatabase.families()
        for fam in prefer:
            if fam in available:
                return fam
        return "Segoe UI"

    def getScale(self): return self._scale
    def setScale(self, value):
        self._scale = value
        self.update()
    scale = pyqtProperty(float, fget=getScale, fset=setScale)

    def toggle(self):
        if self._is_running:
            self.reset()
        else:
            self.start()

    def start(self):
        self._is_running = True
        self._progress = 0
        self._scale_anim.stop()
        self.setScale(0.9)  # içeride sabit kal
        self.update()

    def reset(self):
        self._is_running = False
        self._progress = 0
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.start()
        self.update()

    def setProgress(self, value: int):
        if not self._is_running:
            return
        if 0 <= value <= 100:
            self._progress = value
            if value >= 100:
                self.reset()
            self.update()

    def animate_press_in(self):
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(0.9)
        self._scale_anim.start()

    def animate_press_out(self):
        if self._is_running:
            return
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        radius = min(rect.width(), rect.height()) / 2 - 6
        center = QPointF(rect.center())

        painter.save()
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)

        pen = QPen(QColor("#bdc3c7"), 6)
        painter.setPen(pen)
        painter.drawEllipse(center, radius, radius)

        if self._is_running:
            pen.setColor(self.running_color)
            painter.setPen(pen)
            span_angle = int(360 * self._progress / 100)
            painter.drawArc(
                QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
                -90 * 16,
                -span_angle * 16
            )

        painter.setBrush(self.running_color if self._is_running else self.default_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius - 8, radius - 8)

        painter.setPen(self.text_color)
        if self._is_running:
            percent_text = f"{self._progress}%"
            px = (radius - 10) * 0.9
            pt = max(9, int(px * 0.75))
            progress_font = QFont(self.progress_font_base)
            progress_font.setPointSize(pt)
            progress_font.setWeight(QFont.Weight.Black)
            painter.setFont(progress_font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, percent_text)
        else:
            painter.setFont(self.font())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

        painter.restore()







class SwitchButton(QAbstractButton):
    """
    Genel amaçlı, animasyonlu, oval bir on/off anahtarı.
    Özelleştirilebilir ve isChecked() ile durum kontrol edilebilir.

    Kullanım:
        switch = SwitchButton()
        switch.setChecked(True)
        switch.clicked.connect(lambda state: print("Açık mı:", state))
    """

    def __init__(
        self,
        parent=None,
        checked_color="#1abc9c",
        unchecked_color="#cccccc",
        thumb_color="white",
        animation_duration=150
    ):
        super().__init__(parent)
        self.setCheckable(True)

        # Renkler
        self._checked_color = QColor(checked_color)
        self._unchecked_color = QColor(unchecked_color)
        self._thumb_color = QColor(thumb_color)

        # Animasyon
        self._thumb_pos = 3
        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setDuration(animation_duration)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(50, 28)

        self.setThumbInitial()

    def sizeHint(self):
        return self.size()

    def paintEvent(self, event):
        radius = self.height() / 2
        bg_color = self._checked_color if self.isChecked() else self._unchecked_color

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(self.rect(), radius, radius)

        # thumb (yuvarlak top)
        r = self.height() - 6
        painter.setBrush(self._thumb_color)
        painter.drawEllipse(QRectF(self._thumb_pos, 3, r, r))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            self._animate()
            self.clicked.emit(self.isChecked())

    def _animate(self):
        start = self._thumb_pos
        end = self.width() - self.height() + 3 if self.isChecked() else 3
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def get_thumb_pos(self):
        return self._thumb_pos

    def set_thumb_pos(self, pos):
        self._thumb_pos = pos
        self.update()

    thumb_pos = pyqtProperty(float, fget=get_thumb_pos, fset=set_thumb_pos)

    def setThumbInitial(self):
        """Başlangıçta doğru pozisyona ayarlamak için çağrılır."""
        self._thumb_pos = self.width() - self.height() + 3 if self.isChecked() else 3

    def setChecked(self, checked: bool):
        """Harici setChecked çağrılarında da thumb konumunu düzeltir."""
        super().setChecked(checked)
        self.setThumbInitial()
        self.update()

