"""Account data provenance shared by local reads and remote API boundaries."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Marketplaces.processors.catalog import normalize_marketplace_environment


def account_environment_scope(account: Any, *, default: str | None = None) -> dict[str, str]:
    def field(name: str, fallback=None):
        return account.get(name, fallback) if isinstance(account, Mapping) else getattr(account, name, fallback)

    extra = field("extra_config")
    extra = dict(extra) if isinstance(extra, Mapping) else {}
    text = lambda value: str(value or "").strip().casefold()
    # A local data marker remains authoritative even if remote credentials or a
    # conflicting production/stage value are later added to the account.
    if (text(extra.get("data_origin")) == "synthetic"
            or text(extra.get("auto_sync_mode")) == "local"
            or text(extra.get("environment")) == "local"
            or text(extra.get("api_environment")) == "local"):
        return {"environment": "local", "environment_source": "account.extra_config"}

    raw = extra.get("environment") or extra.get("api_environment")
    if raw in (None, "") and "stage" in extra:
        raw = "stage" if text(extra["stage"]) in {"true", "1", "stage", "staging", "test"} else "production"
    if raw not in (None, ""):
        clean = text(raw)
        if clean in {"true", "1"}:
            clean = "stage"
        elif clean in {"false", "0"}:
            clean = "production"
        try:
            environment = normalize_marketplace_environment(clean)
        except ValueError:
            environment = "unknown"
        return {"environment": environment, "environment_source": "account.extra_config"}
    if text(field("platform")) == "trendyol":
        return {"environment": "production", "environment_source": "trendyol_catalog_default"}
    if default:
        return {"environment": normalize_marketplace_environment(default), "environment_source": "catalog_default"}
    return {"environment": "unknown", "environment_source": "unresolved"}


def resolve_account_environment(account: Any, *, default: str | None = None) -> str:
    return account_environment_scope(account, default=default)["environment"]


__all__ = ["account_environment_scope", "resolve_account_environment"]
