"""A complete-year order population, written only inside isolated test storage."""
from datetime import datetime, timedelta, timezone
from pathlib import Path


def seed_order_snapshot_fixture(db_name, *, isolation_root, count=570):
    from Testing.processors.business_agent_fixtures import seed_business_fixture
    from sqlmodel import Session, select
    from Core.utils.model_utils import get_engine
    from Orders.models.trendyol.models import OrderData, OrderHeader
    fixture = seed_business_fixture(db_name, isolation_root=isolation_root)
    Path(db_name).resolve().relative_to(Path(isolation_root).resolve())
    now = datetime.now(timezone(timedelta(hours=3))).replace(hour=12, minute=0, second=0, microsecond=0)
    with Session(get_engine(db_name)) as session:
        existing = list(session.exec(select(OrderData)).all())
        for index in range(count - len(existing) + 1):
            outside = index == count - len(existing)
            number = "SNAPSHOT-OUTSIDE" if outside else f"SNAPSHOT-{index:04}"
            stamp = int((now - timedelta(days=800 if outside else 1 + index % 350)).timestamp() * 1000)
            header = OrderHeader(orderNumber=number, api_account_id=101)
            session.add(header)
            session.flush()
            session.add(OrderData(orderNumber=number, api_account_id=101, order_header_id=header.pk,
                id=100_000 + index, status="Delivered", shipmentPackageStatus="Delivered", currencyCode="TRY",
                totalPrice=10 + index, packageTotalPrice=10 + index, orderDate=stamp, lastModifiedDate=stamp))
        session.commit()
    return {**fixture, "year_order_count": count, "outside_order_number": "SNAPSHOT-OUTSIDE"}
