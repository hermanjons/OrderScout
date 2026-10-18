from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from Core.db import bootstrap
from Core.db.models import build_source_id
from Core.utils.model_utils import clear_engine_cache


class TestBootstrapDomainMigrationIntegration(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "legacy.sqlite3"
        clear_engine_cache()

    def tearDown(self) -> None:
        clear_engine_cache()
        self._tmp_dir.cleanup()
        super().tearDown()

    def _create_legacy_apiaccount_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
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
                    is_active INTEGER DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                INSERT INTO apiaccount (
                    pk, seller_id, comp_name, platform, logo, integration_code,
                    api_key, api_secret, token, extra_config, created_at, last_used_at,
                    encrypted, token_valid, is_active
                ) VALUES (
                    1, '784195', 'Demo Sirket', 'TRENDYOL', 'logos/demo.png', 'INT-1',
                    'key', 'secret', 'token', '{"region":"tr"}', '2026-04-01T09:00:00', NULL,
                    1, 0, 1
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_init_database_migrates_real_legacy_sqlite_file(self) -> None:
        self._create_legacy_apiaccount_db()

        bootstrap.init_database(db_name=str(self.db_path))
        clear_engine_cache()

        conn = sqlite3.connect(self.db_path)
        try:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(apiaccount)").fetchall()}
            row = conn.execute(
                """
                SELECT account_id, logo_path, integration_code, sourceType, sourceId
                FROM apiaccount
                WHERE pk = 1
                """
            ).fetchone()
            applied = {
                str(item[0]) for item in conn.execute("SELECT migration_id FROM applied_migrations").fetchall()
            }
        finally:
            conn.close()

        self.assertIn("account_id", columns)
        self.assertIn("logo_path", columns)
        self.assertNotIn("seller_id", columns)
        self.assertNotIn("logo", columns)
        self.assertIsNotNone(row)
        self.assertEqual(str(row[0]), "784195")
        self.assertEqual(str(row[1]), "logos/demo.png")
        self.assertEqual(str(row[2]), "INT-1")
        self.assertEqual(str(row[3]), "user")
        self.assertEqual(
            int(row[4]),
            build_source_id(
                "apiaccount",
                {
                    "platform": "TRENDYOL",
                    "account_id": "784195",
                },
                source_type="user",
            ),
        )
        self.assertIn("account_0001_apiaccount_identity_columns", applied)
