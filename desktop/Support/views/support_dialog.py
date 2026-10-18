from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import settings
from Core.views import AppMessageCenter


class SupportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bana bir kahve al")
        self.setMinimumWidth(440)
        self.resize(500, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(16)

        title = QLabel("☕ Bana bir kahve al")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(title)

        description = QLabel(
            "OrderScout açık kaynak ve ücretsizdir. Tüm özellikleri "
            "aktivasyon anahtarı veya abonelik olmadan kullanabilirsin.\n\n"
            "İşini kolaylaştırıyorsa, bir kahve ısmarlayarak geliştirilmesine "
            "destek olabilirsin. Desteğin için teşekkürler!"
        )
        description.setWordWrap(True)
        description.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(description)

        self.donation_url = QUrl(str(settings.DONATION_URL).strip())
        self.has_donation_url = (
            self.donation_url.isValid()
            and self.donation_url.scheme().lower() in {"http", "https"}
            and bool(self.donation_url.host())
        )
        self.hint_label = QLabel(
            "Bağış tamamen isteğe bağlıdır; uygulamanın kullanımını etkilemez."
            if self.has_donation_url
            else "Bağış bağlantısı henüz eklenmedi. OrderScout'u ücretsiz kullanmaya devam edebilirsin."
        )
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        layout.addStretch()

        buttons = QHBoxLayout()
        self.donate_button = QPushButton("☕ Bana bir kahve al")
        self.donate_button.setMinimumHeight(40)
        self.donate_button.setEnabled(self.has_donation_url)
        self.donate_button.clicked.connect(self._open_donation_page)
        buttons.addWidget(self.donate_button)
        close_button = QPushButton("Kapat")
        close_button.setMinimumHeight(40)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _open_donation_page(self):
        if self.has_donation_url and not QDesktopServices.openUrl(self.donation_url):
            AppMessageCenter.warning(
                self,
                "Bağlantı açılamadı",
                "Bağış sayfası tarayıcıda açılamadı. Daha sonra tekrar deneyebilirsin.",
            )
