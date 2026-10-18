from sqlmodel import SQLModel, Field, UniqueConstraint, Column, JSON
from typing import Optional
from datetime import datetime
from Core.db.models import SourceIdentityMixin


class ApiAccount(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "apiaccount"
    __table_args__ = (
        UniqueConstraint("comp_name", "platform", "account_id",
                         name="uq_apiaccount_comp_platform_account"),
    )
    pk: Optional[int] = Field(default=None, primary_key=True)

    # TEMEL (zorunlu)
    account_id: str = Field(index=True, nullable=False)
    comp_name: str = Field(nullable=False)
    platform_id: Optional[int] = Field(default=None, foreign_key="marketplace.pk", index=True)
    platform: str = Field(index=True, nullable=False)

    # GÖRSEL
    logo_path: Optional[str] = None

    # API KİMLİK
    integration_code: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    token: Optional[str] = None

    # PLATFORM ÖZEL
    extra_config: Optional[dict] = Field(sa_column=Column(JSON), default=None)

    # ZAMAN
    last_used_at: Optional[datetime] = None

    # DURUM
    encrypted: bool = False
    token_valid: bool = True
    is_active: bool = True
