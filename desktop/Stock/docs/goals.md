# Stock Goals

Updated: 2026-07-15

Parent contracts: `../../Core/docs/domain_goals_contract.md`,
`../../AI/docs/goals.md`

Parity evidence: `../../AI/docs/stock_agentic_parity_matrix.md`

## Ürün Sonucu ve Sahiplik

Stock; stok kartı, depo, giriş/çıkış hareketi, bakiye, maliyet detayı, ayarlama ve
Orders/Listing kaynaklı otomatik düşümün authoritative domainidir. AI bu kuralları
kopyalamaz; mevcut Stock action/pipeline fonksiyonlarını doğal dilden çalıştırır.

## Capability Sözleşmesi

```text
read: 14
write: 25
total: 39
```

Manuel capability envanteri ile operation catalog birebir kalmalıdır. Yeni bir Stock UI
aksiyonu eklendiğinde envanter, operation metadata, parity matrisi ve bu dosyanın durumu
aynı değişiklikte değerlendirilir.

## Agentic Kabul

- Envanter özeti, düşük stok, sıfır/negatif stok, kart/depo/hareket/bakiye ve maliyet
  soruları authoritative Stock sonuçlarıyla cevaplanır.
- Create/update/delete, manuel giriş/çıkış, stok ayarlama, attachment, export, marka,
  şirket ve grup işlemleri ortak task runtime'da açık write niyetiyle prepare edilir.
- Approval öncesi DB/dosya etkisi oluşmaz; execute mevcut Stock fonksiyonuna gider;
  bakiye, kayıt veya dosya bağımsız read-back ile doğrulanır ve audit edilir.
- Orders/Listing bağlantısı structured record ref ve domain operation sonucu üzerinden
  kurulur; assistant metninden kimlik çıkararak işlem yapılmaz.

## Risk ve Kanıt

Local DB ve export işlemleri R1'dir; destructive delete kapsamı görünür olmalı ve onay
gerektirir. Mevcut manuel parity ve local execute/verify kanıtı `verified_baseline`dır.
Ortak task runtime write-prepare desteği deterministik olarak kanıtlanmıştır.

## Güncel Durum

- Manuel read/write parity: `verified_baseline`
- Local execute/verify/audit: `verified_baseline`
- Codex task write döngüsü: `verified_baseline` — bileşik read→prepare görevi approval
  öncesi etkisiz kalır; resume mevcut Stock operasyonuna gider, DB read-back ve audit
  üretir (`test_stock_task_runtime_preserves_read_scope_then_executes_verifies_and_audits_local_write`)
- Gemini/OpenRouter/local uzun görünür cevap matrisi: `open`

Stock AI kilometre taşı, en az iki cloud provider ve uygun local modelde uzun task/state
devamlılığı ile gerçek local read-back birlikte geçmeden tamamlanmış sayılmaz.
