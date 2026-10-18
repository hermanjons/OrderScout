from __future__ import annotations

from enum import Enum


class StockItemType(str, Enum):
    physical = "physical"
    service = "service"
    digital = "digital"
    other = "other"


class StockTxDirection(str, Enum):
    IN_ = "IN"
    OUT = "OUT"


class StockTxReason(str, Enum):
    manual_in = "manual_in"
    manual_out = "manual_out"
    adjustment = "adjustment"
    return_in = "return_in"
    order_out = "order_out"


class StockReferenceType(str, Enum):
    none = "none"
    order = "order"
    listing = "listing"
    purchase = "purchase"
    stocktake = "stocktake"


class StockError(str, Enum):
    not_found = "not_found"
    invalid = "invalid"
    insufficient_stock = "insufficient_stock"
    integrity = "integrity"
    db_error = "db_error"


ALLOW_NEGATIVE_STOCK_DEFAULT = False

UNIT_COST_INPUT_MODE_GROSS = "gross"
UNIT_COST_INPUT_MODE_NET = "net"
UNIT_COST_INPUT_MODE_MIXED = "mixed_explicit"
UNIT_COST_INPUT_MODE_LEGACY = "legacy"


__all__ = [
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
]
