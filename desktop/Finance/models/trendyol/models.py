from typing import Optional

from sqlalchemy import UniqueConstraint, Index
from sqlmodel import SQLModel, Field, Relationship

from Account.models.models import ApiAccount
from Marketplaces.models.models import Marketplace
from Core.db.models import SourceIdentityMixin


class Brand(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "brand"

    pk: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    code: Optional[str] = Field(default=None, max_length=80)
    registration_no: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=120)
    website: Optional[str] = Field(default=None, max_length=180)
    contact_email: Optional[str] = Field(default=None, max_length=120)
    contact_phone: Optional[str] = Field(default=None, max_length=40)
    address: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)

    __table_args__ = (
        Index("ix_brand_name_unique", "name", unique=True),
    )


class Company(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "company"

    pk: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=160)
    tax_no: Optional[str] = Field(default=None, max_length=40)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    note: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)

    __table_args__ = (
        Index("ix_company_name_unique", "name", unique=True),
    )


class FinanceTransaction(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_finance_transaction"

    pk: Optional[int] = Field(default=None, primary_key=True)

    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)
    api_account: Optional["ApiAccount"] = Relationship()

    serviceKey: str = Field(index=True)
    sellerId: Optional[int] = Field(default=None, index=True)

    recordId: str = Field(index=True)
    transactionType: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None

    transactionDate: Optional[int] = Field(default=None, index=True)
    orderDate: Optional[int] = Field(default=None, index=True)
    paymentDate: Optional[int] = Field(default=None, index=True)

    orderNumber: Optional[str] = Field(default=None, index=True)
    shipmentPackageId: Optional[int] = Field(default=None, index=True)
    barcode: Optional[str] = Field(default=None, index=True)
    receiptId: Optional[int] = None
    paymentOrderId: Optional[str] = Field(default=None, index=True)
    paymentPeriod: Optional[int] = None

    currency: Optional[str] = None
    country: Optional[str] = None
    affiliate: Optional[str] = None

    debt: Optional[float] = None
    credit: Optional[float] = None
    netAmount: Optional[float] = None
    sellerRevenue: Optional[float] = None
    commissionRate: Optional[float] = None
    commissionAmount: Optional[float] = None
    commissionInvoiceSerialNumber: Optional[str] = Field(default=None, index=True)

    storeId: Optional[int] = None
    storeName: Optional[str] = None
    storeAddress: Optional[str] = None

    __table_args__ = (
        UniqueConstraint(
            "serviceKey",
            "api_account_id",
            "recordId",
            "transactionDate",
            name="uq_financetransaction_service_account_record_date",
        ),
        Index("ix_financetransaction_orderno_date", "orderNumber", "transactionDate"),
        Index("ix_financetransaction_serial_date", "commissionInvoiceSerialNumber", "transactionDate"),
        Index("ix_financetransaction_service_type_date", "serviceKey", "transactionType", "transactionDate"),
    )


class FinanceCargoInvoiceItem(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_finance_cargo_invoice_item"

    pk: Optional[int] = Field(default=None, primary_key=True)

    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)
    api_account: Optional["ApiAccount"] = Relationship()

    sellerId: Optional[int] = Field(default=None, index=True)
    invoiceSerialNumber: str = Field(index=True)
    parcelUniqueId: Optional[int] = Field(default=None, index=True)
    orderNumber: Optional[str] = Field(default=None, index=True)
    shipmentPackageType: Optional[str] = Field(default=None, index=True)
    amount: Optional[float] = None
    desi: Optional[float] = None

    __table_args__ = (
        UniqueConstraint(
            "api_account_id",
            "invoiceSerialNumber",
            "parcelUniqueId",
            "shipmentPackageType",
            name="uq_financecargoitem_account_invoice_parcel_type",
        ),
        Index("ix_financecargoitem_invoice_orderno", "invoiceSerialNumber", "orderNumber"),
    )


class FinanceManualTransaction(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "finance_manual_transaction"

    pk: Optional[int] = Field(default=None, primary_key=True)

    transactionDate: int = Field(index=True)
    direction: str = Field(index=True, max_length=24)
    categoryKey: Optional[str] = Field(default=None, index=True, max_length=80)
    categoryName: Optional[str] = Field(default=None, index=True, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    referenceNo: Optional[str] = Field(default=None, index=True, max_length=120)

    amount: float
    currency: Optional[str] = Field(default="TRY", index=True, max_length=8)
    isVatIncluded: bool = Field(default=True, index=True)
    vatRate: Optional[float] = Field(default=None)

    company_id: Optional[int] = Field(default=None, foreign_key="company.pk", index=True)
    company: Optional["Company"] = Relationship()
    counterparty: Optional[str] = Field(default=None, index=True, max_length=160)

    paymentMethod: Optional[str] = Field(default=None, max_length=80)
    attachmentsJson: Optional[str] = Field(default=None, max_length=4000)
    note: Optional[str] = Field(default=None, max_length=500)
    isDeleted: bool = Field(default=False, index=True)

    __table_args__ = (
        Index("ix_finance_manual_tx_date_direction", "transactionDate", "direction"),
        Index("ix_finance_manual_tx_category_date", "categoryKey", "transactionDate"),
        Index("ix_finance_manual_tx_company_date", "company_id", "transactionDate"),
    )


class FinanceInvoiceDocument(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "finance_invoice_document"

    pk: Optional[int] = Field(default=None, primary_key=True)

    invoiceNumber: str = Field(index=True, max_length=120)
    invoiceType: Optional[str] = Field(default=None, index=True, max_length=80)
    invoiceDate: int = Field(index=True)
    dueDate: Optional[int] = Field(default=None, index=True)

    company_id: Optional[int] = Field(default=None, foreign_key="company.pk", index=True)
    company: Optional["Company"] = Relationship()
    counterparty: Optional[str] = Field(default=None, index=True, max_length=160)

    totalAmount: Optional[float] = Field(default=None)
    vatAmount: Optional[float] = Field(default=None)
    currency: Optional[str] = Field(default="TRY", index=True, max_length=8)

    filePath: str = Field(max_length=1000)
    fileType: Optional[str] = Field(default=None, index=True, max_length=24)
    officialStatus: str = Field(default="official_copy", index=True, max_length=40)

    marketplace_id: Optional[int] = Field(default=None, foreign_key="marketplace.pk", index=True)
    marketplace: Optional["Marketplace"] = Relationship()
    api_account_id: Optional[int] = Field(default=None, foreign_key="apiaccount.pk", index=True)
    api_account: Optional["ApiAccount"] = Relationship()
    sourceTable: Optional[str] = Field(default=None, index=True, max_length=120)
    sourcePk: Optional[int] = Field(default=None, index=True)
    sourceReference: Optional[str] = Field(default=None, index=True, max_length=180)

    note: Optional[str] = Field(default=None, max_length=500)
    isDeleted: bool = Field(default=False, index=True)

    __table_args__ = (
        UniqueConstraint("invoiceNumber", "filePath", name="uq_finance_invoice_doc_number_file"),
        Index("ix_finance_invoice_doc_type_date", "invoiceType", "invoiceDate"),
        Index("ix_finance_invoice_doc_company_date", "company_id", "invoiceDate"),
        Index("ix_finance_invoice_doc_marketplace_ref", "marketplace_id", "sourceReference"),
    )


class FinanceCostItem(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "cost_item"

    pk: Optional[int] = Field(default=None, primary_key=True)

    costKey: str = Field(index=True)
    name: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None

    valueType: Optional[str] = Field(default=None, index=True)
    defaultMatchMode: Optional[str] = Field(default=None, index=True)
    defaultAmount: Optional[float] = Field(default=None)
    currency: Optional[str] = Field(default="TRY", index=True)
    isVatIncluded: bool = Field(default=True, index=True)
    vatRate: Optional[float] = Field(default=None)

    supportedSourceTypesJson: str = Field(default="[]")
    supportedPlatformsJson: str = Field(default="[]")
    supportedPlatformSourceIdsJson: str = Field(default="[]")
    defaultSourceType: Optional[str] = Field(default=None, index=True)
    defaultSourceConfigJson: Optional[str] = Field(default=None)

    isActive: bool = Field(default=True, index=True)
    isDeleted: bool = Field(default=False, index=True)
    createdAt: str = Field(index=True)
    updatedAt: str = Field(index=True)

    __table_args__ = (
        UniqueConstraint("costKey", name="uq_cost_item_costkey"),
        Index("ix_cost_item_active_updated", "isActive", "updatedAt"),
        Index("ix_cost_item_deleted_updated", "isDeleted", "updatedAt"),
    )


class FinanceCostItemMarketplaceLink(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "cost_item_marketplace_link"

    pk: Optional[int] = Field(default=None, primary_key=True)

    cost_item_id: int = Field(foreign_key="cost_item.pk", index=True)
    marketplace_id: int = Field(foreign_key="marketplace.pk", index=True)

    createdAt: str = Field(index=True)
    updatedAt: str = Field(index=True)

    __table_args__ = (
        UniqueConstraint("cost_item_id", "marketplace_id", name="uq_cost_item_marketplace_link_pair"),
        Index("ix_cost_item_marketplace_link_marketplace", "marketplace_id", "cost_item_id"),
    )
