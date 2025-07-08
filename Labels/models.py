from sqlmodel import SQLModel, Field
from typing import Optional


class LabelData(SQLModel, table=True):
    orderNumber: str = Field(primary_key=True)  # PK yerine UNIQUE için özel çözüm gerekebilir
    paperNumber: str = Field(primary_key=True)
    lastModifiedDate: str = Field(primary_key=True)

    cargoTrackingNumber: Optional[str] = None
    cargoProviderName: Optional[str] = None

    customerName: Optional[str] = None
    customerSurname: Optional[str] = None

    leftFirstProd: Optional[str] = None
    leftFirstQuantity: Optional[int] = None

    leftSecondProd: Optional[str] = None
    leftSecondQuantity: Optional[int] = None

    leftThirdProd: Optional[str] = None
    leftThirdQuantity: Optional[int] = None

    leftFourthProd: Optional[str] = None
    leftFourthQuantity: Optional[int] = None

    rightFirstProd: Optional[str] = None
    rightFirstQuantity: Optional[int] = None

    rightSecondProd: Optional[str] = None
    rightSecondQuantity: Optional[int] = None

    rightThirdProd: Optional[str] = None
    rightThirdQuantity: Optional[int] = None

    rightFourthProd: Optional[str] = None
    rightFourthQuantity: Optional[int] = None

    cargoTrackingNumberNumeric: Optional[str] = None
    fullAddress: Optional[str] = None
    isPrinted: Optional[str] = None
    currentPackageStatus: Optional[str] = None
    status: Optional[str] = None
