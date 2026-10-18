from __future__ import annotations

from Logistics.constants.paths import cargo_tariffs_default_file
from Logistics.processors.catalog import (
    builtin_cargo_provider_records,
    cargo_provider_code_for_source_id,
    cargo_provider_name_for_code,
    cargo_provider_options,
    cargo_provider_record_for_source_id,
    cargo_provider_records,
    cargo_provider_simple_records,
    cargo_provider_source_id_for_code,
    changeable_cargo_provider_records,
    clear_cargo_provider_catalog_cache,
    default_cargo_tariff_records,
    default_cargo_provider_logo,
    default_cargo_tariffs_file,
)


LOGISTICS_DEFAULT_CARGO_PROVIDER_LOGO = default_cargo_provider_logo()
LOGISTICS_DEFAULT_CARGO_TARIFFS_FILE = cargo_tariffs_default_file()

__all__ = [
    "LOGISTICS_DEFAULT_CARGO_PROVIDER_LOGO",
    "LOGISTICS_DEFAULT_CARGO_TARIFFS_FILE",
    "builtin_cargo_provider_records",
    "cargo_provider_code_for_source_id",
    "cargo_provider_name_for_code",
    "cargo_provider_options",
    "cargo_provider_record_for_source_id",
    "cargo_provider_records",
    "cargo_provider_simple_records",
    "cargo_provider_source_id_for_code",
    "changeable_cargo_provider_records",
    "clear_cargo_provider_catalog_cache",
    "default_cargo_tariff_records",
    "default_cargo_provider_logo",
    "default_cargo_tariffs_file",
]
