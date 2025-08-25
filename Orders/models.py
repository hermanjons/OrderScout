from typing import Optional, Dict,Any,List
from datetime import datetime
from sqlalchemy import UniqueConstraint, Index
from sqlmodel import SQLModel, Field, Column, UniqueConstraint, Index, JSON,Relationship


# ---- ROOT: Tekil sipariş kimliği ----
class OrderHeader(SQLModel, table=True):
    # orderNumber her sipariş için tekil kök anahtar
    orderNumber: str = Field(primary_key=True, index=True)

    # ilişkiler
    items: List["OrderItem"] = Relationship(back_populates="order")
    snapshots: List["OrderData"] = Relationship(back_populates="header")


# ---- SNAPSHOT/EVENT: Siparişin zamana bağlı halleri ----
class OrderData(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)

    # köke FK
    orderNumber: str = Field(foreign_key="orderheader.orderNumber", index=True)
    header: Optional[OrderHeader] = Relationship(back_populates="snapshots")

    status: Optional[str] = Field(default=None, index=True)

    # Trendyol alanları (kısaltılmış)
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

    # orderDate raporlama/filtre için dursun (eşsizlikte kullanılmıyor)
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

    # EN KRİTİK: en güncel snapshot'ı belirler
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
        # aynı siparişin her event'i tekil
        UniqueConstraint("orderNumber", "lastModifiedDate", name="uq_orderno_lastmod"),
        Index("ix_orderno_lastmod", "orderNumber", "lastModifiedDate"),
        Index("ix_orderno_status_lastmod", "orderNumber", "status", "lastModifiedDate"),
    )


# ---- ITEMS: Sipariş satırları (bire-çok) ----
class OrderItem(SQLModel, table=True):
    # Trendyol line item id genelde tekil; PK olarak kullan
    id: int = Field(primary_key=True)

    # köke FK (tek siparişe ait)
    orderNumber: str = Field(foreign_key="orderheader.orderNumber", index=True)
    order: Optional[OrderHeader] = Relationship(back_populates="items")

    # diğer alanlar
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

    currencyCode: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    orderLineItemStatusName: Optional[str] = None
    taskDate: Optional[int] = None  # (varsa kullan; yoksa kaldırabilirsin)

    __table_args__ = (
        # join ve sorgu performansı
        Index("ix_orderitem_orderno_id", "orderNumber", "id"),
    )


class ScrapData(SQLModel, table=True):
    scrap_date: int = Field(primary_key=True)
