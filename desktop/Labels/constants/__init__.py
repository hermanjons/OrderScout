# Labels/constants/__init__.py
from __future__ import annotations

from .paths import (
    LABEL_ASSETS_DIRNAME,
    LABEL_IMAGES_DIRNAME,
    label_assets_dir,
    label_images_dir,
    LABEL_ASSETS_DIR,
    LABEL_IMAGES_DIR,
)

from .template_constants import (
    LABEL_BRANDS,
    LABEL_MODELS_BY_BRAND,
)
from .ui_constants import LABEL_EXPORT_DIALOG_TITLE, LABEL_EXPORT_SECTION_TITLE

__all__ = [
    # paths
    "LABEL_ASSETS_DIRNAME",
    "LABEL_IMAGES_DIRNAME",
    "label_assets_dir",
    "label_images_dir",
    "LABEL_ASSETS_DIR",
    "LABEL_IMAGES_DIR",

    # templates
    "LABEL_BRANDS",
    "LABEL_EXPORT_DIALOG_TITLE",
    "LABEL_EXPORT_SECTION_TITLE",
    "LABEL_MODELS_BY_BRAND",
]
