from typing import Any, Dict, List, Optional

from sqlalchemy import Column, Index, UniqueConstraint
from sqlmodel import Field, JSON, Relationship, SQLModel

from Account.models.models import ApiAccount
from Core.db.models import SourceIdentityMixin


class OrderHeader(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_order_header"

    pk: Optional[int] = Field(default=None, primary_key=True)
    orderNumber: str = Field(index=True)
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)

    is_printed: bool = Field(default=False, index=True)
    is_extracted: bool = Field(default=False, index=True)
    printed_at: Optional[int] = Field(default=None, index=True)
    extracted_at: Optional[int] = Field(default=None, index=True)

    api_account: Optional["ApiAccount"] = Relationship()
    snapshots: List["OrderData"] = Relationship(back_populates="header", cascade_delete=True)
    items: List["OrderItem"] = Relationship(back_populates="header", cascade_delete=True)
    claims: List["ReturnClaim"] = Relationship(back_populates="header", cascade_delete=True)

    __table_args__ = (
        UniqueConstraint("orderNumber", "api_account_id", name="uq_orderheader_orderno_accountid"),
    )


class OrderData(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_order_data"

    pk: Optional[int] = Field(default=None, primary_key=True)
    order_header_id: Optional[int] = Field(
        default=None,
        foreign_key="trendyol_order_header.pk",
        index=True,
    )
    orderNumber: str = Field(index=True)
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)

    header: Optional["OrderHeader"] = Relationship(back_populates="snapshots")
    api_account: Optional["ApiAccount"] = Relationship()
    items: List["OrderItem"] = Relationship(back_populates="order_snapshot")

    status: Optional[str] = Field(default=None, index=True)
    id: int
    shipmentPackageId: Optional[int] = Field(default=None, index=True)
    cargoTrackingNumber: Optional[str] = None
    cargoTrackingLink: Optional[str] = None
    cargoSenderNumber: Optional[str] = None
    cargoProviderName: Optional[str] = None
    customerId: Optional[int] = None
    customerFirstName: Optional[str] = None
    customerLastName: Optional[str] = None
    customerEmail: Optional[str] = None
    shipmentAddress: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    invoiceAddress: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    packageHistories: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    grossAmount: Optional[float] = None
    totalDiscount: Optional[float] = None
    totalTyDiscount: Optional[float] = None
    totalPrice: Optional[float] = None
    packageGrossAmount: Optional[float] = None
    packageSellerDiscount: Optional[float] = None
    packageTyDiscount: Optional[float] = None
    packageTotalDiscount: Optional[float] = None
    packageTotalPrice: Optional[float] = None
    discountDisplays: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    identityNumber: Optional[str] = None
    taxNumber: Optional[str] = None
    orderDate: Optional[int] = Field(index=True)
    currencyCode: Optional[str] = None
    shipmentPackageStatus: Optional[str] = Field(default=None, index=True)
    deliveryType: Optional[str] = None
    timeSlotId: Optional[int] = None
    estimatedDeliveryStartDate: Optional[int] = None
    estimatedDeliveryEndDate: Optional[int] = None
    deliveryAddressType: Optional[str] = None
    agreedDeliveryDate: Optional[int] = None
    fastDelivery: Optional[bool] = None
    commercial: Optional[bool] = None
    deliveredByService: Optional[bool] = None
    originShipmentDate: Optional[int] = None
    lastModifiedDate: int = Field(index=True)
    fastDeliveryType: Optional[str] = None
    warehouseId: Optional[int] = None
    supplierId: Optional[int] = None
    whoPays: Optional[str] = None
    invoiceLink: Optional[str] = None
    micro: Optional[bool] = None
    giftBoxRequested: Optional[bool] = None
    byTrendyol3: Optional[bool] = None
    etgbNo: Optional[str] = None
    etgbDate: Optional[int] = None
    containsDangerousProduct: Optional[bool] = None
    cargoDeci: Optional[float] = None
    isCod: Optional[bool] = None
    createdBy: Optional[str] = None
    originPackageIds: Optional[List[int]] = Field(default=None, sa_column=Column(JSON))
    hsCode: Optional[str] = None
    shipmentNumber: Optional[str] = None

    __table_args__ = (
        UniqueConstraint("id", "lastModifiedDate", "api_account_id", name="uq_orderdata_id_lastmod_accountid"),
        Index("ix_trendyol_order_data_account_orderno_lastmod", "api_account_id", "orderNumber", "lastModifiedDate"),
        Index("ix_trendyol_order_data_header_lastmod", "order_header_id", "lastModifiedDate"),
        Index("ix_trendyol_order_data_orderno_lastmod", "orderNumber", "lastModifiedDate"),
        Index("ix_trendyol_order_data_orderno_status_lastmod", "orderNumber", "status", "lastModifiedDate"),
        Index("ix_trendyol_order_data_package_lastmod", "id", "lastModifiedDate"),
        Index("ix_trendyol_order_data_shipment_orderdate", "shipmentPackageStatus", "orderDate"),
    )


class OrderItem(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_order_item"

    pk: Optional[int] = Field(default=None, primary_key=True)
    order_header_id: Optional[int] = Field(
        default=None,
        foreign_key="trendyol_order_header.pk",
        index=True,
    )
    orderNumber: str = Field(index=True)
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)

    header: Optional["OrderHeader"] = Relationship(back_populates="items")
    order_data_pk: Optional[int] = Field(
        default=None,
        foreign_key="trendyol_order_data.pk",
        index=True,
    )
    order_snapshot: Optional["OrderData"] = Relationship(back_populates="items")
    order_data_id: Optional[int] = None
    snapshotLastModifiedDate: Optional[int] = Field(default=None, index=True)

    quantity: int
    productSize: Optional[str] = None
    merchantSku: Optional[str] = None
    stockCode: Optional[str] = None
    salesCampaignId: Optional[str] = None
    contentId: Optional[int] = None
    productName: Optional[str] = None
    productCode: Optional[int] = None
    productOrigin: Optional[str] = None
    merchantId: Optional[int] = None
    sellerId: Optional[int] = None

    amount: Optional[float] = None
    lineGrossAmount: Optional[float] = None
    lineTotalDiscount: Optional[float] = None
    lineSellerDiscount: Optional[float] = None
    tyDiscount: Optional[float] = None
    lineTyDiscount: Optional[float] = None
    vatBaseAmount: Optional[float] = None
    price: Optional[float] = None
    lineUnitPrice: Optional[float] = None
    discount: Optional[float] = None
    commission: Optional[float] = Field(default=None)

    currencyCode: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    orderLineItemStatusName: Optional[str] = None
    taskDate: Optional[int] = None
    productColor: Optional[str] = None
    id: Optional[int] = None
    lineId: Optional[int] = Field(default=None, index=True)
    vatRate: Optional[float] = None
    fastDeliveryOptions: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    productCategoryId: Optional[int] = None
    cancelledBy: Optional[str] = None
    cancelReason: Optional[str] = None
    cancelReasonCode: Optional[str] = None
    discountDetails: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    businessUnit: Optional[str] = None
    laborCost: Optional[float] = None

    __table_args__ = (
        UniqueConstraint(
            "order_data_id",
            "snapshotLastModifiedDate",
            "lineId",
            "api_account_id",
            name="uq_orderitem_snapshot_line_account",
        ),
        Index("ix_trendyol_order_item_orderno_productcode", "orderNumber", "productCode"),
        Index("ix_trendyol_order_item_orderdatapk_line", "order_data_pk", "lineId"),
        Index("ix_trendyol_order_item_snapshot_line", "order_data_id", "snapshotLastModifiedDate", "lineId"),
    )


class ReturnClaim(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_return_claim"

    pk: Optional[int] = Field(default=None, primary_key=True)
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)
    order_header_id: Optional[int] = Field(
        default=None,
        foreign_key="trendyol_order_header.pk",
        index=True,
    )

    header: Optional["OrderHeader"] = Relationship(back_populates="claims")

    claimId: str = Field(index=True)
    claimNumber: Optional[str] = Field(default=None, index=True)
    orderNumber: Optional[str] = Field(default=None, index=True)
    orderShipmentPackageId: Optional[int] = Field(default=None, index=True)
    orderOutboundPackageId: Optional[int] = Field(default=None, index=True)

    customerFirstName: Optional[str] = None
    customerLastName: Optional[str] = None
    cargoTrackingNumber: Optional[str] = None
    cargoTrackingLink: Optional[str] = None
    cargoProviderName: Optional[str] = None
    cargoSenderNumber: Optional[str] = None

    claimDate: Optional[int] = Field(default=None, index=True)
    orderDate: Optional[int] = Field(default=None, index=True)
    lastModifiedDate: int = Field(index=True)

    claimItemStatus: Optional[str] = Field(default=None, index=True)
    claimReason: Optional[str] = None
    totalPrice: Optional[float] = None
    currencyCode: Optional[str] = None
    itemCount: Optional[int] = None

    claimLineItemIds: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    waitingClaimLineItemIds: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    claimItemStatuses: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    claimReasons: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    itemsJson: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    replacementOutboundPackageInfo: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    rejectedPackageInfo: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    rawData: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    __table_args__ = (
        UniqueConstraint("claimId", "lastModifiedDate", "api_account_id", name="uq_returnclaim_claimid_lastmod_accountid"),
        Index("ix_trendyol_return_claim_account_claim_lastmod", "api_account_id", "claimId", "lastModifiedDate"),
        Index("ix_trendyol_return_claim_claim_lastmod", "claimId", "lastModifiedDate"),
        Index("ix_trendyol_return_claim_orderno_lastmod", "orderNumber", "lastModifiedDate"),
        Index("ix_trendyol_return_claim_status_claimdate", "claimItemStatus", "claimDate"),
    )
