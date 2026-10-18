# Core/utils/model_utils.py
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from typing import (
    Type, Iterable, Callable, Optional, Any, Dict, Tuple
)

from sqlmodel import SQLModel, Session, select
from sqlmodel import create_engine

from sqlalchemy import Engine, delete as sa_delete, event, text, update as sa_update
from sqlalchemy.exc import IntegrityError, CompileError
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.sql.elements import BindParameter, ClauseElement
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from Core.constants.db_constants import DEFAULT_SQLITE_SAFE_MAX_VARIABLES
from Core.db.models import ensure_source_identity_inplace
from settings import DB_NAME, USER_DATA_DIR
from Feedback.processors.pipeline import Result, map_error_to_message


# ============================================================
# 🔌 ENGINE (STABLE / MULTI-PROCESS SAFE)
# ============================================================

_ENGINE_CACHE: Dict[str, Tuple[int, Engine]] = {}
_MODEL_COLUMNS_CACHE: Dict[Type[SQLModel], frozenset[str]] = {}
_sqlite_safe_max_variables = DEFAULT_SQLITE_SAFE_MAX_VARIABLES
_pd = None
SQLITE_RUNTIME_SAFE_MAX_VARIABLES = 32766


def _pandas():
    global _pd
    if _pd is None:
        import pandas as pd

        _pd = pd
    return _pd


def clear_engine_cache() -> None:
    global _sqlite_safe_max_variables
    for _pid, engine in list(_ENGINE_CACHE.values()):
        try:
            engine.dispose()
        except Exception:
            pass
    _ENGINE_CACHE.clear()
    _sqlite_safe_max_variables = DEFAULT_SQLITE_SAFE_MAX_VARIABLES


def _detect_sqlite_max_variables(cursor) -> int:
    try:
        rows = cursor.execute("PRAGMA compile_options;").fetchall() or []
    except Exception:
        rows = []

    for raw_row in rows:
        option = ""
        if isinstance(raw_row, (list, tuple)) and raw_row:
            option = str(raw_row[0] or "").strip()
        else:
            option = str(raw_row or "").strip()
        if not option.startswith("MAX_VARIABLE_NUMBER="):
            continue
        try:
            parsed = int(option.split("=", 1)[1])
        except Exception:
            continue
        if parsed > 0:
            return min(parsed, SQLITE_RUNTIME_SAFE_MAX_VARIABLES)
    return DEFAULT_SQLITE_SAFE_MAX_VARIABLES


def _is_sqlite_unique_integrity_error(error: Exception) -> bool:
    message = str(error or "").strip().lower()
    return "unique constraint failed" in message or "is not unique" in message


def _is_within_path(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except Exception:
        return False


def _use_ephemeral_pool(db_path: Path, db_dir: Path) -> bool:
    temp_roots = [
        Path(tempfile.gettempdir()).resolve(),
        (db_dir / "_tmp").resolve(),
    ]
    return any(_is_within_path(db_path, root) for root in temp_roots)


def get_engine(db_name: str) -> Engine:
    pid = os.getpid()

    cached = _ENGINE_CACHE.get(db_name)
    if cached is not None and cached[0] == pid:
        return cached[1]

    db_dir = Path(USER_DATA_DIR).resolve()
    db_dir.mkdir(parents=True, exist_ok=True)

    db_path = (db_dir / db_name).resolve()
    db_url = f"sqlite:///{db_path.as_posix()}"

    # SQLite temp dizinini sabitle (Windows + multi-process için kritik)
    tmp_dir = db_dir / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(tmp_dir)
    os.environ["TEMP"] = str(tmp_dir)

    engine_kwargs = {
        "echo": False,
        "connect_args": {
            "check_same_thread": False,
            "timeout": 30,
        },
        "pool_pre_ping": False,
    }
    if _use_ephemeral_pool(db_path, db_dir):
        engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs.update(
            {
                "poolclass": QueuePool,
                "pool_size": 2,
                "max_overflow": 3,
            }
        )

    engine = create_engine(db_url, **engine_kwargs)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _):
        global _sqlite_safe_max_variables
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA cache_size=-8000;")
        cur.execute("PRAGMA mmap_size=268435456;")
        cur.execute("PRAGMA page_size=4096;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA busy_timeout=10000;")
        _sqlite_safe_max_variables = max(_sqlite_safe_max_variables, _detect_sqlite_max_variables(cur))
        cur.close()

    # bağlantı testi
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    _ENGINE_CACHE[db_name] = (pid, engine)
    return engine


# ============================================================
# 🧩 HELPERS
# ============================================================

def batch_iter(seq: Iterable[Any], size: int = 500) -> Iterable[list[Any]]:
    buf: list[Any] = []
    for item in seq:
        buf.append(item)
        if len(buf) == size:
            yield buf
            buf = []
    if buf:
        yield buf


def _get_model_columns_cached(model: Type[SQLModel]) -> frozenset[str]:
    cached = _MODEL_COLUMNS_CACHE.get(model)
    if cached is None:
        cached = frozenset(c.name for c in model.__table__.c)
        _MODEL_COLUMNS_CACHE[model] = cached
    return cached


def get_model_columns(model: Type[SQLModel]) -> set[str]:
    return set(_get_model_columns_cached(model))


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# 🧼 NORMALIZER
# ============================================================

def make_normalizer(
    *,
    defaults: Optional[dict[str, Any]] = None,
    coalesce_none: Optional[dict[str, Any]] = None,
    strip_strings: bool = True,
    upper_keys: Optional[list[str]] = None,
    lower_keys: Optional[list[str]] = None,
    extra: Optional[Callable[[dict], dict]] = None,
) -> Callable[[dict], dict]:

    def _norm(rec: dict) -> dict:
        r = dict(rec)

        if defaults:
            for k, v in defaults.items():
                r.setdefault(k, v)

        if strip_strings:
            for k, v in list(r.items()):
                if isinstance(v, str):
                    r[k] = v.strip()

        if coalesce_none:
            for k, v in coalesce_none.items():
                if r.get(k) in (None, ""):
                    r[k] = v

        if upper_keys:
            for k in upper_keys:
                if isinstance(r.get(k), str):
                    r[k] = r[k].upper()

        if lower_keys:
            for k in lower_keys:
                if isinstance(r.get(k), str):
                    r[k] = r[k].lower()

        if extra:
            r = extra(r)

        return r

    return _norm


# ============================================================
# 🧽 SANITIZE (INSERT SAFETY)
# ============================================================

def _sanitize_row(row: dict) -> dict:
    safe = {}
    for k, v in row.items():
        if isinstance(v, BindParameter):
            safe[k] = getattr(v, "value", None)
        elif isinstance(v, ClauseElement):
            safe[k] = None
        else:
            safe[k] = v
    return safe


def _sanitize_chunk(chunk: list[dict]) -> list[dict]:
    sanitized: list[dict] | None = None
    for idx, row in enumerate(chunk):
        replacement: dict | None = None
        for key, value in row.items():
            if isinstance(value, BindParameter):
                if replacement is None:
                    replacement = dict(row)
                replacement[key] = getattr(value, "value", None)
            elif isinstance(value, ClauseElement):
                if replacement is None:
                    replacement = dict(row)
                replacement[key] = None

        if replacement is not None:
            if sanitized is None:
                sanitized = list(chunk[:idx])
            sanitized.append(replacement)
        elif sanitized is not None:
            sanitized.append(row)

    return chunk if sanitized is None else sanitized


def _group_rows_by_columns(rows: list[dict]) -> list[list[dict]]:
    if len(rows or []) <= 1:
        return [rows] if rows else []

    first_keys_view = rows[0].keys()
    first_key = frozenset(str(col) for col in first_keys_view)
    groups: dict[frozenset[str], list[dict]] | None = None
    ordered_keys: list[frozenset[str]] = []
    for idx, row in enumerate(rows):
        row_keys = row.keys()
        if groups is None and row_keys == first_keys_view:
            continue
        key = frozenset(str(col) for col in row_keys)
        if groups is None:
            groups = {first_key: rows[:idx]}
            ordered_keys.append(first_key)
        if key not in groups:
            groups[key] = []
            ordered_keys.append(key)
        groups[key].append(row)
    if groups is None:
        return [rows]
    return [groups[key] for key in ordered_keys]


def _execute_many(session: Session, stmt: Any, rows: list[dict]) -> int:
    if not rows:
        return 0
    res = session.execute(stmt, rows)
    return res.rowcount or 0


def _debug_find_problematic(rows: list[dict]) -> list[tuple]:
    bad = []
    for i, r in enumerate(rows):
        for k, v in r.items():
            if isinstance(v, (BindParameter, ClauseElement)):
                bad.append((i, k, type(v).__name__, str(v)))
    return bad


def _adaptive_batch_size(rows: list[dict], configured_size: int, *, min_columns: int = 0) -> int:
    if not rows:
        return max(1, int(configured_size or 1))

    max_columns = max(len(row) for row in rows if isinstance(row, dict)) if rows else 1
    max_columns = max(1, int(max_columns), int(min_columns or 0))
    max_rows_by_sqlite = max(1, _sqlite_safe_max_variables // max_columns)
    return max(1, min(int(configured_size or 1), max_rows_by_sqlite))


def _coerce_datetime_value(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.replace(tzinfo=None)
                return parsed
            except Exception:
                pass
    return fallback


def _coerce_iso_value(value: Any, fallback: str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "").strip()
    return text or fallback


def _stamp_audit_timestamps_inplace(
    row: dict,
    columns: set[str],
    *,
    now_dt: datetime | None = None,
    now_iso: str | None = None,
) -> dict:
    if not columns:
        return row

    now_dt = now_dt or _utcnow_naive()
    now_iso = now_iso or now_dt.isoformat()

    def _fill(name: str, source_names: tuple[str, ...], fallback: Any, *, as_datetime: bool) -> None:
        if name not in columns:
            return
        current = row.get(name)
        if current not in (None, ""):
            return
        for source_name in source_names:
            source_value = row.get(source_name)
            if source_value not in (None, ""):
                row[name] = _coerce_datetime_value(source_value, fallback) if as_datetime else _coerce_iso_value(source_value, str(fallback))
                return
        row[name] = fallback

    _fill("created_at", ("updated_at", "createdAt", "updatedAt"), now_dt, as_datetime=True)
    _fill("updated_at", ("created_at", "createdAt", "updatedAt"), now_dt, as_datetime=True)
    _fill("createdAt", ("updatedAt", "created_at", "updated_at"), now_iso, as_datetime=False)
    _fill("updatedAt", ("createdAt", "created_at", "updated_at"), now_iso, as_datetime=False)
    return row


def _stamp_audit_timestamps(
    row: dict,
    columns: set[str],
    *,
    now_dt: datetime | None = None,
    now_iso: str | None = None,
) -> dict:
    stamped = dict(row)
    _stamp_audit_timestamps_inplace(
        stamped,
        columns,
        now_dt=now_dt,
        now_iso=now_iso,
    )
    return stamped


# ============================================================
# ➕ CREATE / UPSERT
# ============================================================

def create_records(
    model: Type[SQLModel],
    data_list: list[dict],
    db_name: str = DB_NAME,
    *,
    conflict_keys: Optional[list[str]] = None,
    mode: str = "ignore",  # ignore | update | plain
    normalizer: Optional[Callable[[dict], dict]] = None,
    chunk_size: int = 500,
    rename_map: Optional[dict[str, str]] = None,
    drop_unknown: bool = True,
) -> Result:

    try:
        model_cols = _get_model_columns_cached(model)
        cols = model_cols if drop_unknown else None

        cleaned: list[dict] = []
        audit_now_dt = _utcnow_naive()
        audit_now_iso = audit_now_dt.isoformat()
        for d in data_list or []:
            r = dict(d)

            if rename_map:
                for old, new in rename_map.items():
                    if old in r:
                        r[new] = r.pop(old)

            if normalizer:
                r = normalizer(r)
                if not isinstance(r, dict):
                    r = dict(r or {})

            r = ensure_source_identity_inplace(model, r)
            r = _stamp_audit_timestamps_inplace(r, model_cols, now_dt=audit_now_dt, now_iso=audit_now_iso)

            if cols and not r.keys() <= cols:
                r = {k: v for k, v in r.items() if k in cols}

            if r:
                cleaned.append(r)

        attempted = len(cleaned)
        if attempted == 0:
            return Result.ok(
                f"{model.__name__}: işlenecek kayıt yok.",
                close_dialog=False,
                data={"attempted": 0, "inserted": 0, "affected": 0},
            )

        engine = get_engine(db_name)
        with Session(engine) as session:

            # ----------------------------------------------------
            # PLAIN INSERT
            # ----------------------------------------------------
            if mode == "plain" or not conflict_keys:
                inserted = 0
                effective_chunk_size = _adaptive_batch_size(cleaned, chunk_size, min_columns=len(model_cols))
                with session.begin():
                    for chunk in batch_iter(cleaned, effective_chunk_size):
                        for safe_group in _group_rows_by_columns(chunk):
                            try:
                                session.bulk_insert_mappings(model, safe_group)
                                inserted += len(safe_group)
                            except CompileError:
                                sanitized_group = _sanitize_chunk(safe_group)
                                session.bulk_insert_mappings(model, sanitized_group)
                                inserted += len(sanitized_group)
                # ✅ IMPORTANT: inserted bilgisi geri döndürüldü
                return Result.ok(
                    f"{model.__name__}: {inserted} kayıt eklendi.",
                    close_dialog=False,
                    data={"attempted": attempted, "inserted": inserted},
                )

            tbl = model.__table__

            # ----------------------------------------------------
            # IGNORE ON CONFLICT
            # ----------------------------------------------------
            if mode == "ignore":
                inserted = 0
                effective_chunk_size = _adaptive_batch_size(cleaned, chunk_size, min_columns=len(model_cols))
                stmt = (
                    sqlite_insert(tbl)
                    .on_conflict_do_nothing(index_elements=conflict_keys)
                )
                for chunk in batch_iter(cleaned, effective_chunk_size):
                    for safe_group in _group_rows_by_columns(chunk):
                        try:
                            inserted += _execute_many(session, stmt, safe_group)
                        except CompileError:
                            # bazı sqlite/driver kombinasyonlarında toplu values compile patlayabilir
                            sanitized_group = _sanitize_chunk(safe_group)
                            inserted += _execute_many(session, stmt, sanitized_group)
                        except IntegrityError as bulk_error:
                            for r in safe_group:
                                try:
                                    stmt = (
                                        sqlite_insert(tbl)
                                        .values(r)
                                        .on_conflict_do_nothing(index_elements=conflict_keys)
                                    )
                                    res = session.exec(stmt)
                                    inserted += res.rowcount or 0
                                except IntegrityError as row_error:
                                    if _is_sqlite_unique_integrity_error(row_error):
                                        continue
                                    raise row_error
                            if not _is_sqlite_unique_integrity_error(bulk_error):
                                raise bulk_error

                session.commit()

                # ✅ IMPORTANT: inserted bilgisi geri döndürüldü
                return Result.ok(
                    f"{model.__name__}: {inserted}/{attempted} kayıt eklendi.",
                    close_dialog=False,
                    data={"attempted": attempted, "inserted": inserted},
                )

            # ----------------------------------------------------
            # UPDATE ON CONFLICT
            # ----------------------------------------------------
            if mode == "update":
                affected = 0
                effective_chunk_size = _adaptive_batch_size(cleaned, chunk_size, min_columns=len(model_cols))
                stmt_cache: dict[frozenset[str], Any] = {}

                def _upsert_stmt_for_columns(column_names: frozenset[str]):
                    cached = stmt_cache.get(column_names)
                    if cached is not None:
                        return cached
                    stmt = sqlite_insert(tbl)
                    update_cols = {
                        c.name: stmt.excluded[c.name]
                        for c in tbl.c
                        if c.name not in conflict_keys
                        and c.name not in {"created_at", "createdAt"}
                        and c.name in column_names
                    }
                    cached = stmt.on_conflict_do_update(
                        index_elements=conflict_keys,
                        set_=update_cols,
                    )
                    stmt_cache[column_names] = cached
                    return cached

                for chunk in batch_iter(cleaned, effective_chunk_size):
                    for safe_group in _group_rows_by_columns(chunk):
                        try:
                            stmt = _upsert_stmt_for_columns(frozenset(safe_group[0].keys()))
                            affected += _execute_many(session, stmt, safe_group)
                        except CompileError:
                            sanitized_group = _sanitize_chunk(safe_group)
                            stmt = _upsert_stmt_for_columns(frozenset(sanitized_group[0].keys()))
                            affected += _execute_many(session, stmt, sanitized_group)

                session.commit()

                # ✅ IMPORTANT: affected bilgisi geri döndürüldü
                return Result.ok(
                    f"{model.__name__}: {affected} kayıt güncellendi.",
                    close_dialog=False,
                    data={"attempted": attempted, "affected": affected},
                )

            return Result.fail(f"Geçersiz mode='{mode}'", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# 📥 READ
# ============================================================

def get_records(
    model: Type[SQLModel] = None,
    db_engine: Engine = None,
    db_name: str = DB_NAME,
    filters: Optional[dict] = None,
    custom_sql: Optional[str] = None,
    custom_stmt: Optional[Any] = None,
    to_dataframe: bool = False,
) -> Result:

    try:
        engine = db_engine or get_engine(db_name)

        if custom_sql:
            with engine.connect() as conn:
                if to_dataframe:
                    pd = _pandas()

                    df = pd.read_sql_query(custom_sql, conn)
                    records = df
                    count = len(df)
                else:
                    rows = conn.execute(text(custom_sql)).fetchall()
                    records = [list(row) for row in rows]
                    count = len(records)
                return Result.ok(
                    f"{count} kayıt çekildi.",
                    close_dialog=False,
                    data={"records": records},
                )

        if custom_stmt is not None:
            with Session(engine) as session:
                res = session.exec(custom_stmt).all()
                if to_dataframe:
                    pd = _pandas()

                    return Result.ok(
                        f"{len(res)} kayıt çekildi.",
                        close_dialog=False,
                        data={"records": pd.DataFrame([r.dict() for r in res])},
                    )
                return Result.ok(
                    f"{len(res)} kayıt çekildi.",
                    close_dialog=False,
                    data={"records": res},
                )

        if model is None:
            return Result.fail("Model belirtilmedi.", close_dialog=False)

        with Session(engine) as session:
            stmt = select(model)
            if filters:
                for k, v in filters.items():
                    stmt = stmt.where(
                        getattr(model, k).in_(v) if isinstance(v, (list, tuple, set))
                        else getattr(model, k) == v
                    )
            res = session.exec(stmt).all()

        if to_dataframe:
            pd = _pandas()

            return Result.ok(
                f"{len(res)} kayıt çekildi.",
                close_dialog=False,
                data={"records": pd.DataFrame([r.dict() for r in res])},
            )

        return Result.ok(
            f"{len(res)} kayıt çekildi.",
            close_dialog=False,
            data={"records": res},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# ✏️ UPDATE
# ============================================================

def update_records(
    model: Type[SQLModel],
    filters: dict,
    update_data: dict,
    db_name: str = DB_NAME,
    db_engine: Engine = None,
) -> Result:

    try:
        engine = db_engine or get_engine(db_name)
        payload = dict(update_data or {})
        if not payload:
            return Result.ok(
                "0 kayıt güncellendi.",
                close_dialog=False,
                data={"affected": 0},
            )

        with Session(engine) as session:
            stmt = sa_update(model).values(**payload)
            for k, v in (filters or {}).items():
                stmt = stmt.where(getattr(model, k) == v)
            res = session.exec(stmt)
            session.commit()
            affected = int(res.rowcount or 0)

        return Result.ok(
            f"{affected} kayıt güncellendi.",
            close_dialog=False,
            data={"affected": affected},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ============================================================
# 🗑 DELETE
# ============================================================

def delete_records(
    model: Type[SQLModel],
    filters: dict,
    db_name: str = DB_NAME,
    db_engine: Engine = None,
) -> Result:

    try:
        engine = db_engine or get_engine(db_name)

        with Session(engine) as session:
            stmt = sa_delete(model)
            for k, v in (filters or {}).items():
                stmt = stmt.where(getattr(model, k) == v)
            res = session.exec(stmt)
            session.commit()
            deleted = int(res.rowcount or 0)

        return Result.ok(
            f"{deleted} kayıt silindi.",
            close_dialog=False,
            data={"deleted": deleted},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
