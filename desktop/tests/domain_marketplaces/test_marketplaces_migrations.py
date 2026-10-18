from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_ops import table_columns
from Core.db.migration_runner import run_domain_migrations
from Marketplaces.models.migrations import MIGRATIONS


class TestMarketplacesMigrations(unittest.TestCase):
    def test_marketplace_rebuild_drops_legacy_capability_columns(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE marketplace (
                        pk INTEGER PRIMARY KEY,
                        code TEXT NOT NULL,
                        label TEXT NOT NULL,
                        description TEXT,
                        logoPath TEXT,
                        supportsOrders BOOLEAN,
                        supportsReturns BOOLEAN,
                        supportsListings BOOLEAN,
                        supportsCargoProviderChange BOOLEAN,
                        supportsStockPush BOOLEAN,
                        supportsPricePush BOOLEAN,
                        supportsHealthCheck BOOLEAN,
                        isActive BOOLEAN,
                        createdAt TEXT,
                        updatedAt TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO marketplace (
                        pk,
                        code,
                        label,
                        description,
                        logoPath,
                        supportsOrders,
                        supportsReturns,
                        supportsListings,
                        supportsCargoProviderChange,
                        supportsStockPush,
                        supportsPricePush,
                        supportsHealthCheck,
                        isActive,
                        createdAt,
                        updatedAt
                    )
                    VALUES (
                        1,
                        'TRENDYOL',
                        'Trendyol',
                        'Legacy kanal',
                        'logo.png',
                        1,
                        1,
                        1,
                        1,
                        1,
                        1,
                        1,
                        1,
                        '2026-04-10T10:00:00',
                        '2026-04-10T10:00:00'
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)

            self.assertIn("marketplaces_0001_drop_capability_flags", applied)
            columns = table_columns(conn, "marketplace")
            self.assertNotIn("supportsOrders", columns)
            self.assertNotIn("supportsReturns", columns)
            self.assertNotIn("supportsListings", columns)
            self.assertNotIn("supportsCargoProviderChange", columns)
            self.assertNotIn("supportsStockPush", columns)
            self.assertNotIn("supportsPricePush", columns)
            self.assertNotIn("supportsHealthCheck", columns)
            row = conn.execute(
                text("SELECT code, label, isActive FROM marketplace WHERE pk = 1")
            ).fetchone()
            self.assertEqual(tuple(row), ("TRENDYOL", "Trendyol", 1))
