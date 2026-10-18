"""Canonical synthetic business fixture for isolated acceptance tests.

Application imports stay lazy until the caller has configured its isolated DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def seed_business_fixture(
    db_name: str, *, isolation_root: str | Path, now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(isolation_root).resolve()
    database = Path(db_name).resolve()
    try:
        database.relative_to(root)
    except ValueError:
        raise ValueError("Acceptance database must be inside the isolated directory.") from None

    from sqlmodel import Session, SQLModel, select
    from Core.db import model_registry  # noqa: F401
    from Core.utils.model_utils import get_engine
    from Account.models.models import ApiAccount
    from Finance.models.trendyol.models import Company, FinanceManualTransaction, FinanceTransaction
    from Listing.models.models import ListingProduct, ListingProductStockSnapshot
    from Orders.models.trendyol.models import OrderData, OrderHeader, OrderItem
    from Stock.models.models import StockItem, StockTx, Warehouse
    from Stock.constants.domain_constants import StockTxDirection, StockTxReason

    current = now or datetime.now(timezone(timedelta(hours=3)))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone(timedelta(hours=3)))
    current = current.replace(hour=12, minute=0, second=0, microsecond=0)
    engine = get_engine(str(database))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(ApiAccount)).first() is not None:
            raise ValueError("Acceptance fixture requires an empty database.")
        session.add_all([
            ApiAccount(pk=101, account_id="2738", comp_name="Pilot Ana", platform="TRENDYOL",
                       extra_config={"environment": "stage"}, api_key="", api_secret=""),
            ApiAccount(pk=102, account_id="2738", comp_name="Pilot Yan", platform="TRENDYOL",
                       extra_config={"environment": "stage"}, api_key="", api_secret=""),
            Company(pk=201, name="Pilot Sentetik İşletme"),
            Warehouse(pk=301, name="Pilot Sentetik Depo", code="PILOT"),
            StockItem(pk=401, sku="PILOT-KUPA", name="Pilot Kupa", barcode="PILOT-KUPA-BAR",
                      unit="adet", min_stock=5, vat_rate=0, is_active=True),
            StockItem(pk=402, sku="PILOT-FILTRE", name="Pilot Filtre", barcode="PILOT-FILTRE-BAR",
                      unit="adet", min_stock=2, vat_rate=0, is_active=True),
            StockItem(pk=403, sku="PILOT-BOS", name="Pilot Boş Kart", unit="adet",
                      min_stock=1, vat_rate=0, is_active=True),
        ])
        session.flush()
        session.add_all([
            StockTx(item_id=401, warehouse_id=301, direction=StockTxDirection.IN_,
                    reason=StockTxReason.manual_in, qty=4, unit_cost=100, currency="TRY",
                    unit_cost_input_mode="gross", occurred_at=current.replace(tzinfo=None), company_id=201),
            StockTx(item_id=402, warehouse_id=301, direction=StockTxDirection.IN_,
                    reason=StockTxReason.manual_in, qty=3, unit_cost=10, currency="USD",
                    unit_cost_input_mode="gross", occurred_at=current.replace(tzinfo=None), company_id=201),
        ])
        for index, item_id, name, barcode in (
            (501, 401, "Pilot Kupa", "PILOT-KUPA-BAR"),
            (502, 402, "Pilot Filtre", "PILOT-FILTRE-BAR"),
        ):
            session.add(ListingProduct(pk=index, api_account_id=101, product_id=str(index),
                                       title=name, barcode=barcode, stock_code="PILOT-KUPA" if item_id == 401 else "PILOT-FILTRE",
                                       stock_item_id=item_id, sale_price=500, vat_rate=0,
                                       quantity=4 if item_id == 401 else 3, on_sale=True, approved=True,
                                       raw={"currencyCode": "TRY"}))
            session.flush()
            session.add(ListingProductStockSnapshot(listing_id=index, stock_item_id=item_id, qty=1))

        recipes = [
            (101, "PILOT-A-OLD-1", 10, "Delivered", 400, "PILOT-KUPA-BAR", "Pilot Kupa", 2),
            (101, "PILOT-A-OLD-2", 11, "Delivered", 400, "PILOT-KUPA-BAR", "Pilot Kupa", 2),
            (101, "PILOT-A-NEW-1", 1, "ReadyToShip", 1000, "PILOT-KUPA-BAR", "Pilot Kupa", 2),
            (101, "PILOT-A-NEW-2", 2, "Picking", 1000, "PILOT-FILTRE-BAR", "Pilot Filtre", 2),
            (101, "PILOT-A-NEW-3", 3, "Delivered", 1000, "PILOT-KUPA-BAR", "Pilot Kupa", 2),
            (102, "PILOT-B-NEW-1", 1, "ReadyToShip", 9000, "PILOT-KUPA-BAR", "Pilot Kupa", 1),
        ]
        for sequence, (account, number, days, status, revenue, barcode, name, quantity) in enumerate(recipes, 1):
            stamp = int((current - timedelta(days=days)).timestamp() * 1000)
            header = OrderHeader(orderNumber=number, api_account_id=account)
            session.add(header)
            session.flush()
            order = OrderData(orderNumber=number, api_account_id=account,
                              order_header_id=header.pk, id=10_000 + sequence, status=status,
                              shipmentPackageStatus=status, orderDate=stamp, lastModifiedDate=stamp,
                              currencyCode="TRY", packageTotalPrice=revenue, totalPrice=revenue,
                              cargoProviderName="ARASMP", supplierId=2738)
            session.add(order)
            session.flush()
            session.add(OrderItem(orderNumber=number, api_account_id=account,
                                  order_header_id=header.pk, order_data_pk=order.pk,
                                  order_data_id=order.id, snapshotLastModifiedDate=stamp,
                                  id=20_000 + sequence, quantity=quantity, barcode=barcode,
                                  productName=name, merchantSku="PILOT-KUPA" if "KUPA" in barcode else "PILOT-FILTRE",
                                  price=revenue / quantity, amount=revenue,
                                  currencyCode="TRY", vatRate=0, orderLineItemStatusName=status))
        stamp = int((current - timedelta(days=1)).timestamp() * 1000)
        session.add_all([
            FinanceTransaction(api_account_id=101, serviceKey="settlements", recordId="PILOT-FIN-TRY",
                               transactionDate=stamp, transactionType="Sale", currency="TRY",
                               credit=3000, debt=300, netAmount=2700,
                               description="Sentetik finans hareketi; gerçekleşmiş banka bakiyesi kanıtı değil."),
            FinanceTransaction(api_account_id=101, serviceKey="settlements", recordId="PILOT-FIN-USD",
                               transactionDate=stamp, transactionType="Sale", currency="USD",
                               credit=20, debt=0, netAmount=20),
            FinanceManualTransaction(transactionDate=stamp, direction="out", categoryKey="rent",
                                     categoryName="Kira", description="Sentetik gider kaydı",
                                     referenceNo="PILOT-RENT", amount=2500, currency="TRY", company_id=201),
        ])
        session.commit()

    return {
        "fixture_kind": "synthetic_business_acceptance_v1",
        "customer_data": False,
        "marketplace_credentials": False,
        "as_of": current.isoformat(),
        "accounts": [{"id": 101, "name": "Pilot Ana", "environment": "stage"},
                     {"id": 102, "name": "Pilot Yan", "environment": "stage"}],
        "orders": {
            "primary_account_id": 101, "total": 5, "recent_count": 3,
            "recent_revenue_try": 3000, "previous_count": 2, "previous_revenue_try": 800,
            "other_account_recent_revenue_try": 9000,
            "primary_order_numbers": [row[1] for row in recipes if row[0] == 101],
            "other_order_numbers": [row[1] for row in recipes if row[0] == 102],
        },
        "stock": {"stock_value_by_currency": {"TRY": 400, "USD": 30},
                  "balance_by_sku": {"PILOT-KUPA": 4, "PILOT-FILTRE": 3, "PILOT-BOS": 0}},
        "finance": {"movement_net_by_currency": {"TRY": 200, "USD": 20},
                    "bank_balance_observed": False, "settlement_realization_observed": False},
        "scope_limit": "Synthetic records. Shared company/account ownership and historical FX/cost are not inferred from fixture names.",
    }
