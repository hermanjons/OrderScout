from __future__ import annotations

from collections import OrderedDict


PENDING_UI_MS = 300_000
VERIFY_RETRY_MS = 5_000
LISTING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 15
LISTING_TAB_HERO_TITLE = "İlanlar / İlan Yönetimi"
LISTING_TAB_HERO_SUBTITLE = "Mağazalardan ürünleri çek, filtrele ve yönet."
LISTING_TAB_ACTION_TEXT = "İlanlar"
LISTING_FETCH_PANEL_TITLE = "Veri Çekme Paneli"
LISTING_FETCH_BUTTON_TEXT = "Ürün Çek"
LISTING_AUTO_FETCH_LABEL = "Oto Çekim"
LISTING_AUTO_FETCH_UNIT_TEXT = "dk"
LISTING_STATUS_IDLE_TEXT = "Henüz veri çekilmedi."
LISTING_STATUS_FETCHING_TEXT = "Ürünler çekiliyor..."
LISTING_STATUS_FETCHING_COUNT_TEMPLATE = "Ürünler çekiliyor... ({account_count} mağaza)"
LISTING_STATUS_SAVING_TEXT = "Ürünler kaydediliyor..."
LISTING_STATUS_SAVE_COUNT_TEMPLATE = "{count} ürün cache'e kaydediliyor..."
LISTING_STATUS_SAVE_FAILED_TEXT = "Ürünler çekildi ama cache'e yazılamadı."
LISTING_STATUS_SAVED_TEXT = "Ürünler cache'e yazıldı."
LISTING_STATUS_NO_CHANGES_TEXT = "Ürünler güncel, yeni kayıt yok."
LISTING_STATUS_PRODUCTS_RECEIVED_TEMPLATE = "API'den {count} ürün alındı."
LISTING_STATUS_PRODUCTS_EMPTY_TEXT = "API'den ürün alınamadı."
LISTING_AUTO_FETCH_ACTIVE_TEMPLATE = "Oto Çekim aktif ({mins} dk)."
LISTING_AUTO_FETCH_STOPPED_TEXT = "Oto Çekim durduruldu."
LISTING_QUICK_ACCESS_TITLE = "Hızlı Erişim"
LISTING_QUICK_ACCESS_SUBTITLE = "İlan listesini ayrı bir pencerede aç."
LISTING_BADGE_BUTTON_TEXT = "İlanlar"

COST_MATCH_MODES = {"manual", "semi_automatic", "automatic"}
COST_AMOUNT_PLACEHOLDER_BY_TYPE: dict[str, str] = {
    "percentage": "% Oran",
}
COST_SOURCE_FIELD_PLACEHOLDER = "Alan ara/seç"
COST_MATCH_SOURCE_TOOLTIP = "Bu maliyetin değeri nereden gelecek?"
COST_MATCH_DB_FIELD_TOOLTIP = "Bu ilanda mevcut olan sayısal alanlardan birini seç."
COST_MATCH_CARGO_PROVIDER_PLACEHOLDER = "Kargo firması"
COST_MATCH_CARGO_PROVIDER_TOOLTIP = "Bu maliyet için tercih edilen kargo firmasını seç."
COST_MATCH_ROW_HEIGHT = 96
COST_MATCH_PERCENT_DIAMETER = 84
LISTING_LIST_LOADING_TEXT = "İlanlar yükleniyor..."
LISTING_PROFIT_DETAIL_LOADING_TEXT = "Kâr detayı hazırlanıyor..."

PREFERRED_DB_FIELD_LABELS: "OrderedDict[str, str]" = OrderedDict(
    [
        ("salePrice", "Satış Fiyatı"),
        ("listPrice", "Liste Fiyatı"),
        ("vatRate", "KDV Oranı"),
        ("quantity", "Stok Adedi"),
        ("dimensionalWeight", "Desi"),
        ("commissionRate", "Komisyon Oranı"),
        ("cargoPrice", "Kargo Tutarı"),
        ("shippingPrice", "Kargo Tutarı"),
        ("specialConsumptionTax", "ÖTV"),
        ("discount", "İndirim"),
        ("discountRate", "İndirim Oranı"),
    ]
)

DB_FIELD_EXCLUDED_NAMES = {
    "api_account_id",
    "stock_item_id",
    "supplierid",
    "brandid",
    "productid",
    "platformlistingid",
    "stockid",
    "pimcategoryid",
    "batchrequestid",
    "version",
    "approved",
    "archived",
    "locked",
    "on_sale",
}

LISTING_STYLE = """
QWidget#ListingRoot { background-color: #F3F4F6; color: #111827; }
QFrame#HeaderCard {
    border-radius: 12px;
    border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0F172A, stop:1 #111827);
}
QLabel#HeaderTitle { font-size: 16px; font-weight: 600; color: #F9FAFB; }
QLabel#HeaderSubtitle { font-size: 11px; color: #E5E7EB; }
QFrame#SectionCard { background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E7EB; }
QFrame#SectionCard[modeActive="true"] { border: 2px solid #3B82F6; }
QLabel#SectionTitle { font-size: 12px; font-weight: 600; color: #111827; }
QLabel#Muted { font-size: 11px; color: #6B7280; }
QLineEdit#Input {
    padding: 7px 10px;
    border-radius: 10px;
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
}
QPushButton#GhostBtn {
    padding: 6px 10px;
    border-radius: 10px;
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    font-weight: 600;
}
QPushButton#GhostBtn:hover { background: #F3F4F6; }
QPushButton#SoftDanger {
    background: rgba(239, 68, 68, 0.12);
    color: #B91C1C;
    border: 1px solid rgba(239, 68, 68, 0.28);
    border-radius: 12px;
    padding: 11px 14px;
    font-weight: 900;
}
QPushButton#SoftDanger:hover {
    background: rgba(239, 68, 68, 0.18);
    border: 1px solid rgba(239, 68, 68, 0.42);
}
QFrame#QuickCard {
    background-color: #F8FAFC;
    border-radius: 12px;
    border: 1px dashed #E5E7EB;
}
QPushButton#QuickBtn {
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    font-weight: 700;
}
QPushButton#QuickBtn:hover { background: #F3F4F6; }
QWidget#ListingRoot QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 0px 2px 0px;
}
QWidget#ListingRoot QScrollBar::handle:vertical {
    background: rgba(15, 23, 42, 0.18);
    border-radius: 5px;
    min-height: 24px;
}
QWidget#ListingRoot QScrollBar::handle:vertical:hover {
    background: rgba(59, 130, 246, 0.45);
}
QWidget#ListingRoot QScrollBar::add-page:vertical,
QWidget#ListingRoot QScrollBar::sub-page:vertical,
QWidget#ListingRoot QScrollBar::add-page:vertical:hover,
QWidget#ListingRoot QScrollBar::sub-page:vertical:hover,
QWidget#ListingRoot QScrollBar::add-page:vertical:pressed,
QWidget#ListingRoot QScrollBar::sub-page:vertical:pressed {
    background: transparent;
    border: none;
}
QWidget#ListingRoot QScrollBar::add-line:vertical,
QWidget#ListingRoot QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
    border: none;
}
"""

LISTING_QTY_W = 140
LISTING_QTY_H = 56
LISTING_PRICE_W = 160
LISTING_PRICE_H = 56
LISTING_PROFIT_W = 220
LISTING_PROFIT_H = 56
LISTING_BADGE_BTN_W = 236
LISTING_BADGE_BTN_H = 56
LISTING_BADGE_MIN_W = 108
LISTING_BADGE_MIN_H = 44
LISTING_HOOK_W = 44
LISTING_HOOK_H = 30
LISTING_HOOK_BADGE_GAP = 26
LISTING_BADGE_STACK_GAP = 12
LISTING_MIN_TEXT_W = 260
LISTING_BADGE_VISIBLE_MIN_TEXT_W = 460
LISTING_MIN_RIGHT_SCALE = 0.74
LISTING_COMPACT_QTY_MIN_W = 108
LISTING_COMPACT_PRICE_MIN_W = 160
LISTING_COMPACT_BADGE_MIN_W = 136
LISTING_HIDE_BADGES_CLUSTER_W = (
    LISTING_COMPACT_QTY_MIN_W
    + 8
    + LISTING_COMPACT_PRICE_MIN_W
    + 10
    + LISTING_COMPACT_BADGE_MIN_W
    + LISTING_HOOK_BADGE_GAP
    + LISTING_HOOK_W
    + 10
    + 52
)
LISTING_TEXT_CLUSTER_GAP = 56


__all__ = [
    "PENDING_UI_MS",
    "VERIFY_RETRY_MS",
    "LISTING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS",
    "LISTING_TAB_HERO_TITLE",
    "LISTING_TAB_HERO_SUBTITLE",
    "LISTING_TAB_ACTION_TEXT",
    "LISTING_FETCH_PANEL_TITLE",
    "LISTING_FETCH_BUTTON_TEXT",
    "LISTING_AUTO_FETCH_LABEL",
    "LISTING_AUTO_FETCH_UNIT_TEXT",
    "LISTING_STATUS_IDLE_TEXT",
    "LISTING_STATUS_FETCHING_TEXT",
    "LISTING_STATUS_FETCHING_COUNT_TEMPLATE",
    "LISTING_STATUS_SAVING_TEXT",
    "LISTING_STATUS_SAVE_COUNT_TEMPLATE",
    "LISTING_STATUS_SAVE_FAILED_TEXT",
    "LISTING_STATUS_SAVED_TEXT",
    "LISTING_STATUS_NO_CHANGES_TEXT",
    "LISTING_STATUS_PRODUCTS_RECEIVED_TEMPLATE",
    "LISTING_STATUS_PRODUCTS_EMPTY_TEXT",
    "LISTING_AUTO_FETCH_ACTIVE_TEMPLATE",
    "LISTING_AUTO_FETCH_STOPPED_TEXT",
    "LISTING_QUICK_ACCESS_TITLE",
    "LISTING_QUICK_ACCESS_SUBTITLE",
    "LISTING_BADGE_BUTTON_TEXT",
    "COST_MATCH_MODES",
    "COST_AMOUNT_PLACEHOLDER_BY_TYPE",
    "COST_SOURCE_FIELD_PLACEHOLDER",
    "COST_MATCH_CARGO_PROVIDER_PLACEHOLDER",
    "COST_MATCH_CARGO_PROVIDER_TOOLTIP",
    "COST_MATCH_DB_FIELD_TOOLTIP",
    "COST_MATCH_SOURCE_TOOLTIP",
    "COST_MATCH_ROW_HEIGHT",
    "COST_MATCH_PERCENT_DIAMETER",
    "LISTING_LIST_LOADING_TEXT",
    "LISTING_PROFIT_DETAIL_LOADING_TEXT",
    "PREFERRED_DB_FIELD_LABELS",
    "DB_FIELD_EXCLUDED_NAMES",
    "LISTING_STYLE",
    "LISTING_QTY_W",
    "LISTING_QTY_H",
    "LISTING_PRICE_W",
    "LISTING_PRICE_H",
    "LISTING_PROFIT_W",
    "LISTING_PROFIT_H",
    "LISTING_BADGE_BTN_W",
    "LISTING_BADGE_BTN_H",
    "LISTING_BADGE_MIN_W",
    "LISTING_BADGE_MIN_H",
    "LISTING_HOOK_W",
    "LISTING_HOOK_H",
    "LISTING_HOOK_BADGE_GAP",
    "LISTING_BADGE_STACK_GAP",
    "LISTING_MIN_TEXT_W",
    "LISTING_BADGE_VISIBLE_MIN_TEXT_W",
    "LISTING_MIN_RIGHT_SCALE",
    "LISTING_COMPACT_QTY_MIN_W",
    "LISTING_COMPACT_PRICE_MIN_W",
    "LISTING_COMPACT_BADGE_MIN_W",
    "LISTING_HIDE_BADGES_CLUSTER_W",
    "LISTING_TEXT_CLUSTER_GAP",
]
