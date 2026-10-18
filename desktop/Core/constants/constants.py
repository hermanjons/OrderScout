from __future__ import annotations

from Core.processors.catalog import country_directory, currency_options, unit_options


UNIT_OPTIONS = unit_options()
CURRENCY_OPTIONS = currency_options()
COUNTRY_OPTIONS, CITY_OPTIONS_BY_COUNTRY, COUNTRY_PHONE_CODE_BY_COUNTRY, PHONE_DIAL_CODE_OPTIONS = country_directory()

__all__ = [
    "CITY_OPTIONS_BY_COUNTRY",
    "COUNTRY_OPTIONS",
    "COUNTRY_PHONE_CODE_BY_COUNTRY",
    "CURRENCY_OPTIONS",
    "PHONE_DIAL_CODE_OPTIONS",
    "UNIT_OPTIONS",
]
