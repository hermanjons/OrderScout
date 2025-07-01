from sqlmodel import SQLModel, Field
from typing import Optional


class LicenseKey(SQLModel, table=True):
    license_key: str = Field(primary_key=True)
    api_token: str
