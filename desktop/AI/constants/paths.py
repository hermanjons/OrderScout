from __future__ import annotations

from pathlib import Path

from settings import USER_DATA_DIR


AI_DOMAIN_ROOT = USER_DATA_DIR / "ai"
AI_MODELS_ROOT = AI_DOMAIN_ROOT / "models"
AI_RUNTIME_ROOT = AI_DOMAIN_ROOT / "runtime"
AI_DEFAULT_MODELS_DIR = AI_MODELS_ROOT
AI_CONFIG_FILE = AI_DOMAIN_ROOT / "ai_config.json"

AI_CONSTANTS_DIR = Path(__file__).resolve().parent
AI_PACKAGE_ROOT = AI_CONSTANTS_DIR.parent
AI_BUNDLED_RUNTIME_ROOT = AI_PACKAGE_ROOT / "runtime"
AI_DEFAULT_FILES_DIR = AI_CONSTANTS_DIR / "files"
DEFAULT_AI_CONFIG_FILE = AI_DEFAULT_FILES_DIR / "ai_config.default.json"


def ensure_ai_paths() -> None:
    AI_DOMAIN_ROOT.mkdir(parents=True, exist_ok=True)
    AI_MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    AI_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)

