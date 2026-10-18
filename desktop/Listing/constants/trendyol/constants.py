from __future__ import annotations

from typing import Any

from Marketplaces.processors.catalog import (
    marketplace_api_operation_profile,
    marketplace_api_scope_profile,
    marketplace_api_status_message,
)


LISTING_TRENDYOL_PLATFORM_CODE = "TRENDYOL"
LISTING_TRENDYOL_API_SCOPE = "listing"


def trendyol_listing_scope_profile(environment: str = "production") -> dict[str, Any]:
    profile = marketplace_api_scope_profile(
        LISTING_TRENDYOL_PLATFORM_CODE,
        LISTING_TRENDYOL_API_SCOPE,
        environment,
    )
    if not profile:
        raise RuntimeError("Listing API scope tanimi bulunamadi.")
    return profile


def trendyol_listing_operation_profile(
    operation_name: str,
    environment: str = "production",
) -> dict[str, Any]:
    profile = marketplace_api_operation_profile(
        LISTING_TRENDYOL_PLATFORM_CODE,
        LISTING_TRENDYOL_API_SCOPE,
        operation_name,
        environment,
    )
    if not profile.get("path"):
        raise RuntimeError(f"Listing API endpoint tanimi bulunamadi: {operation_name}")
    return profile


def trendyol_listing_status_message(operation_name: str, status_code: int) -> str:
    return str(
        marketplace_api_status_message(
            LISTING_TRENDYOL_PLATFORM_CODE,
            LISTING_TRENDYOL_API_SCOPE,
            operation_name,
            status_code,
        )
        or ""
    ).strip()


__all__ = [
    "LISTING_TRENDYOL_PLATFORM_CODE",
    "LISTING_TRENDYOL_API_SCOPE",
    "trendyol_listing_scope_profile",
    "trendyol_listing_operation_profile",
    "trendyol_listing_status_message",
]
