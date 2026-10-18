from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from sqlmodel import SQLModel

from Core.utils.model_utils import get_engine
from Logistics.views.actions import (
    accept_logistics_cargo_provider_record,
    delete_logistics_cargo_provider_record,
    load_logistics_cargo_providers,
    logistics_cargo_provider_platform_options,
    save_logistics_cargo_provider_record,
)
from Marketplaces.views.actions import accept_marketplace_record


def _prepare_db(db_path: Path) -> str:
    engine = get_engine(str(db_path))
    SQLModel.metadata.create_all(engine)
    return str(db_path)


class TestLogisticsActions(TestCase):
    def test_trendyol_default_tariffs_include_barem_support_rows(self) -> None:
        json_path = Path(__file__).resolve().parents[2] / "Logistics" / "constants" / "files" / "cargo_tariffs.default.json"
        payload = json.loads(
            json_path.read_text(encoding="utf-8")
        )
        records = payload.get("records", []) or []
        support_rows = [
            row for row in records
            if str(row.get("platform") or "") == "TRENDYOL"
            and str(row.get("cargoProviderCode") or "") == "ARASMP"
            and float(row.get("minSalePrice") or 0.0) == 0.0
            and float(row.get("maxSalePrice") or 0.0) == 199.99
        ]
        self.assertEqual(len(support_rows), 1)
        self.assertEqual(float(support_rows[0].get("amount") or 0.0), 42.91)

    def test_trendyol_default_tariffs_follow_pdf_availability_ranges(self) -> None:
        json_path = Path(__file__).resolve().parents[2] / "Logistics" / "constants" / "files" / "cargo_tariffs.default.json"
        payload = json.loads(
            json_path.read_text(encoding="utf-8")
        )
        records = payload.get("records", []) or []
        tex_101 = [
            row for row in records
            if str(row.get("platform") or "") == "TRENDYOL"
            and str(row.get("cargoProviderCode") or "") == "TEXMP"
            and row.get("minDesi") == 101
            and row.get("minSalePrice") is None
        ]
        kolay_500 = [
            row for row in records
            if str(row.get("platform") or "") == "TRENDYOL"
            and str(row.get("cargoProviderCode") or "") == "KOLAYGELSINMP"
            and row.get("minDesi") == 500
            and row.get("minSalePrice") is None
        ]
        self.assertEqual(tex_101, [])
        self.assertEqual(len(kolay_500), 1)

    def test_platform_options_come_from_accepted_marketplaces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "logistics.sqlite3")
            accepted = accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accepted.success, accepted.message)

            options = logistics_cargo_provider_platform_options(include_all=False, db_name=db_name)
            self.assertIn(("Trendyol", "TRENDYOL"), options)

    def test_load_logistics_cargo_providers_lists_builtin_suggestions_for_accepted_platform(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "logistics.sqlite3")
            accepted = accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accepted.success, accepted.message)

            result = load_logistics_cargo_providers(platform_code="TRENDYOL", db_name=db_name)
            self.assertTrue(result.success, result.message)
            records = (result.data or {}).get("records", []) or []
            self.assertTrue(records)
            self.assertTrue(all(str(row.get("platformCode") or "") == "TRENDYOL" for row in records))
            self.assertTrue(any(not bool(row.get("isBuiltinAccepted")) for row in records))

    def test_custom_cargo_provider_is_saved_to_db_and_loaded(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "logistics.sqlite3")
            accepted = accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accepted.success, accepted.message)

            save_result = save_logistics_cargo_provider_record(
                {
                    "cargoProviderName": "Benim Ozel Kargo",
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "BENOZEL",
                    "note": "Kullanici kaydi",
                    "logoPath": None,
                },
                db_name=db_name,
            )
            self.assertTrue(save_result.success, save_result.message)

            load_result = load_logistics_cargo_providers(platform_code="TRENDYOL", db_name=db_name)
            self.assertTrue(load_result.success, load_result.message)
            records = (load_result.data or {}).get("records", []) or []
            custom = next((row for row in records if str(row.get("cargoProviderCode") or "") == "BENOZEL"), None)
            self.assertIsNotNone(custom)
            self.assertEqual(str((custom or {}).get("sourceLabel") or ""), "Veritabani")
            self.assertFalse(bool((custom or {}).get("isBuiltin")))

    def test_custom_cargo_provider_can_be_deleted_from_db(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "logistics.sqlite3")
            accepted = accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accepted.success, accepted.message)

            save_result = save_logistics_cargo_provider_record(
                {
                    "cargoProviderName": "Silinecek Kargo",
                    "platformCode": "TRENDYOL",
                    "cargoProviderCode": "SILKARGO",
                    "note": "Silme testi",
                    "logoPath": None,
                },
                db_name=db_name,
            )
            self.assertTrue(save_result.success, save_result.message)
            provider_pk = (save_result.data or {}).get("pk")
            self.assertTrue(provider_pk)

            delete_result = delete_logistics_cargo_provider_record(
                {"pk": provider_pk, "platformCode": "TRENDYOL", "cargoProviderCode": "SILKARGO"},
                db_name=db_name,
            )
            self.assertTrue(delete_result.success, delete_result.message)

            load_result = load_logistics_cargo_providers(platform_code="TRENDYOL", search="SILKARGO", db_name=db_name)
            self.assertTrue(load_result.success, load_result.message)
            records = (load_result.data or {}).get("records", []) or []
            self.assertFalse(any(str(row.get("cargoProviderCode") or "") == "SILKARGO" for row in records))

    def test_builtin_cargo_provider_can_be_accepted_into_db(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "logistics.sqlite3")
            accepted = accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accepted.success, accepted.message)

            load_result = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=db_name)
            self.assertTrue(load_result.success, load_result.message)
            builtin = next((row for row in (load_result.data or {}).get("records", []) or [] if str(row.get("cargoProviderCode") or "") == "TEXMP"), None)
            self.assertIsNotNone(builtin)
            self.assertFalse(bool((builtin or {}).get("isBuiltinAccepted")))

            accept_provider = accept_logistics_cargo_provider_record(dict(builtin or {}), db_name=db_name)
            self.assertTrue(accept_provider.success, accept_provider.message)

            reloaded = load_logistics_cargo_providers(platform_code="TRENDYOL", search="texmp", db_name=db_name)
            self.assertTrue(reloaded.success, reloaded.message)
            rows = (reloaded.data or {}).get("records", []) or []
            accepted_row = next((row for row in rows if str(row.get("cargoProviderCode") or "") == "TEXMP"), None)
            self.assertIsNotNone(accepted_row)
            self.assertTrue(bool((accepted_row or {}).get("isBuiltinAccepted")))
