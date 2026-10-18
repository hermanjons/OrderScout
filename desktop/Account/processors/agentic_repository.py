from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from Account.models.models import ApiAccount
from Core.utils.model_utils import get_engine
from Feedback.processors.pipeline import Result, map_error_to_message
from settings import DB_NAME


def list_accounts(*, pks: list[int] | None = None, active_only: bool = False, db_name: str = DB_NAME) -> Result:
    try:
        with Session(get_engine(db_name or DB_NAME)) as session:
            stmt = select(ApiAccount)
            if pks:
                stmt = stmt.where(ApiAccount.pk.in_([int(value) for value in pks]))
            if active_only:
                stmt = stmt.where(ApiAccount.is_active.is_(True))
            rows = session.exec(stmt).all() or []
        return Result.ok("API hesaplari getirildi.", close_dialog=False, data={"records": rows})
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)


def get_account(pk: Any, *, db_name: str = DB_NAME) -> Result:
    try:
        account_pk = int(pk)
    except (TypeError, ValueError):
        return Result.fail("API hesap kimligi gecersiz.", close_dialog=False)
    result = list_accounts(pks=[account_pk], db_name=db_name)
    rows = list((result.data or {}).get("records") or []) if result.success else []
    if not rows:
        return Result.fail("API hesabi bulunamadi.", close_dialog=False)
    return Result.ok("API hesabi getirildi.", close_dialog=False, data={"record": rows[0]})
