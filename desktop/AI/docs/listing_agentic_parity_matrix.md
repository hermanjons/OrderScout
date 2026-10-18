# Listing Agentic Parity Matrix

Updated: 2026-07-17

Authoritative inventory: `AI.processors.operation_runtime.operation_coverage_report`.
Listing marketplace/cache rules remain in Listing and are never reimplemented in AI.

## Runtime coverage

- read: 9
- write: 7
- total: 16

## Capability inventory

### Read

- `listing.action_check_batch_request_for_account`
- `listing.action_get_all_companies`
- `listing.action_get_company_credentials`
- `listing.action_get_listing_brands_from_db`
- `listing.action_get_listings_from_db`
- `listing.action_load_finance_cargo_tariffs`
- `listing.action_load_finance_cost_items`
- `listing.action_load_logistics_cargo_providers`
- `listing.action_load_logistics_cargo_tariffs`

### Write

- `listing.action_fetch_listings`
- `listing.action_set_listing_cost_items`
- `listing.action_set_listing_stock_items`
- `listing.action_sync_listing_cost_snapshots_for_item`
- `listing.action_update_approved_content_for_account`
- `listing.action_update_listing_price_inventory_cache`
- `listing.action_update_price_inventory_for_account`

## Current acceptance

- Read parity, local cache/binding execute/DB verify/audit: `verified_baseline`
- Price/inventory staging mutation: `deferred_external`
- Title/description/image content prepare/API/runtime boundary: `verified_baseline`
  - SEO/content optimize önerisi execute edilemez ve staging action taşımaz.
  - Explicit mutation yalnız kullanıcı-verili title/description/HTTPS image URL ile,
    tek approved `contentId` + tek `api_account_id` kapsamında hazırlanır.
  - V2 `content-bulk-update` doğrulaması API sınırında tekrarlanır; attributes kabul edilmez.
  - Listing fetch, fiyat/stok ve içerik istemcileri account `environment` değerini korur.
  - Listeleme, fiyat/stok, içerik ve batch-result operasyonları catalog'daki environment
    kökünden ayrılamaz; Stage/production çapraz `base_url` override'ı istekten önce reddedilir.
  - Direct generic execute reddedilir; staging preflight seller/environment/idempotency
    doğrulaması ve başarılı Trendyol batch verify olmadan runtime başarı saymaz.
  - Account DPAPI credential reference istemciye adapter içinde bağlanır; pending action
    ve audit credential/secret içermez.
- Title/description/image gerçek Stage mutation/read-back: `deferred_external`
- Long Gemini/OpenRouter/suitable-local and provider-switch matrix: `open`

## Deterministic evidence

- `tests/domain_listing`: `92 passed + 9 subtests`
- `tests/domain_ai`: `763 passed, 443 skipped + 64 subtests`
- Listing odaklı AI tekrar koşusu: `34 passed, 13 skipped`
- `test_stage_listing_operations_use_only_stage_endpoints`
- `test_listing_client_rejects_cross_environment_base_url_overrides`
- `test_listing_explicit_content_update_prepares_exact_stage_action_and_verifies_batch`
- `test_listing_content_update_rejects_ambiguous_scope_and_keeps_seo_suggestion_unbound`
- `test_update_approved_content_uses_v2_stage_endpoint_and_exact_payload`
- `test_update_approved_content_rejects_unsafe_or_incomplete_payload_before_request`
