# Stock Agentic Parity Matrix

Updated: 2026-07-16

Authoritative inventory: `AI.processors.operation_runtime.operation_coverage_report`.
Any count or capability drift fails `test_domain_goals_contract.py`.

## Runtime coverage

- read: 14
- write: 25
- total: 39

## Capability inventory

### Read

- `stock.action_generate_unique_barcode`
- `stock.action_get_on_hand`
- `stock.action_get_tx_cost_detail`
- `stock.action_list_brands`
- `stock.action_list_companies`
- `stock.action_list_item_balances`
- `stock.action_list_items`
- `stock.action_list_sub_groups`
- `stock.action_list_txs`
- `stock.action_list_txs_by_ids`
- `stock.action_list_txs_filtered`
- `stock.action_list_upper_group_records`
- `stock.action_list_upper_groups`
- `stock.action_list_warehouses`

### Write

- `stock.action_adjust_item_stock_to`
- `stock.action_auto_deduct_order_items`
- `stock.action_create_brand`
- `stock.action_create_company`
- `stock.action_create_item`
- `stock.action_create_sub_group`
- `stock.action_create_upper_group`
- `stock.action_create_warehouse`
- `stock.action_delete_brand`
- `stock.action_delete_company`
- `stock.action_delete_item`
- `stock.action_delete_sub_group`
- `stock.action_delete_upper_group`
- `stock.action_delete_warehouse`
- `stock.action_export_txs_excel`
- `stock.action_manual_in`
- `stock.action_manual_out`
- `stock.action_update_brand`
- `stock.action_update_company`
- `stock.action_update_item`
- `stock.action_update_sub_group`
- `stock.action_update_tx_attachments`
- `stock.action_update_tx_edit_fields`
- `stock.action_update_upper_group`
- `stock.action_update_warehouse`

## Current acceptance

- Manual surface parity and local execute/DB-or-file verify/audit: `verified_baseline`
- Shared task-runtime read→prepare→approval/resume→execute chain: `verified_baseline`
- Long Gemini/OpenRouter/suitable-local and provider-switch matrix: `open`
