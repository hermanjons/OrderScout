from __future__ import annotations

from unittest import TestCase

from Core.constants import constants


class TestCoreConstants(TestCase):
    def test_country_directory_exposes_country_city_and_phone_code(self) -> None:
        self.assertIn("Turkiye", constants.COUNTRY_OPTIONS)
        self.assertEqual(constants.COUNTRY_PHONE_CODE_BY_COUNTRY.get("Turkiye"), "+90")
        self.assertIn("Istanbul", constants.CITY_OPTIONS_BY_COUNTRY.get("Turkiye", []))
        self.assertIn("+90", constants.PHONE_DIAL_CODE_OPTIONS)

    def test_currency_options_loaded_from_core(self) -> None:
        self.assertIn("TRY", constants.CURRENCY_OPTIONS)
        self.assertIn("EUR", constants.CURRENCY_OPTIONS)
