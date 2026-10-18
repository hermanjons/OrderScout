from __future__ import annotations


APP_MESSAGE_DETAILS_SHOW_TEXT = "Detayları Göster"
APP_MESSAGE_DETAILS_HIDE_TEXT = "Detayları Gizle"
APP_MESSAGE_DEFAULT_TITLES = {
    "info": "Bilgi",
    "success": "Başarılı",
    "warning": "Uyarı",
    "error": "Hata",
    "question": "Onay",
}
APP_MESSAGE_OK_TEXT = "Tamam"
APP_MESSAGE_YES_TEXT = "Evet"
APP_MESSAGE_NO_TEXT = "Hayır"
APP_MESSAGE_CANCEL_TEXT = "Vazgeç"
APP_MESSAGE_CLOSE_TEXT = "Kapat"
APP_MESSAGE_ICON_SIZE = 64
APP_MESSAGE_ICON_PIXMAP_SIZE = 28
APP_MESSAGE_MIN_WIDTH = 640
APP_MESSAGE_DETAILS_HEIGHT = 140
APP_MESSAGE_ICON_PALETTE = {
    "info": ("#DCE8FF", "#165AA7"),
    "success": ("#DCFCE7", "#15803D"),
    "warning": ("#FEF3C7", "#B45309"),
    "error": ("#FEE2E2", "#B91C1C"),
    "question": ("#DBEAFE", "#1D4ED8"),
}
APP_MESSAGE_STYLE = """
            QDialog#AppMessageDialog {
                background: transparent;
            }
            QFrame#Card {
                background: #FFFFFF;
                border-radius: 24px;
                border: 1px solid rgba(148, 163, 184, 0.18);
            }
            QLabel#Title {
                color: #111827;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#Text {
                color: #475569;
                font-size: 13px;
                line-height: 1.45;
            }
            QFrame#Footer {
                background: #F8FAFC;
                border-top: 1px solid rgba(226, 232, 240, 0.95);
                border-bottom-left-radius: 24px;
                border-bottom-right-radius: 24px;
            }
            QPushButton#PrimaryButton {
                min-width: 164px;
                padding: 0 18px;
                border: none;
                border-radius: 14px;
                background: #1561B7;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 800;
            }
            QPushButton#PrimaryButton:hover {
                background: #0F4F99;
            }
            QPushButton#PrimaryButton:focus {
                border: 2px solid #BFDBFE;
            }
            QPushButton#SecondaryButton {
                min-width: 144px;
                padding: 0 10px;
                border: 1px solid transparent;
                border-radius: 14px;
                background: transparent;
                color: #1561B7;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#SecondaryButton:hover {
                background: rgba(21, 97, 183, 0.08);
                border-color: rgba(21, 97, 183, 0.16);
            }
            QPushButton#SecondaryButton:focus {
                border-color: #BFDBFE;
            }
            QToolButton#DetailsToggle {
                border: none;
                padding: 0;
                color: #1561B7;
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            }
            QToolButton#DetailsToggle:hover {
                color: #0F4F99;
            }
            QPlainTextEdit#Details {
                background: #F8FAFC;
                color: #334155;
                border: 1px solid rgba(203, 213, 225, 0.95);
                border-radius: 14px;
                padding: 10px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
            }
            """

RECORD_WORKSPACE_STYLE = """
QWidget#RecordWorkspaceRoot, QWidget#FinanceRoot { background-color: #F3F4F6; color: #111827; }
QFrame#SectionCard { background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E7EB; }
QFrame#SoftCard { background-color: #F8FAFC; border-radius: 14px; border: 1px solid #E2E8F0; }
QLabel#SectionTitle { font-size: 12px; font-weight: 700; color: #111827; }
QLabel#Muted { font-size: 11px; color: #6B7280; }
QLabel#StatusInfo { font-size: 11px; color: #475569; }
QLabel#FieldLabel { font-size: 12px; font-weight: 700; color: #0F172A; }
QFrame#QuickCard { background-color: #F8FAFC; border-radius: 12px; border: 1px dashed #E5E7EB; }
QLineEdit#Input, QComboBox#Combo {
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    min-height: 22px;
}
QPlainTextEdit#MethodText {
    border-radius: 10px;
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    padding: 8px 10px;
}
QPushButton#Ghost, QPushButton#SecondaryButton, QPushButton#Secondary {
    background-color: #FFFFFF;
    color: #1E3A8A;
    border: 1px solid #CBD5E1;
    border-radius: 14px;
    padding: 10px 16px;
    font-weight: 800;
}
QPushButton#Ghost:hover, QPushButton#SecondaryButton:hover, QPushButton#Secondary:hover {
    border: 1px solid #60A5FA;
    background-color: #EFF6FF;
    color: #1D4ED8;
}
QPushButton#Ghost:disabled, QPushButton#SecondaryButton:disabled, QPushButton#Secondary:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
    border: 1px solid #CBD5E1;
}
QPushButton#Primary, QPushButton#PrimaryButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #2563EB;
    border-radius: 14px;
    padding: 10px 18px;
    font-weight: 900;
}
QPushButton#Primary:hover, QPushButton#PrimaryButton:hover {
    background-color: #1D4ED8;
    border: 1px solid #1D4ED8;
}
QPushButton#Primary:disabled, QPushButton#PrimaryButton:disabled {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border: 1px solid #93C5FD;
}
QPushButton#Danger, QPushButton#DangerButton {
    background-color: #EF4444;
    color: #FFFFFF;
    border: 1px solid #EF4444;
    border-radius: 14px;
    padding: 10px 16px;
    font-weight: 900;
}
QPushButton#Danger:hover, QPushButton#DangerButton:hover {
    background-color: #DC2626;
    border: 1px solid #DC2626;
}
QPushButton#Danger:disabled, QPushButton#DangerButton:disabled {
    background-color: #FEE2E2;
    color: #F87171;
    border: 1px solid #FECACA;
}
QPushButton#SoftDanger {
    background-color: rgba(239, 68, 68, 0.12);
    color: #B91C1C;
    border: 1px solid rgba(239, 68, 68, 0.28);
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 900;
}
QPushButton#SoftDanger:hover {
    background-color: rgba(239, 68, 68, 0.18);
    border: 1px solid rgba(239, 68, 68, 0.42);
}
QPushButton#SoftDanger:disabled {
    background-color: rgba(239, 68, 68, 0.08);
    color: #F87171;
    border: 1px solid rgba(248, 113, 113, 0.26);
}
QPushButton#PageButton {
    min-width: 38px;
    min-height: 38px;
    border-radius: 12px;
    border: 1px solid #D1D5DB;
    background-color: #FFFFFF;
    font-weight: 900;
}
QPushButton#PageButton:hover {
    border: 1px solid #60A5FA;
    background-color: #EFF6FF;
}
QPushButton#SelectButton {
    min-width: 64px;
    min-height: 40px;
    border-radius: 12px;
    border: 1px solid #CBD5E1;
    background-color: #FFFFFF;
    color: #274060;
    font-weight: 900;
}
QPushButton#SelectButton:hover {
    border: 1px solid #3B82F6;
    background-color: #EFF6FF;
    color: #1D4ED8;
}
QPushButton#SelectButton[selected="true"] {
    border: 1px solid #60A5FA;
    background-color: #DBEAFE;
    color: #1D4ED8;
}
QPushButton#TariffSelectButton {
    min-width: 64px;
    min-height: 40px;
    border-radius: 12px;
    border: 1px solid #CBD5E1;
    background-color: #FFFFFF;
    color: #274060;
    font-weight: 900;
}
QPushButton#TariffSelectButton:hover {
    border: 1px solid #3B82F6;
    background-color: #EFF6FF;
    color: #1D4ED8;
}
QPushButton#TariffSelectButton[picked="true"] {
    border: 1px solid #22C55E;
    background-color: #DCFCE7;
    color: #166534;
}
QFrame#FinanceListCard {
    background: #FFFFFF;
    border-radius: 16px;
    border: 1px solid #E5E7EB;
}
QFrame#FinanceListCard:hover {
    border: 1px solid #93C5FD;
}
QFrame#FinanceListCard[selected="true"] {
    border: 1px solid #60A5FA;
    background: #EFF6FF;
}
QLabel#InvoiceTitle {
    font-size: 13px;
    font-weight: 900;
    color: #0F172A;
}
QLabel#InvoiceMeta {
    font-size: 11px;
    color: #475569;
}
QLabel#InvoiceMetaStrong {
    font-size: 11px;
    color: #0F172A;
    font-weight: 700;
}
QLabel#DefaultBadge {
    padding: 4px 8px;
    border-radius: 999px;
    background: rgba(34, 197, 94, 0.15);
    color: #166534;
    font-size: 10px;
    font-weight: 900;
}
QLabel#DetailValue {
    font-size: 11px;
    color: #0F172A;
    font-weight: 700;
}
QLabel#DetailCaption {
    font-size: 11px;
    color: #64748B;
}
QFrame#DetailMetricCard {
    background: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
}
QTableWidget {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    gridline-color: #E5E7EB;
}
QHeaderView::section {
    background: #F8FAFC;
    border: 0px;
    padding: 6px 8px;
    font-weight: 700;
}
QWidget#RecordWorkspaceRoot QScrollBar:vertical,
QWidget#FinanceRoot QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 0px 2px 0px;
}
QWidget#RecordWorkspaceRoot QScrollBar::handle:vertical,
QWidget#FinanceRoot QScrollBar::handle:vertical {
    background: rgba(15, 23, 42, 0.18);
    border-radius: 5px;
    min-height: 24px;
}
QWidget#RecordWorkspaceRoot QScrollBar::handle:vertical:hover,
QWidget#FinanceRoot QScrollBar::handle:vertical:hover {
    background: rgba(59, 130, 246, 0.45);
}
QWidget#RecordWorkspaceRoot QScrollBar::add-page:vertical,
QWidget#RecordWorkspaceRoot QScrollBar::sub-page:vertical,
QWidget#RecordWorkspaceRoot QScrollBar::add-line:vertical,
QWidget#RecordWorkspaceRoot QScrollBar::sub-line:vertical,
QWidget#FinanceRoot QScrollBar::add-page:vertical,
QWidget#FinanceRoot QScrollBar::sub-page:vertical,
QWidget#FinanceRoot QScrollBar::add-line:vertical,
QWidget#FinanceRoot QScrollBar::sub-line:vertical {
    background: transparent;
    border: none;
    height: 0px;
}
QWidget#RecordWorkspaceRoot QScrollArea,
QWidget#FinanceRoot QScrollArea {
    border: 0px;
    background: transparent;
}
QWidget#RecordWorkspaceRoot QScrollArea::viewport,
QWidget#FinanceRoot QScrollArea::viewport {
    background: transparent;
}
QWidget#FormBody {
    background: transparent;
}
QListView#RecordWorkspaceListView {
    background-color: #FFFFFF;
    border-radius: 12px;
    border: 1px solid #E5E7EB;
}
QWidget#RecordWorkspaceRoot QCheckBox,
QWidget#FinanceRoot QCheckBox {
    spacing: 8px;
    color: #334155;
    font-size: 12px;
}
QWidget#RecordWorkspaceRoot QCheckBox::indicator,
QWidget#FinanceRoot QCheckBox::indicator {
    width: 18px;
    height: 18px;
}
"""

RECORD_WORKSPACE_EMPTY_TEXT = "Gösterilecek kayıt bulunamadı."
RECORD_WORKSPACE_SELECT_BUTTON_TEXT = "SEÇ"
RECORD_WORKSPACE_PREV_BUTTON_TEXT = "<"
RECORD_WORKSPACE_NEXT_BUTTON_TEXT = ">"
RECORD_WORKSPACE_PAGE_LABEL_TEMPLATE = "Sayfa {current}/{total} | Toplam: {count} kayıt"
RECORD_WORKSPACE_PAGE_SIZE_LABEL = "Sayfa başına"

SWITCH_SELECT_ARROW_CLOSED_TEXT = "v"
SWITCH_SELECT_ARROW_OPEN_TEXT = "^"
SWITCH_SELECT_SEARCH_PLACEHOLDER = "Ara..."
DATE_SELECTOR_PREV_MONTH_TEXT = "‹"
DATE_SELECTOR_NEXT_MONTH_TEXT = "›"
DATE_SELECTOR_MONTH_NAMES = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
DATE_SELECTOR_RANGE_SEPARATOR_TEXT = "→"
DATE_SELECTOR_RANGE_END_TEXT = "Bitiş seç"
DATE_SELECTOR_ICON_TEXT = "📅"
DATE_SELECTOR_RANGE_SELECTED_HINT_TEXT = "Aralık seçildi"
DATE_SELECTOR_RANGE_END_HINT_TEXT = "Bitiş tarihini seçin"
DATE_SELECTOR_RANGE_START_HINT_TEXT = "Başlangıç tarihini seçin"
TIME_SELECTOR_RANGE_SEPARATOR_TEXT = "→"
TIME_SELECTOR_START_LABEL = "Başlangıç"
TIME_SELECTOR_END_LABEL = "Bitiş"
TIME_SELECTOR_ICON_TEXT = "🕒"
TIME_SELECTOR_NOW_TEXT = "Şimdi"
TIME_SELECTOR_OK_TEXT = "Tamam"
TIME_SELECTOR_RANGE_HINT_TEXT = "Saat aralığı seçin"
TIME_SELECTOR_SINGLE_HINT_TEXT = "Saat seçin"

FILE_BADGE_HEADER_TEMPLATE = "{count} adet seçildi  {arrow}"
FILE_BADGE_DRAWER_CLOSED_ARROW_TEXT = "▾"
FILE_BADGE_DRAWER_OPEN_ARROW_TEXT = "▴"
FILE_BADGE_HINT_TEXT = "Seçilen dosyaları açmak için çipe tıkla."
FILE_BADGE_PREVIEW_TITLE = "Önizleme"
FILE_BADGE_IMAGE_OPEN_ERROR_TEXT = "Görsel açılamadı"
FILE_BADGE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
FILE_BADGE_EMPTY_HINT_TEMPLATE = "{button_text} ile dosya ekleyebilirsin."

PHONE_DEFAULT_DIAL_CODE = "+90"
PHONE_FALLBACK_DIAL_CODES = ("+1", "+44", "+49", "+33", "+39", "+34")
PHONE_NUMBER_PLACEHOLDER = "5000000000"
PHONE_MIN_DIGITS = 4
PHONE_MAX_DIGITS = 15

__all__ = [
    "APP_MESSAGE_DETAILS_HIDE_TEXT",
    "APP_MESSAGE_DETAILS_SHOW_TEXT",
    "APP_MESSAGE_CANCEL_TEXT",
    "APP_MESSAGE_CLOSE_TEXT",
    "APP_MESSAGE_DEFAULT_TITLES",
    "APP_MESSAGE_DETAILS_HEIGHT",
    "APP_MESSAGE_ICON_PALETTE",
    "APP_MESSAGE_ICON_PIXMAP_SIZE",
    "APP_MESSAGE_ICON_SIZE",
    "APP_MESSAGE_MIN_WIDTH",
    "APP_MESSAGE_NO_TEXT",
    "APP_MESSAGE_OK_TEXT",
    "APP_MESSAGE_STYLE",
    "APP_MESSAGE_YES_TEXT",
    "DATE_SELECTOR_ICON_TEXT",
    "DATE_SELECTOR_MONTH_NAMES",
    "DATE_SELECTOR_NEXT_MONTH_TEXT",
    "DATE_SELECTOR_PREV_MONTH_TEXT",
    "DATE_SELECTOR_RANGE_END_HINT_TEXT",
    "DATE_SELECTOR_RANGE_END_TEXT",
    "DATE_SELECTOR_RANGE_SELECTED_HINT_TEXT",
    "DATE_SELECTOR_RANGE_SEPARATOR_TEXT",
    "DATE_SELECTOR_RANGE_START_HINT_TEXT",
    "FILE_BADGE_DRAWER_CLOSED_ARROW_TEXT",
    "FILE_BADGE_DRAWER_OPEN_ARROW_TEXT",
    "FILE_BADGE_EMPTY_HINT_TEMPLATE",
    "FILE_BADGE_HEADER_TEMPLATE",
    "FILE_BADGE_HINT_TEXT",
    "FILE_BADGE_IMAGE_EXTENSIONS",
    "FILE_BADGE_IMAGE_OPEN_ERROR_TEXT",
    "FILE_BADGE_PREVIEW_TITLE",
    "PHONE_DEFAULT_DIAL_CODE",
    "PHONE_FALLBACK_DIAL_CODES",
    "PHONE_MAX_DIGITS",
    "PHONE_MIN_DIGITS",
    "PHONE_NUMBER_PLACEHOLDER",
    "RECORD_WORKSPACE_EMPTY_TEXT",
    "RECORD_WORKSPACE_NEXT_BUTTON_TEXT",
    "RECORD_WORKSPACE_PAGE_LABEL_TEMPLATE",
    "RECORD_WORKSPACE_PAGE_SIZE_LABEL",
    "RECORD_WORKSPACE_PREV_BUTTON_TEXT",
    "RECORD_WORKSPACE_SELECT_BUTTON_TEXT",
    "RECORD_WORKSPACE_STYLE",
    "SWITCH_SELECT_ARROW_CLOSED_TEXT",
    "SWITCH_SELECT_ARROW_OPEN_TEXT",
    "SWITCH_SELECT_SEARCH_PLACEHOLDER",
    "TIME_SELECTOR_END_LABEL",
    "TIME_SELECTOR_ICON_TEXT",
    "TIME_SELECTOR_NOW_TEXT",
    "TIME_SELECTOR_OK_TEXT",
    "TIME_SELECTOR_RANGE_HINT_TEXT",
    "TIME_SELECTOR_RANGE_SEPARATOR_TEXT",
    "TIME_SELECTOR_SINGLE_HINT_TEXT",
    "TIME_SELECTOR_START_LABEL",
]
