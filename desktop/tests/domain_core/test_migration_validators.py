from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from Core.db.migration_validators import (
    MigrationValidationError,
    assert_columns_absent,
    assert_columns_exist,
    assert_non_blank_strings,
    assert_no_nulls,
    assert_row_count,
)


class TestMigrationValidators(unittest.TestCase):
    def test_validators_accept_expected_schema_and_data(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample (
                        id INTEGER PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        comp_name TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sample (id, account_id, comp_name)
                    VALUES (1, '784195', 'Demo Sirket')
                    """
                )
            )

            assert_columns_exist(conn, "sample", ["id", "account_id", "comp_name"])
            assert_columns_absent(conn, "sample", ["seller_id", "logo"])
            assert_row_count(conn, "sample", 1)
            assert_no_nulls(conn, "sample", ["account_id", "comp_name"])
            assert_non_blank_strings(conn, "sample", ["account_id", "comp_name"])

    def test_non_blank_validator_fails_for_empty_strings(self) -> None:
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE sample (
                        id INTEGER PRIMARY KEY,
                        account_id TEXT
                    )
                    """
                )
            )
            conn.execute(text("INSERT INTO sample (id, account_id) VALUES (1, '')"))

            with self.assertRaises(MigrationValidationError):
                assert_non_blank_strings(conn, "sample", ["account_id"])


if __name__ == "__main__":
    unittest.main()
