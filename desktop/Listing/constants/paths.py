from __future__ import annotations

from pathlib import Path

from settings import MEDIA_ROOT


DOMAIN_CONSTANTS_ROOT = Path(__file__).resolve().parent
TRENDYOL_CONSTANTS_ROOT = DOMAIN_CONSTANTS_ROOT / "trendyol"

LISTING_IMAGE_CACHE_DIRNAME = "listing_images"
LISTING_IMAGE_CACHE_DIR = MEDIA_ROOT / LISTING_IMAGE_CACHE_DIRNAME
