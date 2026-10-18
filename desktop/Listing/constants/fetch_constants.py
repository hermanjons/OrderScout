from __future__ import annotations


# Trendyol Stage, onay bekleyen ilanlarda 1000 satırlık sayfaları zaman zaman
# 504 ile reddediyor. Küçük sayfa Stage akışını kararlı tutarken production
# hesabının mevcut hızlı çekim davranışını koruyor.
LISTING_DEFAULT_FETCH_PAGE_SIZE = 1000
LISTING_STAGE_FETCH_PAGE_SIZE = 200


__all__ = [
    "LISTING_DEFAULT_FETCH_PAGE_SIZE",
    "LISTING_STAGE_FETCH_PAGE_SIZE",
]
