from __future__ import annotations

import os
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGroupBox, QGridLayout, QWidget,
    QMessageBox, QSizePolicy, QSpacerItem, QInputDialog
)
from PyQt6.QtGui import QIcon, QAction, QDesktopServices
from PyQt6.QtCore import QSize, Qt, QUrl

from settings import MEDIA_ROOT
from License.processors.pipeline import (
    activate_and_validate_license,
    validate_current_license,
    deactivate_current_license,
)

from License.constants import CHECKOUT_LINK

try:
    from Feedback.processors.pipeline import map_error_to_message
except Exception:
    map_error_to_message = None


def _err_text(res) -> str:
    if map_error_to_message and getattr(res, "error", None):
        try:
            return map_error_to_message(res.error)
        except Exception:
            pass
    return getattr(res, "message", None) or "Bilinmeyen hata"


class LicenseManagerDialog(QDialog):
    """
    - Lisans YOK:
        ✅ Lisans Gir & Doğrula
        ✅ Satın Al
        ❌ Lisansı Kaldır

    - Lisans VAR:
        ✅ Lisansı Kaldır
        ❌ Lisans Gir & Doğrula
        ❌ Satın Al
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Lisans - OrderScout")
        self.resize(560, 340)

        self._setup_styles()
        self._init_ui()
        self._refresh_ui_silent()

    def _setup_styles(self):
        self.setStyleSheet("""
        QDialog { background-color: #101018; color: #F5F5F5; }
        QLabel { color: #F5F5F5; }
        QGroupBox {
            border: 1px solid #26293A;
            border-radius: 10px;
            margin-top: 16px;
            padding: 12px;
            color: #C5C7D5;
            font-weight: bold;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QPushButton {
            border-radius: 8px; padding: 8px 14px;
            background-color: #2F80ED; color: white; border: none; font-weight: 500;
        }
        QPushButton:hover { background-color: #337FE0; }

        QPushButton#secondaryButton {
            background-color: #1F2233; border: 1px solid #34384C;
        }
        QPushButton#secondaryButton:hover { background-color: #25293B; }

        QPushButton#dangerButton { background-color: #EB5757; }
        QPushButton#dangerButton:hover { background-color: #D94444; }

        QFrame#card {
            background-color: #181B2A;
            border-radius: 14px;
            border: 1px solid #26293A;
        }
        QLabel#titleLabel { font-size: 16px; font-weight: 650; }
        QLabel#subtitleLabel { font-size: 12px; color: #A0A4B8; }
        QLabel#valueLabel { font-weight: 600; color: #E6E8F2; }
        QLabel#hintLabel { font-size: 11px; color: #9EA2B8; }
        QLabel#statusBadge {
            padding: 4px 10px; border-radius: 10px;
            font-size: 11px; font-weight: 700; color: #0E111A;
            background-color: #4F4F4F;
        }
        """)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("card")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 12)

        left = QVBoxLayout()
        self.lbl_title = QLabel("Lisans Durumu")
        self.lbl_title.setObjectName("titleLabel")
        self.lbl_subtitle = QLabel("Satın aldıysan e-postana gelen lisans anahtarını buraya gir.")
        self.lbl_subtitle.setObjectName("subtitleLabel")
        self.lbl_subtitle.setWordWrap(True)
        left.addWidget(self.lbl_title)
        left.addWidget(self.lbl_subtitle)

        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_status_badge = QLabel("LİSANS YOK")
        self.lbl_status_badge.setObjectName("statusBadge")
        self.lbl_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.lbl_status_badge)

        hl.addLayout(left)
        hl.addStretch()
        hl.addLayout(right)
        root.addWidget(header)

        box = QGroupBox("Bilgiler")
        gl = QGridLayout(box)
        gl.setHorizontalSpacing(12)
        gl.setVerticalSpacing(6)

        r = 0
        gl.addWidget(QLabel("Lisans Anahtarı:"), r, 0)
        self.lbl_license_key = QLabel("-")
        self.lbl_license_key.setObjectName("valueLabel")
        self.lbl_license_key.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        gl.addWidget(self.lbl_license_key, r, 1); r += 1

        gl.addWidget(QLabel("Durum:"), r, 0)
        self.lbl_status = QLabel("-")
        self.lbl_status.setObjectName("valueLabel")
        gl.addWidget(self.lbl_status, r, 1); r += 1

        gl.addWidget(QLabel("Son Doğrulama:"), r, 0)
        self.lbl_last_verified = QLabel("-")
        self.lbl_last_verified.setObjectName("valueLabel")
        gl.addWidget(self.lbl_last_verified, r, 1); r += 1

        gl.addWidget(QLabel("Device ID:"), r, 0)
        self.lbl_device_id = QLabel("-")
        self.lbl_device_id.setObjectName("valueLabel")
        self.lbl_device_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        gl.addWidget(self.lbl_device_id, r, 1); r += 1

        self.lbl_hint = QLabel("Not: İnternet yoksa doğrulama başarısız olabilir.")
        self.lbl_hint.setObjectName("hintLabel")
        self.lbl_hint.setWordWrap(True)
        gl.addItem(QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum), r, 0); r += 1
        gl.addWidget(self.lbl_hint, r, 0, 1, 2)

        root.addWidget(box)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_enter_key = QPushButton("Lisans Gir & Doğrula")

        self.btn_buy = QPushButton("Satın Al")
        self.btn_buy.setObjectName("secondaryButton")

        self.btn_deactivate = QPushButton("Lisansı Kaldır")
        self.btn_deactivate.setObjectName("dangerButton")

        self.btn_close = QPushButton("Kapat")
        self.btn_close.setObjectName("secondaryButton")

        self.btn_enter_key.clicked.connect(self.on_enter_key)
        self.btn_buy.clicked.connect(self.on_buy)
        self.btn_deactivate.clicked.connect(self.on_deactivate)
        self.btn_close.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_enter_key)
        btn_row.addWidget(self.btn_buy)
        btn_row.addWidget(self.btn_deactivate)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._apply_license_presence_ui(has_license=False)

    def _apply_license_presence_ui(self, *, has_license: bool):
        self.btn_enter_key.setVisible(not has_license)
        self.btn_buy.setVisible(not has_license)
        self.btn_deactivate.setVisible(has_license)

        self.btn_enter_key.setEnabled(not has_license)
        self.btn_buy.setEnabled(not has_license)
        self.btn_deactivate.setEnabled(has_license)

        if has_license:
            self.lbl_subtitle.setText("Bu cihazda lisans aktif. İstersen lisansı kaldırabilirsin.")
        else:
            self.lbl_subtitle.setText("Satın aldıysan e-postana gelen lisans anahtarını buraya gir.")

    def set_license_data(self, data: Dict[str, Any]):
        def get(k, d="-"):
            v = data.get(k, d)
            return d if v in (None, "") else v

        self.lbl_license_key.setText(str(get("license_key")))
        self.lbl_status.setText(str(get("status_label", get("status"))))
        self.lbl_last_verified.setText(str(get("last_verified_at")))
        self.lbl_device_id.setText(str(get("device_id")))
        self._update_status_badge(str(get("status", "none")))

        status = str(get("status", "none")).lower()
        has_license = ("none" not in status) and (get("license_key") != "-")
        self._apply_license_presence_ui(has_license=bool(has_license))

    def _clear_license_ui(self):
        self.lbl_license_key.setText("-")
        self.lbl_status.setText("-")
        self.lbl_last_verified.setText("-")
        self._update_status_badge("none")
        self._apply_license_presence_ui(has_license=False)

    def _update_status_badge(self, status: str):
        s = (status or "").lower()
        if "trial" in s:
            text, color = "TRIAL", "#F2C94C"
        elif "active" in s or "valid" in s:
            text, color = "AKTİF", "#27AE60"
        elif "expired" in s:
            text, color = "SÜRESİ DOLMUŞ", "#EB5757"
        elif "blocked" in s or "revoked" in s:
            text, color = "ENGELLİ", "#9B51E0"
        elif "cancel" in s:
            text, color = "İPTAL", "#EB5757"
        else:
            text, color = "LİSANS YOK", "#4F4F4F"

        self.lbl_status_badge.setText(text)
        self.lbl_status_badge.setStyleSheet(
            f"padding: 4px 10px; border-radius: 10px; font-size: 11px; "
            f"font-weight: 700; color: #0E111A; background-color: {color};"
        )

    def _refresh_ui_silent(self):
        res = validate_current_license()
        if getattr(res, "success", False):
            self.set_license_data(res.data)
        else:
            self._clear_license_ui()

    def on_enter_key(self):
        key, ok = QInputDialog.getText(self, "Lisans Anahtarı", "E-postana gelen lisans anahtarını gir:")
        if not ok:
            return
        key = (key or "").strip()
        if not key:
            QMessageBox.warning(self, "Hata", "Lisans anahtarı boş olamaz.")
            return

        res = activate_and_validate_license(license_key=key)
        if not getattr(res, "success", False):
            QMessageBox.critical(self, "Lisans Hatası", _err_text(res))
            return

        self.set_license_data(res.data)
        QMessageBox.information(self, "Başarılı", "Lisans doğrulandı ve kaydedildi.")

    def on_buy(self):
        link = (CHECKOUT_LINK or "").strip()
        if not link:
            QMessageBox.warning(self, "Satın Al", "Checkout link tanımlı değil (CHECKOUT_LINK boş).")
            return

        ok = QDesktopServices.openUrl(QUrl(link))
        if not ok:
            QMessageBox.warning(self, "Satın Al", "Link açılamadı. Tarayıcı engelliyor olabilir.")

    def on_deactivate(self):
        reply = QMessageBox.question(
            self,
            "Lisansı Kaldır",
            "Bu cihazın lisansını kaldırmak istiyor musun?\n\n"
            "Bu işlem Freemius tarafında cihaz kotasını boşaltır.\n"
            "Sonrasında tekrar lisans girmen gerekir.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        res = deactivate_current_license()
        if not getattr(res, "success", False):
            QMessageBox.critical(self, "Kaldırma Hatası", _err_text(res))
            return

        self._clear_license_ui()
        QMessageBox.information(self, "Başarılı", "Lisans kaldırıldı. Bu cihaz artık lisanssız.")


class LicenseManagerButton:
    def __init__(self, parent=None):
        self.parent = parent

    def create_action(self):
        icon_path = os.path.join(MEDIA_ROOT, "license_manager.png")
        action = QAction(QIcon(icon_path), "Lisans", self.parent)
        action.setToolTip("Lisansı yönet")
        action.setData("license_manager")

        if self.parent and hasattr(self.parent, "toolBar"):
            self.parent.toolBar.setIconSize(QSize(32, 32))

        action.triggered.connect(self.open_dialog)
        return action

    def open_dialog(self):
        dlg = LicenseManagerDialog(self.parent)
        dlg.exec()
