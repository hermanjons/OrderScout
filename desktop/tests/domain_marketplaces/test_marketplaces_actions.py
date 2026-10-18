from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from sqlmodel import SQLModel
from sqlmodel import Session, select

import Marketplaces.processors.catalog as marketplaces_catalog
import Marketplaces.views.actions as marketplaces_actions
from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Logistics.models.models import LogisticsCargoProvider


def _prepare_db(db_path: Path) -> str:
    engine = get_engine(str(db_path))
    SQLModel.metadata.create_all(engine)
    return str(db_path)


class TestMarketplacesActions(TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.default_file = root / "default_marketplaces.json"
        self.override_file = root / "marketplace_label_overrides.user.json"
        self.trendyol_config_file = root / "trendyol" / "platform_api_config.json"
        self.hepsiburada_config_file = root / "hepsiburada" / "platform_api_config.json"
        self.trendyol_cargo_config_file = root / "trendyol" / "platform_cargo_config.json"
        self.hepsiburada_cargo_config_file = root / "hepsiburada" / "platform_cargo_config.json"

        self.default_file.write_text(
            json.dumps(
                [
                    {
                        "code": "TRENDYOL",
                        "label": "Trendyol",
                        "description": "Varsayilan kanal",
                        "logoPath": "images/marketplaces-icon.png",
                        "source_id": 1,
                        "isActive": True,
                        "supportsOrders": True,
                        "supportsReturns": True,
                        "supportsListings": True,
                        "supportsCargoProviderChange": True,
                        "supportsStockPush": True,
                        "supportsPricePush": True,
                        "supportsHealthCheck": True,
                    },
                    {
                        "code": "HEPSIBURADA",
                        "label": "Hepsiburada",
                        "description": "Hazir kanal",
                        "logoPath": "images/comp_ico.png",
                        "source_id": 2,
                        "isActive": True,
                        "supportsOrders": False,
                        "supportsReturns": False,
                        "supportsListings": False,
                        "supportsCargoProviderChange": False,
                        "supportsStockPush": False,
                        "supportsPricePush": False,
                        "supportsHealthCheck": False,
                    },
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.trendyol_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.hepsiburada_config_file.parent.mkdir(parents=True, exist_ok=True)

        self.trendyol_config_file.write_text(
            json.dumps(
                {
                    "commonStatusMessages": {"200": "Istek basariyla tamamlandi.", "*": "Istek basarisiz oldu."},
                    "account": {
                        "authStrategy": "api_key_secret",
                        "enabledFields": ["seller_id", "comp_name", "api_key", "api_secret", "extra_config"],
                        "fieldLabels": {
                            "seller_id": "Satici ID",
                            "account_id": "Satici ID",
                            "comp_name": "Sirket Adi",
                        },
                    },
                    "healthCheck": {
                        "method": "GET",
                        "baseUrl": "https://apigw.trendyol.com",
                        "path": "/integration/product/sellers/{account_id}/products/approved",
                        "queryDefaults": {"page": 0, "size": 1},
                        "successStatusCodes": [200],
                        "requiredCredentials": ["account_id", "api_key", "api_secret"],
                        "authStrategy": "basic_api_key_secret",
                        "statusMessages": {"200": "API baglanti kontrolu basarili.", "*": "API baglanti kontrolu basarisiz."},
                    },
                    "scopes": {
                        "finance": {
                            "defaultFetchDays": 14,
                            "services": {
                                "settlements": {"label": "Uzlasma Hareketleri", "transactionTypes": ["Sale", "Return"]},
                                "otherfinancials": {"label": "Diger Finansal Hareketler", "transactionTypes": ["PaymentOrder"]},
                                "cargo_invoice_items": {"label": "Kargo Fatura Kalemleri", "transactionTypes": []},
                            },
                        }
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.hepsiburada_config_file.write_text(
            json.dumps(
                {
                    "account": {
                        "authStrategy": "api_key_secret",
                        "enabledFields": ["seller_id", "comp_name", "api_key", "api_secret", "extra_config"],
                        "fieldLabels": {"seller_id": "Satici ID", "account_id": "Satici ID", "comp_name": "Sirket Adi"},
                    },
                    "scopes": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.trendyol_cargo_config_file.write_text(
            json.dumps({"form": {"visibleFields": ["cargoProvider", "desiRange", "salePriceRange", "amount", "vatRate"]}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.hepsiburada_cargo_config_file.write_text(
            json.dumps({"form": {"visibleFields": ["cargoProvider", "desiRange", "amount", "vatRate"]}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._patches = [
            patch.object(marketplaces_catalog, "DEFAULT_MARKETPLACES_FILE", self.default_file),
            patch.object(marketplaces_catalog, "MARKETPLACE_LABEL_OVERRIDES_FILE", self.override_file),
            patch.object(
                marketplaces_catalog,
                "platform_api_config_file",
                lambda code: root / str(code or "").strip().casefold() / "platform_api_config.json",
            ),
            patch.object(
                marketplaces_catalog,
                "platform_cargo_config_file",
                lambda code: root / str(code or "").strip().casefold() / "platform_cargo_config.json",
            ),
            patch.object(
                marketplaces_catalog,
                "ensure_marketplaces_paths",
                lambda: self.override_file.parent.mkdir(parents=True, exist_ok=True),
            ),
        ]
        for item in self._patches:
            item.start()
            self.addCleanup(item.stop)
        marketplaces_catalog._invalidate_marketplace_cache()

    def tearDown(self) -> None:
        marketplaces_catalog._invalidate_marketplace_cache()
        super().tearDown()

    def test_load_marketplaces_returns_builtin_suggestions_when_db_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "marketplaces.sqlite3")
            result = marketplaces_actions.load_marketplaces(db_name=db_name)
            self.assertTrue(result.success, result.message)
            records = (result.data or {}).get("records", []) or []
            self.assertEqual({row["code"] for row in records}, {"TRENDYOL", "HEPSIBURADA"})
            self.assertTrue(all(bool(row.get("isBuiltin")) for row in records))
            self.assertTrue(all(not bool(row.get("isBuiltinAccepted")) for row in records))

    def test_catalog_normalizes_marketplace_code_for_storage_keys(self) -> None:
        self.assertEqual(marketplaces_catalog.normalize_marketplace_code(" trendyol-store 42 "), "TRENDYOL_STORE_42")
        self.assertEqual(marketplaces_catalog.normalize_marketplace_code("hepsi/burada"), "HEPSI_BURADA")

    def test_catalog_coerces_marketplace_bool_text(self) -> None:
        self.assertTrue(marketplaces_catalog.coerce_marketplace_bool("evet"))
        self.assertTrue(marketplaces_catalog.coerce_marketplace_bool("ON"))
        self.assertFalse(marketplaces_catalog.coerce_marketplace_bool("hayir", default=True))
        self.assertTrue(marketplaces_catalog.coerce_marketplace_bool("?", default=True))

    def test_catalog_coerce_marketplace_row_rejects_incomplete_rows(self) -> None:
        self.assertIsNone(marketplaces_catalog.coerce_marketplace_row({"code": "X"}, builtin=True))
        row = marketplaces_catalog.coerce_marketplace_row(
            {
                "code": " custom market ",
                "label": "Custom Market",
                "logoPath": "images\\custom.png",
                "source_id": "55",
                "isActive": "false",
            },
            builtin=False,
        )
        self.assertEqual(row["code"], "CUSTOM_MARKET")
        self.assertEqual(row["logoPath"], "images/custom.png")
        self.assertEqual(row["sourceId"], 55)
        self.assertFalse(bool(row["isActive"]))

    def test_accept_marketplace_persists_builtin_into_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "marketplaces.sqlite3")
            result = marketplaces_actions.accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(result.success, result.message)

            reloaded = marketplaces_actions.load_marketplaces(db_name=db_name)
            self.assertTrue(reloaded.success, reloaded.message)
            rows = (reloaded.data or {}).get("records", []) or []
            trendyol = next(row for row in rows if str(row.get("code") or "") == "TRENDYOL")
            self.assertTrue(bool(trendyol.get("isBuiltinAccepted")))
            self.assertEqual(str(trendyol.get("sourceCode") or ""), "accepted")

    def test_save_marketplace_requires_acceptance_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "marketplaces.sqlite3")
            result = marketplaces_actions.save_marketplace(
                payload={"code": "TRENDYOL", "label": "Trendyol TR"},
                db_name=db_name,
            )
            self.assertFalse(result.success)
            self.assertIn("kabul", result.message.casefold())

    def test_save_marketplace_updates_accepted_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "marketplaces.sqlite3")
            accept = marketplaces_actions.accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accept.success, accept.message)

            save = marketplaces_actions.save_marketplace(
                payload={"code": "TRENDYOL", "label": "Trendyol TR", "description": "DB etiketi"},
                db_name=db_name,
            )
            self.assertTrue(save.success, save.message)

            rows = (marketplaces_actions.load_marketplaces(db_name=db_name).data or {}).get("records", []) or []
            trendyol = next(row for row in rows if str(row.get("code") or "") == "TRENDYOL")
            self.assertEqual(str(trendyol.get("label") or ""), "Trendyol TR")

    def test_set_marketplaces_active_state_updates_accepted_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "marketplaces.sqlite3")
            accept = marketplaces_actions.accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accept.success, accept.message)

            result = marketplaces_actions.set_marketplaces_active_state(
                codes=["TRENDYOL"],
                is_active=False,
                db_name=db_name,
            )
            self.assertTrue(result.success, result.message)
            rows = (marketplaces_actions.load_marketplaces(db_name=db_name).data or {}).get("records", []) or []
            trendyol = next(row for row in rows if str(row.get("code") or "") == "TRENDYOL")
            self.assertFalse(bool(trendyol.get("isActive")))

    def test_accept_marketplace_backfills_related_platform_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_name = _prepare_db(Path(tmpdir) / "marketplaces.sqlite3")
            engine = get_engine(db_name)
            with Session(engine) as session:
                session.add(ApiAccount(account_id="100", comp_name="Acme", platform="TRENDYOL"))
                session.add(
                    LogisticsCargoProvider(
                        platformCode="TRENDYOL",
                        cargoProviderCode="FAST",
                        cargoProviderName="Fast Cargo",
                    )
                )
                session.commit()

            accept = marketplaces_actions.accept_marketplace_record(code="TRENDYOL", db_name=db_name)
            self.assertTrue(accept.success, accept.message)

            with Session(engine) as session:
                account = session.exec(select(ApiAccount).where(ApiAccount.platform == "TRENDYOL")).first()
                provider = session.exec(
                    select(LogisticsCargoProvider).where(LogisticsCargoProvider.platformCode == "TRENDYOL")
                ).first()
                self.assertIsNotNone(account)
                self.assertIsNotNone(provider)
                self.assertGreater(int(getattr(account, "platform_id", 0) or 0), 0)
                self.assertGreater(int(getattr(provider, "platform_id", 0) or 0), 0)

    def test_marketplace_account_health_profile_returns_trendyol_endpoint(self) -> None:
        profile = marketplaces_catalog.marketplace_account_health_profile("TRENDYOL")
        self.assertEqual(profile.get("platformCode"), "TRENDYOL")
        self.assertEqual(profile.get("authStrategy"), "basic_api_key_secret")
        self.assertIn("{account_id}", str(profile.get("urlTemplate") or ""))

    def test_marketplace_finance_scope_metadata_returns_service_options_and_limits(self) -> None:
        options = marketplaces_catalog.marketplace_finance_service_options("TRENDYOL", include_all=False)
        tx_types = marketplaces_catalog.marketplace_finance_transaction_types("TRENDYOL", "settlements")
        default_fetch_days = marketplaces_catalog.marketplace_finance_scope_int("TRENDYOL", "defaultFetchDays", 0)

        self.assertEqual(
            options,
            [
                ("Uzlasma Hareketleri", "settlements"),
                ("Diger Finansal Hareketler", "otherfinancials"),
                ("Kargo Fatura Kalemleri", "cargo_invoice_items"),
            ],
        )
        self.assertEqual(tx_types, ["Sale", "Return"])
        self.assertEqual(default_fetch_days, 14)
