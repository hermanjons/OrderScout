from datetime import datetime
from typing import List, Optional

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Index

from Core.db.models import SourceIdentityMixin
from Finance.models.trendyol.models import Brand, Company
from Stock.constants.constants import (
    StockItemType, StockTxDirection, StockTxReason, StockReferenceType
)


class StockItem(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "stock_item"

    pk: Optional[int] = Field(default=None, primary_key=True)

    sku: str = Field(index=True, max_length=64)
    name: str = Field(max_length=255)
    barcode: Optional[str] = Field(default=None, index=True, max_length=64)

    item_type: StockItemType = Field(default=StockItemType.physical)
    unit: str = Field(default="adet", max_length=32)
    brand_id: Optional[int] = Field(default=None, index=True, foreign_key="brand.pk")
    brand: Optional[str] = Field(default=None, max_length=80)
    category: Optional[str] = Field(default=None, max_length=120)
    sub_category: Optional[str] = Field(default=None, max_length=120)
    model_code: Optional[str] = Field(default=None, max_length=120)
    manufacturer: Optional[str] = Field(default=None, max_length=120)
    gtip_code: Optional[str] = Field(default=None, max_length=64)
    custom_label: Optional[str] = Field(default=None, max_length=120)
    location_code: Optional[str] = Field(default=None, max_length=80)

    image_path: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=1500)
    note: Optional[str] = Field(default=None, max_length=500)

    is_active: bool = Field(default=True)
    min_stock: Optional[float] = Field(default=None)
    max_stock: Optional[float] = Field(default=None)
    safety_stock: Optional[float] = Field(default=None)
    reorder_point: Optional[float] = Field(default=None)
    reorder_qty: Optional[float] = Field(default=None)
    lead_time_days: Optional[int] = Field(default=None)
    shelf_life_days: Optional[int] = Field(default=None)
    serial_tracking: bool = Field(default=False)
    lot_tracking: bool = Field(default=False)
    allow_negative_stock: bool = Field(default=False)

    vat_rate: Optional[float] = Field(default=None)

    weight_kg: Optional[float] = Field(default=None)
    length_cm: Optional[float] = Field(default=None)
    width_cm: Optional[float] = Field(default=None)
    height_cm: Optional[float] = Field(default=None)

    txs: List["StockTx"] = Relationship(back_populates="item")
    brand_ref: Optional["Brand"] = Relationship()

    __table_args__ = (
        Index("ix_stock_item_sku_unique", "sku", unique=True),
    )


class Warehouse(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "warehouse"

    pk: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=128)
    code: Optional[str] = Field(default=None, index=True, max_length=80)
    manager_name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=120)
    country: Optional[str] = Field(default=None, max_length=120)
    capacity_m3: Optional[float] = Field(default=None)
    layout_json: Optional[str] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)

    txs: List["StockTx"] = Relationship(back_populates="warehouse")


class StockTx(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "stock_tx"

    pk: Optional[int] = Field(default=None, primary_key=True)

    item_id: int = Field(index=True, foreign_key="stock_item.pk")
    warehouse_id: int = Field(index=True, foreign_key="warehouse.pk")

    direction: StockTxDirection = Field(index=True)
    reason: StockTxReason = Field(index=True)

    qty: float = Field(gt=0)
    occurred_at: datetime = Field(default_factory=datetime.now, index=True)

    unit_cost: Optional[float] = Field(default=None)
    unit_cost_input_mode: Optional[str] = Field(default=None, max_length=32)
    unit_cost_vat_rate: Optional[float] = Field(default=None)
    currency: Optional[str] = Field(default="TRY", max_length=8)
    valuation_method: Optional[str] = Field(default="moving_avg", max_length=32)
    valuation_calc_version: Optional[int] = Field(default=1)
    valuation_cost_source: Optional[str] = Field(default=None, max_length=64)
    valuation_qty_before: Optional[float] = Field(default=None)
    valuation_qty_after: Optional[float] = Field(default=None)
    valuation_stock_value_before: Optional[float] = Field(default=None)
    valuation_stock_value_after: Optional[float] = Field(default=None)
    valuation_avg_before: Optional[float] = Field(default=None)
    valuation_avg_after: Optional[float] = Field(default=None)

    reference_type: StockReferenceType = Field(default=StockReferenceType.none, index=True)
    reference_id: Optional[str] = Field(default=None, index=True, max_length=128)
    order_header_id: Optional[int] = Field(default=None, index=True, foreign_key="trendyol_order_header.pk")
    order_ref: Optional[str] = Field(default=None, index=True, max_length=128)
    listing_id: Optional[str] = Field(default=None, index=True, max_length=128)
    map_qty: Optional[float] = Field(default=None)

    note: Optional[str] = Field(default=None, max_length=500)
    created_by: Optional[str] = Field(default=None, max_length=128)
    company_id: Optional[int] = Field(default=None, index=True, foreign_key="company.pk")
    counterparty: Optional[str] = Field(default=None, max_length=160)
    attachments: Optional[str] = Field(default=None, max_length=2000)

    item: Optional["StockItem"] = Relationship(back_populates="txs")
    warehouse: Optional["Warehouse"] = Relationship(back_populates="txs")
    company_ref: Optional["Company"] = Relationship()

    __table_args__ = (
        Index(
            "ix_stock_tx_ref_unique",
            "reference_type",
            "reference_id",
            "item_id",
            unique=True,
        ),
        Index(
            "ix_stock_tx_item_wh_time",
            "item_id",
            "warehouse_id",
            "occurred_at",
            "created_at",
        ),
        Index(
            "ix_stock_tx_item_time",
            "item_id",
            "occurred_at",
            "created_at",
            "pk",
        ),
        Index(
            "ix_stock_tx_warehouse_time",
            "warehouse_id",
            "occurred_at",
            "created_at",
            "pk",
        ),
        Index(
            "ix_stock_tx_company_time",
            "company_id",
            "occurred_at",
            "created_at",
            "pk",
        ),
    )
