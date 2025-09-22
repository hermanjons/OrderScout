# model_utils.py
from sqlmodel import SQLModel, Session, select
from typing import Type, Iterable, Callable, Optional, Any, List
from settings import DB_NAME, DEFAULT_DATABASE_DIR
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # PG'ye geçince pg_insert
# from sqlalchemy.dialects.postgresql import insert as pg_insert
import os
import pandas as pd


def get_engine(db_name: str):
    """
    Belirtilen veritabanı ismine göre SQLite engine döner.
    Örnek: get_engine("orders.db") → sqlite:///databases/orders.db
    """
    db_path = os.path.join(DEFAULT_DATABASE_DIR, db_name)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


# ---------- Genel: büyük listeleri parça parça işlemek ----------
def batch_iter(seq: Iterable[Any], size: int = 500) -> Iterable[list[Any]]:
    """
    Büyük listeleri güvenli/parçalı işlemek için generator.
    - Bellek/SQL statement limitlerini aşmayı önler.
    """
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) == size:
            yield buf
            buf = []
    if buf:
        yield buf


# ---------- Genel: normalize fabrikası ----------
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
    Tüm modellere uygulanabilir normalize fonksiyonu üretir.
    - defaults: eksik anahtarlar için varsayılan değer (setdefault)
    - coalesce_none: None veya "" ise şu değere çek (unique key'ler için kritik)
    - strip_strings: string alanlarda .strip()
    - upper_keys / lower_keys: belirli string alanları büyüt/küçült
    - extra: özel ek dönüştürme (callable)
    """

    def _norm(rec: dict) -> dict:
        r = dict(rec)

        # 1) defaults
        if defaults:
            for k, v in defaults.items():
                r.setdefault(k, v)

        # 2) strip
        if strip_strings:
            for k, v in list(r.items()):
                if isinstance(v, str):
                    r[k] = v.strip()

        # 3) coalesce None / empty
        if coalesce_none:
            for k, v in coalesce_none.items():
                if r.get(k) is None or (isinstance(r.get(k), str) and r.get(k) == ""):
                    r[k] = v

        # 4) upper/lower
        if upper_keys:
            for k in upper_keys:
                if k in r and isinstance(r[k], str):
                    r[k] = r[k].upper()
        if lower_keys:
            for k in lower_keys:
                if k in r and isinstance(r[k], str):
                    r[k] = r[k].lower()

        # 5) extra hook
        if extra:
            r = extra(r)

        return r

    return _norm


def get_model_columns(model: Type[SQLModel]) -> set[str]:
    return {c.name for c in model.__table__.c}


# ---------- Genel kayıt oluşturma/upsert ----------
def create_records(
        model: Type[SQLModel],
        data_list: list[dict],
        db_name: str,
        *,
        conflict_keys: Optional[list[str]] = None,  # ör: ["id","orderNumber","productCode","orderLineItemStatusName"]
        mode: str = "ignore",  # "ignore" | "update" | "plain"
        normalizer: Optional[Callable[[dict], dict]] = None,
        chunk_size: int = 500,
        rename_map: Optional[dict[str, str]] = None,  # YENİ: "3pByTrendyol" -> "byTrendyol3" gibi
        drop_unknown: bool = True,  # YENİ: modelde olmayan key'leri at
):
    """
    Genel toplu kayıt:
    - mode="ignore": conflict_keys çakışırsa ekleme (hata fırlatmaz)
    - mode="update": conflict_keys çakışırsa diğer kolonları güncelle
    - mode="plain": normal add (unique çakışırsa IntegrityError fırlar)
    - normalizer: her kaydı DB'ye gitmeden önce normalize eder
    - rename_map: DB’ye gitmeden önce key yeniden adlandırma
    - drop_unknown: modelde olmayan anahtarları süz
    """
    engine = get_engine(db_name)

    # 0) temizleme: rename + normalize + drop_unknown
    cols = get_model_columns(model) if drop_unknown else None
    cleaned: list[dict] = []
    for d in data_list:
        r = dict(d)

        # rename (opsiyonel)
        if rename_map:
            for old, new in list(rename_map.items()):
                if old in r:
                    r[new] = r.pop(old)

        # normalize (opsiyonel)
        if normalizer:
            r = normalizer(r)

        # modelde olmayanları at (opsiyonel)
        if drop_unknown and cols is not None:
            r = {k: v for k, v in r.items() if k in cols}

        if r:  # tamamen boş kalmışsa ekleme
            cleaned.append(r)

    with Session(engine) as session:
        try:
            if mode == "plain" or not conflict_keys:
                with session.begin():
                    for r in cleaned:
                        session.add(model(**r))
                return

            tbl = model.__table__

            if mode == "ignore":
                for chunk in batch_iter(cleaned, chunk_size):
                    stmt = sqlite_insert(tbl).values(chunk)
                    stmt = stmt.on_conflict_do_nothing(index_elements=conflict_keys)
                    session.exec(stmt)

            elif mode == "update":
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
                    session.exec(stmt)

            session.commit()

        except IntegrityError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise


def get_records(
        model: Type[SQLModel],
        db_engine: Engine,
        filters: Optional[dict] = None,
        custom_sql: Optional[str] = None,
        to_dataframe: bool = False
) -> Any:
    """
    Genel amaçlı veri çekme fonksiyonu.
    - `model`: SQLModel tablosu
    - `db_engine`: SQLAlchemy engine objesi
    - `filters`: dict olarak filtreler (örn. {"name": "Ali"})
    - `custom_sql`: Ham SQL sorgusu vermek istersen buradan gir.
    - `to_dataframe`: True ise sonucu pandas DataFrame olarak döndürür.
    """

    if custom_sql:
        with db_engine.connect() as conn:
            if to_dataframe:
                return pd.read_sql_query(custom_sql, conn)
            else:
                result = conn.execute(custom_sql)
                return result.fetchall()

    with Session(db_engine) as session:
        stmt = select(model)

        # Filtreleri uygula
        if filters:
            for attr, value in filters.items():
                stmt = stmt.where(getattr(model, attr) == value)

        result = session.exec(stmt).all()
        if to_dataframe:
            return pd.DataFrame([r.dict() for r in result])
        return result


def update_records(
        model: Type[SQLModel],
        db_engine: Engine,
        filters: dict,
        update_data: dict
):
    """
    Genel amaçlı update fonksiyonu.

    - `model`: Güncelleme yapılacak SQLModel sınıfı
    - `db_engine`: SQLAlchemy engine objesi
    - `filters`: Güncellenecek kayıtların filtreleri (örn: {"orderNumber": "123"})
    - `update_data`: Güncellenecek alanlar ve değerleri (örn: {"isPrinted": "True"})
    """
    try:
        with Session(db_engine) as session:
            stmt = select(model)
            for attr, value in filters.items():
                stmt = stmt.where(getattr(model, attr) == value)

            results = session.exec(stmt).all()

            for item in results:
                for attr, value in update_data.items():
                    setattr(item, attr, value)

            session.commit()

    except Exception as e:
        print(f"[HATA] Kayıt güncellenemedi: {e}")



def delete_records(
        model: Type[SQLModel],
        db_engine: Engine,
        filters: dict
) -> object:
    """
    Genel amaçlı delete fonksiyonu.

    - `model`: Silme yapılacak SQLModel sınıfı
    - `db_engine`: SQLAlchemy engine objesi
    - `filters`: Silinecek kayıtların filtreleri (örn: {"orderNumber": "123"})
    """
    try:
        with Session(db_engine) as session:
            stmt = select(model)
            for attr, value in filters.items():
                stmt = stmt.where(getattr(model, attr) == value)

            results = session.exec(stmt).all()

            for item in results:
                session.delete(item)

            session.commit()
            print(f"[OK] {len(results)} kayıt silindi.")

    except Exception as e:
        print(f"[HATA] Kayıt silinemedi: {e}")
