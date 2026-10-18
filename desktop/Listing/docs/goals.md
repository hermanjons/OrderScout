# Listing Goals

Updated: 2026-07-17

Parent contracts: `../../Core/docs/domain_goals_contract.md`,
`../../AI/docs/goals.md`

Parity evidence: `../../AI/docs/listing_agentic_parity_matrix.md`

## Ürün Sonucu ve Sahiplik

Listing; marketplace ilan cache'i, barkod/ürün kimliği, stok ve maliyet bağları, kâr
tahmini, kalite/SEO görünümü, listing fetch ve Trendyol fiyat/envanter güncellemesinin
sahibidir. AI Listing pipeline'ını yeniden üretmez.

## Capability Sözleşmesi

```text
read: 9
write: 7
total: 16
```

## Agentic Kabul

- Arama, özet, fiyat, başlık, detay, stok, durum, URL, attention ve quality audit
  cevapları aynı Listing record ref'lerini korur.
- Fetch, local cache, stock/cost binding ve cost snapshot görevleri ortak task runtime
  üzerinden prepare/onay/execute/verify/audit zincirine girer.
- Fiyat veya stok güncellemesi exact listing/account/value kapsamını taşıyan staging
  action olarak hazırlanır; credential pending action'a girmez.
- Content optimize yalnız öneridir ve execute edilemez. Kullanıcının açıkça verdiği
  title/description/HTTPS image URL değerleri ise `contentId` + tek account kapsamına
  bağlanan ayrı `content_update.prepare` akışından geçer; AI içerik veya URL uydurmaz.
- Onaylı içerik mutation'ı Trendyol v2 `content-bulk-update` operasyonunu kullanır;
  en fazla 1000 item, 100 karakter başlık, 30000 karakter açıklama, en fazla 8 HTTPS
  görsel ve attributes yasağı domain API sınırında tekrar doğrulanır.

## Risk ve Dış Sınır

Local binding/cache yazmaları R1; Trendyol fiyat/envanter ve onaylı içerik mutasyonları
R2'dir. Her ikisi de DB'deki account environment'ını istemciye taşır, doğrudan generic
execute'a kapalıdır ve yalnız staging preflight + idempotency + exact seller guard ile
çalışır. Listing istemcisi environment catalog kökü dışında bir `base_url` override'ını
istek oluşmadan reddeder; Stage→production ve production→Stage çapraz geçişi yasaktır.
Gerçek kontrollü içerik mutation kanıtı `deferred_external`dır.

## Güncel Durum

- Read parity ve görünür listing cevapları: `verified_baseline`
- Local write execute/DB verify/audit: `verified_baseline`
- Task runtime local write döngüsü: `verified_baseline` — açık `yerel cache` niyeti R1
  cache operasyonuna gider, R2 marketplace mutation'a kaymaz; approval/resume sonrası
  DB verify ve audit üretir (`test_listing_task_runtime_keeps_local_cache_write_separate_from_external_mutation_and_verifies_db`)
- Trendyol price/inventory gerçek staging execute: `deferred_external`
- Content title/description/image prepare/API/runtime boundary: `verified_baseline` —
  öneri ile mutation ayrıldı; tek onaylı contentId/account, kullanıcı-verili değer,
  Stage endpoint, secret-redacted audit ve batch-result verify deterministik testlerden geçti.
  DPAPI credential bundle reference runtime'da çözülür; pending action ve audit ham secret
  veya credential reference taşımaz.
- Production/Stage hard isolation: `verified_baseline` — listeleme, fiyat/stok, içerik ve
  batch-result yolları seçili environment endpoint'inde kalır; cross-environment explicit
  URL override reddedilir ve production fallback oluşmaz.
- Deterministik kanıt: `tests/domain_listing` offscreen `92 passed + 9 subtests`;
  güncel exhaustive `tests/domain_ai` `763 passed, 443 skipped + 64 subtests`; Listing
  odaklı son tekrar `34 passed, 13 skipped`.
- Content title/description/image gerçek Stage mutation/read-back: `deferred_external`
- Gemini/OpenRouter/local uzun model matrisi: `open`

Listing kilometre taşı, content sınırı dürüstçe çözülmeden ve provider/state kabulü
tamamlanmadan bitmiş sayılmaz.
