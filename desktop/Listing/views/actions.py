# Listing/views/actions.py
from __future__ import annotations

from typing import Optional, Dict, Any, Callable

from Feedback.processors.pipeline import Result
from Account.processors.pipeline import get_company_by_id, get_all_companies
from Listing.processors.trendyol.pipeline import (
    fetch_listings_all,
    update_price_and_inventory_for_account,
    update_approved_content_for_account,
    check_batch_request_for_account,
)
from Listing.processors.pipeline import (
    get_listings_from_db,
    get_listing_brands_from_db,
    set_listing_stock_items,
    set_listing_cost_items,
    sync_listing_cost_snapshots_for_item,
    update_listing_price_inventory_cache,
)
from Finance.views.actions import load_finance_cost_items
from Logistics.views.actions import load_logistics_cargo_providers, load_logistics_cargo_tariffs


def action_get_all_companies() -> Result:
    return get_all_companies()


def action_get_company_credentials(company_pks: list[int]) -> Result:
    return get_company_by_id(company_pks)


async def action_fetch_listings(
    comp_api_account_list: list,
    *,
    page: int = 0,
    size: int = 50,
    approved: Optional[bool] = None,
    barcode: Optional[str] = None,
    stock_code: Optional[str] = None,
    product_main_id: Optional[str] = None,
    brand_ids: Optional[Any] = None,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
    date_query_type: Optional[str] = None,
    status: Optional[str] = None,
    next_page_token: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    fetch_all_pages: bool = False,
    max_pages: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Result:
    return await fetch_listings_all(
        comp_api_account_list,
        page=page,
        size=size,
        approved=approved,
        barcode=barcode,
        stock_code=stock_code,
        product_main_id=product_main_id,
        brand_ids=brand_ids,
        start_date=start_date,
        end_date=end_date,
        date_query_type=date_query_type,
        status=status,
        next_page_token=next_page_token,
        extra_params=extra_params,
        fetch_all_pages=fetch_all_pages,
        max_pages=max_pages,
        progress_callback=progress_callback,
    )


async def action_update_price_inventory_for_account(
    *,
    api_key: str,
    api_secret: str,
    seller_id: str,
    items: list[dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    barcode: Optional[str] = None,
    wait_result: bool = True,
    poll_interval: float = 1.5,
    max_wait: float = 60.0,
    environment: str = "production",
    accept_language: Optional[str] = None,
    credential_reference: Optional[str] = None,
) -> Result:
    return await update_price_and_inventory_for_account(
        api_key=api_key,
        api_secret=api_secret,
        seller_id=seller_id,
        items=items,
        progress_callback=progress_callback,
        barcode=barcode,
        wait_result=wait_result,
        poll_interval=poll_interval,
        max_wait=max_wait,
        environment=environment,
        accept_language=accept_language,
        credential_reference=credential_reference,
    )


async def action_update_approved_content_for_account(
    *,
    api_key: str,
    api_secret: str,
    seller_id: str,
    items: list[dict],
    progress_callback: Optional[Callable[[int, int], None]] = None,
    content_id: Optional[int] = None,
    wait_result: bool = True,
    poll_interval: float = 1.5,
    max_wait: float = 60.0,
    environment: str = "production",
    accept_language: Optional[str] = None,
    credential_reference: Optional[str] = None,
) -> Result:
    return await update_approved_content_for_account(
        api_key=api_key,
        api_secret=api_secret,
        seller_id=seller_id,
        items=items,
        progress_callback=progress_callback,
        content_id=content_id,
        wait_result=wait_result,
        poll_interval=poll_interval,
        max_wait=max_wait,
        environment=environment,
        accept_language=accept_language,
        credential_reference=credential_reference,
    )


async def action_check_batch_request_for_account(
    *,
    api_key: str,
    api_secret: str,
    seller_id: str,
    batch_request_id: str,
    barcode: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    environment: str = "production",
    accept_language: Optional[str] = None,
    credential_reference: Optional[str] = None,
) -> Result:
    return await check_batch_request_for_account(
        api_key=api_key,
        api_secret=api_secret,
        seller_id=seller_id,
        batch_request_id=batch_request_id,
        barcode=barcode,
        progress_callback=progress_callback,
        environment=environment,
        accept_language=accept_language,
        credential_reference=credential_reference,
    )


def action_get_listings_from_db(**kwargs) -> Result:
    return get_listings_from_db(**kwargs)


def action_get_listing_brands_from_db(**kwargs) -> Result:
    return get_listing_brands_from_db(**kwargs)


def action_set_listing_stock_items(
    *,
    api_account_id: int,
    product_id: str,
    stock_items: list[dict],
    db_name: str = "",
) -> Result:
    kwargs: Dict[str, Any] = {}
    if db_name:
        kwargs["db_name"] = db_name
    return set_listing_stock_items(
        api_account_id=api_account_id,
        product_id=product_id,
        stock_items=stock_items,
        **kwargs,
    )


def action_set_listing_cost_items(
    *,
    api_account_id: int,
    product_id: str,
    cost_items: list[dict],
    db_name: str = "",
) -> Result:
    kwargs: Dict[str, Any] = {}
    if db_name:
        kwargs["db_name"] = db_name
    return set_listing_cost_items(
        api_account_id=api_account_id,
        product_id=product_id,
        cost_items=cost_items,
        **kwargs,
    )


def action_load_finance_cost_items(**kwargs) -> Result:
    return load_finance_cost_items(**kwargs)


def action_load_logistics_cargo_tariffs(**kwargs) -> Result:
    return load_logistics_cargo_tariffs(**kwargs)


def action_load_logistics_cargo_providers(**kwargs) -> Result:
    return load_logistics_cargo_providers(**kwargs)


def action_load_finance_cargo_tariffs(**kwargs) -> Result:
    return action_load_logistics_cargo_tariffs(**kwargs)


def action_update_listing_price_inventory_cache(
    *,
    api_account_id: int,
    product_id: str,
    quantity: Optional[float],
    list_price: Optional[float],
    sale_price: Optional[float],
    db_name: str = "",
) -> Result:
    kwargs: Dict[str, Any] = {}
    if db_name:
        kwargs["db_name"] = db_name
    return update_listing_price_inventory_cache(
        api_account_id=api_account_id,
        product_id=product_id,
        quantity=quantity,
        list_price=list_price,
        sale_price=sale_price,
        **kwargs,
    )


def action_sync_listing_cost_snapshots_for_item(
    *,
    item: dict,
    estimation: dict | None,
    db_name: str = "",
) -> Result:
    kwargs: Dict[str, Any] = {}
    if db_name:
        kwargs["db_name"] = db_name
    return sync_listing_cost_snapshots_for_item(item=item, estimation=estimation, **kwargs)
