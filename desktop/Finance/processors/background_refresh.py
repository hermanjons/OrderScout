"""Bounded finance windows with the same fetch/persistence atom as manual UI."""
from __future__ import annotations

from datetime import datetime, timezone

from Feedback.processors.pipeline import Result


async def refresh_finance(accounts: list, *, db_name: str, cursor: dict) -> Result:
    from Finance.processors.trendyol.pipeline import sync_finance_for_accounts

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    day = 86_400_000
    state = dict(cursor)
    changed = False
    more = False
    for account in accounts:
        key = str(account.pk)
        start = int((state.get(key) or {}).get("until_ms") or now_ms - 30 * day)
        end = min(now_ms, start + day)
        row = [account.pk, account.api_key, account.api_secret, str(account.account_id),
               account.comp_name, dict(account.extra_config or {})]
        result = await sync_finance_for_accounts(
            [row], transaction_date_start=max(0, start - 600_000), transaction_date_end=end,
            page_size=100, max_pages=20, db_name=db_name,
        )
        if not result.success or (result.data or {}).get("errors"):
            return Result.fail("Finans kaynağı tamamlanamadı.", close_dialog=False)
        changed = changed or any(int(v or 0) for v in ((result.data or {}).get("db_counts") or {}).values())
        state[key] = {"until_ms": end}
        more = more or end < now_ms
    return Result.ok("Finans kayıtları güncellendi.", close_dialog=False,
                     data={"changed": changed, "cursor": state, "has_more": more})
