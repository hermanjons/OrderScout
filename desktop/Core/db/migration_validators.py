from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import text

from Core.db.migration_ops import table_columns, table_row_count


class MigrationValidationError(RuntimeError):
    pass


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_ident(identifier: str) -> str:
    ident = str(identifier or "").strip()
    if not _IDENT_RE.match(ident):
        raise MigrationValidationError(f"Unsafe SQL identifier in migration validator: {identifier!r}")
    return f'"{ident}"'


def assert_columns_exist(conn, table_name: str, required_columns: Iterable[str]) -> None:
    existing = table_columns(conn, table_name)
    missing = [str(column) for column in required_columns if str(column) not in existing]
    if missing:
        raise MigrationValidationError(
            f"{table_name} is missing expected columns: {', '.join(sorted(missing))}"
        )


def assert_columns_absent(conn, table_name: str, unexpected_columns: Iterable[str]) -> None:
    existing = table_columns(conn, table_name)
    present = [str(column) for column in unexpected_columns if str(column) in existing]
    if present:
        raise MigrationValidationError(
            f"{table_name} still contains legacy columns: {', '.join(sorted(present))}"
        )


def assert_row_count(conn, table_name: str, expected_count: int) -> None:
    actual = table_row_count(conn, table_name)
    if int(actual) != int(expected_count):
        raise MigrationValidationError(
            f"{table_name} row count mismatch: expected {int(expected_count)}, got {int(actual)}"
        )


def assert_no_nulls(conn, table_name: str, columns: Iterable[str]) -> None:
    for column in columns:
        column_name = str(column)
        quoted = _quote_ident(column_name)
        row = conn.execute(
            text(f"SELECT COUNT(*) FROM {_quote_ident(table_name)} WHERE {quoted} IS NULL")
        ).fetchone()
        if row is not None and int(row[0] or 0) > 0:
            raise MigrationValidationError(f"{table_name}.{column_name} contains NULL values after migration.")


def assert_non_blank_strings(conn, table_name: str, columns: Iterable[str]) -> None:
    for column in columns:
        column_name = str(column)
        quoted = _quote_ident(column_name)
        row = conn.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {_quote_ident(table_name)}
                WHERE {quoted} IS NULL OR trim(CAST({quoted} AS TEXT)) = ''
                """
            )
        ).fetchone()
        if row is not None and int(row[0] or 0) > 0:
            raise MigrationValidationError(
                f"{table_name}.{column_name} contains blank values after migration."
            )
