# Proje durumu

OrderScout aktif geliştirilen bir masaüstü uygulamasıdır. Özellik kapsamı ve
entegrasyonlar zaman içinde değişir; sürüm notları ve test sonuçları birlikte
değerlendirilmelidir.

## Odağımız

- Trendyol sipariş/iadeleri, ürünler, stok ve maliyet akışları.
- Yerel SQLite verisiyle çalışan manuel masaüstü iş akışları.
- Aktivasyon sistemi olmadan ücretsiz kullanım ve isteğe bağlı bağış.

## Henüz tamamlanmış sayılmayan alanlar

- AI iş ajanı deneyseldir. Bir sağlayıcının yanıt vermesi, bir iş akışının
  uçtan uca doğrulandığını göstermez. Dış sistemde değişiklik yapan işlemlerde
  onay ve doğrulama sınırlarını korumak gerekir.
- Geniş test çalışmasında AI sohbeti/çalışma zamanı sözleşmeleriyle ilgili
  başarısız regresyonlar vardır. CI'daki seçili testlerin geçmesi bütün AI
  kabul senaryolarının geçtiği anlamına gelmez.
- Diğer pazaryerleri için yapılandırma iskeletleri tamamlanmış entegrasyon değildir.
- Fatura ve bazı finans işlem ekranları görünürlük anahtarlarının arkasındadır.
- Canlı servis kabulü, ilgili hesap ve gerçek servis kanıtı gerektirir.
- Windows dışındaki platformlar desteklenmez.

## Güvenlik sınırı

Gitleaks ve bağımlılık taramaları bilinen örüntü/veritabanlarıyla sınırlıdır.
Sıfır bulgu, bütün güvenlik sorunlarının giderildiği iddiası değildir.
Tüm serbest metinlerdeki kişisel bilgilerin otomatik temizlendiği varsayılmaz.
API anahtarları ve gerçek sipariş verileri asla test fixture'ı olarak paylaşılmamalıdır.
