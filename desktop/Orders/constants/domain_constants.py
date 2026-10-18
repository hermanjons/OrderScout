from __future__ import annotations

from Core.constants.time_constants import TZ_GMT3

MAX_FETCH_WINDOW_DAYS = 30
MAX_FETCH_WINDOW_SAFETY_MINUTES = 10
INITIAL_FETCH_LOOKBACK_HOURS = 24 * MAX_FETCH_WINDOW_DAYS
INCREMENTAL_FETCH_OVERLAP_MINUTES = 10
NONFINAL_REFRESH_INTERVAL_HOURS = 6

# Canonical order lifecycle boundary shared by manual refresh logic and
# headless/agentic Orders reads.  Keep marketplace status codes in one domain
# constant so AI wrappers cannot silently define a different "nonfinal" set.
ORDER_FINAL_STATUS_CODES = (
    "Delivered",
    "Cancelled",
    "Returned",
    "UnDelivered",
    "UnDeliveredAndReturned",
    "UnSupplied",
)

__all__ = [
    "TZ_GMT3",
    "MAX_FETCH_WINDOW_DAYS",
    "MAX_FETCH_WINDOW_SAFETY_MINUTES",
    "INITIAL_FETCH_LOOKBACK_HOURS",
    "INCREMENTAL_FETCH_OVERLAP_MINUTES",
    "NONFINAL_REFRESH_INTERVAL_HOURS",
    "ORDER_FINAL_STATUS_CODES",
]
