# OrderScout Domain Goals Contract

Updated: 2026-10-16

Status: `binding`

Bu belge, her ana OrderScout domainindeki `docs/goals.md` dosyasının ortak
sözleşmesidir. Domain dosyaları bu kuralları tekrar kopyalamaz; yalnız kendi ürün
sonucunu, sahipliğini, capability yüzeyini, risklerini, kanıtlarını ve açık işlerini
tanımlar.

## Zorunlu Mimari

- Manuel UI ile AI aynı `views/actions.py` veya domain processor operasyonunu kullanır.
- Tool'un ihtiyaç duyduğu atomik işlem mevcut değilse geliştirme sırasında sahibi
  domainin application/processor katmanında oluşturulur ve test edilir. Atomik işlem
  eksikliği, yetkilendirilmiş işi mevcut tool listesine göre daraltma veya yalnız açık
  iş notu bırakıp bitmiş sayma gerekçesi değildir.
- Yeni atomik işlem tek, yeniden kullanılabilir bir iş sorumluluğu taşır; açık
  girdi/çıktı ve hata sözleşmesiyle UI ve AI'dan bağımsız çalışır. Mevcut manuel işlem
  aynı işi yapıyorsa onun adapter'ı da bu ortak fonksiyona bağlanır. Henüz manuel
  ekranı bulunmaması domain işlemini oluşturmayı engellemez.
- AI domain iş mantığını yeniden yazmaz; route, context, plan, prepare, approval,
  execute, verify ve audit katmanlarını sağlar.
- Normal agent konuşmasında niyet, iş yaklaşımı, araç seçimi ve doğal cevap seçili
  LLM'e aittir. Runtime kaynak/girdi/etki/onay/bütçe bütünlüğünü uygular; hazır bir
  iş senaryosu veya prose şablonuyla modelin kararını değiştirmez. Tek amaçlı bir
  tool, domain içinde birden fazla atomik fonksiyonu birleştirebilir; her yardımcı
  fonksiyonun veya widget callback'inin ayrı tool olarak açılması gerekmez.
- Gerçekten domainler arası olan primitive Core'a alınır. Domain terimi veya özel iş
  kuralı taşıyan kod sahibi domainde kalır.
- Kayıt kimlikleri structured state içinde taşınır. Görünür model metni kayıt kapsamının
  tek kaynağı olamaz.
- Count, list, selected set, prepare, execute ve verify aynı immutable kapsamı korur.
- Provider/model seçimi domain davranışını değiştirmez. Gemini, OpenRouter ve uygun
  local model aynı typed tool/operation sözleşmesini tüketir.
- Uzun görevler ortak task runtime'da planlanır; write adımı yalnız açık kullanıcı
  niyetiyle prepare edilir ve kullanıcı onayı olmadan execute edilmez.
- R0 salt-okuma, R1 local/reversible, R2 external write ve R3 yüksek etkili işlem
  ayrımı korunur. R2/R3 gerçek testleri kontrollü ortamda veya kullanıcı gözetiminde
  yapılır.

## Her Domain Goals Dosyasının Zorunlu İçeriği

1. Ürün sonucu ve domain sahipliği
2. Manuel capability toplamı ile read/write dağılımı
3. Agentic read ve write kabul zincirleri
4. Structured context ve cross-domain bağlantılar
5. Risk/deferred external sınırları
6. Deterministic, offscreen, gerçek veri ve canlı model kanıtları
7. `verified_baseline`, `partial`, `open`, `deferred_external` veya
   `blocked_external` durumlarıyla güncel gerçek
8. Kapanmadan önce tamamlanması gereken ölçülebilir maddeler

## Ortak Kapanma Yasağı

Bir domain aşağıdakilerden yalnız biriyle tamamlanmış sayılamaz:

- Capability'nin envanterde görünmesi
- Tool'un doğru seçilmesi
- Prepare veya approval kartının oluşması
- Tek provider ya da tek kısa sohbetin geçmesi
- Yalnız fixture veya yalnız pytest sonucunun yeşil olması
- Execute sonucunun bağımsız read-back olmadan başarılı dönmesi
- `deferred_external` işin yapılmış gibi raporlanması

Kapanış için manuel parity, doğal task döngüsü, doğru visible cevap, state devamlılığı,
uygun provider/model matrisi, risk seviyesine uygun gerçek kanıt ve bağımsız verify/audit
birlikte gerekir. Yeni gerçek kullanıcı hatası daha eski bütün passing artifact'lardan
önceliklidir.
