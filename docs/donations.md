# Gönüllü destek

OrderScout aktivasyon anahtarı, abonelik veya lisans sunucusu olmadan çalışır.
Masaüstü araç çubuğundaki **Bana bir kahve al** bölümü tamamen
isteğe bağlıdır; hiçbir özelliği kilitlemez ve kendiliğinden ağ isteği yapmaz.

Bağış platformu olarak Buy Me a Coffee seçilmiştir. Proje sahibinin kişisel hesap
bağlantısı henüz belirlenmediği için varsayılan ödeme adresi boştur. Bu durumda
bağış düğmesi pasiftir; açıklama ve uygulama kullanılmaya devam eder.

Kendi bağış sayfanızı eklemek için:

- Masaüstü: `desktop/settings.py` dosyasındaki `DONATION_URL` varsayılanını
  kişisel bağış bağlantınızla doldurun veya `ORDER_SCOUT_DONATION_URL` ortam
  değişkenini ayarlayın.

Yalnızca geçerli HTTP/HTTPS bağlantıları kabul edilir. Düğmeye basılınca bağış
sayfası tarayıcıda açılır; uygulama ödeme bilgisi veya bağış durumu toplamaz.

Eski lisans tabloları bulunan veritabanlarıyla uyumluluk için mevcut veritabanı
geçiş tanımları korunmuştur. Yeni kurulumlarda lisans tabloları oluşturulmaz;
eski kayıtlar uygulamanın çalışmasını etkilemez.
