from pathlib import Path
from settings import ASSETS_DIR, MEDIA_ROOT

# Klasör isimleri (domain sabiti)
COMPANY_LOGOS_DIRNAME = "company_logos"
ACCOUNT_ASSETS_DIR = Path(ASSETS_DIR)
ACCOUNT_TOOLBAR_ICON_PATH = ACCOUNT_ASSETS_DIR / "comp_ico.png"
ACCOUNT_SIDEBAR_NEW_ICON_PATH = ACCOUNT_ASSETS_DIR / "yeni-kayit.png"
ACCOUNT_SIDEBAR_EDIT_ICON_PATH = ACCOUNT_ASSETS_DIR / "duzenleme-icon.png"
ACCOUNT_SIDEBAR_BULK_ICON_PATH = ACCOUNT_ASSETS_DIR / "toplu-secim (2).png"


def company_logos_dir() -> Path:
    """
    Şirket logo klasörü (MEDIA_ROOT altında).
    """
    return Path(MEDIA_ROOT) / COMPANY_LOGOS_DIRNAME
