from __future__ import annotations

import os
import json
import urllib.request
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

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
    exchange_activation_code,      # ✅
    get_device_id,                # ✅ pipeline içinden alıyoruz
)

from License.constants import CHECKOUT_LINK, LICENSE_BACKEND_BASE_URL

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


# ------------------------------------------------------
# Worker helper: /start -> sid al
# ------------------------------------------------------
def _worker_start_checkout_session(*, device_id: str) -> Dict[str, Any]:
    """
    Worker'a POST /start atar, {ok:true, sid:"..."} döner.
    requests kullanmıyoruz; urllib ile dependency yok.
    """
    base = (LICENSE_BACKEND_BASE_URL or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "message": "LICENSE_BACKEND_BASE_URL boş."}

    url = f"{base}/start"
    payload = json.dumps({"device_id": device_id}).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            try:
                j = json.loads(raw)
            except Exception:
                return {"ok": False, "message": f"Worker JSON parse error: {raw[:200]}"}
            return j
    except Exception as e:
        return {"ok": False, "message": f"Worker /start hata: {e}"}


def _append_query_param(url: str, **params) -> str:
    """
    URL'ye query param ekler, var olanları korur.
    """
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    for k, v in params.items():
        if v is not None:
            q[str(k)] = str(v)
    new_query = urlencode(q, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))


class LicenseManagerDialog(QDialog):
    """
    Duruma göre butonlar:

    - Lisans YOK:
        ✅ Lisans Gir & Doğrula
        ✅ Satın Al (SID ile açar)
        ✅ Satın Aldım (Kod Gir)
        ❌ Lisansı Kaldır

    - Lisans VAR:
        ✅ Lisansı Kaldır
        ❌ Lisans Gir & Doğrula
        ❌ Satın Al
        ❌ Satın Aldım (Kod Gir)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Lisans - OrderScout")
        self.resize(580, 360)

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
        self.lbl_subtitle = QLabel("Lisans anahtarını girip doğrulayabilir ya da satın alabilirsin.")
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
        gl.addWidget(self.lbl_license_key, r, 1)
        r += 1

        gl.addWidget(QLabel("Durum:"), r, 0)
        self.lbl_status = QLabel("-")
        self.lbl_status.setObjectName("valueLabel")
        gl.addWidget(self.lbl_status, r, 1)
        r += 1

        gl.addWidget(QLabel("Son Doğrulama:"), r, 0)
        self.lbl_last_verified = QLabel("-")
        self.lbl_last_verified.setObjectName("valueLabel")
        gl.addWidget(self.lbl_last_verified, r, 1)
        r += 1

        gl.addWidget(QLabel("Device ID:"), r, 0)
        self.lbl_device_id = QLabel("-")
        self.lbl_device_id.setObjectName("valueLabel")
        self.lbl_device_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        gl.addWidget(self.lbl_device_id, r, 1)
        r += 1

        self.lbl_hint = QLabel("Not: Satın alma sonrası kodu girerek lisansı otomatik bağlayabilirsin.")
        self.lbl_hint.setObjectName("hintLabel")
        self.lbl_hint.setWordWrap(True)
        gl.addItem(QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum), r, 0)
        r += 1
        gl.addWidget(self.lbl_hint, r, 0, 1, 2)

        root.addWidget(box)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_enter_key = QPushButton("Lisans Gir & Doğrula")

        self.btn_buy = QPushButton("Satın Al")
        self.btn_buy.setObjectName("secondaryButton")

        self.btn_i_bought = QPushButton("Satın Aldım (Kod Gir)")
        self.btn_i_bought.setObjectName("secondaryButton")

        self.btn_deactivate = QPushButton("Lisansı Kaldır")
        self.btn_deactivate.setObjectName("dangerButton")

        self.btn_close = QPushButton("Kapat")
        self.btn_close.setObjectName("secondaryButton")

        self.btn_enter_key.clicked.connect(self.on_enter_key)
        self.btn_buy.clicked.connect(self.on_buy)                 # ✅ SID’li açacak
        self.btn_i_bought.clicked.connect(self.on_i_bought)
        self.btn_deactivate.clicked.connect(self.on_deactivate)
        self.btn_close.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_enter_key)
        btn_row.addWidget(self.btn_buy)
        btn_row.addWidget(self.btn_i_bought)
        btn_row.addWidget(self.btn_deactivate)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._apply_license_presence_ui(has_license=False)

    def _apply_license_presence_ui(self, *, has_license: bool):
        self.btn_enter_key.setVisible(not has_license)
        self.btn_buy.setVisible(not has_license)
        self.btn_i_bought.setVisible(not has_license)
        self.btn_deactivate.setVisible(has_license)

        self.btn_enter_key.setEnabled(not has_license)
        self.btn_buy.setEnabled(not has_license)
        self.btn_i_bought.setEnabled(not has_license)
        self.btn_deactivate.setEnabled(has_license)

        if has_license:
            self.lbl_subtitle.setText("Bu cihazda lisans aktif. İstersen lisansı kaldırabilirsin.")
        else:
            self.lbl_subtitle.setText("Lisans anahtarını girip doğrulayabilir ya da satın alabilirsin.")

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

    # -------------------------
    # Actions
    # -------------------------
    def on_enter_key(self):
        key, ok = QInputDialog.getText(self, "Lisans Anahtarı", "Lisans anahtarını gir:")
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
        """
        ✅ Yeni akış:
        1) device_id al
        2) Worker /start -> sid al
        3) Checkout linkini ?sid=... ekleyip aç
        """
        base_link = (CHECKOUT_LINK or "").strip()
        if not base_link:
            QMessageBox.warning(self, "Satın Al", "Checkout link tanımlı değil (CHECKOUT_LINK boş).")
            return

        device_id = get_device_id()
        start_res = _worker_start_checkout_session(device_id=device_id)

        if not start_res.get("ok"):
            QMessageBox.critical(self, "Satın Al", start_res.get("message", "SID alınamadı."))
            return

        sid = (start_res.get("sid") or "").strip()
        if not sid:
            QMessageBox.critical(self, "Satın Al", "Worker SID döndürmedi.")
            return

        # checkout linkine sid ekle
        link_with_sid = _append_query_param(base_link, sid=sid)

        ok = QDesktopServices.openUrl(QUrl(link_with_sid))
        if not ok:
            QMessageBox.warning(self, "Satın Al", "Link açılamadı. Tarayıcı engelliyor olabilir.")

    def on_i_bought(self):
        code, ok = QInputDialog.getText(
            self,
            "Satın Aldım - Aktivasyon Kodu",
            "Satın alma sonrası ekranda çıkan kodu gir:",
        )
        if not ok:
            return

        code = (code or "").strip().upper()
        if not code:
            QMessageBox.warning(self, "Hata", "Kod boş olamaz.")
            return

        # 1) Worker'dan license_key al (device_id ile bağlı olmalı)
        res = exchange_activation_code(code=code)  # sen bunu pipeline içinde device_id ile güncelleyeceksin
        if not getattr(res, "success", False):
            QMessageBox.critical(self, "Kod Hatası", _err_text(res))
            return

        license_key = (res.data or {}).get("license_key")
        if not license_key:
            QMessageBox.critical(self, "Kod Hatası", "Sunucu lisans anahtarını döndürmedi.")
            return

        # 2) license_key ile cihazda activate+validate (DB'ye yazacak)
        res2 = activate_and_validate_license(license_key=str(license_key))
        if not getattr(res2, "success", False):
            QMessageBox.critical(self, "Lisans Hatası", _err_text(res2))
            return

        self.set_license_data(res2.data)
        QMessageBox.information(self, "Başarılı", "Lisans otomatik bağlandı ve aktive edildi.")

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
