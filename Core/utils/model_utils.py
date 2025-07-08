# model_utils.py
from sqlmodel import SQLModel, Session, select
from typing import Type, Optional, List, Any
from settings import DB_NAME, DEFAULT_DATABASE_DIR
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine

import pandas as pd


def get_engine(db_name: str):
    """
    Belirtilen veritabanı ismine göre SQLite engine döner.
    Örnek: get_engine("orders.db") → sqlite:///databases/orders.db
    """
    db_path = os.path.join(DEFAULT_DATABASE_DIR, db_name)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


def create_records(model: Type[SQLModel], data_list: list[dict], db_name: str):
    """
    Belirli bir modele ve veritabanına bulk veri ekler.
    """
    engine = get_engine(db_name)
    with Session(engine) as session:
        for data in data_list:
            try:
                instance = model(**data)
                session.add(instance)
            except Exception as e:
                print(f"[HATA] {model.__name__} için veri eklenemedi: {e}")
        session.commit()


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
