from __future__ import annotations


MARKETPLACE_SELECT_BUTTON_TEXT = "SEÇ"
MARKETPLACE_SELECTED_BUTTON_TEXT = "SEÇİLİ"
MARKETPLACE_ACCEPT_BUTTON_TEXT = "KABUL ET"
MARKETPLACE_PENDING_BADGE_TEXT = "ÖNERİLEN KAYIT"
MARKETPLACE_ACCEPT_TITLE = "Önerilen Kayıt"
MARKETPLACE_ACCEPT_CONFIRMATION_TEXT = (
    "Bu kayıt OrderScout tarafından önerilen bir kayıttır. "
    "Bu işlem sonucunda bu kaydı kullanmayı kabul etmiş olursunuz.\n\n"
    "Devam edilsin mi?"
)

MARKETPLACES_TAB_STYLE = """
QWidget#MarketplacesRoot { background: #F3F4F6; color: #0F172A; }
QFrame#SectionCard {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 16px;
}
QFrame#QuickCard {
    background: #F8FAFC;
    border: 1px dashed #E2E8F0;
    border-radius: 14px;
}
QLabel#SectionTitle { font-size: 14px; font-weight: 900; color: #0F172A; }
QLabel#Muted { font-size: 12px; color: #64748B; }
"""

MARKETPLACES_HERO_TITLE = "Pazaryerleri / Satış Kanalları"
MARKETPLACES_HERO_SUBTITLE = "Hazır pazaryerlerini ve kullanıcı tanımlı satış kanallarını tek katalogda yönet."
MARKETPLACES_PANEL_TOOLTIP = "Pazaryeri bilgi paneli"
MARKETPLACES_PANEL_TITLE = "Pazaryeri Paneli"
MARKETPLACES_INFO_TITLE = "Satış kanalı sahipliği burada"
MARKETPLACES_INFO_HINT = (
    "Platformlar ve kullanıcı tanımlı satış kanalları bu domainde tutulur. "
    "Account, Orders ve diğer domainler aynı kataloğu ortak dil olarak tüketir."
)
MARKETPLACES_QUICK_ACCESS_TITLE = "Hızlı Erişim"
MARKETPLACES_QUICK_ACCESS_SUBTITLE = "Pazaryeri kataloğunu ayrı pencerede aç ve yönet."
MARKETPLACES_BADGE_BUTTON_TEXT = "Pazaryerleri"

__all__ = [
    "MARKETPLACE_ACCEPT_BUTTON_TEXT",
    "MARKETPLACE_ACCEPT_CONFIRMATION_TEXT",
    "MARKETPLACE_ACCEPT_TITLE",
    "MARKETPLACE_PENDING_BADGE_TEXT",
    "MARKETPLACE_SELECT_BUTTON_TEXT",
    "MARKETPLACE_SELECTED_BUTTON_TEXT",
    "MARKETPLACES_BADGE_BUTTON_TEXT",
    "MARKETPLACES_HERO_SUBTITLE",
    "MARKETPLACES_HERO_TITLE",
    "MARKETPLACES_INFO_HINT",
    "MARKETPLACES_INFO_TITLE",
    "MARKETPLACES_PANEL_TITLE",
    "MARKETPLACES_PANEL_TOOLTIP",
    "MARKETPLACES_QUICK_ACCESS_SUBTITLE",
    "MARKETPLACES_QUICK_ACCESS_TITLE",
    "MARKETPLACES_TAB_STYLE",
]
