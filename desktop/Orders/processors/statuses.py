"""Shared shipment-status labels for manual views and domain observations."""
from __future__ import annotations

import re

from Orders.constants.trendyol.constants import TRENDYOL_ORDER_STATUS_ALIASES, TRENDYOL_STATUS_LABELS


def normalize_order_status_code(status_code: str) -> str:
    code = str(status_code or "").strip()
    if not code:
        return ""
    for alias_code, canonical_code in TRENDYOL_ORDER_STATUS_ALIASES.items():
        if str(alias_code).casefold() == code.casefold():
            return str(canonical_code)
    return code


def humanize_order_status_code(status_code: str) -> str:
    text = str(status_code or "").strip()
    if not text:
        return "-"
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"(?<!^)(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "-"


def order_status_label_for_code(status_code: str) -> str:
    code = normalize_order_status_code(status_code)
    if not code:
        return "-"
    for key, value in TRENDYOL_STATUS_LABELS.items():
        if str(key).casefold() == code.casefold():
            return str(value)
    return humanize_order_status_code(code)
