from sqlmodel import SQLModel, Field
from typing import Optional


class CompAccount(SQLModel, table=True):
    seller_id: int = Field(primary_key=True)
    api_key: str
    api_secret: str
    comp_name: str
