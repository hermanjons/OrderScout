# model_utils.py
from sqlmodel import SQLModel, Session
from typing import Type
from dbase_set import engine  # sqlite:///databases/x.db bağlantılarını buradan al


def get_engine(db_name: str):
    """
    Belirtilen veritabanı ismine göre SQLite engine döner.
    Örnek: get_engine("orders.db") → sqlite:///databases/orders.db
    """
    db_path = os.path.join("databases", db_name)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


def insert_bulk_data(model: Type[SQLModel], data_list: list[dict], db_name: str):
    """
    Belirli bir modele ve veritabanına bulk veri ekler.
    """
    engine = engine.get_engine(db_name)
    with Session(engine) as session:
        for data in data_list:
            try:
                instance = model(**data)
                session.add(instance)
            except Exception as e:
                print(f"[HATA] {model.__name__} için veri eklenemedi: {e}")
        session.commit()
