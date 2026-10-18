# settings.py
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "OrderScout"
APP_VERSION = os.getenv("ORDER_SCOUT_VERSION", "0.3.5")


# ==========================================================
# Base paths
# ==========================================================
def _get_project_root() -> Path:
    # settings.py'nin yeri neresi ise ona göre root hesapla
    return Path(__file__).resolve().parent


PROJECT_ROOT: Path = _get_project_root()


def resource_path(relative: str) -> str:
    """
    PyInstaller / normal çalıştırma uyumlu path resolver.
    - Dev: PROJECT_ROOT/relative
    - PyInstaller: _MEIPASS/relative
    """
    base = Path(getattr(sys, "_MEIPASS", str(PROJECT_ROOT)))
    return str(base / relative)


# ==========================================================
# User data dir (DB, logs, cache, user media)
# ==========================================================
def get_user_data_dir(app_name: str = APP_NAME) -> Path:
    # Windows
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / app_name

    # macOS
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name

    # Linux + diğerleri
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / app_name


USER_DATA_DIR: Path = get_user_data_dir()
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================================
# Database
# ==========================================================
DB_BASENAME = "oscdb"          # ✅ yeni isim
DB_EXT = ".sqlite3"
DB_FILENAME = f"{DB_BASENAME}{DB_EXT}"

DB_PATH: Path = USER_DATA_DIR / DB_FILENAME
DB_NAME: str = str(DB_PATH)
DB_URL: str = f"sqlite:///{DB_PATH.as_posix()}"


# ==========================================================
# User media (kullanıcı tarafından seçilen logo, export, vs)
# ==========================================================
MEDIA_ROOT: Path = USER_DATA_DIR / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

MEDIA_COMPANY_LOGOS: Path = MEDIA_ROOT / "company_logos"
MEDIA_COMPANY_LOGOS.mkdir(parents=True, exist_ok=True)

MEDIA_EXPORTS: Path = MEDIA_ROOT / "exports"
MEDIA_EXPORTS.mkdir(parents=True, exist_ok=True)

MEDIA_LOGS: Path = USER_DATA_DIR / "logs"
MEDIA_LOGS.mkdir(parents=True, exist_ok=True)


# ==========================================================
# App static assets (uygulama içi ikonlar/resimler)
# ==========================================================
# Proje içinde duran images klasörü (değişmez, bundled asset)
ASSETS_DIR: Path = PROJECT_ROOT / "images"

# PyInstaller ile kullanmak için:
# icon_path = resource_path("images/add_button.png")


# ==========================================================
# Optional donations (Buy Me a Coffee or another personal support page)
# ==========================================================
DONATION_URL = os.getenv("ORDER_SCOUT_DONATION_URL", "").strip()


# ==========================================================
# Release surface feature visibility
# ==========================================================
# Domain code remains available; these switches only decide which unfinished
# surfaces are exposed by the production shell during the manual-first release.
# Show AI during source development/testing; keep packaged releases opt-in.
_DEFAULT_AI_UI = "0" if bool(getattr(sys, "frozen", False)) else "1"
ENABLE_AI_UI: bool = os.getenv("ENABLE_AI_UI", _DEFAULT_AI_UI) == "1"
ENABLE_FINANCE_INVOICES_UI: bool = os.getenv("ENABLE_FINANCE_INVOICES_UI", "0") == "1"
ENABLE_FINANCE_TRANSACTIONS_UI: bool = os.getenv("ENABLE_FINANCE_TRANSACTIONS_UI", "0") == "1"

# ==========================================================
# Test Lab UI (internal QA tooling)
# ==========================================================
# 0 => kapalı (default), 1 => toolbar'da Test Lab açılır
# Dev (source) çalışmada varsayılan açık, frozen build'de varsayılan kapalı.
_DEFAULT_TEST_LAB_UI = "0" if bool(getattr(sys, "frozen", False)) else "1"
# 0 => kapalı, 1 => toolbar'da Test Lab açılır
ENABLE_TEST_LAB_UI: bool = os.getenv("ENABLE_TEST_LAB_UI", _DEFAULT_TEST_LAB_UI) == "1"
