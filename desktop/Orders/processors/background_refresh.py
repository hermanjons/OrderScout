"""Headless automatic Orders/returns refresh using shared fetch/save atoms."""
from __future__ import annotations

from datetime import datetime, timezone

from Feedback.processors.pipeline import Result


def sync_saved_order_stock(items: list[dict], *, db_name: str) -> Result:
    """Run the existing idempotent stock atom in the same database scope."""
    from Stock.processors.pipeline import auto_deduct_order_items, database_scope

    with database_scope(db_name):
        return auto_deduct_order_items(items, created_by="orders:auto")


async def verify_open_orders(account, order_numbers: list[str]) -> Result:
    from Orders.api.trendyol.orders_api import TrendyolApi
    from Orders.processors.trendyol.pipeline import normalize_order_data

    api = TrendyolApi.from_account(account)
    orders: list[dict] = []
    items: list[dict] = []
    for number in order_numbers:
        result = await api.get_order_by_number(number)
        if not result.success:
            return Result.fail("Açık sipariş doğrulaması tamamlanamadı.", close_dialog=False)
        content = (result.data or {}).get("content") or []
        if not content:
            return Result.fail("Açık sipariş için güncel kaynak kaydı bulunamadı.", close_dialog=False)
        for raw in content:
            order_rows, item_rows = normalize_order_data(raw, int(account.pk))
            if not order_rows:
                return Result.fail("Açık sipariş kaynağı normalleştirilemedi.", close_dialog=False)
            orders.extend(order_rows)
            items.extend(item_rows)
    return Result.ok("Açık siparişler doğrulandı.", close_dialog=False,
                     data={"order_data_list": orders, "order_item_list": items})


async def refresh_orders(accounts: list, *, db_name: str, cursor: dict) -> Result:
    from Orders.constants.domain_constants import ORDER_FINAL_STATUS_CODES
    from Orders.constants.trendyol.constants import TRENDYOL_API_STATUS_LIST
    from Orders.processors.trendyol.pipeline import (
        canonical_order_status_code, fetch_orders_all, get_latest_orders,
        get_latest_return_claims, save_orders_to_db, save_return_claims_to_db,
    )
    from Orders.views.actions import _fetch_returns_from_active_companies_async, RETURN_ACTIVE_STATUS_CODES

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    day = 86_400_000
    state = dict(cursor)
    counts: dict[str, int] = {}
    changed = False
    more = False
    for account in accounts:
        account_id = int(account.pk)
        key = str(account_id)
        previous = dict(state.get(key) or {})
        # A bounded window catches up to the present without an unbounded fetch
        # on startup. Keep overlap so late events at a boundary are not missed.
        start = int(previous.get("until_ms") or now_ms - 30 * day)
        end = min(now_ms, start + day)
        extra = dict(account.extra_config or {})
        rows = [[account_id, account.api_key, account.api_secret,
                 str(account.account_id), account.last_used_at, extra]]
        fetched = await fetch_orders_all(list(TRENDYOL_API_STATUS_LIST), end,
                                         max(0, start - 600_000), rows)
        if not fetched.success or (fetched.data or {}).get("sync_diagnostics", {}).get("source_rows_complete") is False:
            return Result.fail("Sipariş kaynağı tamamlanamadı.", close_dialog=False)
        saved = save_orders_to_db(fetched, db_name=db_name)
        if not saved.success:
            return saved
        stock = sync_saved_order_stock((fetched.data or {}).get("order_item_list") or [], db_name=db_name)
        if not stock.success or int((stock.data or {}).get("tx_failed") or 0):
            return Result.fail("Sipariş stok hareketleri tamamlanamadı.", close_dialog=False)
        changed = changed or bool((saved.data or {}).get("changed"))
        for name, value in ((saved.data or {}).get("counts") or {}).items():
            counts[name] = counts.get(name, 0) + int(value or 0)

        returns = await _fetch_returns_from_active_companies_async(
            [account], start_ms=max(0, start - 600_000), end_ms=end, size=50,
        )
        if not returns.success or (returns.data or {}).get("errors"):
            return Result.fail("İade kaynağı tamamlanamadı.", close_dialog=False)
        claims_saved = save_return_claims_to_db(returns, db_name=db_name)
        if not claims_saved.success:
            return claims_saved
        changed = changed or bool((claims_saved.data or {}).get("changed"))
        for name, value in ((claims_saved.data or {}).get("counts") or {}).items():
            counts[name] = counts.get(name, 0) + int(value or 0)

        open_claims = get_latest_return_claims(
            api_account_ids=[account_id], claim_statuses=list(RETURN_ACTIVE_STATUS_CODES), db_name=db_name,
            summary_only=True,
        )
        if not open_claims.success:
            return open_claims
        claim_ids = sorted({str(claim.claimId) for claim in (open_claims.data or {}).get("claims", [])})
        claim_offset = int(previous.get("claim_offset") or 0)
        if claim_offset >= len(claim_ids):
            claim_offset = 0
        claim_batch = claim_ids[claim_offset:claim_offset + 20]
        if claim_batch:
            verified_claims = await _fetch_returns_from_active_companies_async(
                [account], start_ms=0, end_ms=now_ms, size=50, claim_ids=claim_batch,
            )
            if not verified_claims.success or (verified_claims.data or {}).get("errors"):
                return Result.fail("Açık iadeler doğrulanamadı.", close_dialog=False)
            found_ids = {str(row.get("claimId")) for row in
                         (verified_claims.data or {}).get("return_claim_list", [])}
            if not set(claim_batch).issubset(found_ids):
                return Result.fail("Açık iadelerin kaynak doğrulaması eksik kaldı.", close_dialog=False)
            verified_claims_saved = save_return_claims_to_db(verified_claims, db_name=db_name)
            if not verified_claims_saved.success:
                return verified_claims_saved
            changed = changed or bool((verified_claims_saved.data or {}).get("changed"))
            for name, value in ((verified_claims_saved.data or {}).get("counts") or {}).items():
                counts[name] = counts.get(name, 0) + int(value or 0)

        # Verify old open orders too: their creation date can predate the pull
        # window. Rotate a bounded slice instead of repeatedly querying page 0.
        local = get_latest_orders(api_account_ids=[account_id], db_name=db_name, summary_only=True)
        if not local.success:
            return local
        open_orders = sorted({str(row.orderNumber) for row in (local.data or {}).get("orders", [])
                              if canonical_order_status_code(getattr(row, "shipmentPackageStatus", None)
                                                             or getattr(row, "status", "")) not in ORDER_FINAL_STATUS_CODES})
        offset = int(previous.get("open_offset") or 0)
        if offset >= len(open_orders):
            offset = 0
        batch = open_orders[offset:offset + 20]
        if batch:
            verified = await verify_open_orders(account, batch)
            if not verified.success:
                return verified
            verified_saved = save_orders_to_db(verified, db_name=db_name)
            if not verified_saved.success:
                return verified_saved
            stock = sync_saved_order_stock((verified.data or {}).get("order_item_list") or [], db_name=db_name)
            if not stock.success or int((stock.data or {}).get("tx_failed") or 0):
                return Result.fail("Sipariş stok hareketleri tamamlanamadı.", close_dialog=False)
            changed = changed or bool((verified_saved.data or {}).get("changed"))
        state[key] = {"until_ms": end, "open_offset": offset + len(batch),
                      "claim_offset": claim_offset + len(claim_batch)}
        more = more or end < now_ms
    return Result.ok("Sipariş ve iadeler güncellendi.", close_dialog=False,
                     data={"changed": changed, "counts": counts, "cursor": state, "has_more": more})
