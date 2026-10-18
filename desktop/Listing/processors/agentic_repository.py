from __future__ import annotations

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Listing.models.models import ListingProduct, ListingProductCostSnapshot, ListingProductStockSnapshot
from settings import DB_NAME


def list_products(*, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = session.exec(select(ListingProduct)).all() or []
        return Result.ok("Listing kayitlari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def verification_bundle(*, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            products = session.exec(select(ListingProduct)).all() or []
            stock_snapshots = session.exec(select(ListingProductStockSnapshot)).all() or []
            cost_snapshots = session.exec(select(ListingProductCostSnapshot)).all() or []
        return Result.ok(
            "Listing verify kayitlari getirildi.",
            close_dialog=False,
            data={
                "products": products,
                "stock_snapshots": stock_snapshots,
                "cost_snapshots": cost_snapshots,
            },
        )
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
