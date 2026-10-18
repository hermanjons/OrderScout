# Marketplaces Goals

Updated: 2026-07-17

Parent contracts: `../../Core/docs/domain_goals_contract.md`,
`../../AI/docs/goals.md`

Parity evidence: `../../AI/docs/marketplaces_agentic_parity_matrix.md`

## Ürün Sonucu ve Sahiplik

Marketplaces; desteklenen pazaryeri kataloğu, kabul/save/delete ve active-state
yönetiminin sahibidir. API account credential yaşam döngüsü Account domaininde;
marketplace katalog kimliği bu domainde kalır.

## Capability Sözleşmesi

```text
read: 1
write: 4
total: 5
```

## Agentic Kabul

- Katalog/özet/aktif sayı soruları marketplace kayıtlarını account kayıtlarıyla
  karıştırmadan cevaplanır.
- Accept/save/delete/active-state işlemleri exact marketplace code kapsamıyla task
  runtime'da prepare edilir, approval olmadan DB yazmaz ve DB verify/audit üretir.
- Yeni platform eklendiğinde katalog, API scope metadata ve ilgili domain capability
  profilleri birlikte güncellenir; AI içine platforma özel kopya akış yazılmaz.
- Marketplace API origin ve operation path'leri yalnız catalog'da tanımlanır. Runtime
  Python kaynaklarında hard-coded Trendyol API origin'i bulunamaz; yeni Trendyol client
  ailesi açık envanter testine eklenmeden kabul edilmez.

## Güncel Durum

- Manuel parity ve local DB execute/verify/audit: `verified_baseline`
- OpenRouter görünür cevap/execute baseline: `verified_baseline`
- Task runtime local write döngüsü: `verified_baseline` — katalog read kapsamı korunarak
  accept prepare edilir; approval/resume sonrası mevcut Marketplaces action'ı, DB
  read-back ve audit geçer (`test_marketplaces_task_runtime_preserves_read_scope_then_executes_verifies_and_audits_local_write`)
- Trendyol HTTP client envanteri ve catalog-only endpoint sahipliği: `verified_baseline` —
  mevcut üç aile Orders, Listing ve Finance'tır; Production/Stage environment kapsamları
  domain testleriyle, envanter/hard-coded-origin yasağı `tests/domain_marketplaces`
  kapısıyla korunur (`29 passed`).
- Gemini ve uygun local uzun görev/model geçişi: `open`

Marketplaces kilometre taşı katalog/account ayrımı ve provider geçiş state'i uzun
sohbette kanıtlanmadan kapanmaz.
