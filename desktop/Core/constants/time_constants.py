from __future__ import annotations

from datetime import timedelta, timezone


TZ_ISTANBUL = timezone(timedelta(hours=3), name="Europe/Istanbul")

# Backward-compatible public alias while domain callers migrate to the semantic name.
TZ_GMT3 = TZ_ISTANBUL


__all__ = ["TZ_GMT3", "TZ_ISTANBUL"]
