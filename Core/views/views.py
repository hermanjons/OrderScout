from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QAbstractButton, \
    QLabel, QHBoxLayout, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QPalette, QPixmap
import sys


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

        self._hover_progress = 0.0  # ← 🔧 HATAYI ÖNLER
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
        self._is_hovered = True
        self._anim.stop()
        self._anim.setStartValue(self._hover_progress)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, event):
        self._is_hovered = False
        self._anim.stop()
        self._anim.setStartValue(self._hover_progress)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)

        # Hover efekti
        bg = QColor(self._bg_color)
        if self._is_hovered:
            bg = self._bg_color.lighter(100 + int(20 * self._hover_progress))

        painter.setBrush(bg)
        painter.setPen(QPen(self._border_color, 1))
        painter.drawRoundedRect(rect, self._radius, self._radius)

        # İkon çizimi
        if self._icon:
            icon_size = 36
            icon_x = 20
            icon_y = (self.height() - icon_size) // 2
            painter.drawPixmap(icon_x, icon_y, icon_size, icon_size, self._icon)

        # Metin
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#333333"))

        text_x = 70 if self._icon else 20
        text_y = self.height() // 2 + 5
        painter.drawText(QPointF(text_x, text_y), self._text)

    def get_hover_progress(self):
        return self._hover_progress

    def set_hover_progress(self, value):
        self._hover_progress = value
        self.update()

    hover_progress = pyqtProperty(float, fget=get_hover_progress, fset=set_hover_progress)


from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QPalette


class ListSmartItemWidget(QWidget):
    """
    Kart görünümünde çok amaçlı liste öğesi.
    - Sol ikon (opsiyonel)
    - Ortada çok satırlı metin (title / subtitle / extra) (kopyalanabilir)
    - Sağda opsiyonel widget (SwitchButton, buton, vs.)
    - Hover efekti + tıklanınca seçili kalma
    - Parent zincirine bağımlı değil: selectionRequested sinyali yayınlar
    """
    interaction = pyqtSignal(str, object)  # (identifier, value)
    selectionRequested = pyqtSignal(QWidget)  # parent temizlesin diye

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
        self.identifier = identifier or title

        self._hover = False
        self._selected = False

        # İsteğe bağlı: kart tıklanabilir olduğunu hissettirsin
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Sol ikon
        if icon_path:
            self.icon = QLabel()
            pixmap = QPixmap(icon_path).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
            self.icon.setPixmap(pixmap)
            self.icon.setFixedSize(28, 28)
            layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignTop)
        else:
            self.icon = None

        # Orta metin
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

        # Sağ opsiyonel widget
        self.right_widget = optional_widget
        if self.right_widget:
            # Sağdaki widget tıklandığında kartı seçili yapmayalım:
            self.right_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            layout.addWidget(self.right_widget,
                             alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._connect_right_widget()

        # Shadow efektini bir kez oluştur
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(12)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(2)
        self._shadow.setColor(QColor(0, 0, 0, 50))
        self.setGraphicsEffect(self._shadow)
        self._shadow.setEnabled(False)

        self.setAutoFillBackground(True)
        self._apply_background("#ffffff")

    # Sağdaki widget sinyallerini bağla → interaction yayınla
    def _connect_right_widget(self):
        if hasattr(self.right_widget, "clicked"):
            self.right_widget.clicked.connect(self._on_right_widget_clicked)
        if hasattr(self.right_widget, "stateChanged"):
            self.right_widget.stateChanged.connect(self._on_right_widget_state_changed)

    def _on_right_widget_clicked(self, value):
        # SwitchButton gibi QAbstractButton'lar bool gönderebilir
        self.interaction.emit(self.identifier, value)

    def _on_right_widget_state_changed(self, state):
        self.interaction.emit(self.identifier, state)

    # ---- Etkileşim / Stil ----
    def mousePressEvent(self, event):
        # Eğer sağdaki widget tıklandıysa kart seçimini tetikleme
        if self.right_widget and self.right_widget.geometry().contains(event.pos()):
            return super().mousePressEvent(event)

        self._selected = True
        self.update_style()
        self.selectionRequested.emit(self)  # parent diğerlerini temizlesin
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
        """
        Sadece yeniden çizimi tetikler.
        Arka plan ve border paintEvent içinde çizilir.
        """
        self.update()  # paintEvent tekrar çalışır

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 🔹 renkler
        base_color = QColor("#ffffff")  # normal
        hover_color = QColor("#fafafa")  # çok hafif gri
        selected_color = QColor("#f0f6ff")  # açık mavi

        if self._selected:
            bg = selected_color
            border = QColor("#3399ff")  # hafif mavi kenarlık
            border_width = 2
        elif self._hover:
            bg = hover_color
            border = QColor("#cccccc")
            border_width = 1
        else:
            bg = base_color
            border = QColor(Qt.GlobalColor.transparent)
            border_width = 0

        # 🔹 arka plan
        rect = self.rect()
        painter.setBrush(bg)
        painter.setPen(QPen(border, border_width))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

        # diğer widget'lar normal çizilsin
        super().paintEvent(event)


class CircularProgressButton(QPushButton):
    def __init__(self, text="Başlat", parent=None):
        super().__init__(text, parent)
        self._progress = 0
        self._is_running = False
        self._scale = 1.0

        self.setFixedSize(120, 120)
        self.default_color = QColor("#3498db")  # mavi
        self.running_color = QColor("#2ecc71")  # yeşil
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

    def getScale(self):
        return self._scale

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
