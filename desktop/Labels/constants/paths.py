# Labels/constants/paths.py
from __future__ import annotations

from pathlib import Path

# Domain sabiti: assets klasörü
LABEL_ASSETS_DIRNAME = "assets"
LABEL_IMAGES_DIRNAME = "images"


def label_assets_dir() -> Path:
    """
    Labels/assets klasörü (domain altında).
    """
    # Labels/constants/paths.py -> parent: constants -> parent: Labels -> assets
    return Path(__file__).resolve().parent.parent / LABEL_ASSETS_DIRNAME


def label_images_dir() -> Path:
    """
    Labels/assets/images klasörü.
    """
    return label_assets_dir() / LABEL_IMAGES_DIRNAME


LABEL_ASSETS_DIR = label_assets_dir()
LABEL_IMAGES_DIR = label_images_dir()
