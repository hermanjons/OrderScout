from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase
import sys


class CircularProgressButton(QPushButton):
    def __init__(self, text="Başlat", parent=None):
        super().__init__(text, parent)
        self._progress = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.advance_progress)

        self.setFixedSize(120, 120)
        self.default_color = QColor("#3498db")   # mavi (idle)
        self.running_color = QColor("#2ecc71")   # yeşil (running)
        self.text_color = QColor("white")

        self._is_running = False

        # Label font (buton yazısı)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        # Progress font (ortadaki % yazısı için "değişik" font)
        self.progress_font_family = self._pick_decorative_font()
        self.progress_font_base = QFont(self.progress_font_family, 10, QFont.Weight.Black)
        # Hafif harf aralığı verelim; dekoratif hissi artırır
        self.progress_font_base.setStretch(100)

        # İstersen buradan kendi TTF dosyanı yükleyebilirsin:
        # font_id = QFontDatabase.addApplicationFont(":/fonts/Audiowide-Regular.ttf")

        # merkezden küçülme / büyüme için scale property animasyonu
        self._scale = 1.0
        self._scale_anim = QPropertyAnimation(self, b"scale")
        self._scale_anim.setDuration(120)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # etkileşim: basınca içeri göç, bırakınca koşula göre hareket
        self.pressed.connect(self.animate_press_in)
        self.released.connect(self.animate_press_out)
        self.clicked.connect(self.toggle)

    # --- yardımcı: uygun dekoratif font seç ---
    def _pick_decorative_font(self) -> str:
        prefer = ["Orbitron", "Audiowide", "Russo One", "Stencil", "Impact", "Comic Sans MS", "Bahnschrift SemiBold"]
        available = QFontDatabase.families()
        for fam in prefer:
            if fam in available:
                return fam
        return "Segoe UI"

    # --- scale property ---
    def getScale(self): return self._scale
    def setScale(self, value):
        self._scale = value
        self.update()
    scale = pyqtProperty(float, fget=getScale, fset=setScale)

    # --- public api ---
    def toggle(self):
        if self._is_running:
            self.reset()
        else:
            self.start()

    def start(self):
        """Çalışmayı başlat: yeşile dön, ilerlemeyi başlat, buton içeride kalsın."""
        self._is_running = True
        self._progress = 0
        self._timer.start(30)
        # içeride sabit kalsın
        self._scale_anim.stop()
        self.setScale(0.9)  # pressed hissi, kalıcı
        self.update()

    def reset(self):
        """Çalışma bitti: ilerlemeyi durdur, yukarı animasyonla çık."""
        self._is_running = False
        self._timer.stop()
        self._progress = 0
        # yukarı (eski boyuta) dön
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.start()
        self.update()

    # --- progress ---
    def advance_progress(self):
        if self._progress < 100:
            self._progress += 1
        else:
            self.reset()
        self.update()

    # --- interactions ---
    def animate_press_in(self):
        """Basınca içeri doğru girsin (scale ↓)."""
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(0.9)
        self._scale_anim.start()

    def animate_press_out(self):
        """Bırakınca: eğer çalışıyorsa içeride KALSIN; değilse eski haline dönsün."""
        if self._is_running:
            return  # çalışma sürerken yukarı çıkma!
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.start()

    # --- paint ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        radius = min(rect.width(), rect.height()) / 2 - 6
        center = QPointF(rect.center())

        painter.save()
        # merkezden scale
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)

        # dış çember (gri kılavuz)
        pen = QPen(QColor("#bdc3c7"), 6)
        painter.setPen(pen)
        painter.drawEllipse(center, radius, radius)

        # progress çemberi (sadece çalışırken)
        if self._is_running:
            pen.setColor(self.running_color)
            painter.setPen(pen)
            span_angle = int(360 * self._progress / 100)
            painter.drawArc(
                QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
                -90 * 16,
                -span_angle * 16
            )

        # iç dolgu
        painter.setBrush(self.running_color if self._is_running else self.default_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius - 8, radius - 8)

        # yazılar
        painter.setPen(self.text_color)

        if self._is_running:
            # Ortada % göster — dinamik boyutla
            percent_text = f"{self._progress}%"
            # Dinamik point size: buton çapına göre yaklaşık orantı
            px = (radius - 10) * 0.9
            # point ~ pixels*(72/96) varsayımıyla basit bir çevrim
            pt = max(9, int(px * 0.75))
            progress_font = QFont(self.progress_font_base)
            progress_font.setPointSize(pt)
            progress_font.setWeight(QFont.Weight.Black)
            painter.setFont(progress_font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, percent_text)
        else:
            # Idle: standart buton metni
            painter.setFont(self.font())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

        painter.restore()


# --- TEST ALANI ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout()

    btn = CircularProgressButton("Çalıştır")
    layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    window.setLayout(layout)
    window.resize(320, 320)
    window.setWindowTitle("Circular Progress Button — pressed-state hold + % overlay")
    window.show()
    sys.exit(app.exec())
