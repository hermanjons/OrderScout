"""Incremental page traversal without pruning an incomplete marketplace scan."""
from __future__ import annotations

from Feedback.processors.pipeline import Result


async def refresh_listings(accounts: list, *, db_name: str, cursor: dict) -> Result:
    from Listing.processors.trendyol.pipeline import fetch_listings_all
    from Listing.processors.pipeline import save_listings_to_db

    state = dict(cursor)
    changed = False
    more = False
    for account in accounts:
        key = str(account.pk)
        previous = dict(state.get(key) or {})
        approved = bool(previous.get("approved", True))
        page = max(0, int(previous.get("page") or 0))
        token = previous.get("token") or None
        extra = dict(account.extra_config or {})
        row = [account.pk, account.api_key, account.api_secret, str(account.account_id),
               extra.get("acceptLanguage", ""), extra.get("environment", "production"),
               extra.get("credential_reference") or extra.get("credential_ref") or ""]
        fetched = await fetch_listings_all([row], page=page, size=50, approved=approved,
                                           next_page_token=token, fetch_all_pages=False)
        if not fetched.success:
            return fetched
        payload = dict(fetched.data or {})
        saved = save_listings_to_db(payload.get("items") or [], db_name=db_name,
                                    sync_api_account_ids=[account.pk], prune_missing=False)
        if not saved.success:
            return saved
        changed = changed or bool((saved.data or {}).get("changed"))
        per_account = payload.get("per_account") or []
        meta = dict((per_account[0] if per_account else {}).get("meta") or {})
        next_token = str(meta.get("nextPageToken") or "").strip()
        total_pages = int(meta.get("totalPages") or 0)
        raw_items = meta.get("items") or []
        has_next = bool(next_token) or (page + 1 < total_pages if total_pages
                                      else len(raw_items) >= 50)
        if next_token and next_token == token:
            return Result.fail("Listeleme sayfa imleci ilerlemedi.", close_dialog=False)
        if has_next:
            state[key] = {"approved": approved, "page": page + 1, "token": next_token}
        else:
            # Traverse approved and pending content separately. A subsequent
            # cycle starts a fresh scan, so stock/price edits are discovered.
            state[key] = {"approved": not approved, "page": 0, "token": ""}
        more = more or has_next or approved
    return Result.ok("Listelemeler güncellendi.", close_dialog=False,
                     data={"changed": changed, "cursor": state, "has_more": more})
