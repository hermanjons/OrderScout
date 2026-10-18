# Mimari

OrderScout bir Windows masaüstü uygulamasıdır. Giriş noktası `desktop/main.py`,
ortak ayarlar `desktop/settings.py` dosyasıdır. PyQt6 arayüzü, SQLModel/SQLAlchemy
ile SQLite üzerinde çalışan domain akışlarını çağırır.

| Klasör | Sorumluluk |
| --- | --- |
| `Account` | Firma ve pazaryeri hesapları. |
| `Orders` | Sipariş/iadelerin alınması, saklanması ve yönetimi. |
| `Listing`, `Stock` | Pazaryeri ürünleri, stok kartları, depo ve hareketler. |
| `Finance`, `Logistics` | Maliyetler, kârlılık ve kargo tarifeleri. |
| `Labels` | Etiket şablonları ve çıktı hazırlama. |
| `Marketplaces` | Pazaryeri yapılandırmaları ve API sözleşmeleri. |
| `Core`, `Feedback` | Veritabanı, kimlik bilgisi deposu, ortak UI ve redakte loglar. |
| `AI` | Deneysel iş ajanı, sağlayıcılar, model ve araç çalışma zamanı. |
| `Update`, `Support` | Güncelleme akışı ve isteğe bağlı bağış arayüzü. |
| `Testing`, `tests` | Test Lab, sentetik veriler ve otomatik kontroller. |

Domainler tipik olarak `views`, `processors`, `models`, `api` ve `constants`
katmanlarına ayrılır. Manuel UI ve AI araçlarının ortak iş mantığını kullanması
amaçlanır; AI için ayrı bir ticari hesaplama yolu oluşturulmamalıdır.

## Sınırlar

Pazaryeri ve AI servisleri dış ağ sınırıdır. Yerel veritabanı ve Windows kimlik
bilgisi deposu kullanıcı verisi içerir; kaynak deposunun parçası değildir.
Hata mesajları ve istisna izleri log kuyruğuna girmeden önce yaygın anahtar
alanları bakımından redakte edilir.

`AI/runtime` içindeki Python dosyaları uygulama kaynak kodudur. Bu klasördeki
indirilmiş model çalıştırıcıları/binary dosyaları kaynak dağıtımına dahil edilmez.
Canlı kabul kayıtları ve özel çalışma raporları da yayımlanmaz.
