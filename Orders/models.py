from sqlmodel import SQLModel, Field
from typing import Optional


class OrderData(SQLModel, table=True):
    orderNumber: int = Field(primary_key=True)
    id: int
    cargoTrackingNumber: Optional[str] = None
    cargoProviderName: Optional[str] = None
    customerId: Optional[int] = None
    customerFirstName: Optional[str] = None
    customerLastName: Optional[str] = None
    shipmentAddress: Optional[str] = None
    grossAmount: Optional[float] = None
    totalDiscount: Optional[float] = None
    totalTyDiscount: Optional[float] = None
    invoiceAddress: Optional[str] = None
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
    totalPrice: Optional[int] = None
    deliveryAddressType: Optional[str] = None
    agreedDeliveryDate: Optional[str] = None
    fastDelivery: Optional[str] = None
    originShipmentDate: Optional[str] = None
    lastModifiedDate: int
    commercial: Optional[str] = None
    fastDeliveryType: Optional[str] = None
    deliveredByService: Optional[str] = None
    agreedDeliveryDateExtendible: Optional[str] = None
    extendedAgreedDeliveryDate: Optional[str] = None
    agreedDeliveryExtensionEndDate: Optional[str] = None
    agreedDeliveryExtensionStartDate: Optional[str] = None
    warehouseId: Optional[int] = None
    groupDeal: Optional[str] = None
    encodedCtNumber: Optional[str] = None
    totalProfit: Optional[float] = None


class OrderItem(SQLModel, table=True):
    pk: int = Field(default=None, primary_key=True)
    quantity: int
    productSize: Optional[str] = None
    merchantSku: Optional[str] = None
    salesCampaignId: Optional[str] = None
    productName: Optional[str] = None
    productCode: Optional[int] = None
    merchantId: Optional[int] = None
    amount: Optional[float] = None
    tyDiscount: Optional[float] = None
    currencyCode: Optional[str] = None
    discount: Optional[int] = None
    id: int
    vatBaseAmount: Optional[float] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    orderLineItemStatusName: Optional[str] = None
    price: Optional[int] = None
    orderNumber: int
    taskDate: Optional[int] = None


class ScrapData(SQLModel, table=True):
    scrap_date: int = Field(primary_key=True)
