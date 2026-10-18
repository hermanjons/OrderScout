# Stock/views/actions.py
from __future__ import annotations

from typing import Optional, Dict, Any
from datetime import datetime

from Feedback.processors.pipeline import Result
from Stock.processors.pipeline import (
    create_item,
    generate_unique_barcode,
    update_item,
    delete_item,
    list_items,
    create_warehouse,
    update_warehouse,
    delete_warehouse,
    list_warehouses,
    get_on_hand,
    manual_in,
    manual_out,
    update_tx_edit_fields,
    update_tx_attachments,
    list_txs,
    list_txs_by_ids,
    get_tx_cost_detail,
    list_txs_filtered,
    export_txs_excel,
    adjust_item_stock_to,
    auto_deduct_order_items,
    list_item_balances,
    create_sub_group,
    update_sub_group,
    delete_sub_group,
    list_sub_groups,
    list_upper_groups,
    list_upper_group_records,
    create_upper_group,
    update_upper_group,
    delete_upper_group,
)
from Finance.views.actions import (
    action_create_brand as finance_action_create_brand,
    action_update_brand as finance_action_update_brand,
    action_delete_brand as finance_action_delete_brand,
    action_list_brands as finance_action_list_brands,
    action_create_company as finance_action_create_company,
    action_update_company as finance_action_update_company,
    action_delete_company as finance_action_delete_company,
    action_list_companies as finance_action_list_companies,
)
from Stock.constants.constants import StockReferenceType

def action_create_item(
    sku: str,
    name: str,
    unit: str = "adet",
    item_type: str = "physical",
    barcode: Optional[str] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    model_code: Optional[str] = None,
    manufacturer: Optional[str] = None,
    gtip_code: Optional[str] = None,
    custom_label: Optional[str] = None,
    location_code: Optional[str] = None,
    image_path: Optional[str] = None,
    description: Optional[str] = None,
    note: Optional[str] = None,
    is_active: bool = True,
    min_stock: Optional[float] = None,
    max_stock: Optional[float] = None,
    safety_stock: Optional[float] = None,
    reorder_point: Optional[float] = None,
    reorder_qty: Optional[float] = None,
    lead_time_days: Optional[int] = None,
    shelf_life_days: Optional[int] = None,
    serial_tracking: bool = False,
    lot_tracking: bool = False,
    allow_negative_stock: bool = False,
    vat_rate: Optional[float] = None,
    weight_kg: Optional[float] = None,
    length_cm: Optional[float] = None,
    width_cm: Optional[float] = None,
    height_cm: Optional[float] = None,
) -> Result:
    return create_item(
        sku=sku, name=name, unit=unit, item_type=item_type,
        barcode=barcode, brand=brand, category=category,
        sub_category=sub_category, model_code=model_code, manufacturer=manufacturer,
        gtip_code=gtip_code, custom_label=custom_label, location_code=location_code,
        image_path=image_path, description=description, note=note,
        is_active=is_active, min_stock=min_stock,
        max_stock=max_stock, safety_stock=safety_stock, reorder_point=reorder_point,
        reorder_qty=reorder_qty, lead_time_days=lead_time_days, shelf_life_days=shelf_life_days,
        serial_tracking=serial_tracking, lot_tracking=lot_tracking, allow_negative_stock=allow_negative_stock,
        vat_rate=vat_rate,
        weight_kg=weight_kg, length_cm=length_cm, width_cm=width_cm, height_cm=height_cm,
    )


def action_generate_unique_barcode(prefix: str = "869") -> Result:
    return generate_unique_barcode(prefix=prefix)

def action_update_item(pk: int, update_data: Dict[str, Any]) -> Result:
    return update_item(pk=pk, update_data=update_data)

def action_delete_item(pk: int, cascade: bool = False) -> Result:
    return delete_item(pk=pk, cascade=cascade)

def action_list_items(only_active: bool = True, *, db_name: str | None = None) -> Result:
    return list_items(only_active=only_active, db_name=db_name)

def action_create_warehouse(
    name: str,
    code: Optional[str] = None,
    manager_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    capacity_m3: Optional[float] = None,
    layout_json: Optional[str] = None,
    note: Optional[str] = None,
) -> Result:
    return create_warehouse(
        name=name,
        code=code,
        manager_name=manager_name,
        phone=phone,
        email=email,
        address=address,
        city=city,
        country=country,
        capacity_m3=capacity_m3,
        layout_json=layout_json,
        note=note,
    )

def action_update_warehouse(pk: int, update_data: Dict[str, Any]) -> Result:
    return update_warehouse(pk=pk, update_data=update_data)

def action_delete_warehouse(pk: int) -> Result:
    return delete_warehouse(pk=pk)

def action_list_warehouses(only_active: bool = True) -> Result:
    return list_warehouses(only_active=only_active)

def action_get_on_hand(item_id: int, warehouse_id: Optional[int] = None) -> Result:
    return get_on_hand(item_id=item_id, warehouse_id=warehouse_id)

def action_manual_in(
    item_id: int,
    warehouse_id: int,
    qty: float,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
    counterparty: Optional[str] = None,
    attachments: Optional[str] = None,
    reason: Optional[str] = None,
) -> Result:
    return manual_in(
        item_id=item_id,
        warehouse_id=warehouse_id,
        qty=qty,
        note=note,
        created_by=created_by,
        occurred_at=occurred_at,
        unit_cost=unit_cost,
        unit_cost_input_mode=unit_cost_input_mode,
        unit_cost_vat_rate=unit_cost_vat_rate,
        currency=currency,
        counterparty=counterparty,
        attachments=attachments,
        reason=reason,
    )

def action_manual_out(
    item_id: int,
    warehouse_id: int,
    qty: float,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    allow_negative: bool = False,
    occurred_at: Optional[datetime] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
    counterparty: Optional[str] = None,
    attachments: Optional[str] = None,
    reason: Optional[str] = None,
    reference_type: StockReferenceType = StockReferenceType.none,
    reference_id: Optional[str] = None,
    order_ref: Optional[str] = None,
    listing_id: Optional[str] = None,
    map_qty: Optional[float] = None,
) -> Result:
    return manual_out(
        item_id=item_id,
        warehouse_id=warehouse_id,
        qty=qty,
        note=note,
        created_by=created_by,
        allow_negative=allow_negative,
        occurred_at=occurred_at,
        unit_cost=unit_cost,
        unit_cost_input_mode=unit_cost_input_mode,
        unit_cost_vat_rate=unit_cost_vat_rate,
        currency=currency,
        counterparty=counterparty,
        attachments=attachments,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        order_ref=order_ref,
        listing_id=listing_id,
        map_qty=map_qty,
    )

def action_update_tx_attachments(*, tx_id: int, attachments: Optional[str] = None) -> Result:
    return update_tx_attachments(tx_id=tx_id, attachments=attachments)


def action_update_tx_edit_fields(
    *,
    tx_id: int,
    attachments: Optional[str] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
) -> Result:
    return update_tx_edit_fields(
        tx_id=tx_id,
        attachments=attachments,
        unit_cost_input_mode=unit_cost_input_mode,
        unit_cost_vat_rate=unit_cost_vat_rate,
    )

def action_list_txs(item_id: Optional[int] = None, warehouse_id: Optional[int] = None, limit: int = 200) -> Result:
    return list_txs(item_id=item_id, warehouse_id=warehouse_id, limit=limit)

def action_list_txs_by_ids(tx_ids: list[int]) -> Result:
    return list_txs_by_ids(tx_ids=tx_ids)


def action_get_tx_cost_detail(*, tx_id: int) -> Result:
    return get_tx_cost_detail(tx_id=tx_id)

def action_list_txs_filtered(
    *,
    item_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    direction: Optional[str] = None,
    reason: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    limit: int = 500,
) -> Result:
    return list_txs_filtered(
        item_id=item_id,
        warehouse_id=warehouse_id,
        direction=direction,
        reason=reason,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
    )

def action_export_txs_excel(*, txs: list, output_path: str) -> Result:
    return export_txs_excel(txs=txs, output_path=output_path)

def action_list_item_balances(
    *,
    warehouse_id: Optional[int] = None,
    only_active: bool = True,
    db_name: str | None = None,
) -> Result:
    return list_item_balances(
        warehouse_id=warehouse_id,
        only_active=only_active,
        db_name=db_name,
    )


def action_inventory_overview(*, db_name=None, limit=12) -> Result:
    from Stock.processors.inventory_summary import read_inventory_overview
    return read_inventory_overview(limit=limit, **({"db_name": db_name} if db_name else {}))


def action_low_stock_summary(*, db_name=None, limit=10) -> Result:
    from Stock.processors.inventory_summary import read_low_stock_summary
    return read_low_stock_summary(limit=limit, **({"db_name": db_name} if db_name else {}))


def action_adjust_item_stock_to(
    *,
    item_id: int,
    target_qty: float,
    warehouse_id: Optional[int] = None,
    note: Optional[str] = None,
    created_by: Optional[str] = None,
    allow_negative: Optional[bool] = None,
    unit_cost: Optional[float] = None,
    unit_cost_input_mode: Optional[str] = None,
    unit_cost_vat_rate: Optional[float] = None,
    currency: str = "TRY",
) -> Result:
    return adjust_item_stock_to(
        item_id=item_id,
        target_qty=target_qty,
        warehouse_id=warehouse_id,
        note=note,
        created_by=created_by,
        allow_negative=allow_negative,
        unit_cost=unit_cost,
        unit_cost_input_mode=unit_cost_input_mode,
        unit_cost_vat_rate=unit_cost_vat_rate,
        currency=currency,
    )


def action_auto_deduct_order_items(order_item_list: list[dict], *, created_by: Optional[str] = "orders:auto") -> Result:
    return auto_deduct_order_items(order_item_list=order_item_list, created_by=created_by)

def action_create_brand(
    name: str,
    code: Optional[str] = None,
    registration_no: Optional[str] = None,
    country: Optional[str] = None,
    website: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    address: Optional[str] = None,
    note: Optional[str] = None,
) -> Result:
    return finance_action_create_brand(
        name=name,
        code=code,
        registration_no=registration_no,
        country=country,
        website=website,
        contact_email=contact_email,
        contact_phone=contact_phone,
        address=address,
        note=note,
    )

def action_update_brand(pk: int, update_data: Dict[str, Any]) -> Result:
    return finance_action_update_brand(pk=pk, update_data=update_data)

def action_delete_brand(pk: int) -> Result:
    return finance_action_delete_brand(pk=pk)

def action_list_brands(only_active: bool = True) -> Result:
    return finance_action_list_brands(only_active=only_active)

def action_create_company(name: str, **kwargs) -> Result:
    return finance_action_create_company(name=name, **kwargs)

def action_update_company(pk: int, update_data: Dict[str, Any]) -> Result:
    return finance_action_update_company(pk=pk, update_data=update_data)

def action_delete_company(pk: int) -> Result:
    return finance_action_delete_company(pk=pk)

def action_list_companies(only_active: bool = True) -> Result:
    return finance_action_list_companies(only_active=only_active)


def action_create_sub_group(category: str, name: str, is_active: bool = True) -> Result:
    return create_sub_group(category=category, name=name, is_active=is_active)


def action_update_sub_group(pk: int, update_data: Dict[str, Any]) -> Result:
    return update_sub_group(pk=pk, update_data=update_data)


def action_delete_sub_group(pk: int) -> Result:
    return delete_sub_group(pk=pk)


def action_list_sub_groups(category: Optional[str] = None, only_active: bool = True) -> Result:
    return list_sub_groups(category=category, only_active=only_active)


def action_list_upper_groups() -> Result:
    return list_upper_groups()


def action_list_upper_group_records() -> Result:
    return list_upper_group_records()


def action_create_upper_group(name: str) -> Result:
    return create_upper_group(name=name)


def action_update_upper_group(pk: int, update_data: Dict[str, Any]) -> Result:
    return update_upper_group(pk=pk, update_data=update_data)


def action_delete_upper_group(pk: int) -> Result:
    return delete_upper_group(pk=pk)
