from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel
from Core.db.models import SourceIdentityMixin


def _now_iso_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class Marketplace(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "marketplace"
    __table_args__ = (
        UniqueConstraint("code", name="uq_marketplace_code"),
        Index("ix_marketplace_active_label", "isActive", "label"),
    )

    pk: Optional[int] = Field(default=None, primary_key=True)

    code: str = Field(index=True, nullable=False, max_length=32)
    label: str = Field(nullable=False, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    logoPath: Optional[str] = Field(default=None, max_length=500)

    isActive: bool = Field(default=True, index=True)

    createdAt: str = Field(default_factory=_now_iso_text, index=True)
    updatedAt: str = Field(default_factory=_now_iso_text, index=True)
