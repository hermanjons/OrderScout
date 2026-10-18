from __future__ import annotations

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Logistics.models.models import LogisticsCargoProvider, LogisticsCargoTariff
from settings import DB_NAME


def list_providers(*, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = session.exec(select(LogisticsCargoProvider)).all() or []
        return Result.ok("Kargo firmalari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def list_tariffs(*, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = session.exec(select(LogisticsCargoTariff)).all() or []
        return Result.ok("Kargo tarifeleri getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
