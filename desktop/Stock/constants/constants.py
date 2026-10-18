# Stock/constants/constants.py
from __future__ import annotations

from Core.processors.catalog import (
    city_options_by_country,
    country_options,
    country_phone_code_by_country,
    currency_options,
    phone_dial_code_options,
    unit_options,
)
from Stock.constants.catalog_constants import ITEM_TYPE_OPTIONS
from Stock.constants.domain_constants import (
    ALLOW_NEGATIVE_STOCK_DEFAULT,
    StockError,
    StockItemType,
    StockReferenceType,
    StockTxDirection,
    StockTxReason,
    UNIT_COST_INPUT_MODE_GROSS,
    UNIT_COST_INPUT_MODE_LEGACY,
    UNIT_COST_INPUT_MODE_MIXED,
    UNIT_COST_INPUT_MODE_NET,
)

UNIT_OPTIONS = unit_options()
CURRENCY_OPTIONS = currency_options()
COUNTRY_OPTIONS = country_options()
CITY_OPTIONS_BY_COUNTRY = city_options_by_country()
COUNTRY_PHONE_CODE_BY_COUNTRY = country_phone_code_by_country()
PHONE_DIAL_CODE_OPTIONS = phone_dial_code_options()

__all__ = [
    "COUNTRY_PHONE_CODE_BY_COUNTRY",
    "CITY_OPTIONS_BY_COUNTRY",
    "COUNTRY_OPTIONS",
    "CURRENCY_OPTIONS",
    "PHONE_DIAL_CODE_OPTIONS",
    "UNIT_OPTIONS",
    "StockItemType",
    "StockTxDirection",
    "StockTxReason",
    "StockReferenceType",
    "StockError",
    "ALLOW_NEGATIVE_STOCK_DEFAULT",
    "UNIT_COST_INPUT_MODE_GROSS",
    "UNIT_COST_INPUT_MODE_NET",
    "UNIT_COST_INPUT_MODE_MIXED",
    "UNIT_COST_INPUT_MODE_LEGACY",
    "ITEM_TYPE_OPTIONS",
]
