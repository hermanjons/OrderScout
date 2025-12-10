# License/views/views.py
from __future__ import annotations

import os
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGroupBox, QGridLayout, QWidget,
    QMessageBox, QSizePolicy, QSpacerItem
)
from PyQt6.QtGui import QIcon, QFont, QAction
from PyQt6.QtCore import QSize, Qt

from settings import MEDIA_ROOT


# ─────────────────────────────────────────
# 🎨 Lisans Yönetimi Dialog'u (UI)
# ─────────────────────────────────────────
class LicenseManagerDialog(QDialog):
    """
    OrderScout lisans yönetim ekranı.
    Sadece UI tasarım odaklı; veri doldurma için set_license_data() kullanılacak.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Lisans Yönetimi - OrderScout")
        self.resize(720, 460)

        self._setup_styles()
        self._init_ui()

        # Şimdilik örnek dummy data yüklüyoruz.
        # Gerçek entegrasyonda bu satırı kaldırıp dışarıdan set_license_data() çağırırsın.
        self._load_demo_data()

    # ─────────────────────────
    # Stil ayarları
    # ─────────────────────────
    def _setup_styles(self):
        # Basit, modern bir dark tema
        self.setStyleSheet("""
        QDialog {
            background-color: #101018;
            color: #F5F5F5;
        }
        QLabel {
            color: #F5F5F5;
        }
        QGroupBox {
            border: 1px solid #26293A;
            border-radius: 10px;
            margin-top: 16px;
            padding: 12px;
            color: #C5C7D5;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px 0 4px;
        }
        QPushButton {
            border-radius: 8px;
            padding: 8px 16px;
            background-color: #2F80ED;
            color: white;
            border: none;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #337FE0;
        }
        QPushButton:disabled {
            background-color: #3A3F55;
            color: #888C99;
        }
        QPushButton#secondaryButton {
            background-color: #1F2233;
            border: 1px solid #34384C;
        }
        QPushButton#secondaryButton:hover {
            background-color: #25293B;
        }
        QPushButton#dangerButton {
            background-color: #EB5757;
        }
        QPushButton#dangerButton:hover {
            background-color: #D94444;
        }
        QFrame#card {
            background-color: #181B2A;
            border-radius: 14px;
            border: 1px solid #26293A;
        }
        QLabel#titleLabel {
            font-size: 18px;
            font-weight: 600;
        }
        QLabel#subtitleLabel {
            font-size: 12px;
            color: #A0A4B8;
        }
        QLabel#valueLabel {
            font-weight: 500;
            color: #E6E8F2;
        }
        QLabel#hintLabel {
            font-size: 11px;
            color: #9EA2B8;
        }
        QLabel#statusBadge {
            padding: 4px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            color: #0E111A;
            background-color: #27AE60; /* varsayılan: aktif */
        }
        """)

    # ─────────────────────────
    # Ana UI layout
    # ─────────────────────────
    def _init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # ── Header Card
        header_card = QFrame()
        header_card.setObjectName("card")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(10)

        # Sol taraf: Başlık + açıklama
        header_text_layout = QVBoxLayout()
        self.lbl_title = QLabel("OrderScout Lisans Yönetimi")
        self.lbl_title.setObjectName("titleLabel")

        self.lbl_subtitle = QLabel("Lisans anahtarını yönet, plan detaylarını görüntüle ve durumu kontrol et.")
        self.lbl_subtitle.setObjectName("subtitleLabel")
        self.lbl_subtitle.setWordWrap(True)

        header_text_layout.addWidget(self.lbl_title)
        header_text_layout.addWidget(self.lbl_subtitle)

        # Sağ taraf: Status badge
        header_right_layout = QVBoxLayout()
        header_right_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_status_badge = QLabel("AKTİF")
        self.lbl_status_badge.setObjectName("statusBadge")
        self.lbl_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_right_layout.addWidget(self.lbl_status_badge)

        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()
        header_layout.addLayout(header_right_layout)

        header_card.setLayout(header_layout)
        main_layout.addWidget(header_card)

        # ── Orta bölge: 2 sütun (Lisans Bilgisi & Plan Bilgisi)
        center_layout = QHBoxLayout()
        center_layout.setSpacing(12)

        # Sol sütun: Lisans Bilgisi
        license_group = QGroupBox("Lisans Bilgileri")
        license_layout = QGridLayout()
        license_layout.setVerticalSpacing(6)
        license_layout.setHorizontalSpacing(12)

        row = 0

        license_layout.addWidget(QLabel("Lisans Anahtarı:"), row, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        self.lbl_license_key = QLabel("-")
        self.lbl_license_key.setObjectName("valueLabel")
        self.lbl_license_key.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        license_layout.addWidget(self.lbl_license_key, row, 1)
        row += 1

        license_layout.addWidget(QLabel("Lisans E-posta:"), row, 0)
        self.lbl_license_email = QLabel("-")
        self.lbl_license_email.setObjectName("valueLabel")
        self.lbl_license_email.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        license_layout.addWidget(self.lbl_license_email, row, 1)
        row += 1

        license_layout.addWidget(QLabel("Durum:"), row, 0)
        self.lbl_license_status = QLabel("-")
        self.lbl_license_status.setObjectName("valueLabel")
        license_layout.addWidget(self.lbl_license_status, row, 1)
        row += 1

        license_layout.addWidget(QLabel("Başlangıç Tarihi:"), row, 0)
        self.lbl_issued_at = QLabel("-")
        self.lbl_issued_at.setObjectName("valueLabel")
        license_layout.addWidget(self.lbl_issued_at, row, 1)
        row += 1

        license_layout.addWidget(QLabel("Bitiş Tarihi:"), row, 0)
        self.lbl_expires_at = QLabel("-")
        self.lbl_expires_at.setObjectName("valueLabel")
        license_layout.addWidget(self.lbl_expires_at, row, 1)
        row += 1

        license_layout.addWidget(QLabel("Son Doğrulama:"), row, 0)
        self.lbl_last_verified = QLabel("-")
        self.lbl_last_verified.setObjectName("valueLabel")
        license_layout.addWidget(self.lbl_last_verified, row, 1)
        row += 1

        self.lbl_license_hint = QLabel("Lisans anahtarın bu cihaza özeldir. Paylaşmaman önerilir.")
        self.lbl_license_hint.setObjectName("hintLabel")
        self.lbl_license_hint.setWordWrap(True)
        license_layout.addItem(QSpacerItem(0, 4, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum), row, 0)
        row += 1
        license_layout.addWidget(self.lbl_license_hint, row, 0, 1, 2)

        license_group.setLayout(license_layout)

        # Sağ sütun: Plan Bilgisi
        plan_group = QGroupBox("Plan ve Abonelik")
        plan_layout = QGridLayout()
        plan_layout.setVerticalSpacing(6)
        plan_layout.setHorizontalSpacing(12)

        row2 = 0

        plan_layout.addWidget(QLabel("Plan Adı:"), row2, 0)
        self.lbl_plan_name = QLabel("-")
        self.lbl_plan_name.setObjectName("valueLabel")
        plan_layout.addWidget(self.lbl_plan_name, row2, 1)
        row2 += 1

        plan_layout.addWidget(QLabel("Plan Kodu:"), row2, 0)
        self.lbl_plan_code = QLabel("-")
        self.lbl_plan_code.setObjectName("valueLabel")
        plan_layout.addWidget(self.lbl_plan_code, row2, 1)
        row2 += 1

        plan_layout.addWidget(QLabel("Faturalama Döngüsü:"), row2, 0)
        self.lbl_billing_cycle = QLabel("-")
        self.lbl_billing_cycle.setObjectName("valueLabel")
        plan_layout.addWidget(self.lbl_billing_cycle, row2, 1)
        row2 += 1

        plan_layout.addWidget(QLabel("Abonelik ID:"), row2, 0)
        self.lbl_subscription_id = QLabel("-")
        self.lbl_subscription_id.setObjectName("valueLabel")
        self.lbl_subscription_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        plan_layout.addWidget(self.lbl_subscription_id, row2, 1)
        row2 += 1

        plan_layout.addWidget(QLabel("Sonraki Faturalama:"), row2, 0)
        self.lbl_next_billing_at = QLabel("-")
        self.lbl_next_billing_at.setObjectName("valueLabel")
        plan_layout.addWidget(self.lbl_next_billing_at, row2, 1)
        row2 += 1

        plan_layout.addWidget(QLabel("Sağlayıcı:"), row2, 0)
        self.lbl_provider = QLabel("-")
        self.lbl_provider.setObjectName("valueLabel")
        plan_layout.addWidget(self.lbl_provider, row2, 1)
        row2 += 1

        self.lbl_plan_hint = QLabel("Plan ve faturalama detayları ödeme sağlayıcın (Freemius vb.) üzerinden yönetilir.")
        self.lbl_plan_hint.setObjectName("hintLabel")
        self.lbl_plan_hint.setWordWrap(True)
        plan_layout.addItem(QSpacerItem(0, 4, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum), row2, 0)
        row2 += 1
        plan_layout.addWidget(self.lbl_plan_hint, row2, 0, 1, 2)

        plan_group.setLayout(plan_layout)

        center_layout.addWidget(license_group)
        center_layout.addWidget(plan_group)

        main_layout.addLayout(center_layout)

        # ── Alt kısım: Device info + butonlar
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        # Sol: Device info
        device_group = QGroupBox("Cihaz Bilgisi")
        device_layout = QGridLayout()
        device_layout.setVerticalSpacing(6)
        device_layout.setHorizontalSpacing(12)

        device_layout.addWidget(QLabel("Device ID:"), 0, 0)
        self.lbl_device_id = QLabel("-")
        self.lbl_device_id.setObjectName("valueLabel")
        self.lbl_device_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        device_layout.addWidget(self.lbl_device_id, 0, 1)

        device_layout.addWidget(QLabel("Son Hata:"), 1, 0)
        self.lbl_last_error = QLabel("-")
        self.lbl_last_error.setObjectName("hintLabel")
        self.lbl_last_error.setWordWrap(True)
        device_layout.addWidget(self.lbl_last_error, 1, 1)

        device_group.setLayout(device_layout)

        bottom_layout.addWidget(device_group, stretch=2)

        # Sağ: Action butonları
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.btn_refresh = QPushButton("Lisansı Şimdi Doğrula")
        self.btn_change_key = QPushButton("Lisans Anahtarını Değiştir")
        self.btn_change_key.setObjectName("secondaryButton")
        self.btn_deactivate = QPushButton("Bu Cihazı Lisanssız Bırak")
        self.btn_deactivate.setObjectName("dangerButton")
        self.btn_close = QPushButton("Kapat")
        self.btn_close.setObjectName("secondaryButton")

        self.btn_refresh.clicked.connect(self.on_refresh_clicked)
        self.btn_change_key.clicked.connect(self.on_change_key_clicked)
        self.btn_deactivate.clicked.connect(self.on_deactivate_clicked)
        self.btn_close.clicked.connect(self.reject)

        actions_layout.addWidget(self.btn_refresh)
        actions_layout.addWidget(self.btn_change_key)
        actions_layout.addWidget(self.btn_deactivate)
        actions_layout.addSpacing(8)
        actions_layout.addWidget(self.btn_close)

        bottom_layout.addLayout(actions_layout, stretch=1)

        main_layout.addLayout(bottom_layout)

        self.setLayout(main_layout)

    # ─────────────────────────
    # UI'ya veri basmak için API
    # ─────────────────────────
    def set_license_data(self, data: Dict[str, Any]):
        """
        Dışarıdan lisans verisini doldurmak için.
        data içinden bulduklarını alır, bulamadıklarını '-' olarak bırakır.
        """

        def get(key, default="-"):
            value = data.get(key, default)
            return value if value not in (None, "") else default

        # Lisans bilgileri
        self._set_label_text(self.lbl_license_key, get("license_key"))
        self._set_label_text(self.lbl_license_email, get("license_email"))
        self._set_label_text(self.lbl_license_status, get("status_label", get("status")))

        self._set_label_text(self.lbl_issued_at, get("license_issued_at"))
        self._set_label_text(self.lbl_expires_at, get("license_expires_at"))
        self._set_label_text(self.lbl_last_verified, get("last_verified_at"))

        # Plan bilgileri
        self._set_label_text(self.lbl_plan_name, get("plan_name"))
        self._set_label_text(self.lbl_plan_code, get("plan_code"))
        self._set_label_text(self.lbl_billing_cycle, get("billing_cycle"))
        self._set_label_text(self.lbl_subscription_id, get("subscription_id"))
        self._set_label_text(self.lbl_next_billing_at, get("next_billing_at"))
        self._set_label_text(self.lbl_provider, get("provider", "freemius"))

        # Cihaz ve hata
        self._set_label_text(self.lbl_device_id, get("device_id"))
        self._set_label_text(self.lbl_last_error, get("last_error_message", "-"))

        # Status badge rengi
        self._update_status_badge(get("status", "none"))

    def _set_label_text(self, label: QLabel, text: str):
        label.setText(str(text))

    def _update_status_badge(self, status: str):
        status = (status or "").lower()

        if "trial" in status:
            text = "TRIAL"
            color = "#F2C94C"
        elif "active" in status or "valid" in status:
            text = "AKTİF"
            color = "#27AE60"
        elif "expired" in status:
            text = "SÜRESİ DOLMUŞ"
            color = "#EB5757"
        elif "blocked" in status or "revoked" in status:
            text = "ENGELLİ"
            color = "#9B51E0"
        else:
            text = "LİSANS YOK"
            color = "#4F4F4F"

        self.lbl_status_badge.setText(text)
        # Badge arka plan rengini inline style ile güncelle
        self.lbl_status_badge.setStyleSheet(
            f"padding: 4px 10px; border-radius: 10px; font-size: 11px; "
            f"font-weight: 600; color: #0E111A; background-color: {color};"
        )

    # ─────────────────────────
    # Demo veri (geçici)
    # ─────────────────────────
    def _load_demo_data(self):
        """
        Sadece tasarımı görmek için demo veri.
        Gerçek kullanımda bu fonksiyonu kaldırıp
        dışarıdan set_license_data() çağırırsın.
        """
        demo = {
            "license_key": "OS-1234-5678-ABCD",
            "license_email": "kullanici@domain.com",
            "status": "active",
            "license_issued_at": "01.01.2025",
            "license_expires_at": "01.01.2026",
            "last_verified_at": "10.12.2025 03:12",
            "plan_name": "OrderScout PRO",
            "plan_code": "pro",
            "billing_cycle": "Yıllık",
            "subscription_id": "sub_9f23jk2",
            "next_billing_at": "01.01.2026",
            "provider": "Freemius",
            "device_id": "DEVICE-ABC-123",
            "last_error_message": "-",
        }
        self.set_license_data(demo)

    # ─────────────────────────
    # Buton eventleri (şimdilik stub)
    # ─────────────────────────
    def on_refresh_clicked(self):
        QMessageBox.information(
            self,
            "Lisans Doğrulama",
            "Bu buton, lisansını sunucu ile yeniden doğrulamak için kullanılacak.\n"
            "Backend entegrasyonunda buraya async doğrulama eklenecek."
        )

    def on_change_key_clicked(self):
        QMessageBox.information(
            self,
            "Lisans Anahtarını Değiştir",
            "Burada yeni lisans anahtarı girebileceğin bir pencere açacağız.\n"
            "Şimdilik sadece tasarım odaklı bir ekran."
        )

    def on_deactivate_clicked(self):
        reply = QMessageBox.question(
            self,
            "Bu Cihazı Lisanssız Bırak",
            "Bu cihazdaki lisans bağlantısını kaldırmak istediğinden emin misin?\n"
            "Bu işlemden sonra OrderScout'u kullanmak için tekrar lisans girmen gerekecek.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            QMessageBox.information(
                self,
                "Lisans Kaldırma",
                "Gerçek kullanımda burada DB'den lisans bilgileri silinecek.\n"
                "Şimdilik sadece tasarım amaçlı bir aksiyon."
            )


# ─────────────────────────────────────────
# 🔘 Toolbar Butonu
# ─────────────────────────────────────────
class LicenseManagerButton:
    """
    Toolbar üzerinde 'Lisans Yönetimi' butonunu temsil eder.
    CompanyManagerButton ile aynı mantıkta.
    """

    def __init__(self, parent=None):
        self.parent = parent

    def create_action(self):
        icon_path = os.path.join(MEDIA_ROOT, "license_manager.png")

        action = QAction(QIcon(icon_path), "Lisans Yönetimi", self.parent)
        action.setToolTip("OrderScout lisansını görüntüle ve yönet")
        action.setIconText("Lisans")
        action.setIconVisibleInMenu(True)
        action.setData("license_manager")
        action.setEnabled(True)
        action.setCheckable(False)

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(32, 32))

        action.triggered.connect(self.open_license_manage_dialog)
        return action

    def open_license_manage_dialog(self):
        dlg = LicenseManagerDialog(self.parent)
        dlg.exec()
