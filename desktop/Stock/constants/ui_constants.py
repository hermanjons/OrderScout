from __future__ import annotations


MODERN_LIGHT_QSS = """
#StockRoot {
    background: #F4F6FA;
    color: #0F172A;
    font-family: "Segoe UI";
    font-size: 13px;
}

#StockRoot QFrame#Card,
#StockRoot QFrame#CardLeft,
#StockRoot QFrame#SectionCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.98),
        stop:0.55 rgba(247,250,255,0.98),
        stop:1 rgba(244,247,252,0.98)
    );
    border: 1px solid rgba(15, 23, 42, 0.05);
    border-radius: 22px;
}

#StockRoot QFrame#BottomBar {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
}

#StockRoot QFrame#CardLeft {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,1),
        stop:1 rgba(248,250,255,1)
    );
}

#StockRoot QFrame#SoftCard,
#StockRoot QFrame#QuickCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(255,255,255,0.92),
        stop:1 rgba(244,247,252,0.92)
    );
    border: 1px solid rgba(15, 23, 42, 0.05);
    border-radius: 18px;
}

#StockRoot QFrame#QuickCard {
    border-style: dashed;
}

#StockRoot QLabel#Title {
    font-size: 18px;
    font-weight: 900;
    color: #0F172A;
}

#StockRoot QLabel#SubTitle {
    font-size: 12px;
    color: rgba(15, 23, 42, 0.65);
}

#StockRoot QLabel#Section,
#StockRoot QLabel#SectionTitle {
    font-size: 14px;
    font-weight: 900;
    color: #0F172A;
}

#StockRoot QLabel#FieldLabel {
    font-size: 12px;
    font-weight: 700;
    color: #0F172A;
}

#StockRoot QLabel#Muted,
#StockRoot QLabel#StatusInfo {
    font-size: 11px;
    color: rgba(15, 23, 42, 0.65);
}

#StockRoot QComboBox#Combo {
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    min-height: 22px;
    color: #0F172A;
}

#StockRoot QComboBox#Combo:hover {
    border: 1px solid #CBD5E1;
}

#StockRoot QComboBox#Combo:focus {
    border: 1px solid #60A5FA;
}

#StockRoot QCheckBox { color: #0F172A; }
#StockRoot QCheckBox::indicator { width: 18px; height: 18px; }

#StockRoot QPushButton#Primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2563EB,
        stop:1 #1D4ED8
    );
    color: white;
    border: 0px;
    border-radius: 12px;
    padding: 11px 16px;
    font-weight: 900;
}
#StockRoot QPushButton#Primary:hover { background: #1D4ED8; }
#StockRoot QPushButton#Primary:pressed { background: #1E40AF; }
#StockRoot QPushButton#Primary:disabled {
    background: #DBEAFE;
    color: #93C5FD;
    border: 1px solid #BFDBFE;
}

#StockRoot QPushButton#Secondary {
    background: rgba(37, 99, 235, 0.10);
    color: #1D4ED8;
    border: 1px solid rgba(37, 99, 235, 0.18);
    border-radius: 12px;
    padding: 11px 14px;
    font-weight: 900;
}
#StockRoot QPushButton#Secondary:hover { background: rgba(37, 99, 235, 0.14); }

#StockRoot QPushButton#InlineAction {
    background: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 900;
}
#StockRoot QPushButton#InlineAction:hover {
    background: #DBEAFE;
    border: 1px solid #93C5FD;
}
#StockRoot QPushButton#InlineAction:pressed {
    background: #BFDBFE;
    border: 1px solid #60A5FA;
}
#StockRoot QPushButton#InlineAction:disabled {
    background: #F1F5F9;
    color: #94A3B8;
    border: 1px solid #CBD5E1;
}

#StockRoot QPushButton#Ghost {
    background: #FFFFFF;
    color: #0F172A;
    border: 1px solid rgba(17, 24, 39, 0.12);
    border-radius: 12px;
    padding: 11px 14px;
    font-weight: 800;
}
#StockRoot QPushButton#Ghost:hover { background: rgba(15, 23, 42, 0.03); }
#StockRoot QPushButton#Ghost:disabled {
    background: #F8FAFC;
    color: #94A3B8;
    border: 1px solid rgba(148, 163, 184, 0.32);
}

#StockRoot QPushButton#Danger {
    background: #EF4444;
    color: white;
    border: 0px;
    border-radius: 12px;
    padding: 11px 14px;
    font-weight: 950;
}
#StockRoot QPushButton#Danger:hover { background: #DC2626; }
#StockRoot QPushButton#Danger:disabled {
    background: #FEE2E2;
    color: #F87171;
    border: 1px solid #FECACA;
}

#StockRoot QPushButton#Success {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #22C55E,
        stop:1 #16A34A
    );
    color: #FFFFFF;
    border: 0px;
    border-radius: 12px;
    padding: 11px 16px;
    font-weight: 950;
}
#StockRoot QPushButton#Success:hover { background: #16A34A; }
#StockRoot QPushButton#Success:disabled {
    background: #DCFCE7;
    color: #86EFAC;
    border: 1px solid #BBF7D0;
}

#StockRoot QPushButton#DangerStrong {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #EF4444,
        stop:1 #DC2626
    );
    color: #FFFFFF;
    border: 0px;
    border-radius: 12px;
    padding: 11px 16px;
    font-weight: 950;
}

#StockRoot QPushButton#SoftDanger {
    background: rgba(239, 68, 68, 0.10);
    color: #B91C1C;
    border: 1px solid rgba(239, 68, 68, 0.18);
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 900;
}
#StockRoot QPushButton#SoftDanger:hover {
    background: rgba(239, 68, 68, 0.14);
    border-color: rgba(239, 68, 68, 0.28);
}

#StockRoot QPushButton#PageButton {
    background: #FFFFFF;
    color: #0F172A;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 12px;
    min-width: 42px;
    min-height: 42px;
    font-weight: 900;
}
#StockRoot QPushButton#PageButton:hover {
    background: #EFF6FF;
    border-color: #BFDBFE;
}

#StockRoot QFrame#TxModeTabs {
    background: rgba(255, 255, 255, 0.88);
    border: 1px solid rgba(148, 163, 184, 0.20);
    border-radius: 14px;
}

#StockRoot QPushButton#TxModeTab {
    border: 1px solid transparent;
    border-radius: 10px;
    background: transparent;
    color: #334155;
    padding: 10px 14px;
    font-weight: 900;
}
#StockRoot QPushButton#TxModeTab:hover {
    background: rgba(15, 23, 42, 0.05);
}
#StockRoot QPushButton#TxModeTab:disabled {
    color: rgba(15, 23, 42, 0.42);
    background: rgba(15, 23, 42, 0.03);
}
#StockRoot QPushButton#TxModeTab[locked="true"] {
    color: rgba(15, 23, 42, 0.42);
    background: rgba(15, 23, 42, 0.03);
}
#StockRoot QPushButton#TxModeTab[locked="true"]:hover {
    background: rgba(15, 23, 42, 0.03);
}
#StockRoot QPushButton#TxModeTab[active="true"][tone="in"],
#StockRoot QPushButton#TxModeTab[active="true"][tone="in"][locked="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #22C55E,
        stop:1 #16A34A
    );
    color: #FFFFFF;
    border: 1px solid rgba(22, 163, 74, 0.55);
}
#StockRoot QPushButton#TxModeTab[active="true"][tone="out"],
#StockRoot QPushButton#TxModeTab[active="true"][tone="out"][locked="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #EF4444,
        stop:1 #DC2626
    );
    color: #FFFFFF;
    border: 1px solid rgba(220, 38, 38, 0.55);
}
#StockRoot QPushButton#TxModeTab[active="true"][tone="in"]:disabled {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #22C55E,
        stop:1 #16A34A
    );
    color: #FFFFFF;
    border: 1px solid rgba(22, 163, 74, 0.55);
}
#StockRoot QPushButton#TxModeTab[active="true"][tone="out"]:disabled {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #EF4444,
        stop:1 #DC2626
    );
    color: #FFFFFF;
    border: 1px solid rgba(220, 38, 38, 0.55);
}

#StockRoot QTableWidget {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 16px;
    gridline-color: rgba(148, 163, 184, 0.16);
}
#StockRoot QHeaderView::section {
    background: #F8FAFC;
    color: #0F172A;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid rgba(15, 23, 42, 0.06);
    font-weight: 900;
}

#StockRoot QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px 2px 2px 2px;
}
#StockRoot QScrollBar::handle:vertical {
    background: rgba(15, 23, 42, 0.14);
    border-radius: 6px;
    min-height: 28px;
}
#StockRoot QScrollBar::handle:vertical:hover {
    background: rgba(37, 99, 235, 0.34);
}
#StockRoot QScrollBar::add-line:vertical,
#StockRoot QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
    border: none;
}

#StockRoot QScrollArea { border: 0px; background: transparent; }
#StockRoot QScrollArea::viewport { background: transparent; }
#StockRoot QWidget#FormBody { background: transparent; }
"""

STOCK_NATIVE_LINE_EDIT_QSS = """
QLineEdit {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 12px;
    padding: 10px 12px;
    color: #0F172A;
}
QLineEdit:focus {
    border: 1px solid rgba(59, 130, 246, 0.95);
    background: #FFFFFF;
}
QLineEdit:hover {
    border: 1px solid rgba(15, 23, 42, 0.18);
}
"""

STOCK_SEARCH_LINE_EDIT_QSS = """
QLineEdit {
    background: #FFFFFF;
    border: 1px solid rgba(59, 130, 246, 0.35);
    border-radius: 12px;
    padding: 10px 12px;
    color: #0F172A;
}
QLineEdit:focus {
    border: 1px solid rgba(59, 130, 246, 0.95);
    background: #FFFFFF;
}
QLineEdit:hover {
    border: 1px solid rgba(15, 23, 42, 0.18);
}
"""

STOCK_TEXT_EDIT_QSS = """
QTextEdit {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 12px;
    padding: 10px 10px;
    color: #0F172A;
}
QTextEdit:focus {
    border: 1px solid rgba(59, 130, 246, 0.95);
    background: #FFFFFF;
}
QTextEdit:hover {
    border: 1px solid rgba(15, 23, 42, 0.18);
}
"""

STOCK_COMBO_QSS = """
QComboBox {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 12px;
    padding: 10px 12px;
    padding-right: 28px;
    color: #0F172A;
}
QComboBox:focus {
    border: 1px solid rgba(59, 130, 246, 0.95);
}
QComboBox:hover {
    border: 1px solid rgba(15, 23, 42, 0.18);
}
QComboBox::drop-down {
    border: 0px;
    width: 30px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
    background: transparent;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 6px solid rgba(15, 23, 42, 0.55);
    margin-right: 8px;
}
"""

STOCK_DOUBLE_SPIN_QSS = """
QDoubleSpinBox {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 12px;
    padding: 10px 12px;
    color: #0F172A;
}
QDoubleSpinBox:focus {
    border: 1px solid rgba(59, 130, 246, 0.95);
}
QDoubleSpinBox:hover {
    border: 1px solid rgba(15, 23, 42, 0.18);
}
QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {
    width: 30px;
    border: 0px;
    background: rgba(15, 23, 42, 0.04);
    border-left: 1px solid rgba(17, 24, 39, 0.10);
}
QDoubleSpinBox::up-button {
    subcontrol-position: top right;
}
QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
}
QDoubleSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover {
    background: rgba(37, 99, 235, 0.10);
}
QDoubleSpinBox::up-button:pressed {
    background: rgba(22, 163, 74, 0.25);
}
QDoubleSpinBox::down-button:pressed {
    background: rgba(220, 38, 38, 0.22);
}
"""

STOCK_SWITCH_SELECT_QSS = """
QFrame#SwitchSelectHeader {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 12px;
}
QFrame#SwitchSelectHeader[open="true"] {
    border-color: rgba(59, 130, 246, 0.92);
    background: #F8FBFF;
}
QLabel#SwitchSelectSummary {
    color: #0F172A;
    font-weight: 600;
}
QToolButton#SwitchSelectArrow {
    border: none;
    min-width: 28px;
    min-height: 28px;
    color: rgba(15, 23, 42, 0.58);
}
QToolButton#SwitchSelectArrow:hover {
    color: #0F172A;
}
QFrame#SwitchSelectPopup {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 14px;
}
QLineEdit#SwitchSelectSearch {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 10px;
    padding: 6px 10px;
    min-height: 30px;
    color: #0F172A;
}
QLineEdit#SwitchSelectSearch[state="focus"] {
    border: 1px solid rgba(59, 130, 246, 0.92);
}
QLineEdit#SwitchSelectSearch[state="typing"] {
    border: 1px solid rgba(34, 197, 94, 0.88);
}
QLineEdit#SwitchSelectSearch[state="error"] {
    border: 1px solid rgba(239, 68, 68, 0.92);
}
QListWidget#SwitchSelectList {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
QWidget#SwitchSelectItem {
    background: #FFFFFF;
    border-radius: 8px;
}
QWidget#SwitchSelectItem:hover {
    background: #F8FAFC;
}
QLabel#SwitchSelectItemLabel {
    color: #0F172A;
    font-weight: 600;
}
"""

STOCK_FILE_BADGE_PICKER_QSS = """
QPushButton#FileBadgeHeaderButton {
    border: 1px solid #CBD5E1;
    border-radius: 16px;
    color: #0F172A;
    font-size: 12px;
    font-weight: 800;
    text-align: center;
    padding: 8px 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F8FAFC, stop:1 #EEF4FF);
}
QPushButton#FileBadgeHeaderButton:hover {
    border-color: #93C5FD;
    background: #EFF6FF;
}
QPushButton#FileBadgeHeaderButton:pressed {
    border-color: #60A5FA;
    background: #DBEAFE;
}
QFrame#FileBadgeDrawer {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}
QLabel#FileBadgeHint {
    color: #475569;
    font-size: 11px;
    padding-left: 4px;
}
QPushButton#FileBadgePickButton, QToolButton#FileBadgeClearButton {
    border: 1px solid #CBD5E1;
    border-radius: 12px;
    background: #FFFFFF;
    color: #0F172A;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#FileBadgePickButton:hover, QToolButton#FileBadgeClearButton:hover {
    border-color: #93C5FD;
    background: #EFF6FF;
}
QPushButton#FileBadgePickButton:pressed, QToolButton#FileBadgeClearButton:pressed {
    background: #DBEAFE;
    border-color: #60A5FA;
}
QScrollArea#FileBadgeScroll {
    background: transparent;
    border: none;
    border-radius: 0px;
}
QToolButton#FileBadgeRemove {
    border: 1px solid #FECACA;
    border-radius: 8px;
    background: #FFFFFF;
    color: #DC2626;
    min-width: 17px;
    min-height: 17px;
    max-width: 17px;
    max-height: 17px;
    font-size: 9px;
    font-weight: 900;
}
QToolButton#FileBadgeRemove:hover {
    border-color: #EF4444;
    color: #B91C1C;
}
"""

STOCK_NUMBER_STEPPER_QSS = """
QFrame#NumberStepperFrame {
    border: 1px solid rgba(15, 23, 42, 0.12);
    border-radius: 17px;
    background: #FFFFFF;
}
QFrame#NumberStepperFrame[focused="true"] {
    border: 1px solid rgba(15, 23, 42, 0.24);
}
QLineEdit#NumberStepperInput {
    border: 0px;
    border-radius: 10px;
    padding: 0px 4px;
    background: transparent;
    color: #0F172A;
    font-size: 13px;
    font-weight: 800;
    min-height: 28px;
    max-height: 28px;
}
QToolButton#NumberStepperPlus, QToolButton#NumberStepperMinus {
    border: 0px;
    border-radius: 14px;
    font-size: 15px;
    font-weight: 950;
    padding: 0px;
}
QToolButton#NumberStepperPlus {
    background: rgba(34, 197, 94, 0.10);
    color: #15803D;
}
QToolButton#NumberStepperMinus {
    background: rgba(239, 68, 68, 0.10);
    color: #B91C1C;
    font-size: 16px;
}
QToolButton#NumberStepperPlus:hover {
    background: rgba(34, 197, 94, 0.18);
    color: #166534;
}
QToolButton#NumberStepperMinus:hover {
    background: rgba(239, 68, 68, 0.18);
    color: #991B1B;
}
QToolButton#NumberStepperPlus[pulse="true"] {
    background: rgba(34, 197, 94, 0.32);
    color: #14532D;
}
QToolButton#NumberStepperMinus[pulse="true"] {
    background: rgba(239, 68, 68, 0.30);
    color: #7F1D1D;
}
"""

STOCK_CARD_FONT_FAMILY = "Segoe UI"
STOCK_CARD_PLACEHOLDER_TEXT_COLOR = "#6B7280"
STOCK_CARD_ICON_PLACEHOLDER_COLOR = "#E5E7EB"
STOCK_CARD_TITLE_COLOR = "#111827"
STOCK_CARD_BODY_COLOR = "#374151"
STOCK_CARD_MUTED_COLOR = "#6B7280"
STOCK_CARD_ACTION_TEXT_COLOR = "#2563EB"
STOCK_CARD_AVATAR_FILL_COLOR = "#E0E7FF"
STOCK_CARD_AVATAR_TEXT_COLOR = "#1D4ED8"
STOCK_CARD_BADGE_BORDER_COLOR = "#22C55E"
STOCK_CARD_BADGE_FILL_COLOR = "#DCFCE7"
STOCK_CARD_BADGE_TEXT_COLOR = "#166534"
STOCK_CARD_SELECTED_BUTTON_FILL_COLOR = "#DBEAFE"
STOCK_CARD_SELECTED_BUTTON_BORDER_COLOR = "#60A5FA"
STOCK_CARD_HOVER_BUTTON_FILL_COLOR = "#EFF6FF"
STOCK_CARD_HOVER_BUTTON_BORDER_COLOR = "#93C5FD"
STOCK_CARD_IDLE_BUTTON_FILL_COLOR = "#F8FAFC"
STOCK_CARD_IDLE_BUTTON_BORDER_COLOR = "#CBD5E1"
STOCK_CARD_PLACEHOLDER_FONT_SIZE = 9
STOCK_CARD_TITLE_FONT_SIZE = 10
STOCK_CARD_META_FONT_SIZE = 8
STOCK_CARD_ACTION_FONT_SIZE = 8
STOCK_CARD_AVATAR_FONT_SIZE = 11
STOCK_MANAGER_CARD_ROW_HEIGHT = 116

STOCK_ITEMS_EMPTY_TEXT = "Gösterilecek stok kartı bulunamadı."
STOCK_TX_EMPTY_TEXT = "Gösterilecek hareket bulunamadı."
STOCK_MANAGER_EMPTY_TEXT = "Gösterilecek kayıt bulunamadı."
STOCK_IMAGE_PREVIEW_TITLE = "Görsel Önizleme"
STOCK_IMAGE_PREVIEW_LOAD_ERROR_TEXT = "Görsel yüklenemedi."
STOCK_IMAGE_PREVIEW_EMPTY_TEXT = "Görsel bulunamadı."
STOCK_ITEM_SOURCE_BUTTON_TEXT = "Stok Hareketleri"
STOCK_TX_SOURCE_BUTTON_TEXT = "Stok Kartı"
STOCK_TX_ORDER_BUTTON_TEXT = "Sipariş"
STOCK_TX_LISTING_BUTTON_TEXT = "İlan"

STOCK_CARD_INLINE_STOCK_W = 208
STOCK_CARD_INLINE_AVG_W = 176
STOCK_CARD_INLINE_STOCK_H = 56
STOCK_CARD_INLINE_GAP = 10

STOCK_MANAGER_REFRESH_TEXT = "Yenile"
STOCK_MANAGER_FILTERS_TITLE = "Filtreler"
STOCK_MANAGER_LEFT_EDIT_TITLE = "Düzenle"
STOCK_MANAGER_LEFT_NEW_TITLE = "Yeni Ekle"
STOCK_MANAGER_LEFT_BULK_TITLE = "Toplu İşlemler"
STOCK_MANAGER_BULK_TITLE = "Toplu İşlemler"
STOCK_MANAGER_CLEAR_TEXT = "Temizle"
STOCK_MANAGER_SAVE_EDIT_TEXT = "Güncelle"
STOCK_MANAGER_DELETE_TEXT = "Sil"
STOCK_MANAGER_RESET_FILTERS_TEXT = "Filtreyi Sıfırla"
STOCK_MANAGER_BULK_CLEAR_TEXT = "Seçimi Temizle"
STOCK_MANAGER_BULK_DELETE_TEXT = "Seçilenleri Sil"
STOCK_MANAGER_SIDEBAR_BULK_TOOLTIP = "Toplu işlem paneli"
STOCK_MANAGER_WORKSPACE_SHELL_KWARGS = {
    "sidebar_width": 92,
    "left_stick_size": 520,
    "left_collapse_trigger": 260,
    "min_left_width": 320,
    "min_right_width": 320,
    "root_margins": (0, 0, 0, 0),
    "root_spacing": 8,
}


__all__ = [
    "MODERN_LIGHT_QSS",
    "STOCK_NATIVE_LINE_EDIT_QSS",
    "STOCK_SEARCH_LINE_EDIT_QSS",
    "STOCK_TEXT_EDIT_QSS",
    "STOCK_COMBO_QSS",
    "STOCK_DOUBLE_SPIN_QSS",
    "STOCK_SWITCH_SELECT_QSS",
    "STOCK_FILE_BADGE_PICKER_QSS",
    "STOCK_NUMBER_STEPPER_QSS",
    "STOCK_CARD_FONT_FAMILY",
    "STOCK_CARD_PLACEHOLDER_TEXT_COLOR",
    "STOCK_CARD_ICON_PLACEHOLDER_COLOR",
    "STOCK_CARD_TITLE_COLOR",
    "STOCK_CARD_BODY_COLOR",
    "STOCK_CARD_MUTED_COLOR",
    "STOCK_CARD_ACTION_TEXT_COLOR",
    "STOCK_CARD_AVATAR_FILL_COLOR",
    "STOCK_CARD_AVATAR_TEXT_COLOR",
    "STOCK_CARD_BADGE_BORDER_COLOR",
    "STOCK_CARD_BADGE_FILL_COLOR",
    "STOCK_CARD_BADGE_TEXT_COLOR",
    "STOCK_CARD_SELECTED_BUTTON_FILL_COLOR",
    "STOCK_CARD_SELECTED_BUTTON_BORDER_COLOR",
    "STOCK_CARD_HOVER_BUTTON_FILL_COLOR",
    "STOCK_CARD_HOVER_BUTTON_BORDER_COLOR",
    "STOCK_CARD_IDLE_BUTTON_FILL_COLOR",
    "STOCK_CARD_IDLE_BUTTON_BORDER_COLOR",
    "STOCK_CARD_PLACEHOLDER_FONT_SIZE",
    "STOCK_CARD_TITLE_FONT_SIZE",
    "STOCK_CARD_META_FONT_SIZE",
    "STOCK_CARD_ACTION_FONT_SIZE",
    "STOCK_CARD_AVATAR_FONT_SIZE",
    "STOCK_MANAGER_CARD_ROW_HEIGHT",
    "STOCK_ITEMS_EMPTY_TEXT",
    "STOCK_TX_EMPTY_TEXT",
    "STOCK_MANAGER_EMPTY_TEXT",
    "STOCK_IMAGE_PREVIEW_TITLE",
    "STOCK_IMAGE_PREVIEW_LOAD_ERROR_TEXT",
    "STOCK_IMAGE_PREVIEW_EMPTY_TEXT",
    "STOCK_ITEM_SOURCE_BUTTON_TEXT",
    "STOCK_TX_SOURCE_BUTTON_TEXT",
    "STOCK_TX_ORDER_BUTTON_TEXT",
    "STOCK_TX_LISTING_BUTTON_TEXT",
    "STOCK_CARD_INLINE_STOCK_W",
    "STOCK_CARD_INLINE_AVG_W",
    "STOCK_CARD_INLINE_STOCK_H",
    "STOCK_CARD_INLINE_GAP",
    "STOCK_MANAGER_REFRESH_TEXT",
    "STOCK_MANAGER_FILTERS_TITLE",
    "STOCK_MANAGER_LEFT_EDIT_TITLE",
    "STOCK_MANAGER_LEFT_NEW_TITLE",
    "STOCK_MANAGER_LEFT_BULK_TITLE",
    "STOCK_MANAGER_BULK_TITLE",
    "STOCK_MANAGER_CLEAR_TEXT",
    "STOCK_MANAGER_SAVE_EDIT_TEXT",
    "STOCK_MANAGER_DELETE_TEXT",
    "STOCK_MANAGER_RESET_FILTERS_TEXT",
    "STOCK_MANAGER_BULK_CLEAR_TEXT",
    "STOCK_MANAGER_BULK_DELETE_TEXT",
    "STOCK_MANAGER_SIDEBAR_BULK_TOOLTIP",
    "STOCK_MANAGER_WORKSPACE_SHELL_KWARGS",
]
