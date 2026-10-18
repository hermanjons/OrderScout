from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel
from Core.db.models import SourceIdentityMixin


def _now_iso_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class LogisticsCargoProvider(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "logistics_cargo_provider"

    pk: Optional[int] = Field(default=None, primary_key=True)

    platform_id: Optional[int] = Field(default=None, foreign_key="marketplace.pk", index=True)
    platformCode: str = Field(index=True, max_length=32)
    cargoProviderCode: str = Field(index=True, max_length=64)
    cargoProviderName: str = Field(index=True, max_length=180)

    logoPath: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=1000)

    createdAt: str = Field(default_factory=_now_iso_text, index=True)
    updatedAt: str = Field(default_factory=_now_iso_text, index=True)

    __table_args__ = (
        UniqueConstraint(
            "platformCode",
            "cargoProviderCode",
            name="uq_logistics_cargo_provider_platform_code",
        ),
        Index(
            "ix_logistics_cargo_provider_platform_name",
            "platformCode",
            "cargoProviderName",
        ),
    )


class LogisticsCargoTariff(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "cargo_tariff"

    pk: Optional[int] = Field(default=None, primary_key=True)

    tariffKey: str = Field(index=True)
    name: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None

    cargo_provider_id: Optional[int] = Field(
        default=None,
        foreign_key="logistics_cargo_provider.pk",
        index=True,
    )
    platform: Optional[str] = Field(default="TRENDYOL", index=True)
    cargoProviderCode: Optional[str] = Field(default=None, index=True)
    cargoProviderName: Optional[str] = Field(default=None, index=True)

    minDesi: Optional[float] = Field(default=None)
    maxDesi: Optional[float] = Field(default=None)
    minSalePrice: Optional[float] = Field(default=None)
    maxSalePrice: Optional[float] = Field(default=None)
    amount: Optional[float] = Field(default=None)
    currency: Optional[str] = Field(default="TRY", index=True)
    isVatIncluded: bool = Field(default=True, index=True)
    vatRate: Optional[float] = Field(default=None)

    isActive: bool = Field(default=True, index=True)
    isDeleted: bool = Field(default=False, index=True)
    createdAt: str = Field(default_factory=_now_iso_text, index=True)
    updatedAt: str = Field(default_factory=_now_iso_text, index=True)

    __table_args__ = (
        UniqueConstraint("tariffKey", name="uq_cargo_tariff_tariffkey"),
        Index("ix_cargo_tariff_active_updated", "isActive", "updatedAt"),
        Index("ix_cargo_tariff_deleted_updated", "isDeleted", "updatedAt"),
    )
