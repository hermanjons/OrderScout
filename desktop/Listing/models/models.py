from __future__ import annotations

from typing import Optional

from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint, Index
from Core.db.models import SourceIdentityMixin
from Finance.models.trendyol.models import FinanceCostItem  # noqa: F401
from Logistics.models.models import LogisticsCargoProvider  # noqa: F401


class ListingProduct(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_listing_product"
    __table_args__ = (
        UniqueConstraint("api_account_id", "product_id", name="uq_trendyol_listing_product_acc_prod"),
        Index("ix_trendyol_listing_product_stock_item", "stock_item_id"),
        Index("ix_trendyol_listing_product_account_updated", "api_account_id", "updated_at"),
        Index("ix_trendyol_listing_product_account_status_updated", "api_account_id", "archived", "on_sale", "updated_at"),
        Index("ix_trendyol_listing_product_account_qty_updated", "api_account_id", "archived", "quantity", "updated_at"),
        Index("ix_trendyol_listing_product_account_brand_updated", "api_account_id", "brand", "updated_at"),
    )

    pk: Optional[int] = Field(default=None, primary_key=True)

    api_account_id: int = Field(index=True, foreign_key="apiaccount.pk")
    product_id: str = Field(index=True, max_length=64)

    product_code: Optional[str] = Field(default=None, index=True, max_length=64)
    batch_request_id: Optional[str] = Field(default=None, max_length=128)
    supplier_id: Optional[int] = Field(default=None, index=True)

    create_datetime: Optional[int] = Field(default=None)
    last_update_date: Optional[int] = Field(default=None)

    gender: Optional[str] = Field(default=None, max_length=64)
    category_name: Optional[str] = Field(default=None, max_length=128)
    product_main_id: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2000)
    stock_unit_type: Optional[str] = Field(default=None, max_length=32)

    title: Optional[str] = Field(default=None, max_length=255)
    barcode: Optional[str] = Field(default=None, index=True, max_length=64)
    stock_code: Optional[str] = Field(default=None, index=True, max_length=120)
    brand: Optional[str] = Field(default=None, max_length=120)
    quantity: Optional[float] = Field(default=None)
    approved: Optional[bool] = Field(default=None)
    archived: Optional[bool] = Field(default=None)
    on_sale: Optional[bool] = Field(default=None)

    list_price: Optional[float] = Field(default=None)
    sale_price: Optional[float] = Field(default=None)
    vat_rate: Optional[float] = Field(default=None)
    dimensional_weight: Optional[float] = Field(default=None)
    location_based_delivery: Optional[str] = Field(default=None, max_length=32)
    lot_number: Optional[str] = Field(default=None, max_length=64)
    special_consumption_tax: Optional[float] = Field(default=None)

    delivery_option: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    images: Optional[list] = Field(sa_column=Column(JSON), default=None)
    attributes: Optional[list] = Field(sa_column=Column(JSON), default=None)

    platform_listing_id: Optional[str] = Field(default=None, max_length=64)
    stock_id: Optional[str] = Field(default=None, max_length=64)
    has_active_campaign: Optional[bool] = Field(default=None)
    locked: Optional[bool] = Field(default=None)
    product_content_id: Optional[int] = Field(default=None)
    pim_category_id: Optional[int] = Field(default=None)
    brand_id: Optional[int] = Field(default=None)
    version: Optional[int] = Field(default=None)
    color: Optional[str] = Field(default=None, max_length=64)
    size: Optional[str] = Field(default=None, max_length=64)
    locked_by_unsupplied_reason: Optional[bool] = Field(default=None)
    product_url: Optional[str] = Field(default=None, max_length=500)

    stock_item_id: Optional[int] = Field(default=None, index=True, foreign_key="stock_item.pk")
    raw: Optional[dict] = Field(sa_column=Column(JSON), default=None)


class ListingProductStockSnapshot(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "stock_item_snapshot"
    __table_args__ = (
        Index("ix_stock_item_snapshot_listing", "listing_id"),
        Index("ix_stock_item_snapshot_listing_item_created", "listing_id", "stock_item_id", "created_at"),
    )

    pk: Optional[int] = Field(default=None, primary_key=True)

    status: str = Field(default="append", index=True, max_length=16)
    listing_id: int = Field(index=True, foreign_key="trendyol_listing_product.pk")
    stock_item_id: int = Field(index=True, foreign_key="stock_item.pk")
    qty: float = Field(default=1)


class ListingProductCostSnapshot(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "cost_item_snapshot"
    __table_args__ = (
        Index("ix_cost_item_snapshot_listing", "listing_id"),
        Index("ix_cost_item_snapshot_listing_key_created", "listing_id", "cost_key", "created_at"),
    )

    pk: Optional[int] = Field(default=None, primary_key=True)

    status: str = Field(default="append", index=True, max_length=16)
    cost_item_id: Optional[int] = Field(default=None, index=True, foreign_key="cost_item.pk")
    cargo_provider_id: Optional[int] = Field(default=None, index=True, foreign_key="logistics_cargo_provider.pk")
    listing_id: int = Field(index=True, foreign_key="trendyol_listing_product.pk")
    cost_key: str = Field(index=True, max_length=128)
    source_type: Optional[str] = Field(default=None, max_length=64)
    source_config: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    resolved_amount: Optional[float] = Field(default=None)
    resolved_net_amount: Optional[float] = Field(default=None)
    resolved_vat_amount: Optional[float] = Field(default=None)
    currency: Optional[str] = Field(default="TRY", max_length=16)
    note: Optional[str] = Field(default=None, max_length=255)
    resolution_meta: Optional[dict] = Field(sa_column=Column(JSON), default=None)


class ListingProductHistory(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "trendyol_listing_product_history"
    __table_args__ = (
        Index("ix_trendyol_listing_product_history_key", "api_account_id", "product_id"),
        Index("ix_trendyol_listing_product_history_created", "created_at"),
    )

    pk: Optional[int] = Field(default=None, primary_key=True)

    api_account_id: int = Field(index=True, foreign_key="apiaccount.pk")
    product_id: str = Field(index=True, max_length=64)

    changes: Optional[dict] = Field(sa_column=Column(JSON), default=None)
