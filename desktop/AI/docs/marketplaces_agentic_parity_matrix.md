# Marketplaces Agentic Parity Matrix

Updated: 2026-07-17

Authoritative inventory: `AI.processors.operation_runtime.operation_coverage_report`.
Marketplace catalog identity remains in Marketplaces; account credentials remain in the
credential store and Account domain.

## Runtime coverage

- read: 1
- write: 4
- total: 5

## Capability inventory

### Read

- `marketplaces.load_marketplaces`

### Write

- `marketplaces.accept_marketplace_record`
- `marketplaces.delete_marketplace`
- `marketplaces.save_marketplace`
- `marketplaces.set_marketplaces_active_state`

## Current acceptance

- Manual parity, local DB execute/verify/audit and task approval/resume: `verified_baseline`
- Catalog/account structured-state separation: `verified_baseline`
- Catalog-only API endpoint ownership and explicit Trendyol client inventory:
  `verified_baseline` (`tests/domain_marketplaces`: `29 passed`). Runtime Python source
  cannot hard-code Trendyol API origins; the accepted client families are Orders, Listing
  and Finance, each with explicit Production/Stage coverage.
- Long Gemini/OpenRouter/suitable-local and provider-switch matrix: `open`
