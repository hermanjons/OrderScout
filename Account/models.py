from sqlmodel import SQLModel, Field, UniqueConstraint
from typing import Optional
from datetime import datetime


class ApiAccount(SQLModel, table=True):
    __tablename__ = "apiaccount"
    __table_args__ = (
        UniqueConstraint("comp_name", "platform", "seller_id",
                         name="uq_apiaccount_comp_platform_seller"),
    )

    # Surrogate PK
    id: Optional[int] = Field(default=None, primary_key=True)

    # TEMEL BİLGİLER
    seller_id: int = Field(index=True)  # Artık PK değil, index'li alan
    comp_name: str  # Firma adı (UI için)

    # API GİRİŞ BİLGİLERİ
    api_key: str
    api_secret: str

    # PLATFORM BİLGİSİ
    platform: str = Field(default="trendyol", index=True)

    # TAKİP VE KULLANIM ZAMANLARI
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_used_at: Optional[datetime] = None

    # GÜVENLİK & ŞİFRELEME (opsiyonel)
    encrypted: bool = False
    token_valid: bool = True

    # AKTİFLİK DURUMU
    is_active: bool = True
