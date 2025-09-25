# model_utils.py
from sqlmodel import SQLModel, Session, select
from typing import Type, Iterable, Callable, Optional, Any
from settings import DB_NAME, DEFAULT_DATABASE_DIR
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # PG'ye geçince pg_insert
# from sqlalchemy.dialects.postgresql import insert as pg_insert
import os
import pandas as pd
from Feedback.processors.pipeline import Result, map_error_to_message


# ---------- Engine ----------
def get_engine(db_name: str):
    """
    Belirtilen veritabanı ismine göre SQLite engine döner.
    Örn: get_engine("orders.db") → sqlite:///databases/orders.db
    """
    db_path = os.path.join(DEFAULT_DATABASE_DIR, db_name)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


# ---------- Helper ----------
def batch_iter(seq: Iterable[Any], size: int = 500) -> Iterable[list[Any]]:
    """
    Büyük listeleri güvenli/parçalı işlemek için generator.
    """
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) == size:
            yield buf
            buf = []
    if buf:
        yield buf


def get_model_columns(model: Type[SQLModel]) -> set[str]:
    return {c.name for c in model.__table__.c}


# ---------- Normalizer ----------
def make_normalizer(
        *,
        defaults: Optional[dict[str, Any]] = None,
        coalesce_none: Optional[dict[str, Any]] = None,
        strip_strings: bool = True,
        upper_keys: Optional[list[str]] = None,
        lower_keys: Optional[list[str]] = None,
        extra: Optional[Callable[[dict], dict]] = None,
) -> Callable[[dict], dict]:
    """
    Normalize fonksiyonu üretir.
    """

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
                if r.get(k) is None or (isinstance(r.get(k), str) and r.get(k) == ""):
                    r[k] = v

        if upper_keys:
            for k in upper_keys:
                if k in r and isinstance(r[k], str):
                    r[k] = r[k].upper()
        if lower_keys:
            for k in lower_keys:
                if k in r and isinstance(r[k], str):
                    r[k] = r[k].lower()

        if extra:
            r = extra(r)

        return r

    return _norm


# ---------- Create ----------
def create_records(
        model: Type[SQLModel],
        data_list: list[dict],
        db_name: str = DB_NAME,
        *,
        conflict_keys: Optional[list[str]] = None,
        mode: str = "ignore",  # "ignore" | "update" | "plain"
        normalizer: Optional[Callable[[dict], dict]] = None,
        chunk_size: int = 500,
        rename_map: Optional[dict[str, str]] = None,
        drop_unknown: bool = True,
) -> Result:
    """
    Toplu kayıt ekleme/upsert.
    """
    try:
        engine = get_engine(db_name)

        # Temizleme
        cols = get_model_columns(model) if drop_unknown else None
        cleaned = []
        for d in (data_list or []):
            r = dict(d)

            if rename_map:
                for old, new in list(rename_map.items()):
                    if old in r:
                        r[new] = r.pop(old)

            if normalizer:
                r = normalizer(r)

            if drop_unknown and cols is not None:
                r = {k: v for k, v in r.items() if k in cols}

            if r:
                cleaned.append(r)

        attempted = len(cleaned)
        if attempted == 0:
            return Result.ok(
                f"{model.__name__}: işlenecek kayıt yok.",
                close_dialog=False,
                data={"model": model.__name__, "attempted": 0}
            )

        with Session(engine) as session:
            # plain
            if mode == "plain" or not conflict_keys:
                try:
                    with session.begin():
                        for r in cleaned:
                            session.add(model(**r))
                    return Result.ok(
                        f"{model.__name__}: {attempted} kayıt eklendi (plain).",
                        close_dialog=False,
                        data={"model": model.__name__, "attempted": attempted, "inserted": attempted}
                    )
                except IntegrityError as e:
                    session.rollback()
                    return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
                except Exception as e:
                    session.rollback()
                    return Result.fail(map_error_to_message(e), error=e, close_dialog=False)

            tbl = model.__table__

            if mode == "ignore":
                inserted_total = 0
                for chunk in batch_iter(cleaned, chunk_size):
                    stmt = sqlite_insert(tbl).values(chunk)
                    stmt = stmt.on_conflict_do_nothing(index_elements=conflict_keys)
                    res = session.exec(stmt)
                    rc = getattr(res, "rowcount", 0) or 0
                    inserted_total += rc
                session.commit()
                return Result.ok(
                    f"{model.__name__}: {attempted} kaydın {inserted_total} adedi eklendi (ignore).",
                    close_dialog=False,
                    data={"model": model.__name__, "attempted": attempted, "inserted": inserted_total}
                )

            elif mode == "update":
                affected_total = 0
                for chunk in batch_iter(cleaned, chunk_size):
                    stmt = sqlite_insert(tbl).values(chunk)
                    update_cols = {
                        c.name: stmt.excluded[c.name]
                        for c in tbl.c
                        if c.name not in conflict_keys
                    }
                    stmt = stmt.on_conflict_do_update(
                        index_elements=conflict_keys,
                        set_=update_cols
                    )
                    res = session.exec(stmt)
                    rc = getattr(res, "rowcount", 0) or 0
                    affected_total += rc
                session.commit()
                return Result.ok(
                    f"{model.__name__}: {attempted} kaydın {affected_total} adedi etkilendi (update).",
                    close_dialog=False,
                    data={"model": model.__name__, "attempted": attempted, "affected": affected_total}
                )

            return Result.fail(f"Geçersiz mode='{mode}'.", close_dialog=False)

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ---------- Read ----------
def get_records(
        model: Type[SQLModel] = None,
        db_engine: Engine = None,
        db_name: str = DB_NAME,
        filters: Optional[dict] = None,
        custom_sql: Optional[str] = None,
        custom_stmt: Optional[Any] = None,  # ✅ ORM query desteği
        to_dataframe: bool = False
) -> Result:
    """
    Genel amaçlı veri çekme fonksiyonu.
    - filters: dict → {"name": "Ali"} veya {"pk": [1,2,3]}
    - custom_sql: ham SQL string
    - custom_stmt: ORM query (örn: select(...).join(...))
    - to_dataframe: True ise DataFrame döner
    """
    try:

        if db_engine is None:
            db_engine = get_engine(db_name)

        # 🔹 Ham SQL modu
        if custom_sql:
            with db_engine.connect() as conn:
                if to_dataframe:
                    df = pd.read_sql_query(custom_sql, conn)
                    return Result.ok(
                        f"{len(df)} kayıt çekildi (custom SQL, DataFrame).",
                        close_dialog=False,
                        data={"records": df, "count": len(df)}
                    )
                else:
                    result = conn.execute(custom_sql).fetchall()
                    return Result.ok(
                        f"{len(result)} kayıt çekildi (custom SQL).",
                        close_dialog=False,
                        data={"records": result, "count": len(result)}
                    )

        # 🔹 ORM Query modu
        if custom_stmt is not None:
            with Session(db_engine) as session:
                result = session.exec(custom_stmt).all()
                if to_dataframe:
                    df = pd.DataFrame([r.dict() for r in result])
                    return Result.ok(
                        f"{len(df)} kayıt çekildi (custom_stmt, DataFrame).",
                        close_dialog=False,
                        data={"records": df, "count": len(df)}
                    )
                return Result.ok(
                    f"{len(result)} kayıt çekildi (custom_stmt).",
                    close_dialog=False,
                    data={"records": result, "count": len(result)}
                )

        # 🔹 Normal SQLModel select (filters ile)
        if model is None:
            return Result.fail("Model belirtilmedi.", close_dialog=False)

        with Session(db_engine) as session:
            stmt = select(model)

            if filters:
                for attr, value in filters.items():
                    if isinstance(value, (list, tuple, set)):
                        stmt = stmt.where(getattr(model, attr).in_(value))
                    else:
                        stmt = stmt.where(getattr(model, attr) == value)

            result = session.exec(stmt).all()

            if to_dataframe:
                df = pd.DataFrame([r.dict() for r in result])
                return Result.ok(
                    f"{len(df)} kayıt çekildi (DataFrame).",
                    close_dialog=False,
                    data={"records": df, "count": len(df)}
                )

            return Result.ok(
                f"{len(result)} kayıt çekildi.",
                close_dialog=False,
                data={"records": result, "count": len(result)}
            )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ---------- Update ----------
def update_records(
        model: Type[SQLModel],
        filters: dict,
        update_data: dict,
        db_name: str = DB_NAME,
        db_engine: Engine = None,

) -> Result:
    """
    Genel amaçlı update fonksiyonu.
    """
    try:
        if db_engine is None:
            db_engine = get_engine(db_name)

        with Session(db_engine) as session:
            stmt = select(model)
            for attr, value in filters.items():
                stmt = stmt.where(getattr(model, attr) == value)

            results = session.exec(stmt).all()
            for item in results:
                for attr, value in update_data.items():
                    setattr(item, attr, value)

            session.commit()

        return Result.ok(
            f"{len(results)} kayıt güncellendi.",
            close_dialog=False,
            data={"count": len(results)}
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)


# ---------- Delete ----------
def delete_records(
        model: Type[SQLModel],
        filters: dict,
        db_name: str = DB_NAME,
        db_engine: Engine = None,
) -> Result:
    """
    Genel amaçlı delete fonksiyonu.
    """
    try:
        if db_engine is None:
            db_engine = get_engine(db_name)

        with Session(db_engine) as session:
            stmt = select(model)
            for attr, value in filters.items():
                stmt = stmt.where(getattr(model, attr) == value)

            results = session.exec(stmt).all()
            deleted = len(results)

            for item in results:
                session.delete(item)

            session.commit()

        return Result.ok(
            f"{deleted} kayıt silindi.",
            close_dialog=False,
            data={"count": deleted}
        )

    except Exception as e:
        return Result.fail(map_error_to_message(e), error=e, close_dialog=False)
