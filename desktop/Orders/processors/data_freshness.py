"""Read local order timestamp evidence without inventing an API retrieval time."""
from datetime import datetime, timedelta, timezone

from Feedback.processors.pipeline import Result, map_error_to_message
from Orders.processors.trendyol.pipeline import get_latest_orders_filtered
from Orders.constants import TZ_GMT3
from Account.processors.agentic_repository import list_accounts
from settings import DB_NAME


def _iso(value, *, naive_zone=timezone.utc):
    if not isinstance(value, datetime):
        return None
    return (value.replace(tzinfo=naive_zone) if value.tzinfo is None else value).astimezone(TZ_GMT3).isoformat()


def _event_ms(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(TZ_GMT3).isoformat() if value else None


def read_local_order_freshness(*, api_account_ids=None, db_name=DB_NAME):
    """Remote event, local audit and fetch cursor are distinct clock domains."""
    try:
        result = get_latest_orders_filtered(api_account_ids=api_account_ids, db_name=db_name)
        if not result.success:
            return result
        rows = list((result.data or {}).get("orders") or [])
        accounts_result = list_accounts(pks=api_account_ids, db_name=db_name)
        if not accounts_result.success:
            return accounts_result
        latest_order = max((int(row.orderDate or 0) for row in rows), default=0)
        latest_remote = max((int(row.lastModifiedDate or 0) for row in rows), default=0)
        local_created = max((_iso(row.created_at) for row in rows if row.created_at), default=None)
        local_updated = max((_iso(row.updated_at) for row in rows if row.updated_at), default=None)
        cursors = [{"api_account_id": row.pk, "account_id": row.account_id,
                    "recorded_last_used_at": _iso(row.last_used_at, naive_zone=TZ_GMT3),
                    "meaning": "account_fetch_cursor_not_a_successful_retrieval_receipt"}
                   for row in accounts_result.data.get("records") or []]
        return Result.ok("Kayıtlı siparişlerin zaman kanıtları okundu; yeni veri çekilmedi.", close_dialog=False,
            data={"order_count": len(rows), "requested_api_account_ids": api_account_ids or [],
                "latest_order_event_at": _event_ms(latest_order), "latest_order_event_ms": latest_order or None,
                "latest_remote_modified_at": _event_ms(latest_remote), "latest_remote_modified_ms": latest_remote or None,
                "latest_local_record_created_at": local_created, "latest_local_record_updated_at": local_updated,
                "account_fetch_cursors": cursors, "last_successful_retrieval_at": None,
                "successful_retrieval_time_known": False, "network_request_performed": False,
                "simulated_excluded": int((result.data or {}).get("simulated_excluded") or 0),
                "timezone": "UTC+03:00", "evidence_basis": "local_order_rows_and_account_cursors",
                "timestamp_meanings": {
                    "latest_order_event_at": "Marketplace order creation time; not when OrderScout fetched it.",
                    "latest_remote_modified_at": "Marketplace modification time; not local retrieval time.",
                    "latest_local_record_created_at": "Local row creation; can reflect migration/import, not necessarily API fetch.",
                    "latest_local_record_updated_at": "Local row write; not necessarily API fetch.",
                    "last_successful_retrieval_at": "Unknown: no authoritative successful retrieval receipt in this source."}})
    except Exception as error:
        return Result.fail(map_error_to_message(error), error=error, close_dialog=False)
