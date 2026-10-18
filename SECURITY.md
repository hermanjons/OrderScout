# Güvenlik politikası / Security policy

## Bir açık bildirmek

Gerçek API anahtarlarını, müşteri verilerini veya kullanılabilir bir saldırı
örneğini herkese açık bir issue'ya ekleme. GitHub'ın
[özel güvenlik bildirimi](https://github.com/hermanjons/OrderScout/security/advisories/new)
kanalını kullan. Bu kanal kullanılamıyorsa, herkese açık issue'da yalnızca
özel iletişim iste; hassas ayrıntıları paylaşma.

Please report vulnerabilities through GitHub's private security advisory form.
Do not post credentials, customer data or working exploits in public issues.

## Kapsam

En güncel kaynak sürümündeki kimlik bilgisi sızıntıları, güvensiz dosya/çıktı
işleme, güncelleme akışı ve yetkisiz işlem sorunları önceliklidir.
Eski sürümler için sürekli bakım veya yanıt süresi taahhüdü verilmez.

## Verilerini koru

- Pazaryeri ve AI anahtarlarını kaynak koda, testlere veya ekran görüntülerine koyma.
- Testlerde sentetik veri ve ayrı test hesabı kullan; gerçek müşteri verisi ekleme.
- `%LOCALAPPDATA%\OrderScout` veritabanını, dışa aktarımları ve
  `%USERPROFILE%\.orderscout` kimlik bilgisi deposunu paylaşma.
- DPAPI Windows kullanıcısına bağlıdır; aynı kullanıcı adına çalışan kötü amaçlı
  yazılıma karşı bir güvenlik sınırı değildir. Eski hesap verilerindeki düz metin
  kimlik bilgilerini de hassas kabul et.
- Log redaksiyonu yaygın anahtar alanlarını ve yetkilendirme başlıklarını temizler;
  bütün serbest metinlerdeki kişisel bilgileri otomatik olarak temizlediği varsayılmaz.
- Dış AI sağlayıcısını kullanmadan önce ilgili veri paylaşım koşullarını değerlendir.
- Bir anahtarın sızdığını düşünüyorsan önce sağlayıcıdan iptal et/yenile; dosyayı
  silmek veya Git geçmişini değiştirmek anahtarı geçersiz kılmaz.

## Proje korumaları

Bağımlılık kilit dosyalarında dosya özetleri tutulur. CI; kaynak kontrolleri,
seçili otomatik testler, bağımlılık denetimi ve Gitleaks taraması içerir.
Bu kontroller, bağımsız ve kapsamlı bir güvenlik denetimi yapıldığı anlamına gelmez.
