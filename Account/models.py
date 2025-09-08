from sqlmodel import SQLModel, Field, UniqueConstraint
from typing import Optional
from datetime import datetime


class ApiAccount(SQLModel, table=True):
    __tablename__ = "apiaccount"
    __table_args__ = (
        UniqueConstraint("comp_name", "platform"),  # İsim + platform birlikte unique
    )

    # TEMEL BİLGİLER
    seller_id: int = Field(primary_key=True)  # Özgün satıcı ID'si (örn: Trendyol ID)
    comp_name: str                            # Firma adı (UI için)

    # API GİRİŞ BİLGİLERİ
    api_key: str                              # API erişim anahtarı
    api_secret: str                           # API şifresi

    # PLATFORM BİLGİSİ
    platform: str = Field(default="trendyol")  # Örn: trendyol, amazon, hepsiburada

    # TAKİP VE KULLANIM ZAMANLARI
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None   # En son sipariş çekilen zaman

    # GÜVENLİK & ŞİFRELEME (opsiyonel)
    encrypted: Optional[bool] = False         # Şifreleme kullanıldı mı?
    token_valid: Optional[bool] = True        # Token geçerli mi?

    # AKTİFLİK DURUMU
    is_active: bool = True                    # Kullanımda mı?
