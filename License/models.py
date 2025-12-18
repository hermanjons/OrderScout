# License/models.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import JSON, Index, UniqueConstraint


# ─────────────────────────────────────────
# Enums
# ─────────────────────────────────────────
class LicenseStatus(str, Enum):
    none = "none"          # lisans yok
    trial = "trial"        # trial
    active = "active"      # aktif/geçerli
    expired = "expired"    # süresi dolmuş
    cancelled = "cancelled"  # is_cancelled = true
    blocked = "blocked"    # revoked/blocked vs.
    error = "error"        # doğrulama hatası


class Provider(str, Enum):
    freemius = "freemius"


# ─────────────────────────────────────────
# Core: Bu cihazdaki lisans "state" tablosu
# ─────────────────────────────────────────
class LocalLicenseState(SQLModel, table=True):
    """
    Bu tablo, OrderScout'un çalıştığı cihazda lisansın güncel durumunu tutar.
    99% kullanımda tek satır olacak (singleton mantığı).
    """

    __tablename__ = "license_state"

    id: Optional[int] = Field(default=None, primary_key=True)

    provider: Provider = Field(default=Provider.freemius, index=True)

    # Kullanıcının girdiği anahtar:
    license_key: str = Field(index=True, max_length=128)
    license_email: Optional[str] = Field(default=None, index=True, max_length=255)

    # Freemius product scope için:
    freemius_product_id: Optional[int] = Field(default=None, index=True)

    # Freemius License ID (varsa API'den çekince dolacak)
    freemius_license_id: Optional[int] = Field(default=None, index=True)

    # Plan / Pricing / Subscription snapshot (Freemius'tan dönen verilere göre doldurulur)
    freemius_plan_id: Optional[int] = Field(default=None, index=True)
    plan_name: Optional[str] = Field(default=None, max_length=128)
    plan_code: Optional[str] = Field(default=None, index=True, max_length=64)

    freemius_subscription_id: Optional[int] = Field(default=None, index=True)
    billing_cycle: Optional[str] = Field(default=None, max_length=64)  # Aylık/Yıllık vs (UI string)

    # Install bilgileri: aktivasyon cevabından gelir:
    install_id: Optional[int] = Field(default=None, index=True)
    install_uuid: Optional[str] = Field(default=None, index=True, max_length=64)  # uid={uuid} (32-char öneriliyor)
    install_api_token: Optional[str] = Field(default=None, max_length=255)

    # Cihaz fingerprint / device id (senin ürettiğin stabil id)
    device_id: str = Field(index=True, max_length=128)

    # Durum
    status: LicenseStatus = Field(default=LicenseStatus.none, index=True)
    status_label: Optional[str] = Field(default=None, max_length=64)  # UI için

    # Freemius validasyonundan gelen kritik alanlar:
    expires_at: Optional[datetime] = Field(default=None, index=True)      # expiration
    is_cancelled: Optional[bool] = Field(default=None, index=True)

    issued_at: Optional[datetime] = Field(default=None, index=True)

    # Son doğrulama takibi
    last_verified_at: Optional[datetime] = Field(default=None, index=True)
    last_verify_ok: Optional[bool] = Field(default=None, index=True)

    last_error_code: Optional[str] = Field(default=None, max_length=64)
    last_error_message: Optional[str] = Field(default=None)

    # Freemius'tan gelen "tam obje snapshot" (ileride alan eklenirse DB migrate derdi olmadan saklarsın)
    raw_license_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    raw_install_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    raw_subscription_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (
        # Bu cihazda aynı provider + device_id için tek state mantığı:
        UniqueConstraint("provider", "device_id", name="uq_license_state_provider_device"),
        Index("ix_license_state_license_key_device", "license_key", "device_id"),
    )


# ─────────────────────────────────────────
# Webhook/Event Log: audit & debug için
# ─────────────────────────────────────────
class FreemiusEventLog(SQLModel, table=True):
    """
    Webhook veya API event fetch ile gelen payloadları saklarız.
    - Debug: 'neden lisans düştü?' sorusunu tek yerden görürsün.
    - Replay: işlenemeyen event'leri tekrar işlemek için.
    """

    __tablename__ = "freemius_event_log"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Freemius event id (dashboard Events Log'daki ID; API'den de çekiliyor)
    freemius_event_id: Optional[int] = Field(default=None, index=True)

    # Örn: license.activated, subscription.canceled, install.deactivated vs.
    event_type: str = Field(index=True, max_length=128)

    # Hangi product'a ait?
    freemius_product_id: Optional[int] = Field(default=None, index=True)

    # Korelasyon alanları (payload içinden mümkün oldukça doldur)
    freemius_license_id: Optional[int] = Field(default=None, index=True)
    freemius_subscription_id: Optional[int] = Field(default=None, index=True)
    install_id: Optional[int] = Field(default=None, index=True)

    # Güvenlik: webhook signature kontrolü
    signature_header: Optional[str] = Field(default=None, max_length=128)
    signature_valid: Optional[bool] = Field(default=None, index=True)

    # Ham payload
    payload_json: Dict[str, Any] = Field(sa_column=Column(JSON))

    # İşleme durumu
    processed_at: Optional[datetime] = Field(default=None, index=True)
    process_error: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_freemius_event_type_created", "event_type", "created_at"),
    )


# ─────────────────────────────────────────
# Aktivasyon geçmişi (kullanıcı anahtar değiştirdi / cihazı lisanssız bıraktı vs)
# ─────────────────────────────────────────
class LicenseActionLog(SQLModel, table=True):
    """
    UI aksiyonlarını loglar:
    - 'Lisans Anahtarını Değiştir'
    - 'Bu Cihazı Lisanssız Bırak'
    - 'Şimdi Doğrula'
    """

    __tablename__ = "license_action_log"

    id: Optional[int] = Field(default=None, primary_key=True)

    action: str = Field(index=True, max_length=64)  # activate / deactivate / validate / change_key / refresh
    provider: Provider = Field(default=Provider.freemius, index=True)

    device_id: str = Field(index=True, max_length=128)
    license_key: Optional[str] = Field(default=None, index=True, max_length=128)

    ok: bool = Field(default=False, index=True)
    error_message: Optional[str] = Field(default=None)

    # İstek/cevap snapshot (debug kolaylığı)
    request_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    response_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
