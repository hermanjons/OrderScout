# Kurulum ve ayarlar

Desteklenen geliştirme ortamı Windows ve Python 3.11'dir. Başlangıç komutları
[README](../README.md) içindedir. Komutları proje kökünden, uygulamayı ise
`desktop` klasöründen çalıştır.

## Yerel veri

`desktop/settings.py` varsayılan olarak `%LOCALAPPDATA%\OrderScout` altında
veritabanı, log ve çıktı klasörlerini oluşturur. Uygulamayı ilk kez açmak için
pazaryeri anahtarı gerekmez; veri senkronizasyonu için kendi hesabını eklemelisin.
Uygulama verilerini yedeklerken bunları hassas veri olarak ele al.

## Ortam değişkenleri

PowerShell'de, uygulamayı başlatmadan önce ayarlayabilirsin:

| Değişken | Amaç |
| --- | --- |
| `ORDER_SCOUT_DONATION_URL` | İsteğe bağlı kişisel bağış sayfası; varsayılan boştur. |
| `ENABLE_AI_UI` | Deneysel AI çalışma alanını göstermek için `1`, gizlemek için `0`. |
| `ENABLE_TEST_LAB_UI` | Geliştirici Test Lab araçlarını göstermek için `1`. |
| `ENABLE_FINANCE_INVOICES_UI` | Tamamlanmamış fatura arayüzünü göstermek için `1`. |
| `ENABLE_FINANCE_TRANSACTIONS_UI` | Tamamlanmamış işlem arayüzünü göstermek için `1`. |

```powershell
$env:ENABLE_AI_UI = "0"
$env:ENABLE_TEST_LAB_UI = "0"
```

Kaynak çalıştırmada AI ve Test Lab görünür olabilir; paketlenmiş sürümde
varsayılan olarak gizlenir. Görünürlük, bir özelliğin kabul testlerinden geçtiği
veya tüm entegrasyonların tamamlandığı anlamına gelmez.

## API bilgileri

Hesapları uygulamanın firma yönetiminden ekle. Kaynak dosyasına anahtar koyma;
ortak veya demo adı altında gerçek hesap dağıtma. Test Lab için ayrı bir Stage
hesabı kullan. AI sağlayıcıları uygulama içinden ayrıca yapılandırılır.

## Bağımlılık güncelleme

Kilit dosyaları Python 3.11 için sınanır. Özellikle SQLModel sürümünü tek başına
yükseltme: tarih/saat alanlarının saklama davranışı yeni sürümlerde değişebilir.
Yeni bağımlılık setini ayrı bir ortamda test et ve güvenlik denetimini tekrar çalıştır.
