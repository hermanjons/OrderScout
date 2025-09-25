# Orders/custom_queries.py
from sqlmodel import select, func
from Orders.models.trendyol.trendyol_models import OrderData
from sqlalchemy.orm import aliased
from sqlalchemy.orm import selectinload

# -------------------------------------------------
# 📦 ReadyToShip Siparişler (en güncel snapshot)
# -------------------------------------------------
def latest_ready_to_ship_query():
    """
    Her api_account_id + orderNumber için en güncel ReadyToShip siparişleri döner.
    Bu sadece SQLModel query nesnesini üretir, çalıştırma işini get_records yapar.
    """
    # Subquery → api_account_id + orderNumber için max(lastModifiedDate)
    subq = (
        select(
            OrderData.api_account_id,
            OrderData.orderNumber,
            func.max(OrderData.lastModifiedDate).label("max_date")
        )
        .group_by(OrderData.api_account_id, OrderData.orderNumber)
        .subquery()
    )

    # Ana query → subquery join + ReadyToShip filtrele


    OD = aliased(OrderData)

    stmt = (
        select(OD)
        .join(
            subq,
            (OD.api_account_id == subq.c.api_account_id)
            & (OD.orderNumber == subq.c.orderNumber)
            & (OD.lastModifiedDate == subq.c.max_date)
        )
        .where(OD.shipmentPackageStatus == "ReadyToShip")
        .options(selectinload(OD.api_account))  # 🔑 BURASI
    )

    return stmt
