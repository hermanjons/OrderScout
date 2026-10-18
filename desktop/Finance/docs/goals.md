# Finance Goals

Updated: 2026-07-17

Parent contracts: `../../Core/docs/domain_goals_contract.md`,
`../../AI/docs/goals.md`

Parity evidence: `../../AI/docs/finance_agentic_parity_matrix.md`

## Ürün Sonucu ve Sahiplik

Finance; dashboard, nakit akışı, kâr, maliyet kalemleri, manuel hareketler, faturalar,
kargo tarifeleri, marka/şirket finans verisi ve marketplace finans senkronunun sahibidir.
Hesaplama ve persistence Finance'ta kalır; AI yalnız ortak agentic döngüyü işletir.

## Capability Sözleşmesi

```text
read: 11
write: 22
total: 33
```

## Agentic Kabul

- Kâr, cashflow, maliyet kataloğu, dashboard, işlem, fatura ve kargo faturası cevapları
  gerçek dönem/payda/para birimini görünür biçimde taşır.
- Cost item, manuel işlem, fatura dokümanı, kargo tarifesi ve marka/şirket CRUD
  görevleri plan→prepare→approval→execute→DB/file verify→audit zincirini kullanır.
- Ortak task runtime içinden doğal dilde Finance write hazırlama ve approval sonrası
  mevcut `Finance.views.actions` operasyonuna devam etme local DB üzerinde
  deterministik olarak kanıtlanmıştır.
- API credential'ları task state, pending action, görünür cevap veya audit payload'ına
  yazılmaz; runtime güvenli credential referansını çözer.
- Marketplace Finance hesapları ortak account adapter'ını kullanır; `environment` ve
  `credential_reference` UI/AI/company-payload zincirinden Finance istemcisine kayıpsız
  taşınır.
- Stage istemcisi yalnız Stage API kökünü seçer. Stage hesabının production endpoint'ine
  sessiz geri düşmesi yasaktır ve yakalanan istek URL'siyle deterministik test edilir.

## Risk ve Dış Sınır

Local Finance yazmaları R1; marketplace finans sync R2 external write'tır. Secret-safe
adapter ve Production/Stage hard-isolation sözleşmesi deterministik olarak kanıtlanmış
olsa da gerçek kontrollü Stage Finance fetch/sync kanıtı `deferred_external`dır.
Production üzerinde gözetimsiz test edilemez.

## Güncel Durum

- Manuel parity ve Finance read cevapları: `verified_baseline`
- Local CRUD execute/verify/audit: `verified_baseline`
- Codex task prepare→approval→execute→verify: `verified_baseline` (local cost item
  referans zinciri; `test_finance_task_runtime_prepares_approves_executes_verifies_and_audits_local_write`)
- Finance Production/Stage hard isolation: `verified_baseline` (Stage URL seçimi, ortak
  account adapter'ı, credential-reference çözümü, production fallback yasağı ve
  explicit production URL override reddi, secret-free task/audit; canlı dış çağrı olmadan
  deterministik kabul; güncel `tests/domain_finance`: `74 passed`)
- Finance sync gerçek staging kanıtı: `deferred_external`
- Gemini kanıtı dışındaki OpenRouter ve uygun local uzun görev matrisi: `open`

Finance kilometre taşı, provider matrisi tamamlanmadan ve external sync açıkça
kanıtlanmış ya da dürüstçe deferred bırakılmış olmadan kapanmaz.
