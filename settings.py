# settings.py
from __future__ import annotations

from pathlib import Path

# settings.py'nin bulunduğu klasör (orderScout/)
BASE_DIR = Path(__file__).resolve().parent

# DATABASE
DB_NAME = "orders.db"

# ✅ PROJE İÇİ DB KLASÖRÜ (MUTLAK)
DEFAULT_DATABASE_DIR = (BASE_DIR / "databases").resolve()
DEFAULT_DATABASE_DIR.mkdir(parents=True, exist_ok=True)

# MEDIA
MEDIA_ROOT = str((BASE_DIR / "images").resolve())
