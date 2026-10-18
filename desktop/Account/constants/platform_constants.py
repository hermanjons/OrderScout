from __future__ import annotations

from Marketplaces.processors.catalog import (
    canonical_platform_code as account_platform_code,
    marketplace_account_default_enabled_fields,
    marketplace_account_enabled_fields,
    marketplace_account_health_profile,
    marketplace_account_profile,
    marketplace_codes,
    platform_label_for_code,
    platform_select_options,
)

ACCOUNT_PLATFORM_CODES = tuple(marketplace_codes())
ACCOUNT_PLATFORM_CODE_SET = frozenset(ACCOUNT_PLATFORM_CODES)
ACCOUNT_PLATFORM_OPTIONS = tuple(platform_select_options(include_all=False))
ACCOUNT_DEFAULT_PLATFORM_CODE = str(ACCOUNT_PLATFORM_CODES[0] if ACCOUNT_PLATFORM_CODES else "")
ACCOUNT_PLATFORM_LABELS = {
    str(code): str(platform_label_for_code(code) or code)
    for code in ACCOUNT_PLATFORM_CODES
}
ACCOUNT_DEFAULT_PLATFORM_LABEL = str(
    ACCOUNT_PLATFORM_LABELS.get(ACCOUNT_DEFAULT_PLATFORM_CODE) or ACCOUNT_DEFAULT_PLATFORM_CODE or ""
)
ACCOUNT_DEFAULT_ENABLED_FIELDS = frozenset(marketplace_account_default_enabled_fields())
ACCOUNT_ALWAYS_ENABLED_FIELDS = frozenset({"account_id", "comp_name", "platform", "is_active", "logo"})
ACCOUNT_PLATFORM_ENABLED_FIELDS = {
    str(code): frozenset(marketplace_account_enabled_fields(code) or ACCOUNT_DEFAULT_ENABLED_FIELDS)
    for code in ACCOUNT_PLATFORM_CODES
}
ACCOUNT_PLATFORM_FIELD_LABELS = {
    str(code): dict((marketplace_account_profile(code) or {}).get("fieldLabels") or {})
    for code in ACCOUNT_PLATFORM_CODES
}
ACCOUNT_PLATFORM_HEALTH_PROFILES = {
    str(code): dict(marketplace_account_health_profile(code) or {})
    for code in ACCOUNT_PLATFORM_CODES
}

__all__ = [
    "ACCOUNT_PLATFORM_CODES",
    "ACCOUNT_PLATFORM_CODE_SET",
    "ACCOUNT_PLATFORM_OPTIONS",
    "ACCOUNT_DEFAULT_PLATFORM_CODE",
    "ACCOUNT_PLATFORM_LABELS",
    "ACCOUNT_DEFAULT_PLATFORM_LABEL",
    "ACCOUNT_DEFAULT_ENABLED_FIELDS",
    "ACCOUNT_ALWAYS_ENABLED_FIELDS",
    "ACCOUNT_PLATFORM_ENABLED_FIELDS",
    "ACCOUNT_PLATFORM_FIELD_LABELS",
    "ACCOUNT_PLATFORM_HEALTH_PROFILES",
    "account_platform_code",
]
