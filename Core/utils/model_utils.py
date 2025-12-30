# Core/utils/model_utils.py
from __future__ import annotations

import os
from pathlib import Path
from typing import (
    Type, Iterable, Callable, Optional, Any, Dict, Tuple
)

import pandas as pd
from sqlmodel import SQLModel, Session, select
from sqlmodel import create_engine

from sqlalchemy import Engine, event, text
from sqlalchemy.exc import IntegrityError, CompileError
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import BindParameter, ClauseElement
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from settings import DB_NAME, DEFAULT_DATABASE_DIR
from Feedback.processors.pipeline import Result, map_error_to_message


# ============================================================
# 🔌 ENGINE (STABLE / MULTI-PROCESS SAFE)
# ============================================================

_ENGINE_CACHE: Dict[str, Tuple[int, Engine]] = {}


def get_engine(db_name: str) -> Engine:
    pid = os.getpid()

    cached = _ENGINE_CACHE.get(db_name)
    if cached is not None and cached[0] == pid:
        return cached[1]

    db_dir = Path(DEFAULT_DATABASE_DIR).resolve()
    db_dir.mkdir(parents=True, exist_ok=True)

    db_path = (db_dir / db_name).resolve()
    db_url = f"sqlite:///{db_path.as_posix()}"

    # SQLite temp dizinini sabitle (Windows + multi-process için kritik)
    tmp_dir = db_dir / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(tmp_dir)
    os.environ["TEMP"] = str(tmp_dir)

    engine = create_engine(
        db_url,
        echo=False,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
        poolclass=NullPool,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=DELETE;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA busy_timeout=10000;")
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


def get_model_columns(model: Type[SQLModel]) -> set[str]:
    return {c.name for c in model.__table__.c}


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
    return [_sanitize_row(r) for r in chunk]


def _debug_find_problematic(rows: list[dict]) -> list[tuple]:
    bad = []
    for i, r in enumerate(rows):
        for k, v in r.items():
            if isinstance(v, (BindParameter, ClauseElement)):
                bad.append((i, k, type(v).__name__, str(v)))
    return bad


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
        engine = get_engine(db_name)
        cols = get_model_columns(model) if drop_unknown else None

        cleaned: list[dict] = []
        for d in data_list or []:
            r = dict(d)

            if rename_map:
                for old, new in rename_map.items():
                    if old in r:
                        r[new] = r.pop(old)

            if normalizer:
                r = normalizer(r)

            if cols:
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

        with Session(engine) as session:

            # ----------------------------------------------------
            # PLAIN INSERT
            # ----------------------------------------------------
            if mode == "plain" or not conflict_keys:
                with session.begin():
                    for r in cleaned:
                        session.add(model(**r))
                # ✅ IMPORTANT: inserted bilgisi geri döndürüldü
                return Result.ok(
                    f"{model.__name__}: {attempted} kayıt eklendi.",
                    close_dialog=False,
                    data={"attempted": attempted, "inserted": attempted},
                )

            tbl = model.__table__

            # ----------------------------------------------------
            # IGNORE ON CONFLICT
            # ----------------------------------------------------
            if mode == "ignore":
                inserted = 0
                for chunk in batch_iter(cleaned, chunk_size):
                    safe = _sanitize_chunk(chunk)
                    try:
                        stmt = (
                            sqlite_insert(tbl)
                            .values(safe)
                            .on_conflict_do_nothing(index_elements=conflict_keys)
                        )
                        res = session.exec(stmt)
                        inserted += res.rowcount or 0
                    except CompileError:
                        # bazı sqlite/driver kombinasyonlarında toplu values compile patlayabilir
                        for r in safe:
                            stmt = (
                                sqlite_insert(tbl)
                                .values(r)
                                .on_conflict_do_nothing(index_elements=conflict_keys)
                            )
                            res = session.exec(stmt)
                            inserted += res.rowcount or 0

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
                for chunk in batch_iter(cleaned, chunk_size):
                    stmt = sqlite_insert(tbl).values(chunk)
                    update_cols = {
                        c.name: stmt.excluded[c.name]
                        for c in tbl.c
                        if c.name not in conflict_keys
                    }
                    stmt = stmt.on_conflict_do_update(
                        index_elements=conflict_keys,
                        set_=update_cols,
                    )
                    res = session.exec(stmt)
                    affected += res.rowcount or 0

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
                df = pd.read_sql_query(custom_sql, conn)
                return Result.ok(
                    f"{len(df)} kayıt çekildi.",
                    close_dialog=False,
                    data={"records": df if to_dataframe else df.values.tolist()},
                )

        if custom_stmt is not None:
            with Session(engine) as session:
                res = session.exec(custom_stmt).all()
                if to_dataframe:
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

        with Session(engine) as session:
            stmt = select(model)
            for k, v in filters.items():
                stmt = stmt.where(getattr(model, k) == v)

            rows = session.exec(stmt).all()
            for row in rows:
                for k, v in update_data.items():
                    setattr(row, k, v)

            session.commit()

        return Result.ok(
            f"{len(rows)} kayıt güncellendi.",
            close_dialog=False,
            data={"affected": len(rows)},
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
            stmt = select(model)
            for k, v in filters.items():
                stmt = stmt.where(getattr(model, k) == v)

            rows = session.exec(stmt).all()
            for row in rows:
                session.delete(row)

            session.commit()

        return Result.ok(
            f"{len(rows)} kayıt silindi.",
            close_dialog=False,
            data={"deleted": len(rows)},
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
