from sqlmodel import SQLModel, Field
from typing import Optional


class ScrapData(SQLModel, table=True):
    scrap_date: int = Field(primary_key=True)
