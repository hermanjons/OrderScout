from __future__ import annotations

ACCOUNT_LOGO_ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

ACCOUNT_WINDOW_TITLE = "Şirket Yönetimi"
ACCOUNT_TOOLBAR_ACTION_TEXT = "Şirket Yönetimi"
ACCOUNT_TOOLBAR_ACTION_TOOLTIP = "Şirket API hesaplarını yönet"
ACCOUNT_TOOLBAR_ACTION_KEY = "company_manager"
ACCOUNT_TOOLBAR_ICON_SIZE = (32, 32)
ACCOUNT_DIALOG_MIN_SIZE = (900, 600)
ACCOUNT_TABLE_ROW_HEIGHT = 40
ACCOUNT_FORM_FIELD_PLACEHOLDERS = {
    "account_id": "Örn: 761365",
    "comp_name": "Şirket adı",
    "api_key": "API Key",
    "api_secret": "API Secret",
    "integration_code": "Entegrasyon Kodu",
    "token": "Token",
    "extra_config": '{"region": "EU", "merchant_id": "123"}',
}
ACCOUNT_LOGO_BUTTON_TEXT = "Logo Seç"
ACCOUNT_LOGO_CLEAR_TEXT = "Temizle"
ACCOUNT_LOGO_DIALOG_TITLE = "Logo Seç"
ACCOUNT_LOGO_DIALOG_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
ACCOUNT_FORM_FIELD_LABELS = {
    "account_id": "Satıcı ID",
    "platform": "Platform",
    "comp_name": "Şirket Adı",
    "api_key": "API Key",
    "api_secret": "API Secret",
    "integration_code": "Entegrasyon Kodu",
    "token": "Token",
    "extra_config": "Extra Config (JSON)",
    "logo": "Logo",
    "is_active": "Durum",
}
ACCOUNT_EDITOR_CLEAR_TEXT = "Temizle"
ACCOUNT_EDITOR_DELETE_TEXT = "Sil"
ACCOUNT_WORKSPACE_PAGE_SIZE_OPTIONS = (20, 50, 100, 200)
ACCOUNT_WORKSPACE_SHELL_KWARGS = {
    "sidebar_width": 92,
    "left_stick_size": 520,
    "left_collapse_trigger": 480,
    "min_left_width": 320,
    "min_right_width": 320,
    "root_margins": (0, 0, 0, 0),
    "root_spacing": 8,
    "snap_on_drag": False,
}
ACCOUNT_LIST_EMPTY_TEXT = "Gösterilecek şirket bulunamadı."
ACCOUNT_CARD_TITLE_FALLBACK = "(İsimsiz Şirket)"
ACCOUNT_CARD_SELLER_ID_PREFIX = "Satıcı ID"
ACCOUNT_CARD_STATUS_PREFIX = "Durum"
ACCOUNT_CARD_ICON_SIZE = 44
ACCOUNT_CARD_ROW_HEIGHT = 78
ACCOUNT_CARD_HOOK_WIDTH = 50
ACCOUNT_CARD_HOOK_HEIGHT = 30
ACCOUNT_CARD_TITLE_COLOR = "#111827"
ACCOUNT_CARD_META_KEY_COLOR = "#111827"
ACCOUNT_CARD_META_VALUE_COLOR = "#374151"
ACCOUNT_CARD_TITLE_FONT_FAMILY = "Segoe UI"
ACCOUNT_CARD_TITLE_FONT_SIZE = 10
ACCOUNT_CARD_TITLE_TOP_OFFSET = 10
ACCOUNT_CARD_TITLE_HEIGHT = 18
ACCOUNT_CARD_SUBTITLE_TOP_GAP = 4
ACCOUNT_CARD_SUBTITLE_HEIGHT = 16
ACCOUNT_CARD_EXTRA_TOP_GAP = 2
ACCOUNT_CARD_EXTRA_HEIGHT = 16
ACCOUNT_CARD_META_FONT_SIZE = 8
ACCOUNT_DIALOG_STYLESHEET = """
        QDialog#CompanyDialogRoot {
            background-color: #F3F4F6;
            color: #111827;
            font-family: "Segoe UI";
        }
        QFrame#SectionCard {
            background-color: #FFFFFF;
            border-radius: 12px;
            border: 1px solid #E5E7EB;
        }
        QLabel#SectionTitle {
            font-size: 12px;
            font-weight: 700;
            color: #111827;
        }
        QLabel#FieldLabel {
            font-size: 11px;
            font-weight: 600;
            color: #374151;
        }
        QLineEdit, QPlainTextEdit, QComboBox {
            background: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            padding: 8px 10px;
            font-size: 11px;
        }
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 1px solid #93C5FD;
            background: #FFFFFF;
        }
        QPlainTextEdit { min-height: 100px; }
        QPushButton#PrimaryButton {
            background-color: #2563EB;
            color: #FFFFFF;
            border-radius: 8px;
            padding: 8px 14px;
            border: none;
            font-weight: 600;
        }
        QPushButton#PrimaryButton:hover { background-color: #1D4ED8; }

        QPushButton#SecondaryButton {
            background-color: #E5E7EB;
            color: #111827;
            border-radius: 8px;
            padding: 8px 14px;
            border: none;
            font-weight: 600;
        }
        QPushButton#SecondaryButton:hover { background-color: #D1D5DB; }

        QPushButton#DangerButton {
            background-color: #DC2626;
            color: #FEF2F2;
            border-radius: 8px;
            padding: 8px 14px;
            border: none;
            font-weight: 700;
        }
        QPushButton#DangerButton:hover { background-color: #B91C1C; }

        QLabel#LogoBox {
            border: 1px dashed #D1D5DB;
            border-radius: 12px;
            background: #F9FAFB;
        }
        QWidget#PlatformSelect QFrame#SwitchSelectHeader {
            min-height: 44px;
        }
        QWidget#PlatformSelect QToolButton#SwitchSelectArrow {
            min-height: 32px;
            min-width: 32px;
        }
        QLabel#SwitchSelectSummary {
            font-size: 11px;
        }
        QScrollBar:vertical {
            background: transparent;
            width: 10px;
            margin: 2px 0px 2px 0px;
        }
        QScrollBar::handle:vertical {
            background: rgba(15, 23, 42, 0.18);
            border-radius: 5px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background: rgba(59, 130, 246, 0.45);
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QListView#CompanyListView {
            background-color: #FFFFFF;
            border-radius: 12px;
            border: 1px solid #E5E7EB;
        }
        """
ACCOUNT_EDIT_OVERLAY_PROMPT = "Düzenlemek için sağdaki listeden bir şirket seç."
ACCOUNT_BULK_OVERLAY_PROMPT = "Toplu işlem için sağdaki listeden en az bir şirketi SEÇ."
ACCOUNT_LEFT_TITLE_EDIT = "Düzenle"
ACCOUNT_LEFT_HINT_EDIT_EMPTY = "Düzenlemek için sağdaki listeden bir şirket seç."
ACCOUNT_FILTERS_TITLE = "Filtreler"
ACCOUNT_FILTERS_SUBTITLE = "Bu ekranda henüz alan bazlı filtre yok; bağlantı durumu burada izlenir."
ACCOUNT_RECORDS_TITLE = "Kayıtlı Mağazalar"
ACCOUNT_SIDEBAR_NEW_TOOLTIP = "Yeni şirket kaydı"
ACCOUNT_SIDEBAR_EDIT_TOOLTIP = "Şirket düzenleme paneli"
ACCOUNT_SIDEBAR_BULK_TOOLTIP = "Toplu işlem paneli"
ACCOUNT_FORM_SUBMIT_NEW_TEXT = "API Kaydet"
ACCOUNT_FORM_SUBMIT_EDIT_TEXT = "Güncelle"
ACCOUNT_BULK_TITLE = "Toplu İşlemler"
ACCOUNT_BULK_SUMMARY_TEMPLATE = "Seçili Şirket: {count}"
ACCOUNT_BULK_HINT = "SEÇ ile işaretlenen şirketler üzerinde toplu API kontrolü çalıştır."
ACCOUNT_BULK_HEALTH_BUTTON_TEXT = "Toplu API Kontrolü"
ACCOUNT_BULK_CLEAR_BUTTON_TEXT = "Seçimi Temizle"
ACCOUNT_HEALTH_IDLE_TEXT = "API bağlantı kontrolü hazır."
ACCOUNT_HEALTH_RUNNING_TEXT = "API bağlantı kontrolü çalışıyor..."
ACCOUNT_HEALTH_DONE_FALLBACK_TEXT = "API bağlantı kontrolü tamamlandı."
ACCOUNT_FILTERS_SUMMARY_TEMPLATE = "Toplam şirket: {total} | Seçili: {selected}"
ACCOUNT_RECORDS_SUMMARY_TEMPLATE = "{shown} / {total} kayıt"
ACCOUNT_RECORDS_INITIAL_SUMMARY = ACCOUNT_RECORDS_SUMMARY_TEMPLATE.format(shown=0, total=0)
ACCOUNT_LIST_LOADING_TEXT = "Şirketler yükleniyor..."
ACCOUNT_LEFT_TITLE_NEW = "Yeni Ekle"
ACCOUNT_LEFT_HINT_NEW = "Yeni şirket bilgilerini doldurup kaydet."
ACCOUNT_LEFT_TITLE_BULK = "Toplu İşlemler"
ACCOUNT_LEFT_HINT_BULK = "SEÇ ile işaretlediğin şirketler üzerinde toplu işlem yapabilirsin."
ACCOUNT_LEFT_HINT_EDIT_SELECTED_TEMPLATE = "Seçili Şirket: {name}"
ACCOUNT_EDIT_CHOOSE_PROMPT = "Düzenlemek için sağdaki listeden bir şirket seç."
ACCOUNT_SUBMIT_RUNNING_TEXT = "Kayıt ve doğrulama işlemi çalışıyor..."
ACCOUNT_BULK_NO_SELECTION_MESSAGE = "Toplu kontrol için en az bir şirket seçmelisin."
ACCOUNT_BULK_HEALTH_FAILED_TEMPLATE = "{failed} şirket için API bağlantı kontrolü başarısız."
ACCOUNT_SESSION_HEALTH_FAILED_TEMPLATE = "Açılış kontrolünde {failed} şirket doğrulanamadı."
ACCOUNT_DELETE_NO_SELECTION_MESSAGE = "Herhangi bir şirket seçilmedi."
ACCOUNT_DELETE_CONFIRM_TITLE = "Silme Onayı"
ACCOUNT_DELETE_CONFIRM_MESSAGE_TEMPLATE = "{name} şirketini silmek istediğine emin misin?"

__all__ = [
    "ACCOUNT_WINDOW_TITLE",
    "ACCOUNT_TOOLBAR_ACTION_TEXT",
    "ACCOUNT_TOOLBAR_ACTION_TOOLTIP",
    "ACCOUNT_TOOLBAR_ACTION_KEY",
    "ACCOUNT_TOOLBAR_ICON_SIZE",
    "ACCOUNT_DIALOG_MIN_SIZE",
    "ACCOUNT_TABLE_ROW_HEIGHT",
    "ACCOUNT_FORM_FIELD_PLACEHOLDERS",
    "ACCOUNT_FORM_FIELD_LABELS",
    "ACCOUNT_EDITOR_CLEAR_TEXT",
    "ACCOUNT_EDITOR_DELETE_TEXT",
    "ACCOUNT_LOGO_BUTTON_TEXT",
    "ACCOUNT_LOGO_CLEAR_TEXT",
    "ACCOUNT_LOGO_DIALOG_TITLE",
    "ACCOUNT_LOGO_DIALOG_FILTER",
    "ACCOUNT_LOGO_ALLOWED_EXTENSIONS",
    "ACCOUNT_WORKSPACE_PAGE_SIZE_OPTIONS",
    "ACCOUNT_WORKSPACE_SHELL_KWARGS",
    "ACCOUNT_LIST_EMPTY_TEXT",
    "ACCOUNT_CARD_TITLE_FALLBACK",
    "ACCOUNT_CARD_SELLER_ID_PREFIX",
    "ACCOUNT_CARD_STATUS_PREFIX",
    "ACCOUNT_CARD_ICON_SIZE",
    "ACCOUNT_CARD_ROW_HEIGHT",
    "ACCOUNT_CARD_HOOK_WIDTH",
    "ACCOUNT_CARD_HOOK_HEIGHT",
    "ACCOUNT_CARD_TITLE_COLOR",
    "ACCOUNT_CARD_META_KEY_COLOR",
    "ACCOUNT_CARD_META_VALUE_COLOR",
    "ACCOUNT_CARD_TITLE_FONT_FAMILY",
    "ACCOUNT_CARD_TITLE_FONT_SIZE",
    "ACCOUNT_CARD_TITLE_TOP_OFFSET",
    "ACCOUNT_CARD_TITLE_HEIGHT",
    "ACCOUNT_CARD_SUBTITLE_TOP_GAP",
    "ACCOUNT_CARD_SUBTITLE_HEIGHT",
    "ACCOUNT_CARD_EXTRA_TOP_GAP",
    "ACCOUNT_CARD_EXTRA_HEIGHT",
    "ACCOUNT_CARD_META_FONT_SIZE",
    "ACCOUNT_DIALOG_STYLESHEET",
    "ACCOUNT_EDIT_OVERLAY_PROMPT",
    "ACCOUNT_BULK_OVERLAY_PROMPT",
    "ACCOUNT_LEFT_TITLE_EDIT",
    "ACCOUNT_LEFT_HINT_EDIT_EMPTY",
    "ACCOUNT_FILTERS_TITLE",
    "ACCOUNT_FILTERS_SUBTITLE",
    "ACCOUNT_RECORDS_TITLE",
    "ACCOUNT_SIDEBAR_NEW_TOOLTIP",
    "ACCOUNT_SIDEBAR_EDIT_TOOLTIP",
    "ACCOUNT_SIDEBAR_BULK_TOOLTIP",
    "ACCOUNT_FORM_SUBMIT_NEW_TEXT",
    "ACCOUNT_FORM_SUBMIT_EDIT_TEXT",
    "ACCOUNT_BULK_TITLE",
    "ACCOUNT_BULK_SUMMARY_TEMPLATE",
    "ACCOUNT_BULK_HINT",
    "ACCOUNT_BULK_HEALTH_BUTTON_TEXT",
    "ACCOUNT_BULK_CLEAR_BUTTON_TEXT",
    "ACCOUNT_HEALTH_IDLE_TEXT",
    "ACCOUNT_HEALTH_RUNNING_TEXT",
    "ACCOUNT_HEALTH_DONE_FALLBACK_TEXT",
    "ACCOUNT_FILTERS_SUMMARY_TEMPLATE",
    "ACCOUNT_RECORDS_SUMMARY_TEMPLATE",
    "ACCOUNT_RECORDS_INITIAL_SUMMARY",
    "ACCOUNT_LIST_LOADING_TEXT",
    "ACCOUNT_LEFT_TITLE_NEW",
    "ACCOUNT_LEFT_HINT_NEW",
    "ACCOUNT_LEFT_TITLE_BULK",
    "ACCOUNT_LEFT_HINT_BULK",
    "ACCOUNT_LEFT_HINT_EDIT_SELECTED_TEMPLATE",
    "ACCOUNT_EDIT_CHOOSE_PROMPT",
    "ACCOUNT_SUBMIT_RUNNING_TEXT",
    "ACCOUNT_BULK_NO_SELECTION_MESSAGE",
    "ACCOUNT_BULK_HEALTH_FAILED_TEMPLATE",
    "ACCOUNT_SESSION_HEALTH_FAILED_TEMPLATE",
    "ACCOUNT_DELETE_NO_SELECTION_MESSAGE",
    "ACCOUNT_DELETE_CONFIRM_TITLE",
    "ACCOUNT_DELETE_CONFIRM_MESSAGE_TEMPLATE",
]
