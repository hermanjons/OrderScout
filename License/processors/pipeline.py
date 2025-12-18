# License/processors/pipeline.py
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result
from License.api.license_api import FreemiusLicenseApi
from License.models import LocalLicenseState, LicenseStatus, LicenseActionLog


from datetime import timedelta


# License/processors/pipeline.py içine ekle

def deactivate_current_license() -> Result:
    engine = get_engine("orders.db")

    try:
        api = FreemiusLicenseApi()
    except Exception as e:
        return Result.fail(message="Freemius ayarları eksik veya hatalı.", error=e)

    with Session(engine) as session:
        device_id = get_device_id()
        state = session.exec(
            select(LocalLicenseState).where(LocalLicenseState.device_id == device_id)
        ).first()

        if not state or not state.install_id or not state.install_uuid or not state.license_key:
            return Result.fail(message="Bu cihazda kaldırılacak bir lisans bulunamadı.")

        res = api.deactivate(
            uid=state.install_uuid,
            license_key=state.license_key,
            install_id=int(state.install_id),
        )

        if not res.success:
            return res

        # başarılıysa local state temizle
        session.delete(state)
        session.commit()

        return Result.ok(message="Bu cihaz lisanssız bırakıldı.", close_dialog=False)




VERIFY_TTL_MINUTES = 30  # 30 dk'da bir Freemius'e git
GRACE_OFFLINE_DAYS = 7   # son doğrulama 7 gün içindeyse offline idare et (istersen)

def ensure_license_valid(*, force: bool = False) -> Result:
    """
    Hızlı kontrol + gerekirse validate_current_license().
    force=True -> direkt Freemius validate.
    """
    engine = get_engine("orders.db")

    with Session(engine) as session:
        device_id = get_device_id()
        state = session.exec(
            select(LocalLicenseState).where(LocalLicenseState.device_id == device_id)
        ).first()

        if not state or not state.license_key:
            return Result.fail(message="Lisans bulunamadı. Lütfen lisans anahtarını gir.")

        # DB’de zaten blok/iptal vs ise anında kes
        st = (str(state.status) or "").lower()
        if "blocked" in st or "revoked" in st:
            return Result.fail(message="Lisans engellenmiş görünüyor.")
        if "cancel" in st:
            return Result.fail(message="Lisans iptal edilmiş görünüyor.")
        if "expired" in st:
            return Result.fail(message="Lisans süresi dolmuş görünüyor.")

        now = datetime.utcnow()

        # Son doğrulama yoksa, zorunlu doğrula
        if force or not state.last_verified_at:
            return validate_current_license()

        # TTL dolmadıysa Freemius'e gitme (hızlı geç)
        if now - state.last_verified_at < timedelta(minutes=VERIFY_TTL_MINUTES):
            if state.last_verify_ok is False:
                # TTL içinde ama son verify başarısızsa bloklayabilirsin
                return Result.fail(message=state.last_error_message or "Lisans doğrulanamadı.")
            return Result.ok(message="Lisans geçerli (cache).", data=_state_to_ui_dict(state))

        # TTL doldu -> Freemius validate
        return validate_current_license()



# -------------------------
# Device ID / UID
# -------------------------
def get_device_id() -> str:
    raw = f"{uuid.getnode()}|{os.getlogin()}|{os.getcwd()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24].upper()


def get_or_create_uid(session: Session, device_id: str) -> str:
    state = session.exec(
        select(LocalLicenseState).where(LocalLicenseState.device_id == device_id)
    ).first()
    if state and state.install_uuid:
        return state.install_uuid
    return uuid.uuid4().hex  # 32 char


# -------------------------
# Freemius payload parse
# -------------------------
def _extract_install(act_json: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], Dict[str, Any]]:
    install = act_json.get("install") or act_json.get("data") or act_json
    install_id = install.get("id") or install.get("install_id")
    token = install.get("api_token") or install.get("install_api_token")

    try:
        install_id = int(install_id) if install_id is not None else None
    except Exception:
        install_id = None

    return install_id, token, install


def _status_from_validate(val_json: Dict[str, Any]) -> Tuple[LicenseStatus, str, Optional[datetime]]:
    lic = val_json.get("license") or val_json.get("data") or val_json

    is_cancelled = lic.get("is_cancelled")
    expiration = lic.get("expiration") or lic.get("expires_at")

    # İlk aşama: parse etmiyoruz, ileride ISO geliyorsa parse ekleriz
    expires_at = None

    if is_cancelled is True:
        return LicenseStatus.cancelled, "İptal", expires_at

    # expiration varsa büyük ihtimal “aktif / süreli”
    if expiration:
        return LicenseStatus.active, "Aktif", expires_at

    return LicenseStatus.active, "Aktif", expires_at


def _state_to_ui_dict(state: LocalLicenseState) -> Dict[str, Any]:
    def dt(x):
        return x.strftime("%d.%m.%Y %H:%M") if x else "-"

    return {
        "license_key": state.license_key,
        "license_email": state.license_email or "-",
        "status": str(state.status),
        "status_label": state.status_label or str(state.status),
        "license_issued_at": dt(state.issued_at),
        "license_expires_at": dt(state.expires_at),
        "last_verified_at": dt(state.last_verified_at),
        "plan_name": state.plan_name or "-",
        "plan_code": state.plan_code or "-",
        "billing_cycle": state.billing_cycle or "-",
        "subscription_id": str(state.freemius_subscription_id) if state.freemius_subscription_id else "-",
        "next_billing_at": "-",
        "provider": "Freemius",
        "device_id": state.device_id,
        "last_error_message": state.last_error_message or "-",
    }


# -------------------------
# Pipelines
# -------------------------
def activate_and_validate_license(*, license_key: str, license_email: Optional[str] = None) -> Result:
    """
    Kullanıcı lisans anahtarı girince:
    activate -> validate -> DB upsert -> UI dict döndür
    """
    engine = get_engine("orders.db")

    try:
        api = FreemiusLicenseApi()
    except Exception as e:
        return Result.fail(message="Freemius ayarları eksik veya hatalı.", error=e)

    with Session(engine) as session:
        device_id = get_device_id()
        uid = get_or_create_uid(session, device_id)

        log = LicenseActionLog(
            action="activate",
            device_id=device_id,
            license_key=license_key,
            ok=False,
            request_json={"uid": uid},
        )
        session.add(log)
        session.commit()

        act_res = api.activate(uid=uid, license_key=license_key)
        if not act_res.success:
            log.ok = False
            log.error_message = act_res.message
            log.response_json = act_res.data
            session.add(log); session.commit()
            return act_res

        act_json = (act_res.data or {}).get("json") or {}
        install_id, install_token, _ = _extract_install(act_json)

        if not install_id:
            msg = "Aktivasyon başarılı görünüyor ama install_id alınamadı."
            log.ok = False
            log.error_message = msg
            log.response_json = {"activate_json": act_json}
            session.add(log); session.commit()
            return Result.fail(message=msg)

        val_res = api.validate(uid=uid, license_key=license_key, install_id=install_id)
        if not val_res.success:
            log.ok = False
            log.error_message = val_res.message
            log.response_json = {"activate_json": act_json, "validate": val_res.data}
            session.add(log); session.commit()
            return val_res

        val_json = (val_res.data or {}).get("json") or {}
        status, status_label, expires_at = _status_from_validate(val_json)

        state = session.exec(
            select(LocalLicenseState).where(LocalLicenseState.device_id == device_id)
        ).first()

        if not state:
            state = LocalLicenseState(device_id=device_id, license_key=license_key)

        state.license_key = license_key
        state.license_email = license_email
        state.install_uuid = uid
        state.install_id = install_id
        state.install_api_token = install_token
        state.status = status
        state.status_label = status_label
        state.expires_at = expires_at
        state.last_verified_at = datetime.utcnow()
        state.last_verify_ok = True
        state.last_error_message = None
        state.raw_install_json = act_json
        state.raw_license_json = val_json
        state.updated_at = datetime.utcnow()

        session.add(state)

        log.ok = True
        log.response_json = {"activate": act_json, "validate": val_json}
        session.add(log)
        session.commit()

        return Result.ok(message="Lisans doğrulandı ve kaydedildi.", data=_state_to_ui_dict(state))


def validate_current_license() -> Result:
    """
    Mevcut lisansı Freemius üzerinden yeniden doğrular.
    """
    engine = get_engine("orders.db")

    try:
        api = FreemiusLicenseApi()
    except Exception as e:
        return Result.fail(message="Freemius ayarları eksik veya hatalı.", error=e)

    with Session(engine) as session:
        device_id = get_device_id()

        state = session.exec(
            select(LocalLicenseState).where(LocalLicenseState.device_id == device_id)
        ).first()

        if not state or not state.install_id or not state.install_uuid or not state.license_key:
            return Result.fail(message="Bu cihazda kayıtlı lisans bulunamadı.")

        val_res = api.validate(
            uid=state.install_uuid,
            license_key=state.license_key,
            install_id=int(state.install_id),
        )

        state.last_verified_at = datetime.utcnow()

        if not val_res.success:
            state.last_verify_ok = False
            state.last_error_message = val_res.message
            session.add(state); session.commit()
            return val_res

        val_json = (val_res.data or {}).get("json") or {}
        status, status_label, expires_at = _status_from_validate(val_json)

        state.status = status
        state.status_label = status_label
        state.expires_at = expires_at
        state.last_verify_ok = True
        state.last_error_message = None
        state.raw_license_json = val_json
        state.updated_at = datetime.utcnow()

        session.add(state); session.commit()
        return Result.ok(message="Lisans güncellendi.", data=_state_to_ui_dict(state))
