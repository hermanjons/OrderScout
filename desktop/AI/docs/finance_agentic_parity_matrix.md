# Finance Agentic Parity Matrix

Updated: 2026-07-17

Authoritative inventory: `AI.processors.operation_runtime.operation_coverage_report`.
Finance calculations and persistence stay in Finance; AI only plans and orchestrates.

## Runtime coverage

- read: 11
- write: 22
- total: 33

## Capability inventory

### Read

- `finance.action_list_brands`
- `finance.action_list_companies`
- `finance.get_manual_finance_transactions_from_db`
- `finance.load_finance_cargo_invoices_from_db`
- `finance.load_finance_cargo_tariffs`
- `finance.load_finance_cargo_tariffs_summary`
- `finance.load_finance_cost_items`
- `finance.load_finance_dashboard_from_db`
- `finance.load_finance_invoice_documents_from_db`
- `finance.load_finance_quick_summary`
- `finance.load_finance_transactions_from_db`

### Write

- `finance.accept_finance_cargo_tariff`
- `finance.accept_finance_cargo_tariffs`
- `finance.accept_finance_cost_item`
- `finance.action_create_brand`
- `finance.action_create_company`
- `finance.action_delete_brand`
- `finance.action_delete_company`
- `finance.action_sync_finance_for_accounts`
- `finance.action_sync_finance_for_company_pks`
- `finance.action_sync_finance_for_selected_companies`
- `finance.action_update_brand`
- `finance.action_update_company`
- `finance.delete_finance_cargo_tariff`
- `finance.delete_finance_cargo_tariffs`
- `finance.delete_finance_cost_item`
- `finance.delete_finance_cost_items`
- `finance.delete_finance_invoice_document`
- `finance.delete_manual_finance_transaction`
- `finance.save_finance_cargo_tariff`
- `finance.save_finance_cost_item`
- `finance.save_finance_invoice_document`
- `finance.save_manual_finance_transaction`

## Current acceptance

- Manual parity, local CRUD execute/verify/audit and task approval/resume: `verified_baseline`
- Production/Stage hard isolation: `verified_baseline` for deterministic Stage URL selection,
  shared account-environment propagation, credential-reference resolution, production
  fallback/explicit cross-environment override rejection and secret-free task/audit payloads
  (`tests/domain_finance`: `74 passed`).
- Marketplace finance sync: `deferred_external`
- Long OpenRouter/suitable-local and provider-switch matrix: `open`
