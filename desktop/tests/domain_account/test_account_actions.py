from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import ANY, patch

from Account.views.actions import (
    account_platform_options,
    account_visual_status,
    get_platform_enabled_fields,
    submit_company_values,
    validate_form_values,
)
from Marketplaces.constants.catalog_constants import marketplace_account_field_label, platform_select_options


class TestAccountActions(TestCase):
    def test_account_platform_options_follow_marketplaces_catalog(self) -> None:
        self.assertEqual(account_platform_options(), platform_select_options(include_all=False))

    def test_validate_form_values_canonicalizes_platform_label(self) -> None:
        payload = {
            "account_id": "10001",
            "comp_name": "Acme",
            "platform": "Trendyol",
        }

        with patch(
            "Account.views.actions.platform_record_for_code",
            return_value={"code": "TRENDYOL", "label": "Trendyol"},
        ):
            result = validate_form_values(payload)

        self.assertTrue(result.success, result.message)
        self.assertEqual(payload["platform"], "TRENDYOL")

    def test_validate_form_values_rejects_platform_when_marketplace_is_not_accepted(self) -> None:
        payload = {
            "account_id": "10001",
            "comp_name": "Acme",
            "platform": "Trendyol",
        }

        with patch("Account.views.actions.platform_record_for_code", return_value=None):
            result = validate_form_values(payload)

        self.assertFalse(result.success)
        self.assertIn("Geçersiz platform", result.message)

    def test_account_field_rules_follow_trendyol_profile_and_unknown_platform_falls_back(self) -> None:
        fallback_fields = get_platform_enabled_fields("AMAZON")
        trendyol_fields = get_platform_enabled_fields("TRENDYOL")

        self.assertIn("seller_id", trendyol_fields)
        self.assertNotIn("token", trendyol_fields)
        self.assertTrue(fallback_fields)

    def test_account_visual_status_turns_passive_when_token_is_invalid(self) -> None:
        active_broken = SimpleNamespace(is_active=True, token_valid=False)
        inactive_ok = SimpleNamespace(is_active=False, token_valid=True)
        active_ok = SimpleNamespace(is_active=True, token_valid=True)

        self.assertEqual(account_visual_status(active_broken), "Pasif")
        self.assertEqual(account_visual_status(inactive_ok), "Pasif")
        self.assertEqual(account_visual_status(active_ok), "Aktif")

    def test_account_field_labels_are_resolved_from_marketplaces_profiles(self) -> None:
        self.assertEqual(marketplace_account_field_label("TRENDYOL", "account_id"), "Satıcı ID")
        self.assertEqual(marketplace_account_field_label("TRENDYOL", "comp_name"), "Şirket Adı")

    def test_submit_company_values_create_runs_health_check_before_save(self) -> None:
        payload = {
            "account_id": "10001",
            "comp_name": "Acme",
            "platform": "TRENDYOL",
            "api_key": "key",
            "api_secret": "secret",
            "integration_code": "INT-1",
            "extra_config": {"region": "tr"},
        }

        with patch("Account.views.actions.check_company_api_health") as mock_health, patch(
            "Account.views.actions.save_company_to_db"
        ) as mock_save:
            mock_health.return_value = SimpleNamespace(success=True, data={"platform": "TRENDYOL"}, error=None)
            mock_save.return_value = SimpleNamespace(success=True, data={}, message="saved")

            result = submit_company_values(account_pk=None, values=dict(payload))

        self.assertTrue(result.success)
        mock_health.assert_called_once()
        mock_save.assert_called_once()

    def test_submit_company_values_update_skips_health_check_and_updates_record(self) -> None:
        payload = {
            "account_id": "10001",
            "comp_name": "Acme Updated",
            "platform": "TRENDYOL",
        }

        with patch("Account.views.actions.check_company_api_health") as mock_health, patch(
            "Account.views.actions.update_company"
        ) as mock_update:
            mock_update.return_value = SimpleNamespace(success=True, data={}, message="updated")

            result = submit_company_values(account_pk=7, values=dict(payload))

        self.assertTrue(result.success)
        mock_health.assert_not_called()
        mock_update.assert_called_once_with(7, ANY)
