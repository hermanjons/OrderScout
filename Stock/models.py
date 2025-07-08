from sqlmodel import SQLModel, Field
from typing import Optional


class StockData(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_name: str
    product_price: int
    purchase_place: str
    purchase_date: str
    quantity: int
    stock_code: str
    is_have_package_cost: str


class MatchData(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_stock_code: str
    package_quantity: int
    advert_barcode: str
