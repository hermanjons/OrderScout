from __future__ import annotations

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Stock.models.models import StockItem, StockTx, Warehouse
from settings import DB_NAME


def list_items(*, active_only: bool = False, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(StockItem)
            if active_only:
                stmt = stmt.where(StockItem.is_active.is_(True))
            rows = session.exec(stmt).all() or []
        return Result.ok("Stok kalemleri getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_transactions(
    *,
    item_ids: list[int] | None = None,
    db_name: str = DB_NAME,
) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(StockTx)
            normalized_item_ids = [
                int(value)
                for value in list(item_ids or [])
                if value not in (None, "")
            ]
            if normalized_item_ids:
                stmt = stmt.where(StockTx.item_id.in_(normalized_item_ids))
            rows = session.exec(stmt.order_by(StockTx.pk.asc())).all() or []
        return Result.ok("Stok hareketleri getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_warehouses(*, active_only: bool = False, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(Warehouse)
            if active_only:
                stmt = stmt.where(Warehouse.is_active.is_(True))
            rows = session.exec(stmt).all() or []
        return Result.ok("Depolar getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
