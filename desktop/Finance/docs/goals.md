# Finance Goals

## 20 Ekim 2026 ortak nakit hareketi hesabı

`cashflow.read_cashflow_summary` tarih, silinme ve döviz kurallarının sahibidir.
AI adapter'ı dönem girdisini çözüp domain sonucunu taşır. Manuel finans
özetleriyle ortak `transaction_amount_totals` primitive'i kullanılır. Hatalar
boş başarıya çevrilmez. Çoklu/belirsiz döviz tek tutara indirgenmez; kayıtlı
hareket neti banka bakiyesi değildir. Bu kapsamın kanıtı
`../../AI/docs/atomic_domain_operations_2026_10_20.md` altındadır. Genel Finance
kabulü açık kalır.

Kâr motorunun gerektirdiği maliyet ve tarife katalog okumaları, kabul/override
kuralları korunarak `catalog_reads` içine taşındı. Manuel actions aynı domain
işlemlerine delege eder; katalog cache'i bu processor'ın sorumluluğundadır.

Updated: 2026-10-20

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
