from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Finance.models.trendyol.models import (
    Brand,
    Company,
    FinanceCostItem,
    FinanceInvoiceDocument,
    FinanceManualTransaction,
    FinanceTransaction,
)
from settings import DB_NAME


_MODELS = {
    "brand": Brand,
    "company": Company,
    "cost_item": FinanceCostItem,
    "manual_transaction": FinanceManualTransaction,
    "invoice_document": FinanceInvoiceDocument,
    "transaction": FinanceTransaction,
}


def list_records(kind: str, *, db_name: str = DB_NAME) -> Result:
    try:
        model = _MODELS.get(str(kind or "").strip())
        if model is None:
            return Result.fail("Finance repository record turu desteklenmiyor.", close_dialog=False)
        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = session.exec(select(model)).all() or []
        return Result.ok("Finance kayitlari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
