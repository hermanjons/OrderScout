from __future__ import annotations

from unittest import TestCase

from Finance.processors.rule_loader import (
    build_finance_rule_handler_map,
    finance_rule_resolver_entry,
    get_finance_rule_callable,
    normalize_finance_rule_key,
    resolve_finance_rule,
)


class FinanceRuleLoaderTests(TestCase):
    def test_rule_key_normalization_trims_without_aliasing(self) -> None:
        self.assertEqual(normalize_finance_rule_key(" cargo_amount_matcher "), "cargo_amount_matcher")
        self.assertEqual(normalize_finance_rule_key(None), "")

    def test_rule_loader_exposes_cargo_amount_matcher_entry(self) -> None:
        entry = finance_rule_resolver_entry("cargo_amount_matcher")
        self.assertEqual(entry.get("module"), "Logistics.processors.cargo_amount_matcher")
        self.assertEqual(entry.get("callable"), "resolve_cargo_amount_matcher")

    def test_rule_loader_rejects_unknown_rule_key(self) -> None:
        with self.assertRaises(KeyError):
            get_finance_rule_callable("unknown_rule")

    def test_rule_loader_builds_handler_map_for_all_registered_rules(self) -> None:
        handlers = build_finance_rule_handler_map()
        self.assertIn("cargo_amount_matcher", handlers)
        self.assertTrue(callable(handlers["cargo_amount_matcher"]))

    def test_rule_loader_returns_callable_for_cargo_amount_matcher(self) -> None:
        resolver = get_finance_rule_callable("cargo_amount_matcher")
        self.assertTrue(callable(resolver))

    def test_rule_loader_resolves_cargo_amount_matcher(self) -> None:
        result = resolve_finance_rule(
            "cargo_amount_matcher",
            {"cargoProviderCode": "ARASMP"},
            {
                "platform_code": "TRENDYOL",
                "sale_price": 99.0,
                "effective_dimensional_weight": 1.0,
                "cargo_tariffs": [
                    {
                        "tariffKey": "aras-0-1",
                        "name": "Aras 0-1",
                        "platformCode": "TRENDYOL",
                        "cargoProviderCode": "ARASMP",
                        "cargoProviderName": "Aras Kargo Marketplace",
                        "minDesi": 0,
                        "maxDesi": 1,
                        "minSalePrice": 0,
                        "maxSalePrice": 200,
                        "amount": 10,
                        "isVatIncluded": True,
                        "isActive": True,
                    }
                ],
            },
        )
        self.assertEqual(result.get("amount"), 10.0)
        self.assertEqual(((result.get("meta") or {}).get("ruleKey")), "cargo_amount_matcher")
