from __future__ import annotations

from sqlmodel import Session, select

from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from Marketplaces.models.models import Marketplace
from settings import DB_NAME


def list_marketplaces(*, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            rows = session.exec(select(Marketplace)).all() or []
        return Result.ok("Pazaryerleri getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
