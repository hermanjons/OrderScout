# Orders Agentic Parity Matrix

Bu dosya, Orders kaynak UI'sındaki tıklanabilir yüzeylerin agentic karşılığını veya
bilinçli `UI-only` sınıfını bağlayıcı envanter olarak tutar. İş mantığı burada
tekrarlanmaz; capability ve execute adapter'ları ilgili domain/Core sözleşmelerini
kullanır.

Authoritative inventory:
`AI.processors.operation_runtime.operation_coverage_report`.

## Runtime coverage

- read: 26
- write: 10
- total: 36

### Read inventory

- `orders.action_list_item_balances`
- `orders.action_list_items`
- `orders.fetch_orders_all` — intentionally blocked from generic read routing; use the
  approval-aware account fetch/sync flow
- `orders.get_latest_order_items_by_numbers`
- `orders.get_latest_orders`
- `orders.get_latest_orders_filtered`
- `orders.get_latest_ready_to_ship_orders`
- `orders.get_latest_return_claims`
- `orders.get_latest_return_claims_filtered`
- `orders.get_listings_from_db`
- `orders.get_nonfinal_order_numbers`
- `orders.get_order_date`
- `orders.get_stale_return_claims`
- `orders.list_changeable_cargo_providers`
- `orders.load_finance_cost_items`
- `orders.load_logistics_cargo_tariffs`
- `orders.load_order_items_for_order_number`
- `orders.load_order_items_for_order_numbers`
- `orders.load_order_profit_catalog`
- `orders.load_orders_by_numbers`
- `orders.load_orders_for_source_filters`
- `orders.load_orders_for_status_filter`
- `orders.load_ready_to_ship_orders`
- `orders.load_returns_claims`
- `orders.load_returns_for_source_filters`
- `orders.load_returns_from_db`

### Write inventory

- `orders.action_export_order_profit_excel`
- `orders.action_export_report_snapshot_xlsx`
- `orders.approve_return_claim`
- `orders.change_order_cargo_provider`
- `orders.change_orders_cargo_provider_bulk`
- `orders.get_orders_from_companies`
- `orders.mark_return_claims_stale`
- `orders.restore_return_claims_from_stale`
- `orders.save_return_claims_to_db`
- `orders.update_last_used_at_for_accounts`

## Operational Orders Controls

| Manuel yüzey | Agentic karşılık | Risk/sonuç |
|---|---|---|
| Veri Cek | `orders.get_orders_from_companies` | Marketplace read + lokal sync; approval ve verify gerekir. |
| Order profit Excel export | `orders.export_profit_excel.prepare` | Lokal dosya, prepare/approval/execute/filesystem verify. |
| Ad-hoc Orders report Excel export | `orders.item_sales_report_xlsx.prepare` | Aynı immutable ReportSnapshot, approval, structural/semantic XLSX read-back. |
| Detail cargo change | `orders.change_cargo_provider.prepare` | External write; Stage guard veya production supervised kapısı. |
| Detail/bulk print labels | `labels.create_from_orders.prepare` | Immutable selection; DOCX/print sonucu ayrı doğrulanır. |
| Approve return | `returns.approve.prepare` | Destructive external write; exact claim/account kapsamı gerekir. |
| Bulk cargo change | `orders.change_cargo_provider_bulk.prepare` | External write; her kayıt/account scope'u korunur. |
| Review stale returns | `returns.reconcile_snapshot` | Read/reconciliation; fresh snapshot olmadan mutation yok. |
| Restore stale returns | `returns.restore_stale.prepare` | Lokal reversible write; prepare/approval/DB verify gerekir. |

## UI-Only Orders Controls

Bu kontroller domain operasyonu değildir ve modele bağımsız bir write capability gibi
sunulmaz:

- Auto fetch toggle
- Navigation and drawer controls
- Clear filters and pagination
- Returns-mode inherited order controls

UI-only sınıfı; pencere açma/kapama, drawer açma, sayfalama, filtre temizleme,
responsive yerleşim ve istemci görünüm state'i gibi etkileri kapsar. Bu sınıfın bir
üyesi ileride gerçek domain etkisi üretirse önce operation catalog, risk sınıfı,
prepare/verify sözleşmesi ve bu matris birlikte güncellenir.
