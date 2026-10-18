# Logistics Goals

Updated: 2026-07-15

Parent contracts: `../../Core/docs/domain_goals_contract.md`,
`../../AI/docs/goals.md`

Parity evidence: `../../AI/docs/logistics_agentic_parity_matrix.md`

## Ürün Sonucu ve Sahiplik

Logistics; kargo sağlayıcı kataloğu, tarife kayıtları, önerilen kayıtların kabulü ve
toplu tarife yönetiminin sahibidir. Listing/Finance yalnız Logistics'in yayınladığı
provider/tariff sonuçlarını tüketir.

## Capability Sözleşmesi

```text
read: 3
write: 8
total: 11
```

## Agentic Kabul

- Profil, provider ve tarife soruları gerçek Logistics kayıt/sayılarıyla cevaplanır.
- Provider/tariff save, accept, delete ve bulk işlemleri ortak task runtime'da açık
  write niyetiyle prepare edilir; local DB etkisi onaydan önce oluşmaz.
- Execute mevcut Logistics action'ına gider; tekil/toplu kayıt seti DB read-back ve
  audit ile doğrulanır.
- Listing/Finance bağlantısında provider id/code kaynağı structured state'tir.

## Güncel Durum

- Manuel parity, read ve local CRUD/bulk verify: `verified_baseline`
- Task runtime local write döngüsü: `verified_baseline` — provider read kapsamı korunarak
  save prepare edilir; approval/resume sonrası mevcut Logistics action'ı, DB read-back ve
  audit geçer (`test_logistics_task_runtime_preserves_read_scope_then_executes_verifies_and_audits_local_write`)
- Gemini görünür cevap/execute baseline: `verified_baseline`
- OpenRouter ve uygun local uzun görev kabulü: `open`

Logistics kilometre taşı provider/model geçişlerinde aynı tarife/provider state'i
korunduğu kanıtlanmadan kapanmaz.
