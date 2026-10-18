# Katkıda bulunma

Hata düzeltmeleri, testler, belgeler ve arayüz iyileştirmeleri için katkı bekliyoruz.
Büyük bir entegrasyon veya davranış değişikliği için önce bir issue açıp amacı açıkla.

## Ortam

Windows ve Python 3.11 kullan. Proje kökünde:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
cd desktop
..\.venv\Scripts\python.exe -m pytest tests/domain_feedback tests/domain_core tests/domain_main -q
```

Değiştirdiğin domainin testlerini de çalıştır. Bütün yerel testleri çalıştırmak
için `python -m pytest tests -q` kullanabilirsin. Canlı servis kabul senaryoları
ayrı hesap ve yapılandırma ister; bunları normal test çalışmasına dahil etme.
Yerel kabul kanıtı olmayan bir senaryoyu başarılı olarak işaretleme.
Pytest başlangıcı uygulama verilerini ve kimlik bilgisi deposunu geçici bir
klasöre yönlendirir; geliştiricinin gerçek iş veritabanını kullanmaz.

## Değişiklikler

- İş mantığını ilgili domainin `processors` katmanında tut; görünüm katmanından
  kullanılan aynı akışı test et.
- Pazaryeri uçlarını `Marketplaces/constants/files` içindeki tanımlarla uyumlu tut.
- API anahtarı, gerçek sipariş, telefon, adres veya özel çalışma raporu ekleme.
- Hata ve güvenlik testlerinde açıkça sentetik veri kullan.
- Bağımlılığı değiştirirken `desktop/requirements*.txt` kaynaklarını düzenle ve
  kökteki kilit dosyalarını yeniden üret:

```powershell
uv pip compile desktop/requirements.txt --universal --generate-hashes -o requirements.lock
uv pip compile desktop/requirements-dev.txt --universal --generate-hashes -o requirements-dev.lock
```

PR açıklamasında sorunu, kullanıcıya etkisini ve çalıştırdığın testleri belirt.
Katkılar, aksi açıkça kararlaştırılmadıkça projenin GPL-3.0-or-later lisansı
altında kabul edilir. Başkasına ait kod veya görseller için lisans bilgisini koru.

Güvenlik sorunları için [SECURITY.md](SECURITY.md) yolunu izle.
