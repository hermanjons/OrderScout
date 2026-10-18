from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Account.models.migrations import MIGRATIONS
from Core.db.migration_runner import run_domain_migrations


class TestAccountMigrations(unittest.TestCase):
    def test_apiaccount_legacy_columns_are_moved_to_new_schema(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE apiaccount (
                        pk INTEGER PRIMARY KEY,
                        seller_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        logo TEXT,
                        integration_code TEXT,
                        api_key TEXT,
                        api_secret TEXT,
                        token TEXT,
                        extra_config TEXT,
                        created_at TEXT NOT NULL,
                        last_used_at TEXT,
                        encrypted INTEGER DEFAULT 0,
                        token_valid INTEGER DEFAULT 1,
                        is_active INTEGER DEFAULT 1,
                        sync_uuid TEXT,
                        sync_version INTEGER DEFAULT 1,
                        sync_updated_at TEXT,
                        sync_deleted_at TEXT,
                        sync_source_device TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO apiaccount (
                        pk, seller_id, comp_name, platform, logo, integration_code,
                        api_key, api_secret, token, extra_config, created_at, last_used_at,
                        encrypted, token_valid, is_active, sync_uuid, sync_version,
                        sync_updated_at, sync_deleted_at, sync_source_device
                    ) VALUES (
                        1, '784195', 'Demo Sirket', 'TRENDYOL', 'logos/demo.png', 'INT-1',
                        'key', 'secret', 'token', '{"region":"tr"}', '2026-04-01T09:00:00', NULL,
                        1, 0, 1, 'uuid-1', 3, '2026-04-01T09:00:00', NULL, 'desktop-local'
                    )
                    """
                )
            )

            applied = run_domain_migrations(conn, migrations=MIGRATIONS)

            cols = conn.execute(text("PRAGMA table_info(apiaccount)")).fetchall()
            col_names = {str(row[1]) for row in cols}
            row = conn.execute(
                text(
                    """
                    SELECT account_id, logo_path, sync_uuid, sync_version, integration_code
                    FROM apiaccount
                    WHERE pk = 1
                    """
                )
            ).fetchone()

            self.assertEqual(
                applied,
                [
                    "account_0001_apiaccount_identity_columns",
                    "account_0002_add_apiaccount_platform_fk",
                ],
            )
            self.assertIn("account_id", col_names)
            self.assertIn("logo_path", col_names)
            self.assertIn("platform_id", col_names)
            self.assertNotIn("seller_id", col_names)
            self.assertNotIn("logo", col_names)
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "784195")
            self.assertEqual(str(row[1]), "logos/demo.png")
            self.assertEqual(str(row[2]), "uuid-1")
            self.assertEqual(int(row[3]), 3)
            self.assertEqual(str(row[4]), "INT-1")


if __name__ == "__main__":
    unittest.main()
