# Stock Goals

## 2 Kasım 2026 stok eşiği primitive'leri

`item_updates` tek kartın politika önizlemesi, snapshot ve miktar doğrulamasını
sağlar. AI `stock.thresholds.prepare` aracı burayı kullanır; execute manuel
UI'nin de kullandığı `pipeline.update_item` fonksiyonuna gider. İsteğe bağlı
`expected_values`, SQL'de de korunan karşılaştırmayla eski onayın yeni manuel
değeri ezmesini önler. Eski manuel çağrı sözleşmesi korunur.

`item_queries` bütün stok eşiklerini null/kesir korumasıyla döndürür.
`policy_rules` düşük stok hesabına giren alanlarla yalnız saklanan ayarları
ayırır; stok politikası kaydı otomatik bildirim veya sipariş kanıtı sayılmaz.
129 ilgili test +10 alt test ve ücretsiz modelle yedi turluk izole akış geçti.
Genel Stock AI milestone/provider matrisi açık kalır.
[İş akışı kanıtı](../../AI/docs/stock_threshold_workflow_2026_11_02.md).

## 20 Ekim 2026 ortak katalog işlemleri

`item_queries` arama/liste/sayım işlemlerinin sahibidir. Arama ve liste bakiyeleri
gerçek manuel ekranlarla aynı `pipeline.list_item_balances` hesabından gelir;
AI hareketlerden tekrar bakiye üretmez. Kesirli miktarlar korunur, tanımsız eşik
sıfır sayılmaz ve sayfalama tam eşleşme sayısını açıklar. Yeni manuel
`action_list_items_with_balances` aynı primitive'i kullanır. Mevcut görsel arama
widget'ları yeniden yazılmadı. Genel Stock kabulü açık; bu kapsamın kanıtı
`../../AI/docs/atomic_domain_operations_2026_10_20.md` altındadır.

Updated: 2026-11-02

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
