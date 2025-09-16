from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import Column, UniqueConstraint, Index
from sqlmodel import SQLModel, Field, Relationship, JSON
from Account.models import ApiAccount


# ---- ROOT: Siparişin temel kaydı ----
class OrderHeader(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)  # ✅ Otomatik birincil anahtar

    orderNumber: str = Field(index=True)
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)
    api_account: Optional[ApiAccount] = Relationship()

    snapshots: List["OrderData"] = Relationship(back_populates="header")
    items: List["OrderItem"] = Relationship(back_populates="header")

    __table_args__ = (
        UniqueConstraint("orderNumber", "api_account_id", name="uq_orderheader_orderno_accountid"),
    )


# ---- ZAMAN DAMGALI HAL: Siparişin snapshot'ı ----
class OrderData(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)

    orderNumber: str = Field(foreign_key="orderheader.orderNumber", index=True)
    header: Optional[OrderHeader] = Relationship(back_populates="snapshots")
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)

    status: Optional[str] = Field(default=None, index=True)

    id: int
    cargoTrackingNumber: Optional[str] = None
    cargoProviderName: Optional[str] = None
    customerId: Optional[int] = None
    customerFirstName: Optional[str] = None
    customerLastName: Optional[str] = None
    shipmentAddress: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    invoiceAddress: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    grossAmount: Optional[float] = None
    totalDiscount: Optional[float] = None
    totalTyDiscount: Optional[float] = None
    totalPrice: Optional[float] = None
    tcIdentityNumber: Optional[str] = None
    orderDate: Optional[int] = Field(index=True)
    currencyCode: Optional[str] = None
    shipmentPackageStatus: Optional[str] = None
    deliveryType: Optional[str] = None
    timeSlotId: Optional[int] = None
    scheduledDeliveryStoreId: Optional[int] = None
    estimatedDeliveryStartDate: Optional[int] = None
    estimatedDeliveryEndDate: Optional[int] = None
    deliveryAddressType: Optional[str] = None
    agreedDeliveryDate: Optional[str] = None
    fastDelivery: Optional[bool] = None
    commercial: Optional[bool] = None
    deliveredByService: Optional[bool] = None
    agreedDeliveryDateExtendible: Optional[bool] = None
    groupDeal: Optional[bool] = None
    originShipmentDate: Optional[int] = None
    lastModifiedDate: int = Field(index=True)
    fastDeliveryType: Optional[str] = None
    encodedCtNumber: Optional[str] = None
    extendedAgreedDeliveryDate: Optional[str] = None
    agreedDeliveryExtensionEndDate: Optional[str] = None
    agreedDeliveryExtensionStartDate: Optional[str] = None
    warehouseId: Optional[int] = None
    totalProfit: Optional[float] = None
    printed_date: Optional[datetime] = None

    __table_args__ = (
        UniqueConstraint("orderNumber", "lastModifiedDate", "api_account_id", name="uq_orderno_lastmod_accountid"),
        Index("ix_orderno_lastmod", "orderNumber", "lastModifiedDate"),
        Index("ix_orderno_status_lastmod", "orderNumber", "status", "lastModifiedDate"),
    )


# ---- SATIR VERİSİ: Siparişin içeriği ----
class OrderItem(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)  # ✅ Auto PK

    orderNumber: str = Field(foreign_key="orderheader.orderNumber", index=True)
    header: Optional[OrderHeader] = Relationship(back_populates="items")

    # 🔁 Ek alanlar
    order_data_id: Optional[int] = None  # eski 'id', ama artık item değil snapshot ID'si
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)  # ✅ Eklendi

    quantity: int
    productSize: Optional[str] = None
    merchantSku: Optional[str] = None
    salesCampaignId: Optional[str] = None
    productName: Optional[str] = None
    productCode: Optional[int] = None
    merchantId: Optional[int] = None

    amount: Optional[float] = None
    tyDiscount: Optional[float] = None
    vatBaseAmount: Optional[float] = None
    price: Optional[float] = None
    discount: Optional[float] = None
    commission: Optional[float] = Field(default=None)

    currencyCode: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    orderLineItemStatusName: Optional[str] = None
    taskDate: Optional[int] = None

    __table_args__ = (
        UniqueConstraint(
            "orderNumber", "productCode", "orderLineItemStatusName", "api_account_id",
            name="uq_item_orderno_productcode_status_api"
        ),
        Index("ix_orderitem_orderno_productcode", "orderNumber", "productCode"),
    )




# ---- Dış Veri: Kırpılmış veriler (opsiyonel) ----
class ScrapData(SQLModel, table=True):
    scrap_date: int = Field(primary_key=True)
