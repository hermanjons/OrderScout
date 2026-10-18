from unittest import TestCase

from Logistics.processors.cargo_amount_matcher import match_cargo_amount, resolve_cargo_amount_matcher


class TestCargoAmountMatcher(TestCase):
    def test_resolver_honors_selected_provider_code_even_when_other_tariff_is_cheaper(self) -> None:
        result = resolve_cargo_amount_matcher(
            {
                "ruleKey": "cargo_amount_matcher",
                "cargoProviderCode": "ARASMP",
                "cargoProviderName": "Aras Kargo Marketplace",
            },
            {
                "sale_price": 114.99,
                "effective_dimensional_weight": None,
                "platform_code": "TRENDYOL",
                "cargo_tariffs": [
                    {
                        "tariffKey": "ptt-0",
                        "name": "PTT 0 Desi",
                        "platformCode": "TRENDYOL",
                        "cargoProviderCode": "PTTMP",
                        "cargoProviderName": "PTT Kargo Marketplace",
                        "minDesi": 0,
                        "maxDesi": 0,
                        "amount": 50.0,
                        "isVatIncluded": False,
                        "vatRate": 20.0,
                        "isActive": True,
                    },
                    {
                        "tariffKey": "aras-0",
                        "name": "Aras 0 Desi",
                        "platformCode": "TRENDYOL",
                        "cargoProviderCode": "ARASMP",
                        "cargoProviderName": "Aras Kargo Marketplace",
                        "minDesi": 0,
                        "maxDesi": 0,
                        "amount": 77.54,
                        "isVatIncluded": False,
                        "vatRate": 20.0,
                        "isActive": True,
                    },
                ],
            },
        )

        self.assertAlmostEqual(float(result.get("amount") or 0.0), 93.048, places=3)
        self.assertEqual(((result.get("meta") or {}).get("matchedTariffKey")), "aras-0")
        self.assertEqual(((result.get("meta") or {}).get("selectedCargoProviderCode")), "ARASMP")

    def test_resolver_supports_legacy_provider_code_aliases(self) -> None:
        result = resolve_cargo_amount_matcher(
            {
                "ruleKey": "cargo_amount_matcher",
                "cargoProviderCode": "ARAS",
                "cargoProviderName": "Aras Kargo Marketplace",
            },
            {
                "sale_price": 114.99,
                "effective_dimensional_weight": 0,
                "platform_code": "TRENDYOL",
                "cargo_tariffs": [
                    {
                        "tariffKey": "ptt-0",
                        "name": "PTT 0 Desi",
                        "platformCode": "TRENDYOL",
                        "cargoProviderCode": "PTTMP",
                        "cargoProviderName": "PTT Kargo Marketplace",
                        "minDesi": 0,
                        "maxDesi": 0,
                        "amount": 50.0,
                        "isVatIncluded": False,
                        "vatRate": 20.0,
                        "isActive": True,
                    },
                    {
                        "tariffKey": "aras-0",
                        "name": "Aras 0 Desi",
                        "platformCode": "TRENDYOL",
                        "cargoProviderCode": "ARASMP",
                        "cargoProviderName": "Aras Kargo Marketplace",
                        "minDesi": 0,
                        "maxDesi": 0,
                        "amount": 77.54,
                        "isVatIncluded": False,
                        "vatRate": 20.0,
                        "isActive": True,
                    },
                ],
            },
        )

        self.assertEqual(((result.get("meta") or {}).get("matchedTariffKey")), "aras-0")

    def test_matcher_uses_global_tariff_when_platform_specific_tariff_missing(self) -> None:
        match = match_cargo_amount(
            sale_price=50,
            dimensional_weight=1,
            platform_code="TRENDYOL",
            cargo_tariffs=[
                {
                    "tariffKey": "global-1",
                    "name": "Global 1 Desi",
                    "platformCode": "",
                    "minDesi": 0,
                    "maxDesi": 1,
                    "amount": 12.0,
                    "isVatIncluded": True,
                    "isActive": True,
                },
                {
                    "tariffKey": "hb-1",
                    "name": "HB 1 Desi",
                    "platformCode": "HEPSIBURADA",
                    "minDesi": 0,
                    "maxDesi": 1,
                    "amount": 1.0,
                    "isVatIncluded": True,
                    "isActive": True,
                },
            ],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.get("tariffKey"), "global-1")

    def test_matcher_skips_inactive_and_invalid_amount_tariffs(self) -> None:
        result = resolve_cargo_amount_matcher(
            {},
            {
                "platform_code": "TRENDYOL",
                "sale_price": 50,
                "effective_dimensional_weight": 1,
                "cargo_tariffs": [
                    {
                        "tariffKey": "inactive",
                        "platformCode": "TRENDYOL",
                        "minDesi": 0,
                        "maxDesi": 1,
                        "amount": 1.0,
                        "isActive": False,
                    },
                    {
                        "tariffKey": "bad-amount",
                        "platformCode": "TRENDYOL",
                        "minDesi": 0,
                        "maxDesi": 1,
                        "amount": "not-a-number",
                        "isActive": True,
                    },
                ],
            },
        )

        self.assertIn("missing_reason", result)
