from __future__ import annotations

from AI.processors.catalog import load_default_ai_config


AI_DEFAULT_SETTINGS = load_default_ai_config()
AI_DEFAULT_SEARCH_LIMIT = int(AI_DEFAULT_SETTINGS.get("search_limit") or 16)
AI_DEFAULT_PREFERRED_EXTENSIONS = tuple(
    AI_DEFAULT_SETTINGS.get("prefer_extensions") or [".gguf"]
)

__all__ = [
    "AI_DEFAULT_PREFERRED_EXTENSIONS",
    "AI_DEFAULT_SEARCH_LIMIT",
    "AI_DEFAULT_SETTINGS",
]
