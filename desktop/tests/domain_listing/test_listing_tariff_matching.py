from __future__ import annotations

import unittest

import Listing.processors.pipeline as listing_pipeline


class TestListingTariffMatching(unittest.TestCase):
    def test_match_cargo_tariff_for_fractional_desi_uses_next_integer_bucket(self) -> None:
        matched = listing_pipeline.match_cargo_tariff_for_listing(
            sale_price=100.0,
            dimensional_weight=1.5,
            platform_code="TRENDYOL",
            cargo_tariffs=[
                {
                    "tariffKey": "desi-1",
                    "platformCode": "TRENDYOL",
                    "minDesi": 1,
                    "maxDesi": 1,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 10.0,
                    "isVatIncluded": True,
                    "isActive": True,
                },
                {
                    "tariffKey": "desi-2",
                    "platformCode": "TRENDYOL",
                    "minDesi": 2,
                    "maxDesi": 2,
                    "minSalePrice": 0,
                    "maxSalePrice": None,
                    "amount": 12.0,
                    "isVatIncluded": True,
                    "isActive": True,
                },
            ],
        )

        self.assertIsNotNone(matched)
        self.assertEqual(matched["tariffKey"], "desi-2")
        self.assertEqual(matched["effectiveAmount"], 12.0)
