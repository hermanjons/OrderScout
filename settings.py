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


# ===============================
# Freemius License Settings
# ===============================

FREEMIUS_BASE_URL = "https://api.freemius.com"

# Freemius Dashboard → Product → Product ID
FREEMIUS_PRODUCT_ID = 22119   # 🔴 BURAYA KENDİ PRODUCT ID’Nİ YAZ

# Freemius Dashboard → Settings → Keys
# ⚠️ Şimdilik dev için, prod'da exe içine gömmek risklidir
FREEMIUS_SECRET_KEY = "sk_m6Ey2v}XP*HOc@HK)S=J5q};P2?VW"
