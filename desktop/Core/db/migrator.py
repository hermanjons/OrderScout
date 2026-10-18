from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, Optional, Iterable

from sqlalchemy import text


@dataclass
class TableSpec:
    name: str
    create_sql: Optional[str] = None
    columns: Dict[str, str] = field(default_factory=dict)
    rename_columns: Dict[str, str] = field(default_factory=dict)
    indexes_sql: Iterable[str] = field(default_factory=list)
    post_sql: Iterable[str] = field(default_factory=list)


_TABLE_SPECS: Dict[str, TableSpec] = {}
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def register_table(spec: TableSpec) -> None:
    existing = _TABLE_SPECS.get(spec.name)
    if existing is None:
        _TABLE_SPECS[spec.name] = spec
        return

    merged = TableSpec(
        name=spec.name,
        create_sql=existing.create_sql or spec.create_sql,
        columns={**existing.columns, **spec.columns},
        rename_columns={**existing.rename_columns, **spec.rename_columns},
        indexes_sql=list(dict.fromkeys([*(existing.indexes_sql or []), *(spec.indexes_sql or [])])),
        post_sql=list(dict.fromkeys([*(existing.post_sql or []), *(spec.post_sql or [])])),
    )
    _TABLE_SPECS[spec.name] = merged


def clear_registered_tables() -> None:
    _TABLE_SPECS.clear()


def _table_exists(conn, table_name: str) -> bool:
    res = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table_name},
    ).fetchone()
    return res is not None


def _get_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {r[1] for r in rows}


def _quote_ident(identifier: str) -> str:
    ident = str(identifier or "").strip()
    if not _IDENT_RE.match(ident):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f'"{ident}"'


def _ensure_renamed_columns(conn, table_name: str, rename_map: Dict[str, str]) -> None:
    if not rename_map:
        return

    table_q = _quote_ident(table_name)
    existing = _get_columns(conn, table_name)

    for old_name, new_name in (rename_map or {}).items():
        if old_name not in existing:
            continue
        if new_name in existing:
            continue

        old_q = _quote_ident(old_name)
        new_q = _quote_ident(new_name)
        conn.execute(text(f"ALTER TABLE {table_q} RENAME COLUMN {old_q} TO {new_q}"))
        existing.remove(old_name)
        existing.add(new_name)


def _ensure_columns(conn, table_name: str, columns: Dict[str, str]) -> None:
    existing = _get_columns(conn, table_name)
    table_q = _quote_ident(table_name)
    for col, col_type in (columns or {}).items():
        if col not in existing:
            col_q = _quote_ident(col)
            conn.execute(text(f"ALTER TABLE {table_q} ADD COLUMN {col_q} {col_type}"))


def _ensure_indexes(conn, indexes_sql: Iterable[str]) -> None:
    for idx_sql in indexes_sql or ():
        sql = str(idx_sql or "").strip()
        if not sql:
            continue
        conn.execute(text(sql))


def _run_post_sql(conn, sql_list: Iterable[str]) -> None:
    for stmt in sql_list or ():
        sql = str(stmt or "").strip()
        if not sql:
            continue
        conn.execute(text(sql))


def run_auto_migrations(conn) -> None:
    for spec in _TABLE_SPECS.values():
        if spec.create_sql and not _table_exists(conn, spec.name):
            conn.execute(text(spec.create_sql))
        if not _table_exists(conn, spec.name):
            continue

        if spec.rename_columns:
            _ensure_renamed_columns(conn, spec.name, spec.rename_columns)
        if spec.columns:
            _ensure_columns(conn, spec.name, spec.columns)
        if spec.indexes_sql:
            _ensure_indexes(conn, spec.indexes_sql)
        if spec.post_sql:
            _run_post_sql(conn, spec.post_sql)
