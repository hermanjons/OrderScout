from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON,UniqueConstraint


class OrderData(SQLModel, table=True):
    # Trendyol'da çok büyük olabildiği için str PK
    orderNumber: str = Field(primary_key=True)
    id: int

    cargoTrackingNumber: Optional[str] = None
    cargoProviderName: Optional[str] = None
    customerId: Optional[int] = None
    customerFirstName: Optional[str] = None
    customerLastName: Optional[str] = None

    # API dict döndürüyor → JSON kolon
    shipmentAddress: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    invoiceAddress: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    grossAmount: Optional[float] = None
    totalDiscount: Optional[float] = None
    totalTyDiscount: Optional[float] = None
    totalPrice: Optional[float] = None  # int değil, float

    tcIdentityNumber: Optional[str] = None
    orderDate: Optional[int] = None
    currencyCode: Optional[str] = None
    shipmentPackageStatus: Optional[str] = None
    status: Optional[str] = None
    deliveryType: Optional[str] = None
    timeSlotId: Optional[int] = None
    scheduledDeliveryStoreId: Optional[int] = None
    estimatedDeliveryStartDate: Optional[int] = None
    estimatedDeliveryEndDate: Optional[int] = None
    deliveryAddressType: Optional[str] = None
    agreedDeliveryDate: Optional[str] = None

    # payload bool döndürüyor
    fastDelivery: Optional[bool] = None
    commercial: Optional[bool] = None
    deliveredByService: Optional[bool] = None
    agreedDeliveryDateExtendible: Optional[bool] = None
    groupDeal: Optional[bool] = None

    originShipmentDate: Optional[int] = None
    lastModifiedDate: int
    fastDeliveryType: Optional[str] = None
    encodedCtNumber: Optional[str] = None
    extendedAgreedDeliveryDate: Optional[str] = None
    agreedDeliveryExtensionEndDate: Optional[str] = None
    agreedDeliveryExtensionStartDate: Optional[str] = None
    warehouseId: Optional[int] = None
    totalProfit: Optional[float] = None


class OrderItem(SQLModel, table=True):
    # Yapay PK (auto increment) — FK ve ORM işleri çok kolay olur
    pk: Optional[int] = Field(default=None, primary_key=True)

    # Doğal alanlar
    id: int                                     # Trendyol lineItemId
    orderNumber: str = Field(foreign_key="orderdata.orderNumber", index=True)
    productCode: int
    orderLineItemStatusName: str

    # Diğer alanlar
    quantity: Optional[int] = None
    productSize: Optional[str] = None
    merchantSku: Optional[str] = None
    salesCampaignId: Optional[str] = None
    productName: Optional[str] = None
    merchantId: Optional[int] = None

    amount: Optional[float] = None
    tyDiscount: Optional[float] = None
    vatBaseAmount: Optional[float] = None
    price: Optional[float] = None
    discount: Optional[float] = None

    currencyCode: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    taskDate: Optional[int] = None

    __table_args__ = (
        UniqueConstraint("id", "orderNumber", "productCode", "orderLineItemStatusName",
                         name="uq_item_id_order_prod_status"),
    )


class ScrapData(SQLModel, table=True):
    scrap_date: int = Field(primary_key=True)
