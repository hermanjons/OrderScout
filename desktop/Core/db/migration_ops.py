from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
import re

from sqlalchemy import text


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    ).fetchone()
    return row is not None


def table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {str(row[1]) for row in rows}


def table_has_index(conn, table_name: str, index_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA index_list({table_name})")).fetchall()
    expected = str(index_name or "").strip().lower()
    if not expected:
        return False
    return any(str(row[1] or "").strip().lower() == expected for row in rows)


def table_row_count(conn, table_name: str) -> int:
    row = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
    return int(row[0] or 0) if row is not None else 0


def create_indexes(conn, indexes_sql: Iterable[str]) -> None:
    for statement in indexes_sql or ():
        sql = str(statement or "").strip()
        if not sql:
            continue
        upper_sql = sql.upper()
        if upper_sql.startswith("CREATE UNIQUE INDEX ") and " IF NOT EXISTS " not in upper_sql:
            sql = sql.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
        elif upper_sql.startswith("CREATE INDEX ") and " IF NOT EXISTS " not in upper_sql:
            sql = sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
        conn.exec_driver_sql(sql)


def quote_ident(identifier: str) -> str:
    ident = str(identifier or "").strip()
    if not _IDENT_RE.match(ident):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f'"{ident}"'


def add_column_if_missing(conn, *, table_name: str, column_name: str, column_sql: str) -> bool:
    existing = table_columns(conn, table_name)
    if str(column_name) in existing:
        return False
    conn.exec_driver_sql(
        f"ALTER TABLE {quote_ident(table_name)} ADD COLUMN {quote_ident(column_name)} {str(column_sql).strip()}"
    )
    return True


def copy_column_values(
    conn,
    *,
    table_name: str,
    target_name: str,
    source_names: Iterable[str],
    copy_when_blank: bool = False,
) -> None:
    sources = [str(name) for name in source_names if str(name)]
    if not sources:
        return

    existing = table_columns(conn, table_name)
    if str(target_name) not in existing:
        return

    usable_sources = [name for name in sources if name in existing]
    if not usable_sources:
        return

    table_q = quote_ident(table_name)
    target_q = quote_ident(target_name)
    coalesce_expr = ", ".join(quote_ident(name) for name in usable_sources)
    source_expr = coalesce_expr if len(usable_sources) == 1 else f"COALESCE({coalesce_expr})"
    target_missing_expr = f"{target_q} IS NULL"
    if copy_when_blank:
        target_missing_expr = f"({target_q} IS NULL OR trim(CAST({target_q} AS TEXT)) = '')"
    conn.exec_driver_sql(
        f"""
        UPDATE {table_q}
        SET {target_q} = {source_expr}
        WHERE {target_missing_expr}
        """
    )


def drop_table_if_exists(conn, table_name: str) -> None:
    conn.exec_driver_sql(f"DROP TABLE IF EXISTS {quote_ident(table_name)}")


def has_rows_missing_stock_tx_legacy_cost_defaults(
    conn,
    *,
    table_name: str = "stock_tx",
) -> bool:
    if not table_exists(conn, table_name):
        return False
    columns = table_columns(conn, table_name)
    required = {"unit_cost", "unit_cost_input_mode", "unit_cost_vat_rate", "item_id"}
    if not required.issubset(columns):
        return False
    return bool(
        conn.exec_driver_sql(
            f"""
            SELECT 1
            FROM {quote_ident(table_name)}
            WHERE unit_cost IS NOT NULL
              AND (
                  unit_cost_input_mode IS NULL
                  OR (
                      unit_cost_input_mode = 'net'
                      AND unit_cost_vat_rate IS NULL
                  )
              )
            LIMIT 1
            """
        ).fetchone()
    )


def backfill_stock_tx_legacy_cost_defaults(
    conn,
    *,
    table_name: str = "stock_tx",
    stock_item_table_name: str = "stock_item",
) -> None:
    if not has_rows_missing_stock_tx_legacy_cost_defaults(conn, table_name=table_name):
        return

    conn.exec_driver_sql(
        f"""
        UPDATE {quote_ident(table_name)}
        SET unit_cost_input_mode = 'net'
        WHERE unit_cost IS NOT NULL
          AND unit_cost_input_mode IS NULL
        """
    )

    if not table_exists(conn, stock_item_table_name):
        return
    stock_item_columns = table_columns(conn, stock_item_table_name)
    if "vat_rate" not in stock_item_columns:
        return
    stock_item_pk_column = "pk" if "pk" in stock_item_columns else "id"

    conn.exec_driver_sql(
        f"""
        UPDATE {quote_ident(table_name)}
        SET unit_cost_vat_rate = (
            SELECT {quote_ident(stock_item_table_name)}.vat_rate
            FROM {quote_ident(stock_item_table_name)}
            WHERE {quote_ident(stock_item_table_name)}.{stock_item_pk_column} = {quote_ident(table_name)}.item_id
            LIMIT 1
        )
        WHERE unit_cost IS NOT NULL
          AND unit_cost_input_mode = 'net'
          AND unit_cost_vat_rate IS NULL
        """
    )


def _normalized_resolution_meta(value: object) -> dict[str, object] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = None
    if not isinstance(value, Mapping):
        return None
    normalized = {str(key): item for key, item in dict(value).items()}
    return normalized or None


def merged_listing_resolution_meta(row: Mapping[str, object]) -> str | None:
    resolution_meta = _normalized_resolution_meta(row.get("resolution_meta")) or {}

    matched_tariff_key = str(row.get("matched_tariff_key") or "").strip()
    matched_tariff_name = str(row.get("matched_tariff_name") or "").strip()
    if matched_tariff_key:
        resolution_meta["matchedTariffKey"] = matched_tariff_key
    if matched_tariff_name:
        resolution_meta["matchedTariffName"] = matched_tariff_name

    if not resolution_meta:
        return None
    return json.dumps(resolution_meta, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def promote_legacy_table(
    conn,
    *,
    old_table_name: str,
    new_table_name: str,
    drop_empty_target: bool = True,
) -> None:
    if not table_exists(conn, old_table_name):
        return

    target_exists = table_exists(conn, new_table_name)
    if target_exists:
        target_count = table_row_count(conn, new_table_name)
        if target_count != 0:
            raise ValueError(
                f"Target table {new_table_name} must be empty before promoting {old_table_name}, found {target_count} rows."
            )

    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        if target_exists and drop_empty_target:
            drop_table_if_exists(conn, new_table_name)
        conn.exec_driver_sql(
            f"ALTER TABLE {quote_ident(old_table_name)} RENAME TO {quote_ident(new_table_name)}"
        )
    finally:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def rebuild_table(
    conn,
    *,
    table_name: str,
    create_sql: str,
    insert_sql: str,
    row_mapper: Callable[[Mapping[str, object]], Mapping[str, object]],
    indexes_sql: Iterable[str] = (),
    old_suffix: str = "__old",
    validate: Callable[[object], None] | None = None,
) -> None:
    source_count = table_row_count(conn, table_name)
    old_name = f"{table_name}{old_suffix}"
    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    try:
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {old_name}")
        conn.exec_driver_sql(f"ALTER TABLE {table_name} RENAME TO {old_name}")
        conn.exec_driver_sql(create_sql)

        rows = conn.execute(text(f"SELECT * FROM {old_name}")).mappings().all()
        insert_stmt = text(insert_sql)
        for row in rows:
            conn.execute(insert_stmt, dict(row_mapper(row)))

        target_count = table_row_count(conn, table_name)
        if target_count != source_count:
            raise ValueError(
                f"Rebuild row count mismatch for {table_name}: expected {source_count}, got {target_count}."
            )

        if validate is not None:
            validate(conn)

        conn.exec_driver_sql(f"DROP TABLE {old_name}")
        create_indexes(conn, indexes_sql)
    finally:
        conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def rehome_table(
    conn,
    *,
    source_table_name: str,
    target_table_name: str,
    create_sql: str,
    insert_sql: str,
    row_mapper: Callable[[Mapping[str, object]], Mapping[str, object]],
    indexes_sql: Iterable[str] = (),
    validate: Callable[[object], None] | None = None,
    drop_source: bool = True,
) -> None:
    if not table_exists(conn, source_table_name):
        return

    source_count = table_row_count(conn, source_table_name)
    target_exists = table_exists(conn, target_table_name)
    target_created = False

    if target_exists:
        target_count = table_row_count(conn, target_table_name)
        if target_count != 0:
            raise ValueError(
                f"Target table {target_table_name} must be empty before rehome, found {target_count} rows."
            )
    else:
        conn.exec_driver_sql(create_sql)
        target_created = True

    rows = conn.execute(text(f"SELECT * FROM {quote_ident(source_table_name)}")).mappings().all()
    insert_stmt = text(insert_sql)
    for row in rows:
        conn.execute(insert_stmt, dict(row_mapper(row)))

    target_count = table_row_count(conn, target_table_name)
    if target_count != source_count:
        raise ValueError(
            f"Rehome row count mismatch from {source_table_name} to {target_table_name}: "
            f"expected {source_count}, got {target_count}."
        )

    if drop_source:
        drop_table_if_exists(conn, source_table_name)
    if validate is not None:
        validate(conn)
    if target_created:
        create_indexes(conn, indexes_sql)


def append_rows_to_table(
    conn,
    *,
    source_table_name: str,
    target_table_name: str,
    create_sql: str,
    insert_sql: str,
    row_mapper: Callable[[Mapping[str, object]], Mapping[str, object]],
    indexes_sql: Iterable[str] = (),
    validate: Callable[[object], None] | None = None,
    drop_source: bool = False,
) -> None:
    if not table_exists(conn, source_table_name):
        return

    source_count = table_row_count(conn, source_table_name)
    target_exists = table_exists(conn, target_table_name)
    target_created = False
    before_count = table_row_count(conn, target_table_name) if target_exists else 0

    if not target_exists:
        conn.exec_driver_sql(create_sql)
        target_created = True

    rows = conn.execute(text(f"SELECT * FROM {quote_ident(source_table_name)}")).mappings().all()
    insert_stmt = text(insert_sql)
    for row in rows:
        conn.execute(insert_stmt, dict(row_mapper(row)))

    target_count = table_row_count(conn, target_table_name)
    if target_count != before_count + source_count:
        raise ValueError(
            f"Append row count mismatch from {source_table_name} to {target_table_name}: "
            f"expected {before_count + source_count}, got {target_count}."
        )

    if drop_source:
        drop_table_if_exists(conn, source_table_name)
    if validate is not None:
        validate(conn)
    if target_created:
        create_indexes(conn, indexes_sql)
