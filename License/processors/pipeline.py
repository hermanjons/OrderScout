from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

from sqlmodel import Session, select

import settings
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result

from License.api.license_api import FreemiusLicenseApi
from License.models import (
    LocalLicenseState,
    LicenseStatus,
    Provider,
    LicenseActionLog,
)

import json
import urllib.request
import urllib.error

from License.constants import LICENSE_BACKEND_BASE_URL


# ======================================================
# CONFIG
# ======================================================
VERIFY_TTL_MINUTES = 30


# ======================================================
# DEVICE / UID (STABLE)
# ======================================================
def get_device_id() -> str:
    raw = f"{uuid.getnode()}|{os.getlogin()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_uid32(device_id: str) -> str:
    salt = getattr(settings, "LICENSE_UID_SALT", "orderscout")
    return hashlib.md5(f"{device_id}|{salt}".encode()).hexdigest()  # 32 char


# ======================================================
# HELPERS
# ======================================================
def _find_state(session: Session, device_id: str) -> Optional[LocalLicenseState]:
    return session.exec(
        select(LocalLicenseState).where(
            LocalLicenseState.provider == Provider.freemius,
            LocalLicenseState.device_id == device_id,
        )
    ).first()


def _extract_install(act_json: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    install = act_json.get("install") or act_json.get("data") or act_json or {}
    install_id = install.get("id") or install.get("install_id")
    token = install.get("api_token") or install.get("install_api_token")

    try:
        install_id = int(install_id) if install_id is not None else None
    except Exception:
        install_id = None

    return install_id, token


def _status_from_validate(val_json: Dict[str, Any]) -> Tuple[LicenseStatus, str]:
    lic = val_json.get("license") or val_json.get("data") or val_json or {}

    if lic.get("is_cancelled"):
        return LicenseStatus.cancelled, "İptal"

    expiration = lic.get("expiration") or lic.get("expires_at")
    if expiration:
        return LicenseStatus.active, "Aktif"

    return LicenseStatus.active, "Aktif"


def _ui_dict(state: LocalLicenseState) -> Dict[str, Any]:
    def dt(x): return x.strftime("%d.%m.%Y %H:%M") if x else "-"

    return {
        "license_key": state.license_key,
        "status": state.status,
        "status_label": state.status_label,
        "last_verified_at": dt(state.last_verified_at),
        "expires_at": dt(state.expires_at),
        "plan_name": state.plan_name,
        "plan_code": state.plan_code,
        "billing_cycle": state.billing_cycle,
        "subscription_id": state.freemius_subscription_id,
        "provider": "Freemius",
        "device_id": state.device_id,
        "last_error_message": state.last_error_message,
    }


# ======================================================
# CORE: ENSURE (decorator için)
# ======================================================
def ensure_license_valid(force: bool = False) -> Result:
    engine = get_engine("orders.db")

    with Session(engine) as session:
        state = _find_state(session, get_device_id())

        if not state:
            return Result.fail("Bu cihazda lisans yok.")

        if not force and state.last_verified_at:
            if datetime.utcnow() - state.last_verified_at < timedelta(minutes=VERIFY_TTL_MINUTES):
                if state.last_verify_ok:
                    return Result.ok("Lisans geçerli (cache).", data=_ui_dict(state))

        return validate_current_license()


# ======================================================
# ACTIVATE + VALIDATE (TEK GİRİŞ NOKTASI)
# ======================================================
def activate_and_validate_license(*, license_key: str, license_email: Optional[str] = None) -> Result:
    license_key = (license_key or "").strip()
    if not license_key:
        return Result.fail("Lisans anahtarı boş olamaz.")

    engine = get_engine("orders.db")
    device_id = get_device_id()
    uid32 = get_uid32(device_id)

    try:
        api = FreemiusLicenseApi()
    except Exception as e:
        return Result.fail("Freemius ayarları eksik.", error=e)

    with Session(engine) as session:
        state = _find_state(session, device_id)

        # ✅ Aynı cihaz + aynı lisans → ACTIVATE YOK, SADECE VALIDATE
        if state and state.license_key == license_key and state.install_id and state.install_uuid:
            return validate_current_license()

        # ❌ Aynı cihazda başka lisans varken yeni key
        if state and state.license_key != license_key:
            return Result.fail(
                "Bu cihazda başka bir lisans aktif.\n"
                "Yeni lisans girmeden önce mevcut lisansı kaldırmalısın."
            )

        # ---------- ACTIVATE ----------
        log = LicenseActionLog(
            action="activate",
            provider=Provider.freemius,
            device_id=device_id,
            license_key=license_key,
            ok=False,
            request_json={"uid": uid32},
        )
        session.add(log)
        session.commit()

        act_res = api.activate(uid=uid32, license_key=license_key)
        if not act_res.success:
            log.error_message = act_res.message
            log.response_json = act_res.data
            session.add(log)
            session.commit()
            return act_res

        act_json = (act_res.data or {}).get("json") or {}
        install_id, install_token = _extract_install(act_json)

        if not install_id:
            return Result.fail(
                "Aktivasyon başarılı görünüyor ancak install_id alınamadı.\n"
                "Freemius panelinden bu cihazı kaldırıp tekrar deneyin."
            )

        # ---------- VALIDATE ----------
        val_res = api.validate(
            uid=uid32,
            license_key=license_key,
            install_id=int(install_id),
        )
        if not val_res.success:
            return val_res

        val_json = (val_res.data or {}).get("json") or {}
        status, status_label = _status_from_validate(val_json)

        # ---------- DB STATE (FULL) ----------
        state = LocalLicenseState(
            provider=Provider.freemius,
            device_id=device_id,
            license_key=license_key,
            license_email=license_email,
            freemius_product_id=int(getattr(settings, "FREEMIUS_PRODUCT_ID", 0) or 0) or None,
            install_id=int(install_id),
            install_uuid=uid32,
            install_api_token=install_token,
            status=status,
            status_label=status_label,
            issued_at=datetime.utcnow(),
            last_verified_at=datetime.utcnow(),
            last_verify_ok=True,
            raw_install_json=act_json,
            raw_license_json=val_json,
            updated_at=datetime.utcnow(),
        )

        session.add(state)

        log.ok = True
        log.response_json = {"activate": act_json, "validate": val_json}
        session.add(log)

        session.commit()

        return Result.ok(
            "Lisans doğrulandı ve kaydedildi.",
            close_dialog=False,
            data=_ui_dict(state),
        )


# ======================================================
# VALIDATE ONLY
# ======================================================


def exchange_activation_code(*, code: str) -> Result:
    """
    Cloudflare Worker: /exchange endpointine code gönderir,
    license_key dönerse Result.ok(data={"license_key": ...})
    """
    code = (code or "").strip().upper()
    if not code:
        return Result.fail("Kod boş olamaz.")

    base = (LICENSE_BACKEND_BASE_URL or "").strip().rstrip("/")
    if not base:
        return Result.fail("LICENSE_BACKEND_BASE_URL tanımlı değil.")

    url = f"{base}/exchange"
    payload = json.dumps({"code": code}).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        # Worker JSON döner ama bazen text de olabilir
        try:
            err_raw = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_raw = str(e)
        return Result.fail(f"Exchange hatası ({e.code}): {err_raw[:250]}")
    except Exception as e:
        return Result.fail("Lisans sunucusuna bağlanılamadı.", error=e)

    try:
        j = json.loads(raw or "{}")
    except Exception:
        return Result.fail(f"Exchange yanıtı okunamadı: {raw[:250]}")

    if not j.get("ok"):
        return Result.fail(j.get("message") or "Exchange başarısız.")

    license_key = (j.get("license_key") or "").strip()
    if not license_key:
        return Result.fail("Sunucu lisans anahtarını döndürmedi.")

    return Result.ok("Kod çözüldü.", data={"license_key": license_key, "email": j.get("email")})




def validate_current_license() -> Result:
    engine = get_engine("orders.db")

    try:
        api = FreemiusLicenseApi()
    except Exception as e:
        return Result.fail("Freemius ayarları eksik.", error=e)

    with Session(engine) as session:
        state = _find_state(session, get_device_id())
        if not state:
            return Result.fail("Bu cihazda lisans yok.")

        if not state.install_id or not state.install_uuid:
            return Result.fail("Bu cihazda install bilgisi eksik.")

        val_res = api.validate(
            uid=state.install_uuid,
            license_key=state.license_key,
            install_id=int(state.install_id),
        )

        state.last_verified_at = datetime.utcnow()

        if not val_res.success:
            state.last_verify_ok = False
            state.last_error_message = val_res.message
            session.add(state)
            session.commit()
            return val_res

        val_json = (val_res.data or {}).get("json") or {}
        status, status_label = _status_from_validate(val_json)

        state.status = status
        state.status_label = status_label
        state.last_verify_ok = True
        state.last_error_message = None
        state.raw_license_json = val_json
        state.updated_at = datetime.utcnow()

        session.add(state)
        session.commit()

        return Result.ok("Lisans geçerli.", data=_ui_dict(state))


# ======================================================
# DEACTIVATE
# ======================================================
def deactivate_current_license() -> Result:
    engine = get_engine("orders.db")

    try:
        api = FreemiusLicenseApi()
    except Exception as e:
        return Result.fail("Freemius ayarları eksik.", error=e)

    with Session(engine) as session:
        state = _find_state(session, get_device_id())
        if not state:
            return Result.fail("Bu cihazda kaldırılacak lisans yok.")

        if state.install_id and state.install_uuid:
            res = api.deactivate(
                uid=state.install_uuid,
                license_key=state.license_key,
                install_id=int(state.install_id),
            )
            if not res.success:
                return res

        session.delete(state)
        session.commit()

        return Result.ok("Lisans bu cihazdan kaldırıldı.", close_dialog=False)
