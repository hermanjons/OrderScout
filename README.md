<p align="center">
  <img src="desktop/images/orderscout-logo.png" alt="OrderScout" width="112">
</p>

<h1 align="center">OrderScout</h1>
<p align="center"><strong>Siparişten kâra, e-ticaret operasyonun tek çalışma alanında.</strong></p>
<p align="center">Windows · Python · PyQt6 · SQLite · Açık kaynak</p>
<p align="center">
  <a href="README.en.md">English</a> ·
  <a href="https://github.com/hermanjons/OrderScout-releases/releases">Hazır uygulamayı indir</a> ·
  <a href="CONTRIBUTING.md">Katkıda bulun</a> ·
  <a href="SECURITY.md">Güvenlik</a>
</p>

OrderScout, Trendyol satıcılarının siparişlerini, iadelerini, stoklarını ve
maliyetlerini yerel bir masaüstü uygulamasında yönetmesi için geliştiriliyor.
Veriler bilgisayarındaki SQLite veritabanında tutulur; senkronizasyon için kendi
pazaryeri hesabını bağlarsın.

**Ücretsizdir. Aktivasyon anahtarı veya OrderScout aboneliği gerekmez.**
Geliştirmeye destek olmak istersen uygulamadaki “Bana bir kahve al” bölümünü
kullanabilirsin. Bağış hiçbir özelliği açıp kapatmaz.

## Neler yapabilirsin?

| Çalışma alanı | İşlev |
| --- | --- |
| Siparişler ve iadeler | Siparişleri getir, durumlarını izle, iade talepleriyle çalış. |
| Ürünler ve stok | İlanları, stok kartlarını, depoları ve stok hareketlerini yönet. |
| Maliyet ve kârlılık | Ürün maliyetlerini, komisyonları ve kargo tarifelerini değerlendir. |
| Kargo etiketleri | Sipariş bilgileriyle hazır etiket şablonlarını doldur ve çıktı hazırla. |
| Birden fazla firma | Firma ve pazaryeri hesaplarını aynı uygulamada kullan. |

Aktif entegrasyon odağı **Trendyol**'dur. Diğer pazaryerleri için yapılandırma
tanımları bulunması, bu entegrasyonların tamamlandığı anlamına gelmez.
AI çalışma alanı deneyseldir; yerel model veya harici sağlayıcı ayarı gerektirebilir.
Harici AI hizmetlerinin kendi ücretleri ve veri işleme koşulları geçerlidir.

## Başlarken

Hazır Windows uygulaması için [indirme deposuna](https://github.com/hermanjons/OrderScout-releases/releases)
git. Bu depo kaynak kodu, testleri ve geliştirme belgelerini içerir.

Kaynak koddan çalıştırmak için **Windows ve Python 3.11** kullan:

```powershell
git clone https://github.com/hermanjons/OrderScout.git
cd OrderScout
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
cd desktop
..\.venv\Scripts\python.exe main.py
```

İlk açılışta firma/pazaryeri hesabını ekle ve kendi API bilgilerini gir.
API anahtarlarını kaynak dosyalarına yazma. Windows dışındaki platformlar bu
sürümün destek kapsamına dahil değildir.

## Veriler ve güvenlik

- Uygulama verileri varsayılan olarak `%LOCALAPPDATA%\OrderScout` altında tutulur.
- Windows kimlik bilgisi deposu `%USERPROFILE%\.orderscout` altında DPAPI kullanır.
  Eski hesap kayıtlarında düz metin alanlar bulunabilir; yerel veritabanını paylaşma.
- Pazaryeri senkronizasyonu ilgili hizmete bağlanır. AI sağlayıcısını
  kullandığında isteğin kapsamındaki veriler o sağlayıcıya gönderilebilir.
- Log, veritabanı, sipariş çıktısı ve gerçek müşteri bilgilerini hata bildirimlerine ekleme.

[Güvenlik politikası](SECURITY.md) · [Kurulum ve ayarlar](docs/setup.md) ·
[Mimari](docs/architecture.md) · [Bilinen sınırlar](docs/project-status.md)

## Geliştirme

Bağımlılıklar sürüm ve dosya özetiyle kilitlenmiştir. Test ortamını kurmak için:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
cd desktop
..\.venv\Scripts\python.exe -m pytest tests/domain_feedback tests/domain_core tests/domain_main -q
```

Canlı pazaryeri/AI kabul testleri ayrı yapılandırma gerektirir; kendi hesapların
olmadan gerçek servis doğrulaması yapıldığı varsayılmaz.
[Katkı rehberi](CONTRIBUTING.md) test ve değişiklik akışını açıklar.

## Lisans

OrderScout'un özgün kaynak kodu **GPL-3.0-or-later** lisansıyla sunulur.
Copyright © 2026 OrderScout contributors. Ayrıntılar [LICENSE](LICENSE) dosyasında.
Üçüncü taraf kütüphane ve görsellerin koşulları için
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) dosyasına bak.
