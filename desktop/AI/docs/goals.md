# OrderScout AI Domain Hedefleri

> **18 Ekim 2026 mimari yönlendirmesi:** Kullanıcı modelin konuşma, karar ve
> araç seçimi sahibi olmasını yeniden teyit etti; AI altyapısının bu esasa göre
> yeniden kurulmasını istedi. Manuel UI ile AI ortak domain işlemlerini kullanır.
> Her düşük seviye yardımcı fonksiyon bire bir tool yapılmaz; modelin kullanacağı
> tek amaçlı iş yeteneği, domain içinde gerekli atomik işlemleri çağırır.
> Yeni çekirdek ve kalan geçiş:
> [agent_architecture_2026_10_18.md](agent_architecture_2026_10_18.md).

> **16 Ekim 2026 kullanıcı netleştirmesi:** Bir tool'un ihtiyaç duyduğu atomik
> fonksiyon yoksa geliştirme sırasında ilgili domainde oluşturulur ve test edilir;
> sonra AI tool'u bu ortak fonksiyonu kullanır. Mevcut manuel işlem de aynı
> fonksiyona bağlanır. Mevcut tool/fonksiyon envanteri ürünün yapabileceklerinin
> tavanı değildir. Bağlayıcı uygulama sırası bölüm 7.6 ve
> [ortak domain sözleşmesindedir](../../Core/docs/domain_goals_contract.md).

> **8 Ekim 2026 kullanıcı yönlendirmesi:** Codex/ChatGPT Work düzeyinde model bağımsız
> e-ticaret çalışma altyapısının geliştirilmesi ve gerçek cloud testleri yeniden
> yetkilendirildi. Yeni model eğitimi hedef değildir. İstenen test modelleri
> DeepSeek V4.1 Flash ve GLM 5.3 Flash'tır; önceki sabit V4 Flash test rotası bu
> oturumda bunlarla genişletilir. [Güncel çalışma planı](agentic_work_plan_2026_10_08.md)
> kapsamı, açık işleri ve yeni kanıtı takip eder. Ürün kabulü açık; otomatik hedef
> oluşturulmamıştır.

> **7 Ekim 2026 çalışma özeti:** [Güncel durum](current_status.md) ve
> [çalışma ağacı kanıtı](current_working_tree_evidence_2026_10_07.json) ilk okuma
> noktalarıdır. İlk sınırlı düzeltme kümesi typed turn dispatch kararlarının ortak
> sahipliği ve Orders stok maliyeti dövizidir. Tam tur servisi, doğal uzun konuşma,
> provider ve Orders uçtan uca ürün kabulü açık kalır. Tarihsel passing evidence
> güncel kaynağa otomatik taşınmaz; otomatik hedef yeniden açılmamıştır.

> **Belge durumu:** `reference / collaborative_work`
> **Son güncelleme:** 2026-09-22
> **Genel hedef durumu:** `open / foundation_restart / broader_acceptance_pending`
> **İlk referans domain:** Orders
> **Orders durumu:** `open`
> **Ana hedef:** Model, provider ve pazaryeri bağımsız; OrderScout'un manuel e-ticaret
> yeteneklerini aynı domain operasyonları üzerinden kullanan, Codex benzeri gerçek bir
> e-ticaret operasyon agenti oluşturmak.

## Çalışma biçimi — 22 Eylül

Kullanıcı otomatik hedefi kapattı; yeniden açılmayacak. Bu belge ürün yönünü ve
açık kabul şartlarını koruyan referanstır. İşler kullanıcıyla birlikte, sınırlı
değişiklik ve açık sonuç değerlendirmesiyle ilerler. Hedefin kapatılması ürünün
tamamlandığı anlamına gelmez; aşağıdaki tarihsel aktif hedef ifadeleri geçmiş
çalışmaların kayıtlarıdır.

R495–R496: doğal genel değerlendirme → mağaza keşfi geçişinde yeni bir açık bulundu.
Eksik intent_kind, inspect üzerinden tamamlanmadan önce çalışan kapsam denetimini
atlatıyordu. Denetim sırası düzeltildi; açık ve eksik intent için iki test eklendi.
40 odaklı test ve 598 regresyon testi/86 alt kontrol geçti (449 atlandı).
Canlı tekrar, ilk değerlendirmedeki iki model yanıtı kanıt kontrolünden geçmediği
için durduruldu; mağaza geçişinin canlı kabulü hâlâ açık. Model çağrısı süreleri
artık ölçülüyor: son örnekte 75,7 saniyenin yaklaşık75 saniyesi7 model çağrısındaydı.
Bu çalışma hız artışı veya genel AI kabulü değildir. Otomatik hedef kapalı kalır.

R488 ilk adımı: modelin seçtiği focused risk özeti, risk nüfusunun sayı/durum/neden
kanıtını taşır. Eski kelime kuralları bu sözleşmeye tüm siparişlerin count/status
alanlarını ekleyemez veya onu broad_analysis yapamaz. Model ayrıca genel toplam
ve durumları istiyorsa bileşik projection korunur. Bu değişiklik tüm eski kelime
kurallarını kaldırmaz; modelin kapsamı baştan yanlış seçmesi hâlâ ayrı bir risktir.
Güncel kontrol sonuçları completion audit içinde kaydedilir.

R490 açık `metric_population` seçimiyle risk nüfusu ile genel sipariş nüfusunu
ayırır. R491 son kullanıcı mesajının eski hedefe üstünlüğünü prompt'ta açıklar.
Son regresyonda 537 test/86 alt kontrol geçti,449 test atlandı. Gerçek modelde
risk sorusu doğru ve dar yanıtlandı; fakat ardından açıkça tüm siparişler istendiğinde
önceki risk hedefi tekrarlandı. İki turluk kabul bu nedenle failed'dır. Güncel öncelik
yeni mesajın kapsamının karar/plan boyunca korunmasıdır; genel AI kabulü yoktur.

R492–R494 devamında geçmiş hedef tekrarları ilk karar isteminden çıkarıldı;
kapsam ve hesap referansları korundu. Yapılandırılmış yanıttan metin yoluna
geçişte düşen şema, paylaşılan sağlayıcı katmanında korunur. Önceki açık kapsamı
tekrarlayan model kararı, veri okumadan güncel mesajla kısa bir model denetiminden
geçer; çelişki mevcut tek yeniden yorumlama hakkına gider. R494 gerçek iki turda
bu reddi ve onarımı çalıştırarak risk286'dan tüm570 siparişe doğru geçti. Bu dar
kabul geçti; genel AI kabulü değildir.596 test/86 alt kontrol geçti,449 atlandı.
Yanıtlar39.656/44.359 saniye sürdü. Diğer kapsam değişimleri, diğer domainler,
teknik dil ve gecikme açık; otomatik hedef kapalı kalır.

## 0. Güncel Öncelik — 6 Eylül Kullanıcı Hatasından Yeniden Denetim

Kullanıcı AI mimarisinin baştan incelenmesini açıkça istedi. Güncel bağlayıcı
başlangıç noktası `orders_ai_foundation_restart_2026_09_06.json` içindeki gerçek
konuşmadır: "siparişlerim nasıl sence iyi mi" sorusuna AI veri okumadan yerel
sipariş kaydı olmadığını söyledi; kullanıcı ayrıca kayıtlı mağaza olmadığının
söylendiğini bildirdi. Doğrudan yerel okumada 570 sipariş ve aktif Stage seller
2738 hesabı vardır. Sonradan kullanıcının istediği senkronizasyon ayrı bir lisans
hatasına takılmıştır. Bu lisans hatası, mevcut yerel kayıtların yok sayılmasını
açıklamaz. İlk turların ham model kararı saklanmadığı için model/normalizer
sorumluluğu yalnız sohbet metninden kesin atanamaz.

Bu hata kapanmadan önceki focused sonuçlar genel AI yeterliliği sayılmaz.
R461 dört turluk hesap kabulü tarihsel ve sınırlıdır; R462 organik kampanyası
başarısızdır; R463 kapsam/projeksiyon değişikliği henüz fresh canlı kabul almadı.
İnceleme mevcut çalışma ağacını korur ve şu sırayla ilerler:

1. Gerçek source-app yolunda kullanıcı başlangıç sorularını fresh oturumda yeniden
   üret; ham model kararı, kabul edilen karar, tool çağrısı ve final cevabı ayır.
2. İlk kararın chat/explain veya clarification olmasıyla veri araçlarının tamamen
   erişilemez hale geldiği ayrımı incele. R464 fresh source-app koşusunda ilk soru,
   sıfır okuma ile `chat/orders/conversation + requires_clarification=true` kabul
   edilip "Henüz sipariş verileriniz yok" cevabını üretmiştir; koşu ilk turda failed
   kapatılmıştır. İşletme kaydı gerektiren doğal sorular aynı model-led
   observe/act/verify döngüsüne girmeli; kullanıcının tool adı veya özel komut
   söylemesine ihtiyaç olmamalı.
3. `unknown/not_read`, doğrulanmış `empty`, erişim hatası, eksik hesap kapsamı ve
   eski snapshot ayrı durumlar olmalı. Sohbet hafızasının boş olması DB'nin boş
   olduğuna kanıt değildir. Kayıt yokluğu, mağaza yokluğu ve erişim yeteneği
   hakkında da olumlu sonuçlar kadar authoritative kanıt aranmalı.
   Netleştirme yalnız araçlarla bulunamayacak zorunlu kullanıcı kararını istemeli;
   ham model netleştirme metni veri yokluğu veya erişim iddiası olarak yayımlanamaz.
   Ham/kabul edilen kararın güvenli enum özeti ve yanıt hash'i tanıda tutulmalıdır.
   R465 ilk soruda gerçek 570 siparişi ve ürün dağılımını okudu; ancak kıyas kanıtı
   olmadan "performans ortalama" hükmü verdiği için yine failed kapandı. Sayısal
   projection kontrolü nitel değerlendirmeyi tek başına doğrulayamaz. Genel analiz
   yanıtında benchmark, neden, trend, ortam ve yokluk iddiaları ayrıca denetlenir;
   desteklenmeyen yorum aynı modelle düzeltilir, düzelmezse yalnız doğrulanmış
   veriler sunulur. Stage/test gözlemi canlı işletme performansı gibi sunulamaz.
4. Yerel okuma, dış API senkronizasyonu ve onaylı etki birbirinden ayrılmalı.
   Yerel veriyi inceleme talebi otomatik sync zorunluluğu üretmemeli. Lisans veya
   provider hatası doğru adıyla raporlanmalı; engel aşılmamalı veya yok sayılmamalı.
5. Orders ve mağaza/hesap keşfi aynı doğal sohbet içinde kanıtlandıktan sonra
   mevcut kapsam, hesap, onay, artifact ve web kapanış şartlarına dön.
   R466/R467 mağaza sorusu, doğru görünen tek bir adın tam kayıtlı hesap evrenini
   kanıtlamadığını gösterdi. Kayıtlı mağazalar `marketplace_account` nüfusudur;
   siparişlerde görülen mağazalar ayrı bir ilişkili nüfustur. Siparişi olmayan
   hesaplar ilkinden düşemez. Bu ayrım modelin typed sözleşmesinde kalmalı.
6. Typed sözleşmenin gerektirdiği araç yalnız kelime eşleşmesi zayıf diye modelin
   aday kataloğundan düşemez. R467'de hesap aracı kayıtlı olduğu halde retrieval
   dışında kaldı; kaynak doğrulayıcısı yanlış planı reddedince eski template akışı
   tekrar çalıştı. Reddedilen plan aynı modelle bir kez düzeltilir; reddin ardından
   eski planla çalışma veya başarısız projection'ı başarılı cevap gibi sunma yoktur.
7. Pazaryerinin açık durum kodu ile uygulamanın birleşik iş kuyruğu aynı metrik
   değildir. R468 ilk iki kullanıcı sorusunu doğru kaynak ve Stage kapsamıyla
   yanıtladı; üçüncü turda `ReadyToShip` kodu ile daha geniş hazır kuyruğunun
   metrik şartları çeliştiği için sayı üretmeden durdu. Açık filtreli sayım,
   Orders'ın `orders.filtered_count` metriği ve kanıtlı `orders.query` sonucu
   üzerinden doğrulanır. Filtre kodları modelden korunur; kelimeye özel durum
   listesi veya örtük kapsam genişletmesi eklenmez.
8. Planlama ve düzeltme çağrısı, doğrulayıcıyla aynı typed kanıt sözleşmesini
   görmeli. R470'te yorumlayıcı doğru 48 kayıtlık kapsamı korudu; ancak model ve
   düzeltmesi iki kez geniş hazır kuyruğunu seçti. Gerekli tam bağlam aracı katalogda
   vardı fakat sonuç alanları boştu; doğrulayıcının beklediği okuma araçları düzeltme
   mesajından düşüyordu. Ortak `ReadEvidenceContract` ilk/onarım planında aynı
   kaynak şartlarını ve exact filtreyi gösterir; lexical retrieval gerekli aracı
   gizleyemez. Sonuç şeması canonical operation'ın gerçek çıktısıyla uyuşur.
   Runtime bu bilgilerden business plan üretmez; modelin step/argüman/bağımlılık
   kararını denetler. Yanlış planı güvenle reddetmek, kullanıcı işini tamamlamak
   yerine geçmez; fresh gerçek model kabulü yeniden gerekir.
9. Görünür liste, alanların yanıtın herhangi bir yerinde bulunmasıyla doğrulanamaz.
   Her ürün/kargo ve diğer detay kendi sipariş satırına veya açık kimlikli bölümüne
   bağlı olmalı; model kanıtı ve deterministic projection aynı satır ilişkisini
   taşımalıdır. R471 doğru 48/48 kaydı okuduğu halde yedek cevap kimlik listesini
   48 adsız detay bloğundan ayırdı ve sıra numaralarını atladı. Bu cevap geçerli
   projection sayılmaz. Sıra numarası ayrı bir sunum alanıdır: Markdown liste/tablo
   sıra değerleri iş metriği değildir; aynı sayı başka bir veri hücresinde geçerse
   hâlâ kanıt gerektirir. Kontrol global sayı muafiyetiyle yapılamaz. Aday yanıtın
   içerik hash'i ve yapısal sıra sayıları kişisel veri taşımadan tanıda tutulur.
10. Operation değişikliği, o operation'ın argüman ve sonuç sözleşmesiyle birlikte
    model tarafından yapılmalı. R472'de onarım doğru tam bağlam aracını seçti,
    fakat önceki query aracının `mode` parametresini taşıdığı için yine reddedildi.
    Şema hatası yalnız step kimliğine indirgenemez: alan yolu ve ret nedeni hem
    tanıda hem tek model onarımında korunmalı. Bilinmeyen argümanı sessizce silmek
    veya başarısız model planının yerine iş planı üretmek çözüm değildir. R472 tam
    liste kabulü failed'dır; R473'ün aşağıdaki yeni kabulü bu başarısız kaydı silmez.
11. Gruplanmış satır metriklerinin kapsamı, mağaza toplamı ve sipariş kalemi
    detayından ayrıdır. R475 organik koşusunda ürün başına adet/sipariş sayısı
    isteğini normalizer global `orders.total_count` şartına çevirdi; doğru ilk
    model planını reddetti ve ürün cevabından gereksiz detay/tutar kanıtı istedi.
    Koşu ikinci turda failed kapatıldı. Model-authored `grouped_projection`, grup
    boyutunu, istenen sütunları ve satır sınırını birlikte taşır. Plan doğrulaması,
    görünür cevap ve yedek projection aynı sözleşmeyi kullanmalı; adet ve sipariş
    sayısı satır içinde de yer değiştirememeli. Kelime eşleşmesi bu metrikleri
    yeniden adlandıramaz. R476 bu ortak sınırı ekler; fresh canlı kabul gerektirir.
    Typed veri okuma turunda yedek yanıt da doğrulanamıyorsa ham/yedek sonuç
    yayımlanamaz. Yanıt başarısızlığı state'e işlenir; bu kural yalnız mağaza veya
    exact-status örnekleriyle sınırlı değildir.
12. Genel değerlendirmede kullanılan destekleyici ürün istatistikleri, kullanıcının
    ürünleri tek tek listeleme talebi değildir. R476 canlı ilk turda model gereksiz
    `grouped_projection.limit=100` üreterek genel analizi 22 satırlık zorunlu listeye
    çevirdi; yanıt doğrulanamadı ve güvenli biçimde bastırıldı. Koşu failed kapandı.
    R477 grup sözleşmesinde açık `null` durumunu ve yalnız istenen liste için
    sütun/sınır üretme kuralını tanımlar. Genel analizin kapsamı korunmalı; modelin
    uydurduğu çıktı yükümlülüğü başarılı yorumlama sayılmaz. R477 fresh iki turluk
    sınırlı kontrolde genel analiz kapsamı korundu; takipte ilk beş ürünün adet ve
    sipariş sayısı doğru model yanıtıyla gösterildi. İlk turda modelin nitel yorumu
    reddedilip doğrulanmış özet kullanıldı. Bu sonuç 50+ organik kabulün yerine
    geçmez; yorum güvenilirliği, gecikme ve diğer domainler açıktır.
13. Önceki typed hedef yeni isteğin domain/varlık değişimini engelleyemez. R478
    organik koşusunda genel analiz geçti, fakat hangi mağazaya ait olduğu ve başka
    kayıtlı mağaza bulunup bulunmadığı sorusu sıfır okuma ile gereksiz `missing_input=goal`
    sorusuna dönüştü. Belirli bir veri okuması ve çıktı alanları tanımlayan kararın
    aynı anda hedef yok demesi çelişkidir; aynı modelle yeniden yorumlanmalıdır.
    Yeni açıklama turu önceki iş yanıtının doğrulama kaydını taşıyamaz. R479 bu
    sınırları ortak karar/konuşma sahiplerinde uygular; önceki kanıtlar ve onaylar
    korunur, fakat eski projection yeni cevaba kabul kanıtı olamaz.
    R479 sınırlı canlı tekrarda genel analiz ve bağlamsal hesap keşfi geçti;
    hesap sorusunda model eksik hedef kaydı kararını bir kez onardı. Yeni
    `missing_input=goal` çelişki kontrolü ve eski yanıt kanıtı sınırı regresyonla
    doğrulandı; bu canlı turda o iki dal doğrudan çalışmadı. Fresh 50+ kabul açıktır.
14. Bir metriğin anlamını sormak hesap istemek değildir. R480 organik koşusu
    selamlaşma, mağaza keşfi ve bağlamsal sipariş analizini geçti; 286 riskli kaydın
    gerekçesini soran dördüncü turda formülsüz `calculation/ratio` sözleşmesi kabul
    edildi ve cevap üretilemedi. R481 formülsüz hesap projection'ını aynı modelin
    yeniden yorumlamasına gönderir. Risk sayımı, canonical Orders sahibinden tüm
    risk evreninin durum/neden dağılımını ve kullanılan kuralları da taşımalıdır.
    Sipariş tarihinden itibaren yaş eşiği, mevcut durumda bekleme süresi veya gerçek
    teslimat gecikmesi kanıtı değildir. Liste sınırı toplam risk dağılımını daraltamaz.
    R481 canlı tekrarı risk açıklamasını genel tazelik politikasına çevirdi ve
    modelin istediği iş verisi alanlarını sildi; ikinci tur failed kapandı.
    R482 politika etiketiyle iş projection'ı arasındaki çelişkiyi, alanları silmeden
    ve politika alt denetimine para harcamadan önce aynı modele geri gönderir.
    R482 canlı ilk turda sayılar doğruyken sipariş yaşı, kuyrukta bekleme süresi
    diye sunuldu. Risk projection'ı focused olsa da nitel anlam denetiminden geçer;
    zaman başlangıcı ve ölçülmeyen gecikme kesin sonuç gibi değiştirilemez.
    R483 ayrıca ilk yorum onarımının sonraki model alt çağrılarını aynı onarım
    prompt/şemasına zorlayan ara istemciyi kaldırır. Yalnız ilk yorumun prompt'u
    değişir; sonraki topic/formül denetimleri kendi gerçek istemci ve şemalarını kullanır.
    R483 canlı takipte iki model kararı da reddedilince eski canonical hazır okuma
    planı devreye girdi ve semantic verifier tarafından reddedildi. R484 bu yorum
    başarısızlığı yolundan otomatik okuma/prepare planı üretimini çıkarır. Tek model
    onarımı da başarısızsa typed hata döner; bu güvenli duruş kullanıcı işinin
    tamamlandığı anlamına gelmez. Risk açıklamasının fresh canlı kabulü hâlâ açıktır.
    R484 fresh takipte onarım ve bağımsız politika denetimi doğru çalıştı, ancak
    model iş alanlarını boşaltıp yine tazelik politikasına yöneldi. Şematik tutarlılık
    doğru kullanıcı anlamını kanıtlamaz. Gözlenen metriğin gerekçesi ile runtime
    politikası ayrımı hâlâ açıktır; bu failed sonuç önceki dar geçişleri geçersiz
    kılmaz, fakat risk açıklaması veya genel AI kapanışı kanıtı sayılamaz.
    R485 karar şeması ve prompt'undaki geniş kavram/politika eşlemesini iş metriği
    açıklamasından ayırdı; 596 test geçti. Ancak canlı ilk turda aynı modelin anlam
    denetimi de yanlış kuyruk süresi iddiasını kabul etti. Bu denetim kusursuz değildir.
    R486 canonical risk nedenini `order_age_over_threshold_while_ready` olarak
    adlandırır ve `orderDate` ölçüm başlangıcını typed kanıtta açıkça taşır. Eski ad
    kuyrukta bekleme izlenimi veriyordu. Hesap kuralı değişmez; güncel üretilen neden
    kodu değişir, tarihsel kanıtlar yeniden yazılmaz.
    R486 bu canonical `ORDER_` neden kodunu sipariş kimliği gibi reddetti; doğru
    sayısal yedek cevap açıklama kabulü değildir. R487 açık gözlenen `reason_codes`
    listesini taşır ve yalnız istenen risk kanıtındaki bu public kodları tanır.
    Herhangi bir observation metninde geçen kimlik genel muafiyet kazanamaz.
    R487 iki turluk fresh canlı kontrolde risk sayısını ve gerekçesini doğru açıkladı:
    286=238 Picking+48 ReadyToShip; eşik sipariş tarihinden ölçülür, gerçek gecikme
    tespiti değildir. Bu yalnız anlam doğruluğu için dar kanıttır. Gereksiz 570/toplam
    durum dökümü zorunluluğu, teknik başlık ve yinelenen Stage notu hâlâ açıktır.
    R487 regresyonu 596 test/95 alt kontrol geçti; 50+ organik kabul yerine geçmez.

Yeniden denetimin kalan işleri: bu kapıların diğer domain ve eski yürütme yollarında
aynı sahipten uygulanması, sohbet/karar geçmişinin tam kalıcılığı, kayıt yokluğu ve
erişim iddialarının bütün final yollarında denetimi, çapraz domain kapsam sürekliliği
ve yanıt gecikmesi. Nitel anlam denetiminde kullanılan ikinci model kararı tek başına
kusursuzluk kanıtı değildir; fresh insan değerlendirmesi şartı sürer. Geniş ek test
taramasında görülen depo doğrulama hatası, testin yazıcı ve doğrulayıcıyı farklı
veritabanlarına bağlamasından kaynaklandı; aynı izole DB ile mevcut kontroller geçti.
Bu, Stock ürün kabulü değildir. İade capability eşleştirmesinin Testing operasyonunu
öne alması hâlâ açıktır; genel AI hazır kararı verilemez.

Bu çalışma yeni regex/kelime istisnalarıyla iki örnek cümleyi ezberletmek olarak
tamamlanamaz. Düzeltmeler paylaşılan sahiplerde yapılmalı; yazım hataları,
itirazlar, genel değerlendirme soruları ve farklı domainlerdeki eşdeğer istekler
aynı sözleşmeyle çalışmalıdır. Yeni provider veya alternatif runtime eklemek
mevcut akışın doğruluğunu kanıtlamanın yerine geçmez.

İlk kabul kapısı: gerçek UI'da "siparişlerim nasıl", "hangi mağazalar var" ve
bağlamsal bir takip sorusu mevcut yerel veriyi okuyarak yanıtlanır; veri yokluğu
uydurulmaz, gereksiz sync/onay açılmaz, gerçekten boş veri ve gerçek okuma
hataları doğru ayrılır. Bu kapıdan sonra fresh 50+ organik kabul yine zorunludur.

R469 fresh source-app koşusunda üç doğal tur bu kapının mevcut verili örneğini
geçti: 570 siparişin kanıtlı değerlendirmesi, hesap deposundan kayıtlı Stage mağaza
keşfi ve aynı mağazanın açık `ReadyToShip` filtresiyle 48 siparişinin sayımı.
Model fallback kullanılmadı; her tam cevap okunarak sonraki soru seçildi.
Boş/hatalı hesap okumalarının ayrımı ayrıca izole testlerde doğrulandı. Bu sonuç
çok hesaplı veri, tüm domainler veya 50+ organik kabul yerine geçmez. İlk yanıtın
iki dakikayı aşması nedeniyle gecikme de açık kabul başlığıdır. Ayrıntılı kanıt ve
test kapsamı yeniden denetim artifact'ında tutulur.

R473 fresh kaynak uygulama koşusu ayrıca tam liste kapısını iki okunmuş turda geçti:
570 siparişlik Stage özeti ve exact `ReadyToShip` filtresindeki 48 sipariş. Bağımsız
yerel okumayla aynı 48 kimlik, 48 sıra numarası, doğru siparişlere bağlı 67 ürün
kalemi ve tüm kargo firmaları eşleşti. Liste modelin doğrulanmış cevabıdır; planını
model bir kez düzelterek doğru aracı seçti. Bu focused kabul, 50+ organik kampanyaya
tur taşımaz; eski yürütme yolları, çok hesaplı kapsam ve diğer kapanış şartları açıktır.

AI sekmesi kaynak geliştirme/test çalışmasında görünürdür; paketlenmiş release
sürümünde varsayılan gizlidir. Bu, kullanıcının açık görünürlük kararıdır; UI
yeniden tasarımı için Faz 9 şartını değiştirmez.

## 1. Bu Belgenin Görevi

Bu dosya AI domaininin uzun vadeli ürün ve mühendislik sözleşmesidir. Bir geliştirme
hedefi açıldığında:

- Neyi inşa ettiğimizi,
- Hangi mimari sınırların değişmez olduğunu,
- Çalışmanın hangi sırayla ilerleyeceğini,
- Hangi testlerin ve gerçek kullanıcı davranışlarının bağlayıcı olduğunu,
- Bir alanın ne zaman gerçekten tamamlanmış sayılacağını

belirler.

Bu belge bir başarı günlüğü veya test çıktısı deposu değildir. Uzun transcript'ler,
hash'ler, ekran görüntüleri ve ayrıntılı test raporları ayrı redacted evidence
artifact'larında tutulur. Burada yalnız kalıcı ürün ilkeleri, güncel gerçek durum,
sistemik regresyonlar ve ölçülebilir kapanış şartları bulunur.

En yeni gerçek kullanıcı başarısızlığı, kendisinden eski bütün `passed`, `ready` veya
`verified` artifact'larından daha yüksek önceliklidir. Eski kanıt yeni hatayı geçersiz
kılamaz.

Ham API key, secret, token, entegrasyon kodu veya müşteri PII'si bu dosyaya yazılamaz.

## 2. Ürün Vizyonu: E-Ticaret İçin Codex

OrderScout AI bir chatbot, komut paleti, regex router veya tek tool seçme ekranı
değildir. Kullanıcının doğal dilde verdiği e-ticaret hedefini sonuca ulaştıran bir
operasyon agentidir.

Kullanıcı örneğin:

- "Bekleyen siparişleri bul, en çok gelen ürünleri söyle."
- "Bu siparişleri TANEX 2610'a hazırla."
- "Şu siparişin kargosunu Aras yap."
- "Bekleyen iadeler hangi mağazada ve neden bekliyor?"
- "Önce veriyi yenile, sonra değişen siparişleri analiz et."

dediğinde agent yalnız bir tool çağırıp durmaz. Hedefi anlar, gerekli authoritative
veriyi toplar, seçimleri korur, bir veya birden fazla atomic tool'u sırayla kullanır,
sonuçları gözlemler, gerektiğinde planını değiştirir, riskli adımda kullanıcıya kontrol
verir ve işi gerçekten doğrular.

Nihai kullanıcı hissi:

> "Programdaki manuel işlemleri bilen; işletmemin, konuşmanın ve seçtiğim kayıtların
> bağlamını koruyan; yanlış kayıtta işlem yapmayan; gerektiğinde kendi planını kurup
> ilerleten ve bitirdiğini kanıtlayan bir operasyon ortağıyla çalışıyorum."

## 3. Güncel Kök Teşhis ve Yön Değişikliği

2026-07-18 ve 2026-07-19 tarihli gerçek kullanıcı konuşmaları güçlü
`deepseek/deepseek-v4-pro` ve `deepseek/deepseek-v4-flash` modellerinde dahi temel
manuel işlerin güvenilir biçimde yapılamadığını göstermiştir. Bu hata "daha güçlü model
gerekli" veya "tool sayısı az" diye açıklanamaz.

### 3.1. Mevcut yanlış çalışma biçimi

Mevcut runtime'ın kritik bölümü fiilen şu şekildedir:

```text
Kullanıcı mesajı
-> Python regex / intent override
-> tek tool seçimi
-> tek tool sonucu
-> cevap
```

Bu yapıdaki sistemik kusurlar:

- İş niyetini model değerlendirmeden önce regex/keyword kuralları tool seçebiliyor.
- Ekranda güçlü model adı görünse bile bazı kritik turlarda model hiç çağrılmıyor.
- Aynı cargo, label ve follow-up kuralları büyük agent dosyasında birden fazla yerde
  tekrarlandığı için kurallar birbirini eziyor ve DRY bozuluyor.
- Genel `operations.manual_action.route` doğal dili çok sayıda manuel capability
  arasında fuzzy eşleştiriyor; sipariş kargosu değiştirme isteğini lojistik sağlayıcısı
  kaydı oluşturma gibi semantik olarak farklı bir işe çevirebiliyor.
- Basit tek turlu işler one-shot router'dan, yalnız belirli kalıplara uyan işler task
  runtime'dan geçiyor. Tek ve tutarlı bir agent çalışma döngüsü yok.
- Task runtime çoğunlukla önceden tanımlanmış step şablonlarını yürütüyor; her
  observation sonrasında modelin hedefe göre yeniden planladığı gerçek bir döngü değil.
- Ham sohbet metni kayıt ve action state'inin kaynağı olarak taranıyor. İptal edilmiş,
  supersede edilmiş veya ilgisiz eski seçimler yeniden canlanabiliyor.
- Açıklama, varsayım, itiraz, düzeltme ve gerçek action isteği birbirinden güvenilir
  biçimde ayrılmıyor.
- Prepare'ın kendi payload'ıyla tutarlı olması yeterli sayılıyor; hazırlanan işlemin
  kullanıcının gerçek amacı, domaini ve hedef kaydıyla semantik eşleşmesi bağımsız
  doğrulanmıyor.
- Tool contract testleri ve belirli cümlelere göre yazılmış regresyonlar yeşil olsa da
  organik sohbet başarısız olabiliyor.

### 3.2. Bağlayıcı sonuç

Sorunun ana kaynağı model değil, agentic control plane'dir:

```text
intent/mode interpretation
+ typed state
+ dynamic planning loop
+ atomic tools
+ observation
+ replanning
+ policy/approval
+ semantic verification
+ authoritative read-back
= gerçek agent
```

Bu nedenle yeni hedefte regex yaması eklemek, fuzzy router'ı genişletmek veya yalnız
daha güçlü model kullanmak çözüm kabul edilmez. Önce ortak agent runtime mimarisi
düzeltilir. Orders bu yeni mimarinin ilk uçtan uca kanıtıdır.

## 4. Değişmez Ürün İlkeleri

### 4.1. Model planlar; deterministik katman sınırlar ve doğrular

LLM doğal niyeti, konuşma modunu ve hedefe ulaşmak için atılacak adımları yorumlar.
Deterministik kod:

- Input/output şemasını,
- RecordRef ve selection bütünlüğünü,
- Risk ve yetki politikasını,
- Environment/account kapsamını,
- Approval kimliğini,
- Idempotency, freshness ve verification invariant'larını

uygular.

Deterministik katman normal iş akışında doğal dildeki semantik niyeti modelin yerine
uyduramaz, farklı bir domain action seçemez veya yalnız keyword gördüğü için prepare
başlatamaz. Yalnız açık protokol komutları (`approve(action_id)`, `cancel(action_id)`),
şema doğrulama ve güvenlik kapıları deterministic fast-path olabilir.

### 4.2. Doğruluk model zekâsına bırakılamaz

Model kimlik, sayı, tarih, durum, tutar, kapsam veya işlem sonucu uyduramaz. Bunlar
authoritative observation ve typed state'ten gelir. Model yanlış plan üretirse sistem
yanlış kayıtta prepare veya execute yapmamalıdır.

### 4.3. Agent tool seçiminden değil sonuçtan sorumludur

Başarı "doğru tool adı seçildi" değildir. Kullanıcının hedefi doğru kayıtlarda,
doğru kapsamda, doğru etkiyle tamamlanmış ve bağımsız biçimde doğrulanmış olmalıdır.

### 4.4. Doğal sohbet ve çalışma modları korunur

Her mesaj action değildir. Her tur önce aşağıdaki konuşma modlarından biri veya güvenli
bir birleşimi olarak çözülür:

- `chat`: gündelik sohbet veya görüş
- `explain`: geçmiş olayın nedenini açıklama
- `inspect`: authoritative veri inceleme
- `act`: gerçek işlem talebi
- `approve`: belirli pending action'ı onaylama
- `cancel`: belirli pending action'dan vazgeçme
- `correct`: önceki kapsamı, cevabı veya işlemi düzeltme

Varsayımsal "yazdır desem ne sorardın?" sorusu prepare başlatamaz. "Neden az önce
olmadı?" sorusu aynı işlemi yeniden hazırlayamaz. Kullanıcı itirazı önceki action'ın
güvenini askıya alır ve recovery başlatır.

### 4.5. DRY ve domain sahipliği zorunludur

Manuel UI ile agent aynı domain application service/action fonksiyonunu kullanır. AI,
Orders veya başka bir domainin iş mantığını yeniden yazmaz. Başka yerde de gerçekten
kullanılan stabil ve domain bağımsız primitive Core'a alınır; domain anlamı taşıyan
kod sahibi domainde kalır.

### 4.6. Provider/model özgürlüğü esastır

Domain tool'ları ve agent state'i hiçbir provider'a göre şekillenmez. Cloud veya local,
ücretsiz veya ücretli her model aynı typed contract, policy ve verifier arkasında
çalışır. Model yeteneği yetmiyorsa güvenlik gevşetilmez; capability açıkça daraltılır.

### 4.7. UI uygulamanın doğal parçasıdır

AI yüzeyi mevcut OrderScout shell, Core workspace scaffold, theme token, ikon ve
component dilini kullanır. AI için bağımsız ikinci bir uygulama veya CRUD sistemi
kurulamaz.

## 5. Mimari Sahiplik

### 5.1. Core

Core yalnız birden fazla domainde kullanılan ortak primitives'lerin sahibidir:

- Workspace/record scaffold
- `RecordRef`, `SelectionSnapshot` ve ortak source identity primitives
- Operation metadata/result envelope
- Pending action yaşam döngüsü için domain bağımsız primitives
- Environment, credential reference, redaction ve audit
- Ortak async, cancellation, progress ve event-store primitives
- Gerçekten genellenmiş UI bileşenleri

### 5.2. İş domainleri

Orders, Returns, Labels, Stock, Listing, Finance, Logistics, Marketplaces ve diğer
domainler şunların tek sahibidir:

- Query ve mutation iş kuralları
- Validasyon ve veri dönüşümü
- Domain modelleri/repository'leri
- Atomic read, aggregate, prepare, execute ve verify operasyonları
- Marketplace'e taşınacak domain payload'ı

UI içinde gömülü olup agent tarafından kullanılacak davranış önce sahibi domainde
UI'dan bağımsız, test edilebilir bir operasyona dönüştürülür.

### 5.3. Marketplaces

Marketplaces şunların sahibidir:

- Platform-independent marketplace contract
- Trendyol ve gelecekteki adapter'lar
- Production/stage endpoint routing
- Auth, User-Agent, rate limit, retry ve error normalization
- Platform operation/capability katalogları

AI kodu Trendyol URL'si, Basic Auth biçimi veya ham platform payload ayrıntısı bilmez.

### 5.4. AI

AI domaini şunların sahibidir:

- Conversation mode ve objective interpretation
- Provider/model adapter orchestration
- Capability negotiation ve tool retrieval
- Typed conversation/selection/task/action state
- Dinamik plan -> act -> observe -> verify -> replan döngüsü
- Approval koordinasyonu
- Response projection, privacy ve grounded synthesis
- Chat/Model Hub çalışma yüzeyi
- Canlı LLM test ve redacted evidence üretimi

## 6. Gerçek Agent Runtime Sözleşmesi

### 6.1. Tek ve birleşik çalışma döngüsü

Basit ve çok adımlı işler ayrı zekâ yollarına bölünmez. Aynı runtime tek adımlı hedefi
bir adımda, karmaşık hedefi gerektiği kadar adımda tamamlar:

```text
Kullanıcı amacı ve mode
-> typed state'i yükle
-> ilgili operation/tool adaylarını getir
-> model planı veya bir sonraki adımı seçer
-> schema/policy doğrulaması
-> bir atomic tool çalıştır
-> observation üret ve state'e yaz
-> semantic verifier sonucu değerlendirir
-> hedef bitmediyse model yeni observation ile yeniden planlar
-> mutation gerekiyorsa immutable proposal üret ve kullanıcı onayında bekle
-> onaydan sonra execute et
-> authoritative read-back ile doğrula
-> hedef tamamlanana, netleştirme gerekene veya gerçek engel oluşana kadar sürdür
```

Runtime'ın zorunlu davranışları:

- Her tool sonucundan sonra hedef durumu yeniden değerlendirilir.
- Tool hatası otomatik olarak final cevap değildir; güvenli retry, alternatif read,
  kapsam daraltma veya clarification seçenekleri planlanır.
- Model aynı mesaj içinde veya takip turlarında birden fazla tool'u compose edebilir.
- Uzun görev planı gözlemlere göre değişebilir; yalnız sabit step template çalıştırılmaz.
- Pending approval çalışma döngüsünü güvenli checkpoint'te durdurur.
- İptal veya düzeltme eski plan/action'ı açıkça supersede eder.
- Gizli chain-of-thought saklanmaz; yalnız güvenli plan özeti, tool/observation ve
  karar kanıtı tutulur.

### 6.2. Intent override yasağı

Normal iş niyetlerinde regex/keyword katmanı modelden önce kesin tool seçemez.

İzin verilen deterministic işler:

- Exact kimlik ve açık filtre token'larını güvenli biçimde çıkarmak
- Explicit action ID'li onay/iptal protokolünü doğrulamak
- No-write, environment ve risk politikasını uygulamak
- Şema ve invariants kontrolü
- Secret/PII redaction

Yasak örnekler:

- Mesajda "yazdır" geçti diye `labels.create...prepare` çağırmak
- "kargo firması değiştir" geçti diye sipariş bağlamını görmeden Logistics action seçmek
- "neden/niye" içeren takip mesajını önceki action'ın tekrar denemesi saymak
- Geçmişteki ilk/son bulunan sipariş numarasını aktif hedef kabul etmek

Her business turn evidence'ı `planner_invoked`, seçilen mode, candidate operations,
modelin seçtiği operation ve policy/verifier kararını ayrı göstermelidir. Modelin
çağrılmadığı protokol fast-path'leri açık reason code taşır.

### 6.2.1. Modelin yerine plan kuran deterministic recovery yasağı

Provider çıktısını doğrulamak ile modelin yapamadığı agentic işi onun yerine yapmak aynı
şey değildir. Deterministik katman:

- Şema lehçesini çevirebilir, enum/kimlik/tarih biçimini normalize edebilir,
- Aynı semantik niyet içindeki canonical operation adını resolve edebilir,
- Scope, eligibility, privacy, approval ve güvenlik invariant'larını uygulayabilir,
- Authoritative observation'dan istenen exact alanı güvenli biçimde project edebilir.

Ancak modelin seçmediği business hedefini, kayıt kümesini, domaini veya çok adımlı planı
`semantic compiler`, keyword, template ya da compatibility fallback adı altında icat
edemez. Eksik veya çelişkili model kararı semantik olarak yeni bir karar gerektiriyorsa
model observation ile yeniden çağrılır; bu mümkün değilse sistem fail-closed clarification
üretir. Deterministik recovery yalnız aynı doğrulanmış typed contract'ın kayıpsız ve
semantik olarak eşdeğer temsiline izin verir.

Modelin semantic karar alanı ile katalog sahibinin metadata alanı birbirine
karıştırılamaz. Modelden canonical `operation_id`, kullanıcı hedefi ve o operation'ın
typed business argümanları istenir. `operation_domain`, owner, risk sınıfı, contract
sürümü, approval policy ve benzeri canonical katalogdan kesin olarak türetilebilen
metadata modelin tekrar yazması gereken bir zekâ sınavı değildir. Exact ve izinli
`operation_id` ile semantik olarak doğru typed argümanlar üretildiğinde bu tür redundant
metadata'nın eksikliği planı reddetme veya modeli eski/yanlış plana zorlayan repair
gerekçesi olamaz; runtime metadata'yı authoritative operation catalog'dan bağlar. Modelin
gönderdiği redundant metadata authoritative katalogla çelişirse ona güvenilmez ve bu
uyumsuzluk açık provenance ile raporlanır. Modelin seçmediği operation, hedef kayıt kümesi
veya business argümanı ise bu kuralla hiçbir zaman tamamlanamaz.

Gerçek agentic kanıtta model yalnız ilk tool adını seçmiş sayılmaz. Her anlamlı observation
sonrasında hedefin tamamlanıp tamamlanmadığını, sonraki atomic adımı veya plan değişikliğini
model değerlendirir. Sabit bir Python step listesi model kararı gibi raporlanamaz.

### 6.3. Tool discovery ve retrieval

Bütün capability'leri her prompt'a yığmak veya doğal dili 176 manuel capability
arasında fuzzy eşleştirmek kabul edilmez.

Operation catalog metadata'sı üzerinden:

1. Aktif domain, objective, record type, mode ve risk düzeyine göre adaylar getirilir.
2. Modele yalnız ilgili ve yönetilebilir aday kümesi verilir.
3. Model bir operation seçebilir, ek bilgi isteyebilir veya toolsuz cevap verebilir.
4. Seçim schema, scope, capability ve semantic verifier'dan geçer.

`operations.manual_action.route` ve benzeri generic fuzzy router'lar normal production
planner'ın ana kapısı olamaz. Geçiş döneminde yalnız açık compatibility/diagnostic
amaçla kullanılabilir ve doğrudan mutation proposal üretemez.

Retrieval bir business kararı değil, modele gösterilecek aday yüzeyidir. Türkçe çekimler
ve eş anlamlılar (`çek/fetch`, `kaydet/save`, `yenile/sync`, `detay/bağlam/full_context`,
`sayı/count`) provider'dan bağımsız genel metadata katmanında normalize edilir; belirli
bir kullanıcı cümlesini doğrudan tool'a zorlayan router yazılmaz. Alias genişletmesi
yalnız kullanıcı sorgusuna uygulanır. Catalog tarafına çift yönlü alias yayarak aynı
ismi paylaşan kardeş operasyonların birbirinin fiillerini devralması (örneğin label
`mark` operasyonunun label `create/print` gibi görünmesi) yasaktır. Canlı kabulde yalnız
modelin seçtiği operation geçerlidir; retrieval'ın doğru operation'ı ilk adaylara getirmesi
tek başına plan başarısı sayılamaz.

Correction/follow-up retrieval yalnız yeni ham cümleye indirgenemez. Kullanıcı “11 tane
var”, “2736 değil 2610” veya “onun yerine bunu yap” dediğinde typed semantic contract,
active selection ve active/superseded target operation metadata'sı privacy-safe retrieval
hint olarak aday sorgusuna eklenebilir. Bu enrichment operation seçmez ve argüman yazmaz;
yalnız konuşmada tekrar edilmeyen fakat typed state'te authoritative olarak bulunan bağlam
yüzünden doğru canonical capability'nin aday kümesinden düşmesini engeller. Son operation
ve business argüman kararı yine model-authored planda görünür.

## 7. Atomic Tool ve Operation Sözleşmesi

### 7.1. Atomic ne demektir?

Atomic operation tek, açık ve birleşebilir bir iş niyetini temsil eder. Atomic olmak
az parametre almak demek değildir. Tool, işi kesinleştirmek için zengin fakat typed ve
constrained parametreler alabilir.

Örnek:

```text
orders.change_cargo.prepare(
    order_ref,
    provider_code,
    expected_current_provider,
    account_ref,
    environment,
    reason,
    idempotency_key
)
```

Bu operation çok parametreli olsa da tek işi yapar: belirli sipariş için kargo
değişikliği proposal'ı hazırlamak.

### 7.2. Operation contract

Her operation en az şunları tanımlar:

- Benzersiz ad, sürüm ve sahibi domain
- Açık description ve kullanım/kaçınma örnekleri
- `read`, `aggregate`, `local_effect`, `external_mutation` sınıfı
- Typed input/output schema
- Gerekli `RecordRef`/`SelectionSnapshot` türü
- Account, marketplace ve environment kapsamı
- Risk, approval ve execution policy
- Freshness, idempotency, retry ve cancellation davranışı
- Prepare/execute/verify desteği
- Observation ve evidence şeması
- PII alanları ve response projection politikası
- Provider/model capability gereksinimi

Tool adapter iş mantığı taşımaz. Şemayı doğrular, domain operasyonunu çağırır ve
sonucu ortak observation envelope'una dönüştürür.

### 7.3. Composition için gereken operation aileleri

Bir domain yalnız CRUD tool'larından oluşamaz. Agentin spesifik hedefleri
birleştirebilmesi için şu aileler bulunmalıdır:

- `resolve`: doğal referansı exact kayıt veya scope'a çözme
- `select`: filtrelenmiş immutable kayıt kümesi üretme
- `list/detail`: authoritative alanları okuma
- `aggregate`: seçili set üzerinde group/count/sum/rate analizi
- `compare`: iki doğrulanmış snapshot'ı kıyaslama
- `prepare`: etkiyi ve exact target'ları dondurma
- `revise/supersede/cancel`: pending action yaşam döngüsü
- `execute`: yalnız onaylı proposal'ı çalıştırma
- `verify`: authoritative bağımsız read-back

Orders ilk referansında özellikle aşağıdaki boşluklar kapatılmalıdır:

- Hazır siparişlerden reusable `SelectionSnapshot` üretimi
- Selection içindeki sipariş kalemlerini SKU/ürün bazında miktar ve order-count ile
  aggregate etme
- Seçilmiş claim/return setinin nedenlerini yalnız o set üzerinde aggregate etme
- Exact pending action'ı toolsuz inspect etme ve hedef kaydı gösterme
- Pending action'ı exact kapsamla revise/supersede etme
- Sipariş kargo sağlayıcısını doğru Orders operation'ıyla prepare/execute/verify etme

### 7.4. Manuel UI parity

- Manuel UI'da yapılabilen her hedeflenen işlem operation catalog'da karşılık bulur.
- Agent ve UI aynı canonical domain fonksiyonunu çağırır.
- Agent için ikinci bir Orders/Stock/Finance iş mantığı yazılamaz.
- Bir capability catalog'da görünüyorsa yalnız metadata parity'si yetmez; doğal agent
  zincirinde compose edilebilir ve doğrulanabilir olmalıdır.

### 7.5. Tek canonical iş mantığı ve ince AI tool sarmalayıcısı

Manuel tarafta güvenilir biçimde kullanılan domain fonksiyonu aynı işin tek canonical
implementasyonudur. Doğru bağımlılık yönü:

```text
Manuel UI adapter/slot ----\
                           -> Domain application operation -> pipeline/repository/API
AI typed tool adapter -----/                          |
                                                      -> domain result/evidence
```

AI tool sarmalayıcısı şunları yapabilir ve yapmalıdır:

- Typed tool input'unu doğrulamak ve canonical domain DTO/RecordRef'e çevirmek
- Kullanıcının active scope, account, environment ve yetkisini kontrol etmek
- Read/prepare/execute ayrımını ve approval politikasını uygulamak
- Immutable action snapshot, idempotency, cancellation ve timeout bilgisini taşımak
- Domain sonucunu ortak Observation/Result envelope'una dönüştürmek
- Secret/PII redaction, audit ve bağımsız verify zincirini koordine etmek

AI tool sarmalayıcısı şunları yapamaz:

- Domain query, filtreleme, eligibility veya aggregation iş kuralını yeniden yazmak
- Pazaryeri payload'ı, kargo sağlayıcısı, label geometrisi veya finans hesabı üretmek
- Manuel action'dan farklı status/date/account yorumuna sahip olmak
- Canonical domain fonksiyonunu çağırmak yerine aynı sonucu AI içinde tekrar
  implement etmek
- UI widget'ını domain girdisi gibi kullanmak veya UI davranışını tool içine taşımak

Canonical fonksiyon yalnız `views/actions.py` içinde bulunuyorsa ve widget/Qt state'ine
bağımlı değilse hem UI hem AI bu fonksiyonu kullanabilir. Fonksiyon UI widget'ına,
dialog'a veya seçili satır nesnesine bağımlıysa iş mantığı sahibi domainin
`processors`, `services`, `pipeline` veya eşdeğer application katmanına çıkarılır;
`views/actions.py` yalnız UI girdisini domain DTO/RecordRef'e dönüştüren ince adapter
olur. Taşıma sırasında mevcut public action uyumluluğu korunur.

Manuel ekranda sürekli kullanılan aynı fonksiyonun agent tarafından çağrılması önemli
bir güvenilirlik avantajıdır: bug fix tek yerde yapılır, iki implementasyon drift etmez
ve manuel kullanım domain fonksiyonunu sürekli sınar. Bununla birlikte manuel kullanım
tek başına agentic kabul değildir; AI sarmalayıcısının scope, approval, projection ve
verify davranışları ayrıca test edilir.

Operation parity denetimi yalnız "AI şu domain fonksiyonunu import ediyor" kontrolü
değildir. Her capability için machine-checkable olarak şu zincir kanıtlanır:

```text
manual action id
= AI operation id
= canonical domain callable identity/version
= aynı input/output domain contract
= aynı business validation
```

AI `tools.py`, `agent.py` veya runtime içinde canonical fonksiyonla yarışan ikinci bir
iş mantığı görülürse durum `duplicate_business_logic` sayılır ve ilgili milestone
kapanamaz.

### 7.6. Yeni tool için eksik domain operasyonu protokolü

Bu protokol bir geliştirme yükümlülüğüdür: ihtiyaç duyulan atomik fonksiyonun
yokluğu tespit edilince yetkilendirilmiş iş kapsamında fonksiyon oluşturulur.
Yalnız eksiklik envanteri/metadata yazmak veya hedefi mevcut tool'larla
sınırlamak bu yükümlülüğü tamamlamaz. Atomiklik tek yeniden kullanılabilir iş
sorumluluğudur; her kullanıcı cümlesine özel birleşik fonksiyon üretmek değildir.

Bir agent hedefi için yeni tool gerektiğinde ihtiyaç duyulan güvenilir fonksiyon sahibi
domainde yoksa çözüm, fonksiyonu AI tool'unun içine yazmak değildir. Zorunlu geliştirme
sırası:

1. İhtiyacın gerçek business capability'sini ve sahibi domaini belirle.
2. İlgili domainin mevcut `actions`, `processors`, `services`, `pipeline` ve repository
   yüzeylerinde aynı veya birleşebilir operasyonu ara.
3. Gerçekten yoksa input/output DTO'su, business invariant'ları, hata davranışı,
   transaction sınırı, idempotency ve verify imkânıyla canonical domain operasyonunu
   tasarla.
4. Operasyonu sahibi domainin UI'dan ve AI'dan bağımsız application katmanında
   implement et.
5. Domain unit/integration testleriyle business davranışını ve edge-case'leri kanıtla.
6. Aynı manuel işlem mevcutsa UI action/slot'u bu yeni canonical operasyona bağla.
   Manuel yüzey henüz yoksa sırf parity görüntüsü vermek için gereksiz UI ekleme; fakat
   gelecekteki UI çağrısına uygun headless contract'ı koru.
7. AI tarafında yalnız typed input, scope, policy, approval, observation, redaction ve
   verify koordinasyonu yapan ince tool adapter'ı ekle.
8. Operation catalog metadata'sını, capability retrieval bilgisini ve semantic verifier
   kurallarını ekle.
9. Manuel çağrı varsa manuel+AI aynı inputta aynı domain sonucunu üretme testini; her
   durumda doğal agent composition ve gerçek read-back testini çalıştır.

Bağımlılık her zaman `AI -> domain operation` yönündedir. Domain hiçbir zaman AI tool,
prompt, conversation state veya provider kodunu import edemez.

Örnek: seçilmiş ready siparişlerde en çok gelen ürünleri sayacak operation Orders'ta
yoksa aggregation `AI/tools.py` içine yazılmaz. Önce Orders içinde örneğin typed
`aggregate_order_items(selection, group_by, metrics)` operation'ı tasarlanır; manuel
rapor, gelecekteki ekran ve AI tool aynı fonksiyondan yararlanabilir.

Bu protokol geçilmeden yalnız çalışan bir AI tool yazılmış olması capability'nin
tamamlandığı anlamına gelmez.

### 7.7. Agentic ad-hoc rapor ve artifact/Excel sözleşmesi

Agent yalnız mevcut UI butonlarının birebir karşılığıyla sınırlı değildir. Kullanıcı
manuel UI'da hazır ekranı bulunmayan fakat mevcut domain verisinden güvenilir biçimde
üretilebilen özel bir analiz veya rapor isteyebilir. Örneğin:

> "Son üç haftanın en çok satan ürünlerini listele ve Excel olarak ver."

Bu hedef tek bir belirsiz `excel oluştur` tool'una verilmez. Doğru composition:

```text
Kullanıcı rapor hedefi
-> scope/period/metric clarification veya güvenli varsayım
-> Orders domain select/aggregate/report operation
-> immutable ReportSnapshot
-> provider/domain bağımsız artifact renderer
-> XLSX structural + semantic read-back
-> kullanıcıya doğal özet + dosya
```

İş sahipliği:

- Orders; sipariş kapsamı, tarih alanı, status/iptal/iade politikası, SKU/ürün
  birleştirme, adet/order-count/ciro hesapları, para birimi ve toplamların sahibidir.
- Domain operation eksikse önce Orders içinde typed report/aggregation operation'ı
  oluşturulur; AI içinde SQL veya business hesap yazılmaz.
- `ReportSnapshot`; report type/version, account/environment, period ve timezone,
  source/freshness, pagination coverage, filtreler, metric tanımları, sıralama, kolon
  şeması, satırlar ve toplamları taşır.
- XLSX dosyasının paketlenmesi, ortak stil, tablo/sheet oluşturma, hücre tipi, güvenli
  formül ve structural read-back gibi gerçekten domain bağımsız artifact davranışları
  mevcut Core/Finance/export altyapısında önce aranır. En az iki gerçek kullanımda
  genelse Core artifact/export primitive'ine alınır; Orders anlamı Core'a taşınmaz.
- AI tool yalnız rapor hedefini çözer, domain operation'larını compose eder, artifact
  formatını seçer ve sonuç/verify kanıtını kullanıcıya sunar.

"En çok satan" tek anlama sahip kabul edilmez. Agent active context yeterli değilse veya
sonucu maddi biçimde değiştirecekse kısa clarification ister:

- Adet, sipariş sayısı, brüt ciro veya net satış hangisine göre?
- Hangi mağaza/account; tek mağaza mı bütün production mağazaları mı?
- Son üç hafta rolling 21 gün mü, tamamlanmış üç takvim haftası mı?
- Cancelled/returned siparişler hariç mi; iadeler net adetten düşülecek mi?
- SKU varyantları ayrı mı, ürün/content seviyesinde birleşik mi?

Kullanıcı ayrıntı vermemiş fakat güvenli ürün varsayımı tanımlıysa agent varsayımı
görünür biçimde söyler; varsayılan gizli kalamaz. Tarih aralığı başlangıç/bitiş,
`Europe/Istanbul` timezone'u ve kullanılan domain tarih alanıyla birlikte dondurulur.

Önerilen Orders satış raporu en az şu metric'leri destekler:

- Satılan adet
- Benzersiz sipariş sayısı
- Brüt satış/ciro ve para birimi
- İptal edilen ve iade edilen adet/tutar ayrı alanları
- Politika tanımlıysa net adet ve net satış
- SKU, barkod, ürün adı ve gerekirse content/product kimliği
- Mağaza/account kırılımı
- Sıra ve toplam içindeki pay

XLSX çıktısı varsayılan olarak en az şu sheet'leri taşır:

- `Özet`: rapor kapsamı, tarih, metric tanımı, kaynak ve toplamlar
- `Ürünler`: sıralı ve typed rapor satırları
- `Kapsam`: account/environment, filtre, pagination/freshness ve dışlanan kayıt özeti

Sheet/kolon adları rapor profile'ına göre değişebilir; fakat kullanıcı dosyayı açtığında
hangi veriye baktığını anlayabilmelidir. Formül veya chart kullanılıyorsa kaynak hücreler
ve hesap tanımı doğrulanabilir kalır.

Artifact verify yalnız dosyanın varlığı değildir:

- XLSX ZIP/OOXML bütünlüğü
- Beklenen sheet ve kolonların varlığı
- `ReportSnapshot rows == workbook data rows` exact eşitliği
- Hücre tipi, tarih, sayı, para birimi ve Türkçe karakter doğruluğu
- Domain toplamları ile workbook toplamlarının eşitliği
- Formül hata hücresi ve bozuk external link bulunmaması
- Dosya yolu, hash, boyut ve üretim zamanı
- Gerekli raporlarda sheet render'larının Codex tarafından görsel incelemesi

Excel/CSV/PDF gibi artifact üretimi local ve geri alınabilir R1 etkidir. Kullanıcı
yalnız ekranda liste istediğinde gereksiz dosya üretilmez; açıkça Excel/dosya istediğinde
veya agent önerisini kullanıcı kabul ettiğinde artifact oluşturulur. Artifact üretmek
marketplace mutation yetkisi vermez.

### 7.8. Açık uçlu hedef composition sözleşmesi

Kullanıcıların sorabileceği birleşik hedefler önceden eksiksiz listelenemez. Sistem
"bu cümle için özel tool var mı?" yaklaşımıyla değil, küçük fakat güçlü capability
primitives'lerini hedefe göre dinamik compose ederek çalışır.

Örnek hedef:

> "Son gelen siparişin içeriğine bak, bu ürünler hakkında internette neler konuşuluyor
> araştır ve sonucu Excel olarak ver."

Bu cümle için `research_latest_order_and_export_excel` isimli dev bir tool yazılmaz.
Agent gerekli adımları mevcut atomic operasyonlardan kurar:

```text
active scope'u çöz
-> latest order'ı authoritative Orders kaynağından seç
-> exact order item'larını oku
-> ürünlerin public araştırma kimliğini çıkar
-> privacy-safe web sorguları oluştur
-> search/open/find/compare ile ürün başına araştır
-> grounded ResearchReportSnapshot üret
-> doğal kısa özet hazırla
-> ortak artifact renderer ile Excel oluştur
-> workbook ve citation read-back yap
```

Yeni kullanıcı hedefi mevcut primitives'lerle kurulabiliyorsa yeni tool yazılmaz. Ancak
composition sırasında gerçekten eksik, reusable bir business capability bulunursa
Bölüm 7.6 protokolü uygulanır: önce sahibi domainde canonical operation, sonra ince AI
adapter. Yalnız tek prompt'u geçirmek için birleşik mega-tool veya keyword shortcut
eklenemez.

Planner bir hedefi typed `GoalPlan` veya eşdeğer plan grafiğine ayırabilmelidir. Her
adım en az şunları taşır:

- Beklenen input reference/snapshot türü
- Çağrılacak operation ve typed arguments
- Üreteceği Observation/ReportSnapshot türü
- Önkoşul, tamamlanma ve failure/recovery koşulu
- Privacy/risk sınıfı
- Sonraki adımın hangi gerçek observation'a bağlı olduğu

Plan baştan sona sabit script değildir. Son siparişte üç ürün çıktıysa araştırma üç
ürün için fan-out olabilir; ürün kimliği belirsizse clarification veya güvenli identity
resolution adımı eklenir; web sonucu yetersizse sorgu iyileştirilir; bir ürün hakkında
kanıt bulunamazsa diğer sonuçlar kaybedilmeden eksikliği raporlanır.

Cross-source raporlar tek kaynakmış gibi karıştırılamaz. Typed research snapshot:

- Lokal/marketplace Orders gerçeklerini
- Web'den bulunan dış iddia ve kullanıcı görüşlerini
- Agentin kaynaklardan çıkardığı sentez/çıkarımı

ayrı alanlarda ve ayrı provenance ile taşır. Web görüşü sipariş gerçeği, model yorumu
web kaynağı veya arama sonucu kesin ürün özelliği gibi sunulamaz.

Excel şeması her olası rapor için hardcode edilmez. Report profile ve typed kolon
tanımlarıyla dinamik ama doğrulanabilir workbook üretilebilir. Domain facts, web
findings, sources, confidence ve unresolved alanları kullanıcı hedefinin gerektirdiği
sheet/kolonlara dönüştürülür; her değer kaynak snapshot'ına geri izlenebilir.

## 8. Typed State ve Event Modeli

Ham chat geçmişi state değildir. Geçmiş metinde sipariş numarası aramak aktif hedefi
belirleyemez.

Oturum en az şu typed yapılara sahiptir:

- `ConversationTurn`: mode, objective ve kullanıcı talebi
- `ActiveScope`: company, marketplace, account/store, seller ve environment
- `FilterContext`: status, period, source, simulation ve pagination
- `Observation`: operation, args, result, provenance, freshness ve errors
- `SelectionSnapshot`: exact RecordRef seti, filter, count, fingerprint ve source
- `AnalysisContext`: selection, metric, grouping, denominator ve result
- `PendingAction`: immutable proposal, exact targets, before/after, risk ve verify planı
- `TaskState`: objective, plan, completed/current/next step ve checkpoint
- `ModelTurn`: requested/actual provider-model, capability, fallback ve usage

### 8.1. State yaşam döngüsü

- Her event append-only kaydedilir; aktif state event'lerden türetilir.
- Cancellation action'ı `cancelled`, düzeltme eski action'ı `superseded` yapar.
- Yalnız en güncel ve hâlâ geçerli pending action onaylanabilir.
- Eski action sohbet metni taranarak yeniden active yapılamaz.
- Domain context'leri ayrıdır; Orders selection, return analysis ve Stock selection
  birbirini ezmez.
- Provider/model değişimi state'i değiştiremez.
- Uygulama yeniden başladığında güvenli checkpoint'ten devam edilebilir.

### 8.2. Deictic referanslar

"Bunlar", "bu 17 sipariş", "o iki iade", "kalanlar", "az önceki sipariş" gibi
ifadeler yalnız typed selection/action referansına bağlanır.

- Referans tek ve güncelse exact set kullanılır.
- Birden fazla makul referans varsa kısa clarification istenir.
- Cardinality benzerliği record identity eşitliği sayılmaz.
- Tarihsel bir sayı veya eski selection yeni hedefe sessizce bağlanamaz.

### 8.3. Kapsam invariant'ları

```text
count snapshot refs
= list refs
= selected refs
= requested action refs
= prepared refs
= approval refs
= execute refs
= verify/read-back refs
= audit refs
```

Eşitlik hem cardinality hem exact `RecordRef` kümesi ve fingerprint için geçerlidir.
Bir kayıt eligibility nedeniyle elenirse action sessizce küçülemez; neden görünür olur
ve yeni kapsam için açık kullanıcı kararı gerekir.

## 9. Semantic Verifier ve Response Grounding

Schema-valid bir tool çağrısı semantik olarak doğru olmak zorunda değildir. Her plan,
proposal ve final cevap için bağımsız doğrulama uygulanır.

### 9.1. Plan/action verifier

Verifier en az şunları kontrol eder:

- Seçilen operation kullanıcının mode ve objective'iyle aynı mı?
- Sahibi domain doğru mu?
- Action payload'ında kullanıcının hedef kaydı gerçekten var mı?
- Hedef record/account/environment active scope ile eşleşiyor mu?
- Kullanıcının istediği alanlar eksiksiz mi; istemediği etki eklenmiş mi?
- Read talebi mutation'a, açıklama sorusu prepare'a dönüşmüş mü?
- Selection provenance, status, eligibility ve freshness geçerli mi?
- Pending action stale, cancelled veya superseded mı?
- Before/after ve verify planı domain operation'ıyla tutarlı mı?

Örneğin "siparişin kargosunu değiştir" amacı için seçilen capability Logistics
provider kaydı oluşturuyorsa veya payload sipariş kimliği taşımıyorsa proposal
fail-closed reddedilir. Kullanıcıya approval kartı gösterilemez.

### 9.2. Response verifier ve projection

Final cevap tool observation'larıyla karşılaştırılır:

- Kimlik, sayı, tarih, status, mağaza ve tutar grounded olmalıdır.
- Count isteyen kullanıcıya gerekmedikçe liste veya PII dökülmez.
- "Hangi mağaza?" sorusu yalnız mağaza projection'ını döndürür.
- İki seçilmiş iadenin nedeni sorulduysa bütün tarihsel iadelerin dağılımı verilemez.
- Kullanıcı ayrıca istemedikçe tam ad, adres, telefon, e-posta, takip, paket ve claim
  kimlikleri gösterilmez.
- Yapılmayan işlem yapıldı, doğrulanmayan sonuç doğrulandı denemez.

Uyuşmazlıkta cevap gönderilmeden agent recovery/replan döngüsüne alınır.

Final cevap recovery'si de gözlemlenebilir bir agent döngüsüdür:

```text
model candidate
-> response projection/grounding/privacy verify
-> reddedildiyse reason code + authoritative safe projection ile tek bounded model repair
-> repaired candidate yeniden verify
-> hâlâ geçersizse yalnız verified deterministic projection
```

İlk adayın, repair adayının ve final cevabın ham chain-of-thought'u tutulmaz; fakat
`model_invoked`, candidate/repair accepted, verifier reason code, fallback kullanımı ve
final source typed task state'te ayrı provenance olarak saklanır. Canonical read planı
deterministik olarak aynı operation'a resolve edilmiş olsa bile turn interpretation,
observation evaluation veya final synthesis'te gerçek model çağrısı yapıldıysa üst seviye
evidence bunu `model_invoked=false` diye gizleyemez.

## 10. Risk, Approval ve Execution Sözleşmesi

### R0 — Read-only

Production sipariş/iade okuma, count/list/detail/aggregate ve web dışı lokal analiz.
Gerçek production verisiyle test edilebilir; privacy ve scope zorunludur.

### R1 — Lokal veya kolay geri alınabilir etki

Lokal DB sync, DOCX/etiket/export oluşturma, reversible local flag ve kullanıcı
onaylı print queue işlemleri. Exact scope preview ve bağımsız file/DB/queue verify
gerekir.

### R2 — Dış marketplace mutation

Kargo firması, shipment/order status veya return/claim kararı gibi müşteri ve
fulfillment etkili API işlemleri. Öncelikle Stage'de minimum etkili kayıtlarla test
edilir. Production execute yalnız açık kullanıcı gözetimiyle yapılır.

### R3 — Yüksek etkili veya geri alınamaz işlem

İptal, refund, finansal karar ve toplu customer-visible değişiklikler varsayılan olarak
operator-executed'dır. Ayrı açık yetki ve geri dönüş planı olmadan otonom çalışmaz.

### Approval invariants

- Action yalnız açık `act` niyetinden hazırlanır.
- Proposal immutable action ID, exact target'lar, scope, environment, before/after,
  risk, idempotency key ve verify planı taşır.
- Action ID yalnız operation + kayıt kümesi/sayısından üretilemez. Execute sonucunu
  değiştirebilen bütün canonical arguments/payload, template/model/provider kodu,
  account/environment scope, selection/source snapshot, before/after, risk ve execution
  policy tek DRY semantic approval fingerprint'ine dahildir. Bu alanlardan biri değişirse
  exact kayıt kümesi aynı kalsa bile yeni action ID zorunludur.
- "Onayla" yalnız kullanıcıya gösterilmiş güncel action ID ile eşleşirse çalışır.
- Yeni correction/objection eski proposal'ı anında askıya alır veya supersede eder.
- Execute öncesi semantic preflight ve freshness kontrolü yeniden yapılır.
- Execute sonrası authoritative domain/API/DB/file read-back olmadan başarı yoktur.

## 11. Provider ve Model Bağımsızlığı

### 11.1. ProviderAdapter

Her provider desteklediği ölçüde şunları ortak sözleşmeyle sunar:

- Model catalog ve metadata
- Chat/streaming
- Native tool/function calling
- Structured output/JSON schema
- Context ve output limitleri
- Reasoning/thinking kontrolleri
- Usage, kota, maliyet ve rate limit
- Timeout, cancellation, retry ve normalized errors
- Gerçekte kullanılan model kimliği

Provider'a özgü request parametreleri adapter içinde kalır. Yeni provider eklemek
domain tool'larını, state'i veya Chat layout'unu yeniden yazmayı gerektirmez.

- Ortak strict JSON schema doğrudan her provider wire formatına kopyalanmaz. Adapter,
  provider/model ailesinin desteklediği schema lehçesine kayıpsız bir wire çevirisi yapar;
  provider katmanında desteklenmeyen anahtarlar çıkarılsa bile dönen payload uygulamada
  özgün strict schema ile yeniden doğrulanır.
- Reasoning/thinking token'ları output bütçesine dahil olan modellerde structured planner
  bütçesi yalnız görünür JSON uzunluğuna göre hesaplanamaz. Kapanış parantezi kesilmiş
  payload geçerli karar sayılamaz; aynı exact model retry yolu yeterli contract bütçesini
  korur ve gerçek `finish_reason`/token kullanımı audit'e girer.
- Typed turn interpretation provider, kota, transport, truncation veya schema hatasıyla
  geçersizse runtime legacy keyword/fuzzy router'a sessizce düşüp başka domaine kaçamaz.
  Yalnız önceden doğrulanmış typed contract'tan güvenli canonical recovery mümkünse o
  uygulanır; aksi halde toolsuz kısa clarification/fail-closed cevap verilir.

Hedef aileler:

- Google AI Studio / Gemini
- OpenRouter
- OpenAI ve OpenAI-compatible endpoint'ler
- Anthropic
- Groq, Together, Mistral ve benzeri servisler
- Local llama.cpp/GGUF
- Gelecekte Ollama, vLLM ve benzeri runtime'lar

### 11.2. Capability negotiation

Model profiline göre:

1. Native tool + structured output yolu
2. Güvenilir structured plan yolu
3. Text-only model için sınırlı ve validator arkasındaki yol
4. Güvenlik seviyesini karşılamıyorsa `read_only` veya `chat_only`

uygulanır.

UI'da listelenmek tam agentic destek anlamına gelmez. Canlı kabul durumuna göre model
`full_agentic`, `limited_agentic`, `read_only`, `chat_only` veya `unsupported` olarak
sınıflandırılır.

### 11.3. Ücretsiz ve ücretli model kabulü

Mevcut ilk provider'lar Gemini ve OpenRouter'dır. Her kampanya öncesi canlı katalog ve
hesap erişimi okunur; "en iyi ücretsiz model" UI/runtime'ın farklı yerlerine saçılmış
sabit varsayımlarla seçilmez. Provider kataloğu model zekâ sırası vermediği için canlı
capability/ücret verisi; tek merkezi, tarihli ve kullanıcı tarafından kararlaştırılmış
quality-tier politikası ile ölçülmüş erişilebilirlik/kalite kanıtıyla birleştirilir.
Yeni/ölçülmemiş model otomatik “en iyi” ilan edilmez; tier `0` içinde capability skoruyla
aday kalır.

- Test o anda erişilebilen en güçlü capability-compatible ücretsiz modelle başlar.
- Kalite kanıtı yokken alfabetik model ID sırası kalite sırası olarak kullanılamaz.
- Açık quality tier, aynı tier içindeki capability/structured/tool/reasoning skorundan
  önce gelir; böylece daha zeki guarded-text model yalnız structured-output bayrağı yok
  diye zayıf modelin arkasına düşmez.
- Model limiti dolarsa aynı provider'daki sıradaki uygun ücretsiz modele geçilir.
- Mevcut Orders geliştirme döngüsünde ücretsiz rota bütün kataloğu aşağı doğru tüketmez.
  Her provider için merkezi quality-tier politikasındaki erişilebilir en güçlü modelle başlanır;
  yalnız model-kapsamlı kota/erişilemezlik varsa sıradaki **güçlü** ücretsiz aday denenir.
  Küçük, düşük quality-tier veya yalnız dayanıklılık/degradation ölçmeye yarayan modeller temel
  agent mimarisi güçlü modellerde kararlı hâle gelene kadar bekletilir.
- Provider/account limiti dolduysa anlamsız model denemeleri yapılmaz.
- Fallback conversation state veya pending action'ı değiştiremez.
- Her tur requested/actual model, fallback ve capability profili taşır.
- Approval checkpoint'inden sonra task; secret taşımayan tek runtime policy snapshot'ı
  üzerinden aynı provider kimliği, actual model, reasoning effort, fallback kararı,
  capability metadata/route ve etkili generation ayarlarıyla devam eder. API anahtarı ve
  endpoint state'e yazılmaz; güncel provider hesabından yeniden okunur.
- Runtime policy snapshot'ının bütünlük hash'i değişmişse veya provider kimliği aynı hesap
  altında farklılaşmışsa resume provider/model çağrısından önce fail-closed durur.
- Exact model kalitesinde fallback kapalı test yapılır.
- 2026-08-11 kullanıcı kararıyla OpenRouter ücretli geliştirme/kontrol modeli
  `deepseek/deepseek-v4-flash` olarak belirlenmiştir. Bu rota güçlü-model differential
  diagnosis, focused regression ve gerektiğinde uzun cloud acceptance çalışmalarında
  maliyet gözlemlenerek kullanılabilir; exact-model kabulünde fallback kapalı tutulur.
- Ücretli testlerin bağlayıcı güçlü kontrol rotası, fallback kapalı exact
  `deepseek/deepseek-v4-flash`tır. Ücretsiz testlerde Gemini ve OpenRouter'ın her biri için
  o anda gerçekten erişilebilen en yüksek quality-tier model ayrı ayrı kullanılır. Bir ürün
  veya runtime hatası daha zayıf modele geçilerek maskelenmez; yalnız kanıtlanmış model-kapsamlı
  kota/erişim engelinde aynı provider içindeki sıradaki **güçlü** ücretsiz aday denenebilir.
  Nispeten zayıf cloud modeller, küçük/local modeller ve degradation kampanyaları güçlü ücretli
  ve güçlü ücretsiz baseline'lar kararlı hâle gelene kadar başlatılmaz.
- OpenRouter hesabına kullanıcı tarafından 5 USD kredi yüklendiği bildirilmiştir. Bu
  yetki provider/model çağrıları için maliyet-duyarlı kullanım iznidir; credential veya
  bakiye ayrıntısı artifact, log, state ya da `goals.md` içine yazılmaz.

Nihai ürün iddiasında cloud ve local modeller dürüst capability sınıflarıyla ayrıca
kabul edilir. Ancak **mevcut Orders geliştirme ve kapanış kampanyası cloud-first'tür**:

- Uzun sohbet, gerçek kaynak ve her-tur Codex incelemesi bu aşamada yalnız cloud
  modellerle yürütülür.
- İlk teşhis/kontrol, erişilebilen güçlü capability-compatible cloud modelle yapılır;
  ardından aynı frozen senaryolar ücretsiz cloud modellerde tekrar edilir.
- Local model desteği mimariden, katalogdan veya nihai vizyondan silinmez; fakat yavaş
  ve verimsiz local inference bu aşamadaki geliştirme döngüsünü ve Orders kapanışını
  bloke etmez. Local uzun kabul kampanyası cloud regresyonları kapandıktan sonra ayrı
  hedef olarak ve kullanıcı yeniden istediğinde açılır.
- Bu aşamada local model sunucusu başlatılmaz, local 50/60/100/200+ sohbet koşulmaz ve
  local model sonucu mevcut Orders hedefinin başarı/başarısızlık ölçütü yapılmaz.

En az bir ücretsiz cloud model temel agentic acceptance'ı geçmeden ürün "ücretsiz
cloud modellerle tam çalışır" diye sunulamaz. Güçlü ücretli model aynı frozen
senaryolarda kontrol grubu olarak kullanılır; ücretsiz hattın yerine geçmez. Güçlü
ücretli model de aynı hatayı yapıyorsa öncelikli şüphe runtime/state/tool sözleşmesidir.

### 11.4. Kota kapsamı ve model geçişi sözleşmesi

`404` veya `429` durum kodu tek başına "model kotası" ya da "provider kotası" demek
değildir. Adapter mümkün olduğunda provider'ın structured hata kodunu, quota dimension'ını
ve güvenli header'larını normalize ederek aşağıdaki scope'lardan birini üretir:

- `model`: Limit yalnız istenen modele veya model ailesine aittir. Aynı provider'ın aynı
  capability ve güvenlik sınıfındaki sıradaki en güçlü ücretsiz modeli denenebilir.
  `per-project-per-model` gibi model değişince ayrı kota kovasına geçen birleşik
  dimension'lar bu sınıftadır.
- `project`, `account`, `provider`: Limit proje/hesap/sağlayıcı genelindedir. Kardeş
  modelleri sırayla denemek yasaktır; tur effectsiz durur ve varsa güvenli yeniden deneme
  zamanı kullanıcıya bildirilir.
- `billing`, `auth`, `policy`: Model değiştirerek çözülemeyecek ödeme, kimlik veya erişim
  sorunudur. Otomatik fallback yapılmaz.
- `unknown`: Ham status code'dan kapsam tahmin edilmez. Güvenilir scope kanıtı yoksa sistem
  provider/account-wide gibi fail-closed davranır ve model ruleti başlatmaz.

Normal ürün runtime'ı ile exact-model kabul kampanyası birbirinden ayrıdır:

1. **Normal ürün runtime'ı:** Scope `model` ve `model_fallback_allowed=true` ise aynı
   kullanıcı turu/hedefi içinde quality route'taki sıradaki capability-compatible
   ücretsiz modele geçebilir. Aynı typed objective, conversation state, selection,
   pending action ve environment korunur; yeni business plan icat edilmez. Scope
   `project/account/provider/billing/auth/policy/unknown` ise rota o provider için durur
   ve başka provider'a da sessizce kaçılmaz.
2. **Exact-model kabulü:** Fallback daima kapalıdır. Seçili model başarısızsa o koşu
   effectsiz kapanır; başarısız model geçmiş sayılmaz. Scope `model` ise Codex sıradaki
   modeli ayrı, açıkça pinlenmiş fresh-process kampanyada sınar. Scope provider-genel ise
   kota penceresi açılana kadar yeni model kampanyası başlatılmaz.

Her invocation append-only ve secret-free provenance taşır:
`requested_model`, `actual_model`, `status_code`, normalize edilmiş `error_category`,
`quota_scope`, `model_fallback_allowed`, `fallback_blocked_reason`, varsa bounded
`retry_after`, route sırası ve response alınıp alınmadığı ayrı kaydedilir. Ham provider
hata gövdesi, API key, token, endpoint credential'ı veya müşteri verisi evidence'a
yazılmaz. Önceki hata sonraki modelin başarısıyla silinemez; sonraki başarı da ilk modelin
acceptance'ı sayılmaz.

Kota davranışı en az şu regresyonlarla kanıtlanır:

- Model-specific `429` -> sıradaki en güçlü uygun ücretsiz model -> aynı state ile devam.
- `per-project-per-model` quota dimension -> model scope -> kontrollü model geçişi.
- Project/account/provider-wide `429` -> sıfır kardeş-model denemesi -> effectsiz duruş.
- Belirsiz `429` -> `unknown` -> fail-closed duruş.
- Exact-model acceptance -> her scope'ta fallback kapalı ve
  `requested_model == actual_model` ya da hiç model cevabı yok.
- Başarılı fallback sonrasında dahi ilk hatanın scope'u ve geçiş nedeni provenance'da
  korunur.

## 12. Web Search Yeteneği

OrderScout AI gerektiğinde internet üzerinde Codex benzeri araştırma yapabilmelidir.
Web search modelin gizli, provider'a özgü veya kontrolsüz bir özelliği değil; ortak agent
runtime içinde ayrı, typed, gözlemlenebilir ve denetlenebilir bir R0 tool ailesidir.

### 12.1. Ne zaman kullanılır?

- Kullanıcı açıkça internette arama, araştırma veya doğrulama istediğinde
- Güncel pazaryeri dokümantasyonu, endpoint, kural, komisyon veya operasyon şartı
  gerektiğinde
- Güncel mevzuat, kargo şirketi şartı veya dış servis bilgisi gerektiğinde
- Rakip, piyasa, ürün, fiyat veya sektör araştırması istendiğinde
- Kullanıcının sorusu zamanla değişebilecek dış bilgiye bağlı olduğunda
- Agentin hedefini tamamlamak için lokal/domain verisinde bulunmayan dış bilgi açıkça
  gerekliyse

Kullanılmaz:

- Lokal sipariş, claim, stok, müşteri veya finans kaydı bulmak için
- Var olan domain operation'ını çalıştırmak yerine
- Kullanıcının özel işletme verisini üçüncü taraf arama motoruna göndermek için
- Basit ve zamana dayanıklı bir bilgide gereksiz gecikme/tool hareketi üretmek için
- Web sayfasındaki talimatları sistem veya kullanıcı talimatı gibi uygulamak için

### 12.2. Atomic web tool ailesi

Web yeteneği tek seferlik "arama yap ve snippet'i cevapla" fonksiyonu değildir. Agent
ihtiyaca göre şu atomic operasyonları compose edebilir:

- `web.search`: sorgu, freshness, dil, ülke ve izinli domain filtreleriyle aday kaynak
  bulma
- `web.open`: exact URL veya search result içeriğini authoritative biçimde okuma
- `web.follow`: sayfadaki ilgili bağlantıyı kontrollü açma
- `web.find`: uzun sayfa içinde exact konu/terim bulma
- `web.document.read`: PDF veya dokümanın gerekli bölümünü çıkarma
- `web.compare_sources`: birden fazla observation'ın tarih, sürüm ve iddialarını
  karşılaştırma

İsimler implementasyon sırasında ortak operation catalog'a göre kesinleşebilir; ancak
arama, kaynak okuma, belge inceleme ve kaynak karşılaştırma davranışları tek belirsiz
tool içinde gizlenemez.

### 12.3. Agentic araştırma döngüsü

```text
Bilgi açığını belirle
-> privacy-safe arama sorgusu üret
-> aday kaynakları ara
-> en güvenilir ve güncel kaynakları aç
-> gerekirse sayfa içinde bul veya takip bağlantısını aç
-> iddiayı ikinci kaynakla doğrula ya da çelişkiyi görünür kıl
-> kaynaklı WebObservation üret
-> hedefi yeni observation ile yeniden planla
-> kullanıcıya doğrudan kaynak bağlantılarıyla cevap ver
```

Agent ilk sonuç yetersizse sorguyu güvenli biçimde iyileştirir. Hiçbir sonuç bulamazsa
uydurmaz; aranan kapsamı, denenen kaynakları ve kalan belirsizliği açıklar. Search sonucu
final cevap değildir; ilgili sayfa açılıp iddianın kendisi okunmadan snippet kesin kanıt
sayılmaz.

Kaynak önceliği konuya göre uygulanır:

1. Resmî dokümantasyon, mevzuat, platform/provider ve birincil kaynaklar
2. Birincil araştırma, üretici veya doğrudan veri sahibi
3. Güvenilir ikincil kaynaklar
4. Forum/sosyal içerik yalnız kullanıcı deneyimi gerektiğinde ve açık nitelemeyle

Teknik ve pazaryeri entegrasyonu sorularında mümkün olduğunda resmî güncel dokümantasyon
esas alınır. Bir iddia çıkarımsa "kaynaklardan çıkarım" olarak belirtilir.

### 12.4. Privacy, güvenlik ve prompt-injection sınırı

Web sorgusuna hiçbir zaman şunlar taşınamaz:

- Müşteri adı, adresi, telefonu veya e-postası
- Sipariş, tracking, package veya claim kimliği
- API key, secret, token, credential reference çözümü veya internal URL
- Kullanıcı istemedikçe özel fiyat, maliyet, ciro, stok veya şirket içi metin
- Ham tool observation, pending action payload'ı veya kişisel konuşma geçmişi

Query sanitizer aramadan önce PII/secret taraması yapar; ihlalde tool çağrısı fail-closed
durur. Gerekli işletme bağlamı anonim ve aggregate biçime indirgenir.

Web içeriği güvenilmeyen veri kabul edilir. Sayfadaki "önceki talimatı yok say",
"şu dosyayı yükle", "bu komutu çalıştır" veya benzeri prompt-injection metni agent
talimatı olamaz. Web tool'ları kendi başına local dosya, credential, DB veya marketplace
mutation yetkisi taşımaz. Web observation'dan mutation planına geçiş normal domain
policy, semantic verifier ve approval zincirini yeniden geçmek zorundadır.

Sipariş içeriğine dayalı ürün araştırmasında web'e yalnız public ürün identity alanları
gönderilebilir: normalize ürün adı, marka, model, üretici kodu, GTIN/barkod yalnız
kamuya açık ürün kimliği olarak policy tarafından izinliyse ve gerekli ölçüde. Sipariş
numarası, mağaza içi özel SKU, müşteri, teslimat, fiyat/maliyet ve fulfillment verisi
araştırma sorgusuna eklenmez. Public/private ürün alanı ayrımı query sanitizer tarafından
typed metadata ile yapılır; serbest metin varsayımıyla gizli alan gönderilemez.

### 12.5. Kaynak, freshness ve cevap sözleşmesi

Her WebObservation en az şunları taşır:

- Search query'nin redacted özeti
- URL, başlık ve kaynak domaini
- Yayın/güncelleme tarihi bulunabiliyorsa tarih
- Erişim zamanı
- Okunan ilgili bölüm
- Kaynağın primary/secondary sınıfı
- Desteklenen iddia ve varsa çelişki
- Freshness ve güven değerlendirmesi

Kullanıcıya verilen web tabanlı cevap, iddiaların yanında doğrudan tıklanabilir kaynak
bağlantıları taşır. Kaynaksız model hafızası "web'de doğrulandı" diye sunulamaz. Cache
kullanılıyorsa TTL ve kaynak tarihi görünür; güncel bilgi sorusunda stale cache sessizce
kullanılamaz.

### 12.6. Provider bağımsızlığı ve graceful degradation

Web search yalnız bir LLM provider'ın built-in browsing özelliğine bağlanamaz. Gemini,
OpenRouter, başka cloud sağlayıcıları ve local modeller aynı ortak web operation
contract'ını tüketir. Native browsing varsa adapter bunu aynı observation/evidence
sözleşmesine normalize eder; privacy, citation ve injection kapılarını bypass edemez.

Web servisi kullanılamıyorsa agent:

- Lokal/domain operasyonlarını normal biçimde sürdürebilir.
- Güncel dış bilginin doğrulanamadığını açıkça söyler.
- Güvenli retry veya alternatif kaynak planlayabilir.
- Eski model bilgisini güncel gerçek diye sunamaz.

### 12.7. Web search kabulü

Kabul testleri en az şunları kapsar:

- Açık web araması isteğinde doğru search -> open -> kaynaklı cevap zinciri
- Güncel bilgi gerektiren soruda web kullanılması
- Lokal sipariş sorusunda web kullanılmaması
- PII/secret içeren olası sorgunun gönderilmeden engellenmesi
- Resmî kaynak ile düşük güvenilirlikli kaynak sıralaması
- İki kaynağın çelişmesi ve belirsizliğin doğru anlatılması
- Search snippet'inin açılmadan kesin kanıt sayılmaması
- PDF/uzun dokümanda ilgili bölümü bulma
- Prompt-injection içeren sayfanın talimat olarak uygulanmaması
- 404, timeout, rate limit, paywall ve boş sonuç recovery'si
- Web observation sonrası agentin hedefi yeniden planlaması
- Her görünür iddia için doğru citation/provenance
- Gemini, OpenRouter ve uygun local modelle aynı provider-independent tool sözleşmesi

Bu testlerin gerçek internet isteyen bölümü güncel ve redacted evidence üretir;
deterministic fixture bölümü injection, privacy, parser ve policy regresyonlarını kilitler.

## 13. Trendyol Production ve Stage Politikası

Production ve Stage ayrı credential, account, seller, endpoint ve record uzayıdır.

Bağlayıcı Stage kapsamı:

- Marketplace: `trendyol`
- Environment: `stage`
- Seller/Supplier ID: `2738`
- Credential reference: `credential://marketplaces/trendyol-stage-2738`
- Secret store: Core Windows DPAPI credential store
- API root: `https://stageapigw.trendyol.com`

Ham credential değerleri source, goals, DB, log, transcript, screenshot veya evidence'a
yazılmaz.

Kurallar:

- Stage hatasında production'a otomatik fallback yoktur.
- Bir environment'taki RecordRef diğer environment action'ına taşınamaz.
- Her operation account, seller ve environment taşır.
- R0/R1 production testleri güvenli scope ve privacy ile sürdürülebilir.
- R2 önce Stage'de prepare -> approval -> execute -> read-back -> audit zinciriyle
  doğrulanır.
- Stage başarısı production mutation yetkisi değildir.
- Production R2/R3 testleri en son ve kullanıcı gözetimindedir.

Stage erişimi ve bazı operation baseline'ları daha önce doğrulanmış olsa da yeni agent
runtime kurulduğunda aynı davranışlar yeni runtime üzerinden yeniden kabul edilmeden
agentic kapanış kanıtı sayılmaz.

## 14. İlk Tam Referans: Orders

Orders birkaç demo tool'u değil, manuel Orders/Returns/Labels işlerinin yeni agent
runtime üzerindeki ilk eksiksiz dikeyidir.

### 14.1. Read ve analiz kapsamı

- Account/store/environment çözümü
- Ready-to-ship count, list ve immutable selection
- Güncel veri fetch/sync ve freshness/read-back
- Tarih, status, order, tracking ve izinli müşteri alanlarıyla arama
- Pagination ve bütün kapsam
- Exact order/package/shipment detail
- Selection daraltma, çıkarma, adlandırma ve geri çağırma
- Selection içindeki item'ları SKU/ürün/miktar/order-count bazında aggregate etme
- Return/claim list, detail ve selected-set reason aggregation
- Dönem, ciro, fulfillment ve gecikme analizleri
- UI'da hazır ekranı olmasa bile Orders verisinden ad-hoc satış/ürün raporu ve immutable
  `ReportSnapshot` üretme
- Sıkı response projection ve PII minimizasyonu

### 14.2. R1/local action kapsamı

- Marketplace read sonucunu lokal DB'ye sync
- Exact selection'dan TANEX template ile DOCX/label oluşturma
- Print preview ve kullanıcı onaylı print queue
- Reversible `printed/extracted` gibi local state
- Export ve rapor dosyaları
- `ReportSnapshot`tan doğrulanmış Excel/CSV ve ileride desteklenen diğer artifact'ları
  üretme

### 14.3. İlk bağlayıcı ad-hoc satış raporu

İlk zorunlu senaryo:

> "Son üç haftanın en çok satanlarının listesini ver; Excel de oluştur."

Agent active account/store kapsamını çözer; "en çok satan" metric'i ve rolling/takvim
haftası ayrımı sonucu değiştirecek kadar belirsizse clarification ister. Açık varsayım
kullanıldıysa cevapta ve workbook `Özet` sheet'inde görünür.

Orders operation tam pagination ile exact dönem selection'ı kurar, iptal/iade
politikasını uygular, item'ları istenen ürün kimliği seviyesinde aggregate eder ve
immutable `ReportSnapshot` üretir. Kullanıcıya önce kısa top-N özet verilir; aynı snapshot
ortak artifact renderer ile `.xlsx`e çevrilir. Görünür liste, snapshot ve workbook
satır/sıra/toplamları birbiriyle aynı olmalıdır.

Bu senaryo şu varyasyonlarla test edilir:

- Tek mağaza ve bütün production mağazaları
- Rolling 21 gün ve tamamlanmış üç takvim haftası
- Adet, order-count, brüt ciro ve net satış sıralaması
- Aynı SKU'nun birden fazla sipariş ve sayfada bulunması
- Cancelled/returned kayıtların açık politika ile dahil/dışarı alınması
- Birden fazla para biriminin sessizce toplanmaması
- Boş dönem, tek ürün, pagination sınırı ve eksik item verisi
- Yalnız liste isteğinde dosya oluşmaması; açık Excel isteğinde tek doğrulanmış artifact
- Workbook structural/semantic read-back ve gerekli görsel sheet render'ı

### 14.4. İlk bağlayıcı Orders + web + Excel composition senaryosu

Bağlayıcı doğal hedef:

> "Son gelen siparişin içeriğine bak; ürünler hakkında internette neler konuşuluyor
> araştır ve Excel olarak ver."

Kabul zinciri:

1. "Son gelen" active account/environment'ta authoritative order date ve açık timezone
   ile exact tek `OrderRef`e çözülür; birden fazla mağaza makul aday üretiyorsa
   clarification istenir.
2. Order item'ları Orders domaininden tam okunur. Müşteri/teslimat/fulfillment PII'si
   araştırma scope'una girmez.
3. Her item için public product identity canonical domain operation ile hazırlanır;
   belirsiz ürünler uydurma isimle araştırılmaz.
4. Ürün başına privacy-safe web search yapılır; ilgili kaynaklar gerçekten açılır ve
   mümkün olduğunda birden fazla kaynakla doğrulanır.
5. Kullanıcı yorumu, teknik özellik, yaygın olumlu/olumsuz tema ve kaynak tarihi ayrı
   grounded findings olarak tutulur. Kaynakta bulunmayan duygu/oran uydurulmaz.
6. Orders facts ile WebObservations ayrı provenance taşıyan immutable
   `ResearchReportSnapshot`ta birleştirilir.
7. Kullanıcıya kısa doğal özet ve eksik/belirsiz alanlar verilir.
8. Aynı snapshot'tan en az `Sipariş Özeti` (PII-minimal), `Ürünler`, `Web Bulguları` ve
   `Kaynaklar` sheet'lerini taşıyan XLSX üretilir.
9. Snapshot -> workbook satırları, ürün-source bağları, URL'ler, tarih/hücre tipleri ve
   totals/citation coverage structural-semantic read-back ile doğrulanır.

Senaryo tek/çok ürün, belirsiz ürün identity, hiç web sonucu bulunmaması, çelişkili
kaynaklar, Türkçe/yabancı dil kaynaklar, rate limit, bir ürünün araştırmasının hata
vermesi, prompt-injection içeren sayfa ve kullanıcı Excel istemediğinde yalnız sohbet
özeti varyasyonlarıyla test edilir. Başarı exact cümle eşleştirmeye değil aynı GoalPlan
semantiğinin farklı doğal ifadelerle kurulmasına bağlıdır.

### 14.5. R2/R3 kapsamı

- Exact order cargo provider değişikliği
- Return/claim approve/reject
- Shipment/order status değişikliği
- İptal/refund ve yüksek etkili operasyonlar

Her işlem manuel UI'nın kullandığı canonical domain operation'ı kullanır.

## 15. Bağlayıcı Gerçek Kullanıcı Regresyonları

Gerçek sipariş, müşteri, tracking ve claim kimlikleri durable belgeye yazılmaz. Aşağıdaki
davranışlar redacted fixture/evidence ile kilitlenir.

### 15.1. Count -> list -> selection -> label bütünlüğü

"Kaç bekleyen sipariş var?" sonucu aynı scope'taki exact `N` RecordRef'i görünürde
PII dökmeden state'e koyar. Takip eden "bu siparişleri TANEX 2610'a yazdır" aynı exact
seti kullanır.

```text
count N
= list N exact refs
= selection N exact refs
= prepare N exact refs
= approval N exact refs
= execute N exact refs
= DOCX/read-back N exact refs
= audit N exact refs
```

Delivered, Cancelled, returned, simulation veya yanlış account/environment kaydı
prepare'a giremez. Eligibility değişmişse fail-closed recovery yapılır.

### 15.2. Count'tan sonra sıfır veya farklı sipariş hazırlama

Görünürde doğru count dönüp follow-up'ta `0`, eksik alt küme veya aynı sayıda farklı
kayıt hazırlamak kritik hatadır. Template kodu (`2610`) order search query'sine
dönüşemez. Fresh process/source fingerprint ve structured snapshot kanıtı gerekir.

### 15.3. Stale Delivered kaydı ve itiraz recovery

Genel "bekleyen siparişlerimi yazdır" eski selection'dan çalışamaz; önce güncel ready
selection okunur. Kullanıcı "bu sipariş ne?", "teslim edilmiş", "emin misin?" veya
"yanlış kayıt" dediğinde pending action askıya alınır/supersede edilir, exact record
authoritative kaynaktan yeniden okunur ve kullanıcı ayrıca istemeden yeni prepare
oluşturulmaz.

### 15.4. Varsayımsal ve açıklama soruları

- "Yazdır desem hangi etiketi sorar mıydın?" -> toolsuz açıklama/clarification;
  label prepare yok.
- "Bu 17 siparişi az önce neden yazdıramadın?" -> son observation/error inspection;
  label prepare yok.
- "Bu onay hangi sipariş için?" -> active `PendingAction` state'inden exact ve minimal
  cevap; eski label selection veya yeni tool yok.

### 15.5. Ready sipariş item aggregation

"17 siparişi listele, neler sipariş gelmiş, en çok hangisi?" yalnız order header ve
kargo toplamı döndüremez. Exact ready selection kurulur; item'lar SKU/ürün bazında
`quantity` ve `order_count` ile aggregate edilir. Pagination ve selection coverage
görünürdür.

### 15.6. Exact sipariş kargosunu değiştirme

"[order] bunun kargo firmasını Aras yapalım" amacı:

1. Exact order resolve/read
2. Doğru Orders cargo-provider option resolution
3. `orders.change_cargo_provider.prepare`
4. Exact order + before/after + environment içeren approval
5. Onay sonrası canonical Orders execute
6. API/domain read-back ve audit

zinciridir.

Şunlar kritik fail-closed ihlalidir:

- `logistics.save_logistics_cargo_provider_record` veya başka domain action seçmek
- Payload'da hedef order kimliği olmaması
- Kullanıcıya yanlış action'ı doğruymuş gibi açıklamak
- "Hangi sipariş için?" sorusunda eski 17-label state'ini göstermek
- "Yalnız bir sipariş" düzeltmesini label prepare'a çevirmek

### 15.7. Return scope ve projection

- Dönem özetindeki `19` return ile tüm zamanların `188` return'ü sessizce karışamaz.
- "Bekleyen kaç iade?" ile kurulan iki-record selection takiplerde korunur.
- "Hangi mağazanın?" yalnız mağaza/account projection'ını verir; claim, order,
  customer ve amount listesi dökmez.
- "Niye iade etmişler?" yalnız aktif iki selected claim'in reason aggregation'ını
  kullanır; bütün tarihsel iadelerin dağılımına genişleyemez.

### 15.8. Cancellation, correction ve stale action

- `Vazgeç` action'ı cancelled yapar ve sonradan onaylanamaz.
- Kullanıcı düzeltmesi eski action'ı supersede eder.
- Düzeltme eski proposal payload'ını yerinde değiştiremez. Eski task/action kalıcı state'te
  `superseded` olur, remaining step'leri temizlenir ve UI yalnız runtime'ın geri döndürdüğü
  canonical persisted state'i gösterir.
- Supersede edilmiş action; eski karttan, sohbetten yazılan `onayla` komutundan, restart
  sonrasından veya elde kalmış action ID'den hiçbir zaman execute edilemez.
- "Dördünü değil bütün bekleyenleri" gibi kapsam düzeltmesinde yeni action ancak güncel
  authoritative ready selection yeniden doğrulandıktan sonra hazırlanır. Model birkaç ID
  önermiş olsa bile exact aktif selection'ın alt kümesi sessizce onaya sunulamaz.
- Correction turu yeni bir business hedefi hâlâ gerektiriyorsa model temiz typed state ve
  supersession observation'ıyla yeniden planlar; Python eski action'ı kopyalayıp yeni action
  diye yayınlayamaz.
- Yeni ve ilgisiz action eski selection'ı otomatik miras alamaz.
- Approval sorusu yeni business action veya fuzzy lookup başlatamaz.

### 15.9. Doğal sohbet doğruluğu

Agent authoritative read yapmadan siparişlerin veya operasyonların "yolunda" olduğunu
iddia edemez. Gündelik sohbete doğal cevap verir; gerçek durum soruluyorsa ilgili read
yapar.

### 15.10. DeepSeek V4 Flash cloud konuşması — frozen control-plane regresyonu

2026-07-22 tarihli gerçek kullanıcı konuşması güçlü bir cloud model kullanılmasına
rağmen başarısız olmuştur. Bu konuşma redacted biçimde baştan sona yeniden oynatılır;
tek tek cümlelere regex/keyword yaması yazmak kabul edilmez. Güçlü modelin de aynı
hataları üretmesi model yetersizliği kanıtı değil, öncelikle runtime/state/tool compiler/
verifier kusuru kabul edilir.

Bağlayıcı hata ve beklenen davranış listesi:

1. "Siparişler hakkında genel bilgi ver" isteği boş bir yönlendirmeyle geçiştirilemez;
   açıklama mı, canlı mağaza özeti mi istendiği bağlamdan çözülür, gerçekten belirsizse
   kısa clarification istenir.
2. "Sipariş sayısı kaç?" `entity=order`, `metric=count`, görünür account/environment,
   uygun status/date/freshness ve `projection=count_only` taşıyan typed intent üretir.
   Basit count için sabit üçlü overview (`ready_to_ship + fulfillment_risk + returns`)
   çalıştırılmaz; tek minimal canonical Orders count operation'ı seçilir.
3. Kullanıcı "güncel veriyi çek" dediğinde fetch/persist ve sonraki count aynı account,
   environment, status, date-window, source revision ve freshness üzerinde read-back
   yapar. Sync sonrası gerçekte `11` görünen set için `0` denmesi kritik source/scope
   tutarsızlığıdır; response verifier cevabı reddetmelidir.
4. Aktif konu siparişlerken "bekleyen kargo sayısı" ifadesindeki `kargo` kelimesi
   `logistics.tariff_count` operasyonuna kaçamaz. Aktif entity ve önceki goal önceliklidir;
   gerçekten iki anlam mümkünse kullanıcıdan kısa ayrım istenir.
5. "Hayır, bekleyen sipariş sayısını sordum" ve "0 olamaz, 11 tane var" mesajları yeni
   selamlaşma değildir. Önceki başarısız observation'a bağlı correction/contradiction
   olayı üretir, hatalı goal/selection askıya alınır ve exact count authoritative
   kaynaktan yeniden planlanır. Kullanıcının `11` demesi çatışma kanıtıdır; tek başına
   authoritative gerçek sayılmaz.
6. Correction sonrası "Naber, nasılsın?" gibi ilgisiz cevap; veri olmadan "vereceğim"
   vaadi; istenen metric yerine farklı bir metriğin sunulması semantic response verifier
   tarafından yayınlanmadan reddedilir.
7. "Siparişlerimi internette ara" private order/account verisini veya kimliğini public
   web query'sine taşıyamaz. Privacy kapısı fail-closed çalışır ve kullanıcıya güvenli
   sınırı açıklar. Yalnız açıkça istenen ürün araştırmasında canonical Orders read ile
   türetilmiş privacy-safe public product identity web'e gönderilebilir.
8. "Hepsiburada kargo fiyatlarını bul" `listing.price_lookup` değildir. Kullanıcının
   istediği güncel public tarife ise web search/open/citation planlanır; kayıtlı yerel
   tarife kastediliyorsa logistics read kullanılır; ayrım çıkarılamıyorsa clarification
   istenir.
9. "Trendyol kargo fiyatlarını bul" için local kayıt ile güncel resmi/web kaynağı
   sessizce karıştırılamaz. Cevap kaynak türünü ve freshness'i görünür söyler.
10. `S?rat`, `Yurti?i` benzeri mojibake kaynak/tool/UI katmanlarından final cevaba
    çıkamaz; encoding bozukluğu acceptance hatasıdır.
11. Correction, konu değişimi, yanlış tool observation'ı ve source contradiction'ı
    agent loop'u bitirmez: `observe -> evaluate -> replan/clarify -> verify -> respond`
    döngüsü hedef doğru çözülene veya açık blocker oluşana kadar sürer.

Bu konuşmanın tamamı önce güçlü cloud modelle control run olarak, sonra erişilebilen en
iyi ücretsiz Gemini ve OpenRouter modelleriyle aynı typed scenario/state üzerinde
çalıştırılır. Her görünür assistant cevabını Codex sırayla inceler. Aynı kök neden için
model veya cümle özelinde yama değil; typed intent/metric/scope compiler, canonical
operation seçimi, correction state'i ve semantic verifier seviyesinde düzeltme gerekir.

### 15.11. Açık uçlu population analizi, kapsam yalıtımı ve metrik kökeni

2026-07-29 tarihli gerçek Gemini 2.5 Flash konuşmasında kullanıcı sync sonrasında
"toplam kaç siparişim var, genel bakınca bu siparişler hakkında analiz yap" demiştir.
Turn interpretation doğru biçimde `count`, `status`, `amount` ve `item_sales_rows`
boyutlarını çıkarmasına rağmen eski runtime yalnız `orders.total_count` requirement'ını
korumuştur. İlk observation sonrası replan; status dağılımını ve gerçek toplam geliri
sessizce düşürmüş, açık uçlu bütün-population hedefini eski seçili iki siparişe daraltmış
ve bu iki ürün satırındaki `199.99` değerini "tahmini ciro" diye yayımlamıştır.

Bu frozen regresyon tek cümleye veya Gemini'ye özel değildir. Aşağıdaki invariant'lar,
aynı yapısal hedefi taşıyan bütün paraphrase ve gelecek kullanıcı soruları için geçerlidir:

1. Açık uçlu bir order-population analizi `record_scope=all_matching` taşır. Kullanıcı
   açıkça exact ID veya aktif seçimi istemedikçe eski `RecordRef`/selection bu hedefe
   bağlanamaz.
2. İstenen her analiz boyutu ayrı typed metric requirement'tır. En az toplam sipariş,
   status dağılımı, toplam gelir, ürün satış özeti ve istenmişse fulfillment riskinin
   authoritative operation/evidence sözleşmesi ayrı kalır.
3. Model planı bütün requirement'ları karşılamıyorsa execution'dan önce reason-coded
   repair gerekir. Deterministic katman kullanıcı adına business workflow uyduramaz;
   yalnız eksik contract coverage'ı reddeder.
4. Observation sonrası replan, tamamlanan adımlar ile yeni remaining graph'in birleşiminde
   bütün karşılanmamış requirement'ları korur. Replan herhangi bir boyutu düşürürse
   reddedilir ve önceki geçerli remaining graph sürdürülür.
5. Ürün satırı `gross_amount`, tek sipariş tutarı, örnek satır veya nested arbitrary
   numeric değer; population toplam geliri değildir. Revenue yalnız
   `orders.revenue_total` contract'ına kayıtlı authoritative alanlardan yayımlanabilir.
6. Ürün satış özeti bütün-population hedefinde `order_numbers` ile daraltılmışsa kabul
   edilmez. Direct item rows ancak aynı record scope ve source snapshot'ı kanıtlıyorsa
   projection'a girebilir.
7. Visible response verifier her requested metric için operation-aware provenance ve
   coverage arar. Bir boyut eksikse uydurma/tahmini sayı yayımlamak yerine eksik kanıtı
   açıkça söyler veya agent loop'u yeniden planlar.
8. Kabul en az üç farklı doğal paraphrase, stale selection fixture'ı, eksik ilk plan,
   requirement düşüren observation replan'i ve nested yanlış tutar fixture'ıyla yapılır.
   Bir tek transcript cümlesine keyword/regex branch eklemek bu regresyonu kapatmaz.

## 16. AI Chat ve Model Hub UI Sözleşmesi

UI'nin görsel tasarım dili onaylanmış ve mevcut uygulama scaffold'una bağlıdır. Agent
runtime dönüşümü sırasında kullanıcı ayrıca istemedikçe tasarım yeniden yorumlanmaz.
Ancak responsive/layout implementasyonu tamamlanmış kabul edilmez. Özellikle sol model
panelinde `Yerel -> Cloud -> Yerel` geçişleri sırasında model listesinin minimum/
maximum yüksekliği, filler/stretch davranışı, splitter genişliği ve scroll alanı bazı
pencere boyutlarında bozulabilmektedir. Runtime için gereken yeni state'ler ve bu
responsive düzeltmeler mevcut component grammar içinde uygulanır.

Authoritative referanslar:

- `desktop/AI/docs/ai-chat-cloud-workspace-concept-v3-scaffold-faithful.png`
- `desktop/AI/docs/ai-chat-local-workspace-concept-v3-scaffold-faithful.png`
- `desktop/AI/docs/ai-model-hub-concept-v3-scaffold-faithful.png`
- Yeniden üretilebilir kaynak:
  `desktop/AI/docs/ai-chat-model-selection-concept-v3-proposal.html`

### 16.1. Chat

- Yerel/Cloud ayrımı mevcut Stok giriş/çıkış tasarım dilini kullanır.
- Yerel modeller doğrudan model adıyla listelenir.
- Cloud modeller provider accordion'u altında; Ücretsiz/Ücretli/Tümü filtresiyle
  listelenir.
- Model, reasoning/zekâ, fallback ve gelişmiş inference ayarları Chat'tedir.
- Gelişmiş ayarlar küçük bağlama bağlı popup'tadır ve yalnız desteklenen parametreleri
  gönderir.
- Model Hub'a gidip model seçme/kaydetme zorunluluğu yoktur.
- Tool event'leri ham debug değil okunabilir observation satırlarıdır.
- Plan ilerlemesi gerektiğinde açılabilir; kullanıcıya iç enum veya chain-of-thought
  gösterilmez.
- Approval, cancelled, superseded, execute ve verify-failed state'leri inline görünür.
- Aktif account/store/environment, selection ve gerçek provider/model kompakt görünür.

### 16.2. Model Hub

Model Hub yalnız:

- Cloud provider credential/account CRUD ve health
- Local model arama, indirme, durdurma, silme ve probe
- Disk/runtime uyumluluk bilgisi

içerir. Aktif model seçimi, free/paid filtre, reasoning, fallback ve generation/runtime
ayarları Model Hub'da bulunmaz.

### 16.3. Görsel kabul

- Testler görünür pencere açmadan offscreen çalışır.
- Authoritative viewport `1800x1100`, `96 DPI` ve deterministic fixture'dır.
- Screenshot, component-tree ve geometry birlikte karşılaştırılır.
- Codex kritik ekranları bizzat görsel olarak inceler.
- Yeni palette, ikon ailesi, shell, kart dashboard veya referans dışı panel düzeni
  kullanıcı kararı olmadan eklenemez.

Önceki offscreen baseline görsel yön için korunur; fakat responsive geçiş kabulünün
yerine geçmez. Yeni bağlayıcı transition matrisi gerçek kaynak widget ve sinyallerini
kullanır:

```text
Chat'i aç
-> Local dolu listeyi yükle
-> kaynak segmentine gerçek click ile Cloud'a geç
-> provider/model listesinin async yerleşmesini bekle
-> anlık source-app screenshot + geometry snapshot al
-> Free/Paid/All ve provider expand/collapse durumlarını dolaş
-> gerçek click ile Local'e dön
-> local selection, scroll, reasoning ve panel geometrisini doğrula
-> aynı Local <-> Cloud döngüsünü art arda en az üç kez tekrarla
```

Her state geçişinde iki ayrı kanıt alınır:

1. Kullanıcı etkileşiminin hemen ardından event queue işlendiğinde alınan **anlık
   screenshot/geometry**; geçiş flicker'ı, sıçrama ve geçici overlap'i yakalar.
2. Async model/provider yüklemesi ve layout tamamen sakinleştiğinde alınan **settled
   screenshot/geometry**; kalıcı responsive sonucu yakalar.

Kabul en az şu viewport/DPI matrisini kapsar:

- Authoritative `1800x1100 / 96 DPI`
- Uygulamanın desteklediği minimum güvenli pencere boyutu
- Orta boy laptop viewport'u
- Geniş ekran viewport'u
- En az `96`, `125%` ve platformca destekleniyorsa `150%` ölçek/DPI davranışı
- Sol splitter kapalı, varsayılan genişlikte ve kullanıcı tarafından genişletilmiş
  durumlar

Her karede machine-checkable olarak şunlar doğrulanır:

- Widget'lar üst üste binmiyor, kesilmiyor ve parent sınırını aşmıyor.
- Chat composer, header ve ana konuşma alanı model paneli yüzünden kaybolmuyor.
- Cloud filtreleri ile local ayarlar birbirinin state'inde görünmüyor.
- Model listesi kullanılabilir alanı dolduruyor; gereksiz sabit boşluk veya aşağı taşma
  oluşturmuyor.
- Scrollbar gerektiğinde var, gerekmediğinde layout genişliğini bozmuyor.
- Segment, provider, model selection ve focus doğru korunuyor veya açık sözleşmeye göre
  sıfırlanıyor.
- Splitter oranı her geçişte büyüyüp küçülmüyor; kullanıcı genişliği korunuyor.
- Advanced popup ekranda kalıyor, kesilmiyor ve doğru modele bağlı açılıyor.
- Loading, empty, error ve dolu liste arasında aynı geometri sözleşmesi korunuyor.

Test fixture'ın private alanlarını doğrudan değiştirerek yalnız son görünümü üretmek
yeterli değildir. En az bir kabul yolu gerçek `click/currentIndexChanged`, async refresh,
signal ve resize event zincirini kullanır. Codex yalnız final similarity skoruna bakmaz;
anlık ve settled source-app screenshot'larının tamamını bizzat açıp inceler. Bir geçişte
görsel sıçrama, taşma veya overlap varsa UI `completed` sayılamaz.

## 17. Test ve Kanıt Stratejisi

### 17.1. Test katmanları

1. Domain unit ve repository testleri
2. Atomic operation contract ve schema testleri
3. Tool retrieval ve semantic planner testleri
   - Önceden özel tool'u olmayan açık uçlu multi-domain/cross-source GoalPlan testleri
4. Typed event/state, selection ve deictic-reference testleri
5. Agent loop, observation, replan ve recovery testleri
6. Policy, approval, cancellation, supersession ve idempotency testleri
7. Semantic action/response verifier testleri
8. Temp DB ve marketplace adapter integration testleri
9. ReportSnapshot, domain aggregation ve XLSX/CSV artifact structural-semantic testleri
10. Offscreen Qt source-widget/source-app testleri
   - Local <-> Cloud gerçek etkileşim ve responsive transition matrisi
   - Her transition için anlık ve settled screenshot/geometry kanıtı
11. Web tool, privacy sanitizer, citation ve prompt-injection testleri
12. Gerçek web search -> open -> kaynaklı cevap ve recovery testleri
13. Gerçek production R0/R1 read ve reversible testleri
14. Trendyol Stage Seller `2738` R0/R1/R2 testleri
15. Gerçek Gemini ve OpenRouter cloud model konuşmaları
16. Önce güçlü cloud referans model kontrolü, ardından aynı frozen senaryolarda
   erişilebilen en iyi ücretsiz cloud model testleri
17. Kullanıcı gözetimli production R2/R3 testi en son
18. Codex'in her görünür assistant cevabını doğrudan incelemesi

Local model konuşmaları mevcut Orders kabul kampanyasına dahil değildir. Cloud kapısı
kapandıktan sonra ayrı bir hedefte yeniden etkinleştirilir.

### 17.2. Unit test tuzağı

Şunlar tek başına agentic başarı değildir:

- Tool fonksiyonunun doğru çalışması
- Bir fixture cümlesinin beklenen tool'u seçmesi
- Pytest'in yeşil olması
- Approval kartının açılması
- Execute'ın exception atmaması
- Otomatik evaluator'ın olumlu puanı
- Eski transcript veya closure JSON'unun `ready` demesi

Testler prompt ezberleyen yeni regex guard'lar üretmemelidir. Aynı anlamın farklı doğal
ifadeleri, takip bağlamı, konu değişimi, itiraz ve beklenmeyen observation'larla
property/scenario tabanlı sınanmalıdır.

### 17.3. Canlı ve uzun sohbet kabulü

Agent aynı oturumda 50, 60, 100 ve gerektiğinde 200+ görünür mesaj boyunca:

- Doğal sohbeti,
- Aktif goal/scope/selection'ı,
- Multi-tool planı,
- Düzeltme ve recovery'yi,
- Pending action yaşam döngüsünü,
- Provider fallback state'ini,
- Topic/domain geçişini,
- İhtiyaç halinde çok adımlı ve kaynaklı web araştırmasını,
- Response projection ve doğal Türkçeyi

koruyabilmelidir.

Codex kapanış kararında her assistant cevabını bizzat ve sırayla okur. Her turda:

- Niyet/mode doğru mu?
- Model gerçekten çağrıldı mı, çağrılmadıysa reason code doğru mu?
- Tool gerekli miydi; doğru ve yeterli atomic tool'lar compose edildi mi?
- Args, scope, selection ve observation doğru mu?
- Agent observation sonrası gerektiğinde yeniden planladı mı?
- Pending action ve approval doğru kayıtlarda mı?
- Final cevap grounded, minimal ve doğal mı?
- PII, uydurma bilgi veya yapılmamış başarı var mı?

soruları değerlendirilir. Her tur `accepted`, `needs_review` veya `failed` kararı ve kısa
gerekçe taşır. Yalnız transcript uzunluğu kabul değildir.

Kritik hata bulunursa:

1. State/tool/planner/verifier zinciri kaydedilir.
2. Aynı oturumda recovery gözlenir.
3. Kök neden mimari sınırda düzeltilir; tek cümleye özel yama yapılmaz.
4. Deterministic ve semantik regresyon eklenir.
5. İlgili canlı konuşma fresh process'te yeniden çalıştırılır.
6. Komşu davranışların gerilemediği doğrulanır.

### 17.4. Model zekâsı ile agent runtime'ını ayırma

DeepSeek V4 sınıfı veya erişilebilen benzer güçlü bir cloud model, manuel UI'da basitçe
yapılabilen bir Orders hedefinde yanlış sipariş kümesini seçiyor, teslim edilmiş siparişi
bekleyen diye ele alıyor, önceki authoritative count/list sonucunu kaybediyor ya da gereksiz
tool'a kaçıyorsa varsayılan açıklama “model yetersiz” olamaz. Önce şu runtime zinciri
incelenir:

```text
capability retrieval
-> typed objective/mode/scope
-> model-authored GoalPlan
-> canonical operation args
-> authoritative observation
-> state/selection hand-off
-> next-action veya replan
-> semantic action verifier
-> grounded response projection
```

Bu ayrım için bağlayıcı kurallar:

- Güçlü/ücretli model yalnız differential-control koşusudur. Aynı hata güçlü ve ücretsiz
  modellerde görülüyorsa ilk şüpheli model değil ortak catalog/state/orchestration/verifier
  katmanıdır.
- Güçlü modelin doğru cevap vermesi de runtime'ı tek başına doğrulamaz; plan, observation,
  exact target set, state devamlılığı, effect ve read-back provenance ile kanıtlanır.
- Ücretsiz modelin yanlış cevabı “free model böyle” denilerek kapatılamaz. Frozen temel
  Orders zinciri her mevcut provider'ın erişilebilen en iyi ücretsiz modeliyle geçmeden
  ürün ücretsiz kullanıcı için güvenilir ilan edilemez.
- Tool seçimi tek başına agentic başarı değildir. Tool gerekli değilken çağrılmışsa, doğru
  tool yanlış scope/set ile çalışmışsa, observation bir sonraki karara taşınmamışsa veya
  final cevap authoritative gerçeğe aykırıysa tur başarısızdır.
- Her failure `retrieval`, `objective/mode`, `planning`, `argument binding`, `domain
  operation`, `observation`, `state continuity`, `replan`, `policy/approval`,
  `semantic verify` veya `response projection` katmanlarından birine kanıtla
  sınıflandırılır. “LLM salak davrandı” kök neden değildir.
- Düzeltme model adına, tek prompt cümlesine veya tek sipariş sayısına özel olamaz. Aynı
  invariant farklı sağlayıcı, model, doğal ifade, cardinality ve takip konuşmasında
  çalışmalıdır.
- Runtime modelden gizlice business plan devralarak testi yeşile çeviremez. Deterministic
  katman schema, safety, scope, canonicalization ve semantic verification ile sınırlıdır;
  bir sonraki business operation kararının sahibi model-led loop'tur.
- Model exact canonical operation'ı ve doğru business argümanlarını üretmişken plan
  validator'ın katalogdan türetilebilen `operation_domain`, owner, risk veya sürüm gibi
  redundant metadata'yı eksik bulup planı düşürmesi model hatası değil control-plane
  contract hatasıdır. Acceptance trace ham model proposal'ını, normalization/enrichment
  sonucunu ve her rejection reason code'unu ayrı taşımadan kök neden kapatılamaz.
- `correct` turunda authoritative güncel amaç kullanıcının son düzeltmesidir. Interpreter
  eski pending action'ın objective'ini kopyalarsa runtime bunu yeni talep gibi kabul edemez;
  eski hedefle eşit stale typed objective'i reddeder, kullanıcı düzeltmesini yeniden modele
  verir ve eski action'ı terminal `superseded` durumda tutar. Bu koruma yeni TANEX modeli,
  kayıt kümesi veya scope'u deterministic olarak icat etmez; yeni business kararı modelin
  güncel mesajdan kurduğu planda görünmelidir.
- Typed mode/objective, active correction target ve model-authored canonical operation
  kurulduktan sonra legacy `_goal_has_*_intent` veya keyword guard raw kullanıcı cümlesini
  yeniden parse ederek semantik kararı veto edemez. Kullanıcı “etiket” sözcüğünü tekrar
  yazmadan “2736 değil 2610 olarak düzelt” diyebilir; aktif label proposal bağlamı typed
  state'tedir. Keyword/alias katmanı aday retrieval'a yardım edebilir, fakat schema-valid
  model planı için ikinci bir business-authority kapısı olamaz.

### 17.5. Evidence

Evidence en az şunları taşır:

- Source app ve source fingerprint
- Tarih, environment ve account alias
- Her tur requested/actual provider-model ve fallback
- Mode/objective ve planner çağrı gerçeği
- Candidate operations ve seçilen operation
- Tool args, observation ve verifier kararı
- Web kullanıldıysa query redaction, URL, freshness, citation ve injection-policy kararı
- Selection/pending-action/task state hash'leri
- Prepare/execute/verify RecordRef eşitliği
- Görünür cevap ve doğrudan Codex değerlendirmesi
- Redaction sonucu

Secret ve gereksiz PII evidence'a giremez.

## 18. Güncel Gerçek Durum

| Alan | Durum | Güncel gerçek |
|---|---|---|
| Ürün vizyonu ve domain sınırları | `verified_baseline` | Hedef doğru tanımlı; uygulama henüz bu hedefte değil. |
| Canonical manuel Orders domain işlemleri | `bounded_source_chat_execute_readback_proven / live_sync_provider_open` | Offscreen source Chat ürün yolunda sync generic manual route yerine model-authored `orders.fetch.prepare` ile exact Stage account kapsamına bağlandı; persisted approval/resume aynı DB bağlamında fake Stage source -> save -> 2/2 verified read-back zincirini tamamladı. Aynı ürün yolunda exact 11 label seti approval sonrası canonical Labels pipeline ile temp DOCX'e dönüştü ve içerik read-back'i 11/11 geçti. Gerçek provider ile aynı zincir yeniden kabul edilmeden alan tamam değildir. |
| Tool/operation catalog zemini | `current_gemini_proven / openrouter_external_gate` | Typed schema ve canonical callable zemini mevcut. Fresh R27 Gemini source-app koşusunda `orders.ready_to_ship_count -> orders.query -> labels.create_from_orders.prepare` atomik zinciri ve aynı operation üzerindeki 2736 -> 2610 correction generic manual route olmadan model tarafından seçildi. Aynı source fingerprint'indeki R22 OpenRouter turu planning başlamadan account-scope `429` aldığı için ikinci-provider kanıtı dış kota engelinde açıktır. |
| Planner ve intent control plane | `current_gemini_correction_proven / openrouter_external_gate` | Typed-evidence guard, katalogdan authoritative metadata enrichment, keyword tekrarsız typed correction authorization ve active-target ile zenginleştirilmiş candidate retrieval fresh Gemini R27'de birlikte geçti. Model exact 12 kayıt için önce TANEX 2736, sonra kullanıcı düzeltmesiyle TANEX 2610 planını doğru yazdı; runtime doğru ilk planı legacy keyword guard ile reddetmedi. OpenRouter current-source R22 account-scope `429` nedeniyle modele ulaşamadı. |
| Birleşik agent loop | `current_gemini_frozen_correction_chain_proven / phase8b_and_openrouter_open` | Fresh R27 gerçek Gemini source-app zincirinde count 12 -> exact list 12 -> TANEX 2736 prepare -> keyword tekrarsız 2610 correction -> provider-free pending read -> eski action ID'nin effectsiz stale rejection'ı -> yalnız güncel action approval -> yerel DOCX execute/read-back geçti. Eski ve yeni immutable kimlikler ayrıldı; içerik 12/12 doğrulandı. OpenRouter eşdeğeri ve Faz 8B organik uzun regresyonları hâlâ açıktır. |
| Typed conversation/selection/action state | `proven` | Typed turn/scope/selection/observation/pending-action/task/GoalPlan restart ve stale action yaşam döngüsü testlidir. Persisted approval resume aynı DB kapsamıyla birlikte secret-free, hash'li provider/model/fallback/capability policy snapshot'ını da korur; değiştirilmiş snapshot provider çağrısından önce reddedilir. |
| Semantic action verifier | `proven` | Mode-objective-domain-operation, exact target set, tam action fingerprint, freshness ve Orders eligibility read-back prepare/approval/execute sınırlarında fail-closed testlidir. |
| Response grounding/projection/privacy | `r473_focused_read_projection_proven / fresh_organic_50_required` | 6 Eylül yeniden denetimi önceliklidir. R469 kullanıcı başlangıcı/mağaza/bağlamsal sayım için dar kabul; güncel R473 kaynak uygulamada Stage570 özeti ve exact48 tam liste için accepted=true. Aynı48 kimlik,48 sıra ve doğru kayda bağlı67 kalem bağımsız yerel okumayla doğrulandı; final model cevabı doğrulanmıştır. Çok hesaplı veri, bütün final yolları, artifact/web ve fresh50+ organik kabul açıktır. Ayrıntı güncel yeniden denetim artifact'ındadır. |
| Orders read/selection/aggregation parity | `current_gemini_exact_set_proven / openrouter_external_gate` | Fresh fallback-kapalı Gemini R27 source-app koşusunda dinamik hazır count `12` ve devamındaki exact aynı 12 sipariş listesi current fingerprint üzerinde doğrulandı; selection correction ve artifact kapsamına kayıpsız taşındı. OpenRouter current-source tekrarı account-scope kota nedeniyle modele ulaşamadığından provider matrisi tamam değildir. |
| Orders ad-hoc rapor ve Excel artifact yeteneği | `proven` | Orders-owned immutable privacy-minimal ReportSnapshot, Core-owned atomic XLSX renderer, formula-injection koruması ve exact read-back ile son üç hafta en çok satanlar zinciri çalışıyor. |
| Orders + web + artifact açık uçlu composition | `orders_input_proven / web_phase_7_open` | Latest exact order -> item -> privacy-safe public product identity girdisi kanıtlandı; gerçek web research, citation ve ResearchReportSnapshot Faz 7'de kurulacak. |
| Orders label zinciri | `current_gemini_12_of_12_execute_readback_proven / openrouter_external_gate` | Fresh R27 Gemini source-app koşusunda exact 12'li aktif seçim önce TANEX 2736 hazırlığına, ardından aynı set korunarak TANEX 2610 replacement'a bağlandı. Effect-bearing template değişikliği action ID/fingerprint'i döndürdü; eski ID açıkça gönderildiğinde effectsiz reddedildi, yalnız yeni action onaylandı. Fiziksel baskı ve pazaryeri mutasyonu olmadan yerel DOCX üretildi ve canonical payload + DOCX içerik read-back'i 12/12 geçti. OpenRouter eşdeğer current-source zinciri kota nedeniyle açıktır. |
| Orders kargo değiştirme zinciri | `control_plane_proven / stage_live_open` | Exact target, doğru Orders operation, before/after payload, approval, execute ve verify deterministic testlidir; Trendyol Stage kanıtı Faz 8'de alınacaktır. |
| Provider adapter ve capability zemini | `current_gemini_proven / openrouter_paid_access_proven_and_free_tier_gate_open` | Gemini structured/native, OpenRouter guarded JSON/reasoning ve llama.cpp local text-guarded yolları ortak capability contract üzerindedir. R22/R63 `:free` 429'ları Karar 60 ile `free_tier` scope'una ayrılmıştır. Eski zero-credit/402 kanıtı tarihsel kalmıştır: 2026-08-11 secret-safe fallback-kapalı exact probe `deepseek/deepseek-v4-flash` modelinden doğru actual-model kimliğiyle cevap almış; billing, quota veya provider hatası oluşmamıştır. Paid erişim artık açıktır; ücretsiz OpenRouter acceptance kapısı ayrıdır. |
| Cloud/free full-agentic baseline | `current_gemini_frozen_correction_chain_proven / openrouter_paid_control_accessible_and_free_baseline_open` | Current-source R27 Gemini, exact Orders okuma, correction/supersession, eski ID stale rejection, yalnız güncel approval ve yerel DOCX 12/12 read-back zincirini fallback olmadan tamamladı. R69 Gemini focused R66 turunda model-authored/repaired multi-metric plan ve eksiksiz deterministic verified projection geçti; final provider synthesis 429 olduğu için full provider kabulü değildir. OpenRouter paid kontrol rotası için exact `deepseek/deepseek-v4-flash` erişimi 2026-08-11'de kanıtlanmıştır; ancak bu mikro erişim probu full-agentic acceptance değildir ve OpenRouter ücretsiz baseline'ının yerine geçmez. Local inference kullanıcı kararıyla ayrı sonraki hedefe ertelenmiştir. |
| Web search agentic yeteneği | `bounded_phase_7_proven / live_routing_failed` | Atomic web ailesi ve privacy sınırı deterministic olarak mevcut; fakat gerçek cloud konuşmasında private siparişleri web'de arama ve Hepsiburada kargo fiyatını listing'e yönlendirme hataları görüldü. Bölüm 15.10 canlı kabulü açıktır. |
| Trendyol Stage erişimi | `live_sync_source_proven / agentic_reverify_open` | Seller `2738` hard isolation ile gerçek atomic sync çalıştı; 34 kaynak satırından 32 kalıcı paket exact DB read-back ile doğrulandı. Kimliksiz 2 non-actionable `Awaiting` satırı için uydurma ID üretilmedi; domain policy-exclusion ayrımı deterministic testlidir. Aynı dış çağrı tekrarlanmadan mevcut kanıtla verifier replay ve sonraki cloud ürün-yolu kabulü açıktır. |
| Chat ve Model Hub görsel dili | `verified_baseline / frozen_design` | Onaylı v3 scaffold referansları korunur; kullanıcı istemeden yeniden tasarım yapılmaz. |
| Chat responsive ve Local <-> Cloud geçişleri | `open` | Bazı boyutlarda geçiş sonrası model paneli/list/filler/splitter geometrisi bozuluyor; gerçek click ve anlık source-app screenshot matrisiyle sertleştirilecek. |
| Production R2/R3 | `deferred_supervised` | En son kullanıcı gözetiminde veya operator-executed. |
| Orders genel kilometre taşı | `open / foundation_restart / fresh_phase8b_organic_50_required` | Kullanıcının6 Eylül bildirimiyle temel denetim yeniden açıldı; mevcut çalışma ağacı korundu. Gerçek kapsam tek Stage hesabı ve570 sipariş. R473 seçili regresyon614 passed/449 skipped/112 subtests; kabul altyapısı28 passed/6 subtests. R469 veR473 yalnız sınırlı okuma kanıtlarıdır. Eski yönlendirici, çok hesaplı kapsam, fresh50+ organik, effect/read-back, artifact/web, ücretsiz providerlar ve diğer domainlerin kapanışı açıktır. |
| Genel AI hedefi | `in_progress / cloud_first_phase_8` | Typed zemin mevcut; gerçek DeepSeek V4 Flash konuşması control-plane ve recovery açıklarını gösterdi. Orders uçtan uca cloud-first yeniden kabul edilecek; local testler şimdilik ertelendi. |

## 19. Yeni Hedef Açıldığında Zorunlu Uygulama Sırası

Bu sıra bağlayıcıdır. Kullanıcı ayrıca istemedikçe ilk fazlarda UI redesign veya başka
domain yayılımına geçilmez.

### 19.0. 2026-07-22 bağlayıcı stabilizasyon reseti

Gerçek DeepSeek V4 Flash konuşması, çok sayıda altyapı parçasının ve testin geçmesinin
ürünün agentic olarak doğru çalıştığını kanıtlamadığını göstermiştir. Aşağıdaki kararlar
önceki `proven`, test sayısı veya closure artifact'larından üstündür:

1. **Yeni yetenek ekleme durur.** Dar Orders çekirdeği kapanmadan yeni provider,
   operation/tool ailesi, web/report genişletmesi, UI polish veya başka domaine yayılım
   yapılmaz. Daha önce yazılmış web/Excel yeteneği silinmez; yalnız kabul sırasının
   arkasına alınır.
2. **İlk dikey dilim sabittir:** current/fresh Orders sync -> ready/pending count ->
   exact list/RecordRef seti -> aynı setten label prepare -> approval -> execute ->
   authoritative read-back. Her adım aynı account, environment, status, date-window,
   source revision ve selection fingerprint'i taşımalıdır.
3. `count N = list N = selection N = prepare N = execute N = read-back N = audit N`
   invariant'ı tek gerçek kaynak snapshot'ı üzerinde sağlanmadan başka capability
   tamamlanmış sayılmaz.
4. **Correction/recovery ikinci zorunlu çekirdektir.** "Hayır onu sormadım", "0 olamaz,
   11 var", "bu sipariş ne?" ve "teslim edilmiş siparişi niye seçtin?" gibi itirazlar
   önceki goal/observation/action'a bağlanır. Runtime yanlış sonucu finalleştirmek yerine
   `observe -> evaluate -> replan/clarify -> verify` döngüsünü gerçekten sürdürür.
5. Modelin planı keyword/fuzzy router veya sabit overview template'i tarafından sessizce
   ezilemez. Deterministic kod business intent seçmez; policy, schema, exact binding,
   eligibility, privacy ve semantic verification sınırını uygular.
6. Tool'un exception atmaması, approval kartının görünmesi, execute cevabının `ok`
   olması, pytest'in yeşil olması veya closure JSON'u başarı değildir. Başarı; doğru
   intent, doğru kaynak/scope, doğru exact kayıt kümesi, doğru observation, gerektiğinde
   replan ve authoritative veriyle uyuşan final cevabın birlikte kanıtlanmasıdır.
7. Her frozen gerçek konuşmada bağımsız bir source-truth oracle kurulur. Her assistant
   cevabı Codex tarafından sırayla okunur; sayı, ID-set, status, mağaza, environment,
   freshness, tool args ve final iddia oracle ile karşılaştırılır. Tek kritik uyuşmazlık
   kampanyayı durdurur ve o kök neden kapanmadan ilerlenmez.
8. Tek cümleye/model adına özel regex yaması yasaktır. Düzeltme typed intent/metric/
   scope/freshness compiler, state transition, canonical operation contract, observation
   evaluator veya semantic response verifier katmanında yapılır ve paraphrase/komşu
   senaryolarla sınanır.
9. **Cloud-first sıra değişmez:** önce güçlü capability-compatible cloud model kontrol
   koşusu, sonra aynı frozen testler erişilebilen en iyi ücretsiz Gemini/OpenRouter
   modellerinde çalışır. Local inference mevcut stabilizasyon hedefinin dışındadır.
10. Dar Orders çekirdeği ve correction/recovery kapısı geçtikten sonra sırasıyla diğer
    manuel Orders işlemleri, web araştırması, Excel/artifact composition ve uzun sohbet
    kabulü yeniden açılır. Bu sıra atlanamaz.
11. **Ürün yolu tek kabul yoludur.** İzole harness, doğrudan tool çağrısı, synthetic
    planner veya test-only state ile geçen senaryo yalnız önkoşul kanıtıdır. Aynı istek;
    gerçek Chat orchestration girişi, seçili provider/model, gerçek DB/account scope'u,
    persisted session ve kullanıcıya gösterilen final cevap üzerinden fresh process'te
    geçmeden ürün davranışı `proven` olamaz. UI penceresi açmak gerekmez; offscreen test
    aynı source-app kod yolunu çalıştırır.
12. **Model-authored karar kanıtı zorunludur.** Evidence her anlamlı adım için modelin
    gördüğü objective/state/observation özetini, getirilen operation adaylarını, modelin
    seçtiği next action'ı ve deterministic katmanın yalnız doğrulama/normalizasyon
    müdahalesini ayırır. Python'ın tamamladığı template planı `llm_direct`, `replan` veya
    model başarısı diye raporlanamaz.
13. **Canlı hata statüyü yeniden açar.** Unit/integration test sayısı, eski acceptance
    artifact'ı veya önceki model koşusu daha yeni gerçek kullanıcı başarısızlığını
    geçersiz kılamaz. Son canlı hata önce frozen regresyona, sonra kök invariant'a ve en
    son aynı gerçek ürün yolundaki cloud tekrarına bağlanır.
14. **Orders sync de atomic bir domain operasyonudur.** `fresh/current/güncel veriyi çek`
    hedefi generic `operations.manual_action.route` ile fuzzy eşlenemez. Exact account ve
    environment alan `orders.fetch.prepare -> approval -> canonical domain execute ->
    authoritative verify` zinciri kullanılır; Production ve Stage hiçbir aşamada
    birbirine genişleyemez.
15. **Boş kaynak da kanıt ister.** Marketplace sync sonucu sıfır kayıt olsa dahi başarı,
    yalnız tamamlanmış kaynak çağrısı, exact account/environment, kapsanan zaman aralığı,
    fetched ID/count, source revision/snapshot ve DB reconciliation kanıtıyla kapanır.
    `source snapshot` eksikliği başarıya çevrilemez ve aynı external çağrı kök neden
    çözülmeden körlemesine tekrarlanamaz.

Bu resetin amacı daha fazla tool eklemek değil; mevcut tool'ları ve domain
operation'larını gerçek bir goal-directed loop içinde doğru compose eden, observation'ı
hedefe karşı değerlendiren ve yanlışsa yeniden planlayan kontrol düzlemini kanıtlamaktır.

### 19.0.1. 2026-07-26 bağlayıcı ürün zekâsı ve çalışma disiplini kararları

Mevcut durumda çok sayıda altyapı parçası ve deterministic test geçmiş olsa da kullanıcı
karşısındaki ürün henüz kabul edilmiş bir agent değildir. Kullanıcının "hâlâ salak gibi"
gördüğü davranış, test sayısıyla veya daha güçlü bir model adıyla örtülemez. Bundan sonraki
çalışma aşağıdaki kararlara tabidir:

1. **Başarı bir altyapı toplamı değil, kullanıcı hedefinin gerçekleşmesidir.** Typed state,
   operation catalog, approval kartı, verifier, audit ve yeşil testler gerekli altyapıdır;
   fakat gerçek cloud model gerçek Chat yolunda doğru hedefi anlayıp doğru kayıt kümesinde
   işi tamamlamadıkça ürün akıllı veya hazır sayılmaz.
2. **Tek bağlayıcı ölçüm görünür uçtan uca davranıştır.** Kullanıcının yazdığı mesajdan
   kullanıcıya gösterilen son cevaba ve üretilen artifact'a kadar bütün zincir aynı anda
   doğru olmalıdır. Aradaki herhangi bir katmanın kendi testini geçmesi, yanlış son cevabı
   telafi etmez.
3. **Synthetic/fixture model zekâ kanıtı değildir.** Cloud-contract fixture, fake provider,
   doğrudan runtime/harness veya önceden beklenen planı döndüren test modeli yalnız
   deterministic sözleşmeleri sınar. Bunların sonucu `model_quality_proven`,
   `real_agentic_acceptance` veya ürün kapanışı diye adlandırılamaz.
4. **Gerçek cloud cevap gelmeden model kabulü yoktur.** Kota, transport, 404, timeout,
   schema veya provider hesabı yüzünden model yanıtı alınamadıysa sonuç fail-closed bir
   erişim kapısıdır; başarı değildir. Kota kapalıyken rastgele model tüketilmez ve
   deterministic recovery gerçek model başarısı gibi gösterilmez.
5. **Önce güçlü cloud kontrolü, sonra ücretsiz cloud ürün şartı uygulanır.** Erişilebilen
   güçlü capability-compatible model aynı frozen senaryoda runtime ile model kalitesini
   ayırmak için kullanılır. Ardından Gemini ve OpenRouter üzerindeki en iyi erişilebilir
   ücretsiz modeller aynı senaryoyu geçmelidir. Güçlü modelin geçmesi ücretsiz model
   kabulünün yerine geçmez; ücretsiz modellerin geçemediği özellik "ücretsiz çalışıyor"
   diye sunulamaz. Kullanıcı açıkça onaylamadan ücret harcanmaz.
6. **Local inference bu kampanyada yoktur.** Local mimari desteği korunur; ancak Orders
   cloud kabulü tamamlanıncaya kadar local model sunucusu, local inference, local uzun
   sohbet ve local kalite karşılaştırması çalıştırılmaz. Local yavaşlığı veya model
   kalitesi mevcut kök nedeni gölgeleyemez.
7. **Model gerçekten karar verir, runtime gerçekten sınırlar.** Model typed hedef ve
   observation'dan sonraki atomic operation'ı, gerekirse clarification veya replan'i
   seçer. Runtime schema, izin, risk, scope, exact kayıt bağlama, eligibility, privacy,
   approval ve semantic doğrulama uygular; modelin yerine iş planı yazmaz veya yanlış
   planı sessizce doğruymuş gibi tamamlamaz.
8. **Tool sayısı değil, compose edilebilir canonical yetenek önemlidir.** Tool'lar küçük
   sorumluluklu, zengin typed parametreli ve domain-owned canonical operation'ların ince
   AI sarmalayıcılarıdır. Manuel UI'da yapılabilen işte aynı domain fonksiyonu kullanılır.
   Gerekli business fonksiyonu yoksa önce sahibi domainde headless ve testli olarak
   tasarlanır; AI içine kopyalanmaz. Tek kullanıcı cümlesi için mega-tool yazılmaz.
9. **Her kritik observation'dan sonra hedef yeniden değerlendirilir.** Agent tek tool
   çağırıp duran bir router değildir. Okunan sayı, bulunan kayıtlar, source çelişkisi,
   approval sonucu, execute sonucu veya verifier hatası modele güvenli typed observation
   olarak döner; model hedef bitti mi, yeni adım mı gerekli, düzeltme mi, clarification mı
   gerektiğine karar verir.
10. **Bir hata kapanmadan yeni genişlik açılmaz.** Frozen gerçek sohbetin tek bir turunda
    yanlış sayı, yanlış sipariş, yanlış status, yanlış mağaza/environment, stale selection,
    gereksiz tool, eksik replan veya gerçekle uyuşmayan final cevap görülürse kampanya o
    noktada durur. Önce trace üzerinde kök neden bulunur, genellenebilir katmanda düzeltilir,
    komşu/paraphrase regresyonları geçer ve aynı gerçek cloud ürün yolu yeniden sınanır.
11. **Codex her cevabı bizzat denetler.** 50/60/100/200+ turluk kampanyalarda yalnız final
    özet veya test exit code'u okunmaz. Her kullanıcı mesajı, model kararı, tool argümanı,
    observation, state transition, approval kapsamı ve görünür cevap source-truth oracle
    ile sıra sıra karşılaştırılır. Kritik bir hata varken sohbetin kalanını çalıştırıp
    başarı yüzdesi üretmek yasaktır.
12. **İlk kapanacak kullanıcı hikâyesi değişmez.** Fresh Orders sync -> hazır/bekleyen
    count -> exact aynı siparişlerin listesi -> kullanıcının referans verdiği aynı setten
    TANEX şablonuyla label prepare -> approval -> canonical execute -> DOCX içerik
    read-back -> audit zinciri gerçek cloud Chat yolunda birebir geçecektir. Delivered,
    cancelled, simulation veya başka mağaza/environment kaydı hiçbir aşamada kümeye
    sızamaz.
13. **Correction ve scope değişikliği birinci sınıf davranıştır.** "Bunları", "hepsini",
    "4 değil bütün bekleyenleri", "bu sipariş ne?", "teslim edilmiş olanı niye seçtin?"
    gibi devam mesajları raw geçmiş aramasıyla değil typed goal/selection/pending-action
    state'iyle çözülür. Eski pending action yeni kapsam tarafından açıkça `superseded`
    edilir; eski kart ve action ID sonradan çalışamaz.
14. **UI kalite işi kabul sırasının sonundadır.** Orders gerçek cloud doğruluğu kapanmadan
    görsel polish ana çalışma konusu yapılmaz. UI aşamasında mevcut Core workspace
    scaffold'u, renk/ikon/component dili korunur; local/cloud geçişi, provider accordion,
    filtreler ve gelişmiş ayarlar görünür pencere açmadan offscreen ölçüm ve anlık
    screenshot karşılaştırmalarıyla responsive olarak doğrulanır.
15. **Provider yokluğu kullanıcı belirsizliği değildir.** Model kotası, provider
    erişimsizliği, timeout veya tekrarlanan boş cevap `needs_clarification` diye
    kullanıcıya geri sorulamaz. Typed sonuç `provider_unavailable` veya
    `model_unavailable` olur; plan, approval ve effect üretmeden provider/model adı,
    güvenli neden ve tekrar koşulu görünür biçimde raporlanır.
16. **Bağlamdaki exact seçim yeniden yazdırılmaz, referans edilir.** "Bu 11 sipariş",
    "bunları" veya "az önce listelediklerin" gibi takiplerde model opaque sipariş
    numaralarını tahmin etmek, placeholder üretmek ya da geçmiş metinden yeniden toplamak
    zorunda bırakılmaz. Model doğru atomic operation ile aktif typed selection referansını
    seçer; runtime yalnız aynı account/environment, exact record set, source revision ve
    snapshot hash doğrulanırsa bu immutable seçimi argümanlara bağlar. Bu doğrulama
    sessiz kapsam düzeltmesi veya modelin yerine plan kurmak değildir.
17. **Boş model cevabı başarıya çevrilemez.** Fallback kapalı exact model ilk çağrıda boş
    içerik döndürürse aynı invocation contract ile en fazla bir bounded same-model retry
    yapılabilir. İkinci boş cevapta model değiştirilemez, deterministic business plan
    kurulamaz ve güvenli canonical read sonucu model başarısı diye yayımlanamaz; tur
    effectsiz `model_unavailable` kapanır.
18. **Kullanıcı cevabı bir iç sözleşme dökümü değildir.** `period_label`,
    `api_account_ids`, `query_fingerprint`, `source_revision`,
    `source_snapshot_hash`, internal operation/action ID veya verifier alanları kullanıcı
    özellikle teknik kanıt istemedikçe görünür cevaba sızamaz. Final cevap doğal insan
    dilinde, source-truth ile uyumlu ve işi sürdürmeye yeterli olmalıdır.
19. **Semantic red, güvenli olsa da kabul başarısı değildir.** Model doğru operation'ı
    seçse bile uydurma `<order-001>` benzeri target, yanlış template alanı veya
    doğrulanamayan kapsam üretirse runtime bunu fail-closed reddeder. Sonraki çözüm
    cümleye özel regex, mega-tool veya deterministic doğru plan eklemek değil; typed
    selection reference, catalog schema, model prompt'u ve semantic compiler sözleşmesini
    bütün benzer takipleri çözecek biçimde düzeltip aynı gerçek cloud ürün yolunu yeniden
    çalıştırmaktır.
20. **Model ile runtime hatası trace üzerinde ayrılır.** Güçlü veya ücretsiz model typed
    objective'i, operation'ı ve gerçek kayıt kimliklerini doğru üretmişken ortak intent,
    policy, schema compiler, selection rebind veya response projection katmanı bunu
    reddediyorsa hata modele yazılmaz. Özellikle doğal Türkçe çekim/isim-fiil biçimleri
    (`hazırlığını yap`, `hazırlık oluştur` gibi) tek cümleye özel router eklenerek değil,
    ortak pozitif-prepare dil primitive'iyle çözülür; raw negatif ve read-only güvenlik
    sınırları aynı regresyon paketinde korunur.
21. **Pending approval hakkında soru kapsam değişikliği değildir.** Kullanıcı “bu hazırlık
    hangi siparişlere/şablona bağlı?”, “dosya üretildi mi?” veya “tam olarak ne yapacak?”
    diye sorarsa agent immutable pending-action state'ini read-only açıklar; mevcut kart,
    action ID, selection ID/hash ve onaylanabilirlik korunur. Yalnız açık iptal, onay veya
    gerçek kapsam düzeltmesi eski action'ı terminal duruma taşır. Salt açıklama sorusunun
    kartı `superseded` etmesi ve ardından hâlâ onay bekliyormuş gibi konuşulması kritik
    state/cevap çelişkisidir ve kampanyayı durdurur.
22. **Kota geçişi scope'a ve çalışma moduna bağlı, açık ve izlenebilirdir.** Normal ürün
    runtime'ında yalnız normalize edilmiş `quota_scope=model` ve
    `model_fallback_allowed=true` sonucu aynı provider'ın capability-compatible sıradaki
    en güçlü ücretsiz modeline otomatik geçişe izin verir. `project`, `account`,
    `provider`, `billing`, `auth`, `policy` veya `unknown` kapsamı bütün kardeş-model
    denemelerini durdurur. Buna karşılık exact-model kabul koşularında scope ne olursa
    olsun fallback kapalıdır; model-specific limit varsa sıradaki model ancak Codex'in
    başlattığı ayrı, açıkça pinlenmiş fresh-process kampanyada sınanır. Her invocation'ın
    quota scope'u, geçiş/duruş kararı ve requested/actual modeli append-only provenance'da
    korunur.
23. **Redacted artifact model trace'iyle karıştırılmaz.** Kanıt dosyasındaki
    `<order-001>` gibi değerler privacy redactor tarafından gerçek kimlikler yazılmadan
    önce/sonra maskelenmiş olabilir. “Model placeholder uydurdu” teşhisi ancak pre-redaction
    runtime state, planner cevabı ve semantic compiler girdisi birlikte okunarak konur.
    Redacted görünüm tek başına kök neden değildir.
24. **Pending-action açıklaması provider işi değil, typed control-state okumasıdır.** Aktif
    bir onay kartı varken kullanıcı yalnız “hangi siparişler?”, “hangi şablon?”, “dosya
    üretildi mi?” veya “tam olarak ne olacak?” diye soruyorsa bu mesaj provider
    interpretation'ından önce immutable pending-action state'ine karşı read-only çözülür.
    Model/provider çağrısı, Orders/Labels business tool'u, API, DB veya dosya etkisi
    çalışmaz; action/selection kimliği, payload hash'i, kart ve onaylanabilirlik aynen
    korunur. Görünür cevap exact kapsamı, şablonu, henüz etki oluşmadığını ve işlemin hâlâ
    onay beklediğini doğal dille söylemelidir. Bu yol modelin yerine business plan kuran
    fallback değil, uygulamanın kendi açık kontrol durumunu okumasıdır.
25. **Provider hatası kullanıcının hedefini veya operation'ını değiştiremez.** İstenen
    model `404/429`, timeout, transport, schema ya da boş cevap yüzünden karar üretemediyse
    runtime sırf kullanıcıya bir şey göstermek için `orders.query`, count, lookup, sync,
    prepare veya başka bir canonical business operation çalıştıramaz. Yalnız kullanıcının
    aynı read-only sorusu daha önce doğrulanmış typed state'ten eksiksiz cevaplanabiliyorsa
    effectsiz state projection yapılabilir; bunun dışında tur
    `provider_unavailable/model_unavailable` kapanır. Başka intent'e ait güvenli bir tool
    sonucu, provider başarısızlığının recovery'si sayılamaz.
26. **“Success” zarfı değil, semantik olarak doğru sonuç kabul edilir.** Runtime'ın
    exception atmaması, bir tool'un başarı dönmesi veya pending kartın korunması tek başına
    tur başarısı değildir. Final-response verifier kullanıcının istediği alanları, aktif
    goal/pending state'ini, seçilen operation'ın soruyla ilgisini ve iddia edilen etkileri
    birlikte doğrular. Pending hazırlığı sorusuna sipariş arama sonucu vermek gibi alakasız
    fakat teknik olarak başarılı cevap kritik ürün hatasıdır ve frozen kampanyayı durdurur.
27. **Exact kayıt kümesinde gizli sayfalama ve eksik materialization yasaktır.** Model
    exact `N` record ID istediğinde limit verilmemiş olması ortak wrapper'ın varsayılan
    `10` sınırıyla kümeyi sessizce daraltamaz. Runtime exact-set cardinality'yi görünür
    biçimde bağlayabilir; observation `requested`, `returned`, `missing`, `unexpected`,
    `listed_count` ve truncation bilgisini taşır. Materialize edilen kayıt kümesi istenen
    exact kümeyle birebir eşleşmeden yeni selection, follow-up referansı, approval veya
    artifact kapsamı üretilemez. Bu deterministic cardinality bağlama kapsam icat etmek
    değil, modelin seçtiği exact kapsamı kayıpsız uygulamaktır.
28. **Çok çağrılı bir turda provider provenance son çağrı tarafından ezilemez.** Turn
    interpretation, plan, observation sonrası karar/response ve bounded repair ayrı model
    invocation'larıdır. Her biri append-only olarak invocation contract, requested/actual
    model, response-received, error, fallback ve amaç bilgisi taşır. İlk iki çağrı başarılı
    olup son synthesis `429` verdiğinde tur “model hiç cevap vermedi” diye yazılamaz; aynı
    şekilde son çağrının başarısı önceki hatayı silemez. Tur seviyesi özet `any response`,
    `final response` ve `accepted semantic output` gerçeklerini ayrı gösterir.
29. **Uzun konuşmada invocation provenance turlar arasında sızamaz veya kesilemez.** Aynı
    provider client'ı 50/60/100/200+ mesaj boyunca yeniden kullanılsa bile her Chat turu
    yalnız kendi başlangıcından sonra oluşan invocation dilimini raporlar. Önceki turun
    başarılı cevabı model çağrısı olmayan yeni turu model-backed gösteremez; önceki hata da
    yeni turun başarısını kirletemez. Provider'ın append-only ham ledger'ı kabul kampanyası
    içinde son `N` kayda kırpılmaz; turn evidence yalnız kendi slice'ını taşır. Böylece hem
    geçmiş kaybolmaz hem artifact'lar kümülatif geçmişi her turda tekrar ederek şişmez.
30. **Configured/requested model actual model kanıtı değildir.** Runtime ve persisted task
    context'i ancak response-received bir invocation'ın
    `last_successful_actual_model` değerini actual model olarak pinleyebilir. Sıfır model
    cevabı + `429/404/timeout` durumunda client'ın `model_name` alanı actual diye
    yazılamaz. Önceki invocation cevap verip final synthesis başarısız olduysa görev
    devamlılığı son başarılı actual modeli korur; final actual model ve final error ayrıca
    boş/hatalı olarak raporlanır.
31. **Kapanış belgeleri en yeni binding regression'dan eski kanıtla `ready` olamaz.**
    `current_acceptance_manifest` current phase, latest binding regression,
    `acceptance_status`, `closure_ready`, current diagnostic/proven slice ve evidence
    contract sürümünü açıkça taşır. Tarihî hash-verified artifact'lar baseline olarak
    korunabilir fakat current proven slice'a sessizce alınamaz. Orders closure ancak
    manifest structurally valid olmanın yanında `ready_for_closure=true`, current
    regression'lar resolved, Phase 8 source-UI kapıları v6 ve goals bölüm audit'i eksiksiz
    olduğunda kapanabilir. `open` manifest ile `closure_ready=true`, eski schema/scope veya
    local/paid-only kanıt fail-closed reddedilir.
32. **Planner yalnız semantic kararları yazar; katalog metadata'sı tek kaynaktan bağlanır.**
    Model exact canonical `operation_id` ve schema-valid business argümanlarını seçtiyse
    `operation_domain`, owner, risk, contract version veya approval policy'yi ayrıca
    tekrar etmedi diye plan reddedilemez. Bu alanlar operation catalog'dan authoritative
    biçimde enrich edilir. Eksik business argümanı, yanlış kayıt kümesi veya farklı
    operation ise katalog metadata'sı adı altında tamamlanamaz. Böylece validator hem
    modelin yerine iş planı kurmaz hem de doğru model planını gereksiz protokol ezberiyle
    bozmaz.
33. **Plan validator ve repair görünür, kayıpsız ve reason-coded olmalıdır.** İlk model
    proposal'ı, canonicalization/enrichment, schema sonucu, semantic verifier kararı,
    reddedilen step ve bounded repair proposal'ı append-only evidence'da ayrı tutulur.
    Doğru ilk plan reddedilip repair modelini eski veya yanlış hedefe sürüklediyse son
    yanlış proposal kök neden diye gösterilemez; ilk haksız red control-plane failure'ıdır.
34. **Düzeltmede son kullanıcı mesajı stale hedefi geçersiz kılar.** Kullanıcı pending
    TANEX 2736 hazırlığını TANEX 2610 olarak düzelttiğinde eski action önce terminal
    `superseded` olur. Typed interpreter eski 2736 objective'ini tekrar ederse bu stale
    değer planning objective olamaz; güncel kullanıcı düzeltmesi modele verilir. Yeni
    2610 action'ı model-authored planla, aynı authoritative exact selection üzerinde yeni
    action ID olarak hazırlanır; eski ID'nin onayı effectsiz reddedilir.
35. **Bu kararların frozen cloud kabul zinciri vardır.** Fresh source-app konuşması count
    -> exact list -> bütün aktif set için TANEX 2736 prepare -> kullanıcı düzeltmesiyle
    TANEX 2610'a supersede/re-prepare -> pending read-back -> eski action onayının reddi ->
    yeni action onayı -> yalnız yerel DOCX execute -> authoritative içerik read-back
    adımlarını geçmelidir. Her adımda exact selection ve account/environment sabit kalır;
    fiziksel baskı veya pazaryeri mutasyonu yapılmaz. Güçlü cloud modelin doğru ilk planı
    validator tarafından haksız reddedilirse kampanya başarısızdır ve model değiştirilerek
    geçiştirilemez.
36. **Legacy keyword intent guard model kararını ikinci kez yargılayamaz.** Typed mode
    `act/correct`, active correction target label proposal ve modelin seçtiği canonical
    operation `labels.create_from_orders.prepare` iken kullanıcının takip mesajında
    “etiket” kelimesini tekrar etmemesi plan red nedeni değildir. Effectful operation
    yetkisi candidate membership, typed mode/semantic contract, active target, schema,
    scope, policy ve semantic verifier ile kurulur. `_goal_has_label_intent` benzeri raw
    text guard'ları yalnız retrieval hint veya erken güvenlik sinyali olabilir; modelin
    doğru semantik kararını veto eden production authorization kapısı olamaz.
37. **Follow-up capability retrieval typed bağlamla zenginleşir, tool seçmez.** Düzeltme
    mesajının ham metni tek başına catalog query değildir. Typed semantic contract, aktif
    selection ve pending/superseded target'ın action/operation metadata'sı aday retrieval'a
    eklenir; böylece kullanıcı domain ismini tekrar etmedi diye `ready_to_ship_count` veya
    `labels.create_from_orders.prepare` katalog yüzeyinden düşmez. Bu enrichment yalnız
    candidate set üretir; seçimi model yapar, runtime schema/policy/verifier ile sınırlar.
38. **Supersession action kimliğini mutlaka döndürür.** Aynı 12 sipariş ve aynı label
    operation'ında TANEX 2736 -> TANEX 2610 değişikliği yalnız açıklama farkı değildir;
    execute payload değişmiştir. Eski action terminal `superseded`, replacement farklı
    `action_id` ve farklı `prepare_fingerprint` taşır. Eski ID'nin onayı yeni payload'a
    yönlenemez ve effectsiz stale-action hatası verir. Approval identity bütün domainlerde
    tek canonical semantic fingerprint fonksiyonundan üretilir; Labels'e özel kimlik
    yaması veya yalnız record-count hash'i kabul edilmez. UI, persisted state ve redacted
    acceptance artifact'ındaki superseded-action projection eski `action_id` ve güvenli
    `prepare_fingerprint` kimliğini kaybetmez; kimliksiz “superseded oldu” özeti stale-ID
    reddini sonradan authoritative olarak doğrulayamadığı için kapanış kanıtı sayılmaz.
39. **Schema-valid model operation'ı legacy kelime kurallarıyla kardeş operation'a
    çevrilemez.** Model katalogdaki mutually-exclusive single/bulk operation ailesinden
    tam bir canonical operation seçmiş, typed argümanları ve exact kayıt kümesini üretmişse
    “tümü/hepsi/tamamında” gibi raw token yardımcıları bu seçimi tekilden topluya veya
    topludan tekile yeniden yazamaz. Bu yardımcılar yalnız candidate retrieval ya da model
    planı bulunmayan açık legacy/diagnostic yol için kullanılabilir. Target cardinality,
    schema binding ve semantic verifier tarafından doğrulanır; doğru model planını keyword
    katmanının bozması doğrudan control-plane failure'dır.
40. **Focused düzeltme kapanış veya ürün ilerlemesi değildir.** Focused source-app koşusu,
    unit test veya dar regresyon yalnız belirli kök nedenin kapandığını kanıtlar. Her böyle
    düzeltmeden sonra en az 22 turlu tam organik cloud kampanyası fresh process ve current
    source fingerprint ile ilk mesajdan yeniden başlar. Önceki kampanyanın geçmiş turları,
    eski artifact'ı veya doğru tool sonuçları yeni koşuya devredilemez.
41. **Organik kabul yalnız business tool turlarından oluşmaz.** Aynı kesintisiz konuşma;
    doğal selamlaşma ve duygusal sohbeti, toolsuz konu değişimlerini, uzun bağlam dönüşünü,
    exact Orders okuma/selection/detail/risk akışlarını, prepare/cancel ve approval yaşam
    döngüsünü, Excel artifact execute/read-back'ini, public web araştırmasını, private-web
    sınırını ve kapanış sohbetini birlikte geçmelidir. Her görünür cevap Codex tarafından
    okunur; tek kritik sapmada koşu durur ve kök katman düzeltilmeden sonraki tura geçilmez.
42. **Model rota değişimi başarısız turun devamı gibi gösterilemez.** Exact-model kabulünde
    model-scope `429` alınırsa aynı süreçte fallback yapılmaz. Aynı provider'ın quality
    route'undaki sıradaki capability-compatible ücretsiz model ancak ayrıca pinlenmiş fresh
    process kampanyada denenebilir ve kampanya ilk turdan başlar. Normal ürün runtime'ının
    açık, provenance'lı same-provider fallback davranışı ayrı bir ürün sözleşmesidir; exact
    acceptance kanıtının yerine geçmez. Project/account/provider/unknown scope'ta kardeş
    model denenmez.
43. **Eksiksiz ve yürütülebilir read isteği gereksiz clarification'a çevrilemez.** Kullanıcı
    “son 5 siparişi ... alanlarıyla göster” gibi kayıt türünü, sıralama anlamını, limiti ve
    istenen alanları açıkça verdiyse runtime yeniden zaman aralığı soramaz. `son/en son/latest`
    ifadesi bounded recency sıralamasıdır; ayrıca söylenmedikçe `today`, son 24 saat veya başka
    bir takvim filtresi uydurulamaz. Model eksiksiz isteğe rağmen clarification üretirse typed
    interpreter yalnız aynı açık read contract'ını kayıpsız normalize edebilir; operation,
    filtre, kayıt kümesi veya business hedefi icat edemez.
44. **Business intent ham substring eşleşmesiyle yetkilendirilemez veya yeniden yazılamaz.**
    Bir provider adı ya da fiil başka bir kelimenin içinde geçti diye niyet sinyali sayılamaz;
    örneğin `numarası` içindeki `aras`, Aras Kargo değişikliği değildir. Mutation niyeti typed
    mode, açık business subject, gerçek değişiklik fiili, active target ve policy/verifier
    birlikteliğiyle kurulur. Token sınırı olmayan substring kontrolleri yalnız mutation'da
    değil bütün domainlerde canonical read planını düşüremez, sibling operation seçemez ve
    kullanıcıdan gereksiz clarification isteyemez.
45. **Model-authored plan tek başına accepted semantic output değildir.** Doğru planner
    operation'ı ancak tool observation'ı, kullanıcıya görünen final projection ve istenen
    alan/metric kapsamı da verifier'dan geçtiğinde kabul edilir. Genel Orders özetinde
    authoritative toplam ve hazır sayı gibi zorunlu metrikler eksik bırakılamaz; internal
    account ID mağaza adı diye gösterilemez. Deterministic fallback doğrulanamadıysa
    `deterministic_verified_projection` veya eşdeğer bir başarı kaynağı etiketi taşıyamaz.
46. **Fresh organik kampanya, focused düzeltmelerin birleşim sınavıdır.** Her yeni semantic
    compiler, interpreter veya projection düzeltmesi focused source-app tekrarında ilgili
    turu geçse bile kabul kampanyası kaldığı yerden sürmez. Güncel source fingerprint ile
    selamlaşmadan başlayan fresh 22+ tur; eksiksiz read, uzun bağlam, mutation prepare/cancel,
    artifact/Excel ve web/privacy akışlarını aynı process içinde birlikte geçmeden Faz 8B
    kapanmaz.
47. **Kullanıcının istediği cevap alanları tool business argümanı değildir.** Model,
    `orders.query` gibi bir read operation'ında kullanıcıya hangi alanların gösterileceğini
    `projection` veya eşdeğer response metadata'sıyla anlatmışsa ve bu alanların tamamı typed
    kullanıcı isteğiyle birebir doğrulanıyorsa runtime bunları tool şemasında bulunmayan
    business filtresi diye reddetmez; response-evidence contract'ına kayıpsız taşır. Bu izin
    yalnız read-only operation ve doğrulanmış alan kümesi içindir. Bilinmeyen alan, yeni filtre,
    kayıt seçimi, mutation argümanı veya kullanıcının istemediği projection fail-closed kalır.
48. **Observation alan lehçesi gereksiz replanning veya veri kaybı üretemez.** Domain sonucu
    `customer`, `cargo_provider` veya `cargo_tracking_number`; semantic contract ise
    `customer_name`, `cargo` veya `tracking_number` diyebilir. Aynı canonical anlamı taşıyan
    açık alias'lar ortak evidence normalizer'da eşleştirilir ve model var olan veri için ikinci
    bir tool'a kaçmaya zorlanmaz. Alias eşlemesi değer uyduramaz, farklı alanları birleştiremez
    ve business kapsamını genişletemez.
49. **Read cevabı aggregate değil, istenen kayıt satırları üzerinden doğrulanır.** “Son 5
    siparişi numara, durum, müşteri, tarih, tutar, kargo ve takip bilgisiyle göster” hedefinde
    exact beş kayıt ve her kayıtta istenen her alan ayrı doğrulanır. Satır tutarıyla ilgisiz
    genel toplam birbirinin kanıtı olamaz. Authoritative değeri gerçekten boş olan açıkça
    istenmiş alan `belirtilmemiş` gibi dürüst bir gösterimle korunur; sessizce düşürülemez.
    Kullanıcıya görünen yanıt ancak bu satır-bazlı projection geçerse accepted semantic output
    ve deterministic verified projection sayılabilir.
50. **Acceptance sürücüsü timeout'u görünmez veya yarım başarı bırakamaz.** Source-app turu
    zaman aşımına uğrarsa süreç traceback ile çıkıp sıfır turlu `open` artifact bırakamaz ve
    önceki assistant cevabını yeni turun sonucu diye kullanamaz. Timeout ayrı, reason-coded
    başarısız turn olarak yazılır; model/tool/effect hakkında kanıtlanmayan iddia kurulmaz,
    artifact kapanır ve sonraki kabul fresh process ile ilk turdan başlar. Timeout, provider
    hatası veya boş artifact ürün başarısı ya da semantik regresyon kanıtı değildir.
51. **Cloud-first kabul sırası korunur; local kalite testi şimdilik çalıştırılmaz.** Orders'ın
    birleşik agent runtime'ı önce gerçek Chat source-app yolunda güçlü ve erişilebilir ücretsiz
    cloud modellerle kanıtlanır. Local provider, katalog ve UI desteği korunur; fakat cloud
    Faz 8B/8C kapıları kapanmadan local inference, local uzun sohbet veya local model kalite
    kampanyası süre ve ilerleme ölçütü olarak kullanılamaz. Güçlü cloud modeldeki kötü görünen
    basit manuel parity sonucu da “model yetersiz” diye kapatılamaz; plan, validation,
    observation, replanning, projection ve verifier provenance'ı tek tek incelenir.
52. **Operation seçimi response projection güvencesini zayıflatamaz.** Aynı exact kayıt kümesi
    `orders.query`, `orders.recent`, `orders.full_context` veya gelecekteki başka bir canonical
    read operation'ıyla dönmüş olabilir. Kullanıcı satır bazında numara/durum/müşteri/tarih/
    tutar/kargo/takip istediğinde operation adına bakılarak bu alanların doğrulaması kapatılamaz.
    `contexts[].order`, `orders[]` ve eşdeğer authoritative payload'lar ortak canonical order-row
    projection'a girer. Full-context içinde kalem/iade gibi zengin bölümler istenmişse bunlar
    satır alanlarının yerine geçmez; iki projection kayıpsız compose edilir.
53. **Türkçe çekim veya alt-küme aggregate'ı açık count hedefini düşüremez.** `sayı`, `sayısı`,
    `sayıyı`, `toplam sipariş` ve eşdeğer açık adet ifadeleri typed `count` projection'ını
    model unutsa dahi kayıpsız korur; fakat “toplam tutar/ciro” sipariş adedi sayılamaz.
    Authoritative bütün-sipariş count'u ile filtreli/listelenmiş alt-küme total'i aynı kavram
    değildir. Kullanıcı genel toplamı istediğinde non-cancelled, limitli veya başka filtreli
    `total_count` genel toplam etiketiyle gösterilemez; verifier iki metriğin provenance'ını
    operation ve semantic contract üzerinden ayırır.
54. **Bir turun önceki model cevabı final model cevabının yerine geçmez.** Aynı kullanıcı
    turunda interpretation başarılı olup final chat/planning/synthesis invocation'ı boş veya
    provider-unavailable kalabilir. Append-only provenance `any_model_response_received=true`
    ile `final_model_response_received=false` durumunu ayrı korur; bu tur accepted semantic
    output olamaz. Toolsuz chat/explain turunda kullanıcıya generic “Uygulama hatası” yerine
    reason-coded, secret-safe provider-unavailable açıklaması gösterilir ve hiçbir business tool
    çalışmadığı ancak bu branch gerçekten toolsuzsa söylenir. Business observation oluşmuş bir
    turda final cevap kaybolursa mevcut observation/effect durumu saklanır; “hiçbir işlem olmadı”
    diye kanıtsız iddia kurulmaz.
55. **Capability sorusu sohbet geçmişindeki kanıta indirgenemez.** Kullanıcı belirli bir domain
    için “neler yapabilirsin”, “nelerde yardım edebilirsin”, “nasıl yardımcı olabilirsin” veya
    “hangi konularda destek olabilirsin” dediğinde typed intent `capability_overview` olur ve
    görünür cevap canonical operation catalog'dan grounded üretilir. Modelin yakın sohbette bu
    yeteneklerin konuşulmadığını söylemesi ürün cevabı değildir. Türkçe yardım/destek/yapabilme
    soru ailesi semantic guard'da normalize edilir; bu guard business operation seçmez, yalnız
    model-authored domain capability niyetinin toolsuz chat yolunda kaybolmasını engeller.
    Acceptance artifact her turdaki typed `turn_interpretation`ı ayrıca saklar; karar izi yalnız
    final cevap veya tool adına bakılarak geriye doğru tahmin edilmez.
56. **Aynı alan adı aynı business metriği demek değildir; kanıt operation-aware olmak
    zorundadır.** `orders.count.count` bütün siparişlerin authoritative toplamıdır;
    `orders.ready_to_ship_count.count` yalnız kargoya hazır alt kümenin adedidir;
    `orders.query.total_count` ise sorgunun filtre, tarih, status, pagination ve account
    kapsamındaki sonuç sayısıdır. Runtime, observation normalizer, response verifier ve
    deterministic projection bu değerleri ortak bir `count` scalar havuzuna atamaz. Her
    metrik `metric_id`, operation, account/store, environment, status/date/filter kapsamı,
    source revision ve freshness ile taşınır. Genel toplamın kanıtı hazır adet; hazır adedin
    kanıtı genel toplam; filtreli query total'i de bunlardan herhangi biri olamaz.
57. **Bir kullanıcı cümlesindeki bağımsız metriklerin tamamı ayrı ayrı korunur ve
    doğrulanır.** Kullanıcı aynı turda genel toplam sipariş sayısını, kargoya hazır sayıyı,
    mağaza/ortamı ve durum dağılımını istediyse tek bir `count` cevabı bütün hedefi tamamlamaz.
    Typed semantic contract her istenen metriği ayrı requirement olarak taşır; planner
    gereken canonical read'leri compose eder, verifier her requirement'ı doğru operation ve
    doğru scope kanıtıyla eşler. Görünür cevapta metriklerden biri eksik, yanlış kapsamlı ya
    da başka alt kümeden alınmışsa model cevabı da deterministic fallback de accepted olamaz;
    bounded replan mümkünse eksik kanıt tamamlanır, değilse eksiklik açıkça bildirilir.
58. **Örnek kayıt statüleri genel durum dağılımı değildir.** Limitli veya filtreli
    `orders.query` sonucunda görülen `ReadyToShip`, `Shipped` gibi birkaç satır statüsü ancak
    o listelenen selection'ın satır alanı olarak sunulabilir. “Siparişler genel olarak ne
    durumda?” veya açık durum dağılımı isteği authoritative `orders.status_counts` ya da aynı
    semantiği taşıyan canonical aggregate operation ile; `total_orders`, bütün status
    bucket'ları, account/environment ve freshness kanıtıyla cevaplanır. Sample statüler
    “Sipariş durumları” başlığıyla globale yükseltilemez, eksik bucket'lar sessizce düşürülemez
    ve böyle bir projection `deterministic_verified_projection` etiketi alamaz.
59. **Deterministic projection başarısı bütün requested-field matrisi üzerinden hesaplanır.**
    Herhangi bir provider hatasından sonra mevcut authoritative observation'lardan güvenli
    cevap üretilebilse bile `accepted=true` ancak tüm istenen metrik/alanların ayrı semantic
    verifier kapılarını geçmesiyle mümkündür. Bir alt metriğin doğru olması, başka bir metriğin
    yokluğunu örtemez. `projection_verified=true`, `final_source=deterministic_verified_projection`
    ve boş `problems` birlikte yalnız eksiksiz kanıt matrisinde yazılır; aksi halde artifact
    reason-coded failed/replan-required kapanır. Bu kural güçlü model, ücretsiz model ve bütün
    provider'larda aynıdır.
60. **Ücretsiz model kotası ücretli hesap/kredi kotası diye genellenemez.** OpenRouter
    `:free` modellerinin paylaşılan günlük/dakikalık kotası dolduğunda quota scope
    `free_tier` olarak taşınır. Aynı free havuzundaki kardeş model ruleti durur; fakat bu
    sonuç paid model erişiminin, API-key harcama limitinin veya hesap kredisinin tükendiğini
    kanıtlamaz. `billing`, gerçek `account/provider` kotası ve `free_tier` birbirinden ayrı
    provenance taşır. Paid modele geçiş yalnız kullanıcının açık harcama bütçesi/politikası
    kapsamında, kalan key limiti read-only provider endpoint'iyle doğrulandıktan sonra ve
    fresh process kampanyada yapılır; ayrıca `/api/v1/key` harcama tavanı ile
    `/api/v1/credits` satın alınmış hesap kredisi ayrı ayrı doğrulanır. Pozitif key limiti
    tek başına paid erişim kanıtı değildir. Ücretli kontrol ücretsiz kabul kanıtının yerine
    geçmez. Kullanıcıya
    görünen hata da “provider hesabının genel kotası doldu” diyemez, ücretsiz model havuzu
    sınırını, key harcama tavanını ve gerçek paid krediyi açıkça ayırır.
61. **Çoklu Orders metriğinin kimliği ve kapsama yeterliliği domain-owned tek sözleşmeden
    yönetilir.** `orders.total_count`, `orders.ready_to_ship_count` ve
    `orders.status_distribution` requirement'ları kullanıcı cümlesindeki bağımsız hedefleri
    temsil eder. Her requirement için hangi canonical operation'ın hangi doğrudan result
    alanının authoritative kanıt olduğu Orders domaininde tek registry'de tanımlanır; planner
    coverage, semantic verifier ve response verifier bu registry'yi ortak kullanır. Plan bütün
    requirement'ları kapsayan operation seti üretmeden hiçbir read step'i çalıştırılmaz; model
    bir kez bounded repair'e alınır. `orders.query.count/total_count/status_counts` gibi
    filtreli veya sample sonuçlar bu registry tarafından genel toplam ya da global durum
    dağılımı kanıtı ilan edilmedikçe projection'a yükseltilemez. Cevapta her zorunlu metric
    ayrı iddia ve doğru değerle bulunmazsa `projection_verified/accepted` yazılamaz.
62. **Aggregate operation kanıtı kayıt listesi gibi şişemez ve planner output
    sözleşmesini görmeden minimal plan kurmaya zorlanamaz.** Count, status distribution,
    revenue ve eşdeğer aggregate read'ler exact selection üretmiyorsa bütün kayıtların
    order/claim kimliklerini veya record-to-account haritasını observation'a taşımaz;
    yalnız aggregate değer, distinct account/store/environment scope, source revision/hash
    ve gerekli freshness metadata'sını döndürür. Exact follow-up selection gereken
    `ready_to_ship_count` gibi açık istisnalar kayıt kümesini typed selection için
    koruyabilir. Operation catalog planner'a yalnız arguments schema'yı değil privacy-safe
    result field sözleşmesini de gösterir. Typed metric operation'ları bütün requested
    projection kanıtlarını zaten döndürüyorsa metrik requirement'a katkısı olmayan ikinci
    read planı execution öncesi `redundant_projection_read_operation` ile reddedilir;
    runtime step'i sessizce silmez, model bounded repair ile minimal planı yeniden yazar.

Bu kararların özeti şudur: bundan sonra "çok çalışıldı", "çok test geçti" veya "güçlü
model seçildi" diye sonuç ilan edilmeyecek. Yalnız gerçek modelin gerçek ürün yolunda,
authoritative veri üzerinde, kullanıcı hedefini doğru ve doğrulanmış biçimde tamamlaması
kapanış sayılacaktır.

### Faz 0 — Gerçeği dondur ve eski kapanışı aç

- Son gerçek kullanıcı sohbetlerini redacted acceptance fixture/evidence yap.
- Eski `Orders ready/completed` sonuçlarını güncel kapanış girdisi olmaktan çıkar.
- Dört problemli business prompt'ta planner'ın devre dışı kaldığını deterministic
  testle kanıtla.
- Mevcut operation, duplicate intent rule, manual capability ve state-flow envanterini
  çıkar.
- Başarı kriteri: yeni mimari planı mevcut kod gerçeğine ve fail eden transcript'lere
  bağlanmış; hiçbir eski artifact Orders'ı hazır göstermiyor.

### Faz 1 — Typed event/state temeli

- ConversationTurn, ActiveScope, Observation, SelectionSnapshot, AnalysisContext,
  PendingAction ve TaskState sözleşmelerini kur.
- Ham history taramasını kayıt/action state'inin kaynağı olmaktan çıkar.
- Cancel/supersede/approve yaşam döngüsünü action ID ile merkezileştir.
- Gerçekten domainler arası primitives'leri Core'a, AI orchestration state'ini AI'a koy.
- Başarı kriteri: stale/iptal edilmiş selection veya action hiçbir doğal takipte active
  olamıyor; app restart/checkpoint davranışı testli.

Uygulama durumu (2026-07-20): `proven`. Production chat ve persisted task runtime
`AgentSessionState` kullanıyor; ham sohbet satırlarındaki structured context üretim
kararına taşınmıyor, yalnız aktif typed state legacy okuyuculara geçici projection olarak
veriliyor. Pending action yaşam döngüsü exact `action_id` ile approve/cancel/supersede
ediliyor ve stale ID execute öncesinde kapanıyor. Kanıt:
`agentic_control_plane_phase1_typed_state_2026-07-20.json`.

### Faz 2 — Atomic operation catalog ve tool retrieval

- Operation metadata/schema'yı tek canonical contract'a getir.
- Generic fuzzy router'ı production planner yolundan çıkar veya yetkisiz diagnostic
  katmana indir.
- Model prompt'una ilgili typed operation adaylarını retrieval ile ver.
- Orders item aggregate, selected return reason aggregate ve pending-action inspect/
  revise boşluklarını kapat.
- Manuel UI -> domain operation -> AI adapter parity'sini yeniden denetle.
- AI tool'larının içinde tekrar yazılmış query, eligibility, aggregation, mutation ve
  platform iş mantığını bul; canonical sahibi domain operasyonuna taşı ve tool'u ince
  policy/DTO/Result adapter'ına indir.
- Widget bağımlı `views/actions.py` iş mantığını gerektiğinde domain processor/service/
  pipeline katmanına çıkar; manuel public action'ı ve AI operation'ı aynı callable'a
  bağla.
- Başarı kriteri: doğal bir hedef birden fazla atomic operation'la compose edilebiliyor;
  yanlış domain capability proposal üretemiyor ve machine-checkable parity raporu her
  capability için tek canonical callable'ı kanıtlıyor.

Uygulama durumu (2026-07-20): `proven`. Tek `OperationMetadata` tabanlı katalog,
sınırlı semantic tool retrieval ve typed manual-operation retrieval production planner
girdisine bağlandı; fuzzy `operations.manual_action.route` ve capability matcher planner
yüzeyinden çıkarılıp diagnostic/deterministic fallback katmanında bırakıldı. Orders
domainindeki ready count/list/label selection, sipariş ve iade query/lookup, full context,
iptal/ciro/durum/item-sales/return-reason aggregate'leri, fulfillment risk/deadline ve
return snapshot reconciliation aynı canonical domain operasyonlarına bağlandı. Exact
pending action toolsuz inspect, `action_id` ile stale koruması ve immutable scope
revise/supersede typed state testleriyle kanıtlandı. Ham `orders.fetch_orders_all`
yarım-operasyonu doğrudan agente açılmıyor; fetch+persist+approval sözleşmeli
`orders.get_orders_from_companies` tarafından machine-readable biçimde supersede
ediliyor. `operation_catalog_parity_report(domain="orders")` 35 manuel capability,
35 agent operation ve `0` problem ile `ready=true` döndürüyor. Kanıt:
`AI/docs/agentic_control_plane_phase2_operation_catalog_2026-07-20.json`.

### Faz 3 — Birleşik agent loop

- One-shot business router ve sabit task template üstünlüğü yerine tek plan/act/observe/
  verify/replan runtime kur.
- Mode interpretation'ı model + typed contract ile yap; deterministic kod yalnız
  policy/protocol sınırında kalsın.
- Her observation sonrası hedef ve sonraki adım yeniden değerlendirilir.
- Error recovery, clarification, safe retry, cancellation ve persistence eklenir.
- Typed GoalPlan/plan graph ile fan-out/fan-in, cross-source observation ve dinamik
  report profile composition desteği eklenir; her yeni doğal hedef için mega-tool
  yazılmaz.
- Başarı kriteri: basit iş bir adımda, karmaşık iş dinamik çok adımda aynı runtime ile
  tamamlanıyor; business prompt'ta model kararı regex tarafından preempt edilmiyor.

Uygulama durumu (2026-07-21): `proven`. Source UI her provider/local model turunda
önce typed `chat/explain/inspect/act/approve/cancel/correct` yorumunu modelden alır;
geçerli model kararı eski keyword task kapısını preempt eder. Basit ve çok adımlı
business hedefler bounded atomic operation adayları, typed arguments, dependencies,
operation domain ve expected evidence taşıyan tek `GoalPlan` runtime'ında çalışır.
Direct step aynı karar için ikinci kez LLM'e tool seçtirmez; canonical operation'ı
şema/policy sınırında çalıştırır, typed `Observation` üretir ve her başarılı observation
sonrasında hedefi `continue/complete/replan/clarify` sözleşmesiyle yeniden değerlendirir.
Başarılı ve hatalı observation sonrası dinamik replan, transient retry, persistable
clarification, fan-out/fan-in graph ve cross-source operation-domain temeli testlidir.
Ready list -> TANEX 2610 prepare testi aynı exact record set'ini korur; kullanıcı kodu
`2610/TW-2610/TANEX_2610` AI yaması olmadan canonical Labels kataloğunda çözülür.
Kanıt: `AI/docs/agentic_control_plane_phase3_unified_loop_2026-07-21.json`.

### Faz 4 — Semantic verifier ve approval güvenliği

- Objective/domain/operation/target/payload eşleşmesini doğrula.
- Read/explain/hypothetical mesajdan mutation proposal çıkmasını fail-closed engelle.
- Exact set/fingerprint/freshness/eligibility invariant'larını prepare ve execute
  öncesinde zorunlu yap.
- Response grounding, strict projection ve privacy verifier ekle.
- Başarı kriteri: yanlış Logistics action, hedefsiz cargo payload, stale Delivered
  label, eski approval ve gereksiz PII UI'ya ulaşamıyor.

Uygulama durumu (2026-07-21): `proven`. Direct effectful planlar typed `act/correct`
mode'u ve bağımsız structured objective-operation kararı olmadan prepare'a ulaşamaz.
Prepared action, typed plan veya dependency observation'dan gelen exact RecordRef setiyle
eşleşir; action type, target set, count ve tam semantic payload fingerprint değişirse
approval/execute fail-closed kapanır. Kullanıcı onayından sonra fakat execute'tan önce
freshness, immutable fingerprint ve canonical Orders eligibility read-back yeniden
çalışır; ReadyToShip iken hazırlanıp Delivered olan sipariş etiketi ve hedefsiz cargo
provider payload'ı execute edilmez. Final cevap typed requested fields'e göre count/store/
status projection'ı uygular; uydurma sayı/kimlik/status, yapılmamış başarı ve sorulmayan
müşteri/adres/contact/tracking/package/claim verisi gösterilmez. Kanıt:
`AI/docs/agentic_control_plane_phase4_semantic_verifier_2026-07-21.json`.

### Faz 5 — Orders uçtan uca yeniden kurulum

- Ready count/list/selection/item aggregate zinciri
- UI'da hazır olmayan ad-hoc satış raporları için Orders `ReportSnapshot` operation'ı
- Son üç hafta en çok satanlar -> doğal özet -> doğrulanmış Excel artifact zinciri
- Latest order -> item/public identity zinciri ve cross-source research girdisi
- Return selected-scope reason zinciri
- TANEX 2610/2736 exact label prepare/execute/read-back zinciri
- Exact order cargo-provider prepare/approve/execute/verify zinciri
- Fresh sync observability ve recovery
- Kullanıcı correction, explanation, hypothetical, cancel ve pending-action inspect
  akışları
- Başarı kriteri: Bölüm 15'teki bütün gerçek kullanıcı regresyonları fresh process'te,
  yalnız transcript cümlelerine özel olmayan varyasyonlarla geçiyor.

Uygulama durumu (2026-07-21): `deterministic_control_plane_proven / live_acceptance_open`.
GoalPlan adımları artık yalnız ilan edilmiş dependency çıktılarından typed `$from_step`
binding alır; sonuç şeması uygunsa `order_numbers`, `claim_ids`, `report_snapshot` gibi
alanlar modelin kimlik kopyalamasına bırakılmadan exact bağlanır. Yeni sohbet task'ı eski
execution/pending state'ini taşımadan typed selection/scope/observation hafızasını korur;
bu nedenle "4 bekleyen var -> bunları 2610'a yazdır" aynı dört kaydı, "bu sipariş
kimin?" ise önceki exact tek siparişi kullanır ve şikâyet cümlesini fuzzy sorguya
çevirmez.

Orders canonical item-sales aggregation ve privacy-minimal immutable `ReportSnapshot`
üretir. Core ortak XLSX yazıcısı snapshot'ı formula-injection korumasıyla geçici dosyaya
yazar, exact semantic read-back başarılı olmadan hedef dosyanın üzerine atomik geçmez;
barkod/SKU/content kimlikleri string + `@` Excel formatında kilitlidir. Latest order
item'larından müşteri, adres, tracking ve private order kimliği içermeyen public product
identity üretimi cross-source research girdisi olarak hazırdır. Ready/return/label/cargo/
sync/cancel/correct/hypothetical/pending-inspect gerçek kullanıcı varyasyonları fresh
process'te geçmiştir. Kanıt:
`AI/docs/agentic_control_plane_phase5_orders_e2e_2026-07-21.json`.

Bu durum bütün Orders hedefinin kapandığı anlamına gelmez. Gerçek Gemini/OpenRouter/local
temel model yeniden kabulü Faz 6'da tamamlandı. Privacy-safe web research ve kaynaklı
artifact composition Faz 7; uzun konuşma ile Production/Stage source kabulü Faz 8;
responsive source-app UI kabulü Faz 9'da açıktır.

### Faz 6 — Provider/model yeniden kabulü

- Gemini, OpenRouter ve local capability yollarını yeni loop'ta doğrula.
- En güçlü erişilebilir ücretsiz modellerle başla; kota oldukça sıradaki uygun modele
  geç.
- Güçlü ücretli referans modeli aynı frozen scenario/state üzerinde A/B kullan.
- Modelleri gerçek capability/kaliteye göre sınıflandır.
- Başarı kriteri: güvenlik modelden bağımsız; en az bir ücretsiz cloud ve uygun local
  model temel full-agentic Orders hattını geçiyor.

Uygulama durumu (2026-07-21): `proven`. Canlı katalog ve hesap erişimi üzerinden exact
model/fallback kapalı kabul çalıştırıldı. Gemini 3.5 Flash structured planı output sınırında
kesilince ve sonraki denemelerde ücretsiz kota dolunca güvenlik gevşetilmeden sıradaki
uygun ücretsiz model olan Gemini 3 Flash Preview'a geçildi; bu model iki exact siparişin
etiket ve fiş-çıkarıldı zincirini `llm_direct` planla tamamladı. OpenRouter
`nvidia/nemotron-3-super-120b-a12b:free` aynı hattı guarded JSON contract ile geçti;
yanlış/eksik model planı semantic compiler tarafından görünür provenance ile onarıldı.
Yerel `Qwen3-4B-Q4_K_M.gguf`, `os_guarded_low_memory` planında unsafe kaynak artırımı
olmadan exact sipariş kapsamını model-authored ilk adım ve deterministic intent coverage
ile tamamladı.

Bu kabul model kusurlarını gizlemez: Nemotron semantic verifier false-negative/format
hataları ve Qwen'in kısa çıktı sınırındaki eksik plan, mojibake ve yarım final cevabı
gözlendi. Typed objective, canonical operation policy ve authoritative response guard
yalnız yüksek güvenli açık niyette güvenli düzeltme yaptı; çelişkili veya ambiguous hedef
fail-closed kalır. Her model cevabı Codex tarafından doğrudan incelendi. `108` task-runtime
testi + `14` subtest ve `321` provider/catalog/routing/pipeline testi + `35` subtest geçti.
Ücretli model harcaması kullanıcı onayı olmadığı için yapılmadı; bu bir Phase 6 başarı
engeli değildir ve ileride ayrı frozen A/B olarak çalıştırılabilir. Kanıt:
`AI/docs/agentic_control_plane_phase6_provider_acceptance_2026-07-21.json`.

Faz 6 yalnız bounded temel provider/model hattını kapatır. 50/60/100/200+ mesaj kampanyası,
gerçek Trendyol Production/Stage source etkileri ve bütün görünür cevapların uzun dönem
kalite incelemesi Faz 8'in bağlayıcı kabul kapısı olmaya devam eder.

### Faz 7 — Web search agentic yeteneği

- Provider-independent atomic search/open/follow/find/document/compare operation
  ailesini kur.
- Web query privacy sanitizer, secret/PII fail-closed kapısı ve prompt-injection
  savunmasını ekle.
- Search snippet yerine source open/read ve çok kaynak doğrulamasını agent loop'a bağla.
- WebObservation, freshness, citation, cache/TTL ve evidence sözleşmesini typed state'e
  ekle.
- Güncel Trendyol dokümanı, kargo şartı, dış araştırma, çelişkili kaynak, PDF, boş sonuç
  ve injection senaryolarını gerçek ve deterministic testlerle doğrula.
- Son sipariş item'ları -> privacy-safe ürün araştırması -> grounded
  ResearchReportSnapshot -> Excel composition senaryosunu uçtan uca çalıştır.
- Gemini, OpenRouter ve uygun local modelin aynı web tool sözleşmesini compose etmesini
  kanıtla.
- Başarı kriteri: agent yalnız gerektiğinde web'e gider, gizli veri göndermez, sayfa
  talimatına uymaz, kaynakları gerçekten açıp karşılaştırır ve tıklanabilir kaynaklı
  cevapla hedefini sürdürür.

Uygulama durumu (2026-07-21): `proven`. Provider-independent `search/open/follow/find/
document.read/compare/research_report/report_xlsx.prepare` operation ailesi typed
GoalPlan loop'una bağlandı. Search snippet'ları yalnız adaydır; final kanıt ve citation
olabilmek için kaynak gerçekten açılır ve `WebObservation` olarak doğrulanır. URL/secret/
PII sanitizer, SSRF ve DNS guard, prompt-injection ayrımı, HTML/text/PDF okuma, freshness,
source sınıfı, başarısız kaynak recovery'si ve duplicate final-source engeli fail-closed
çalışır. Tamamlanmış canonical web graph'ı model evaluator yeniden açamaz.

Orders item'larından yalnız public ürün kimliği çıkar; müşteri, adres, tracking, package,
private order ID ve gizli SKU web'e taşınmaz. Açılmış kaynaklar immutable
`ResearchReportSnapshot` üretir; aynı snapshot Core ortak XLSX yazıcısıyla exact semantic
read-back ve atomik publish sonrasında Excel'e dönüşür. Dört görünür sheet offscreen
render edilip Codex tarafından incelendi; bulunan 13 haneli barkodun bilimsel gösterim
sorunu düzeltilip yeniden render edildi. Gemini 3 Flash Preview, OpenRouter Nemotron 3
Super free ve yerel Qwen3-4B aynı web sözleşmesinde gerçek public source akışını
çalıştırdı. Model plan/binding/final kusurları gizlenmedi; semantic compiler, response
verifier ve deterministic terminal ownership doğrulanmış sonucu korudu. Aynı domain'deki
iki sayfa bağımsız doğrulama sayılmayıp cevapta `kısmi` olarak açıklandı. `172` test +
`18` subtest geçti; `124` koşullu test skip edildi. Ücretli harcama, marketplace API/
DB mutation veya UI açılışı yapılmadı. Kanıt:
`AI/docs/agentic_control_plane_phase7_web_report_acceptance_2026-07-21.json`.

Faz 7 bounded web/report capability'sini kapatır. 50/60/100/200+ görünür mesaj boyunca
state, topic switch, correction, approval, recovery ve gerçek Production/Stage kaynak
dayanıklılığı Faz 8'in bağlayıcı kabul kapısıdır; aktif çalışma artık cloud-first Faz
8'dedir.

### Faz 8 — Cloud-first Orders stabilizasyonu ve gerçek kaynak kabulü

- Bu fazda local model testi yapılmaz; local server/inference başlatılmaz ve daha önceki
  local prefix bu fazın kapanış kanıtı sayılmaz.
- **Faz 8A — Dar Orders truth zinciri:** güçlü cloud modelle sync/count/list/exact
  selection/label zinciri ve correction/contradiction varyasyonları çalıştırılır. Her
  cevap source-truth oracle ile doğrulanır. 8A kapanmadan web, Excel veya uzun sohbet
  kampanyasına geçilmez.
- Bu zincir yalnız gerçek Chat ürün yolunda kabul edilir. Direct tool/harness sonucu
  teşhis ve regresyon önkoşuludur; modelin observation sonrası next-action kararını ve
  kullanıcıya gösterilen grounded final cevabı ikame etmez.
- Doğru görünen bir final cevap tek başına model/agent başarısı değildir. Provenance'ta
  gerçek provider cevabı, model-authored plan, observation sonrası karar ve grounded
  response ayrı ayrı görünmelidir. Provider cevap vermediğinde deterministic read recovery
  güvenli cevap üretebilir; fakat bu koşu cloud/model kabulü diye sayılamaz.
- Sync, count, list, selection ve label adımları generic manual route veya sabit Python
  workflow'una devredilemez. Her biri catalog'dan getirilen domain-owned atomic
  operation'dır; model gerekli observation'ları gördükçe bir sonraki adımı seçer.
- Source UI/chat runtime, canonical operation'ın kullandığı gerçek DB kimliğini ve
  çözülen account/store/environment scope'unu task runtime'a açıkça taşır. `db_name`
  veya active scope'un arada düşmesi yüzünden Production `[1]` sorgusunun bütün hesaplara
  genişlemesi kritik kabul hatasıdır.
- Persisted approval/resume yalnız DB scope'u değil, hazırlama turundaki provider/model
  politikasını da taşır. Provider kaydından yalnız güncel credential yeniden okunur; provider
  kimliği, actual model, reasoning, fallback açık/kapalı kararı, sanitized capability route ve
  etkili generation ayarları task boyunca pinlidir. Snapshot hash'i uyuşmazsa çağrı yapılmaz.
- `entity=order` için `waiting_action` geçerli bir Orders status'u değildir. Bekleyen
  sipariş/kargo kuyruğu typed olarak `ready_to_ship`; açık adet isteği de model `list`
  dese dahi `metric=count` olarak doğrulanır. Bu doğrulama canonical operation derlemeden
  önce yapılır.
- Correction/objection geldiğinde source Chat eski pending task'i yalnız UI'da gizlemez;
  aynı task-store içindeki canonical state'i `superseded` olarak persist eder. Eski action
  ID ile resume fail-closed kalır; yeni plan eski proposal'ın mutable devamı değil, exact
  selection provenance'ı taşıyan yeni bir action'dır.
- Güçlü ücretli cloud model yalnız runtime ile model kalitesini ayıran kontrol koşusudur;
  kullanıcı açıkça onaylamadan ücret harcanmaz ve bu koşu ücretsiz cloud acceptance'ın
  yerine geçmez. Ürün mevcut provider'ların her birinde en az bir erişilebilir güçlü
  ücretsiz cloud model frozen Orders zincirini geçmeden ücretsiz modellerle güvenilir
  ilan edilemez; bir provider'ın başarısı diğer provider'ın kabulünün yerine geçmez.
- **Faz 8B — Orders capability geri açma:** 8A'dan sonra manuel Orders parity'sindeki
  diğer read/analysis/action akışları; ardından web araştırması ve Excel/artifact
  composition frozen konuşmaları güçlü cloud modelde çalıştırılır.
- **Faz 8C — Ücretsiz cloud ve uzun kabul:** aynı frozen senaryolar erişilebilen en iyi
  ücretsiz Gemini/OpenRouter modellerinde tekrarlanır; limit doldukça aynı provider'daki
  sıradaki uygun modele geçilir. Sonrasında cloud modellerle 50/60/100 ve gerekirse
  200+ görünür mesaj kampanyaları yürütülür.
- Her assistant cevabı Codex tarafından sırayla doğrudan incelenir.
- Production R0/R1 read/reversible kanıtı ve Trendyol Stage Seller `2738` R0/R1/R2
  agentic kanıtı aynı source/scope/read-back sözleşmesini kullanır.
- Stage sync kabulünde external fetch'in dönmesi tek başına başarı değildir. Empty veya
  dolu sonuçta source snapshot + DB reconciliation kapanmadıysa verify başarısız kalır;
  kök neden bulunmadan aynı API çağrısı tekrarlanmaz ve Production'a fallback yapılmaz.
- Offscreen source-app testleri yalnız gerçek runtime akışını gözlemek için yapılır;
  Faz 8A kapanmadan görsel redesign/polish yapılmaz.
- Başarı kriteri: dar Orders truth zincirinde tek set sapması yok; correction gerçekten
  replan ediyor; sonra açılan web/report/long-context/multi-tool akışları aynı
  güvenilirliği doğal kullanıcı seviyesinde koruyor.

Local capability mimaride korunur fakat local uzun sohbet/acceptance cloud kapısından
sonra açılacak ayrı bir kampanyadır; mevcut Faz 8'i veya Orders kapanışını bloke etmez.

Uygulama durumu (2026-07-22): `in_progress`. Orders sync artık generic manual route yerine
exact account kapsamlı `orders.fetch.prepare` atomic operation'ına bağlanmıştır. İlk gerçek
Stage koşusunda source çağrısı tekrarlanmadan kayıtlı audit yeniden doğrulanmış; 34 kaynak
satırının 32 kalıcı operasyonel paketi ve 32 kalemi exact DB read-back ile kapanmıştır.
Kalıcı package kimliği henüz oluşmamış 2 `Awaiting` satırı için ID uydurulmamış, bunlar
non-actionable policy exclusion olarak ayrıca sayılmıştır. Aynı kimlik eksikliği
`Created/Picking/...` gibi işlem yapılabilir bir statüde fail-closed kalır. Bu kanıt yalnız
source/execute verifier katmanını kapatır; gerçek cloud Chat ürün yolunda model-authored
sync -> observation -> next-action/recovery zinciri ve correction kabulü hâlâ açıktır.
Kanıt: `AI/docs/agentic_control_plane_phase8a_stage_sync_replay_2026-07-22.json`.

Aynı gün yapılan fallback-kapalı exact `gemini-3.5-flash` source-app kontrolü provider
project quota sınırında modele ulaşmadan fail-closed kalmış; hiçbir business tool
çalışmamış ve actual-model kanıtı oluşmamıştır. Bu sonuç cloud kabulü değildir. Account/
provider quota sürerken rastgele model denemesi yapılmaz; erişim açıldığında aynı frozen
ürün-yolu konuşması kaldığı yerden çalıştırılır. Kanıt:
`AI/docs/agentic_control_plane_phase8a_cloud_gate_2026-07-22.json`.

Cloud erişimini ikame etmeyen deterministic cloud-contract fixture'ında gerçek
`AITab -> typed turn -> GoalPlan -> atomic read -> Observation -> model goal evaluation
-> grounded final synthesis` ürün yolu ayrıca dondurulmuştur. İlk model cevabındaki yanlış
`0` sayısı yayınlanmadan reddedilmiş, authoritative sayı verilen tek bounded repair modeli
tarafından düzeltilip yeniden doğrulanmıştır; repair de yanlış kaldığında verified
deterministic projection kullanılmıştır. Interpretation/evaluation/synthesis model çağrı
provenance'ı ve bütün response reason code'ları typed state'te görünürdür. Bu yalnız runtime
contract kanıtıdır; gerçek cloud kabulü değildir. Kanıt:
`AI/docs/agentic_control_plane_phase8a_response_repair_2026-07-22.json`.

Faz 8A capability discovery auditinde atomic `orders.fetch.prepare` operasyonunun doğal
"güncel siparişleri çek/kaydet/senkronize et" hedefinde retrieval yüzeyine girmediği,
sync'in arka plandaki deterministic template sayesinde çalışabildiği bulunmuştur. Genel
query-side semantic alias ve Türkçe çekim normalizasyonu sonrası sync ve exact-order
`orders.full_context` ilk aday; label yazdırmada `labels.create_from_orders.prepare`
işaretleme operasyonunun önündedir. Observation sonrası modelin önerdiği `orders.count`
replanı da "sipariş sayısını/toplam" ifadesinde catalog doğrulamasından geçmektedir.
Generic manual router planner adayına alınmamıştır. `291` ilgili test geçmiş, `178`
koşullu cloud testi skip edilmiştir. Bu bounded retrieval/control-plane kanıtıdır; gerçek
cloud model seçimi ve ürün-yolu kabulünü kapatmaz. Kanıt:
`AI/docs/agentic_control_plane_phase8a_operation_retrieval_2026-07-22.json`.

Aynı audit, eski test sözleşmesinin model `ready-list + label` seçtiğinde Python'ın bunu
silip kendiliğinden sync planına çevirmesini başarı saydığını da göstermiştir. Orders direct
plan doğrulaması artık eksik business step'i materialize etmez. Policy ilgisiz/izinsiz model
adımını düşürebilir, canonical ad çözebilir ve typed selection/account bağlayabilir; fakat
`semantic_missing_step_ids` varsa aynı modele reason code ve bounded catalog ile yalnız bir
repair çağrısı yapılır. Repair geçerse bütün model-authored kaynaklar aynı act-mode, action
type, exact target/fingerprint ve prepared-action verifier'ından geçer; repair de geçmezse
`needs_clarification` durumunda sıfır tool/etkiyle durur. Yanlış sync planının deterministic
template ile değiştirilmediği, doğru model repair'inin atomic sync prepare ürettiği ve
komşu action zincirlerinin korunduğu testlidir. Bu bounded source-contract kanıtıdır; gerçek
cloud kabulü değildir. Kanıt:
`AI/docs/agentic_control_plane_phase8a_model_plan_authority_2026-07-22.json`.

Model-plan authority ayrıca görünür UI açılmadan gerçek source Chat giriş fonksiyonu
`AI.views.chat_tab._run_chat_turn_with_runtime` üzerinden dondurulmuştur. Aynı offscreen
cloud-contract senaryosunda model sync için yalnız `orders.fetch.prepare`, önceki exact
ready selection'ı etiketlemek için yalnız `labels.create_from_orders.prepare` seçmiştir;
iki planda da kaynak `llm_direct`, `deterministic_business_steps_inserted=false` ve
`semantic_inserted_step_ids=[]` kalmıştır. Label planı bilerek active 11'li setten yalnız 3
target ID önermiş; policy yeni step eklemeden partial argümanı `context_rebound_step_ids`
provenance'ıyla immutable active selection'a bağlamıştır. Aradaki typed count/read compiler'ı 11 gerçek
ready kaydı tek immutable selection'a bağlamış, 5 simülasyon kaydını dışlamış; label prepare
aynı selection ID, query fingerprint, source revision ve snapshot hash ile 11/11/11
preview/execute kapsamı üretmiştir. Approval öncesi hiçbir external sync, dosya veya fiziksel
yazdırma çalışmamıştır. Aynı persisted source Chat action'ı onaylandıktan sonra canonical
Labels pipeline izole temp dizinde DOCX üretmiş; verifier aynı 11 order number'ın tamamını
DOCX içeriğinden read-back ile doğrulamıştır. Fiziksel yazıcı çalıştırılmamıştır. Orders task
runtime `165 passed / 179 conditional skipped`, tam AI domain paketi
`987 passed / 559 conditional skipped` sonucundadır. Bu ürün
kodu yolunda bounded sözleşme kanıtıdır; gerçek provider/model kabulü değildir. Kanıt:
`AI/docs/agentic_control_plane_phase8a_source_chat_authority_2026-07-22.json`.

Persisted source Chat approval yolunda ayrıca bir DB-scope süreklilik açığı bulunmuştur.
Prepare action doğru `db_name` payload'ı taşısa da `_run_approved_chat_action`, task'i
`resume_agent_task_by_id` ile açarken aynı DB bağlamını vermiyordu; execute sonrası
observation/replan/read-back varsayılan Production DB'ye kayabilirdi. Resume artık açıkça
source Chat'in canonical `DB_NAME` değeriyle sürer. Offscreen entegrasyonda model-authored
Stage sync prepare -> inline approval -> isolated fake Stage fetch -> gerçek izole DB save
-> verifier read-back zinciri 2 source row = 2 saved snapshot = 2 read-back invariant'ıyla
tamamlanmıştır. Gerçek Trendyol API çağrısı yapılmamıştır; bu bounded ürün-yolu kanıtıdır.

Aynı persisted approval yolunda model-runtime sürekliliği de tek canonical sözleşmeye
bağlanmıştır. Task state API key/endpoint saklamadan provider kimliği, actual model,
reasoning effort, fallback kararı, sanitized model capability metadata'sı, canlı free-route
snapshot'ı ve etkili generation ayarlarını hash'li policy snapshot olarak taşır. Provider
kaydı sonradan model/fallback/temperature bakımından değişse bile resume hazırlama turundaki
politikayı kullanır; snapshot değiştirilmişse provider çağrısından önce fail-closed durur.
İlk tur fallback ile başka actual modele geçtiyse resume metadata'sı route içindeki o actual
model capability'sine yeniden bağlanır. Bu bounded süreklilik kanıtıdır; gerçek provider
Faz 8A kabulünün yerine geçmez.

Label execute incelemesinde DB scope'un verifier'da doğru olmasına rağmen canonical Labels
fonksiyonunun sipariş detayını global varsayılan DB'den okuduğu bulunmuştur. `db_name` artık
approval payload'ından ince AI adapter ile `Labels.processors.pipeline.create_order_label_from_orders`
ve oradan `Orders.processors.trendyol.pipeline.get_order_full_details_by_numbers` fonksiyonuna
açıkça iletilir. Böylece prepare, execute ve read-back aynı DB kimliğinde kalır; testin geçmesi
için domain globalini monkeypatch etme gereksinimi kaldırılmıştır. İlgili domain regresyonları
`96 passed`, geniş AI control-plane paketi `291 passed / 178 conditional cloud skipped`tir.

Correction yaşam döngüsü incelemesinde source Chat'in task-backed kapsam düzeltmesini UI'da
`superseded` diye göstermesine rağmen persisted task'i canonical olarak `cancelled` bıraktığı;
ayrıca custom task-store root ve dönen canonical state'in konuşma state'ine taşınmadığı
bulunmuştur. Session/task runtime'a ayrı typed supersede geçişi eklenmiş; state, goal plan,
action history ve remaining-step temizliği tek canonical fonksiyonda birleştirilmiştir.
Source Chat artık aynı session/action/store kimliğiyle bu geçişi çağırır ve dönen persisted
state'i uygular. Cancellation aynı ortak terminal-resolution sözleşmesini kullanır fakat
`cancelled` semantiğini korur.

Bu düzeltmenin ilk gerçek offscreen source-controller koşusu ikinci bir control-plane
kusurunu açığa çıkarmıştır: model correction turunu typed olarak "tüm ready seti yeniden oku
ve etikete hazırla" diye doğru yorumladığı hâlde runtime ham eliptik kullanıcı cümlesini plan
hedefi yapıp correction'ı deterministic tek read'e indiriyor ve label action'ını düşürüyordu.
`action_result` isteyen geçerli model-authored correction artık read-recovery tarafından
preempt edilmez; typed objective schema/policy/semantic verifier sınırları içinde canonical
planning objective olur, özgün kullanıcı mesajı audit/state kanıtı olarak korunur.

Frozen offscreen cloud-contract zincirinde eski 4'lü label task'i persisted `superseded`
olmuş, remaining/pending state'i temizlenmiş, eski kart ve action ID ile resume reddedilmiş;
model `llm_direct` kaynaklı `orders.ready_to_ship -> labels.create_from_orders.prepare`
GoalPlan'ını kurmuş ve deterministic business step eklenmemiştir. Yeni action güncel 11
ReadyToShip kaydın 11/11 exact setini taşımış; chat içinden onay sonrası canonical Labels
pipeline temp DOCX üretmiş, içerik verifier aynı 11 order number'ı doğrulamış ve sohbetin
canonical state'i `complete` olarak geri bağlanmıştır. Fiziksel yazıcı çalışmamıştır.
Chat/session/task paketi `254 passed / 179 conditional skipped`, tam AI domain paketi
`987 passed / 559 conditional skipped` sonucundadır. Bu bounded ürün-yolu kanıtıdır; gerçek
provider/model Faz 8A kabulünün yerine geçmez. Kanıt:
`AI/docs/agentic_control_plane_phase8a_source_chat_authority_2026-07-22.json`.

OpenRouter canlı ücretsiz katalog kontrolü 14 chat-eligible rota döndürmüştür. Kayıtlı eski
`openai/gpt-oss-120b:free` rotası provider cevabı üretmeden `404`; policy sırasındaki ilk
canlı ücretsiz `google/gemma-4-26b-a4b-it:free` ise fallback kapalı source Chat denemesinde
account quota/rate-limit kapısında durmuştur. Her iki durumda da `actual_model` boş,
`model_response_received=false`; doğru görünen 11 ready count cevabı model başarısı değil
`typed_canonical_read_recovery` sonucudur. Label ve Stage sync prepare oluşmamış, hiçbir
marketplace API/DB sync/dosya/yazıcı etkisi gerçekleşmemiştir. Provider erişimi değişmeden
sıradaki modellere kör deneme yapılmaz.

Bu kontrolde typed turn prompt'unun elle kopyalanmış domain enumunun canonical JSON schema
ile çeliştiği de bulunmuştur: prompt artık bütün enumları doğrudan şemadan türetir, sipariş
etiketi/sync/iade domain ownership'i Orders'a bağlanır ve bozuk typed turn için yalnız bir
bounded model repair yapılır. Provider `404/429` ile hiç model cevabı vermediyse repair için
ikinci ağ çağrısı yapılmaz. Repair alamazsa deterministic safe read recovery uygulanabilir
fakat provenance'da repair `applied=false` kalır. Source runtime ayrıca provider denemesini
gerçek cevaptan ayırır: `model_invocation_attempted` ve `model_response_received` farklı
alanlardır; actual model boşken `model_invoked=true` yazılamaz. Kanıt:
`AI/docs/agentic_control_plane_phase8a_openrouter_cloud_gate_2026-07-22.json`.

Uygulama durumu (2026-07-26): `in_progress / real_cloud_label_gate_open`. Gerçek
offscreen source-app Chat koşusunda Gemini `gemini-3.5-flash` kota nedeniyle model cevabı
verememiştir. Bu tur artık kullanıcıdan anlamsız açıklama istemek yerine effectsiz
`provider_unavailable` olarak kapanır; tool, approval, DB veya dosya etkisi yoktur. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3.5-flash-provider-unavailable-source-ui-2026-07-26.json`.

OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` ile fallback kapalı gerçek ürün
yolunda ilk iki tur geçmiştir. Model önce `orders.ready_to_ship_count`, sonra
`orders.query` atomic operation'ını `llm_direct` seçmiş; Production hesap `[1]` için 5
simülasyon dışarıda bırakılarak aynı 11 ReadyToShip sipariş sayılmış ve listelenmiştir.
Count ile list adımı aynı immutable selection ID, exact 11 record ID ve
`f3a5b93331168658bae6622f1519a01396123940c4cd5ca911f24c4824dff70a` source snapshot
hash'ini taşımıştır. İç `period_label` sızıntısı final-response verifier'a bağlanan genel
internal-marker yasağıyla kapatılmış; exact query'nin yeni seçim üretmesi ortak
Orders-owned projection/hash ve selection-lineage doğrulamasıyla düzeltilmiştir.

Aynı gerçek konuşmanın önceki TANEX 2610 red teşhisi düzeltilmiştir. Kanıttaki
`<order-001>` ... `<order-011>` değerleri modelin uydurduğu placeholder'lar değil,
`LiveEvidenceRedactor` tarafından artifact yazımında maskelenen gerçek sipariş
numaralarıdır. Pre-redaction incelemede modelin `act/orders`,
`labels.create_from_orders.prepare` ve gerçek 11 kimliği doğru ürettiği; shared
deterministic authorization guard'ın kullanıcının doğal “etiket hazırlığını yap”
isim-fiil biçimini tanımadığı için doğru planı reddettiği görülmüştür. Ortak
positive-prepare dil primitive'i `hazırla/prepare` yanında `hazırlık/hazırlama + yap/
oluştur/başlat/tamamla` biçimlerini kapsayacak şekilde düzeltilmiş, negatif/read-only
komşu regresyonlar korunmuştur.

2026-07-27 gerçek fallback-kapalı OpenRouter source-app tekrarında count -> exact list ->
TANEX 2610 prepare zinciri model tarafından `llm_direct` geçmiştir: Production `[1]`
kapsamında 11 ReadyToShip ve 5 simulation exclusion doğrulanmış; count ve list aynı
`5cd3448cfec7e46e00e9d947cb1bb70d` selection ID ile
`f3a5b93331168658bae6622f1519a01396123940c4cd5ca911f24c4824dff70a` snapshot hash'ini
taşımış; prepare 11/11 kayıt, canonical `TANEX_2610`, 11 preview/ref/execute input ile
onay sınırında durmuş ve API/DB/dosya/yazıcı etkisi üretmemiştir. İç `all` period enumu
tool mesajında da ortak humanization ile kapatılmış; final cevap
`verified_model_candidate` olarak doğrulanmıştır. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-real-count-list-label-r7-2026-07-27.json`.

Ancak aynı R7 koşusunun dördüncü read-only takip sorusunda Chat UI, “bu hazırlık hangi
sipariş kümesine ve hangi şablona bağlı, dosya üretildi mi?” mesajını yanlışlıkla kapsam
revizyonu sayıp 11'li pending action'ı `superseded` etmiş; görünür cevap ise çelişkili
biçimde hâlâ onay beklediğini söylemiştir. Kampanya bağlayıcı karar 10/11 uyarınca bu
noktada kesilmiş; pending-read classifier, UI supersede önceliği ve label pending
projection'ı ortak katmanda düzeltilmiş, exact soru ile gerçek scope-correction/identity
objection komşu testleri birlikte geçirilmiştir. Düzeltme sonrası R8 ilk count turunu
aynı exact 11'li oracle ve verified model final ile yeniden geçmiş; ikinci turda seçili
Nemotron ücretsiz rota `http_429` verdiği için hiçbir tool/effect çalışmadan kampanya
effectsiz durmuştur. Bu kota sonucu ürün başarısı değildir ve aynı tur içinde sessiz
fallback yapılmamıştır. Kanıtlar:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-real-count-list-label-r7-2026-07-27.json`,
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-real-count-list-label-r8-2026-07-27.json`.

Katalogdaki sıradaki güçlü ücretsiz tool-capable rota
`nvidia/nemotron-3-super-120b-a12b:free` R9 fresh process'te açıkça pinlenmiş; fakat daha
ilk invocation'da yine `http_429` dönmüştür. `actual_model` boş, tool/effect sıfır ve
fallback kapalıdır; bu, model özelinden çok güncel OpenRouter hesap/provider kota kapısı
olarak kaydedilmiştir. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-super-real-count-list-label-r9-2026-07-27.json`.

2026-07-27 gerçek fallback-kapalı Gemini `gemini-3-flash-preview` R1 koşusunda ilk count
turu Production `[1]` kapsamında 11 ReadyToShip ve 5 simulation exclusion ile geçmiştir.
İkinci turda model doğru `orders.query` operation'ını ve exact 11 sipariş kimliğinin
tamamını üretmiş; fakat AI wrapper'daki gizli `limit=10` varsayılanı yalnız 10 kayıt
materialize etmiştir. İstenen kimliklerin ham argümandan conversation selection'a taşınması
eksik kaydı görünmez kılabildiği için kampanya o anda kesilmiştir. Ortak Orders query ve
task-runtime katmanı exact ID cardinality'yi otomatik bağlayacak, selection'ı yalnız gerçek
materialize edilen satırlardan kuracak ve eksik/fazla/truncated exact read'i fail-closed
reddedecek biçimde düzeltilmiştir. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3-flash-preview-count-list-label-pending-r1-2026-07-27.json`.

Gemini R2 fresh process tekrarında count ve exact list aynı 11'li immutable selection,
selection ID `5cd3448cfec7e46e00e9d947cb1bb70d` ve
`f3a5b93331168658bae6622f1519a01396123940c4cd5ca911f24c4824dff70a` snapshot hash'iyle
geçmiştir. Ardından model `labels.create_from_orders.prepare` operation'ını `llm_direct`
seçmiş; canonical `TANEX_2610`, 11 selected/preview/execute ref ile approval sınırında
durmuş, API/DB/dosya/yazıcı etkisi üretmemiştir. Böylece ilk üç tur gerçek model +
gerçek source-app ürün yolunda doğrulanmıştır.

Ancak R2'nin dördüncü read-only pending sorusunda yeni bir ortak runtime hatası
bulunmuştur. Gemini turn interpretation çağrısı pending hazırlığın kapsam/artifact
durumunun sorulduğunu doğru anlamış; sonraki plan çağrısı buna rağmen `orders.query`
seçmiştir. Bu iki structured model çağrısından sonra final response synthesis çağrısı
`http_429` vermiş ve runtime tool mesajını “all döneminde 11 sipariş eşleşti” diye başarı
olarak yayımlamıştır. Pending action'ın korunması ve `superseded_count=0` doğru olsa da
business tool gereksizdir, cevap soruyu yanıtlamaz ve iç `all` enumunu sızdırır. Ayrıca
runtime yalnız son invocation'ın `429` durumuna bakıp önceki gerçek model cevaplarını
kaybetmiş; `actual_model` boş ve `model_invoked=false` yazarak çok çağrılı tur
provenance'ını yanlış özetlemiştir. Bu nedenle R2 başarısızdır; hata Gemini'nin genel
zekâsına değil pending state'in pre-provider guard'ı atlamasına, model planının control
state sorusunu business read'e çevirebilmesine ve invocation provenance'ın last-write
olmasına aittir. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3-flash-preview-count-list-label-pending-r2-2026-07-27.json`.

Uygulama güncellemesi (2026-07-27): pending açıklama guard'ı artık source Chat
orchestration girişinde, provider hesabı/client oluşturulmadan önce aktif immutable
`PendingActionSnapshot` üzerinden çalışır. Bu yolda model/interpretation/task planner ve
business tool çağrısı sıfırdır; aynı action ID ile pending state korunur. Label şablonunun
gerçek typed context'te top-level değil `safe_payload.model_code` içinde tutulduğu da
ortak pending projection'da düzeltilmiştir. Salt dosya/kapsam sorusu için ayrıca “onay/
bekleyen/hazırlık” kelimesi şartı kaldırılmış; yalnız aktif pending state + ortak read-only
classifier birlikte guard'ı açar. Exact pending soru, paraphrase, do-not-run, gerçek scope
correction, identity/status objection, approve ve cancel komşuları aynı pakette geçmiştir.

Çok çağrılı provider provenance'ı da append-only `invocation_outcome_history` ile
düzeltilmiştir. Her invocation contract requested/actual model, response-received, error
ve fallback sonucunu ayrı taşır; `model_response_count`,
`any_model_response_received`, `final_model_response_received` ve
`last_successful_actual_model` birbirinden ayrıdır. “Önce structured cevap, sonra final
429” Gemini regresyonu bu sözleşmeyi doğrulamıştır. Offscreen kanıt özeti: provider
adapter paketi `25 passed`; Chat paketi `73 passed + 9 subtests`; pending/cardinality
odaklı ek paket `4 passed`; ilgili modüller `py_compile` geçmiştir. Bütün
`test_ai_pipeline.py` koşusu üç dakikalık dış komut sınırında sonuç üretmeden kesildiği
için bu geniş koşu başarı olarak sayılmamıştır.

Son ortaklaştırma (2026-07-27): provider provenance hesabı Chat, task resume ve güncel
source-evidence tüketicilerinin kullandığı tek canonical projeksiyona alınmıştır. Shared
client kullanan uzun konuşma runtime'ı turn başlangıç offset'lerini kaydeder ve yalnız o
turun invocation slice'ını yayımlar; invocation ledger üzerindeki eski `16` kayıt kırpması
kaldırılmıştır. Pending-action pre-provider read guard'ı da yalnız source UI'da değil,
UI-bağımsız uzun konuşma runtime'ında aynı shared callable üzerinden çalışır. Görünür cevap
exact kapsam/şablon yanında “dosya üretilmedi” durumunu açıkça söyler; action state'i
korunur. Güncel offscreen kanıt: provider + conversation + Chat paketleri `109 passed`;
task actual-model pinleme ve v5 source-evidence kapıları `27 passed`; pending scope pipeline
regresyonu `1 passed`; uzun-sohbet human-review/reviewer paketi `14 passed`; değişen
modüller `py_compile` geçmiştir. Bu bounded kanıt gerçek fresh cloud dört-tur kabulünün
yerine geçmez.

Kapanış doğruluk reseti (2026-07-27): 18 Temmuz tarihli manifest ve completion audit'in
Orders'ı kapalı/proven gösterdiği, güncel `goals.md` ile çeliştiği saptanmıştır. Manifest
schema v2'ye alınmış; eski 24 artifact `historical_baseline` olarak ayrılmış, current
proven slice boşaltılmış, R2/R3 yalnız diagnostic evidence yapılmış ve 27 Temmuz pending/
provider-provenance regresyonu latest binding open regression olarak eklenmiştir. Closure
checklist artık local/paid kanıtı Faz 8 current scope'ta saymaz; pending-read,
approval/execute/read-back ve correction/supersession için ayrı gerçek source-UI v6
kapıları ile goals bölüm audit'ini zorunlu tutar. `orders_agentic_completion_audit.md`
authoritative biçimde `open` olarak yeniden yazılmıştır. Böylece eski yeşil artifact'lar
korunur fakat yeni failure'ı geçersiz kılamaz.

Fresh-process Gemini R3 gerçek source-app koşusu yeni kaynak fingerprint'iyle başlatılmış,
fakat ilk “başkan kaç sipariş var bekleyen” invocation'ında exact
`gemini-3-flash-preview` `http_429` vermiştir. Tur `provider_unavailable`, actual model
boş, response count `0`, tool/approval/effect sıfır ve fallback kapalı kapanmıştır;
kampanya dördüncü pending-read turuna ulaşmadan kesilmiş ve kör tekrar yapılmamıştır.
Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3-flash-preview-count-list-label-pending-r3-2026-07-27.json`.

Fresh-process Gemini R4, evidence contract v5 ile aynı exact modelde bir kez daha
çalıştırılmış; ilk count invocation'ı yine `http_429` vermiştir. V5 provenance gerçek
durumu kaybetmeden `model_invocation_attempted=true`, response count `0`, actual/final
actual model boş, tek başarısız `structured_output` outcome ve fallback kapalı olarak
kaydetmiştir. Business tool, approval, API, DB, dosya ve yazıcı etkisi oluşmamıştır.
Bu artifact model kabulü değil, provider-unavailable diagnostic kanıttır; kota
düzelmeden kör tekrar yapılmayacaktır. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3-flash-preview-count-list-label-pending-r4-2026-07-27.json`.

Aynı v5 source-app kapısı OpenRouter
`nvidia/nemotron-3-ultra-550b-a55b:free` ile R10 fresh process'te çalıştırılmış;
ilk count invocation'ı `http_429` vermiştir. Runtime yine response count `0`,
actual/final actual model boş, tek başarısız `json_text_guarded` outcome, fallback
kapalı ve sıfır business tool/effect kaydetmiştir. Bu da kabul değil diagnostic
kanıttır. İki mevcut provider hedefi nedeniyle Phase 8 source-UI kapanışı yalnız
Gemini ile daraltılamaz; aynı frozen zincir güncel en iyi ücretsiz Gemini ve
OpenRouter modellerinde ayrı fallback-kapalı kanıtlarla geçmelidir. Kanıt:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-count-list-label-pending-r10-2026-07-27.json`.

Phase 8A kapanış kapısı semantic contract ile sertleştirilmiştir. Dört/beş/altı adet
alakasız fakat teknik olarak başarılı tur artık pending-read, execute/read-back veya
correction/supersession kanıtı sayılamaz. Validator cardinality'yi `11` diye
hard-code etmez; ilk authoritative count observation'ından dinamik exact seti çıkarır
ve list, TANEX 2610 prepare, immutable action/selection, sıfır-provider pending-state
projection, fresh DOCX payload/content verify ve corrected replacement execute boyunca
aynı kimlikleri doğrular. Eski action ID execute edilirse, pending sorusu provider/tool'a
kaçarsa, görünür cevap dosya üretilmedi bilgisini taşımazsa veya arbitrary green turns
verilirse kapı fail-closed kalır.

Artifact'ın koşu başı ve koşu sonu fingerprint eşitliği tek başına yeterli değildir.
Closure anında artifact fingerprint'i güncel 26 dosyalık AI/Orders/Labels ürün ve
acceptance yüzeyiyle
de karşılaştırılır; `main.py`, source shell/Chat, provider adapter/policy, conversation/
task/state/catalog/verifier/runtime katmanları, canonical Orders repository/pipeline,
evidence runner/validator/redactor, Labels pipeline/constants ve `TANEX_2610.docx` bu
bağa dahildir. Bu yüzeyde artifact
sonrası yapılan değişiklik eski kabulü otomatik olarak geçersiz kılar.

Sıradaki gerçek-cloud adım kota penceresi açıldığında aynı frozen dört turu yeni fresh
process'te iki provider için baştan çalıştırmaktır. Pending-read alt kapısı ancak
dördüncü turda provider çağrısı olmadan o koşunun authoritative exact count/set'i +
TANEX 2610 + “dosya üretilmedi”, aynı action/selection kimliği,
`superseded_count=0`, sıfır tool/effect ve doğal cevap birlikte görülürse kapanır.
Deterministic/offscreen regresyon güvenlik sözleşmesini kanıtlar; gerçek fresh ürün-yolu
revalidation'ın yerine geçmez.

Gerçek kullanıcı regresyonu izlenebilirliği de aynı fail-closed disipline alınmıştır.
19 Temmuz'daki on control-plane invariant'ı ile 27 Temmuz'daki beş pending/provenance
invariant'ının her biri artık regression artifact'ında ayrı `owner_layer`,
`bounded_status`, çalıştırılabilir `guard_tests` ve `live_acceptance_gate` taşır. Closure
validator eşleme eksikse, aynı invariant iki kez yazılmışsa, guard test dosyası yoksa veya
failure ID kümesiyle contract ID kümesi birebir değilse artifact'ı geçersiz sayar. Güncel
iki artifact'tan çıkarılan 18 benzersiz guard node'u birlikte `18 passed` geçmiştir.
En ağır scope-revision guard'ı ayrıca çıplak `AITab` kurulumundan gerçek
`main.py -> MainInterface -> lazy AI tab` source-app shell'ine yükseltilmiştir. Aynı
offscreen izole koşu, aktif label kartı hakkındaki read-only sorunun sıfır yeni planner
çağrısıyla aynı action'ı koruduğunu ve “dosya üretilmedi” cevabını verdiğini; ardından
scope correction'ın eski persisted task/action'ı `superseded` yaptığını, stale kartı
reddettiğini, yeni exact seti TANEX 2610 ile hazırlayıp yalnız temp DOCX ürettiğini ve
`payload_and_docx_content` read-back ile tamamladığını birlikte doğrular.

Canlı ücretsiz model rota auditinde de model kalitesini bozan bir sıralama hatası
bulunmuştur: ölçülmüş quality/reliability boşken eşit capability skorları alfabetik model
ID ile çözülüyor; Gemini 2.5 Flash ilk, OpenRouter Gemma ilk görünürken kullanıcı tarafından
seçilen Nemotron Ultra altıncı sıraya düşüyordu. Quality tier artık tek
`provider_catalog_policy` sınırında tarih/kaynak metadata'sıyla tanımlanır, canlı katalog
kayıtlarına `pipeline` tarafından eklenir ve `model_routing` tier -> capability score ->
model ID sırasıyla route üretir. Bilinmeyen modeller yasaklanmaz; ölçülene kadar tier `0`
kalır. Secret yazmadan yapılan güncel canlı katalog okumasında Gemini ilk üçü
`gemini-3.5-flash -> gemini-3-flash-preview -> gemini-2.5-pro`, OpenRouter ilk üçü
`Nemotron Ultra -> Nemotron Super -> Gemma 31B` olmuştur. Merkezi policy/routing/catalog
regresyonları `12 passed`, geniş provider/fallback seçkisi `73 passed` geçmiştir.
Secret-free acceptance catalog da canlı route sırasını ve `preferred_free_model` alanını
korur; ölçülmemiş kaliteyi puanlamaz ve credential sızdırmaz.

Son R4 Gemini ve R10 OpenRouter artifact'ları yalnız `http_429` kaydetmiş; normalize
edilmiş `quota_scope`, error category ve fallback karar gerekçesini source-UI evidence'a
taşımamıştır. Bu nedenle bu iki koşudan "model kotası" ya da "provider/account kotası"
sonucu çıkarılamaz; ikisi de yalnız scope'u bilinmeyen provider-unavailable diagnostic
kanıttır.

Bu eksik deterministic zincir 2026-07-27'de evidence contract v6 ile kapatılmıştır.
Provider normalizer artık Gemini `PerProjectPerModel` dimension'ını model scope sayar;
project/account/provider ve belirsiz `429` kardeş-model rotasını durdurur, yalnız açık
model scope aynı typed state ile sıradaki quality-route modeline izin verir. Bounded
`retry_after`, category, scope, fallback izni/duruş gerekçesi ve her önceki hata
invocation outcome -> turn plan -> task runtime -> source-UI artifact boyunca secret-safe
append-only taşınır. Başarılı fallback ilk model hatasını silemez. Source-UI validator v6,
`429` scope kanıtı eksikse, provider-genel scope fallback'e izin veriyorsa veya normalized
history ham alan taşıyorsa fail-closed kalır. Odaklı kanıt: provider/model routing
ve closure paketi `56 passed`, Orders task runtime `176 passed`, Chat yüzeyi
`73 passed`, provider/model odaklı geniş pipeline seçkisi `57 passed`, source-UI
artifact validator `24 passed`; değişen altı runtime/evidence modülü `py_compile`
geçmiştir. Live/opsiyonel testlerin skip edilmesi gerçek cloud acceptance yerine
sayılmamıştır.

Bu bounded kanıt eski R4/R10 artifact'larını geriye dönük olarak scope-proven yapmaz.
Sıradaki gerçek-cloud koşu yeni v6 sözleşmesiyle alınır; normalize scope `model` ise
normal ürün rotası sıradaki güçlü ücretsiz modele geçebilir, exact-model acceptance
fallback kapalı kalır. Scope provider-genel veya `unknown` ise yeni model ruleti
başlatılmaz.

Bu politika fresh gerçek koşuda da doğrulanmıştır. Gemini 3 Flash Preview R6,
Gemini 3.5 Flash R7 ve Gemini 2.5 Pro R8 `429` yanıtlarını secret-safe biçimde
`quota_scope=model` olarak kaydetmiş; exact-model acceptance fallback kapalı kaldığı
halde route policy provider/account genelinde durmamış ve katalog sırasındaki erişilebilir
Gemini 3.1 Flash Lite'a ilerlemiştir. Gemini 3.1 Flash Lite R9 ile OpenRouter Nemotron
Ultra R14, fallback kapalı current-source source-app üzerinde şu frozen zinciri ayrı ayrı
geçmiştir:

1. Model-authored `orders.ready_to_ship_count` ile dynamic exact count `11`
2. Model-authored `orders.query` ile aynı immutable 11 siparişin eksiksiz listesi
3. Model-authored `labels.create_from_orders.prepare` ile aynı selection ID, query
   fingerprint ve source snapshot hash'e bağlı `TANEX_2610` pending action
4. Provider/model/tool çağrısı sıfır olan `typed_pending_state_projection` ile aynı action
   için 11 sipariş, TANEX 2610, açık onay gereği ve dosya üretilmediği read-back'i

Her iki artifact evidence contract v6, current 26-file runtime/acceptance fingerprint,
exact requested/actual model eşitliği, fallback sıfır ve Phase 8A pending semantic
validator ile problems `[]` vermiştir. Kanıtlar:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3.1-flash-lite-count-list-label-pending-v6-r9-2026-07-27.json`
ve
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-count-list-label-pending-v6-r14-2026-07-27.json`.

Bu iki artifact kendi kaynak fingerprint'inde pending-read ve canlı quota-scope kapısını
kapatmıştır. Bu tarihsel başarı, aşağıda açıklanan typed-observation kaynak değişikliğinden
sonra current-source kapanış kanıtı değildir. İki geniş regresyonun status'u fresh
approval/execute/read-back ile correction/supersession kapıları geçilene kadar `open`
kalır; pending başarısı bu sonraki etkili işlemlerin yerine sayılmaz.

Sonraki approval kampanyası bu kapanışı yeniden açan daha derin bir observation hatası
bulmuştur. OpenRouter R15 dynamic `12` siparişi exact listeleyip TANEX 2610 action'ına
bağlamış, açık onaydan sonra yalnız DOCX üretmiş ve aynı action ID ile 12/12 siparişi
`payload_and_docx_content` üzerinden doğrulamıştır. Fiziksel yazdırma ve pazaryeri
mutasyonu olmamıştır. Gemini R10 ise ilk exact `orders.query` adımında gerçekten 12
`order_numbers` döndüğü halde compact observation prompt'unda yalnız `record_count` ve
aggregate bilgisi gördüğü için “numaralar dönmedi” diye redundant `orders.lookup` adımı
önermiştir. Semantic verifier bu zayıflayan `query=all` adımını effectsiz reddetmiş; koşu
başarılı sayılmamıştır.

Kök düzeltme, typed observation evaluator'a gizli değerleri göndermeden
`record_identity_count`, record shape ve her declared `expected_evidence` için yalnız
`present/value_type/count/source` taşır. Başarılı observation sonrası plan boşsa ve modelin
replan adımları yalnız zaten present olan aynı evidence kümesini yeniden istiyorsa runtime
bu redundant replan'ı deterministic olarak reddeder ve goal'ü complete yapar. Yeni guard
`redundant_replan_for_satisfied_evidence_rejected` provenance'ını saklar; yeni operation
veya farklı evidence gerektiren gerçek replan'ları engellemez. Odaklı regresyon `4 passed`,
geniş Orders runtime/closure seçkisi bu değişiklikle `194 passed + 14 subtests` vermiştir.

Bu kaynak değişikliği 26-file runtime fingerprint'ini değiştirdiğinden R9/R14/R15 artık
current-source kapanış kanıtı sayılmaz. Yeni R11 ve R12 Gemini süreçleri count turunu
geçmiş, exact-list turunun ikinci provider invocation'ında mevcut bounded same-model
retry'ye rağmen HTTP `503` almıştır. Yeni R16 OpenRouter süreci count turunu geçmiş,
exact-list turunda `quota_scope=account`, `model_fallback_allowed=false` ve
`fallback_blocked_reason=provider_quota` kaydetmiştir; sibling model ruleti yapılmamıştır.
Bu üç koşuda business tool/API/DB/dosya/yazıcı etkisi yoktur. Dolayısıyla pending-read
current-source kapısı dış erişim düzelene kadar yeniden `open`; testler ve eski başarılı
artifact'lar onun yerine sayılmaz.

Sonraki fresh Gemini kampanyasında normal count -> exact list -> TANEX 2610 prepare ->
pending read -> explicit approval -> yalnız yerel DOCX execute/read-back zinciri 12/12 exact
kayıtla geçmiştir; fiziksel baskı veya pazaryeri mutasyonu oluşmamıştır. Ardından başlatılan
correction/supersession kampanyası daha yeni ve bağlayıcı bir control-plane kusuru bulmuştur:
model güncel “2736 değil TANEX 2610” düzeltmesinden doğru
`labels.create_from_orders.prepare` operation'ını, exact 12 sipariş kimliğini ve doğru
TANEX/2610 business argümanlarını üretmiştir. Plan validator `operation_domain` alanını
zaten authoritative catalog'dan türetmesine rağmen effectful operation'ı ayrıca legacy
`_goal_has_label_intent` raw-text guard'ından geçirmiş; takip mesajı aktif label proposal'ı
typed state'te taşıdığı halde “etiket” sözcüğünü tekrar etmediği için doğru planı
reddetmiştir. Bounded repair bunun ardından eski 2736 hedefini yeniden önermiştir. Semantic
verifier etkili işlemi güvenle engellemiş, eski action
`superseded` kalmış ve yeni dosya/API/DB/yazıcı etkisi doğmamıştır; ancak kullanıcı hedefi
tamamlanmadığı için koşu başarısızdır. Bu bulgu Bölüm 6.2.1, 17.4 ve karar 32-37'yi bağlayıcı
kılmıştır. Runtime doğru model planını legacy keyword intent kapısıyla yeniden veto etmeyecek
ve follow-up candidate retrieval'ını typed semantic/active-target bağlamıyla zenginleştirecek
şekilde düzeltilmiştir. Birebir stale-objective, keyword tekrarsız TANEX correction ve iki
komşu count-correction regresyonu birlikte geçmiştir; geniş Orders/Chat/Labels seçkisi
`263 passed, 1 skipped`, fingerprint/pending-contract pytest seçkisi `5 passed` vermiştir.
Skip ve deterministic testler live acceptance yerine sayılmaz: aynı correction zinciri
fresh source fingerprint'iyle gerçek cloud source-app üzerinde geçmeden Orders
current-source kabulü kapanamaz. OpenRouter tarafındaki son hesap-kapsamlı `429` da ayrı
provider kapısı olarak `open` kalır ve Gemini başarısıyla örtülemez.

Bu düzeltmeden sonraki fresh Gemini R24 source-app koşusu count `12`, exact list `12`,
aynı set için TANEX 2736 prepare ve keyword tekrarsız TANEX 2610 correction/re-prepare
adımlarını model-authored planlarla, fallback kullanmadan geçmiştir. Eski action terminal
`superseded`, yeni payload doğru `TANEX_2610` ve 12/12 exact kapsam olmasına rağmen iki
proposal aynı `action_id`yi taşımıştır. Codex onaya geçmemiş; koşuyu API/DB/dosya/yazıcı
etkisi olmadan başarısız kapatmıştır. Kök neden `PendingActionSnapshot` kimliğinin
operation + selection + record/count ile sınırlı olup effect-bearing template/model ve
arguments payload'ını kapsamamasıydı. Karar 38 bunun sonucudur. Approval fingerprint tek
session-state primitive'inde bütün effect-bearing canonical alanları kapsayacak biçimde
genelleştirilmiş, semantic verifier aynı DRY fingerprint'e bağlanmış ve active-selection
binding sonrası kimliği yeniden üreten boundary eklenmiştir. Aynı exact selection'da
TANEX 2736 -> 2610 kimlik rotasyonu, eski ID stale rejection, payload tamper fail-closed ve
DOCX execute/read-back komşuları dahil geniş paket `293 passed, 1 skipped`; current
fingerprint/correction/pending semantic pytest seçkisi `7 passed` vermiştir. Skip ve testler
live acceptance değildir: fresh R25 correction/approval/read-back kanıtı alınmadan bu kapı
kapanmış sayılmaz.

Fresh Gemini R25 o source fingerprint üzerindeki replacement-action dilimini geçmiştir: model-authored
count `12` -> exact list `12` -> TANEX 2736 prepare -> keyword tekrarsız TANEX 2610
correction/re-prepare zinciri fallback olmadan geçmiştir. Eski 2736 proposal ID'si
`0a461f4c7c6adef0369cfa633fb955a7`, yeni 2610 proposal ID'si
`2b690dec6d4edbc98264ae27fb642da7` olmuş; eski action terminal `superseded` kalmıştır.
Provider/model/tool çağrısı sıfır olan pending-state read-back yeni ID'yi, TANEX 2610'u,
exact 12 kaydı ve dosya üretilmediğini korumuştur. Yalnız yeni action açıkça onaylanmış;
fiziksel baskı veya pazaryeri mutasyonu olmadan 567447 bayt yerel DOCX üretilmiş ve
`payload_and_docx_content` ile 12/12 sipariş authoritative read-back'te doğrulanmıştır.
Evidence contract v6 final validator `problems=[]`, `accepted=true`, `final_status=passed`
vermiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3.1-flash-lite-correction-supersession-v6-r25-2026-07-27.json`.
Bu kanıt Gemini current-source correction ve yalnız replacement-action approval/execute
dilimini kapatır. Frozen zincirdeki superseded eski action ID'sini kullanıcı tarafından
açıkça gönderip effectsiz stale rejection görme adımı R25'te çalıştırılmamıştır; bu davranış
deterministic testte geçse de live kapı hâlâ açıktır. R25 ayrıca OpenRouter'ın ayrı provider
kapısının, Phase 8B geniş organik regresyonlarının veya sonraki UI fazının yerine geçmez.

Aynı runtime source fingerprint'i `f6c7b2101674bceb86668fafb6a6619e65093dd2104286e257e4cd971bfaf01a`
üzerindeki fresh OpenRouter R20 kontrol turu planning veya business tool aşamasına ulaşmadan
`http_429`, `quota_scope=account`, `model_fallback_allowed=false` ile effectsiz kapanmıştır.
Runtime başka ücretsiz sibling modele sessiz geçmemiş; model cevabı, selection, pending action,
API, DB, dosya, yazıcı veya pazaryeri etkisi üretmemiştir. Bu sonuç OpenRouter'ın agent kalitesi
hakkında başarısızlık kanıtı değil, current iki-provider kabulünü dış kota nedeniyle açık tutan
provider-unavailable kanıtıdır. Kota penceresi açıldığında aynı frozen zincir fresh process ve
fallback-kapalı exact model koşusuyla yeniden başlatılacaktır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-count-list-label-pending-v6-r20-2026-07-27.json`
(`14109` bayt, SHA-256
`281f7b40ffdef220845b92d9892410e1ee397019d560c71609900114e17b70cd`).

R25 sonrası closure revalidation, UI `superseded_actions` projection'ının terminal eski
action'ın `action_id` kimliğini taşımadığını ve kullanıcının metinde eski ID'yi açıkça yazıp
“onayla” demesi halinde Chat katmanının bu referansı aktif replacement'a uygulayabildiğini
göstermiştir. Bu iki davranış güvenlik ve kanıt sözleşmesi kusurudur: kimliksiz supersession
stale rejection'ı sonradan kanıtlayamaz; kullanıcı tarafından adı verilen eski action'ın
yerine sessizce güncel action'ı çalıştırmak ise hedef değiştirmedir. Shared session-state
katmanına explicit action-reference çözümleyicisi eklenmiş, Chat yalnız kullanıcının referans
verdiği ID'yi runtime'a taşımış, runtime'ın mevcut fail-closed stale guard'ı korunmuş ve
superseded projection action ID/fingerprint'i kaybetmeyecek biçimde düzeltilmiştir. Acceptance
contract stale-ID turunu teknik failure değil, `execute.success=false`, `stale_approval=true`,
aktif replacement korunmuş effectsiz bir `stale_action_rejected` control outcome olarak
doğrular. Bu source değişikliği R25/R20'yi tarihsel kanıta çevirmiştir.

Fresh Gemini R26 current fingerprint
`1bea4fc52083e433891d5f368c569eb46af7e94c4ce3dffbf8e2ec3297e887cc` üzerinde frozen yedi
turu eksiksiz geçmiştir: count `12` -> exact list `12` -> TANEX 2736 prepare
(`0a461f4c7c6adef0369cfa633fb955a7`) -> keyword tekrarsız TANEX 2610 replacement
(`2b690dec6d4edbc98264ae27fb642da7`) -> sıfır provider/tool etkili pending read -> eski
2736 ID'sinin açıkça gönderilip effectsiz stale rejection'ı -> yalnız güncel 2610 ID'sinin
approval/yerel DOCX execute/read-back'i. Stale turunda `execute.success=false`, aktif 2610
pending action aynen korunmuş; sonraki turda 567447 bayt DOCX `payload_and_docx_content` ile
12/12 doğrulanmıştır. Fiziksel baskı veya pazaryeri mutasyonu yoktur. Final validator
`accepted=true`, `problems=[]`, `final_status=passed` vermiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3.1-flash-lite-correction-supersession-v6-r26-2026-07-27.json`
(`3030206` bayt, SHA-256
`a290f76e338d4a43a0dee0cc87ceaf298d5e368714946f441e47fe9f5df5733a`).

Aynı R26 source fingerprint'indeki OpenRouter R21 probe yine model/planning aşamasından önce
`http_429`, `quota_scope=account`, `model_fallback_allowed=false` ile effectsiz durmuştur.
Başka modele sessiz geçiş, model cevabı, business tool, API, DB, dosya veya yazıcı etkisi
yoktur. Dolayısıyla Gemini frozen zinciri current olarak kanıtlıdır; OpenRouter provider kapısı
dış kota nedeniyle açık kalır ve Gemini bunun yerine sayılmaz. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-count-list-label-pending-v6-r21-2026-07-27.json`
(`14091` bayt, SHA-256
`d5a5b3ae7108e1b9e7202e2edf6d6718b6ed477dc0c83882802fc536fe7d88d8`).

R26 kapanış incelemesinde ürün zinciri doğru olduğu halde Phase 8A birleşik artifact
doğrulayıcısının pending/execute sözleşmeleri için ilk prepare'ı seçtiği görülmüştür. Bir
correction zincirinde ilk prepare artık superseded olduğundan, doğrulayıcı pending read'den
önceki ve execute'a bağlı en son aktif prepare'ı seçmelidir. Bu seçim ortak verifier'da
düzeltilmiş; correction sözleşmesine pending-read sözleşmesi de dahil edilmiş ve birleşik
artifact'ın üç kapıyı birden yanlış pozitif/negatif üretmeden kanıtlaması testle kilitlenmiştir.
Bu kaynak değişikliği R26/R21'i tarihsel kanıta çevirmiştir.

Fresh Gemini R27, güncel fingerprint
`255628b44d4cc74e4d201d5582347f51439186fbb435f932d2841dae09535622` üzerinde aynı yedi
turlu frozen zinciri tekrar geçmiştir: count `12`, exact list `12`, TANEX 2736 eski action
`0a461f4c7c6adef0369cfa633fb955a7`, keyword tekrarsız TANEX 2610 replacement
`2b690dec6d4edbc98264ae27fb642da7`, provider/tool/effect-free pending read, eski ID'nin
açıkça gönderilmesiyle `stale_action_rejected`, ardından yalnız güncel ID ile yerel DOCX
execute/read-back. Eski tur `execute.success=false` ile effectsiz kalmış, güncel turda
567447 bayt DOCX canonical payload ve içerik üzerinden exact 12/12 doğrulanmıştır. Fiziksel
baskı veya pazaryeri mutasyonu yoktur. Aynı artifact pending-read, approval/execute/read-back
ve correction/supersession semantic contract'larının üçünde de `problems=[]` vermiştir.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-gemini-3.1-flash-lite-correction-supersession-v6-r27-2026-07-27.json`
(`3031835` bayt, SHA-256
`c026516cdd09472358ed3ede77f75f7dd1f29724803064d743971c3e99d5baff`).

Aynı R27 fingerprint'indeki OpenRouter R22 probe model/planning başlamadan
`http_429`, `quota_scope=account`, `model_fallback_allowed=false` ile fail-closed durmuştur.
Model cevabı, sibling fallback, business tool, API, DB, dosya, yazıcı veya pazaryeri etkisi
yoktur. Bu dış erişim teşhisi OpenRouter agent başarısı sayılmaz ve iki-provider kapısını
kapatmaz. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8a-openrouter-nemotron-ultra-count-list-label-pending-v6-r22-2026-07-27.json`
(`14070` bayt, SHA-256
`06e2cc38b27747ce4639539807b252aeef66b3e2821d2a7eb39405c4dcbcdfe0`).

2026-07-27 Faz 8B organik cloud kabul durumu: current-source Gemini 3.1 Flash Lite
R9-R22 incelemeleri, güçlü modelin kötü görünen cevaplarının model zekâsından değil runtime
katmanlarından geldiğini somutlaştırmıştır. Bağlayıcı yeni invariant'lar şunlardır:

- Final cevap yalnız ham model çıktısında değil, PII/policy/clearance temizliği ve citation/
  execute ekleri bittikten sonra da well-formed ve projection-complete olmalıdır. Güvenlik
  temizliği gövdeyi kaldırıp boş Markdown başlığı bırakırsa verified fallback'e dönülür.
- Observation evaluator yalnız top-level scalar aramaz; canonical order satırlarındaki
  `total_price` -> amount ve `order_date` -> date gibi typed alias'ları kanıt sayar. Doğru
  nested row evidence varken gereksiz lookup/replan yapılamaz.
- Yerelleştirilmiş tarih ve sayı sunumu (`27.07.2026`, `2.000`, `299,99`) authoritative
  ISO tarih/tutarla eşdeğer doğrulanır; tarih biçimi hallucination sayılamaz.
- Sıralı immutable seçimde “bu listedeki en son/en yeni/ilk sipariş” exact ilk kayda
  indirgenir; tüm liste `full_context` kapsamına genişletilemez. “Bunların tamamı” ise exact
  seçimin tamamını korumaya devam eder.
- Sipariş kalem/kargo/iade bağlamı, satış raporu satırı veya zorunlu claim-id değildir.
  Typed requested-field taxonomy order item, cargo/tracking ve zero-or-more return context'i
  ayrı taşır. Sıfır iade de kullanıcı açıkça istemişse görünür cevapta “iade kaydı yok” diye
  projection edilmelidir; sessizce atlanamaz.
- Aynı kullanıcı hedefini tamamlayan kardeş read/aggregate operation'ları exact aynı
  account, store ve environment kapsamını taşımalıdır. Bir özet içindeki count Production
  mağazasına bakarken status dağılımının Stage veya bütün hesaplara genişlemesi kritik
  scope-parity ihlalidir; sayılar tek tek doğru görünse bile cevap yayınlanamaz.
- “Önceki sipariş konusuna dönelim/devam edelim” yalnız konu değişimidir; kullanıcı ayrıca
  incele, say, listele, göster, hazırla veya çalıştır gibi bir business predicate vermedikçe
  eski siparişi okumaya, eski selection'ı genişletmeye veya tool çağırmaya yetki vermez.
  Konu hafızası korunur fakat yeni operation için açık amaç beklenir.
- Tool observation'ının doğru olması görünür cevabın doğru olduğu anlamına gelmez. Her turda
  operation/args/scope/observation doğruluğu ile son response projection kalitesi ayrı ayrı
  incelenir. Kullanıcının istediği alan, sıfır sonuç, exact kayıt kümesi veya kapsam görünür
  cevapta kaybolursa tur başarısızdır; “model böyle cevap verdi” gerekçesi kabul edilmez.
- Aggregate metrikler nested örnek satır değerleriyle aynı kanıt havuzuna indirgenemez.
  `estimated_revenue/total_revenue` ile örnek sipariş `total_price` değerleri ayrı semantik
  kimlik taşır; kullanıcı ciro istediğinde herhangi bir grounded sipariş fiyatını ciro diye
  yazmak verifier'dan geçemez. Aynı şekilde durum dağılımı yalnız bir status adıyla veya
  bağımsız sayılarla tamamlanmış sayılmaz; authoritative `status_counts` içindeki her
  status-adet çifti görünür projection'da eksiksiz bulunmalıdır. “Toplam N sipariş” ve
  “tamamı kargoya hazır” gibi ilişkisel iddialar da `total_orders` ile ready count arasında
  semantik olarak doğrulanır.
- Uzun sohbet dönüşü yalnız exact `RecordRef`/selection kimliğini değil, referans verilen son
  typed business turun response projection sözleşmesini de korur. Kullanıcı “sekiz mesaj
  önce detayını açtığımız siparişi tekrar göster” deyip yeni alan belirtmiyorsa önceki
  `requested_fields` aynen miras alınır; model müşteri/adres/tarih/tutar gibi yeni alanlar
  ekleyemez. Kullanıcı bu kez açıkça başka alan isterse yalnız o explicit projection ile
  güvenli biçimde daraltılır/genişletilir. Son business turu yakın sohbet penceresinden düşse
  bile ayrı typed context olarak modele verilir; raw history taraması yapılmaz.
- Güçlü cloud model temel manuel Orders isteğinde anlamsız davranıyorsa önce gerçek trace
  katmanları ayrılır: modele hangi objective/candidate/state verildiği, modelin ham planı,
  normalizasyon, tool observation'ı, verifier ve son projection. Kök neden bu katmanlardan
  birinde kanıtlanmadan prompt değiştirmek, model değiştirmek veya yeni mega-tool eklemek
  yasaktır.
- Agentin zekâsı çok tool sunulmasıyla değil, gerekli küçük canonical operation'ları
  observation sonrası hedefe göre yeniden compose edebilmesiyle ölçülür. Runtime modeli
  ilk tool'a zorlayan workflow olamaz; model de authoritative kimlik/sayı/tarih/tutarı
  serbest metinden icat edemez. Model karar verir, domain operation gerçeği üretir,
  deterministic katman sınırlar ve doğrular.
- Mevcut kampanyada local model kalite testi yapılmaz. Local provider/catalog/UI desteği
  korunur; fakat Orders organik cloud kabulü kapanana kadar local server, local inference
  veya local uzun sohbet çalıştırılmaz ve local sonuç hedefin ilerleme ölçütü sayılmaz.
- Focused unit/regression testleri yalnız bulunan kök nedeni kilitleyen laboratuvar
  kanıtıdır; kullanıcı karşısındaki agent zekâsının veya Orders ürününün hazır olduğunun
  kanıtı değildir. Ana ilerleme ölçütü, gerçek Chat source-app yolunda fresh process ile
  başlayan ve kullanıcı diliyle kesintisiz ilerleyen organik cloud konuşmasıdır.
- Kabul senaryosu test-only step queue, gizli doğru tool enjeksiyonu, önceden hazırlanmış
  business plan veya harness'e özel deterministic cevapla geçirilemez. Kullanıcıya açılan
  aynı interpreter -> planner -> tool -> observation -> verifier -> response zinciri
  çalışmalıdır; acceptance harness yalnız mesajı gönderir, görünür cevabı ve provenance'ı
  okur.
- Görünür cevap güçlü modelin seviyesine rağmen "salak", alakasız, eksik veya önceki
  hedefi unutmuş görünüyorsa geçen test sayısı savunma değildir. İlk kritik turda koşu
  durdurulur; model girdisi, typed state/selection, candidate catalog, ham model kararı,
  normalizasyon, domain observation ve response projection ayrı okunur. Kanıtlanan sahip
  katman düzeltilmeden yeni prompt yaması, başka model veya sonraki faza geçiş yapılmaz.
- Aynı kullanıcı mesajının one-shot/legacy router, task runtime ve acceptance runtime gibi
  birden fazla rakip business yolundan farklı davranması yasaktır. Gerçek Chat tek birleşik
  agent loop'unu kullanır; legacy yollar yalnız açık uyumluluk adaptörü olabilir ve business
  niyetini, seçimi veya sonucu yeniden yorumlayamaz.

Canlı kanıt sonucu: R15'te genel özet exact üç minimal read ile, son beş sipariş tek
`orders.query` ile doğru geçmiştir. R16/R17 focused koşularında “listedeki en son” exact tek
`orders.full_context` kaydına bağlanmış; R17'de görünür sıfır-iade projection eksiği bulunarak
kampanya durdurulmuştur. Bu eksik deterministic completeness kapısıyla kapatılmış ve fresh
R18 focused gerçek cloud tekrarında kalem, kargo/takip ve açık “iade kaydı yok” cevabı aynı
exact kayıtta geçmiştir. Sonraki organik koşuda bir özet içindeki `orders.status_counts`
operation'ının account kapsamını kaybettiği görülmüş; bütün periyodik Orders/Returns kardeş
read'leri typed `api_account_ids` kapsamına alınmış ve fresh R21 focused cloud tekrarında
MDB/TRENDYOL/Production scope parity doğrulanmıştır. R22 uzun-sohbet provasında yalnız
“önceki sipariş işine dönelim” mesajının gereksiz `orders.full_context` çağırdığı bulunmuş;
topic-resume boundary yukarıdaki sözleşmeyle kilitlenmiştir.

2026-07-28 tekrarında R24 organik kampanyası görünür özetin örnek sipariş fiyatı `299,99`u
ciro, hazır adet `12`yi toplam sipariş ve tek ReadyToShip statüsünü bütün dağılım gibi
sunabildiğini; verifier'ın bunu yanlışlıkla `verified_model_repair` olarak kabul ettiğini
göstermiş ve turda kampanya durdurulmuştur. Aggregate metric identity, complete
status-count projection ve ilişkisel total/ready doğrulaması eklendikten sonra fresh R25
focused exact-model cloud tekrarında görünür cevap Production scope, 12 hazır, yedi
status-adet çifti, `502518.01` ciro ve 11 risk ile geçmiştir.

R27 organik kampanyası topic-resume sınırını ve sekiz toolsuz mesajı doğru geçirmiş; fakat
uzun-context return exact aynı siparişi bulsa da önceki cargo/returns projection'ını kaybedip
model-authored müşteri/adres placeholder alanları eklediği için on beşinci turda
durdurulmuştur. Son typed business turu ve projection contract yakın sohbet penceresinden
bağımsız hâle getirilmiş; repeat-read inheritance ve unrequested labelled-field privacy
kapısı eklenmiştir. Fresh R28 focused 11 turlu exact-model cloud tekrarında exact son-beş
liste -> exact tek full-context -> sekiz toolsuz ara mesaj -> aynı exact full-context zinciri
geçmiş; ikinci context cevabı da ilk cevapla aynı item, cargo/tracking ve açık zero-return
projection'ını taşımıştır. Her iki focused artifact generic acceptance'ta `problems=[]`
vermiştir.

R29 fresh organik cloud kampanyası ilk 17 turda selamlaşma, doğal sohbet, capability
kataloğu, kapsam-parity'li genel özet, exact son-beş/detail, sekiz toolsuz ara mesaj,
projection-preserving uzun bağlam dönüşü ve exact 12 hazır sipariş count/list zincirini
geçmiştir. 18. turda model exact 12 kayıtla doğru
`orders.shipping_deadline_analysis` planını ve argümanlarını üretmiş; fakat semantic
verifier typed `metric=count + status_scope=ready_to_ship` sözleşmesini yalnız
`orders.ready_to_ship_count` ile eşleyip istenen `risk` projection'ını yok saydığı için
doğru planı `typed_read_contract_operation_mismatch` ile reddetmiştir. Bu model hatası
değil, control-plane false negative'idir ve kampanya kritik sapmada `failed` kapatılmıştır.
Risk isteyen count-shaped typed read sözleşmesi canonical risk operation ailesiyle
doğrulanacak biçimde düzeltilmiş; `shipping_deadline_analysis.overdue_count` response
verifier'da operation-aware risk kanıtına bağlanmıştır. Fresh R30 focused gerçek cloud
tekrarında count `12` -> exact list `12` -> aynı exact sette deadline risk analizi zinciri
geçmiş; görünür cevap MDB/TRENDYOL/production kapsamında 12 kaydın 9'unun son tarihinin
geçtiğini söylemiş ve validator `accepted=true`, `problems=[]` vermiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r30-focused-risk-projection-2026-07-28.json`.

R31 fresh organik cloud tekrarında ilk 18 tur ve yukarıdaki risk düzeltmesi birlikte
geçmiş; 19. turdaki cargo-options read'inde model genel `logistics.provider_catalog`
çalıştırmış, “12 sipariş” ifadesini “12 Haziran” diye yeniden yazmış ve 11 firma adını
listelemeden yalnız adedi söylemiştir. Response verifier'ın kaba `cargo` alanı bu eksik ve
uydurma projection'ı kabul ettiği için kampanya durdurulmuştur. Kargo seçenekleri
`cargo_options` adlı ayrı typed projection'a ayrılmış; aktif Orders selection'ında domain
Orders olarak korunmuş; yalnız `orders.cargo_provider_options` semantic contract'a uygun
sayılmış; provider adlarının tamamı ve kaynaksız takvim iddiaları response verifier'a
bağlanmıştır.

R32 focused tekrarında model iki kez doğru `orders.cargo_provider_options` planını üretmiş,
fakat legacy cargo-change normalizer “henüz hazırlama veya işlem yapma” cümlesindeki `yap`
kelimesini mutation niyeti sayıp doğru read step'ini düşürmüştür. Ortak negatif/read-only
cargo intent sınırı düzeltilmiş; model-authored read planının compiler tarafından
`orders.cargo.change.prepare` ile değiştirilemeyeceği kilitlenmiştir. R33'te doğru read ve
eksiksiz projection çalışmış fakat active Trendyol selection'ın marketplace scope'u
`platform_code` argümanına bağlanmadığı için 11 uygun marketplace firması yerine bütün
platformlardan 19 kayıt listelenmiştir. Execution-boundary scope binding, immutable
selection'daki tek marketplace'i canonical `platform_code` olarak bağlayacak biçimde
düzeltilmiştir. Fresh R34 focused gerçek cloud tekrarında `platform_code=TRENDYOL`, tek
`orders.cargo_provider_options`, 11/11 firma adı-kodu, sıfır approval/action ve validator
`accepted=true`, `problems=[]` ile geçmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r34-focused-cargo-options-projection-2026-07-28.json`.

R35 fresh tam organik cloud tekrarında ilk yedi tur; doğal sohbet, capability özeti,
authoritative genel Orders özeti, exact son-beş liste ve exact full-context projection ile
geçmiştir. Sekizinci toolsuz sohbet turunda Gemini structured interpretation cevabını
vermiş, fakat aynı exact modelin final text invocation'ı HTTP başarısına rağmen boş içerik
döndürmüştür. Provider istemcisi transient `503` için bounded same-model retry uygularken
`empty_response` için aynı sözleşmeyi uygulamadığından tur effectsiz `failed` kapanmıştır.
Ayrıca source-app artifact sürücüsü başarısız `Result` içinde `answer` bulunmadığında güncel
hata mesajından önce chat history'deki son assistant satırını okuyup önceki cevabı stale
`answer` olarak kaydetmiştir. Kampanya sekizinci turda durdurulmuştur. Exact-model Gemini
istemcisi boş response'u aynı prompt hash'i ve aynı invocation contract ile yalnız bir kez
bounded retry edecek; fallback kapalıyken model kimliği değişmeyecek; iki boş cevapta yine
fail-closed duracaktır. Evidence capture da başarısız turda önce güncel `Result.message`ı
kullanacak ve geçmiş assistant cevabını yeni tur cevabı diye yazamayacaktır. Bu iki invariant
provider/evidence katmanında kilitlenmiş; ilgili regresyonlar `12 passed, 2 skipped` vermiştir.
R35 başarısız artifact'ı:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-gemini-3.1-flash-lite-organic-capability-v6-r35-2026-07-28.json`.

R36/R37 koşuları ürün kararı üretmeden dış controller stdin'inin Windows codepage ile
UTF-8 CLI arasındaki encoding uyuşmazlığında kapanmış ve acceptance kanıtı sayılmamıştır.
Controller JSONL satırlarını artık `BaseStream` üzerine açık UTF-8 byte olarak yazmaktadır.
R38 fresh organik koşusu ilk 12 turu geçmiş; 13. toolsuz meta-sohbet turunda exact Gemini
final text contract'ı aynı modelde bounded retry sonrasında da iki boş cevapla kapanmıştır.
Sistem başka modele veya deterministic sahte sohbet cevabına kaçmamış, güncel
`Sohbet modeli bos cevap dondurdu.` hatasını source-app ve artifact'ta doğru taşımış ve
kampanyayı effectsiz `failed` kapatmıştır. Bu dış exact-model failure ürün başarısı değildir;
aynı zamanda fallback-kapalı kabulün fail-closed çalıştığının kanıtıdır. Same-model retry
event'leri ve aynı prompt hash'li attempt ledger'ı source-app artifact runtime kanıtına açıkça
eklenmiştir.

R39 fresh organik cloud koşusu doğal sohbet, capability, genel özet, exact son-beş/detail,
sekiz toolsuz ara mesaj, uzun bağlam dönüşü, 12 hazır sipariş count/list, 9 deadline riski ve
Trendyol'a ait 11/11 kargo seçeneğini ilk 19 turda birlikte geçmiştir. 20. turda model iki
kez exact 12 sipariş kimliği ve `ARASMP` ile doğru
`orders.change_cargo_provider_bulk.prepare` operation'ını üretmiştir. Legacy cargo
normalizer yalnız `tüm/hepsi` gibi raw token'lara baktığı için “12 kaydın tamamında”
ifadesini tekil sanmış, doğru bulk operation'ı `orders.cargo.change.prepare` sibling'iyle
değiştirmeye çalışmış ve planı `deterministic_business_plan_rewrite_required` ile
reddetmiştir. Bu model hatası değil, Bölüm 17.4'te yasaklanan legacy business veto'sudur.
Schema-valid model planındaki tek canonical single/bulk seçimi artık korunur; raw keyword
yardımcısı yalnız aday retrieval veya model planı olmayan legacy yol için kullanılabilir.
Target cardinality argument binding ve semantic verifier tarafından denetlenir. Fresh R40
focused source-app tekrarında count 12 -> exact list 12 -> tek
`orders.change_cargo_provider_bulk.prepare` -> exact 12/`ARASMP` pending approval ->
effect-free cancel zinciri geçmiştir; API, DB, dosya veya pazaryeri etkisi oluşmamış ve
validator `accepted=true`, `problems=[]` vermiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r40-focused-cargo-prepare-cancel-2026-07-28.json`.

R41 fresh organik tekrarında ilk 10 tur geçtikten sonra exact Gemini model-kapsamlı
`http_429` ve yaklaşık 40 saniye `retry_after` üretmiştir. Runtime başka modele geçmemiş,
business tool veya etki çalıştırmamış ve koşu provider-unavailable olarak kapatılmıştır.
Bu sonuç ürün semantik başarısızlığı değildir; yeni fresh kampanyada önceki turların
taşınmasına da izin vermez. Sonrasında geniş task-runtime seçkisi çalıştırılmış; bulunan
iki sapmadan item-sales isteğindeki `count/amount` alanlarının korunmasının doğru yeni
typed contract olduğu doğrulanmış, Stock scalar fallback'inin sonucu “sipariş” diye
etiketlemesi ise gerçek cross-domain projection kusuru olarak düzeltilmiştir. Scalar
fallback önce domain operation'ın authoritative answer'ını kullanır; yoksa owner-domain
noun'u ile projection üretir. Geniş sonuç `204 passed, 218 skipped, 14 subtests passed`tir;
skip'ler canlı cloud acceptance yerine sayılmaz.

R42 fresh exact-model tekrarı bekleme penceresinden sonra ayrı process olarak başlatılmış;
structured interpretation cevap vermesine rağmen ilk turun final-text invocation'ı yine
`http_429`, `quota_scope=model`, yaklaşık 48 saniye retry-after ile kapanmıştır. Exact-model
fallback kapalı tutulmuş; business tool, selection, pending action veya etki oluşmamıştır.
Bu tur başarı ya da semantik ürün regresyonu sayılmaz. Sonraki quality-route modeli aynı
provider içinde ancak ayrıca pinlenmiş, ilk mesajdan başlayan fresh kampanyada sınanacaktır;
R42'nin hiçbir turu yeni kampanyaya başarı olarak taşınamaz.

R43/R44 fresh exact `gemini-3.5-flash` süreçleri ilk turda bounded same-model retry sonrasında
`http_503` ile effectsiz kapanmış; model cevabı, tool veya business effect oluşmadığından kabul
kanıtı sayılmamıştır. R45 exact `gemini-3-flash-preview` koşusunda ilk üç sohbet turu geçmiş,
genel Orders özetinde ise final projection authoritative `total_orders=3112` metriğini
atlamıştır. Projection verifier zorunlu toplam/hazır metriklerini ayrı doğrulayacak, decimal
tutar parçalarını record ID sanmayacak ve doğrulanamayan fallback'e verified-source etiketi
vermeyecek biçimde sıkılaştırılmıştır. R46 tekrarında toplam ve hazır metrikleri görünmüş;
ancak typed `RecordRef.account=1` internal kimliği mağaza adı diye sızmıştır. Store evidence
path-aware yapılarak internal account ref'i dışlanmış, canonical `order.account=MDB` display
değeri korunmuştur. R46 sırasında source değiştiği için bu süreç acceptance sayılmamıştır.

R47 exact `gemini-2.5-pro` ilk invocation'da model-scope `http_429` ile effectsiz kapanmış ve
başka model aynı sürece alınmamıştır. R48 fresh exact `gemini-2.5-flash` koşusunda doğal
sohbet, capability ve eksiksiz genel Orders özeti geçmiştir. “Son 5 siparişi sipariş numarası,
durum, müşteri, tarih, tutar, kargo ve takip bilgisiyle eksiksiz göster” turunda model iki kez
doğru `orders.query(limit=5, sort=order_date_desc)` planını üretmesine rağmen legacy compiler
`numarası` içindeki `aras` substring'ini Aras Kargo sinyali saymış, doğru read planını cargo
mutation'a çevirmeye çalışıp reddetmiştir. Mutation authorization açık subject + gerçek change
verb + typed mode şartına bağlanmış; provider adı veya kelime içi substring tek başına mutation
niyeti olamayacak biçimde genellenmiştir. Geniş task-runtime sonucu bu düzeltmeyle
`207 passed, 221 skipped, 14 subtests passed`tir; skip'ler canlı cloud kabulünün yerine geçmez.

R49 focused exact `gemini-2.5-flash` tekrarında aynı eksiksiz son-beş read isteği bu kez
yanlışlıkla “hangi zaman aralığı?” clarification'ına çevrilmiş; tool ve effect oluşmadan koşu
başarısız kapanmıştır. `son 5` recency + limit sözleşmesidir, `today` filtresi değildir ve açık
alan listesi bulunan bu istek ek kullanıcı kararı gerektirmez. Bu interpreter/read-contract
kusuru bağlayıcı açık regresyondur; kök katmanda kapatılıp focused source-app ile geçmeden ve
ardından fresh tam organik kampanya ilk turdan yeniden başlamadan Faz 8B ilerlemiş sayılamaz.

R50/R51 exact `gemini-2.5-flash` ve R53 exact `gemini-2.5-flash-lite` süreçleri model-scope
`http_429` veya bounded retry sonrası `http_503` nedeniyle model/tool/effect üretmeden
kapanmıştır; semantik kabul veya regresyon kanıtı değildir. R52 `gemini-2.5-flash-lite`
diagnostic koşusunda model doğru son-beş read planını ve exact beş kaydı üretmiş, fakat görünür
fallback kargo/takip/müşteri alanlarını eksik bırakmıştır. Source koşu sırasında değiştiği için
artifact kabul sayılmamış; row projection ailesi istenen alanları ve authoritative boş değerleri
satır bazında koruyacak biçimde düzeltilmiştir. R54 exact `gemma-4-31b-it` süreci source-app
driver timeout'u nedeniyle tamamlanmış bir turn üretemeden açık artifact bırakmıştır. Bu durum
Karar 50 kapsamındaki acceptance-driver kusurudur; timeout açık başarısız turn ve kapalı artifact
olarak kaydedilmeden bu sürücü uzun kampanya için güvenilir kabul edilemez.

R55 fresh exact OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` koşusunda model doğru
`orders.query(limit=5, sort=order_date_desc, mode=list, period=all)` planını üretmiş; ancak
istenen response `projection` metadata'sı tool'un business argümanı sanılarak plan reddedilmiştir.
Karar 47'deki sınırlı read canonicalization uygulanmıştır. R56 tekrarında exact beş kayıt
gelmiş; `customer/customer_name`, `cargo_provider/cargo` ve
`cargo_tracking_number/tracking_number` lehçe farkı observation'ı eksik göstererek gereksiz
`orders.full_context` replanning'ine yol açmış, ayrıca satır tutarları yerine ilgisiz aggregate
tutar verifier'a taşınmıştır. Karar 48-49 kapsamındaki ortak evidence alias ve row projection
doğrulaması bu kök nedenleri kapatmıştır; source değişikliği nedeniyle R56 kabul sayılmamıştır.

R57 aynı exact OpenRouter ücretsiz modelle ve güncel source fingerprint ile focused source-app
tekrarında geçmiştir: model tam bir plan üretmiş, yalnız bir `orders.query` çalışmış, exact beş
kayıt dönmüş ve sipariş numarası, durum, müşteri, tarih, tutar, kargo ile takip alanlarının
tamamı görünür verified projection'da yer almıştır. Artifact validator `accepted=true` ve
`problems=[]` vermiştir. Bu yalnız R49/R52/R55/R56 kök nedenlerinin dar focused kapanışıdır;
Karar 40, 46 ve 51 gereği Faz 8B'yi veya Orders'ı kapatmaz. Sıradaki semantik kabul adımı,
timeout sürücüsü düzeltildikten sonra selamlaşmadan başlayan fresh 22+ turlu organik OpenRouter
kampanyasıdır; Gemini provider kabulü de erişilebilir olduğunda ayrıca fresh tamamlanmalıdır.

Acceptance sürücüsünün R54'te açık bıraktığı timeout kusuru Karar 50'ye göre kapatılmıştır.
Deadline aşımında önceki assistant cevabı yeniden kullanılmadan reason-coded
`source_ui_timeout` turn'ü yazılır; artifact `failed/restart_required` kapanır ve model/tool/effect
durumu kanıt yoksa `unknown_due_to_timeout` kalır. İlgili live-evidence paketi
`48 passed / 64 conditional skipped`, o source'taki geniş task-runtime paketi
`212 passed / 226 conditional skipped` vermiştir.

R58 fresh 22+ organik OpenRouter kampanyası ilk üç toolsuz/capability turunu geçtikten sonra iki
ayrı kritik projection kusuru göstermiş ve beşinci turda durdurularak `failed` kapanmıştır. Dördüncü
turda kullanıcı genel toplam ve hazır sayıyı açıkça istemesine rağmen `sayıyı/toplam sipariş`
çekimi typed `count` alanına alınmamış; authoritative `orders.count=3112` varken filtreli
`orders.query total_count=3002` görünür cevapta “Toplam 3.002 sipariş” diye sunulmuş ve verifier
bunu reddetmemiştir. Beşinci turda model önceki authoritative recent selection'daki exact beş
kayıtla `orders.full_context` seçmiş; tool sonucunda müşteri ve tarih bulunduğu hâlde cevap iki
alanı düşürüp “kaynakta yok” demiştir. Full-context varlığı row verifier'ı kapattığı için yanlış
cevap verified-model etiketi almıştır. Her iki sonuç de model zekâsı değil, Karar 52-53'te
tanımlanan interpretation/evidence/projection control-plane kusurudur.

`contexts[].order` ortak row projection'a alınmış, full-context operation'ı satır doğrulamasını
artık kapatamaz ve deterministic fallback açıkça istenen boş alanları `belirtilmemiş` olarak
korur. R59 iki turlu fresh focused OpenRouter koşusunda genel özetten sonra aynı exact son-beş
isteği her kayıtta numara, durum, müşteri, tarih, tutar, kargo ve takip alanlarıyla geçmiş;
validator `accepted=true`, `problems=[]` vermiştir. Ardından çekimli count intent'i typed `count`
projection'a bağlanmış; genel toplam ile filtreli liste total'inin karışmasını response verifier'ın
mevcut aggregate invariant'ı artık reddeder. Geniş task-runtime sonucu bu source'ta
`214 passed / 228 conditional skipped`tir. R60 current-source focused tekrarında provider
`empty_response` üretmiş; model/tool/effect olmadığı için semantik başarı ya da regresyon sayılmamış
ve koşu failed kapatılmıştır. Karar 40 ve 46 gereği bu focused sonuçlar organik kampanya yerine
geçmez; sıradaki kampanya yeni source fingerprint ile selamlaşmadan yeniden başlar.

R61 fresh organik OpenRouter kampanyasının ilk selamlaşma turu geçmiştir. İkinci toolsuz görüş
turunda interpretation invocation'ı model cevabı almış, final text invocation'ı ise
`empty_response` kalmıştır. Runtime bunu accepted saymamış ve business tool/effect üretmemiştir;
ancak görünür cevap provider provenance'ı yerine generic “Uygulama hatasi olustu” demiştir.
Kampanya ikinci turda durdurulup failed kapatılmıştır. Karar 54 uygulanarak partial provider
failure ortak provider projection'ına bağlanmış; `any response` ile `final response` ayrımı,
`provider_unavailable=true`, accepted=false ve güvenli görünür açıklama tek sözleşmede korunmuştur.
Chat source orchestration paketi `76 passed`tir. Provider hatası semantik model/runtime regresyonu
sayılmasa da kullanıcıya görünen generic hata ürün kalite kusurudur; fresh kampanya current source
ile ilk turdan yeniden başlamalıdır.

R62 fresh organik OpenRouter koşusunda ilk iki doğal sohbet turu geçmiştir. Üçüncü turdaki
“sipariş tarafında bana gerçekten nelerde yardım edebilirsin” isteği model tarafından toolsuz
conversation/explain yolunda bırakılmış; canonical capability catalog çağrılmadan “bu sohbet
kanıtında ne yapabileceğime dair veri yok” cevabı verilmiştir. Bu açık capability sorusuna yanlış
ürün cevabıdır; kampanya üçüncü turda durdurulup failed kapatılmıştır. Karar 55 ile Türkçe
yardım/destek capability soru ailesi typed intent guard'a alınmış, catalog-grounded cevap yolu
korunmuş ve source-app evidence'a `turn_interpretation` projection'ı eklenmiştir. Geniş
task-runtime paketi `215 passed / 229 conditional skipped`, live-evidence paketi
`48 passed / 64 conditional skipped`tir. Fresh organik kampanya current source ile yeniden ilk
turdan başlamadan bu focused/deterministic sonuçlar Faz 8B ilerlemesi sayılmaz.

R63 current-source OpenRouter focused capability tekrarı `http_429`, `quota_scope=account` ile
model/tool/effect üretmeden kapanmıştır. Görünür provider-unavailable açıklaması Karar 54'e uygun,
secret-safe ve generic uygulama hatasından arındırılmıştır; ancak gerçek model cevabı olmadığı için
semantic kabul değildir. Account-scope kota nedeniyle aynı provider'da kardeş modele geçilmemiştir.
R64 fresh exact `gemini-2.5-flash` source-app tekrarında aynı Türkçe yardım capability cümlesi
typed `capability_overview/explain` olarak çözülmüş, yalnız `operations.capability_catalog`
çalışmış ve grounded Orders yetenekleri ile approval/read-back sınırı görünür cevapta doğru
verilmiştir. Validator `accepted=true`, `problems=[]` vermiştir. Bu yalnız Karar 55'in focused
kanıtıdır; Gemini full organik kampanyası ve ayrı OpenRouter full organik kampanyası birbirinin
yerine geçmez.

R65 fresh exact `gemini-2.5-flash` organik kampanyası ilk turda model-scope `http_429`
almış; model cevabı, tool veya effect üretmeden failed kapanmıştır. Karar 42 gereği aynı
exact-model süreci fallback ile sürdürülmemiştir. Bu sonuç semantic başarı ya da runtime
regresyonu değildir; quality route'taki sonraki capability-compatible ücretsiz model ancak
fresh process ve ilk turdan başlayan ayrı kampanyada denenebilir.

R66 fresh `gemini-2.5-flash-lite` organik kampanyasında ilk iki doğal sohbet ve üçüncü
catalog-grounded capability turu geçmiştir. Dördüncü turda kullanıcı mağaza/ortamla birlikte
genel toplam sipariş sayısını ve kargoya hazır sayıyı açıkça istemiştir. Model-authored zincir
`orders.count`, `orders.ready_to_ship_count` ve `orders.query` çalıştırmış; authoritative
observation içinde bütün sipariş toplamı `3112`, hazır adet `12` ve filtreli query total'i
`3002` bulunmuştur. Buna rağmen generic scalar seçimi görünür deterministic projection'da
yalnız “Kargoya hazır 12”yi yayımlamış, genel toplam `3112`yi düşürmüş ve limitli query
satırlarından görülen iki statüyü genel durum özeti gibi göstermiştir. Final provider invocation
`http_429` olmasına rağmen artifact hatalı biçimde `accepted=true`,
`projection_verified=true`, `problems=[]` yazmıştır. Koşu dördüncü turda durdurulmuş ve bütün
kampanya failed kabul edilmiştir. Bu güçlü modelin zekâ hatası değil; Karar 56–59'da kapatılması
zorunlu kılınan operation-aware metrik kimliği, çoklu requested-field coverage, global status
aggregate ve verifier doğruluk kusurudur. R66 düzeltmesi focused ve geniş deterministic
regresyonlardan, ardından fresh source-app focused cloud tekrarından geçmeden; sonrasında da
selamlaşmadan başlayan yeni 22+ organik kampanya ilk turdan yürütülmeden Faz 8B ilerlemiş
sayılmaz.

2026-07-29 OpenRouter kota auditinde R22/R63 artifact'larının yalnız
`nvidia/nemotron-3-ultra-550b-a55b:free` çağrısı yaptığı doğrulanmıştır. Kayıtlı API
anahtarının secret-safe, read-only `/api/v1/key` cevabı `limit=1`,
`usage=0.188776237`, `limit_remaining=0.811223763` döndürmüştür. Dolayısıyla önceki
“provider hesabının genel kotası doldu” projection'ı ücretli model erişimi açısından
tek başına kanıtlanmış değildir; bu ilk audit yalnız OpenRouter free-model havuzu kotasının
dolduğunu ve API key harcama tavanında yer kaldığını göstermiştir. Karar 60
uygulanarak `free_tier` scope'u, `free_tier_quota` blocked reason'ı ve paid bakiye
hakkında free 429'dan hüküm vermeyen güvenli kullanıcı cevabı eklenmiştir. Provider adapter paketi
`33 passed`, geniş Orders task-runtime paketi `216 passed / 230 conditional skipped`
vermiştir. Sonraki ayrı `/api/v1/credits` audit'i `total_credits=0`,
`total_usage=0.199355437` döndürmüş ve fresh DeepSeek V4 Pro çağrısı model cevabından önce
`HTTP 402`, `quota_scope=billing` ile effectsiz kapanmıştır. Böylece `$0.811224` değerin
satın alınmış bakiye değil yalnız key harcama tavanında kalan pay olduğu kesinleşmiştir.
Paid model kabulü yeni kredi eklenmeden açılamaz; ücretsiz OpenRouter kabulü free havuzu
yeniden erişilebilir olduğunda ayrıca yapılır.

2026-07-29 R66 deterministic kök neden kapanışında Orders domainine canonical metric
registry eklenmiştir. Birebir gerçek kullanıcı cümlesi artık
`orders.total_count`, `orders.ready_to_ship_count` ve `orders.status_distribution`
requirement'larını aynı typed semantic contract içinde ayrı taşımaktadır. İlk model planı
`orders.count + orders.ready_to_ship_count + orders.query` kurarsa global status aggregate
eksikliği execution'dan önce reason-coded reddedilmekte ve bounded repair
`orders.status_counts + orders.ready_to_ship_count` composition'ına gidebilmektedir.
Response verifier `orders.count.count=3112`, hazır operation `count=12` ve filtreli
`orders.query.total_count/status_counts` değerlerini birbirine karıştırmamakta; sample
statüleri globalleştirmemekte ve eksik total/status projection'ını accepted saymamaktadır.
Focused R66 seçkisi `6 passed / 6 conditional skipped`, geniş Orders task-runtime paketi
`220 passed / 234 conditional skipped / 17 subtests passed` vermiştir. Bu yalnız
deterministic sözleşme kapanışıdır; R66 fresh Gemini source-app focused tekrarı ve ardından
OpenRouter paid kontrolü yapılmadan canlı kabul değildir.

R67/R68 exact `gemini-2.5-flash-lite` focused tekrarları model-scope `429` ile business
tool/effect üretmeden failed kapanmıştır. Fresh R69 `gemini-3.1-flash-lite` tekrarında
typed contract üç requirement'ı korumuş; ilk eksik plan bounded repair ile
`orders.count + orders.ready_to_ship_count + orders.status_counts + orders.query`
composition'ına dönüşmüştür. Authoritative sonuç ve görünür cevap toplam `3112`, hazır `4`,
`MDB / TRENDYOL / production` kapsamı ve toplamı `3112` olan yedi status bucket'ında birebir
uyuşmuş; response verifier `allowed=true`, reason listesi boş ve
`final_source=deterministic_verified_projection` olmuştur. Final provider synthesis
model-scope `429` aldığı için `accepted_semantic_output=false` kalmış; bu R66'nın gerçek
source-app doğruluk kapanışıdır fakat full Gemini provider kabulü değildir. Ayrıca
mağaza/ortam kanıtı önceki aggregate sonuçlarında bulunduğu hâlde dördüncü
`orders.query` read'i çalışmıştır; bu doğruluğu bozmasa da gereksiz operation kalite
borcudur ve organik kabulde açık kalır. R70 fresh
OpenRouter `deepseek/deepseek-v4-pro` paid kontrolü ise ilk interpretation çağrısında
`HTTP 402/billing` almış; model, tool veya effect üretmemiştir. `/key` ve `/credits`
ayrımı yukarıdaki sıfır-kredi sonucuyla doğrulanmıştır.

R69 trace'indeki gereksiz dördüncü `orders.query` ve yaklaşık `984 KB` artifact şişmesi
Karar 62 ile kökten ele alınmıştır. Orders-owned `summarize_orders` artık bütün siparişler
için `scope_rows/account_by_order` döndürmemekte; distinct account id, source revision/hash
ve aggregate sonuç üretmektedir. Gerçek Production `3112` sipariş snapshot'ında
`orders.count` structured payload'ı `536 byte`, `orders.status_counts` payload'ı `712 byte`
ölçülmüş; mağaza/ortam ve freshness kanıtı korunurken hiçbir order identity map taşınmamıştır.
Planner katalog prompt'u canonical result fields'i taşımakta; metric requirement'a katkısı
olmayan ve mevcut `account_scopes` kanıtını tekrarlayan `orders.query` planı execution
öncesi reason-coded repair'e gitmektedir. Orders AI + domain geniş paketi
`304 passed / 236 conditional skipped / 17 subtests passed` vermiştir. Yeni source
fingerprint'le R71/R72 exact Gemini tekrarları ilk interpretation çağrısında model-scope
`429` aldığı için model/tool/effect üretmeden failed kapanmıştır; deterministic minimal-plan
düzeltmesi canlı provider kabulü sayılmamıştır.

2026-07-29 Karar 63 ile bilgi kaynağı, web ownership ve eski approval bağlamı tek typed
sözleşmede ayrılmıştır. Turn interpretation artık `information_source` alanında
`local_business_data`, `external_public_web` veya `mixed_local_and_public` taşır ve `web`
gerçek Chat source-app ürün yolunda kayıtlı bir task domainidir. “Hepsiburada kargo
fiyatlarını internette bul” listing veya yerel Logistics verisine sıkıştırılamaz; public web
operation'ına gider. “Kayıtlı kargo tarifelerimi göster” Logistics-owned local business
read olarak kalır. Son sipariş içeriğini internette araştır gibi karma hedeflerde yalnız
public ürün kimliği web sorgusuna taşınabilir; sipariş, müşteri, adres, hesap veya diğer özel
işletme verisi ağ çağrısından önce privacy sanitizer tarafından fail-closed durdurulur ve
kullanıcıya hiçbir web sorgusu gönderilmediği açıkça söylenir.

Aynı karar, conversation proximity'nin business authority olmadığı ilkesini de kilitler.
İptal edilmiş, tamamlanmış veya superseded eski approval kartı raw history içinde yakın
görünse bile yeni ve açık “Stage'deki hazır siparişleri listele” gibi authoritative read
hedefini ele geçiremez. Pending kart kapsamı yalnız kullanıcı kartı/aksiyonu açıkça
referans verirse okunur; araya giren cancellation terminal sınırdır. Public/local web
routing, private-web network öncesi blok, gerçek Chat'in typed `web` dispatch'i ve
Orders->web->XLSX / web->XLSX approval-read-back zincirleri focused testlerde geçmiştir.
Ardından bütün Orders agentic task-runtime paketi `226 passed / 240 conditional skipped /
17 subtests passed`, bütün Orders behavioral E2E paketi ise fresh düzeltmeyle
`304 passed / 306 conditional skipped` vermiştir. Bu sonuçlar deterministic ürün
sözleşmesini güçlendirir; fresh 22+ turlu cloud kabulünün, provider erişiminin veya Faz 8B
kapanışının yerine geçmez.

Faz 8B yine de kapanmış değildir. Bu dar focused kanıtların tamamı fresh 22+ turlu organik
cloud ürün-yolu kampanyasında birlikte, her cevap Codex tarafından okunarak geçmelidir.
Kampanya tool-free sohbet aralarını, uzun bağlam dönüşünü, exact count/list/full-context,
kargo seçenek/prepare/cancel, rapor, Excel prepare/pending/execute/read-back, public web
araştırması, private-web privacy sınırı, cancellation ve return akışlarını kapsar. Tek kritik
sapma kampanyayı durdurur; kök katman düzeltilip fresh koşu baştan alınır. Local kabulü bu
aşamada ertelenmiştir; UI responsive/offscreen kabulüne Faz 8B kapanmadan geçilmez.

2026-07-29 Karar 64 ile bir web kaynağının açılabilmesi ile kullanıcı hedefini kanıtlaması
kesin olarak ayrılmıştır. R75 gerçek `gemini-3.5-flash` source-app turu doğru
`web.search -> web.open` composition'ını kurmuş fakat Hepsiburada kargo fiyatı hedefi için
Hepsiburada ana sayfasını açıp ilgisiz metni özetlemeye çalışmıştır. Bundan sonra
`web.open` başarısı tek başına goal evidence değildir. Topic coverage, fiyat/tutar
isteniyorsa para birimi ve miktar kanıtı, ayrıca ölçüm konusu ile değer yakınlığı
deterministic olarak doğrulanır. Yetersiz açılmış kaynak step'i başarısız yapar; runtime
sonraki açılmamış adaya observation-driven replan eder. Bütün adaylar yetersizse sistem
kaynak veya uydurma cevap yayımlamaz, açılan kaynakların hedefi doğrulamadığını dürüstçe
söyler. Yetersiz kaynaklar citation ve artifact evidence havuzuna giremez.
`deterministic_verified_uncertainty` yalnız gerçek final model cevabı alındığında kabul
edilebilir ve provenance'da kendi adıyla görünür. Fresh R77 aynı gerçek hedefte exact
Gemini 3.5 Flash, fallback kapalı source-app yolunda doğrulanmış belirsizlikle
`final_status=passed`, `accepted=true` vermiştir. Web focused paketi, cross-domain
latest-order -> public web -> XLSX regresyonu ve Chat kabulü bu sözleşmeyle geçmiştir.

2026-07-29 Karar 65, fresh organik cloud kampanyalarında iki yeni dış engel ve bir gerçek
ürün hatasını kaydeder. R78 `gemini-3.5-flash` ilk iki doğal sohbet turunu toolsuz ve exact
modelle geçtikten sonra üçüncü turda model-scope `429` almış; R79 aynı modelde dört dakika
sonraki yeni oturumun ilk isteğinde yine `429` almıştır. R80 erişilebilir sonraki
`gemini-3-flash-preview` modeliyle doğal sohbet, capability catalog ve
`MDB / TRENDYOL / production` kapsamındaki toplam `3112`, ReadyToShip `2` ve toplamı
`3112` olan status dağılımını doğru geçmiştir. Beşinci turdaki “son 5 siparişi ... kargo
firmasıyla listele” isteği ise mevcut kargo firması satır alanını kullanılabilir
`cargo_options` kataloğu sanmış; semantic verifier bu yüzden doğru `orders.query` adımını
reddetmiştir. Kök düzeltmede bounded recent order listesi için `cargo` projection'ı
canonical hale getirilmiş, `cargo_options` yalnız birincil provider-options hedefi olduğunda
operation binding'i ele geçirebilir kılınmıştır. İki regression ve bütün Orders task-runtime
paketi `228 passed / 242 conditional skipped / 17 subtests passed` vermiştir. Fresh R81
source-app tekrarında `gemini-3-flash-preview` modele ulaşmadan yeniden model-scope `429`
aldığı için bu düzeltme henüz canlı provider kabulü değildir.

Aynı kararda OpenRouter paid erişiminin nüansı secret-safe canlı çağrıyla ölçülmüştür.
`/api/v1/key` hâlâ `limit=1`, `usage=0.188776237`,
`limit_remaining=0.811223763`, `is_free_tier=true`; `/api/v1/credits` ise
`total_credits=0`, `total_usage=0.199355437` döndürmektedir. Buna rağmen
`deepseek/deepseek-v4-pro` için `max_tokens=4` exact ham çağrı HTTP 200 vermiş ve
`$0.0000127281` maliyetle dört completion token üretmiştir. Aynı modelin
`max_tokens=256` çağrısı provider tarafından “yalnız 54 token karşılanabilir” açıklamalı
HTTP 402 ile reddedilmiş; gerçek source-app structured-output isteği de 2048 token
bütçesinde modele ulaşmadan aynı `402/billing` sonucunu vermiştir. Dolayısıyla OpenRouter
anahtarı tamamen kapalı değildir; fakat görünen `$0.811224` key tavanı kullanılabilir
satın alınmış bakiye değildir ve mevcut mikro marj geçerli typed plan JSON'u için yeterli
değildir. Acceptance geçirmek amacıyla planner bütçesi 54 tokena düşürülüp yarım/bozuk
JSON kabul edilemez. Paid source-app kabulü gerçek kullanılabilir kredi oluştuğunda fresh
process'te yeniden başlar; direct dört-token probe provider/ürün kabulü sayılmaz.

R83 fresh source-app tekrarında erişilebilir en güçlü OpenRouter free adaylarından
`nvidia/nemotron-3-ultra-550b-a55b:free`, fallback kapalı exact model olarak aynı gerçek
“son 5 siparişi ... kargo firmasıyla listele” cümlesini tamamlamıştır. Typed interpretation
`cargo` projection'ını korumuş, `cargo_options` üretmemiş, model-authored plan
`orders.query` seçmiş ve beş authoritative satırın sipariş numarası, status, müşteri,
tarih, tutar, mevcut kargo firması ve takip numarası görünür cevapla birebir uyuşmuştur.
İlk final candidate verifier'dan geçmeyince aynı exact model bounded repair üretmiş;
`final_source=verified_model_repair`, `accepted_semantic_output=true`,
`fallback_used=false` ve artifact acceptance `accepted=true / problems=[]` olmuştur.
Bu yalnız R80 kök hatasının canlı focused kapanışıdır; 24+ turlu OpenRouter organik
kampanyasının veya bütün Faz 8B'nin yerine geçmez.

2026-07-29 Karar 66, bağlamsal sipariş detayı ve response-acceptance provenance'ını
kesinleştirir. R84 organik OpenRouter/Nemotron Ultra koşusunda model önce son beş siparişi,
sonra listedeki en yeni sipariş için `orders.full_context` planını doğru kurmuş; modelin
final cevabı kargo/takip/iade projection'ını eksik bıraktığında authoritative deterministic
projection görünür cevabı doğru tamamlamıştır. Buna rağmen Chat acceptance katmanı yalnız
`final_projection_verified` bayrağına baktığı için doğrulanmış
`fallback_projection_verified` sonucunu yanlışlıkla reddetmiştir. Kabul artık yalnız şu
koşulların tamamında `model_authored_verified_projection` sayılır: çalıştırılan business
operation'ların tamamı `llm_direct` plan adımlarından gelir, deterministic business step
eklenmez, semantic step eklenmez, gerçek final provider cevabı alınır ve görünür
deterministic projection bağımsız verifier'dan geçer. Ortak classifier hem Chat runtime hem
source-app artifact capture tarafından kullanılır.

R85 fresh focused tekrarında ikinci bir semantic ayrım bulunmuştur: “listedeki en son
siparişin kalemlerini, kargo firması ve takip bilgisini ... göster” cümlesindeki tekil mevcut
kargo alanı, genel `göster` fiili yüzünden yanlışlıkla `cargo_options` kataloğu sayılmış ve
doğru model-authored `orders.full_context` adımı semantic verifier tarafından reddedilmiştir.
`cargo_options` bundan sonra ancak seçenek/hangileri/uygun ya da açık çoğul provider-list
dili varsa tutulur; tekil siparişin mevcut kargo firması `cargo` projection'ıdır. R86 taze
source-app zinciri `orders.query -> orders.full_context` ile exact
`nvidia/nemotron-3-ultra-550b-a55b:free`, fallback kapalı biçimde geçmiştir. En yeni satırın
kalemi, mevcut kargosu, takip numarası ve “iade yok” bağlamı authoritative payload ile
eşleşmiş; artifact `final_status=passed`, `accepted=true`, `problems=[]` vermiştir. İlgili
tam paketler son durumda `356 passed / 307 conditional skipped`; Orders task-runtime tek
başına son semantic düzeltmeyle `230 passed / 244 conditional skipped` vermiştir.

R87 24+ turlu OpenRouter organik koşusu ilk iki doğal sohbet turunu exact Nemotron Ultra ile
toolsuz ve doğrulanmış model cevabıyla geçirmiş; üçüncü capability turunun final model
çağrısında normalized `HTTP 429 / quota_scope=free_tier` almıştır. Sıradaki ücretsiz
Nemotron Super ile açılan R88 ilk invocation'da aynı global free-tier kotasına takılmıştır;
bu yüzden modeller arasında sessiz fallback yapılmamış ve iki koşu da acceptance sayılmamıştır.
Gemini tarafında R89/R90 `gemini-3-flash-preview`, R91 `gemini-2.5-flash` taze süreçleri de
ilk invocation'da normalized `HTTP 429 / quota_scope=model` vermiştir. Provider'ın bildirdiği
retry penceresi sonrasında yapılan fresh tekrar da aynı sonucu verdiği için cloud uzun
kampanya dış erişim açılana kadar kapanmış değildir. Bu kota kanıtı uygulamanın agentic
başarısızlığı değildir; fakat başarı kanıtı da değildir. Ücretsiz provider baseline'ı,
50/60/100/200+ mesaj kampanyası ve Faz 8B kesinlikle açık kalır.

Aynı günün en son secret-safe OpenRouter kontrolünde `/api/v1/key`
`limit=1`, `usage=0.188820319`, `limit_remaining=0.811179681`,
`is_free_tier=true`; `/api/v1/credits` ise `total_credits=0`,
`total_usage=0.199399519` döndürmüştür. Exact `deepseek/deepseek-v4-pro`
`max_tokens=4` çağrısı yeniden HTTP 200, `max_tokens=256` çağrısı ise yalnız 34 token
karşılanabildiğini belirten HTTP 402 vermiştir. Dolayısıyla `$1` değeri API anahtarının
harcama tavanıdır; hesaba yüklenmiş kullanılabilir kredi değildir. Ücretli typed planner ve
response synthesis için yeterli kredi yoktur; mikro dört-token probe ile ürün kabulü
yapılmaz.

2026-07-29 Karar 67, gerçek Gemini 2.5 Flash genel sipariş analizi failure'ını cümleye
özel yama olmadan plan coverage, record scope ve metric provenance sözleşmelerinde
kapatmıştır. Persisted task kanıtında turn interpretation `count/status/amount/
item_sales_rows` istemiş, semantic contract yalnız `orders.total_count` taşımış; ilk
observation sonrası model evaluator mevcut remaining graph'i yalnız
`orders.item_sales_summary` ile değiştirmiştir. Bu operation eski aktif seçimden iki
order number miras almış; response verifier aggregate revenue bulunmayınca nested ürün
satırındaki ilk `gross_amount=199.99` değerini population cirosu sanmıştır.

Orders-owned metric registry artık `orders.revenue_total`,
`orders.item_sales_summary` ve `orders.fulfillment_risk_count` contract'larını ve bu
metrikleri kanıtlayabilen canonical operation/result alanlarını taşır. Turn state
`record_scope=all_matching|active_selection|exact_ids|unspecified` ayrımını yapar;
population analizi eski selection binding'ini alamaz. Planner candidate surface bütün
required metric'leri sağlayabilen domain operation'larıyla capability-grounded
genişletilir, fakat deterministic business plan yazılmaz. İlk plan ve observation
replan'i completed + proposed operation birleşiminde bütün metric coverage'ı korumak
zorundadır. Response verifier revenue için yalnız kayıtlı revenue kaynağını kabul eder;
item satırlarından, tek order tutarından veya arbitrary nested sayıdan aggregate ciro
üretemez.

Üç farklı açık uçlu paraphrase, risk boyutu, eksik ilk planın model repair'i, stale exact
selection yalıtımı, nested `199.99` yanlış revenue fixture'ı, geçerli summary + item
kanıtı ve requirement düşüren observation replan'i focused seçkide geçmiştir:
`7 passed / 7 conditional skipped / 3 subtests passed`. Bütün Orders task-runtime paketi
`237 passed / 251 conditional skipped / 20 subtests passed`; Chat/behavioral/catalog
entegrasyon seçkisi `393 passed / 306 conditional skipped / 9 subtests passed` vermiştir.
Bu source değişikliği önceki canlı source-app artifact'larının fingerprint'ini bilinçli
olarak stale yapmıştır; yeni fresh Gemini ve OpenRouter organik cloud koşuları geçmeden
Faz 8B veya Orders tamamlanmış sayılmaz.

Trendyol test ortamı aktif olarak kullanılmaktadır. Stage ve Production credential,
endpoint, account ve record uzayı hard-isolated kalır; Stage hatasında Production fallback
yoktur. Seller `2738` için gerçek Stage source daha önce HTTP 200 vermiş, 34 kaynak
satırından 32 kalıcı paket ve 32 kalem exact DB read-back ile doğrulanmış, kimliksiz iki
`Awaiting` satırı policy exclusion olarak ayrılmıştır. 2026-07-29 read-only güncellik
kontrolünde son 14 günlük ReadyToShip sonucu `0`; yerel Stage uzayında 506 paket ve 29 aktif
iade claim'i vardır. Aynı gün Seller `2738` üzerinde tek sipariş kargo değişikliği,
toplu kargo değişikliği ve iade onayı ayrı idempotency key, external proof, manifest,
audit ve authoritative read-back ile gerçek Stage campaign'inde doğrulanmıştır.
Closure audit üç required action type için `staging_campaign_verified=true`,
`missing=[]`, `problems=[]` üretmiş ve kanıtlar `stage_bulk_cargo_acceptance` checklist
item'ına işlenmiştir. Checklist alias uyumluluğu regression seçkisiyle birlikte
`12 passed` vermiştir. Bu Stage R2 kapanışıdır; açık cloud/source-app semantik kapılarını
ve daha geniş AI hedefini kapatmaz. Stage write/R2 kanıtları yalnız exact Stage scope,
approval, execute, read-back ve audit zinciriyle yürütülür; kullanıcı istemeden
Production mutation veya fiziksel baskı yapılmaz.

2026-07-29 Karar 68, R96-R100 source-app zincirinde ortaya çıkan üç ortak control-plane
sınırını bağlayıcı hale getirir:

1. **Typed semantic contract, legacy goal rewrite'tan üstündür.** R96'da
   `gemini-3.1-flash-lite` bütün-population hedefi için doğru
   `orders.count + orders.status_counts + orders.revenue_total +
   orders.item_sales_summary` graph'ını iki kez yazmış; eski `ürünlerini` keyword
   yardımcısı bu graph'i `orders.full_context` ile değiştirmiştir. Metric requirement
   taşıyan model graph'i bundan sonra legacy raw-text rewrite ile topludan tekile,
   aggregate'den detail'e veya sibling operation'a çevrilemez. Legacy yardımcı yalnız
   typed contract bulunmayan açık compatibility/diagnostic yolunda çalışabilir.
2. **Yeni operation çalıştırma yetkisi ayrı typed turn policy'dir.** Kullanıcının
   “yeni veri işlemi/tool/sorgu çalıştırmadan yalnız mevcut kanıttan açıkla” sınırı
   `operation_policy=existing_observations_only` olur. Bu tur plan/tool yoluna giremez;
   PII-safe typed önceki observation kanıtından açıklama üretir. Model yeni read önermiş
   olsa dahi runtime izin vermez; buna karşılık açık data-read isteğinde normal
   `allow_new_operations` korunur.
3. **Environment ve calendar scope modelin serbest business varsayımı değildir.**
   Bütün Orders/Returns scoped read sözleşmeleri `api_account_ids` bağlanabilir alanını
   açar. Kullanıcı mağaza/ortam söylemez ve etkin Production + Stage hesapları birlikte
   bulunursa generic operasyon yalnız Production'a bağlanır; açık Stage isteği yalnız
   Stage'e gider; ikisini aynı operasyonda birleştiren istek fail-closed clarification
   üretir. Kullanıcının açık `bugün/son 3 hafta/tüm zaman` takvim ifadesi typed period
   otoritesidir. Takvim söylemediği all-matching population/list/queue okumasına model
   `today` veya başka gizli daraltma ekleyemez; full matching local snapshot `all`
   uygulanır. Model planındaki şema-geçerli fakat çelişkili period, execution öncesi
   kullanıcıdan türetilmiş typed contract'a normalize edilir.

R98 fresh source-app ilk turunda `orders.recent`, Production MDB ile Stage Seller `2738`
kayıtlarını aynı iki satırlık listede karıştırdığı için koşu durdurulmuştur. Kök neden
domain query değil, `orders.recent` tool schema'sının handler'da bulunan
`api_account_ids` alanını sözleşmede dışarı açmamasıydı; aynı açıklık
`returns.reason_summary` için de kapatılmıştır. R99'da environment yalıtımı geçmesine
rağmen kullanıcı tarih söylemediği halde model `period=today` üretmiş; dört doğru atomic
operation sıfır günlük veri döndürüp yanlış bir sıfır analizi oluşturmuştur. Bu artifact
failed evidence olarak tutulur.

Fresh R100 exact `gemini-3.1-flash-lite` offscreen full-source-app focused tekrarı üç
adaptif turda geçmiştir. İlk turdaki genel recency sorgusu `api_account_ids=[1]`,
`goal_account_scope:environment_default`, yalnız `MDB / Trendyol / production`,
`period=all` ve exact iki kayıt taşımıştır. İkinci tur `record_scope=all_matching`,
`period=all` ile model-authored dört atomic read çalıştırmış; authoritative toplam
`3112`, status bucket toplamı `3112`, ciro `502518.01 TRY` ve 20 ürün satış satırı
görünür doğrulanmış cevapta korunmuştur. Üçüncü tur
`operation_policy=existing_observations_only`, `mode=explain`, `tool_calls=0` ile yalnız
mevcut kanıttan `MDB / Trendyol / production` kapsamını açıklamıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r100-gemini-3.1-flash-lite-population-scope-evidence-2026-07-29.json`;
`final_status=passed`, `accepted=true`, `problems=[]`. Deterministic kapsam seçkisi ve
task/conversation paketleri son durumda `251 passed / 255 conditional skipped /
20 subtests passed` vermiştir. Bu yalnız Karar 68 focused kapanışıdır; fresh 22+ tur
organik Gemini kampanyası, ayrı OpenRouter baseline'ı ve uzun konuşma kapıları hâlâ
açıktır.

2026-07-29 Karar 69, R101-R109 gerçek source-app tekrarlarında bulunan ortak agent
sınırlarını ve bunların kabul durumunu bağlayıcı hale getirir:

1. **Kullanıcının istemediği çalışma sınırı model tarafından icat edilemez.** R101'de model,
   açık yeni veri okuma isteğini `existing_observations_only` olarak yorumlayıp gerekli
   sorguyu çalıştırmamıştır. Bu policy yalnız kullanıcının açık “yeni tool/sorgu çalıştırma”
   sınırından türetilebilir; modelin serbest seçimi runtime tarafından
   `allow_new_operations` olarak düzeltilir.
2. **Observation sonrası replan tamamlanmış kanıtı unutamaz veya aynı metriği boş yere
   tekrarlayamaz.** R102'de model, zaten tamamlanan metric'i tekrar önererek planın kalan
   kapsamını bozmuştur. Replan, completed metric ledger ve hâlâ eksik typed requirement
   kümesi üzerinden doğrulanır; aynı işi tekrar etmek ya da gerekli sibling metric'i
   düşürmek reddedilir.
3. **Count ve exact list aynı kavram değildir.** R103'te kullanıcı exact liste isterken
   model count operation seçmiştir. Planner validation ile semantic verifier artık aynı
   paylaşılan typed read-contract haritasını kullanır; `count`, `list`, `detail`, `summary`
   aileleri birbirinin yerine geçirilemez. Model yanlış operation seçerse execution
   öncesinde model repair istenir; başarısız repair fail-closed olur.
4. **Authoritative boş liste geçerli kanıttır.** R104'te doğru exact liste sorgusu sıfır
   satır döndürmüş, verifier bunu eksik veri sanmış ve kullanıcıya “satırlar bulunamadı”
   şeklinde belirsiz cevap vermiştir. `all_matching` exact query'nin doğrulanmış boş sonucu
   artık zero-cardinality kanıtıdır; cevap açıkça “kargoya hazır sipariş yok / 0” demek
   zorundadır. Replan sırasında kullanıcıdan türetilmiş `period=all` korunur; gizli
   `today` daraltması eklenemez.
5. **Model istem dışı özel projection icat edemez.** R105'te Stage hedef sorgusunun doğru
   tek satırı bulunmuş, fakat model kullanıcı istemediği halde `item` projection eklediği
   için doğru sonuç genel “337 eşleşme” fallback'ine düşmüştür. `item`, `returns`,
   `address`, `tracking_number`, `package_id`, `customer_name` gibi özel alanlar yalnız
   kullanıcı sinyali veya typed devam bağlamıyla tutulur; aksi halde execution öncesi
   kaldırılır.
6. **Bir metriğin sayısı başka metriğin kanıtı olamaz.** R106'da cevap risk satırını
   atlamış, verifier kargoya-hazır metriğindeki aynı `0` sayısını risk sonucu sanarak cevabı
   kabul etmiştir. Metric verification bundan sonra değer eşitliğiyle değil metric label,
   operation provenance ve typed result alanı birlikte eşleştiğinde geçer.
7. **Dış marketplace kimliği iç DB primary key değildir.** R107'de model Stage SellerID
   `2738` değerini `api_account_ids` içine koymuş, runtime bunu internal account id sanıp
   doğru Stage kaydını kaçırmıştır. Account scope execution boundary'de authoritative
   account catalog'dan yeniden çözülür; modelin public SellerID, mağaza adı veya ortam
   değerleri internal PK yerine geçemez. Açık fakat çözülemeyen scope fail-closed olur.

Bu sınırlar cümleye özel router veya soru-cevap ezberi değildir. Kullanıcının serbest
ifadesi model tarafından intent/plan'a çevrilir; runtime ise entity, metric, population,
period, account identity, projection ve evidence provenance sözleşmelerini modelden
bağımsız uygular. Amaç bilinmeyen binlerce soruda aynı semantik invariants kümesini
korumaktır.

R101-R107'nin her biri önce gerçek model davranışıyla fail artifact olarak saklanmış,
ardından ilgili ortak sınır ve regression testi eklenmiştir. Son local Orders
task/conversation seçkisi `259 passed / 1 conditional skipped` vermiştir. Buna rağmen
Orders tamamlanmış değildir: R108 `gemini-3.1-flash-lite` tur 6'da provider HTTP 429,
R109 sonraki en iyi ücretsiz `gemini-2.5-flash` tur 2'de HTTP 429 ile durmuştur. Bunlar
ürün semantiği kabulü değildir ve başarılı tur sayılmaz. Fresh 22+ organik cloud konuşma;
summary, list/detail, uzun bağlam, Stage/Production scope, risk, returns, label, approval,
execute/read-back, Excel ve web zincirini tek kesintisiz kampanyada geçene kadar Faz 8B
açıktır ve UI Faz 9 frozen kalır.

OpenRouter için “1 USD limite ulaşıldı” denemez. Aynı gün `/api/v1/key` kanıtında limit
`1 USD`, kullanım yaklaşık `0.1888 USD`, kalan yaklaşık `0.8111 USD` görünürken
`/api/v1/credits` satın alınmış toplam krediyi `0 USD` göstermiştir. Exact ücretli
`deepseek/deepseek-v4-pro` dört tokenlık mikro erişim probunu çalıştırmış; 256 token ve
gerçek source-app typed planner bütçeli çağrılar HTTP 402 ile reddedilmiştir. Dolayısıyla
anahtarın harcama tavanı dolmamıştır, fakat hesapta ürün kabulü yapacak kullanılabilir
ücretli kredi yoktur; mikro prob başarılı ürün testi sayılmaz.

2026-07-29 Karar 70, R110-R116 source-app kampanyalarının ortaya çıkardığı plan, kapsam
ve cevap kanıtı sınırlarını bağlayıcı hale getirir:

1. **Sıra ifadesi exact selection üretir.** Bir önceki listeden “ilk sıradaki”,
   “üçüncü sıradaki”, “son sıradaki” veya sayı/sözcük ordinal ile seçilen kayıt yalnız o
   satıra indirgenir. `orders.query`, `orders.lookup` ve `orders.full_context` exact
   sözleşmede beklenen küme dışında tek satır dahi döndürürse sonuç reddedilir. R112'de
   beş satırın tamamına genişleyen `full_context` bu ortak sınırla kapatılmıştır.
2. **Typed metric coverage ile legacy primary-operation kuralı çelişemez.** Kullanıcının
   count/status/revenue/risk gibi metric requirements kümesi tek bir canonical summary
   operasyonuyla eksiksiz karşılanabiliyorsa semantic verifier ayrıca keyfi bir
   `orders.count` adımı zorlayamaz. R113'te doğru model-authored `orders.summary`
   planını reddeden iki farklı doğrulama kuralı tek typed metric registry üzerinde
   birleştirilmiştir.
3. **`all_matching` population referansı eski exact kimlik bağlamı değildir.** “Bu
   siparişlerin genel analizi / ürün dağılımı” gibi population hedefleri, cümlede
   deictic sözcük bulunsa bile eski `order_numbers` listesine daraltılmaz. R114'te
   `orders.item_sales_summary` adımını yanlış `context_binding_missing` ile durduran
   exact-binding dalı `record_scope=all_matching` için kaldırılmıştır.
4. **Planlama belleği ile kullanıcı cevabının kanıt kümesi ayrıdır.** Typed conversation
   state eski selection ve observation'ları uzun bağlam için korur; fakat final cevap
   yalnız mevcut task'ın completed step tool sonuçlarını, o step'lerin observation
   kimliklerini ve mevcut execute/verify kanıtını kullanabilir. Eski active selection,
   eski observation veya önceki task sayısı/kimliği current response provenance sayılmaz.
   R115'te doğru authoritative boş `ready_to_ship` sonucu varken cevaba sekiz tur önceki
   `<order-001>` kimliğinin sızması bu ayrımın yokluğunu kanıtlamıştır. Current empty-list
   cevabına stale kimlik ekleyen model adayı ve repair artık reddedilir; güvenli cevap
   yalnız “kuyruk boş / 0 sipariş” kanıtını projekte eder.
5. **Exact-model kabulünde provider kotası ürün başarısı değildir.** R116 tur 6'da
   `gemini-3.1-flash-lite` HTTP 429, `error_category=quota`,
   `quota_scope=model`, `retry_after_seconds=34`, sıfır model cevabı ve sıfır business
   effect ile durmuştur. Runtime başka modele sessiz geçmemiştir. Bu artifact provider
   erişilebilirlik kanıtıdır; semantic acceptance veya başarılı tur değildir.

R112-R115'teki her semantic sapma önce başarısız gerçek source-app artifact'ı olarak
saklanmış, sonra cümleye özel router yerine ortak typed invariant düzeltilmiş ve focused
regression eklenmiştir. Current-observation provenance değişikliği sonrası response
projection/verifier seçkisinde `37 passed / 37 conditional skipped` alınmıştır. Bununla
birlikte fresh kesintisiz 22+ organik cloud kampanyası henüz geçmediği için Faz 8B ve
Orders hedefi açık, UI Faz 9 frozen kalır.

2026-07-29 Karar 71, kullanıcının “Toplam kaç siparişim var; genel bakınca analiz yap”
gerçek sohbeti ile R117-R124 cloud koşularının ortaya çıkardığı genel yürütme ve kanıt
birleştirme sınırlarını bağlayıcı hale getirir:

1. **Genel analiz bir cümle kalıbı değil typed population contract'ıdır.** Model
   `requested_fields` içine `count/status/amount` yanında `date` gibi ek bir record alanı
   koyduğunda bu tek alan population analizini record-detail isteğine çeviremez.
   `metric=list|detail`, explicit exact kimlik ve bounded recent-list gerçekten record
   contract'ı olarak kalır; buna karşılık limitsiz `count|summary|status|amount` hedefinde
   iki veya daha fazla aggregate boyut `orders.total_count`,
   `orders.status_distribution`, `orders.revenue_total`, gerekiyorsa item/risk
   requirements üretir. Böylece başka bir güçlü model aynı niyeti farklı typed alanlarla
   anlatsa da yalnız `orders.count` veya bir ürün satırının `199.99` tutarı “genel analiz”
   diye yayımlanamaz.
2. **Bir model-yazarlı plan her koşulsuz başarılı ara adımda yeniden modele sorulmaz.** Semantic
   verifier tarafından kabul edilmiş `llm_direct`, `llm_direct_repaired` veya
   `llm_canonical_resolved` read planında çalıştırılan operation declared operation ile
   aynıysa, observation başarılıysa ve step'in bütün `expected_evidence` alanları gerçekten
   mevcutsa controller yalnız mevcut step'e bağlı olmayan, önceden yazılmış ara step'lere
   deterministik ilerler. Plan sonu, mevcut observation'a bağlı kalan step, başarısızlık,
   eksik/beklenmeyen kanıt, dependency sapması, belirsizlik veya gerçek replan ihtiyacında
   goal evaluator çağrılır.
   Bu modelin business plan yazma yetkisini azaltmaz; planı yürütmek için her tool
   observation'ında aynı planı modele yeniden onaylatan inference amplification'ı kaldırır.
3. **Tek bir kullanıcı turunun model çağrısı bütçesi provenance içinde görünürdür.**
   R121'de üç atomik read step'li basit population analizi interpretation + planning +
   üç observation evaluation + candidate + repair olmak üzere yedi provider cevabı
   tüketmiştir. Aynı exact modelin her başarılı adımda yeniden çağrılması kalite kanıtı
   değildir; free-provider rate limitini büyüten runtime kusurudur. Happy-path observation
   ilerlemesi model çağrısı yapmadığını testle kanıtlar; replan ve semantic sapma yolları
   model-led kalır.
4. **Kabul doğrulayıcısı tool adlarını değil kanonik sonuç sinyallerini sayar.** Bir
   population analizinin çok sinyalli sayılması için completed-step sonuçlarında gerçekten
   total count, status distribution, revenue, ready/return/risk veya item-sales kanıtından
   en az ikisi bulunur. İki tool adı olup metric sonucu bulunmayan tur geçmez;
   `orders.summary` tek başına üç authoritative metric taşıyorsa sırf allowlist'te adı yok
   diye yanlış negatif üretmez.
5. **Probe erişimi ile full-agent erişimi aynı iddia değildir.** Dört tokenlık veya tek
   structured-output preflight başarılı olsa bile interpretation/plan/step/replan/final
   zincirini tamamlamayan model full-agent baseline geçmiş sayılmaz. Exact-model 429'unda
   yalnız provider'ın açık `retry_after` ve normalized model scope kanıtı varsa, aynı
   prompt hash ile aynı modelde sınırlandırılmış bekleme/retry yapılabilir; probe bunu
   kapatabilmelidir. R124'te birden fazla Gemini modelinin aynı geri sayımlı 429 vermesi
   paylaşılan project/provider baskısına işaret eden bir çıkarımdır ve model bazlı
   sınıflandırma tek başına fallback yetkisi değildir.
6. **Typed list projection kimlik alanına bağımlı değildir.** Kullanıcı “son 5 siparişi
   tarih, durum ve tutarıyla listele” dediğinde `metric=list`, bounded limit ve row
   projection yeterlidir; ayrıca `order_number` istememiş olması sonucu aggregate summary
   yapmaz. `orders.query` aynı kanonik sonuçta pagination için population `total_amount`
   veya `status_counts` taşısa bile bunlar list cevabına kendiliğinden eklenemez. R130'da
   beş doğru satırın arkasına eklenen, önceki authoritative ciroyla da çelişen
   `519261.77 TRY` bu sınır eksikliğini kanıtlamıştır. List cevabındaki labeled aggregate
   claim yalnız requested aggregate metric varsa kabul edilir; aksi halde satır tutarları
   dışındaki aggregate sayı reddedilir ve deterministic projection yalnız istenen satır
   alanlarını yayımlar.
7. **Privacy taraması typed alan rolünü bilir.** `action_id`, `selection_id`,
   `record_id`, hash ve prepare fingerprint gibi opaque controller kimliklerindeki
   rastlantısal uzun rakam dizileri telefon numarası değildir. Bu alanlar value-pattern
   taramasından muaftır; fakat `customer_phone`, address/email anahtarları ve gerçek özel
   içerik aynı payload içinde fail-closed kalır. Stage preflight sonucu rastlantısal UUID
   içeriğine göre değişemez.

Karar 71 sonrasında exact kullanıcı niyeti focused regression'da total/status/revenue
requirements üretir; modelin fazladan `date` alanı eklemesi kapsamı bozmaz. Verified
model-authored read graph'ın bağımsız ara adımında goal evaluator'ın çağrılmadığı; plan
sonu, observation-dependent step ve eksik expected evidence halinde evaluator/replan
kapısının açık kaldığı ayrı testlerle kanıtlanır. Gemma'nın provider-independent guarded
JSON-text yolunda exact model olarak plan yazabildiği ve native Gemini tool/structured
authority'si almadığı adapter testiyle; list cevabında unrequested population revenue
claim'inin reddedildiği response regression'ıyla kanıtlanır. Fresh kesintisiz 22+ organik cloud
kampanyası hâlâ tamamlanmadığından Faz 8B
ve Orders hedefi açık, UI Faz 9 frozen kalır.

2026-07-29 Karar 72, R131 fresh source-app koşusunun ilk altı turunda ortaya çıkan
projection eksikliği için aşağıdaki ortak sınırı bağlayıcı hale getirir:

1. **Model kullanıcının açıkça istediği alanı typed projection'dan silemez.** Modelin
   objective metninde doğru kavramı tekrar etmesi yeterli değildir. Bounded row-list,
   exact detail/full-context, aggregate ve typed report sözleşmelerinin her biri kendi
   explicit canonical alanlarını `requested_fields` ve semantic contract projection
   içinde zorunlu tutar. Buna karşılık yalnız filtre/entity bağlamında geçen bir sözcük
   çıktı alanı sayılmaz: `kargoya hazır`, `kargo değişikliğine uygun` veya `onay bekleyen
   iadeler` ifadeleri sırasıyla cargo detail ya da nested return-context alanını
   kendiliğinden açamaz. Item-sales ve artifact gibi kendi typed row şemasına sahip özel
   rapor niyetleri de yalnız kendi canonical projection şemasını kullanır.
2. **Doğal dil alan sözlüğü çekimli biçimleri canonical role bağlar.** Türkçede
   `içerik -> içeriği/içeriğini` gibi ünsüz yumuşaması sonucu oluşan kökler ortak field
   lexicon'da aynı `item` rolüne normalize edilir. Bu bir cevap cümlesi veya tool router
   yaması değildir; model hangi operation'ı seçerse seçsin interpretation, response
   verifier ve deterministic projection'ın paylaştığı typed alan sınırıdır.
3. **Eksik detail cevabı başarılı sayılamaz.** R131 tur 6'da ordinal active selection
   doğru tek siparişe bağlanmış ve `orders.full_context` doğru çalışmış olsa da model
   `içeriğini` objective içinde anlayıp `item` alanını projection'dan düşürmüş; iki model
   cevabı da istenmeyen address genişlemesi nedeniyle reddedilmiş ve fallback yalnız
   müşteri/kargo alanlarını yayımlamıştır. Görünür cevap açıkça istenen sipariş kalemini
   taşımadığı ve runtime `deterministic_projection_failed` verdiği için kampanya ilk
   kritik sapmada durdurulmuş, başarı sayılmamıştır. Aynı sınıf artık explicit-field
   retention ve projection regression'ıyla fail-closed kalır.

R131'in ilk beş turu tool-free sohbet, grounded capability catalog, total/status/revenue
population analizi ve satır-alanlarıyla bounded recent-list için doğru davranmıştır;
ancak altıncı turun failure'ı önceki turları Orders kabulüne dönüştürmez. Kaynak
değişikliğinden sonra fresh 22+ organik cloud kampanyası birinci turdan yeniden
başlatılmadan Faz 8B geçmez; UI Faz 9 frozen kalır.

2026-07-29 Karar 73, R132 tur 3'te “Siparişler konusunda benim için hangi işleri
yapabiliyorsun?” sorusunun generic conversation sayılmasıyla ortaya çıkan capability
paraphrase sınırını bağlayıcı hale getirir:

1. **Capability intent tek bir soru kalıbı değildir.** `neler yapabilirsin`, `hangi
   işleri yapabiliyorsun`, `hangi görevleri üstlenebilirsin`, `yapabildiğin operasyonlar
   neler` ve yardım/destek eşdeğerleri; interrogative + affordance/task concept +
   ability/offer predicate bileşimiyle aynı typed `capability_overview` intent'ine
   normalize edilir. Bu katman business operation seçmez; model-authored intent'i
   doğrular ve yalnız capability catalog cevap yolunu açar.
2. **Capability cevabının kaynağı model belleği değildir.** Doğrulanmış capability
   sorusu canonical operation catalog ve domain parity kaydından projekte edilir.
   Modelin sıradan sohbet yolunda “sipariş durumlarını güncelleyebilirim” gibi belirsiz
   veya kayıtsız bir yetenek iddiası üretmesi kabul edilmez. Greeting ve sıradan domain
   sohbeti interrogative/affordance/ability bileşimini taşımadığı sürece capability
   kataloguna çevrilmez.

R132 ilk iki doğal sohbet turunu geçmiş; üçüncü turda model objective/reason seviyesinde
yetenek sorusunu anlamış olsa da eski yüzey-kalıbı guard typed intent'i conversation'a
geri çevirdiği ve cevap grounded catalog kullanmadığı için kampanya durdurulmuştur.
Paraphrase ailesi ve greeting karşı örneği regression testine bağlanmıştır. Fresh 22+
cloud kampanyası kaynak değişikliği nedeniyle yeniden birinci turdan başlar; Faz 8B ve
Orders hedefi açık, UI Faz 9 frozen kalır.

2026-07-29 Karar 74, R133 tur 6'da görünür exact-order fallback bütün istenen alanları
taşıdığı halde privacy verifier'ın bunu reddetmesiyle ortaya çıkan nested field-role
sınırını bağlayıcı hale getirir:

1. **Privacy rolü en yakın typed leaf tarafından belirlenir.** Orders full-context
   payload'ında `shipment_address.recipient_name` ve
   `invoice_address.recipient_name` adres nesnesi altında bulunsa da değer rolü
   customer/addressee identity'dir; sokak adresi değildir. Verifier ancestor container
   adına bakıp müşteri adını address sızıntısı sayamaz. `address`, `district`, `city`,
   `neighborhood`, `postal_code` ve gerçek adres metni address rolünde fail-closed
   kalır.
2. **Aynı görünür projection kendi verifier'ıyla tutarlı olmalıdır.** R133'te ordinal
   selection ve `orders.full_context` doğru çalışmış; fallback order number, customer,
   cargo, tracking ve ürün kalemini eksiksiz yayımlamıştır. Buna rağmen nested
   `recipient_name` yanlış role girdiği için `unrequested_private_field:address` oluşmuş
   ve `deterministic_projection_failed` verilmiştir. Görünür cevap doğru görünse bile
   internal verified projection false olduğu için tur geçmemiş, kampanya durdurulmuştur.

Nested recipient role ve gerçek address metninin ayrışması response regression'ına
bağlanmıştır. Kaynak değişikliğinden sonra fresh cloud kampanyası birinci turdan
başlatılır; Faz 8B ve Orders hedefi açık, UI Faz 9 frozen kalır.

2026-07-30 Karar 75, R134 tur 8'de authoritative hazır kuyruk count/list sonucunun
ikisinin de sıfır olmasına rağmen doğru empty-set cevabının reddedilmesiyle ortaya çıkan
filter/projection ayrımını bağlayıcı hale getirir:

1. **List filter'ı cevap kolonu değildir.** `ready_to_ship`, Stage seller, tarih
   aralığı veya başka bir selection filtresi hangi kayıtların sorgulanacağını belirler;
   kullanıcı ayrıca istemedikçe amount/date/count/risk gibi cevap kolonlarını açmaz.
   Model typed list projection'a bu alanları kendiliğinden eklerse interpretation
   sınırında kaldırılır. Kullanıcı tarih veya tutarı açıkça istediyse aynı alanlar
   korunur; bounded recent row-list davranışı değişmez.
2. **Authoritative empty set eksik evidence değildir.** Exact list operation
   `orders=[]`, `order_numbers=[]`, `listed_count=0`, `truncated=false` ve doğru status
   scope taşıyorsa istenen row set tamamlanmıştır. Var olmayan satırlar için modelin
   uydurduğu amount/date kanıtını talep etmek ve doğru “kuyruk boş / 0 sipariş” cevabını
   `amount_evidence_missing` ile reddetmek yasaktır.

R134 tur 7'de `orders.ready_to_ship_count=0`, tur 8'de
`orders.ready_to_ship` exact boş set dönmüş ve görünür cevap doğru olmuştur; fakat model
istenmemiş amount/date projection'ı eklediği için üç cevap yolu da
`amount_evidence_missing` almış, kampanya bu internal inconsistency nedeniyle
durdurulmuştur. Explicit date/amount row-list karşı örneği ve empty-set projection
regression'ı birlikte geçmeden düzeltme kabul edilmez. Fresh cloud kampanyası kaynak
değişikliği nedeniyle birinci turdan başlar; Faz 8B ve Orders hedefi açık, UI Faz 9
frozen kalır.

2026-07-30 Karar 76, R135 tur 10'da modelin doğru iki adımlı
`orders.query -> orders.change_cargo_provider.prepare` grafını üretmesine rağmen
runtime'ın planı reddetmesiyle ortaya çıkan prepare/dataflow sınırlarını bağlayıcı hale
getirir:

1. **Prepare-only talebi read değildir, execute da değildir.** Kullanıcı “kargo
   firmasını ARASMP yapmaya hazırla ama kesinlikle çalıştırma” dediğinde typed turn
   `mode=act`, `intent_kind=action` olur; yalnız immutable approval paketi hazırlama
   yetkisi verir. Gerçek marketplace mutation yine ayrı açık onay, execute ve read-back
   gerektirir. “Henüz hazırlama / yalnız göster” gibi açık negatifler inspect olarak
   kalır.
2. **Atomic graph güvenli dizi elemanı bağlayabilir.** Bir canonical read sonucunun
   `tool_result.orders[0].order_number` gibi positive-index JSON yolu, yalnız declared
   ve tamamlanmış dependency'den okunmak üzere desteklenir. Negatif indeks, wildcard,
   recursive selector, key enjeksiyonu veya undeclared step kaynağı fail-closed kalır.
   Böylece model önce filtreleyip/sıralayıp sonra seçtiği exact satırı başka bir atomic
   operation'a aktarabilir; bunun için birleşik mega-tool gerekmez.
3. **Semantik normalizer action'ın zorunlu model-yazarlı dependency'sini düşüremez.**
   Legacy intent policy genel bir `ready_to_ship/recent` scope adımı beklese bile
   provider planındaki daha spesifik filtered/sorted `orders.query`, kabul edilmiş
   action tarafından declared dependency olarak kullanılıyorsa transitive dependency
   closure içinde korunur. Yalnız action'a bağlı canonical read korunur; ilişkisiz
   provider adımları tutulmaz ve runtime eksik business step icat etmez.
4. **Prepared-action verifier sembolik binding'i kayıt kimliği sanamaz.** Plan hedef
   kümesi doğrulanırken `{"$from_step": ...}` nesnesinin metni değil execution
   boundary'de çözülmüş `order_numbers` kümesi kullanılır. Hazırlanan action'ın record
   refs kümesi bu exact çözümlenmiş kümeyle eşleşmeden pending approval yayımlanmaz.
5. **Modelin istem dışı option projection'ı plan zorunluluğu oluşturamaz.** Kullanıcı
   hedef kargo sağlayıcısını açıkça vermişken modelin eklediği `cargo_options`,
   `orders.cargo_provider_options` read'ini zorunlu kılamaz. Provider seçenekleri yalnız
   kullanıcı seçenekleri/listeyi açıkça istediğinde typed projection olur; aksi halde
   mevcut cargo alanına normalize edilir.

R135 tur 1-9 doğal sohbet, grounded capability, population summary, bounded list,
ordinal exact detail, authoritative empty ready count/list ve risk composition
adımlarını geçmiştir; tur 10 failure'ı yine de kampanyayı başarısız kılmıştır. Kök zincir
Stage Seller `2738` kapsamını internal account PK'ye authoritative çözerek iki Picking
kayıt arasından en yenisini seçen, yalnız o sipariş için `ARASMP` approval paketi
hazırlayan ve DB cargo değerini değiştirmeyen end-to-end regression ile kanıtlanmıştır.
Orders agentic runtime sonucu `267 passed / 281 conditional skipped / 27 subtests`
olmuştur. Fresh 22+ cloud source-app kampanyası birinci turdan geçmeden Faz 8B kapanmaz;
UI Faz 9 frozen kalır.

2026-07-30 Karar 77, R136 tur 6'da modelin objective içinde sipariş içeriğini doğru
anladığı ve `orders.full_context` authoritative ürün kalemini döndürdüğü halde typed
`requested_fields` listesinden `item` alanını silmesiyle ortaya çıkan contextual
projection sınırını bağlayıcı hale getirir:

1. **Typed selection üzerindeki açık alan listesi kullanıcı otoritesidir.** Kullanıcı
   “bu listedeki ilk sipariş”, “üçüncü kayıt” veya başka bir anaphoric/ordinal referansla
   mevcut selection'ı hedefleyip numara, müşteri, durum, kargo, takip, içerik, tutar gibi
   alanları açıkça sayıyorsa bu alanlar response projection contract'ına union edilir.
   Model objective içinde alanı anlayıp `requested_fields`ten düşürerek görünür cevaptan
   silemez.
2. **Selection projection ile population filter ayrıdır.** Bu koruma yalnız typed
   contextual record target'ında uygulanır. “Kargo değişikliğine uygun Picking
   siparişini listele” gibi bağımsız filtre sorgusu cargo/item detayını kendiliğinden
   açmaz. Kullanıcının gerçekten “uygun kargo firması seçeneklerini göster” dediği özel
   durumda `cargo_options`, sıradan `cargo` alanının yerini almaya devam eder.
3. **Provider finali boşsa fallback bütün explicit contract'ı taşımalıdır.** R136'da
   exact model final text çağrısı aynı modelde üç denemeden sonra boş dönmüş; fakat
   authoritative full-context kanıtında ürün adı/adedi mevcuttur. Deterministic verified
   projection kullanılacaksa açıkça istenen `item` dahil bütün alanları yayımlar; eksik
   fallback tool başarısıyla veya `success=true` bayrağıyla kabul edilemez.

R136 ilk beş turda doğal sohbet, grounded capability, authoritative
total/status/revenue population analizi ve aggregate sızıntısız beş satırlı recent-list
adımlarını geçmiştir. Tur 6 doğru exact kaydı bulmuş fakat görünür cevap ürün içeriğini
atladığı ve runtime `accepted_semantic_output=false` verdiği için kampanya başarısız
kapatılmıştır. Aynı cümle “ayrıntı/detay” sözcüğü olmadan projection regression'ına,
filtre ve `cargo_options` karşı örnekleriyle birlikte bağlanmıştır. Orders agentic runtime
sonucu `268 passed / 282 conditional skipped / 27 subtests` olmuştur. Kaynak değişikliği
sonrası fresh 22+ cloud kampanyası birinci turdan yeniden başlar; Faz 8B ve Orders hedefi
açık, UI Faz 9 frozen kalır.

2026-07-30 Karar 78, R137 tur 8'de `orders.ready_to_ship` authoritative olarak exact
boş küme döndürdüğü halde yalnız `order_number` isteyen list projection'ının “sipariş
numarası kanıtı bulunamadı” cevabına düşmesiyle ortaya çıkan zero-cardinality sınırını
bağlayıcı hale getirir:

1. **Boş row set bütün row kolonları için vacuously complete'tir.** Typed contract
   `entity=order`, `metric=list`, `record_scope=all_matching` iken canonical list
   operation `orders=[]`, `listed_count|selected_count|ready_to_ship=0` ve
   `truncated=false` döndürüyorsa; order number, status, date, amount, customer veya
   başka satır alanı için tek tek missing-evidence aranmaz. Doğru cevap kayıt
   bulunmadığını ve `0 sipariş` olduğunu açıklar.
2. **Bütün fallback projection'ları aynı empty-set authority'sini kullanır.**
   `_order_rows` yolu boş kuyruğu doğru projekte ederken yalnız `order_number` yolu ayrı
   “authoritative sonuçta bulunamadı” metnine düşemez. Count/list/identifier
   projection'ları ortak current-operation provenance ve zero-cardinality helper'ına
   bağlanır.
3. **Empty set eski selection kimliğini yeniden açmaz.** Prior turn'deki exact sipariş
   selection'ı typed memory'de kalabilir; current authoritative empty list cevabına o
   sipariş numarası eklenemez. Empty cevabın gerçekten “boş/0” dememesi de
   `empty_order_list_projection_missing` ile reddedilir.

R137 tur 1-7 doğal sohbet, grounded capability, population summary, recent-list,
ordinal full-context ve ready count adımlarını geçmiştir. Tur 8 doğru `0` satırı
gözlemlemiş fakat deterministic identifier fallback yanlış metin ürettiği için kampanya
başarısız kapatılmıştır. Identifier-only empty projection, explicit multi-column empty
projection ve stale-selection karşı örneği aynı regression ailesinde geçmeden düzeltme
kabul edilmez. Fresh cloud kampanyası kaynak değişikliği nedeniyle birinci turdan
yeniden başlar; Faz 8B ve Orders hedefi açık, UI Faz 9 frozen kalır.

2026-07-30 Karar 79, R139 tur 12'de “son 3 haftanın en çok satan ilk 10 ürününü
burada listele, dosya oluşturma” hedefinin zengin canonical report operation'ı yerine
dar metric operation'larına ayrılmasıyla ortaya çıkan analiz/artifact izin sınırını
bağlayıcı hale getirir:

1. **Report analizi ile dış artifact üretimi ayrı yetkilerdir.** Kullanıcının “dosya
   oluşturma”, “Excel istemiyorum”, “do not export” gibi açık negatif talebi ad-hoc
   analizi engellemez; `orders.item_sales_report` yine immutable, hash'li ve
   PII-minimized `ReportSnapshot` üretir. Yalnız XLSX/CSV/PDF dosyası hazırlayan effectful
   operation çağrılmaz.
2. **Negatif artifact dili export niyeti sayılamaz.** Aynı cümlede `liste` ve `dosya`
   sözcüklerinin bulunması, negatif fiili yok sayıp turn'ü action/export olarak
   sınıflandıramaz. Typed permission boundary önce açık artifact yasağını çözer; report
   read ile export prepare ayrımını modelin rastlantısal tool seçimine bırakmaz.
3. **Zengin ad-hoc rapor dar aggregate'lerle taklit edilemez.** Dönem, group-by, sıralama,
   limit, adet, sipariş sayısı ve tutar isteyen ürün satış hedefinde birden çok
   `orders.item_sales_summary` / `orders.revenue_total` / `orders.count` cevabını prose
   içinde birleştirmek immutable snapshot sözleşmesinin yerine geçmez. Sonraki Excel
   isteği yalnız aynı doğrulanmış snapshot ID/content hash üzerinden hazırlanır.
4. **Görünür makul liste internal verification failure'ı örtemez.** Candidate ve repair
   grounded görünse bile requested item metrics eksik veya aggregate tutar uyuşmazsa
   `deterministic_projection_failed` kritik ürün failure'ıdır; kampanya durdurulur ve
   export zincirine geçilmez.
5. **Intent normalizasyonu source encoding'den bağımsızdır.** Source-app/provider
   sınırında UTF-8 metin Latin-1 veya Windows-1252 olarak bir kez çözülmüşse ortak
   normalizer yalnız geçerli UTF-8 round-trip ve azalan mojibake skoru halinde metni
   onarır; sonra casefold/Türkçe normalizasyonu uygular. `casefold` sonrasında yalnız
   büyük harfli mojibake dizilerini değiştiren ölü mantık kabul edilmez. Düzgün Unicode
   ile mojibake eşdeğeri aynı typed intent, permission ve plan contract'ını üretmelidir.

R139 tur 1-11 doğal sohbet, grounded capability, population summary, exact recent/detail,
zero-cardinality ready count/list, multi-operation risk composition ve Stage-only
prepare-cancel sınırlarını geçmiştir. Tur 12'de model üç dar operation seçmiş; görünür
liste oluşmasına rağmen `report_snapshot` bulunmamış, candidate/repair projection'ı
`aggregate_amount_claim_mismatch` ve `requested_item_sales_metrics_missing` ile
reddedilmiş ve kampanya başarısız kapatılmıştır. Negatif artifact izni ile pozitif
“Excel'e hazırla; dosya üretmeden önce onay bekle” karşı örneği birlikte regression'a
bağlanmıştır. Orders agentic runtime `269 passed / 283 conditional skipped / 27
subtests`, AI pipeline `295 passed / 35 subtests` geçmiştir. Kaynak değişikliği sonrası
fresh cloud kampanyası birinci turdan başlar; Faz 8B ve Orders hedefi açık, UI Faz 9
frozen kalır.

R140 aynı ilk 11 fazı yeniden geçmiş fakat tur 12'de kaynak değişikliğine rağmen aynı
dar planı üretmiştir. Provenance, planın `source=llm_direct`,
`semantic_authority=typed_metric_contract`, `metric=count` ve üç operation
(`orders.item_sales_summary`, `orders.revenue_total`, `orders.count`) taşıdığını
göstermiştir. Unit/source-app ayrışmasının kökü cümle kuralı değil ortak `_normalized`
girişinde bulunmuştur: mojibake metin önce casefold edildiği için mevcut büyük harfli
replacement dizileri hiçbir zaman eşleşmemiş, hem “en çok satan ürün” hem negatif
“dosya oluşturma” sinyali kaybolmuştur. UTF-8/Latin-1 ve UTF-8/CP1252 güvenli round-trip
onarımı ortak boundary'ye alınmış; düzgün ve bozuk metin eşdeğerliği regression'a
bağlanmıştır. Orders agentic runtime `270 passed / 284 conditional skipped / 27
subtests`, AI pipeline `295 passed / 35 subtests` geçmiştir. Fresh R141 kampanyası
birinci turdan başlar; Faz 8B ve Orders hedefi açık, UI Faz 9 frozen kalır.

R141 aynı ilk 11 fazı yeniden geçmiş, tur 12 aynı failure'ı üretmiş ve encoding
düzeltmesinin gerekli fakat yetersiz olduğu kanıtlanmıştır. R142 timeout sonrası R143
focused observability koşusu gerçek source-app girdisinde
`item_sales_report=true`, `report_export=false`, `report_export_prohibited=true`
sinyallerini göstermiş; buna rağmen typed semantic contract'ın
`metric=count`, `metric_requirements=[orders.total_count, orders.revenue_total,
orders.item_sales_summary]` ürettiğini kanıtlamıştır. Böylece nihai sahip katman
encoding veya model retrieval değil, satır projection'ını population aggregate'ine
çeviren semantic-contract compiler olarak belirlenmiştir.

`item_sales_rows` taşıyan explicit top-selling hedefi artık list-shaped bir contract
üretir; ürün satırındaki adet/sipariş sayısı/brüt tutar kolonları ayrı population
count/revenue gereksinimlerine çevrilmez. Yeni
`orders.item_sales_report_snapshot` metric contract'ı yalnız
`orders.item_sales_report` operation'ının immutable `report_snapshot`, `snapshot_id`,
`content_hash` ve `row_count` evidence'ıyla karşılanır. Modelin summary/revenue/count
kompozisyonu eksik metric nedeniyle reddedilir ve model repair gerçek snapshot
operation'ına dönmeden plan kabul edilmez. Orders agentic runtime `271 passed / 285
conditional skipped / 27 subtests`, AI pipeline `295 passed / 35 subtests` geçmiştir.
Focused fresh source-app kanıtından sonra tam organik kampanya yine birinci turdan
başlar; Faz 8B ve Orders hedefi açık, UI Faz 9 frozen kalır.

2026-07-30 Karar 80, R145 tur 10'daki Stage kargo hazırlama ve eski genel analiz
artifact'ında görülen selection/dataflow belirsizliğini bağlayıcı biçimde ayırır:

1. **Query filtresi ile dönen exact set aynı alan değildir.** `orders.query`
   `requested_order_numbers` içinde yalnız çağrı filtresini, `order_numbers` ve
   `returned_order_numbers` içinde ise gerçekten dönen authoritative exact seti taşır.
   Sonraki atomic action yalnız bu gerçek seti typed dependency binding ile alabilir.
2. **Exact dependency yanlış parametre yuvasında gelse bile business seçimi yeniden
   yapılmaz.** Model `orders[0].order_number` binding'ini fuzzy `query` alanına koyarsa
   compiler bunu yalnız eşdeğer schema canonicalization olarak `order_numbers` alanına
   taşır. Hangi kaydın seçileceğine deterministic katman karar vermez.
3. **Population analizi execution sınırında exact ID ile daraltılamaz.** Semantic
   contract `record_scope=all_matching` iken stale active selection veya model replan'i
   `order_numbers/claim_ids` enjekte ederse operation çalışmadan
   `typed_all_matching_scope_narrowed_by_exact_ids` ile reddedilir.
4. **Account/environment scope action'a kadar taşınır.** Cargo prepare operation'ları
   optional `api_account_ids` kabul eder, latest snapshot'ı exact hesapta filtreler ve
   prepared action evidence'ına hesap/ortam kapsamını ekler. Stage selection production
   kaydıyla veya tersine karışamaz.

Bu sınırlar R145 eşdeğeri Stage cargo regression'ı, stale population fixture'ı ve tam
paketlerde kanıtlanmıştır. Sonraki cloud kabulü yine fresh process gerektirir.

2026-07-30 Karar 81, kullanıcının “toplam kaç siparişim var, genel bakınca analiz yap”
hedefinin R147-R150 fresh konuşmalarında doğru operation'lar çalıştığı hâlde ham metric
dökümüne veya deterministic uzun ürün listesine düşmesiyle ortaya çıkan
evidence/projection ayrımını bağlayıcı hale getirir:

1. **Analiz kanıtı ile görünür liste çıktısı ayrı sözleşmelerdir.** Broad analysis için
   `orders.item_sales_summary` bütün population üzerinde ürün performans kanıtı üretir;
   kullanıcı açıkça ürün listesi istemedikçe ilk 20 veya ilk 5 satırın tamamını görünür
   cevaba dökmek zorunlu değildir. Explicit top-selling list/report ise bounded bütün
   satır ve kolonları eksiksiz yayımlamaya devam eder.
2. **Yorum için aritmetiği model uydurmaz.** Orders domaini aynı authoritative
   snapshot'tan `status_rates`, baskın durum/adet/oran, iptal oranı, gelir kapsamındaki
   sipariş adedi ve sipariş başına ortalama tutarı hesaplar. Ürün aggregate'i toplam
   adet, ilk beş adet ve ilk beş yoğunluk oranını domain-owned metric olarak döndürür.
   AI wrapper yalnız schema/scope/provenance taşır.
3. **Concise analiz typed göstergelerle doğrulanır.** Broad analysis cevabı tam status
   tablosu ve beş ürün satırı yerine baskın durum veya iptal oranı ile ürün yoğunluğu
   göstergesini taşıyabilir. Domain-derived göstergeler bulunmayan legacy observation'da
   verifier sessizce gevşemez; eski tam status/satır projection'ına döner.
4. **Yerel sayı biçimi numeric role'u değiştirmez.** `3.859,50` ile `3859.5` aynı
   authoritative decimal olabilir; `3.112` hem locale binlik hem decimal belirsizliğini
   güvenli eşdeğer kümeyle taşır. Yüzde/rate değeri toplam adet iddiası sayılamaz.

R149 doğru scope ve metrikleri üretmiş fakat ürün satırlarını zorunlu tutan eski görünür
contract nedeniyle failed; R150 kısa doğru projection üretmiş fakat doğal toplam ifadesi
dar parser'a takılmıştır. Bu failure'lar başarılı gösterilmemiştir.

2026-07-30 Karar 82, R152 Gemini 2.5 Flash Lite'ın objective içinde açıkça analiz ve
overview hedefini anlamasına rağmen `metric=count` ve eksik ürün boyutu üretmesiyle
ortaya çıkan request-shape boşluğunu kapatır:

1. **Geniş analiz typed bir request shape'tır.** Turn interpretation şeması
   `request_shape=broad_analysis` taşır. Bu değer yalnız model-authored structured
   interpretation'dan gelir; runtime kullanıcı cümlesindeki “analiz” kelimesine regex
   bağlayarak shape uydurmaz.
2. **Broad shape canonical minimum evidence setini belirler.** Orders population,
   exact-ID/selection veya bounded-list olmayan `broad_analysis`; `metric=summary`,
   `record_scope=all_matching` ve en az total count + status distribution + revenue total
   + item sales summary requirements üretir. Açıkça istenen risk ayrıca eklenir.
3. **Shape'ler birbirine genişlemez.** Scalar count, exact record detail, bounded row
   list, immutable artifact report ve action ayrı enum değerleridir; broad-analysis
   defaultları bu hedeflere sızamaz.
4. **Metric doğrulama cümle kalıbına bağlı değildir.** Authoritative total değerinin
   order entity etiketiyle doğal yakınlığı yeterlidir; ancak `%94,79` gibi rate ifadesi
   toplam count claim'i olarak parse edilemez.

R151 aynı kaynakta final sentez sırasında açık `HTTP 429 / quota_scope=model /
retry_after=59` aldığı için cloud kabulü sayılmamıştır. Sonraki erişilebilir ücretsiz
model `gemini-2.5-flash-lite` ile fresh R154, 8.265 saniyede
`orders.summary + orders.item_sales_summary`, `all_matching`, dört bağımsız metric ve
doğal Türkçe model cevabını `verified_model_candidate`, fallback/repair olmadan
tamamlamış; acceptance validation `problems=[]` ile passed olmuştur. Görünür cevap toplam
`3112`, ciro `502.518,01 TL`, Delivered `2950 / %94,79`, iptal `%3,53`, ortalama
`167,39 TL` ve ilk beş ürün yoğunluğu `1211/5835 / %20,75` kanıtlarını taşımıştır.

2026-07-30 Karar 83, gerçek konuşma kayıtlarının zaman/provenance ayrımını ve model
kararına karşı legacy phrase guard otoritesini bağlayıcı hale getirir:

1. **Yeni kullanıcı failure'ı önce gerçek task kaydına bağlanır.** Paylaşılan “toplam
   kaç siparişim var, genel bakınca analiz yap” kötü cevabının persisted kaydı 29 Temmuz
   runtime'ına aittir. O sürüm görevi `orders.count + orders.item_sales_summary` ile
   eksik tamamlamış, status evidence üretmemiş ve tek satırdaki `199.99` tutarını genel
   ciro gibi project etmiştir. Bu kayıt regression'dır; ancak güncel kaynak davranışıyla
   karıştırılarak yeni bir cümle yaması gerekçesi yapılamaz.
2. **Completion, seçilen tool sayısına değil typed evidence coverage'a bağlıdır.** Orders
   population `request_shape=broad_analysis` hedefi; total, status distribution, revenue
   ve item-sales requirements'ın tamamı authoritative observation'larla karşılanmadan
   complete olamaz. Tek kayıt/satır tutarı population revenue yerine geçemez; eksik
   status veya item-sales kanıtı final cevapta “bulunamadı” denilerek başarıya çevrilemez.
3. **Model-authored typed shape legacy doğal-dil guard'ından üstündür.** R157'de
   `gemini-3-flash-preview`, capability paraphrase'ını doğru biçimde
   `intent_kind=capability_overview` olarak üretmiş; eski Türkçe phrase guard bunu
   conversation'a düşürmüştür. Phrase guard kaldırılmış, `request_shape` içine
   `capability_overview` eklenmiş ve yalnız typed domain/intent/shape invariant'ı
   bırakılmıştır. Aynı gerçek paraphrase R158'de canonical capability catalog ile
   `typed_capability_catalog_grounded` olarak geçmiştir.
4. **Güvenli deterministic projection model kabulü değildir.** R160'ta farklı ve açık
   uçlu analiz paraphrase'ı doğru `broad_analysis` shape'ını, `all_matching` kapsamını ve
   `orders.summary + orders.item_sales_summary + orders.fulfillment_risk_count`
   kompozisyonunu kurmuştur. İlk model sentezi toplam/risk projection doğrulamasını,
   bounded repair ise risk projection'ını geçememiş; kullanıcıya yalnız doğrulanmış
   deterministic projection gösterilmiştir. Görünür güvenlik davranışı doğrudur fakat
   exact `gemini-3.1-flash-lite` kabulü sayılmamış, R160 ilk kritik model cevabında
   failed kapatılmıştır.
5. **Ardışık count farkı metinden tahmin edilmez; snapshot zamanı incelenir.** Aynı eski
   konuşmadaki ready-to-ship sonucunun `2`den `0`a düşmesi modelin kullanıcı beklentisini
   gerçek sayması değildir: ilk okuma `2026-07-29T11:10:34Z` sonrasında iki paket
   ReadyToShip'tir; aynı paketlerin authoritative Shipped snapshot'ları DB'ye
   `2026-07-29T11:11:29Z`de yazılmış ve ikinci okuma `11:11:53Z`de gerçekten boş set
   dönmüştür. Böyle temporal değişimler source revision, snapshot hash ve persisted
   domain kayıtlarıyla ayrılmadan agent hatası veya başarısı ilan edilemez.

Bu karar belirli Türkçe cümleleri tanıyan router eklenmesine izin vermez. Aynı anlamın
beklenmedik kelime ve cümle yapılarında çözülmesi provider'ın typed interpretation'ı,
metric coverage compiler'ı, canonical domain observation'ları ve semantic verifier ile
sağlanır; konuşma metninin kendisi yalnız regression girdisidir.

2026-07-30 Karar 84, R161'deki ordinal sipariş detayı failure'ından çıkarılan model
otoritesi ve privacy projection sözleşmesini bağlayıcı hale getirir:

1. **Model-authored typed alanı legacy phrase lexicon veto edemez.** Kullanıcı önceki
   listenin ilk siparişinin kime ait olduğunu sorduğunda aynı model objective içinde
   müşteri/sahip bilgisini doğru anlamış ve atomic plan hedefinde de korumuş; eski
   `_explicit_repeat_projection_fields` sözlüğü yalnız bilinen kelimeleri aradığı için
   `customer_name` alanını sonradan silmiştir. Bu, model hatası değil deterministic
   authority inversion'dır. Privacy-gated typed alanlar artık bu phrase filtresinden
   geçirilmez; yeni eş anlamlı kelime eklenerek semptom yamanmaz.
2. **Özel alan görünürlüğü ayrı typed model sözleşmesidir.** Model interpretation'ındaki
   ve plan evidence'ındaki customer/address/phone/email/tracking/package/claim alanları
   execution öncesinde aynı exact model tarafından yalnız `visible_requested` veya
   `internal_only` olarak sınıflandırılır. `expected_evidence` tek başına PII gösterme
   yetkisi vermez; modelin fazla project ettiği alan `internal_only` ile çıkarılır,
   açıkça istediği fakat interpretation'ın düşürdüğü alan `visible_requested` ile geri
   eklenir. Her alan için karar yoksa hiçbir tool çalışmadan fail-closed clarification
   üretilir.
3. **Text-guarded model şemayı gerçekten görmelidir.** Native structured-output olmayan
   provider yolunda `response_schema` yalnız Python metoduna taşınıp prompt'tan saklanamaz.
   Provider adapter artık kapalı JSON schema'yı authoritative guarded contract olarak
   aynı modele iletir; required/enum/additionalProperties kuralları provider özelliğinden
   bağımsız uygulama sözleşmesidir.
4. **Focused kanıt ürün kabulünün yerine geçmez.** R162 karmaşık array sözleşmesinde,
   R163 ise schema'nın text modele hiç gösterilmemesi nedeniyle güvenli biçimde durmuştur.
   R164'ün ilk kritik denemesi iki 503 sonrası model-scope 429 almış; cooldown sonrası
   retry doğru tool'u çalıştırsa da legacy phrase veto yüzünden müşteriyi yine gizlemiştir.
   Phrase otoritesi kaldırıldıktan sonraki fresh R165; gerçek offscreen `AITab` üzerinde
   `orders.query` ile beşli sıralı seçim kurmuş, doğal ordinal follow-up'ta
   `orders.full_context` ile exact ilk kaydı seçmiş ve görünür cevapta müşteri, sipariş
   numarası, ürün, kargo ve takip alanlarını birlikte göstermiştir. Exact
   `gemma-4-31b-it`, fallback kapalı, model-authored semantic output doğrulanmış;
   acceptance `problems=[]` ile passed olmuştur. Artifact:
   `AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r165-gemma4-model-authority-privacy-focused-2026-07-30.json`.

Bu karar sonrası güncel regresyon: Orders agent runtime `281 passed / 1 skipped`, provider
adapter `35 passed`, AI pipeline `296 passed`, Orders domain `82 passed`. R165 yalnız bu
failure sınıfının focused kapanışıdır; fresh tam organik cloud kampanyası sıfırdan geçmeden
Orders `completed` sayılamaz.

2026-07-31 Karar 85, R170'te görülen “hazır kuyruk boşsa sevkiyatı henüz
tamamlanmamış siparişleri durumlarına göre özetle” failure'ından çıkan kapsam ve cevap
kanıtı sözleşmesini bağlayıcı hale getirir:

1. **Terminal olmayan fulfillment kapsamı first-class typed semantiktir.** Modelin
   `status_scope` sözleşmesi artık `nonfinal` değerini taşıyabilir. Bu kapsam
   `broad_analysis` olsa bile global tüm-sipariş count/status/revenue/product boyutlarına
   genişletilemez; yalnız `orders.nonfinal_count` ve
   `orders.nonfinal_status_distribution` metric gereksinimleri derlenir. Model yanlışlıkla
   `orders.summary` seçerse plan execute edilmeden metric coverage verifier tarafından
   reddedilir ve aynı modelden scoped atomic plan onarımı istenir.
2. **“Final” sınırı AI içinde yeniden tanımlanmaz.** Delivered/Cancelled/Returned/
   UnDelivered/UnDeliveredAndReturned/UnSupplied terminal seti Orders domaininin tek
   canonical `ORDER_FINAL_STATUS_CODES` sabitidir; manuel refresh pipeline'ı,
   `list_nonfinal_orders` ve yeni `summarize_nonfinal_orders` aynı sınırı kullanır. AI
   yalnız ince `orders.nonfinal_summary` şema/policy sarmalayıcısını sunar. Sonuç toplam,
   exhaustive status dağılımı, source revision/hash ve kapsam kanıtını taşır; business
   filtreleme AI katmanına kopyalanmaz.
3. **Negatif operasyon iddiası phrase filtresiyle sonradan kesilmez.** R171-R173'te model
   count/status cevabı ilk projection doğrulamasını geçtiği halde eski satır-tabanlı
   clearance filtresi aynı satırdaki kanıtsız “genel bekleyen iş yok” ek hükmü nedeniyle
   bütün model cevabını silmiş ve deterministic projection'a düşürmüştür. Bu authority
   inversion kaldırılmıştır: return/risk/global-pending/fulfillment clearance iddiaları
   artık semantic response verifier'da ilgili authoritative operation sonucunun gerçekten
   gözlenip gözlenmediği ve sayının sıfır mı pozitif mi olduğu üzerinden adjudicate edilir.
   Exact `orders.full_context` içindeki açık `returns=[]`, mağaza genelindeki `returns.query`
   ile karıştırılmaz; risk/iade pozitifken “yok” iddiası contradiction, kanıt yokken
   unsupported sayılır. Reddedilen model cevabı aynı modele bounded evidence repair olarak
   döner; postprocessor modelin yerine business cevabı yazmaz.
4. **Görünür doğru cevap tek başına model kabulü değildir.** R171 ve R172 doğru scoped
   kullanıcı cevabı göstermiş fakat `final_response_source=deterministic_verified_projection`
   olduğu için kabul edilmemiştir. Instrumented R173 hangi katmanın cevabı değiştirdiğini
   hash-safe `postprocessor_events` ile kanıtlamıştır. Fresh R174 gerçek offscreen source-app
   yolunda exact `gemini-3.1-flash-lite`, fallback kapalı biçimde yalnız
   `orders.nonfinal_summary` çalıştırmış; ilk adayın `unsupported_global_pending_clearance`
   hükmü semantic verifier'da reddedilmiş ve aynı modelin grounded repair'i “7 sipariş,
   Shipped 7” olarak `verified_model_repair` kaynağıyla kabul edilmiştir. Artifact:
   `AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r174-gemini31lite-nonfinal-model-acceptance-2026-07-31.json`;
   acceptance `problems=[]` ve `passed`.

Bu karar belirli kullanıcı cümlesine özel router/tool eklenmesine izin vermez. Yeni
kapsamlar typed semantic dimension, domain-owned canonical aggregate, metric coverage ve
claim-to-evidence verifier zinciriyle çözülür. Güncel geniş regresyon: Orders agent runtime
`286 passed / 300 live-provider skipped / 27 subtests passed`; AI pipeline `296 passed / 35
subtests passed`; Orders domain `131 passed / 7 subtests passed`; provider adapter + operation
catalog + operation contracts `49 passed`. R174 yalnız bu failure sınıfının focused kapanışıdır;
fresh 50+ adaptif cloud kampanyası sıfırdan geçmeden Orders tamamlanmış sayılmaz.

2026-07-30 güncel secret-safe OpenRouter read-only auditinde `/api/v1/key`
`limit=1`, `usage=0.188833047`, `limit_remaining=0.811166953` ve
`is_free_tier=true`; ayrı `/api/v1/credits` ise `total_credits=0`,
`total_usage=0.199412247` döndürmüştür. Dolayısıyla OpenRouter için 1 USD key limiti
dolmuş değildir; kalan 0.811166953 değeri satın alınmış harcanabilir bakiye değil,
anahtarın harcama tavanındaki boşluktur. Uzun paid planner/synthesis çağrılarının 402
alması billing credit yokluğudur; bu durum free-tier 429 veya key limit exhaustion diye
raporlanamaz.

Son geniş regresyon: Orders domain `131 passed / 7 subtests passed`; Orders agent runtime
`286 passed / 300 live-provider skipped / 27 subtests passed`; provider adapter + operation
catalog + operation contracts `49 passed`; AI pipeline `296 passed / 35 subtests passed`.
Bu broad-analysis, R161 ordinal privacy-projection ve R170 nonfinal scope/clearance failure
sınıflarının focused regresyonlarını kapatır.
R146 büyük model timeout'u, R151 Gemini model-scope quota, OpenRouter provider kabulü,
fresh tam organik uzun kampanya, Stage action/read-back, web/Excel zinciri ve Faz 9 UI
kapısı açık kalır; Orders tamamlanmış değildir.

2026-08-01 Karar 86, ürün satırı adedi ile serbest metindeki uzun sayıların semantic
rolünü first-class typed sınır haline getirir:

1. **`quantity`, sipariş/popülasyon `count` değildir.** Kullanıcı exact bir siparişin
   ürününü ve adedini istediğinde typed projection `item + quantity` olur; plan
   `orders.full_context` ile exact kaydı okur. Ürün adındaki "20 Adet" gibi bir sayı,
   satırın authoritative `quantity` değerinin yerine geçemez. Cevap verifier'ı ürün
   adıyla birlikte açıkça etiketlenmiş adedi, kargoyu ve takip numarasını ayrı kanıtlar
   olarak doğrular. Fresh R190 gerçek offscreen source-app üzerinde exact
   `gemini-3.1-flash-lite`, fallback kapalı biçimde ürün ve `Adet: 2` cevabını
   `verified_model_repair` kaynağıyla üretmiş; acceptance `problems=[]` ile geçmiştir.
   Artifact:
   `AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r190-gemini31lite-quantity-model-acceptance-2026-08-01.json`.
2. **Metindeki sayı biçimi tek başına record identity yetkisi vermez.** Aynı uzun sayı
   order id, tutar, oran, adet, tarih veya timestamp olabilir. Prefix'li kimlik ya da
   açık sipariş-numarası bağlamı exact record rolünü korur; decimal/grouped para
   değerleri, currency/tutar/ciro/rakam, oran/yüzde/adet ve tarih/timestamp bağlamları
   record id çıkarımını engeller. Model `exact_ids + detail` üretse bile mesajda gerçek
   bir id yoksa semantic contract önceki typed scope'u korur veya scalar population
   metriğini `all_matching` kapsamına alır; hayali exact selection kurulmaz.
3. **Yanlış numeric-role planı execute edilmeden reddedilir.** Aggregate amount isteği
   `orders.revenue_total` metric requirement'ı taşır. Model "bu fiyattaki siparişi ara"
   diyerek `orders.query` seçerse metric coverage verifier planı reddeder ve aynı modelden
   bounded repair ister. Runtime bu aşamada modelin yerine business plan yazmaz.
4. **Kullanıcıya gösterilen hata gerçek sahip katmanı söylemelidir.** Dependency binding,
   schema uyuşmazlığı, account scope ve typed selection eksikliği aynı genel mesaj altında
   gizlenemez. Failure observation reason-code ve argument problem kanıtını korur; modelin
   yanlış replanning yapmasına yol açan sahte "dependency" teşhisi kabul edilmez.

R191 organik cloud kampanyasının dördüncü turunda `502518.01` tutarının sipariş kimliği
sayılmasıyla `orders.query` planına sapıldığı için kampanya doğru biçimde durdurulmuştur.
Karar 86 sonrasındaki fresh R192'de gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite` ve fallback kapalı koşulda ilk turda `502.518,01 TRY` cirosunu,
ikinci turda literal `502518.01` takibine karşı yalnız `orders.revenue_total` kullanarak
`MDB / TRENDYOL / production / TRY` provenance'ını model-authored
`verified_model_candidate` cevabıyla vermiştir. Sipariş araması yapılmamış, acceptance
`problems=[]` ile `passed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r192-gemini31lite-literal-revenue-provenance-2026-08-01.json`.
Güncel regresyon Orders agent runtime `297 passed / 1 live-provider skipped`, typed session
state `24 passed`; ilgili kaynaklar ayrıca `py_compile` kontrolünü geçmiştir. R190 ve R192
yalnız ilgili failure sınıflarının focused kapanışıdır. R191'in ilk üç turu yeni source
fingerprint için devredilemez; fresh 50+ adaptif cloud kampanyası sıfırdan başlamadan Orders
tamamlanmış sayılmaz.

2026-08-01 Karar 87, modelin doğru veriyi bulmasının tek başına yeterli olmadığını;
kullanıcının istediği projection sınırını da koruması gerektiğini first-class semantic
sözleşme yapar:

1. **Açıkça istenen alanlar cevap için üst sınırdır.** Kullanıcı yalnız toplam ve durum
   dağılımını isterse modelin `broad_analysis` demesi ciro, ortalama tutar, ürün yoğunluğu
   veya risk boyutlarını ekleme yetkisi vermez. Runtime bu dar isteği
   `focused_analysis` olarak normalize eder; plan, verifier, repair ve fallback aynı
   `requested_fields` sınırına tabidir. Bu kural belirli cümle kalıbına değil typed
   aggregate dimension kümesine uygulanır.
2. **Gerçek genel analiz daraltılmaz.** Kullanıcı en az üç bağımsız aggregate boyutu veya
   açık uçlu genel analiz isterse mevcut broad-analysis sözleşmesi korunur. Durum dağılımı
   ise doğası gereği bucket adetlerini içerir; kullanıcı ayrıca “adet” demese bile `status`
   projection'ı authoritative `count` kanıtını taşır. Record-detail `item`, population
   analizinde canonical `item_sales_rows` boyutuna çevrilir.
3. **Oran ayrı ve doğrulanabilir bir metriktir.** “Teslim edilenlerin toplam içindeki payı”
   gibi sorular `ratio + status + count` odaklı sözleşmesine dönüşür. Verifier hedef durumun
   payını diğer durumların bütün dökümünü zorlamadan doğrular; cevap numerator, denominator
   ve yüzdeyi birlikte göstermeden kabul edilmez. Deterministic fallback de yalnız bu üç
   kanıtı sunar ve istenmeyen ciro/ürün alanlarına genişlemez.
4. **Canlı testte ilk kritik sapmada durma kuralı korunur.** R193, ilk dört doğru turdan
   sonra teslim oranı sorusunda sayısal sonuç doğru olsa da ciro/ürün boyutlarına genişlediği
   için beşinci turda `failed` kapatılmıştır. R194, “toplam + durum dağılımı” sorusunu yine
   broad ciro/ürün analizine çevirdiği için ilk turda durdurulmuştur. Bu başarısızlıklar tek
   prompt yaması değil genel projection üst-sınırı ve focused ratio sözleşmesiyle giderildi.

Karar 87 sonrasındaki fresh R195 gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite` ve fallback kapalı koşulda iki adaptif turu geçmiştir. İlk cevap
yalnız `3112` toplam ve dört authoritative durum satırını; ikinci cevap yalnız
`2957 / 3112 = %95.02` teslim oranını vermiştir. Her iki cevap da model-authored
`verified_model_candidate`, kaynak fingerprint'i güncel ve acceptance `problems=[]` /
`passed` durumundadır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r195-gemini31lite-focused-status-ratio-2026-08-01.json`.
Güncel birleşik regresyon `324 passed / 314 live-provider skipped / 34 subtests passed`;
focused projection regresyonu ayrıca `5 passed`. R195 yalnız bu failure sınıfını kapatır;
R193/R194 turları yeni kaynak fingerprint'ine devredilemez. Fresh 50+ adaptif cloud
kampanyası birinci turdan başlamadan Orders tamamlanmış sayılmaz.

2026-08-01 Karar 88, oran analizini tek bir status bucket ile sınırlamaz; kullanıcı tarafından
seçilmiş bir status kümesini first-class typed operand yapar:

1. **Birleşik status hesabı atomic ve doğrulanabilirdir.** Semantic contract
   `status_members` içinde bir veya daha fazla canonical Orders lifecycle durumunu taşır.
   Runtime authoritative status bucket'larını ayrı ayrı okur; numerator bu üyelerin toplamı,
   denominator authoritative toplam sipariş sayısı ve yüzde bunların türevidir. Modelin serbest
   aritmetiğine güvenilmez; türetilmiş sayıların kendisi de grounding allow-list'e yalnız bu
   sözleşme üzerinden girer.
2. **Kullanıcının “hesabı göster” isteği eksiksiz projection'dır.** Birleşik oran cevabı her
   status üyesini ve kendi adedini, toplam numerator'u, population denominator'ını ve yüzdeyi
   birlikte göstermeden kabul edilmez. Türkçe doğal durum adları ile canonical API adları aynı
   statüyü gösterebilir; verifier ikisini typed alias tablosuyla eşler. “Toplam 45 sipariş” gibi
   seçili küme ara toplamı, population toplamı 3112 iddiasıyla karıştırılmaz; denominator ayrıca
   zorunlu kalır.
3. **Orders lifecycle terimi entity'yi kilitler.** `UnDeliveredAndReturned` anlamındaki “iade
   dönen” ifadesi bir return-claim isteği değildir. Açık Orders status üyeleri varsa entity
   canonical `order`, kaynak `local_business_data` olur; modelin `return_claim` veya
   `unspecified` üretmesi normalize edilir. Böylece `orders.summary` yerine yanlışlıkla
   `returns.summary` çalıştırılamaz.

Fresh R196 organik kampanyası üçüncü turda “teslim edilemeyen + iade dönen” birleşik hesabında
status-set sözleşmesi bulunmadığı için doğru biçimde `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r196-gemini31lite-organic-50-2026-08-01.json`.
Karar 88 sonrasındaki fresh R197, gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite` ve fallback kapalı koşulda önce 3112 toplam/dört durum bucket'ını,
ardından model-authored `verified_model_candidate` cevabıyla `44 + 1 = 45` ve
`45 / 3112 = %1.45` hesabını vermiştir. Yalnız `orders.summary` kullanılmış, return-claim
aracına sapılmamış ve acceptance `problems=[]` / `passed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r197-gemini31lite-combined-status-ratio-2026-08-01.json`.
Güncel birleşik regresyon `325 passed / 315 live-provider skipped / 34 subtests passed`.
R197 yalnız bu failure sınıfını kapatır; fresh 50+ adaptif cloud kampanyası yine birinci turdan
başlamadan Orders tamamlanmış sayılmaz.

2026-08-01 Karar 89, aggregate anafor ile record-detail anaforunu aynı projection authority
olarak yorumlamayı yasaklar. “Bu üç grup” ifadesi status bucket kümesine işaret eder; cümlede
“iade dönen” geçmesi `returns` record projection'ı istemek değildir. Status-ratio sözleşmesi
yorumlamanın son kapısında `count + status + ratio` ve açık scope/store/date alanlarıyla
sınırlandırılır; önceki/later lexical retention kuralları `returns`, item, cargo veya başka
kayıt detayını yeniden ekleyemez.

Fresh R198 organik kampanyası üçüncü turda üç status hesabını görünürde doğru üretmiş olsa da
yanlış eklenen `returns` projection'ı için evidence bulunamadığından
`deterministic_projection_failed` olmuş ve kampanya doğru biçimde durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r198-gemini31lite-organic-50-2026-08-01.json`.
Karar 89 sonrasındaki fresh R199 gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite`, fallback kapalı koşulda `Cancelled 110 +
UnDeliveredAndReturned 44 + UnDelivered 1 = 155`, denominator `3112` ve `%4.98`
sonucunu model-authored `verified_model_candidate` olarak vermiş; acceptance
`problems=[]` / `passed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r199-gemini31lite-three-status-ratio-2026-08-01.json`.
Güncel birleşik regresyon `326 passed / 316 live-provider skipped / 34 subtests passed`.
Fresh 50+ adaptif cloud kampanyası kaynak değişikliği nedeniyle yine birinci turdan başlar;
Orders tamamlanmış sayılmaz.

2026-08-01 Karar 90, seçili bir kaydın alanını sonraki turda population aggregate'ına
dönüştürmeyi first-class typed dependency olarak tanımlar. “Üçüncü siparişteki ürün ne?”
ardından “bu üründen tüm geçmişte kaç adet satıldı?” sorusu tek sipariş detayını yeniden
okumak değildir; seçili sipariş yalnız ürün kimliğinin kaynağı, ikinci adım ise bütün eşleşen
sipariş satırlarının bağımsız aggregate'ıdır:

1. **Kimlik kaynağı ile aggregate kapsamı ayrıdır.** `orders.product_public_identities`
   yalnız complete typed selection'daki exact sipariş numarasını kullanır. Modelin farklı
   sipariş numarası yazması reddedilir veya authoritative selection ile değiştirilir.
   Ardından `orders.item_sales_summary`, ilk adımın `tool_result.product_identities`
   çıktısına typed dependency ile bağlanır; `record_scope=all_matching` iken
   `order_numbers` ikinci adıma otomatik bağlanamaz.
2. **Population daraltma istisnası yalnız kanıtlı köprü içindir.** Semantic verifier exact
   ID'yi ancak kaynak operation `orders.product_public_identities` ise, hedef ID active
   selection ile birebir eşleşiyorsa ve downstream sales step doğru dependency path'ini
   taşıyorsa kabul eder. Bu koşulların dışında eski/stale exact ID ile population sorgusu
   `typed_all_matching_scope_narrowed_by_exact_ids` olarak fail-closed reddedilir.
3. **Tarihsel ürün adları tek satır olmak zorunda değildir.** Aynı public ürün/barcode eski
   kayıtlarında farklı ad, SKU veya catalog alias'larıyla birden fazla canonical satış satırı
   üretebilir. Visible answer seçili identity'nin ürün adını taşır; authoritative toplam ise
   bütün eşleşen satırların quantity toplamıdır. Verifier `identity_filter_count=1`, exact
   dependency binding ve `sum(rows.quantity) == total_quantity` kanıtları birlikte yoksa
   cevabı kabul etmez. Böylece model doğru görünen ama bağsız veya tutarsız bir sayı yazamaz.

Bu karar tek cümleye özel bir tool/router yaması değildir; herhangi bir seçili record alanının
sonraki population analizinde güvenli bir operand olabilmesi için `selection -> typed identity
operation -> dependent aggregate -> evidence projection` composition kalıbıdır.

Fresh R200 organik kampanyası onuncu turda bu genel kabiliyet bulunmadığı için seçili ürünün
tüm geçmiş satış adedini çıkaramamış ve ilk kritik sapmada durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r200-gemini31lite-organic-50-2026-08-01.json`.
R201'de model doğru iki adımı kurmuş, fakat semantic verifier identity kaynak adımındaki exact
selection'ı population daraltması sanarak reddetmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r201-gemini31lite-contextual-item-sales-2026-08-01.json`.
R202'de iki adım da gerçekten çalışmış; kısa CLI özeti yalnız ilk tool'u gösterse de full state,
runtime'ın active `order_numbers` değerini aggregate adıma da otomatik bağladığını ve sonucu
seçili siparişteki `1` adede daralttığını kanıtlamıştır. Artifact'ın eski `final_notes` özeti bu
noktada eksiktir; authoritative inceleme artifact içindeki completed step/result state'idir.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r202-gemini31lite-contextual-item-sales-2026-08-01.json`.
R203'te doğru bağımlılık ve tüm-geçmiş kapsamı kurulmuş, repository aynı barcode'a ait iki
tarihsel alias satırını `80 + 2 = 82` üretmiş; response verifier'ın eski `len(rows)==1`
varsayımı doğru kanıtı reddetmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r203-gemini31lite-contextual-item-sales-2026-08-01.json`.

Karar 90 sonrasındaki fresh R204 gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite` ve fallback kapalı koşulda üç adaptif turu geçmiştir: son beş sipariş
listelenmiş, üçüncü siparişten ürün/satır adedi `1` alınmış, ardından model-led iki atomic
adım `orders.product_public_identities -> orders.item_sales_summary` olarak çalışmıştır.
Aggregate adımında `order_numbers` yoktur; `identity_filter_count=1`, dependency binding exact,
iki alias satırı `80 + 2 = 82` ve görünür cevap seçili ürün adıyla “tüm sipariş geçmişinde
82 adet” sonucunu vermiştir. Gerçek/final model `gemini-3.1-flash-lite`, fallback yok,
`final_response_source=verified_model_candidate`, acceptance `problems=[] / passed`.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r204-gemini31lite-contextual-item-sales-2026-08-01.json`.
Değişiklik sonrası geniş regression invocation'ı `415 tests / OK / 1 skipped`; focused
köprü testleri yanlış active ID, stale population daraltması, aggregate exact-ID yeniden
bağlanması, dependency eksikliği ve satır/toplam tutarsızlığını ayrıca fail-closed doğrular.
R204 yalnız bu failure sınıfını kapatır. Fresh 50+ adaptif cloud kampanyası kaynak fingerprint'i
değiştiği için yine birinci turdan başlamadan Orders tamamlanmış sayılmaz.

2026-08-01 Karar 91, tek bir kullanıcı hedefindeki product-report boyutu ile Orders population
metriklerini birbirini dışlayan intent'ler saymayı yasaklar. “Toplam kaç sipariş, durum dağılımı,
toplam ciro ve en çok satan ilk 5 ürün” dört ayrı kanıt boyutuna sahip tek bir GoalPlan'dır:

1. **Product report başka açık metrikleri silemez.** `item_sales_rows` canonical rapor boyutu
   olarak korunurken kullanıcı açıkça population toplamını, status distribution'ı veya toplam
   ciroyu da istediyse projection sırasıyla `count`, `status`, `amount + currency` boyutlarını
   birlikte taşır. Modelin eksik `requested_fields` cevabı explicit kullanıcı boyutlarını
   düşüremez.
2. **Satır metriği ile population metriği ayrılır.** Ürün raporundaki “sipariş sayısı” ve
   “brüt tutar” her ürün satırının sütunlarıdır; tek başına `orders.total_count` veya
   `orders.revenue_total` istemez. Population count yalnız “toplam kaç sipariş / toplam sipariş”,
   population revenue ise açık “ciro / gelir / revenue / toplam tutar” authority'siyle eklenir.
3. **List shape order-row anlamına gelmez.** Semantic metric `list` olsa bile typed requirement
   `orders.item_sales_report_snapshot` ve projection `item_sales_rows` ise status/amount alanları
   sipariş satırı sütunları değil population companion metrikleridir. Response verifier bu
   durumda `order_row_evidence_missing` üretmez; total, status, revenue ve bütün istenen product
   satırlarını kendi authoritative kanıtlarıyla ayrı ayrı doğrular.

Fresh R205 50+ organik kampanyası ilk turda bu sözleşme eksikliği yüzünden doğru biçimde
`failed` kapatılmıştır. Runtime `orders.summary + orders.item_sales_report` çalıştırıp bütün
kanıtları elde ettiği halde interpretation `count/amount` boyutlarını silmiş; visible cevap
toplam sipariş, status dağılımı ve ciroyu vermeyip yalnız ürünleri göstermiş ve
`deterministic_projection_failed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r205-gemini31lite-organic-50-2026-08-01.json`.

Karar 91 sonrasındaki fresh R206 gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite` ve model fallback kapalı koşulda aynı doğal hedefi geçmiştir. Typed
contract `item_sales_rows + count + status + amount + currency` ve dört metric requirement
üretmiş; model-authored plan `orders.count`, `orders.status_counts`, `orders.revenue_total`,
`orders.item_sales_report` atomic adımlarını `period=all` ile compose etmiştir. Visible cevap
`3112` toplamı, dört status bucket'ını, `502518.01 TRY` tahmini ciroyu ve beş product satırının
ad/adet/sipariş/brüt tutarını eksiksiz taşımıştır. İlk model answer/repair beş exact report
satırını projection contract'a uygun gösteremediği için fail-closed reddedilmiş, final cevap
authoritative kanıttan `deterministic_verified_projection` olarak kurulmuştur; plan/model
invocation gerçek Gemini'dir, provider/model fallback yoktur. Acceptance `problems=[] / passed`.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r206-gemini31lite-composite-overview-2026-08-01.json`.
Değişiklik sonrası geniş regression invocation'ı `417 tests / OK / 1 skipped`.
R206 yalnız R205 failure sınıfını kapatır; final synthesis source'un deterministic projection
olması uzun kampanyalarda ayrıca kalite sinyali olarak izlenir. Fresh 50+ adaptif cloud
kampanyası yine yeni source fingerprint ile birinci turdan başlar; Orders tamamlanmış sayılmaz.

2026-08-01 Karar 92, `existing_observations_only` iznini “unchecked conversation” anlamına
gelmekten çıkarır. Kullanıcı yeni sorgu/tool çalıştırmayı yasaklayıp önceki authoritative
kanıttan bir business metric, oran veya analiz istiyorsa:

1. **İzin sınırı semantic contract'ı silmez.** Turn model-authored `inspect/data_read` typed
   contract olarak kalır; `operation_policy=existing_observations_only` yeni operation
   planlanmasını engeller. Scope-only geçmiş açıklaması gibi hesap gerektirmeyen sorular eski
   güvenli `explain/conversation` yolunu korur.
2. **Eski kanıt yeni tool gibi gösterilmez.** Prior completed observations yalnız operand/evidence
   kaynağıdır. Bu turdaki `tool_calls` ve direct tool sonuçları boş kalır; conversation runtime
   eski completed step adlarını “şimdi çalıştı” şeklinde raporlamaz.
3. **Türetilmiş sayı deterministic ve verified'dır.** Örneğin teslim oranı prior authoritative
   `Delivered=2957` ve `total=3112` değerlerinden hesaplanır; visible cevap numerator,
   denominator ve iki ondalık yüzdeyi taşımazsa verifier reddeder. Modelin serbest aritmetiği
   final authority değildir.
4. **Türkçe numeric role ile account scope ayrılır.** `hesapla` ve “hesabı da göster” matematik
   dilidir; `scope` projection açmaz. Account scope yalnız “hangi hesap”, “mağaza hesabı”,
   “hesapta/hesabım” gibi gerçek account/store bağlamıyla açılır.

Fresh R207 50+ organik kampanyası ikinci turda ilk kritik sapmada durmuştur. İlk tur broad
Orders cevabı doğruyken ikinci tur “yeni sorgu çalıştırmadan” prior `2957 / 3112` oranını
istemiş; runtime typed contract'ı boşaltıp free-form conversation'a düşmüş ve görünür cevap
iki ondalıkta yanlış `%95.01` vermiştir (`2957 / 3112 * 100 = 95.0193`, doğru yuvarlama
`%95.02`). Kaynak bu gözlemden hemen sonra düzeltildiği için çalışan acceptance prosesi
fingerprint-stale olmuş ve finalization komutunu reddetmiştir; artifact `open` kalsa da turn 2
visible failure ve runtime provenance immutable kanıttır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r207-gemini31lite-organic-50-2026-08-01.json`.

İlk focused R208 aynı iki turu ve sıfır-tool oran yolunu geçmiştir; fakat sonrasında ortak
conversation-runtime'ın eski step adlarını current tool gibi raporlaması ve Türkçedeki
“hesabı göster” ayrımı düzeltildiği için R208 en son fingerprint'in kapanış kanıtı değildir.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r208-gemini31lite-existing-observation-ratio-2026-08-01.json`.

En son source fingerprint ile fresh R209 gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite` ve fallback kapalı koşulda iki adaptif turu geçmiştir. İlk tur
`orders.summary` ile `3112` toplam ve dört status bucket'ını üretmiş; ikinci tur
model-authored `metric=ratio / status_scope=delivered / existing_observations_only`
sözleşmesiyle hiçbir yeni tool/direct tool/API çalıştırmadan `2957 / 3112 = %95.02`
cevabını vermiştir. Spurious account scope yoktur; acceptance `problems=[] / passed`.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r209-gemini31lite-existing-observation-ratio-2026-08-01.json`.
Ana Orders/state/conversation/pipeline birleşik regression invocation'ı
`430 tests / OK / 1 skipped`. R209 yalnız R207 failure sınıfını kapatır; fresh 50+ adaptif
cloud kampanyası yine birinci turdan başlamadan Orders tamamlanmış sayılmaz.

2026-08-01 Karar 93, seçili sipariş satırından aynı ürünün tarihsel satışına geçişte
**satılan birim adedi** ile **ürünün yer aldığı benzersiz sipariş sayısını** iki ayrı typed
metric olarak tanımlar:

1. `item_sales_quantity / item_quantity_total`, aynı public product identity için dönem
   boyunca satılan toplam birim adedidir. Seçili siparişteki line quantity veya sipariş sayısı
   değildir.
2. `item_sales_order_count / item_order_count`, aynı public product identity'nin yer aldığı
   benzersiz sipariş sayısıdır. Genel Orders population count'u, satılan birim adedi veya
   product alias satırlarının saf toplamı değildir.
3. Her iki metric de aynı güvenilir composition'ı kullanır: exact typed order selection ->
   `orders.product_public_identities` -> dependency-bound `orders.item_sales_summary`. Exact
   order kimliği yalnız product identity çıkarmak içindir; all-history aggregate'e
   `order_numbers` filtresi olarak taşınmaz.
4. Filtreli farklı sipariş sayısının sahibi Orders canonical repository'dir. Repository bütün
   eşleşen public identity alias'larında `(api_account_id, order_number)` kümesi tutar;
   `order_count` filtreli result scope'u, `matched_order_count` benzersiz eşleşmeyi,
   `population_order_count` ise karşılaştırma için bütün uygun population'ı taşır. Aynı ürünün
   iki alias'ı aynı siparişte bulunursa sipariş bir kez sayılır.
5. Response verifier exact identity dependency'sini, `identity_filter_count=1` kanıtını,
   `order_count == matched_order_count` tutarlılığını ve görünür cevapta exact product name ile
   etiketlenmiş farklı sipariş sayısını zorunlu tutar. `2963` gibi genel population sayısı
   filtreli ürün cevabıymış gibi geçemez.
6. Dil canonicalization'ı cümle/clause sınırını aşamaz. “Tüm geçmişte kaç adet satılmış? Bu
   siparişteki 2 adedi değil” quantity metric'idir; ikinci cümledeki `sipariş` kelimesi ilk
   cümlenin `toplam/kaç` ifadesiyle birleştirilip distinct-order intent üretilemez. “Bu 8 adet
   kaç farklı siparişte satılmış?” ise distinct-order metric'idir.

Fresh R210 50+ organik kampanyası turn 7'de ilk kritik sapmada `failed` kapatılmıştır. Model
doğru iki atomic operation'ı ve dependency'yi önermesine rağmen typed contract hedefi yanlış
`orders.total_count` olarak bağlamış, compiler doğru planı reddetmiştir. Aynı kanıtta filtreli
`orders.item_sales_summary.order_count=2963` değerinin de genel population sayısı olduğu
görülmüştür. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r210-gemini31lite-organic-50-2026-08-01.json`.

İlk focused R211 yeni metric'i doğrularken turn 3'te clause sınırı kusurunu açığa çıkarmış ve
doğru biçimde `failed` kapatılmıştır: “toplam kaç adet” sorusuna `8 adet` yerine `4 farklı
sipariş` cevabı verilmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r211-gemini31lite-contextual-item-order-count-2026-08-01.json`.

Clause-bound düzeltme ve repository unique-set hesabı sonrasındaki fresh R212 gerçek offscreen
`AITab`, exact `gemini-3.1-flash-lite`, fallback kapalı koşulda dört adaptif turu geçmiştir:
son 5 order selection -> dördüncü order detail -> aynı ürünün all-history `8 adet` satışı ->
aynı ürünün `4 farklı sipariş` sayısı. Final cevap genel population `2963` ile birim adedi `8`i
karıştırmamış; requested/actual model aynı kalmış, fallback kullanılmamış ve acceptance
`problems=[] / passed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r212-gemini31lite-contextual-item-order-count-2026-08-01.json`.
Ana Orders/state/conversation/pipeline birleşik regression invocation'ı
`434 tests / OK / 1 skipped`. R212 yalnız R210/R211 failure sınıfını kapatır; fresh 50+ adaptif
cloud kampanyası en baştan çalışmadan Orders tamamlanmış sayılmaz.

2026-08-01 Karar 94, seçili ürünün tarihsel **brüt satış tutarını** genel mağaza cirosundan
ayırır. `item_sales_amount / item_gross_amount`, exact contextual public product identity için
all-history `orders.item_sales_summary` sonucudur; `orders.revenue_total` değildir.

1. Orders canonical repository eşleşen bütün product alias satırlarının `gross_amount`
   değerlerini para birimine göre toplar. `gross_amount_by_currency` her currency toplamını,
   tek currency varsa `total_gross_amount + currency` convenience alanlarını taşır.
2. Aynı exact selection -> public identity -> dependency-bound item aggregate zinciri kullanılır;
   seçili order aggregate population filtresi yapılmaz.
3. Response verifier `identity_filter_count=1`, exact dependency, alias satırlarının currency
   bazında toplamıyla top-level toplamın eşitliği, exact product name ve görünür amount/currency
   çiftlerini zorunlu tutar. Genel store revenue ürün tutarıymış gibi geçemez.

Fresh R213 50+ organik kampanyası ilk sekiz turu geçtikten sonra turn 9'da ilk kritik sapmada
`failed` kapatılmıştır. “Bu ürünün tüm sipariş geçmişi boyunca toplam brüt satış tutarı” hedefi
model tarafından doğru `product_public_identities -> item_sales_summary` planlanmış; fakat typed
contract bunu yanlış `orders.total_count + orders.revenue_total` requirement'larına bağladığı
için compiler doğru planı reddetmiş ve hiçbir tool çalışmadan generic safe-plan failure
dönmüştür. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r213-gemini31lite-organic-50-2026-08-01.json`.

Karar 94 sonrasındaki fresh R214 gerçek offscreen `AITab`, exact
`gemini-3.1-flash-lite`, fallback kapalı koşulda üç adaptif turu geçmiştir: son 5 order selection
-> dördüncü order'ın product detail'i -> aynı product identity'nin all-history gross amount'ı.
Visible cevap exact ürünü ve `1199.94 TRY` toplam brüt satış tutarını taşımış; global
`502518.01 TRY` store revenue kullanılmamış; acceptance `problems=[] / passed` olmuştur.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r214-gemini31lite-contextual-item-gross-2026-08-01.json`.
Ana Orders/state/conversation/pipeline birleşik regression invocation'ı
`436 tests / OK / 1 skipped`. R214 yalnız R213 failure sınıfını kapatır; fresh 50+ adaptif cloud
kampanyası yine birinci turdan başlar.

2026-08-01 Karar 95, doğrulanmış mevcut observation'lardan **yeni türetilmiş sonuç üretmeyi**
Codex-benzeri agent davranışının bağlayıcı parçası yapar. Agent, yeni domain sorgusu gerektirmeyen
bir hesap veya karşılaştırma istendiğinde mevcut sayıları yalnız tekrar edemez; typed state içindeki
kanıtları kullanarak işlemi tamamlamalı, sonucu doğrulamalı ve görünür cevapta operandları, işlemi,
sonucu, birimi ve istenen yuvarlamayı göstermelidir. Bu kabiliyet tek bir "ortalama ciro" cümlesine
özel regex veya cevap şablonuyla değil, yeniden kullanılabilir typed derived-observation/compute
sözleşmesiyle sağlanır.

Fresh R215 50+ organik kampanyası turn 1'de toplam sipariş, durum dağılımı, toplam ciro ve ilk beş
ürün birleşik özetini doğru vermiş; turn 2'de ise "yeni sorgu çalıştırmadan 502518.01 / 3112" hedefini
tamamlamamıştır. Görünür cevap yalnız `3112` ve `502518.01 TRY` kanıtlarını tekrar etmiş, bölme
işlemini ve iki ondalıklı sipariş başına ortalamayı üretmemiştir. Kampanya ilk kritik görünür sapmada
`failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r215-gemini31lite-organic-50-2026-08-01.json`.
Bu failure'ın sahibi provenance ile belirlenmeden dar bir intent/response yaması eklenmez; fresh 50+
kampanyası düzeltme ve focused kanıttan sonra yine birinci turdan başlar. Ana birleştirilmiş regression
baseline'ı son kaynak değişikliğinde `436 tests / OK / 1 skipped` olarak kalır; R215 bu testlerin tek
başına ürün kabulü olmadığını yeniden kanıtlar.

2026-08-01 Karar 96, Karar 95'i tek bir ortalama ciro örneğinden bağımsız, yeniden kullanılabilir
bir **typed hesaplama zinciri** olarak uygular. Model business operandlarını `derived_calculation`
sözleşmesinde seçer; deterministik katman operation, operand sırası, sonuç boyutu, hassasiyet ve
görünür işlem zorunluluğunu doğrular. Authoritative Orders metric referansları ile
`derived.latest` önceki doğrulanmış hesap observation'ını gösterebilir. Kullanıcının mevcut turda
rakamla açıkça verdiği sabit `literal` olabilir; fakat sayı ve varsa para kodu exact mevcut mesajda
bulunmuyorsa sözleşme model repair sonrasında fail-closed kapanır. Literal doğrulaması business
intent veya tool seçmez; yalnız modelin kullanıcıda olmayan sayısal kanıt icat etmesini engeller.

Hesap sonucu model serbest metninden alınmaz. Domainler arası ortak, DB/model/sohbet bilmeyen Core
evaluator `Decimal + ROUND_HALF_UP` ile `add/subtract/multiply/divide/percentage/minimum/maximum`
işlemlerini yapar; division-by-zero, non-finite operand ve aşırı precision reddedilir. Response
verifier yalnız exact operand/result/operator/unit/currency projection'ını kabul eder. Başarılı
sonuç `core.verified_calculation` typed observation'ı olarak hash'li provenance ile kaydedilir;
sonraki tur onu yeni bir formula içinde tekrar kullanabilir. Böylece sistem belirli bir Türkçe
cümleye özel cevap şablonu değil, observation -> verified derived observation composition'ı kazanır.

R216 exact `gemini-3.1-flash-lite` focused koşusunda `502518.01 / 3112 = 161.48 TRY/sipariş` ve dört
ondalıklı `161.4775` sonuçlarını doğru vermiştir; fakat ilk turların human selection metadata'sı
eksik olduğu için artifact `open` kalmış ve passing acceptance sayılmamıştır. Fresh R217 ise yeni
bir gerçek runtime kusurunu açığa çıkarmış ve turn 2'de `failed` kapatılmıştır: “sipariş sorgusu
çalıştırmadan” çekimi explicit no-new-operation policy sınırına bağlanmamış, modelin explicit literal
operandları para birimi provenance'ı taşımamış, runtime gereksiz `orders.summary` planlayıp görünür
hesabı doğrulayamamıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r217-gemini31lite-derived-chain-2026-08-01.json`.

Türkçe izin sınırındaki genel çekim ve typed literal-currency provenance düzeltmesinden sonraki fresh
R218 gerçek offscreen `AITab`, exact `gemini-3.1-flash-lite`, fallback kapalı koşulda üç adaptif turu
geçmiştir: authoritative `3112 + 502518.01 TRY` read -> sıfır yeni tool ile görünür
`502518.01 / 3112 = 161.48 TRY/sipariş` -> persisted `derived.latest` ile açık `2` sabitinin sıfır yeni
tool ile `161.48 / 2 = 80.74 TRY/sipariş` composition'ı. Her sonraki prompt önceki görünür cevap
okunduktan sonra seçilmiş; requested/actual model aynı kalmış; acceptance
`accepted=true / problems=[] / passed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r218-gemini31lite-derived-chain-2026-08-01.json`.
Current birleşik regresyon kanıtı `419 tests / OK / 1 skipped` ve ayrı Orders/catalog/state/web/report
grubu `156 tests / OK` sonucudur. R218 yalnız R215/R217 failure sınıfını kapatır; fresh 50+ adaptif
cloud kampanyası current fingerprint için yine birinci turdan başlar.

2026-08-01 Karar 97, derived percentage ve bozuk formula repair'ini aynı typed arithmetic
sözleşmesinin parçası yapar. Yüzde evaluator'ının görünür `× 100` sabiti bir business observation
değil doğrulanmış operator sabitidir; response verifier operandlar ve sonuç dışında yalnız
`operator=percentage` olduğunda bu exact `100` değerini grounded kabul eder. Başka bir formula veya
cevaptaki `100` bu izinle aklanmaz.

Fresh R219 50+ organik kampanyası turn 1'de çok boyutlu Orders özetini doğru tamamlamış, turn 2'de
ilk kritik sapmada `failed` kapanmıştır. Model-authored formula `Delivered 2957 / 3112 × 100 = 95.02`
olarak authoritative kanıttan doğru çözülmüş; fakat response verifier kendi operator sabitini
`ungrounded_number:100` sayıp kendi deterministic projection'ını reddetmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r219-gemini31lite-organic-50-2026-08-01.json`.

Verifier düzeltmesinden sonraki R220/R221 koşuları model contract varyasyonundaki ikinci ortak açığı
göstermiştir. Model bazen `metric=derived` kararını doğru verirken formula nesnesini eksik bırakmış
veya önceki authoritative sayıyı canonical ref yerine current-message literal gibi yazmıştır.
Genel turn-repair şemasında formula koşullu zorunlu olmadığı için aynı eksik cevap tekrar edilmiş;
eski generic read recovery de explicit “yeni sorgu çalıştırma” sınırını kaybederek yeni plan yoluna
girmiştir. İki koşu da görünür oranı üretemediği için `failed` kapatılmıştır. Artifact'lar:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r220-gemini31lite-derived-percentage-2026-08-01.json`
ve
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r221-gemini31lite-derived-percentage-2026-08-01.json`.

Formula normalization artık exact reason-code üretir (`operator_not_allowed`,
`literal_not_in_current_message`, `status_count_member_missing`, currency/precision ve diğer schema
ihlalleri). Valid derived turn kararı sonrası formula eksik/geçersizse aynı modele yalnız bütün
alanları zorunlu formula schema'sı verilen bir bounded repair yapılır; deterministic katman formula
veya business operand icat etmez. Repair de geçersizse explicit no-new-operation sınırı generic read
veya prepare recovery'sini kapatır ve hiçbir tool planlanmaz.

Fresh R222 gerçek offscreen `AITab`, exact `gemini-3.1-flash-lite`, fallback kapalı koşulda iki
adaptif turu geçmiştir: authoritative `3112` total + dört status count read'i ve sıfır yeni tool ile
görünür `2957 siparis / 3112 siparis × 100 = 95.02 %` projection'ı. Acceptance
`accepted=true / problems=[] / passed`; current regression `423 tests / OK / 1 skipped` ve ayrı
Orders/catalog/state/web/report grubu `156 tests / OK` olmuştur. R222 yalnız R219-R221 failure
sınıfını kapatır; fresh 50+ adaptif cloud kampanyası current fingerprint için yeniden turn 1'den
başlar.

2026-08-01 Karar 98, bağlamsal tek ürün için birden fazla metriğin aynı hedefte istenmesini
**arithmetic değil, canonical operation'ın çoklu projection'ı** olarak bağlar. Fresh R223 organik
50+ kampanyasında ilk dört tur; genel Orders özeti, mevcut observation'lardan yüzde, son beş
sipariş ve listedeki üçüncü siparişin ürün/kargo bağlamını doğru tamamlamıştır. Beşinci turda
kullanıcı aynı ürünün tüm geçmişteki toplam adedini, yer aldığı farklı sipariş sayısını ve brüt
satış tutarını birlikte istemiştir. Model doğru iki adımlı planı kurmuştur:
`orders.product_public_identities -> orders.item_sales_summary`. Buna rağmen semantic verifier,
ilk adımdaki exact sipariş kimliğini downstream ürün analizinin kapsamı sanıp
`typed_all_matching_scope_narrowed_by_exact_ids` ile reddetmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r223-gemini31lite-organic-50-2026-08-01.json`.
Kampanya ilk kritik görünür failure'da durdurulmuş ve `failed` kapatılmıştır.

Yeni invariant'ta exact önceki sipariş yalnız ürün kimliğini güvenli biçimde çözmek için kullanılan
typed identity bridge'dir; downstream `period=all / record_scope=all_matching` ürün satış kapsamını
daraltmaz. Bridge ancak complete active selection exact eşleşiyorsa, model-authored direct planda
downstream `orders.item_sales_summary` adımı gerçekten ilk adıma bağımlıysa ve
`product_identities` typed binding'i kullanıyorsa kabul edilir. Modelin farklı boyutlardaki
`quantity + distinct order count + money` değerlerini uydurma bir formülde toplaması kabul edilmez.
İki veya daha fazla açık bağlamsal ürün metriği tek `summary` sözleşmesinde ayrı requested field'lar
olarak korunur; aynı canonical sonuçtan ürün adı, adet, farklı sipariş sayısı, tutar ve para birimi
ayrı ayrı kanıtlanır. Deterministic fallback de bu alanların tümünü birlikte projekte eder; eksik
olan tek metrik görünür cevabın tamamını fail-closed reddettirir.

Focused/unit kanıtı `425 tests / OK / 1 skipped`; ayrı Orders pipeline, operation contracts,
typed state, catalog, model routing, web research ve Core report/artifact grubu
`156 tests / OK` sonucudur. R224 ürün davranışını doğru üretmiş fakat evaluator komutundaki boş
selection-reason metadata'sı nedeniyle kabul sayılmayıp `failed` kapatılmıştır. Metadata'sı doğru
fresh R225 gerçek offscreen source-app koşusu üç adaptif turda geçmiştir: son beş sipariş -> üçüncü
siparişin exact ürünü -> aynı ürünün tüm geçmişte `82 adet / 50 farklı sipariş / 3559.53 TRY` üçlü
projection'ı. Exact `gemini-3.1-flash-lite`, fallback kapalı, PII genişlemesi yok;
`accepted=true / problems=[] / passed`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r225-gemini31lite-contextual-product-multimetric-2026-08-01.json`.
R225 yalnız R223 failure sınıfını kapatır; current source fingerprint için tam 50+ adaptif cloud
kampanyası yine turn 1'den başlar ve her cevap doğrudan okunur.

2026-08-02 Karar 99, doğrulanmış bağlamsal ürün özetinin sonraki turdaki genel typed hesaplarda
yeniden kullanılmasını bağlayıcı hale getirir. Fresh R226 organik 50+ kampanyasının ilk beş turu;
genel Orders özeti, sıfır yeni tool ile durum oranı, son beş sipariş, listedeki üçüncü sipariş ve
aynı ürünün tüm geçmişteki `82 adet / 50 farklı sipariş / 3559.53 TRY` çoklu projection'ını
geçmiştir. Altıncı turda kullanıcı açıkça yeni sorgu çalıştırmadan ürün brüt tutarını ürün adedine
bölmeyi istemiştir. Formula repair eldeki canonical operandları bilmediği için
`derived.latest / derived.latest` yazmış; runtime, bir önceki turda gereken iki authoritative sayı
bulunmasına rağmen “kanıt yetmiyor” cevabıyla fail-closed durmuştur. Kampanya ilk kritik görünür
failure'da `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r226-gemini31lite-organic-50-2026-08-01.json`.

Yeni genel invariant şudur:

1. Exact ürün için başarılı `orders.item_sales_summary` sonucu; identity dependency, tek public
   product identity, period, quantity, distinct-order count, gross/currency, source revision ve
   snapshot hash'iyle immutable `contextual_item_sales_summary` observation'ı olarak saklanır.
2. Bu persisted kanıt yalnız typed turn açıkça
   `operation_policy=existing_observations_only + metric=derived` olduğunda yeni domain sorgusunun
   yerini alabilir. Normal/fresh business read eski observation ile sessizce karşılanamaz.
3. Formula repair bütün canonical ref evrenini değil, exact typed state içinde gerçekten mevcut ve
   doğrulanmış operand ref'lerini görür. Mevcut değilse `derived.latest` veya başka bir ref model
   cevabında bulunsa dahi normalization tarafından reddedilir.
4. `orders.item_gross_amount / orders.item_sales_quantity` ayrı bir
   `amount_per_quantity` boyutudur; deterministik Core evaluator sonucu `TRY/adet` gibi exact
   currency/unit provenance ile üretir. `amount_per_order` veya boyutsuz division olarak
   geçirilemez.
5. Response verifier önceki hash-backed ürün observation'ını yalnız bu dar reuse sözleşmesinde
   metric evidence kabul eder; doğrudan ürün raporu, farklı ürün veya stale/bozuk hash için kabul
   etmez.

Focused regression artık yeni sorgu çalıştırmadan görünür
`3559.53 TRY / 82 adet = 43.41 TRY/adet` sonucunu ve sıfır tool çağrısını doğrular. Bu deterministic
kanıt R226 ürün failure'ını tek başına kapatmaz; exact cloud source-app focused tekrarından sonra
fresh 50+ organik kampanya current fingerprint için yine turn 1'den başlamalıdır.

2026-08-04 Karar 100, R226 ürün-özeti yeniden kullanım failure'ının gerçek ürün yolunda kapandığını
kaydeder. Fresh R227 exact cloud source-app kabulü dört adaptif turda şunları birlikte geçmiştir:

1. Son beş sipariş authoritative `order_date desc` sırasıyla ve yalnız sipariş kimlikleriyle
   listelenmiştir.
2. Kullanıcının numarayı tekrar etmeden söylediği “listedeki üçüncü sipariş” typed selection
   üzerinden çözülmüş; ürün ve kargo bilgisi müşteri/adres genişlemesi olmadan verilmiştir.
3. “Bu ürün” devamı aynı public product identity'yi tüm geçmiş kapsamına taşımış ve tek canonical
   özetten `82 adet / 50 farklı sipariş / 3559.53 TRY` üretmiştir.
4. “Yeni veri sorgusu çalıştırmadan böl” devamı sıfır yeni domain tool çağrısıyla immutable önceki
   observation'ı kullanmış ve görünür
   `3559.53 TRY / 82 adet = 43.41 TRY/adet` sonucunu üretmiştir.

Koşu exact `gemini-3.1-flash-lite` ile, fallback kapalı olarak çalışmıştır. Dördüncü turdaki aynı-model
`429` yeniden denemesi aynı exact modelde başarılı olmuş; başka modele/provider'a geçiş olmamıştır.
Runtime final cevabı doğrulanmış deterministic existing-observation projection'dan üretmiş,
acceptance sonucu `passed / accepted=true / problems=[]` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r227-gemini31lite-contextual-unit-average-2026-08-04.json`.

R227 yalnız R226'nın focused failure sınıfını kapatır; Orders veya Faz 8B kapanışı değildir. Current
source fingerprint için R228 organik 50+ exact-cloud kampanyası turn 1'den başlamalı, promptlar her
önceki görünür cevap bizzat okunduktan sonra seçilmeli ve ilk kritik sapmada kampanya durdurulup kök
neden sahip katmanda giderilmelidir.

2026-08-04 Karar 101, mağaza/sipariş-popülasyonu parasal metriğiyle bağlı tek-ürün parasal metriğini
ayırır. Fresh R228 organik kampanyası ikinci turda durdurulmuştur: kullanıcı toplam sipariş sayısı,
durum dağılımı ve bütün kayıtlı siparişlerden hesaplanan toplam brüt tutarı birlikte istemiştir.
Model-authored interpretation genel `amount` yanında hatalı olarak `item_sales_amount` alanını da
üretmiş; bu alan gereksiz `orders.item_sales_summary` adımını zorlamış ve response verifier doğru
`orders.summary` kanıtında `3112 / status_counts / 502518.01 TRY` bulunmasına rağmen “seçili ürün
tutarı kanıtı yok” cevabıyla görünür sonucu bozmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r228-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'ta `item_sales_quantity`, `item_sales_order_count` ve `item_sales_amount` scalar
projection'ları yalnız current turn gerçekten contextual bir product identity bağladığında
authoritative sayılır. Bağsız model alanı typed projection drift olarak kaldırılır; kullanıcının
açık population `count/status/amount` alanları normal canonical kurallarla korunur. Broad analysis
varsayılan boyutları yalnız kullanıcı explicit aggregate boyutları belirtmediyse eklenir; buna
karşılık broad analizde record-detail alanlarını kaldıran privacy/shape sınırı her durumda çalışmaya
devam eder.

Focused deterministic regression `6 passed`; bütün Orders agent runtime dosyası
`333 passed / 347 skipped` sonucuyla geçmiştir. Fresh R229 exact source-app tekrarı aynı doğal iki
turu yeniden çalıştırmış; tek `orders.summary` çağrısıyla görünür cevap `3112` toplam siparişi, dört
authoritative durum kovasını ve `502518.01 TRY` toplam brüt tutarı eksiksiz vermiştir. Ürün metriği,
ürün tool'u veya fallback yoktur; exact `gemini-3.1-flash-lite`, `passed / accepted=true /
problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r229-gemini31lite-general-orders-overview-2026-08-04.json`.

R229 yalnız R228'in ilk failure sınıfını kapatır. Yeni runtime source fingerprint için R230 organik
50+ exact-cloud kampanyası turn 1'den yeniden başlamalıdır; R228'in iki turu taşınamaz.

2026-08-04 Karar 102, birden fazla lifecycle status üyesinin tek typed oran hedefinde korunmasını
bağlayıcı kılar. Fresh R230 organik kampanyası ilk üç turda konuşma, genel population özeti ve
mevcut observation'dan sıfır tool ile `2957 / 3112 = %95.02` hesabını geçmiştir. Dördüncü turda
`Cancelled + UnDelivered + UnDeliveredAndReturned` birlikte istenmiş; provider bunu tek operandlı
generic `percentage` formülüne çevirmiştir. Formula repair fail edince canonical read recovery
status üyelerini contract'ta tutsa da projection/requirement'ı yalnız toplam sipariş sayısına
indirmiş; görünür cevap yalnız “3112 sipariş” olmuştur. Kampanya burada durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r230-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'ta iki veya daha fazla explicit order lifecycle status'ünün population içindeki
birleşik oranı generic provider formula değildir. Runtime generic derived validation'dan önce bunu
canonical status-set ratio olarak normalize eder; bütün üyeler, her üyenin count kanıtı, birleşik
pay, population paydası ve yüzde tek semantic contract'ta kalır. Tek status için normal typed
derived/formula repair yolu değişmez.

Focused regression `5 passed`; bütün Orders agent runtime dosyası `334 passed / 348 skipped`
sonucuyla geçmiştir. Fresh R231 exact source-app tekrarı dört turda genel özeti, sıfır-tool tek
status oranını ve üç üyeli status-set hesabını geçmiştir. Görünür son cevap
`110 + 44 + 1 = 155`, `155 / 3112 = %4.98` kanıtını eksiksiz göstermiştir. Exact
`gemini-3.1-flash-lite`, fallback yok, `passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r231-gemini31lite-three-status-ratio-2026-08-04.json`.

R231 focused closure'dır; yeni source fingerprint için R232 organik 50+ kampanyası yeniden turn
1'den başlamalıdır.

2026-08-04 Karar 103, doğru görünen fakat business verifier yolunu atlayan cevabı başarısız sayar.
Fresh R232 organik kampanyası genel özeti geçtikten sonra kullanıcı açıkça yeni sorgu çalıştırmadan
önceki tablodaki `iptal + teslim edilemeyen + teslim edilemeyip iade dönen` grubunu hesaplatmıştır.
Görünür cevap tesadüfen `155 / 3112 = %4.98` demiş olsa da runtime
`typed_model_non_business_turn` yoluna düşmüş, `final_response_source` boş kalmış ve canonical
observation projection çalışmamıştır; kampanya üçüncü turda `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r232-gemini31lite-organic-50-2026-08-04.json`.

Kök neden projection-normalization sırasıdır: “iade dönen” ifadesi geçici `returns` record-detail
alanını status ratio projection'ına yeniden eklemiş; existing-observations-only sınıflandırması bu
fazladan alan yüzünden geçerli business analysis'i conversation'a düşürmüş; `returns` ancak daha
sonra kaldırılmıştır. Ayrıca doğal yalın `iptal` lifecycle alias'ı `cancelled` status üyesine
bağlanmamıştır.

Yeni invariant'ta status-set projection temizliği operation-policy/existing-observation
sınıflandırmasından önce tamamlanır. Record-level `returns` status-set ratio'ya sızamaz; yalın
`iptal` canonical `cancelled` üyesidir. Açık no-new-query status hesabı ancak
`typed_existing_observation_verified_projection` ve doğrulanmış deterministic projection kaynağıyla
başarılıdır; serbest sohbetten gelen doğru sayı kabul değildir.

Focused regression `4 passed`; bütün Orders agent runtime dosyası `334 passed / 348 skipped`
sonucuyla geçmiştir. Fresh R233 exact source-app tekrarı üçüncü turda sıfır yeni tool ile
`Cancelled 110 + UnDeliveredAndReturned 44 + UnDelivered 1 = 155; 155 / 3112 = %4.98` üretmiştir.
Karar yolu `typed_existing_observation_verified_projection`, final kaynak
`deterministic_existing_observation_projection`; exact `gemini-3.1-flash-lite`, fallback yok,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r233-gemini31lite-existing-status-set-ratio-2026-08-04.json`.

R233 focused closure'dır; yeni source fingerprint için R234 organik 50+ kampanyası turn 1'den
yeniden başlamalıdır.

2026-08-04 Karar 104, doğal no-new-operation ifadelerinin permission boundary olduğunu kaydeder.
Fresh R234 organik kampanyasında kullanıcı “Yeni sorgu yok” diyerek önceki summary'den aynı üç
status grubunu hesaplatmıştır. Cevap sayısal olarak doğru olsa da runtime `orders.summary`
çalıştırmış; açık kullanıcı sınırı ihlal edildiği için kampanya üçüncü turda durdurulmuştur.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r234-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'ta `yeni/tekrar/yeniden + veri/tool/araç/API/sorgu/işlem + yok/olmasın` biçimleri de
`existing_observations_only` izin sözleşmesidir. Bu grammar business intent veya tool seçmez; yalnız
kullanıcının yeni operation çalıştırma yetkisini daraltır. Model bu sınırı genişletemez.

Focused regression `4 passed`; bütün Orders agent runtime dosyası `334 passed / 348 skipped`
sonucuyla geçmiştir. Fresh R235 exact source-app tekrarı “Yeni sorgu yok” turunda sıfır tool,
`typed_existing_observation_verified_projection` ve
`deterministic_existing_observation_projection` ile exact `155 / 3112 = %4.98` üretmiştir. Exact
`gemini-3.1-flash-lite`, fallback yok, `passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r235-gemini31lite-no-new-query-boundary-2026-08-04.json`.

R235 focused closure'dır; yeni source fingerprint için R236 organik 50+ kampanyası turn 1'den
yeniden başlamalıdır.

2026-08-04 Karar 105, önceki status tablosundaki grouped lifecycle referansını typed bağlam sayar.
Fresh R236 organik kampanyasında kullanıcı “iptal ve iki teslim edilememe grubunu” birleştirmeyi
istemiş; önceki cevap `UnDelivered` ile `UnDeliveredAndReturned` kovalarını açıkça göstermesine
rağmen interpretation malformed generic percentage repair'ında fail etmiş ve gereksiz clarification
üretmiştir. Kampanya üçüncü turda durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r236-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'ta açık “iki/her iki teslim edilememe/non-delivery grubu” canonical grouped status
alias'ıdır ve `UnDelivered + UnDeliveredAndReturned` üyelerini birlikte bağlar. Kullanıcı dahili
marketplace status adlarını tekrar etmek zorunda değildir; group alias yalnız status üyeliğini
çözer, sayı veya tool sonucu uydurmaz.

Focused regression `4 passed`; bütün Orders agent runtime dosyası `334 passed / 348 skipped`
sonucuyla geçmiştir. Fresh R237 exact source-app tekrarı grouped ifadeyi önceki immutable summary
üzerinden sıfır tool ile çözmüş ve `Cancelled 110 + UnDeliveredAndReturned 44 + UnDelivered 1 =
155; 155 / 3112 = %4.98` üretmiştir. Karar yolu
`typed_existing_observation_verified_projection`, exact `gemini-3.1-flash-lite`, fallback yok,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r237-gemini31lite-grouped-status-reference-2026-08-04.json`.

R237 focused closure'dır; yeni source fingerprint için R238 organik 50+ kampanyası turn 1'den
yeniden başlamalıdır.

2026-08-04 Karar 106, record-detail projection'ında açık include/exclude alan sözleşmesini bağlayıcı
kılar. Fresh R238 organik kampanyası beşinci turda listedeki dördüncü siparişi doğru çözmüş fakat
kullanıcının istediği sipariş tutarını atlamış ve istenmeyen takip numarasını görünür cevaba
eklemiştir. “Müşteri/adres verme” denmesine rağmen provider interpretation bu iki alanı requested
projection'a da yazmıştır. Kampanya burada durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r238-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'lar:

1. “Verme/gösterme/yazma/paylaşma/ekleme/olmasın/istemiyorum” ile açıkça yasaklanan alanlar model
   projection'ını daraltan privacy boundary'dir; provider bu alanları yeniden ekleyemez.
2. `cargo` yalnız kargo firması/provider alanıdır; `tracking_number` ancak kullanıcı açıkça takip
   bilgisini istediğinde projection'a girer.
3. Full-order-context projection `amount + currency` istediğinde authoritative `order.total_price`
   ve para birimini görünür cevaba taşır.
4. Grounded olması istenmeyen hassas alanı meşru yapmaz. Customer/address/phone/email/tracking/
   package/claim değeri requested değilse response verifier görünür cevabı reddeder.

Focused regression `4 passed`; bütün Orders agent runtime dosyası `336 passed / 350 skipped`
sonucuyla geçmiştir. Fresh R239 exact source-app tekrarı beş turda dördüncü sipariş için yalnız ürün,
`adet 2`, `Trendyol Express Marketplace` ve `399.98 TRY` üretmiş; müşteri, adres ve takip bilgisi
göstermemiştir. Exact `gemini-3.1-flash-lite`, fallback yok,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r239-gemini31lite-private-detail-projection-2026-08-04.json`.

R239 focused closure'dır; yeni source fingerprint için R240 organik 50+ kampanyası turn 1'den
yeniden başlamalıdır.

2026-08-04 Karar 107, tek kullanıcı turunda birden fazla bağımsız aritmetik sonucun first-class
typed sözleşmeyle taşınmasını bağlayıcı kılar. Fresh R240 organik kampanyası ilk yedi turda genel
özeti, status-set oranını, bounded sipariş listesini, gizlilik-daraltılmış order detail'i,
contextual ürün özetini ve önceki ürün observation'ından sıfır-tool birim tutar hesabını geçmiştir.
Sekizinci turda kullanıcı önceki authoritative özetteki `Delivered` ile `Cancelled` sayıları
arasındaki farkı ve ayrıca `Cancelled / toplam` oranını aynı cevapta istemiştir. State içinde
`2957`, `110` ve `3112` mevcut olmasına rağmen tek-formüllü contract iki ayrı hesabı temsil
edememiş ve runtime görünür “kanıt yetmiyor” cevabıyla fail-closed olmuştur. Kampanya ilk kritik
sapmada durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r240-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'lar:

1. Bir turdaki her bağımsız aritmetik sonuç ayrı operator, ordered operand ref'leri, result kind,
   precision ve show-work taşıyan `derived_calculations` üyesidir. Fark ve oran tek formüle
   sıkıştırılmaz.
2. Her formülün operandları yalnız current typed state'teki canonical authoritative ref'lerden
   çözülür; formüllerden biri kanıtlanamazsa bütün çoklu hesap cevabı fail-closed olur.
3. Deterministic projection bütün sonuçları ve istenen işlemleri görünür cevapta ayrı ayrı taşır;
   response verifier her sonucun operandını, operatorünü, sonucunu, birimini ve currency'sini
   bağımsız doğrular.
4. Eski `derived_calculation` tek-sonuç sözleşmesi geriye uyumlu kalır; çoklu desteği tek-formül
   yollarını veya `derived.latest` observation zincirini bozmaz.
5. Bu yapı doğal dil kalıbına özel cevap yaması değildir; fark+oran, min+max, ortalama+pay gibi
   önceden düşünülmemiş bileşik hesap hedeflerinin ortak typed arithmetic primitive'idir.

Focused ve bütün Orders runtime regresyonu `338 passed / 352 skipped` sonucuyla geçmiştir. Bu yerel
kanıt R240 failure sınıfını tek başına kapatmaz; fresh exact-cloud source-app focused tekrarında iki
formülün model tarafından authored edilmesi, sıfır tool ile exact `2847` ve `%3.53` projection'ının
doğrulanması gerekir. Ardından yeni source fingerprint için tam organik 50+ kampanya yine turn
1'den başlamalıdır.

2026-08-04 Karar 108, R241 focused exact-cloud tekrarının typed interpretation sınırında
durduğunu kaydeder. Model iki bağımsız formülü authored etmiş fakat canonical enum yerine
`subtraction`; bounded formula repair ise `addition` operator adını kullanmıştır. Schema cevabı
business operation'a ulaşmadan reddetmiş ve görünür clarification üretmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r241-gemini31lite-multi-calculation-2026-08-04.json`.

Yeni invariant'ta yaygın şema-eşdeğer operator adları (`addition/sum`, `subtraction/difference`,
`multiplication/product`, `division/quotient`, `percent/rate`, `min/max`) normalization sınırında
canonical `add/subtract/multiply/divide/percentage/minimum/maximum` enumlarına çevrilir. Bu katman
operand seçmez, formül kurmaz veya sayı üretmez; yalnız provider'lar arası sözleşme yazım farkını
canonical schema'ya taşır. Bilinmeyen operator yine fail-closed kalır.

Focused regression `2 passed / 2 skipped` sonucuyla geçmiştir. R241 başarısızdır ve R240'ı kapatmaz;
yeni source fingerprint ile fresh R242 exact-cloud focused tekrar gerekir.

2026-08-04 Karar 109, R242 focused tekrarında operator alias'larının tek başına yeterli olmadığını
kaydeder. Provider çoklu hesap satırlarını düz formula yerine `calculation/derived_calculation/
formula` gibi tek nesnelik taşıyıcılarla döndürebilmiş; normalization satır seviyesinde operator
bulamayınca hem ilk yorum hem bounded repair fail-closed kalmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r242-gemini31lite-multi-calculation-2026-08-04.json`.

Yeni invariant'ta her `derived_calculations` satırı ya canonical düz formula ya da yalnız tek formula
taşıyan yaygın şema wrapper'ıdır. Normalization wrapper'ı açar ve içeriği aynı strict formula
validator'ından geçirir; wrapper içindeki bilinmeyen ref/operator, eksik operand veya boyut hatası
yine reddedilir. Bu provider-shape canonicalization business hedefi veya operand authored etmez.
Focused regresyon `2 passed / 2 skipped`; fresh R243 exact-cloud tekrar gerekir.

2026-08-04 Karar 110, R243/R244 focused tekrarlarının nested provider şema farkını kanıtladığını
kaydeder. Value-free JSON shape gözlemi hem ilk interpretation hem bounded repair cevabında iki
formula bulunduğunu; buna karşılık `operands` üyelerinin object yerine string ve `show_work`
değerinin boolean yerine string serialize edildiğini göstermiştir. R243 artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r243-gemini31lite-multi-calculation-2026-08-04.json`;
R244 artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r244-gemini31lite-multi-calculation-shape-2026-08-04.json`.

Yeni invariant'ta yalnız canonical operand ref metinleri (`orders.total_count`,
`orders.status_count:Delivered`, aynı canonical ref'in parantez/slash biçimi vb.) strict typed
operand nesnesine çevrilebilir; serbest doğal dil operand olarak kabul edilmez. String
`true/false` yalnız `show_work` boolean alanında canonicalize edilir. Literal sayı, ref, status
üyesi, operator veya business ilişki runtime tarafından authored edilmez. Focused regresyon
`2 passed / 2 skipped`; fresh R245 exact-cloud tekrar gerekir.

2026-08-04 Karar 111, R245-R248 tanı koşularının Gemini nested-formula lehçesini değer/PII
sızdırmayan structural diagnostics ile kesinleştirdiğini kaydeder. Provider ilk yorumda operandları
serbest string olarak verebilmekte; bounded repair'de ise canonical `ref` yanında status üyesini
`member` veya `status`, count farkını `difference`, yüzde oranını `divide + ratio` ve `show_work`
boolean'ını görünür işlem açıklaması olarak serialize etmektedir. Artifact'lar:
`orders-phase8b-r245-gemini31lite-multi-calculation-2026-08-04.json`,
`orders-phase8b-r246-gemini31lite-operand-diagnostic-2026-08-04.json`,
`orders-phase8b-r247-gemini31lite-multi-calculation-2026-08-04.json`,
`orders-phase8b-r248-gemini31lite-formula-enum-diagnostic-2026-08-04.json`
(`AI/docs/live_llm_transcripts/source-ui/` altında).

Yeni provider-neutral schema normalization invariant'ları:

1. `status` yalnız `orders.status_count` operandında `member` alias'ıdır.
2. `difference` yalnız bütün operand ref'leri typed count boyutundaysa `count` result kind olur.
3. `ratio/percentage_result/percentage_value` canonical `percentage` result kind'dır; operator
   `divide` ise yalnız bu explicit result kind kanıtıyla canonical `percentage` evaluator'a taşınır.
4. `show_work` içindeki açık boolean/yes/no enumları canonicalize edilir; boş olmayan bir işlem
   açıklaması yalnız presentation flag `true` sayılır. Bu metinden ref, operand, operator, sayı veya
   sonuç üretilmez.
5. Formula diagnostic varsayılan olarak yalnız JSON tür/shape/hash kaydeder; sadece
   operator/result-kind/show-work şema alanları ve allowlist'li canonical ref/status değerleri
   görünür olabilir.

Focused regresyon `3 passed / 3 skipped`; R245-R248 başarısızdır ve R240'ı kapatmaz. Fresh R249
exact-cloud focused tekrar gerekir.

2026-08-04 Karar 112, R249-R251 provider varyasyonlarının result cardinality ve ordered-ref
sözleşmesini first-class yapmayı gerektirdiğini kaydeder. R250'de model iki ayrı hedefi tek
status-set ratio'ya çökertmiş ve görünür `110 + 2957 = 3067; %98.55` üretmiştir; doğru cevap
`2957 - 110 = 2847` ile `110 / 3112 = %3.53` olmalıydı. R251 iki formülü doğru authored etmiş
fakat `operands` yerine `ordered_operand_refs` ve
`orders.status_count(status=Delivered)` biçimini kullanmıştır. Artifact'lar
`orders-phase8b-r249-gemini31lite-multi-calculation-2026-08-04.json`,
`orders-phase8b-r250-gemini31lite-multi-calculation-2026-08-04.json` ve
`orders-phase8b-r251-gemini31lite-multi-calculation-2026-08-04.json`.

Yeni invariant'lar:

1. Typed turn contract `calculation_count` taşır. Model bağımsız görünür sonuç sayısını formüllerden
   ayrı author eder; iki veya daha fazla sonuç tek status-set projection'a indirgenemez.
2. `calculation_count >= 2` iken eksik/bozuk formula seti tek bounded, yalnız-formül decomposition
   çağrısıyla tamamlanır. Bu çağrı mode/domain/objective/tool seçemez.
3. `ordered_operand_refs`, `operands` alanının sıralı schema alias'ıdır.
   `orders.status_count+delivered` ve `orders.status_count(status=Delivered)` yalnız strict
   canonical status-ref grameri içinde operand nesnesine çevrilir; serbest metin kabul edilmez.
4. `members` yalnız tam bir string üyeli listeyse tek `member` alias'ıdır; sıfır veya birden çok üye
   tek scalar status-count operandı olamaz.
5. Model `calculation_count` vermese bile authored `derived_calculations` uzunluğu veya structural
   `multi/multi_step/multiple_results` operator işareti çoklu decomposition sınırını tetikleyebilir;
   runtime sonuç sayısını cümle regex'iyle tahmin etmez.

2026-08-04 Karar 113, R240 failure sınıfının fresh R252 exact-cloud source-app kabulünde
kapandığını kaydeder. Üç adaptif turda:

1. `orders.summary` authoritative `3112` toplam ve dört lifecycle status kovasını üretmiştir.
2. Kullanıcının iki bağımsız hesabı `calculation_count=2`, canonical `subtract + percentage`
   formülleri ve sıfır yeni tool ile deterministic olarak
   `2957 siparis - 110 siparis = 2847 adet` ve
   `110 siparis / 3112 siparis × 100 = 3.53 %` biçiminde görünür olmuştur.
3. Şeffaflık devamında sistem yeni sorgu/tool çalıştırmadığını ve kullandığı exact önceki
   operandları doğru açıklamıştır.

Koşu exact `gemini-3.1-flash-lite`, fallback kapalı, current source fingerprint ve
`passed / accepted=true / problems=[]` ile tamamlanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r252-gemini31lite-multi-calculation-2026-08-04.json`.
Bütün Orders runtime regresyonu `340 passed / 354 skipped` sonucuyla geçmiştir.

R252 yalnız focused closure'dır; yeni source fingerprint için R253 organik 50+ exact-cloud
kampanyası turn 1'den başlamalı ve ilk kritik sapmada durmalıdır.

2026-08-04 Karar 114, fresh R253 organik kampanyasının ikinci turda yeni bir derived-cardinality
regresyonu bulduğunu kaydeder. Kullanıcı count + status distribution + toplam brüt TRY tutarı
istemiş; provider summary metric yanında tek operandlı geçersiz formula/calculation-count drift'i
üretmiştir. Runtime bunu gerçek derived hedef sanıp formula repair'a girmiş; repair fail edince
safe read recovery `amount/currency` projection'ını kaybetmiş ve semantic verifier planı
reddetmiştir. Görünür business cevap üretilememiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r253-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'ta `calculation_count=1` veya geçersiz raw tek formula, kendi başına summary/read
metric'ini derived hedefe çeviremez. Single-result formula repair yalnız model typed
`metric=derived` authored ettiğinde yapılır. Geçerli tek formula veya
`calculation_count>=2 + multiple-result declaration` normal derived yolunu korur. Böylece ayrı
aggregate projection'ları “topla” sözcüğü yüzünden anlamsız tek operandlı aritmetiğe dönüşmez.
Focused regresyon `5 passed / 5 skipped`; fresh exact-cloud broad-summary tekrar gerekir ve
ardından organik kampanya yeni fingerprint ile turn 1'den başlamalıdır.

2026-08-04 Karar 115, R254 broad-summary tekrarının provider'ın direct projection'ı tek operandlı
`identity` derived formula olarak temsil etmesi nedeniyle yine fail ettiğini kaydeder. Formula
repair `identity` operatorünü aritmetik sayıp reddetmiş; safe recovery amount/currency boyutunu
taşımamış ve plan semantic verifier'da durmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r254-gemini31lite-broad-summary-2026-08-04.json`.

Yeni invariant'ta tam bir operandı değişmeden döndüren `identity/projection/passthrough` unary
formula aritmetik değildir. Runtime formula/operand authored etmeden bu wrapper'ı kaldırır ve
modelin mevcut requested field'larından scalar veya multi-dimension summary contract'ını
canonicalize eder. Birden fazla business projection boyutu `summary + broad_analysis`; tek boyut
typed scalar metric olur. Unknown unary operator veya birden fazla operandlı identity reddedilir.
Focused regresyon `4 passed / 4 skipped`; fresh R255 exact-cloud tekrar gerekir.

2026-08-04 Karar 116, R255-R258 tekrarlarının direct aggregate projection ile arithmetic relation
ayrımını provider `request_shape/calculation_count` alanlarına tek başına bırakamayacağımızı
kaydeder. Provider açık count/status/amount alanlarını sırasıyla `count`, `identity` veya tek
operandlı derived formüller gibi serialize etmiş; formula repair ve safe recovery görünür cevabı
üretememiştir. Artifact'lar:
`orders-phase8b-r255-gemini31lite-broad-summary-2026-08-04.json` ...
`orders-phase8b-r258-gemini31lite-broad-summary-2026-08-04.json`.

Yeni invariant'lar:

1. Kullanıcının açık population `count`, status distribution ve total revenue projection'ları
   model requested-fields omission'ına karşı korunur. Revenue projection `amount` taşır; monetary
   normalization `currency` boyutunu ve mevcut audit reason'ını ekler.
2. Birden fazla açık aggregate alan arasında fark/oran/yüzde/bölme/çıkarma/çarpma/ortalama/
   min-max gibi bir relation yoksa bunlar bağımsız summary projection'larıdır; model bunları formula
   setine çeviremez.
3. Arithmetic relation grammar operation/tool seçmez ve “toplam tutar” gibi aggregate isimlerini
   aritmetik `topla` fiili saymaz. Gerçek average/difference/ratio istekleri derived kalır.
4. Early projection retention eski canonical correction reason'larını korur; audit/regression
   gözlemlenebilirliği schema değişiminde sessizce kırılmaz.

2026-08-04 Karar 117, fresh R259 exact-cloud focused tekrarının geniş özeti kapattığını kaydeder.
Tek `orders.summary` çağrısı görünür `3112` toplam, dört status kovası ve `502518.01 TRY` toplam brüt
tutar üretmiştir. Contract `summary + broad_analysis`, requested fields
`count/status/amount/currency`; exact `gemini-3.1-flash-lite`, fallback yok,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r259-gemini31lite-broad-summary-2026-08-04.json`.
Bütün Orders runtime regresyonu `343 passed / 357 skipped` sonucuyla geçmiştir. Fresh R260 organik
50+ kampanya yeni fingerprint ile turn 1'den başlamalıdır.

2026-08-04 Karar 118, fresh R260 organik kampanyasının dördüncü turda bounded sipariş listesi
projection'ında durduğunu kaydeder. İlk üç tur gündelik konuşmayı, tek authoritative genel özeti ve
önceki immutable summary'den sıfır yeni tool ile iki bağımsız hesabı geçmiştir. Dördüncü turda
`orders.recent` doğru sekiz kaydı ve doğru sıralamayı üretmesine rağmen provider açık
`order_number` alanını requested projection'a taşımamış; deterministic cevap yalnız “Son 8 sipariş
getirildi.” diyerek gerçek sipariş numaralarını görünür kılmamıştır. Kampanya ilk kritik sapmada
`failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r260-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'ta kullanıcı açıkça sipariş numarası/kimliği istediğinde `order_number`, provider
omission'ına karşı read-contract normalizasyonundan önce korunur. Ancak bu erken sınır yalnız güvenli
identifier projection'ına aittir; “kargoya hazır”, “kargo değişikliğine uygun” veya “bekleyen
iadeler” gibi filter/entity sözcükleri kargo/iade detail alanıymış gibi çıktı projection'ına
çevrilemez. Diğer record-detail alanları contextual selection, include/exclude ve privacy
sözleşmeleri bilindikten sonra korunur.

2026-08-04 Karar 119, R261 focused tekrarının iki turlu order-list -> ordinal-detail zincirinde yeni
bir population/record ayrımı hatası bulduğunu kaydeder. İlk tur exact sekiz sipariş numarasını
authoritative sırayla göstermiştir. İkinci turda “listedeki üçüncü siparişin ürün adı, adedi, durumu
ve toplam tutarı” isteği active selection içindeki tek kayda bağlanması gerekirken:

1. Record tutarı, bütün sipariş popülasyonunun toplam cirosu sanılmıştır.
2. Satır adedi, population count/item-sales metriği sanılmıştır.
3. Plan `orders.full_context` yerine `orders.revenue_total + orders.item_sales_report` çalıştırmıştır.

Bu LLM'in bilgi veya model gücü problemi değildir; typed semantic contract aynı kelimeleri yanlış
ölçüm seviyesine bağlamıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r261-gemini31lite-order-list-detail-2026-08-04.json`.

Bağlayıcı düzeltmeler:

- Deictic/ordinal bir record referansı varken “tutar” population revenue değildir.
- Contextual order-detail içinde “adet”, sipariş popülasyonu count'u değil seçili kayıt satırının
  quantity alanıdır.
- `record_detail/list + listedeki/ordinal/önceki kayıt` sözleşmesi `active_selection` olur;
  yalnız cümle başındaki yalın “bu” yeni bir sorguyu sahte active selection'a çeviremez.
- Bir önceki typed selection ve exact görünür sıra, modelin tekrar order id yazmasına gerek olmadan
  immutable RecordRef kaynağıdır.

2026-08-04 Karar 120, fresh R262 exact-cloud source-app kabulünün R260 ve R261 failure sınıflarını
birlikte kapattığını kaydeder. İlk tur yalnız tek `orders.query` çağrısıyla son sekiz sipariş
numarasını doğru sırada görünür vermiştir. İkinci tur “listedeki üçüncü sipariş” referansını typed
active selection üzerinden çözmüş, yalnız `orders.full_context` çalıştırmış ve görünür cevapta:

- ürün adını,
- `adet 1` bilgisini,
- `Delivered` durumunu,
- `94.99 TRY` sipariş tutarını

doğru vermiş; müşteri, adres ve takip numarası sızdırmamıştır. Exact
`gemini-3.1-flash-lite`, fallback kapalı, `passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r262-gemini31lite-order-list-detail-2026-08-04.json`.

Yeni değişikliklerden sonra tam Orders agent runtime dosyası `345 passed / 359 skipped` sonucuyla
geçmiştir. Bu koşu ayrıca eski list/return filtre sözleşmelerindeki altı geriye dönük vakayı
doğrulamıştır. R262 focused closure'dır; current source fingerprint için fresh R263 organik 50+
exact-cloud kampanyası turn 1'den başlamalı ve her cevap bizzat okunarak ilk kritik sapmada
durmalıdır.

2026-08-04 Karar 121, fresh R263 organik kampanyasının ikinci turda genel özet sözleşmesini yeniden
reddettiğini kaydeder. İlk gündelik sohbet turu geçmiştir. İkinci turdaki “önce genel resmi çıkar”
ifadesinde provider direct aggregate alanlarını yine geçersiz `count` formula lehçesiyle
serialize etmiş; runtime ise “çıkar” fiilini matematiksel subtraction saydığı için bağımsız
`count/status/amount` projection'larını summary'ye canonicalize edememiştir. Formula repair fail
ettikten sonra safe read recovery de iki ayrı lexical hata yapmıştır:

1. “Hesaplanabilen” sözcüğündeki `hesap` parçasını marketplace account scope sanmıştır.
2. Kullanıcının açık toplam brüt tutar + TRY boyutunu recovery projection'ından düşürmüştür.

Sonuçta contract `count/scope/status` olmuş, canonical plan semantic verifier'da reddedilmiş ve
hiçbir business cevap/tool üretilmemiştir. Kampanya kritik sapmada `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r263-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'lar:

- “Genel resmi/özeti/raporu/tabloyu çıkar” bir raporlama deyimidir, arithmetic subtraction değildir.
  `çıkar` ancak iki sayı, en az iki canonical status üyesi veya açık `sayı/tutar/toplamdan ... çıkar`
  operand ilişkisi bulunduğunda subtraction sinyalidir.
- Safe canonical read recovery ham substring aramaz; count, account scope, status, amount/currency
  ve risk için aynı canonical semantic yardımcıları kullanır.
- Recovery birden fazla bağımsız aggregate boyutu bulduğunda `summary + broad_analysis` kurar ve
  bütün açık boyutları metric requirements'a taşır; model sözleşmesinin bozulması kullanıcı
  projection'ını sessizce daraltamaz.
- “Hesaplanabilen/hesaplama” içindeki kelime parçası account scope değildir; yalnız typed
  `hesap/hesabım/mağaza/stage/production` grameri marketplace kapsamı seçebilir.

Focused regression `4 passed`; bütün Orders agent runtime dosyası
`348 passed / 362 skipped` sonucuyla geçmiştir. R263 başarısızdır; yeni source fingerprint ile fresh
R264 exact-cloud focused broad-summary tekrarı gerekir. Bu focused closure geçerse current
fingerprint için sonraki organik 50+ kampanya yine turn 1'den başlamalıdır.

2026-08-04 Karar 122, R263 failure sınıfının fresh R265 exact-cloud source-app kabulünde kapandığını
kaydeder. Aradaki R264 işlevsel olarak aynı doğru business sonucunu üretmiş ancak kabul istemcisinde
`selection_reason` verilmediği ve salt-okuma koşusu yanlışlıkla fresh write execute kanıtı
gerektirerek finalize edildiği için artifact validation tarafından kabul edilmemiştir; R264
business closure sayılmaz.

R265 temiz protokolle iki turda:

1. Gündelik konuşmaya toolsuz ve doğal cevap vermiştir.
2. Aynı “Önce genel resmi çıkar...” cümlesini tek `orders.summary` çağrısıyla çözmüş;
   `3112` toplam siparişi, `Delivered 2957 / Cancelled 110 /
   UnDeliveredAndReturned 44 / UnDelivered 1` dağılımını ve `502518.01 TRY` toplam brüt tutarı
   görünür vermiştir.

Exact `gemini-3.1-flash-lite`, fallback kapalı,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r265-gemini31lite-broad-summary-2026-08-04.json`.
R265 yalnız focused closure'dır; current source fingerprint için fresh R266 organik 50+
exact-cloud kampanyası turn 1'den başlamalıdır.

2026-08-04 Karar 123, fresh R266 organik kampanyasının beşinci turda record-detail status
projection omission bulduğunu kaydeder. İlk dört tur doğal sohbeti, genel summary'yi, önceki
observation'dan sıfır-tool iki bağımsız hesabı ve privacy-safe son sekiz sipariş kimliği listesini
geçmiştir. Beşinci turda “listedeki üçüncü sipariş” doğru active selection kaydına bağlanmış ve
yalnız `orders.full_context` çalışmıştır. Authoritative context içinde `Delivered` bulunmasına ve
typed projection `item/quantity/status/amount/currency` istemesine rağmen görünür deterministic
cevap yalnız ürün, `adet 1` ve `94.99 TRY` vermiş; açık sipariş durumunu atlamıştır. Müşteri, adres,
telefon veya takip numarası sızmamıştır. Kampanya kritik sapmada `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r266-gemini31lite-organic-50-2026-08-04.json`.

Kök neden tool veya selection değildir. Full-context deterministic projector status alanını
context projection'a dahil etmemiş; response verifier da record-detail status'u population status
distribution olmadığı için zorunlu kanıt/projection olarak kontrol etmemiştir.

Yeni invariant'lar:

- `orders.full_context` + requested `status`, seçili `order.status` kanıtını görünür `Durum: ...`
  satırına taşır.
- Context içinde status kanıtı varken bunu atlayan model veya repair cevabı
  `order_status_projection_missing:<status>` ile reddedilir.
- Status-only eski okuma yolu compact `Siparis durumu: ...` projection'ını korur; full-context
  başlığı yalnız item/quantity/cargo/return/amount gibi gerçek detail boyutlarından biri de
  istendiğinde kullanılır.

Focused regression `4 passed`; tam Orders agent runtime dosyası
`349 passed / 363 skipped` sonucuyla geçmiştir. R266 başarısızdır; yeni source fingerprint ile
fresh R267 exact-cloud order-list -> ordinal-detail focused tekrarı gerekir. Ardından yeni organik
50+ kampanya yine turn 1'den başlamalıdır.

2026-08-04 Karar 124, R266 failure sınıfının fresh R267 exact-cloud source-app kabulünde kapandığını
kaydeder. İki adaptif turda:

1. Tek `orders.query`, en yeni sekiz sipariş kimliğini authoritative sırayla ve kişisel alan
   göstermeden üretmiştir.
2. “Listedeki üçüncü sipariş” immutable selection sırasından çözülmüş, yalnız
   `orders.full_context` çalışmış ve görünür deterministic cevap ürün adını, `adet 1`,
   `94.99 TRY` ile `Durum: Delivered` bilgisini birlikte vermiştir. Müşteri, adres, telefon ve takip
   numarası görünür değildir.

Exact `gemini-3.1-flash-lite`, fallback kapalı,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r267-gemini31lite-order-detail-status-2026-08-04.json`.
R267 yalnız focused closure'dır; current source fingerprint için fresh R268 organik 50+
exact-cloud kampanyası turn 1'den başlamalıdır.

2026-08-04 Karar 125, fresh R268 organik kampanyasının altıncı turda contextual product
multi-metric tutarsızlığı bulduğunu kaydeder. İlk beş tur gündelik konuşma, genel summary, aynı
observation'dan iki farklı birimli hesap (`2847 adet` ve `161.48 TRY/sipariş`), son sekiz kimlik ve
privacy-safe ordinal detail zincirini geçmiştir. Altıncı turda seçili ürünün bütün kayıtlı geçmişte
toplam satılan adedi, yer aldığı farklı sipariş sayısı ve brüt satış tutarı birlikte istenmiştir.
Authoritative `orders.item_sales_summary` kanıtı `82 adet / 50 sipariş / 3559.53 TRY` olmasına rağmen
görünür cevap `0 / 0 / 3559.53 TRY` üretmiş ve verifier bunu kabul etmiştir. Kampanya kritik
sapmada `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r268-gemini31lite-organic-50-2026-08-04.json`.

Kök neden iki semantic-scope hatasının birleşimidir:

1. Contextual ürün aggregate grammar'ı “bütün geçmişte”yi tanırken doğal “bütün kayıtlı geçmişte”
   biçimindeki bounded ara sözcüğü tanımamıştır; quantity ve product amount bağları kaybolmuştur.
2. “Kaç farklı siparişte” ifadesindeki `farklı`, arithmetic `fark` sanılmıştır.

Model formula repair fail edince safe recovery yalnız generic `amount/currency` projection'ını
korumuş; ürün adet ve distinct-order count verifier zorunluluğundan çıkmıştır. Model bu yüzden
authoritative olmayan sıfırları görünür yazabilmiştir.

Yeni invariant'lar:

- Seçili ürün aggregate scope'u `tüm/bütün/genel/toplam` ile
  `sipariş/satış/geçmiş/dönem` arasında en fazla üç bounded niteleyiciyi kabul eden tek DRY
  primitive'den çözülür.
- `farklı sipariş`, distinct-order cardinality'dir; arithmetic difference yalnız `fark/farkı/
  farkını` veya açık subtraction operand ilişkisiyle seçilir.
- Safe canonical recovery contextual ürün quantity/order-count/amount alanlarını generic
  `count/amount`a indirmez; bunları `item_sales_quantity/item_sales_order_count/
  item_sales_amount/currency` olarak birlikte korur.
- Bir ürün özeti üç metriği istiyorsa verifier her üçünü aynı identity-bound summary kanıtına karşı
  doğrular; doğru para değeri yanlış `0/0` adet-count iddialarını meşru kılamaz.
- Önceki ürün özetini bölme/çıkarma gibi açık derived istekleri yeni product summary değildir;
  canonical operand ref'leri üzerinden existing-observation calculation olarak kalır.

Focused regression `4 passed`; tam Orders agent runtime dosyası
`350 passed / 364 skipped` sonucuyla geçmiştir. R268 başarısızdır; yeni source fingerprint ile
fresh R269 exact-cloud list -> ordinal detail -> contextual product summary focused tekrarı
gerekir. Ardından yeni organik 50+ kampanya turn 1'den başlamalıdır.

2026-08-04 Karar 126, R268 failure sınıfının fresh R269 exact-cloud source-app kabulünde kapandığını
kaydeder. Üç adaptif turda:

1. En yeni sekiz sipariş kimliği privacy-safe ve authoritative sırayla listelenmiştir.
2. Listedeki üçüncü sipariş doğru RecordRef üzerinden çözülmüş; ürün, `adet 1`, `Delivered` ve
   `94.99 TRY` birlikte verilmiştir.
3. Aynı ürün “bütün kayıtlı geçmişte” kapsamına taşınmış; identity-bound
   `orders.item_sales_summary` kanıtından görünür `82 adet / 50 farklı sipariş / 3559.53 TRY`
   üretilmiştir.

Son turdaki provider `429` aynı exact modelde tek yeniden denemeyle geçilmiş; provider/model
fallback yapılmamıştır. Exact `gemini-3.1-flash-lite`,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r269-gemini31lite-contextual-product-summary-2026-08-04.json`.
R269 yalnız focused closure'dır; current source fingerprint için fresh R270 organik 50+
exact-cloud kampanyası turn 1'den başlamalıdır.

2026-08-04 Karar 127, fresh R270 organik kampanyasının ilk turda authoritative empty-set
semantiğini kırdığını kaydeder. “Bugün siparişlerde ne var ne yok” isteği doğru biçimde
`period=today` olmuş; `orders.summary` ve `orders.item_sales_summary` gerçekten sıfır sipariş,
boş status dağılımı ve boş ürün satır seti üretmiştir. Buna rağmen response verifier boş
`status_counts={}` ve `rows=[]` değerlerini “kanıt yok” saymış; deterministic projection
doğrulanamamış ve görünür cevap sıfır paydalardan `%0 iptal`, `0 TRY ortalama`, `%0 top-5` gibi
anlamsız analitik yorumlar üretmiştir. `final_source=deterministic_projection_failed` olduğu için
kampanya ilk turda `failed` kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r270-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'lar:

- Authoritative operation'ın `status_counts={}` ve `rows=[]` sonucu absence değil typed empty-set
  kanıtıdır; operation hiç çalışmamış/bozuk payload ile karıştırılamaz.
- Empty status projection dönem kapsamını ve `0 sipariş` sonucunu açıkça söyler.
- Empty item-sales projection dönem kapsamını, ürün satışı olmadığını ve en çok satan ürün
  bulunmadığını açıkça söyler.
- Kullanıcı status ve item-sales boyutlarını istediğinde yalnız “toplam 0” demek yeterli değildir;
  iki empty boyut da görünür projekte edilmelidir.
- Total order count sıfırken cancellation rate, average revenue veya leading-five share gibi
  sıfır-paydalı/iş değeri taşımayan broad-analysis yorumları üretilmez.

Focused regression `3 passed`; tam Orders agent runtime dosyası
`351 passed / 365 skipped` sonucuyla geçmiştir. R270 başarısızdır; yeni source fingerprint ile
fresh R271 exact-cloud today-empty broad-summary focused tekrarı gerekir. Ardından yeni organik
50+ kampanya turn 1'den başlamalıdır.

2026-08-04 Karar 128, R270 empty-set failure sınıfının fresh R271 exact-cloud source-app kabulünde
kapandığını kaydeder. Aynı doğal “bugün siparişlerde ne var ne yok” cümlesi
`orders.summary + orders.item_sales_summary` kanıtıyla görünür olarak:

- `Toplam 0 sipariş`,
- `2026-08-04 sipariş kalemi satışı yok; en çok satan ürün bulunmuyor`,
- `2026-08-04 sipariş durum dağılımı boş`,
- `Tahmini ciro 0 TRY`

sonucunu üretmiştir. İptal oranı, sipariş başına ortalama veya top-5 payı gibi sıfır-paydalı sahte
analitik yoktur. Final kaynak `deterministic_verified_projection`; exact
`gemini-3.1-flash-lite`, fallback kapalı,
`passed / accepted=true / problems=[]`. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r271-gemini31lite-today-empty-summary-2026-08-04.json`.
R271 yalnız focused closure'dır; current source fingerprint için fresh R272 organik 50+
exact-cloud kampanyası turn 1'den başlamalıdır.

2026-08-04 Karar 129, fresh R272 organik exact-cloud kampanyasının turn 5'te durdurulduğunu
kaydeder. Kullanıcı önce en yeni sekiz siparişi yalnız numaralarıyla sıralatmış, sonra
“bu listedeki üçüncü siparişin ürün adı, adedi, durumu ve toplam tutarı”nı istemiştir.
Typed interpretation doğru biçimde `entity=order`, `metric=detail`,
`record_scope=active_selection`, `request_shape=record_detail` ve görünür projection
alanlarını üretmiştir. Aktif immutable sekizli seçim de korunmuştur. Buna rağmen hem ilk
model planı hem bounded plan repair `orders.full_context` yerine `orders.query` seçmiş;
semantic verifier iki planı da
`typed_read_contract_operation_mismatch:orders.query` ile doğru biçimde reddetmiştir.
Runtime bundan sonra canonical tek okuma seçeneğine güvenli lower edemediği için kullanıcıya
gereksiz bir yeniden ifade etme mesajı göstermiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r272-gemini31lite-organic-50-2026-08-04.json`.

Yeni invariant'lar:

- Model-authored ve doğrulanmış typed read contract tam olarak bir canonical read operation'a
  izin veriyorsa, ilk plan ile tek bounded repair yalnız operation-shape mismatch nedeniyle
  reddedildiyse runtime üçüncü bir model denemesi veya kullanıcı clarification'ı istemeden bu
  tek read operation'a schema/policy canonicalization yapabilir.
- Bu recovery yalnız `mode=inspect`, `intent_kind=data_read`, read-only, non-destructive,
  approval gerektirmeyen operation için kullanılabilir; write/action planı üretemez.
- `record_scope=active_selection` recovery'si ancak immutable typed selection gerçekten varsa
  açılır. Ordinal hedef execution boundary'de listenin görünür sırasına göre exact tek kayda
  bağlanır; modelin yazdığı identifier hedef otoritesi değildir.
- `record_scope=exact_ids` için güvenilir typed selection yoksa deterministic katman hedef
  identifier uydurmaz ve bu recovery'yi kullanmaz.
- Semantic verifier gevşetilmez. Yanlış `orders.query` planları rejection provenance'ında
  korunur; kullanılan `orders.full_context` planı ayrıca aynı validator/compiler yolundan
  geçirilir ve `typed_unique_read_recovery` olarak audit edilir.
- Aynı typed contract birden fazla read operation'a izin veriyorsa seçim business planning
  sayılır; deterministic recovery yapılmaz.

Focused ordinal regression ve empty-set regression birlikte `2 passed`; tam Orders agent
runtime dosyası `352 passed / 366 skipped` sonucuyla geçmiştir. Bu yalnız local invariant
kanıtıdır. Fresh source-app R273 aynı list -> üçüncü kayıt detay zinciriyle exact-cloud focused
closure yapmalı; ardından current source fingerprint için R274 organik 50+ kampanyası turn
1'den başlamalıdır.

2026-08-04 Karar 130, ilk R273 exact-cloud focused denemesinin ürün semantiğine ulaşmadan
provider kotasında durduğunu kaydeder. `gemini-3.1-flash-lite` structured-output denemesinden
sonraki text invocation'da model-kapsamlı `HTTP 429`, `retry_after_seconds=59` üretmiştir.
Fallback kapalı kalmış; model cevabı alınmamış, business tool/API/DB/dosya/yazıcı işlemi
çalışmamıştır. Koşu ilk kritik failure'da `failed` finalize edilip source-app process
kapatılmıştır. Bu sonuç kod düzeltmesini doğrulamaz veya çürütmez; provider-unavailable
kanıtıdır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r273-gemini31lite-ordinal-detail-2026-08-04.json`.
Retry penceresinden sonra fresh process ve yeni artifact ile exact-model focused closure yeniden
başlamalı; geçen focused koşudan sonra organik 50+ kampanya ayrıca turn 1'den açılmalıdır.

2026-08-04 Karar 131, retry penceresinden sonra açılan ikinci fresh exact-model process'in de
ürün senaryosuna ulaşmadan aynı model-kapsamlı `HTTP 429` ile durduğunu kaydeder. Model cevabı
ve business tool çağrısı yoktur; fallback kapalıdır. R274 ilk kritik failure'da `failed`
finalize edilmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r274-gemini31lite-ordinal-detail-2026-08-04.json`.
Bu iki provider-quota koşusu local `352 passed / 366 skipped` invariant paketini geçersiz
kılmaz fakat source-app cloud closure yerine de geçmez. Güvenli kod checkpoint'i test edilip
pushlanabilir; exact-cloud R275 focused closure provider erişimi döndüğünde fresh process ile
yeniden denenmeli ve ancak geçerse R276 organik 50+ kampanya açılmalıdır.
Checkpoint öncesi bütün desktop suite `1956 passed / 741 skipped / 1 mevcut collection warning`
sonucuyla geçmiştir.

2026-08-11 Karar 132, OpenRouter paid control kapısının kullanıcı tarafından sağlanan yeni kredi
sonrasında açıldığını kaydeder. Fallback kapalı, secret-safe exact accessibility probe
`deepseek/deepseek-v4-flash` istedi; provider aynı actual model kimliğini döndürdü ve
`ERİŞİLEBİLİR` cevabı alındı. `accessible=true`, `exact_model_responded=true`,
`fallback_used=false`; billing/quota/provider error yoktur. Bu sonuç yalnız paid model erişim
kanıtıdır. Bundan sonraki cloud-first geliştirmelerde DeepSeek V4 Flash güçlü ücretli
differential-control modeli olarak kullanılacaktır. Her gerçek sohbet cevabı yine Codex
tarafından okunacak; harcama kontrollü tutulacak; model başarısı runtime semantic verification,
approval/read-back ve ücretsiz Gemini/OpenRouter baseline kapılarının yerine sayılmayacaktır.

2026-08-11 Karar 133, model kabul sırasını güçlü-model-first olarak daraltır. Bundan sonraki
Orders geliştirme ve gerçek sohbet kampanyalarında:

- ücretli OpenRouter ana kontrolü ve uzun konuşma kabulü exact
  `deepseek/deepseek-v4-flash` ile,
- ücretsiz Gemini kontrolü canlı katalogda erişilebilen en yüksek merkezi quality-tier adayla,
- ücretsiz OpenRouter kontrolü canlı katalogda erişilebilen en yüksek merkezi quality-tier
  adayla

başlar. İlk güçlü aday yalnız model-kapsamlı kota veya gerçek erişilemezlik nedeniyle
çalışamıyorsa aynı provider'daki sıradaki güçlü aday denenebilir. Düşük-tier cloud modeller,
küçük modeller ve local inference; güçlü modellerde agent plan/state/tool/verifier davranışı
kararlı hâle gelmeden kalite teşhisinin ana girdisi yapılmaz. Bu karar provider bağımsızlığı,
ücretsiz-model nihai baseline'ı veya ilerideki zayıf-model capability sınıflandırmasını silmez;
yalnız mevcut geliştirme zamanını model yetersizliğiyle runtime kusurunu birbirine karıştırmayan
en yüksek sinyalli testlere ayırır. Bu aşamada düşük-tier ücretli/ücretsiz modellerle veya local
modellerle uzun kabul kampanyası açılmaz; bunlar güçlü model baseline'ları kararlı olduktan sonra
ayrı capability/degradation matrisi içinde yeniden ele alınır. Güçlü ücretsiz adayların erişimi
canlı probe ile kanıtlanır; yalnız erişim/kota engeli varsa aynı provider içindeki sıradaki en
 güçlü adaya geçilir, ürün/runtime hatası daha zayıf modele geçilerek maskelenmez.

2026-08-11 Karar 134, exact paid DeepSeek V4 Flash ile yapılan R275-R280 focused
koşularını tek tek ürün gerçeğine dönüştürür; bu koşuların hiçbiri daha zayıf modele
geçilerek veya prompta örnek cevap ezberletilerek kapatılmamıştır:

- R275'te bir cloud isteğinin 600 saniyelik varsayılan timeout'u source-app'in 240
  saniyelik tur watchdog'unu aşmıştır. Provider istek timeout'u 120 saniyeyle
  sınırlandırılmıştır.
- R276'da model eksik GoalPlan JSON'u üretmiştir. Aynı model ve aynı typed bağlamla,
  business adımı icat etmeyen tek bounded JSON-only repair eklenmiştir; repair yine
  semantic verifier'dan geçmeden çalışamaz.
- R277'de exact structured-output denemeleri boş dönmüştür. Model fallback açılmadan,
  aynı exact modele tek guarded JSON-text degradation eklenmiştir.
- R278'de model “en yeni 8” ifadesindeki sekizi izinsiz türetilmiş hesap otoritesi gibi
  yorumlamıştır. Sayısal liste limiti/order number ile gerçek aritmetik isteği ayrılmış;
  kullanıcı fark/oran/yüzde/ortalama benzeri bir hesap istemedikçe formula authority
  reddedilmiştir.
- R279'da tek tek çağrılar istek timeout'una sığsa da planlama, repair ve synthesis
  çağrılarının toplamı dış watchdog'u aşmıştır. Bütün provider çağrılarını paylaşan 180
  saniyelik monotonik cloud-turn deadline eklenmiştir.
- R280'de typed ordinal çözülmesine rağmen model kapsamı product-wide/broad analysis'e
  genişletmiştir. Aktif immutable selection içindeki açık tek ordinal ve açık record-field
  isteği deterministik olarak `entity=order`, `metric=detail`,
  `request_shape=record_detail`, `record_scope=active_selection` semantiğine normalize
  edilir; execution hedefi yine typed selection'dan bağlanır.

Bu düzeltmeler semantik iş sonucunu deterministic katmana taşımamıştır. Model hâlâ GoalPlan
üretir; deterministic katman yalnız typed state, kullanıcı kapsamı, operation schema,
privacy, approval ve read-back sınırlarını doğrular/normalize eder. Kaynak artifact'ler
`orders-phase8b-r275-deepseek-v4-flash-ordinal-detail-2026-08-11.json` ile
`orders-phase8b-r280-deepseek-v4-flash-ordinal-detail-2026-08-11.json` arasındadır.

2026-08-11 Karar 135, aynı frozen list -> ordinal detail senaryosunun R281'de geçtiğini
kaydeder. Exact `deepseek/deepseek-v4-flash`, fallback kapalıyken ilk turda `orders.query`
ile tam sekiz sipariş üretmiş; ikinci turda önceki görünür listenin üçüncü kaydını
`session_context:order_selection.ordered_index_3.order_numbers` bağıyla tek
`orders.full_context` adımına çevirmiştir. Sonuç yalnız istenen ürün, adet, durum, tutar ve
para birimi alanlarını içermiş; müşteri/adres/takip bilgisi sızmamıştır. Model-authored
plan ve tool sonucu doğrulanmış, son synthesis ortak deadline'a ulaştığında uydurma cevap
yerine verified deterministic projection dönmüştür. Koşu 240 saniyelik dış sınırın altında
206.6 saniyede, `accepted=true`, iki tur ve iki Codex read-confirmed review ile kapanmıştır.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r281-deepseek-v4-flash-ordinal-detail-2026-08-11.json`.

R281 sonrasında deadline gözlemlenebilirliği de ayrıştırılmıştır: ortak tur bütçesinin
dolması provider/model arızası değildir; `turn_deadline` / `turn_deadline_exceeded` olarak
kaydedilir, retryable değildir ve model fallback'e izin vermez. Böylece maliyetli model
roulette başlamaz, doğrulanmış projection varsa güvenli sonuç korunur. İlgili provider ve
chat regresyon paketi `120 passed`; tam Orders agent runtime paketi bu source fingerprint
öncesinde `356 passed / 370 skipped` sonucuyla geçmiştir. Sonraki zorunlu kapı, yeni process
ve yeni artifact ile turn 1'den başlayacak en az 50 turluk organik DeepSeek V4 Flash
kampanyasıdır. Her cevap Codex tarafından okunacak, sonraki soru önceki gerçek observation'a
göre seçilecek ve ilk sistemik kritik failure'da kampanya durdurulup genel invariant
düzeltilmeden devam edilmeyecektir. Ardından aynı yetenekler erişilebilen en güçlü ücretsiz
Gemini ve OpenRouter adaylarında ayrı baseline olarak sınanacaktır.

2026-08-11 Karar 136, ilk organik 50+ DeepSeek V4 Flash kampanyası R282'nin daha ilk
turda doğru biçimde durdurulduğunu kaydeder. Kullanıcı aynı cümlede sipariş
senkronizasyonunu hazırlamasını ve kullanılacak hesap/ortamı açıkça söylemesini istemiştir.
Model iki atomic adım üretmiş; `orders.query` MDB / TRENDYOL / production scope'unu
authoritative olarak okumuş, `orders.fetch.prepare` güvenli pending approval üretmiş ve
onay öncesinde API/DB yazımı yapmamıştır. Ancak pending finalizer yalnız son prepare
mesajını göstererek ilk adımın açıkça istenen scope cevabını kaybetmiş; ayrıca iç
`api_account_id=1` değerini “Hedef kayıtlar: 1” diye kullanıcı yüzeyine taşımıştır. Bu bir
DeepSeek kalite kusuru olarak kabul edilmemiş; model doğru atomic planı kurduğu hâlde
runtime'ın çok adımlı read+prepare sonuçlarını collapse etmesi nedeniyle genel ürün
invariant'ı olarak ele alınmıştır. R282 turn 1'de `failed` finalize edilmiş, process
kapatılmış ve aynı artifact üzerinde devam edilmemiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r282-deepseek-v4-flash-organic-50-2026-08-11.json`.

Yeni invariant: pending approval cevabı, aynı GoalPlan içindeki doğrulanmış önceki read
observation'larından kullanıcının typed `requested_fields` alanlarını privacy-safe
authoritative projection ile korur; yalnız son prepare mesajına indirgenemez. Bu projection
modelden yeni veri istemez ve business karar üretmez. Marketplace/API hesabının iç DB id'si
kullanıcıya hedef kayıt kimliği olarak gösterilmez; hesap adı/platform/environment yalnız
canonical account scope evidence'ından gelir. Yeni odak regresyonu ile tam Orders task
runtime paketi `357 passed / 371 skipped` sonucuyla geçmiştir. Sonraki organik kampanya R283,
değişen source fingerprint nedeniyle turn 1'den ve yeni process/artifact'tan başlamalıdır.

2026-08-12 Karar 137, R283'ün aynı doğal başlangıç isteğinde ikinci bir genel açığı
yakaladığını kaydeder. Exact DeepSeek V4 Flash doğru typed action interpretation üretmiş
fakat model GoalPlan'da yalnız `orders.query` seçmiş; observation evaluator “güncelle”yi
kargo/etiket/durum mutasyonu gibi yorumlayarak gereksiz clarification istemiştir. Kullanıcının
“sipariş verilerimi şimdi güncelle” ifadesi Türkçe iyelik eki nedeniyle mevcut exact phrase
matcher'a girmemiştir. R283 turn 1'de failed finalize edilmiş, hiçbir prepare/execute/API/DB
işlemi yapılmadan process kapatılmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r283-deepseek-v4-flash-organic-50-2026-08-11.json`.

Yeni invariant, canonical Orders data-refresh intent'ini üretken Türkçe biçimbilgisiyle
tanır: `verilerimi`, `verilerimizi`, `sipariş verisini/verilerini` gibi data noun'ları
`çek/güncelle/yenile/senkronize et` fiilleriyle ilişki kurduğunda intent sync'tir. Bu ilişki
`siparişin kargo durumunu güncelle` gibi gerçek record mutation cümlelerini kapsamaz.
`orders.fetch.prepare` ayrıca çözdüğü exact hesapların canonical `store_name`, platform ve
environment metadata'sını authoritative prepare sonucuna ekler; scope sorusu için bütün
sipariş popülasyonunu okumak gerekmez. Pending projection bu kanıtı kullanıcıya gösterirken
iç DB account id'sini gizli tutar. Orders runtime + provider + chat paketi
`478 passed / 372 skipped` sonucuyla geçmiştir. R284 yeni source fingerprint ve yeni artifact
ile turn 1'den başlamalıdır.

2026-08-12 Karar 138, R284'ün business operation çalışmadan shared cloud-turn deadline'da
fail-closed durduğunu kaydeder. Exact V4 Flash interpretation yanıtını vermiş, ilk structured
GoalPlan çağrısı boş kalmış ve aynı exact model guarded JSON degradation ile plan üretmiştir;
ancak effectful plan için açılan ayrı LLM semantic-verdict çağrısı 180 saniyelik ortak bütçeyi
tüketmiştir. Runtime bunu doğru biçimde `turn_deadline / runtime`, retryable=false ve
fallback=false kaydetmiş; hiçbir tool/API/DB işlemi yapılmamıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r284-deepseek-v4-flash-organic-50-2026-08-12.json`.

Yeni invariant: model-authored effectful plan; typed mode/objective, operation binding,
owner domain, read-only/direct-execute yasağı, schema/policy ve explicit operation intent
ile deterministik olarak tam eşleşiyorsa bağımsız LLM semantic verdict sonucu zaten kararı
değiştiremez. Önceki runtime böyle bir deny veya malformed cevabı da deterministic explicit
intent nedeniyle override ediyordu. Bu non-authoritative dördüncü provider çağrısı artık
atılır ve `model_verdict.skipped=true` audit kanıtıyla kaydedilir. Belirsiz, çelişkili veya
deterministic explicit-intent kanıtı olmayan effectful planlarda bağımsız model verifier
zorunlu kalır ve deny/clarify kararı uygulanır. `orders.fetch.prepare` explicit intent kanıtı,
aynı ortak Türkçe data-refresh matcher'ını goal ve typed step objective üzerinde ayrı ayrı
doğrular; duplicated phrase logic yoktur. Odak semantic testleri ve tam Orders runtime
paketi `359 passed / 373 skipped` sonucuyla geçmiştir. R285 fresh process/artifact ile
turn 1'den başlamalıdır.

2026-08-12 Karar 139, R285'te süre sorununun kalktığını fakat iki model-authored planın da
yanlış `orders.query` operation'ını seçtiği için güvenli biçimde reddedildiğini kaydeder.
Interpretation data-refresh action'ını doğru anlamış; ilk plan ile bounded repair yalnız
mevcut siparişleri listelemeyi önermiştir. Compiler zorunlu `orders.fetch.prepare` eksikliğini
tespit etmiş fakat business step'i model yerine eklememiş; hiçbir tool/API/DB çalışmamıştır.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r285-deepseek-v4-flash-organic-50-2026-08-12.json`.

Yeni invariant: typed action interpretation açık Orders data-refresh sinyali taşıdığında
semantic contract `action_intent=data_refresh`, `required_operation_ids=[orders.fetch.prepare]`
ve exact requested projection'ı plan modeline baştan verir. Model yanlış plan kurarsa compiler
`required_operation_missing:<exact_operation_id>` reason code'unu üretir; bounded semantic
repair promptu bunun model tarafından exact operation ve typed arguments ile yazılması
gerektiğini açıklar. Runtime yine eksik operation'ı kendi başına eklemez, execute etmez veya
approval'ı atlamaz. Odak plan-repair testleri ve tam Orders runtime paketi
`359 passed / 373 skipped` sonucuyla geçmiştir. R286 yeni frozen source ile turn 1'den
başlamalıdır.

2026-08-12 Karar 140, R286'da modelin doğru `orders.query -> orders.fetch.prepare`
GoalPlan'ını kurduğunu fakat operation parametresini izinsiz genişlettiğini kaydeder.
Kullanıcı yalnız sipariş verilerini istemesine rağmen model `fetch_returns=true` yazmış ve
pending action siparişlerle birlikte iadeleri de çekmeye hazırlanmıştır. Onay verilmemiş,
execute/API/DB etkisi oluşmamıştır. Aynı turda task runtime verified
`MDB / TRENDYOL / production` pending projection'ını doğru üretmiş; chat adapter bunu son
prepare step'inin daha dar ham mesajıyla ezdiği için kullanıcı scope'u görememiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r286-deepseek-v4-flash-organic-50-2026-08-12.json`.

Yeni invariant: typed data-refresh contract `include_returns` boolean boyutunu açıkça taşır.
Model-authored `orders.fetch.prepare` arguments bu ortak semantic-contract doğrulayıcısından
hem plan compile aşamasında hem step pre-execution aşamasında geçer. Sipariş-only hedefte
`fetch_returns=true` `unrequested_return_fetch_expansion`; sipariş+iade hedefinde false/missing
değer `requested_return_fetch_missing` reason code'uyla reddedilir ve yalnız bounded model
repair bunu düzeltebilir. Ayrıca chat task projection'ı pending durumda verified
`data.answer/final_answer` değerini öncelikli kullanır; ham son-step mesajı yalnız verified
projection yoksa fallback'tir. Odak testler ve Orders runtime + chat paketi
`440 passed / 374 skipped` sonucuyla geçmiştir. R287 fresh process/artifact ile turn 1'den
başlamalıdır.

2026-08-12 Karar 141, strong-model-first R287 organik kampanyasının ilk dört turunun
başarıyla ilerlediğini fakat beşinci turda yeni bir sohbet-sürekliliği açığı yakaladığını
kaydeder. Exact DeepSeek V4 Flash; sipariş-only senkronu `MDB / TRENDYOL / production`
kapsamında onaya hazırlamış, onaydan sonra 1/1 sipariş ve 1/1 kalem DB exact-key read-back
ile doğrulanmış, güncel hazır sayısını 0 vermiş ve 3119 toplam siparişi
`Cancelled 110 + Delivered 2957 + UnDeliveredAndReturned 52` olarak matematiksel tutarlı
birleştirmiştir. Ardından kullanıcı bu authoritative dağılımdaki exact
`UnDeliveredAndReturned` grubunun en yeni beş kaydını istediğinde interpretation bu tek kodu
hem `undelivered_and_returned` hem `undelivered` üyesine genişletmiş; Orders sorgusu da
provider-independent snake_case adları persisted Trendyol kodlarına çevirmediği için 0 kayıt
dönmüş ve ajan gereksiz clarification istemiştir. Kampanya ilk kritik sapmada failed finalize
edilip durdurulmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r287-deepseek-v4-flash-organic-50-2026-08-12.json`.

Yeni invariant: exact `UnDeliveredAndReturned` tek lifecycle status'tur; yalnız kullanıcı
plain `UnDelivered` grubunu ayrıca adlandırırsa iki üyeli status seti kurulur. AI tool'u
marketplace kod haritası kopyalamaz. Orders-owned `canonical_order_status_code` snake_case,
case ve separator varyantını persisted canonical koda çevirir; sorgu tarihsel
`ReadyToShip`/`Created` uyumluluğu için hem raw hem canonical filtre kodunu korur. Böylece
manuel ve agentic okumalar aynı domain normalizasyonunu kullanır.

2026-08-12 Karar 142, R288 focused source-app tekrarında status filtresinin kapandığını ama
response projection'da ikinci bir rol karışması bulunduğunu kaydeder. `orders.query` doğru
tek status ile 52 kaydı bulmuş ve en yeni 5 satırı observation'a koymuştur; ancak
`UnDeliveredAndReturned` içindeki `Returned/iade` sözcüğü alan çıkarıcı tarafından
return/claim ayrıntı projeksiyonu sanılmıştır. Response verifier sipariş listesinde gereksiz
`return_context_evidence_missing` üretmiş; model adayı ve bounded repair grounded olduğu
halde reddedilmiş, deterministic fallback yalnız “52 sipariş eşleşti” diyerek istenen beş
satırı gizlemiştir. R288 failed finalize edilmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r288-deepseek-v4-flash-exact-status-replay-2026-08-12.json`.

Yeni invariant: lifecycle status filtresi ile response field projection ayrı typed rollerdir.
`UnDeliveredAndReturned`, `iade dönen` veya eşdeğer status ifadesindeki return sözcüğü tek
başına `returns` alanı istemez. Kullanıcı status ifadesinin dışında iade detayı/nedeni/claim
bağlamını açıkça isterse `returns` projeksiyonu korunur. Exact tek status, açık return detayı,
iki/üç status seti ve ratio varyantları aynı ortak semantic field contract'ında test edilir.

2026-08-12 Karar 143, R289 fresh offscreen full-source-app tekrarının exact DeepSeek V4 Flash
ile geçtiğini kaydeder. Model-authored GoalPlan `orders.query` operation'ını
`statuses=[undelivered_and_returned]`, `sort=order_date_desc`, `limit=5` ile kurmuştur.
Authoritative sonuç 52 total / 5 listed; beş satırın tamamı
`UnDeliveredAndReturned` ve tarihler azalan sıradadır. Görünür cevap sipariş no, tarih,
tutar/TRY ve kargo firmasını eksiksiz taşımış; müşteri, adres ve telefon göstermemiştir.
Model fallback kullanılmamış, final response
`model_authored_verified_projection / verified_model_candidate` olarak kabul edilmiş ve
focused artifact validation problems olmadan passed finalize edilmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r289-deepseek-v4-flash-exact-status-list-pass-2026-08-12.json`.
Odak testler ile geniş Orders runtime/domain paketi
`447 passed / 376 skipped / 37 subtests passed` sonucuyla geçmiştir. Bu focused kapanış
50+ tur organik kabulün yerine geçmez; R290 yeni source fingerprint ve yeni artifact ile
turn 1'den başlamalıdır.

2026-08-12 Karar 144, R290 fresh organik kampanyasının ilk beş turda senkron prepare ->
approval/execute/read-back -> güncel hazır sayısı -> toplam/durum dağılımı -> exact
`UnDeliveredAndReturned` en yeni beşli liste zincirini başarıyla geçtiğini; altıncı ordinal
detail turunda ise ortak cloud-turn deadline'a ulaştığını kaydeder. Beş kayıtlı immutable
selection ve açık “üçüncü sipariş” hedefi bulunmasına rağmen ilk structured turn
interpretation kesik JSON üretmiş, bounded interpretation repair yeniden structured kanala
girip boş cevap bekledikten sonra guarded JSON ile düzelmiş, asıl GoalPlan structured çağrısı
başladığında 180 saniyelik ortak bütçe tükenmiştir. Hiçbir tool veya dış etki çalışmamış;
görünür cevap kullanıcıdan gereksiz biçimde yeniden ifade/tekrar istemiştir. Kampanya turn 6'da
failed finalize edilmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r290-deepseek-v4-flash-organic-50-2026-08-12.json`.

Yeni invariant: bounded JSON/semantic repair, aynı exact modelin zaten başarısız olmuş
structured-output kanalını ikinci kez tam timeout boyunca denemez. Provider adapter'ın
önceden wired `invoke_json_text` kanalı aynı provider/model, authoritative JSON schema,
fallback policy ve shared deadline ile doğrudan kullanılabilir. Bu tercih yalnız açık repair
çağrılarına aittir; ilk typed interpretation, ilk GoalPlan ve business kararları normal en güçlü
structured/native model yolunda kalır. Turn interpretation, GoalPlan JSON, semantic plan,
derived formula ve privacy projection repair'leri bu ortak çağrı sözleşmesini kullanır;
operation veya business step deterministic katman tarafından eklenmez. Provider + Orders
runtime/domain geniş paketi `490 passed / 377 skipped / 37 subtests passed` sonucuyla
geçmiştir. R291 fresh process'te focused list -> ordinal detail kapanışını kanıtlamalı; geçse
bile R292 organik 50+ kampanyası turn 1'den yeniden başlamalıdır.

2026-08-12 Karar 145, R291 fresh focused source-app list -> ordinal detail tekrarının exact
DeepSeek V4 Flash ile geçtiğini kaydeder. İlk tur exact
`UnDeliveredAndReturned`, `order_date_desc`, limit 5 selection üretmiş; ikinci tur bu listenin
üçüncü `RecordRef` kimliğini tek `orders.full_context` operation'ına bağlamıştır. İkinci turda
ilk structured response boş kalınca aynı model `json_text_guarded` kanalına doğrudan geçmiş;
ardından model-authored GoalPlan, observation evaluation ve final synthesis ortak deadline
içinde tamamlanmıştır. Tur 145 saniye sürmüş; önceki 188 saniyelik deadline failure tekrarlanmamış,
tool sonucu exact üçüncü kimlikle eşleşmiştir. Görünür cevap `UnDeliveredAndReturned` durumunu,
tek ürün adını/adet 1'i ve 94.99 TRY toplamı taşımış; müşteri, adres, telefon veya takip bilgisi
göstermemiştir. Fallback kullanılmamış, artifact validation problems olmadan passed finalize
edilmiştir. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r291-deepseek-v4-flash-ordinal-repair-pass-2026-08-12.json`.
Bu focused geçiş organik 50+ kabulü değildir; R292 yeni source fingerprint ve turn 1 ile
başlamalıdır.

2026-08-12 Karar 146, kullanıcı tarafından güçlü-model-first test sırasını yeniden teyit
eder ve bir sonraki hedef çalışması için bağlayıcı hale getirir. Ücretli OpenRouter
development/control/focused ve organik kabul koşuları fallback kapalı exact
`deepseek/deepseek-v4-flash` ile yürütülür. Ücretsiz kabulte Gemini ve OpenRouter ayrı ayrı
ele alınır; her provider'da canlı katalog, hesap erişimi ve merkezi quality-tier kanıtına
göre erişilebilen en güçlü ücretsiz aday seçilir. Bu güçlü ücretsiz aday yalnız gerçek
model-kapsamlı kota veya erişilemezlik kanıtı varsa aynı provider'daki sıradaki güçlü adaya
devredilebilir. Nispeten düşük-tier cloud modeller, küçük modeller, local inference ve
degradation/dayanıklılık kampanyaları bu aşamada başlatılmaz; güçlü ücretli kontrol ve her
iki provider'ın güçlü ücretsiz baseline'ları kararlı hale geldikten sonra ayrı capability
matrisinde ele alınır. Bu sıralama zayıf model davranışının ortak agent runtime kusurlarını
gizlemesini engelleyen bir geliştirme önceliğidir; nihai provider/model bağımsızlığı ve
 ücretsiz model kabul şartını kaldırmaz.

2026-08-12 Karar 147, exact DeepSeek V4 Flash R293-R297 focused zincirinin
“birden çok doğrudan aggregate + tek türetilmiş sonuç” failure sınıfını kapattığını
kaydeder. R293'te model toplam sipariş, durum dağılımı ve ciroyu tek operandlı
formüller gibi; R295'te toplam sipariş ile unscoped durum dağılımını geçersiz bir
`add` formülünde paketlemiş, runtime bütün açık hedefi clarification'a düşürmüştür.
Typed turn contract artık modelin görünür projection'ında ve kullanıcının açık geniş
analiz hedefinde bulunan bağımsız base metrikleri `direct_projection` olarak korur;
yalnız canonical direct aggregate ref'lerinden oluşan unary/additive kimlik paketlerini
business hesabı saymaz. Bu uzlaştırma ancak yanında en az bir geçerli model-authored
hesap kaldığında uygulanır; scoped status üyesi, literal, gizli operand veya gerçek
tek/çoklu aritmetik istek sessizce düşürülemez. Bağsız product-sales alanları hem normal
hem direct projection'dan çıkarılır.

Aynı zincir transport katmanındaki ortak deadline kaybını da göstermiştir. Seçili exact
model structured-output kanalında cevapsız kalıp aynı modelin guarded JSON sözleşmesiyle
başarıyla toparladıysa, aynı client içindeki sonraki planner fazı başarısız wire contract'a
yeniden girmez; provider/model/fallback değişmeden doğrulanmış guarded JSON kanalını kullanır.
Bu business plan fallback'i değil provider-independent contract-health kararıdır ve bütün
invocation provenance'inde görünür kalır. R294'teki tekrar structured bekleme yüzünden
oluşan deadline failure bu yolla kapanmıştır.

R296 sayıları doğru üretmiş ancak kullanıcı açıkça mağaza ve ortam sorduğu halde yalnız
`MDB` yazmış; verifier `store` alanını tam scope sanarak cevabı kabul etmiştir. Açık hesap/
mağaza/ortam hedefi derived projection içinde first-class `scope` olarak korunur ve görünür
cevap canonical `store_name + platform + environment` üçlüsünü taşımadan geçemez. R297
fresh offscreen full-source-app koşusunda exact `deepseek/deepseek-v4-flash`, fallback
kapalıyken model-authored tek `orders.summary` planını çalıştırmış; authoritative sonuç
`3119` toplam, `Cancelled 110 / Delivered 2957 / UnDeliveredAndReturned 52`,
`503446.47 TRY` ve `MDB (TRENDYOL / production)` üretmiştir. Core doğrulanmış hesap
`503446.47 / 3119 = 161.41 TRY/siparis` sonucunu vermiş; görünür cevap bütün boyutlarla
eşleşmiş, PII taşımamış ve acceptance validation `problems=[] / passed` olmuştur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r297-deepseek-v4-flash-mixed-overview-pass-2026-08-12.json`.
Focused ve tam Orders runtime kanıtı son kaynakta `370 passed / 384 skipped / 37 subtests
passed`; provider contract-health focused kanıtı `3 passed` sonucudur. R297 focused kapanış
50+ organik kabul değildir; sonraki kampanya fresh process, fresh artifact ve turn 1 ile
başlamalıdır.

2026-08-12 Karar 148, R298-R301 organik exact DeepSeek V4 Flash başlangıçlarının ilk
kritik failure'da durdurulduğunu ve görünen tek cümleye özel yama yazılmadığını kaydeder.
R298 selamlaşmada doğrulanmamış “siparişler hazır”, R299 doğrulanmamış “sipariş cephesinde
her şey yolunda” iddiası üretmiştir. Non-business cevap güvenlik sınırı artık asistanın
“ben hazırım” ifadesini işletme kayıtlarının hazır/sorunsuz/tamam olduğu iddiasından ayırır;
typed observation yoksa sipariş, iade, stok, ilan, kargo, etiket veya ödeme durumuna ilişkin
operasyonel hazır oluş/temiz durum iddiasını reddedip doğal ve effectsiz bir sohbet cevabı
üretir. Bu doğrulayıcı intent veya tool seçmez; yalnız görünür model adayının kanıtla uyumunu
denetler.

R300'de “API'den yeni veri çekme; mevcut yerel kayıttan oku” cümlesindeki external refresh
yasağı yanlışlıkla hem `orders.fetch.prepare` niyeti hem de bütün yeni operation'ları
yasaklayan `existing_observations_only` olarak derlenmiştir. External API sync izni ile
authoritative local DB read izni artık ayrı typed policy boyutlarıdır: açık sync yasağı fetch
üretmez ve aynı cümlede istenen local read'i engellemez. R301 turn 2 bu sınırı gerçek source-app
yolunda doğrulamış; yalnız `orders.count` çalıştırıp API sync/approval/DB write olmadan `3119`
ve `MDB (TRENDYOL / production)` üretmiştir.

R301 yine de full-agentic tur olarak kabul edilmemiştir: ilk model yorumunun bounded repair'i,
model-authored plan ve gereksiz terminal GoalPlan değerlendirmesi ortak tur bütçesini tüketmiş;
son doğal cevap çağrısı `turn_deadline_exceeded` olmuş ve görünür doğru sonuç verified
deterministic projection'dan gelmiştir. Yeni invariant, model-authored terminal read adımını
yalnız ilk plan revizyonunda; geçerli typed turn contract, eksiksiz metric/projection coverage,
semantic verifier geçişi, sıfır deterministic business-step insertion ve beklenen observation
kanıtı birlikte varsa ikinci kez modele değerlendirtmeden `complete` yapar. Typed contract'ı
olmayan eksik hedef, eksik evidence veya model-replan sonrası terminal adım bu optimizasyona
giremez; normal evaluate/replan/clarify döngüsünü sürdürür. Focused sınır testleri ve tam Orders
runtime paketi son kaynakta `374 passed / 388 skipped / 37 subtests passed` sonucuyla geçmiştir.
R301 artifact'i failed olarak korunur; sonraki 50+ kampanya yeni source fingerprint, fresh
process/artifact ve turn 1 ile başlamalıdır.

2026-08-17 Karar 149, R302-R305 focused zincirinde ortaya çıkan iki ortak contract kusurunu
ve exact güçlü-model taşıma davranışını bağlayıcı hale getirir. R302'de `tutarlı` sözcüğünün
`tutar` alt dizisi gibi okunması istenmeyen ciro/para birimi projeksiyonu üretmiş; ayrıca düz
derived-calculation sözleşmesi durum adetleri toplamını authoritative sipariş toplamıyla
ilişkilendiren açık eşitliği taşıyamamıştır. Projection alanı artık sözcük/çekim sınırında
çözülür. Typed derived contract, aynı canonical operand sözleşmesini kullanan
`comparison.operator + comparison.operand` ilişkisini taşır; formül ve karşılaştırma model
tarafından kurulup bounded aynı-model repair'den geçer, aritmetik ve ilişki Core tarafından
ayrı evidence hash'leriyle doğrulanır. Görünür cevap sonucu yalnız sayı olarak değil,
`tutarlı/tutarsız` ve doğrulanmış karşılaştırma ifadesiyle projekte eder.

R303'te model `local_business_data` kaynağını doğru seçmesine rağmen “API'den yeni veri
çekmeden mevcut yerel snapshotta oku” ifadesi `existing_observations_only` politikasına
genişletilmiş ve hiçbir yerel Orders read çalışmamıştır. External marketplace refresh izni,
durable local business read izninden bağımsızdır. Ortak dil sınırı artık yerel/lokal/local
kayıt, snapshot, veritabanı/database, DB, cache ve önbellek kaynaklarını okuma niyetleriyle
birlikte tanır; `çekmeden`, `güncellemeden`, `yenilemeden` ve `senkronize etmeden` biçimleri
pozitif fetch niyeti sayılmaz. Açık “yerel snapshotı okuma” yasağı ise gerçek
`existing_observations_only` sınırı olarak korunur. Bu kural yalnız tek kullanıcı cümlesine
değil bütün Orders intent'lerine ortak semantic boundary'de uygulanır.

R304 turn 1 bu ayrımı exact `deepseek/deepseek-v4-flash`, fallback kapalı gerçek source-app
yolunda yalnız `orders.summary` ile kanıtlamış; `3119` toplamı, `Cancelled 110`,
`Delivered 2957`, `UnDeliveredAndReturned 52` dağılımını ve
`MDB (TRENDYOL / production)` kapsamını doğru göstermiştir. Turn 2 HTTP/kota kanıtı olmayan
bir OpenRouter transport failure nedeniyle business runtime'a ulaşmadan kapanmıştır. Exact
model rotası artık HTTP cevabı oluşmadan düşen retryable transport ve açık 5xx hatalarında
aynı promptu aynı modelde bounded en fazla üç kez dener; auth/policy/billing, 429 veya bozuk
upstream credential rotasını körlemesine tekrarlamaz ve sibling/zayıf modele geçmez.

Fresh R305 iki turluk focused kabulü tamamlamıştır. Turn 1 yine yalnız yerel
`orders.summary` ile aynı total/status/scope cevabını üretmiş; turn 2 hiçbir yeni tool/API/DB
işlemi çalıştırmadan önceki typed observation'lardan model-authored ve model-repaired
`110 + 2957 + 52` formülünü ve `equal orders.total_count` karşılaştırmasını kurmuştur. Core
sonucu `3119` ve ilişkiyi `3119 = 3119` olarak doğrulamış; görünür cevap
`Tutarlılık: tutarlı` demiş, istenmeyen ciro/TRY alanı veya PII taşımamıştır. Requested ve
actual model exact eşleşmiş, fallback kullanılmamış ve source-app acceptance
`problems=[] / passed` kapanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r305-deepseek-v4-flash-status-consistency-2026-08-16.json`.
Bu focused kapanış 50+ organik kabul değildir. Son ortak test kanıtı Core + Orders runtime
 `382 passed / 1 skipped`, provider adapter paketi `44 passed` sonucudur; sıradaki çalışma
 fresh process/artifact ve turn 1 ile 50+ exact DeepSeek V4 Flash organik kampanyasıdır.

2026-08-17 Karar 150, yeniden başlatılacak hedefin model/test önceliğini kesinleştirir.
Bu aşamadaki amaç zayıf model dayanıklılığını ölçmek değil, ortak agent mimarisinin gerçek
kapasitesini mümkün olan en yüksek sinyalle sınamaktır. Bu nedenle test sırası şöyledir:

1. Ücretli OpenRouter kontrolü fallback kapalı ve exact
   `deepseek/deepseek-v4-flash` ile yürütülür. Requested ve actual model her turda aynı
   olmalı; fark, sessiz fallback veya başka modele geçiş kabul edilmez.
2. Ücretsiz kabul Gemini ve OpenRouter için birbirinden bağımsız yürütülür. Her provider'da
   canlı katalog, hesap erişimi ve merkezi quality-tier politikasına göre o anda erişilebilen
   en güçlü ücretsiz model seçilir. Ücretsiz bir provider'ın başarısı diğerinin yerine geçmez.
3. Seçilen güçlü ücretsiz model ancak kanıtlanmış model-kapsamlı kota veya gerçek
   erişilemezlik durumunda aynı provider'daki sıradaki güçlü adaya devredilebilir. Düşük-tier
   modele geçerek ortak runtime kusurunu maskelemek yasaktır.
4. Nispeten düşük güçlü ücretli/ücretsiz cloud modeller, küçük modeller, local inference ve
   degradation/dayanıklılık kampanyaları şimdilik bekletilir. Bunlar DeepSeek V4 Flash ile
   güçlü ücretsiz Gemini/OpenRouter baseline'ları kararlı hale geldikten sonra ayrı capability
   matrisinde ele alınır.
5. Güçlü modelde görülen yanlış tool, bozuk scope, kayıp state, yetersiz replan, hatalı
   synthesis veya doğrulanmamış sonuç varsayılan olarak “model yetersizliği” sayılmaz. Önce
   catalog/retrieval, typed intent/state, GoalPlan compiler, operation contract, observation,
   verifier ve final projection zincirindeki sistemik sahip katman bulunup düzeltilir.
6. Her gerçek LLM cevabı Codex tarafından bizzat okunur. Bir kritik görünür sapmada kampanya
   durdurulur, kök neden cümleye/model adına özel yama olmadan düzeltilir ve uzun kampanya
   fresh process, fresh artifact ve turn 1 ile yeniden başlatılır.

Bu karar local ve daha zayıf model desteğini ürün vizyonundan kaldırmaz; yalnız mevcut Orders
kapanışında geliştirme zamanını en güçlü ücretli ve ücretsiz cloud modellerden alınan yüksek
sinyalli kanıta ayırır. Ücretli DeepSeek başarısı ücretsiz kabul kapısının, ücretsiz başarı da
provider/model bağımsız mimari ve daha sonraki capability sınıflandırmasının yerine geçmez.

2026-08-17 Karar 151, R306-R310 latest-order focused failure zincirini ve kapanışını
bağlayıcı kanıta dönüştürür. R306'nın beşinci turunda “en son gelen sipariş” için istenen tek
kayıt toplamı aggregate `orders.revenue_total` gibi derlenmiş; doğru `orders.recent`
observation'ından sonra kapsam daraltma ihlali oluşmuştur. Tek kaydın tutarı ile küme cirosu
artık ayrı typed metric'tir. Fresh latest-single niyeti `record_scope=active_selection`,
`limit=1`, `sort=order_date_desc` ve first-class `record_selector.kind=latest` taşır.

R307 doğru bağımlı read zincirini süre içinde tamamlayamamıştır. Model-authored ve semantic
olarak doğrulanmış, bütün expected evidence'ı bulunan read-only zincirlerde her discovery
adımından sonra aynı GoalPlan'ı yeniden modele değerlendirtmek yerine kalan typed read adımları
devam eder; eksik/çelişkili evidence, write, replan veya belirsiz hedef bu optimizasyona giremez.
R308'de model `item` alanını atmış, “kimin olduğunu yazmadan” yasağını kaçırmış ve “toplam
tutar” ifadesini broad summary/count gibi genişletmiştir. Latest-single projection artık açık
ürün alanını korur; Türkçe olumsuz projection çekimleri ortak privacy sözleşmesinde çözülür ve
`toplam` yalnız gerçek count niyeti varsa adet alanı üretir.

R309'da typed contract doğru olmasına rağmen model tek `orders.query` ile record detail
kanıtı üretmeye çalışmıştır. Planner sözleşmesi unresolved latest selector için ilk adımda
`orders.recent`, bulunan `tool_result.order_numbers` bağıyla ikinci adımda
`orders.full_context` ister; tek query/list/recent satırı ürün/detail evidence'ı sayılmaz.
Runtime bu iki business adımı model yerine deterministic olarak eklemez; yanlış ilk aday aynı
exact modelin bounded plan repair'inde düzeltilir veya fail-closed kalır.

Fresh R310 gerçek offscreen source-app koşusunda exact `deepseek/deepseek-v4-flash`, fallback
kapalıyken bu zinciri kendisi yazmış ve `orders.recent -> orders.full_context` çalıştırmıştır.
Görünür cevap authoritative en yeni ürün adını, `Delivered` durumunu ve `299.99 TRY` toplamını
doğru vermiş; müşteri kimliği, adres, iletişim, takip ve sipariş kimliği göstermemiştir. API
refresh, write, approval veya başka yan etki yoktur; requested/actual model aynıdır ve
acceptance `accepted=true / problems=[] / passed` kapanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r310-deepseek-v4-flash-latest-detail-2026-08-17.json`.
Son ortak typed runtime/Core regresyon kanıtı `384 passed / 393 skipped / 44 subtests passed`
sonucudur. R310 yalnız focused kapanıştır; sıradaki bağlayıcı kapı fresh process/artifact ve
turn 1 ile başlayacak en az 50 turluk exact DeepSeek V4 Flash organik source-app kampanyasıdır.

2026-08-17 Karar 152, R311 organik kampanyasının üçüncü turunda bulunan kaynak-izni ve
dinamik aggregate kusurunu kapatır. Kullanıcı önce local `orders.count` ile doğrulanmış `3119`
toplamından sonra durum dağılımını, bu bucket'ların toplamını ve `3119` ile tutarlılığını istemiş;
yalnız “API senkronu yapma” demiştir. Runtime bu dış-kaynak yasağını bütün yeni operation'ların
yasağına genişletmiş, henüz gözlenmemiş `orders.status_count+member` ref'lerini interpretation
aşamasında zorunlu kılmış ve gereksiz clarification ile effectsiz kapanmıştır. R311 üçüncü turda
ilk kritik görünür sapmada durdurulmuş ve failed/human-read artifact olarak korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r311-deepseek-v4-flash-organic-50-2026-08-17.json`.

Yeni invariant iki typed ekseni ayırır. `API/marketplace sync yapma` yalnız external refresh'i
yasaklar; `tool/sorgu/işlem/veri okuma yapma` gibi gerçek no-new-operation talimatları ayrı
`existing_observations_only` sınırını korur. Aynı turda henüz isimleri gözlenmemiş bütün status
bucket'larını modelden uydurması beklenmez. Model `add` üzerinde tek canonical collection operand
`orders.status_counts` yazar; canonical Orders status operation'ı gerçek bucket'ları getirir,
response verifier collection'ı authoritative scalar operandlara açar ve Core toplamı immutable
aritmetik/karşılaştırma evidence'ıyla doğrular. Tek bir belirli statü için mevcut
`orders.status_count+member` sözleşmesi değişmez; collection ref comparison operandı olamaz ve
başka scalarlarla belirsiz biçimde karıştırılamaz.

Fresh R312 iki turluk exact DeepSeek V4 Flash source-app tekrarında önce local `3119` ve
`MDB / TRENDYOL / production` kapsamını okumuş; ikinci turda model-authored
`orders.status_counts + orders.count` planı ile model-repaired
`add(orders.status_counts) == orders.total_count` sözleşmesini kurmuştur. Görünür cevap
`Cancelled 110`, `Delivered 2957`, `UnDeliveredAndReturned 52`,
`110 + 2957 + 52 = 3119` ve `Tutarlılık: tutarlı (3119 = 3119)` içermiştir. PII, ciro drift'i,
API sync, write, approval, side effect veya fallback yoktur; acceptance
`accepted=true / problems=[] / passed` kapanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r312-deepseek-v4-flash-dynamic-status-sum-2026-08-17.json`.
Son ortak typed runtime/Core regresyonu `385 passed / 394 skipped / 44 subtests passed` sonucuyla
geçmiştir. R312 focused kanıttır; en az 50 turluk organik kampanya yeni source fingerprint,
fresh process/artifact ve turn 1 ile yeniden başlar.

2026-08-17 Karar 153, R313-R317 zincirinde görülen derived-comparison lehçesi ve minimal
plan repair kusurlarını aynı typed verifier sınırında kapatır. R313'te güçlü model toplama ile
eşitlik kontrolünü iki ayrı calculation satırı olarak yazmış; ikinci satır business hesabı
olmayan `eq_check` pseudo-formülü biçimindeydi. Runtime artık provider'ın `operand_refs`
eşadını typed operands'a çevirir ve açık karşılaştırma istenen tek aritmetik hedefte bu lehçeyi
tek `derived_calculation + comparison` sözleşmesine model-authored bounded repair ile indirger;
deterministik katman sayıları veya iş sonucunu üretmez.

R314'te görünür sayı ve hesap doğru olmasına rağmen model aynı kapsam için
`orders.count + orders.status_counts + orders.summary` çalıştırmıştır. Bu cevap minimal plan
invariant'ını ihlal ettiği için manuel incelemede başarısız sayılmıştır. Canonical result
schema'larından metric/projection coverage çıkaran verifier, bağımsız ve aynı exact scope'taki
read kombinasyonları arasında en küçük kapsayıcı kümeyi hesaplar; step sayısı eşitse daha dar
result surface ve sonra model plan sırası tiebreak'tir. Verifier operation eklemez, silmez veya
çalıştırmaz; yalnız yanlış model planını execution öncesi reason-code ile reddeder.

R315 ve R316'da fail-closed sınırı doğru çalışmış fakat aynı model salt metin hata kodundan
minimal kümeyi iki denemede de tamamlayamamış; ilk üçlü planı repair'de
`orders.count + orders.status_counts` olarak bırakmıştır. Bu nedenle repair prompt'una yeni
phrase veya business workflow eklemek yerine verifier'ın zaten hesapladığı kanıt makine-okunur
hale getirilmiştir: `minimal_metric_cover_operation_ids`, `redundant_metric_operation_ids` ve
operation başına metric coverage. Bu veri rejected model planı ile canonical schema'lardan
gelir; hedefin cevabını veya çalıştırılacak adımı deterministic katman seçmez. Repaired planı
yine aynı LLM yazmak zorundadır ve ikinci verifier geçişinden geçmeden hiçbir tool çalışmaz.

Fresh R317 gerçek offscreen source-app tekrarında exact `deepseek/deepseek-v4-flash`, fallback
kapalıyken ilk olarak aynı gereksiz üçlü planı yazmış; verifier execution öncesi
`orders.count` ile `orders.summary` okumalarını reddetmiş ve minimal witness olarak yalnız
`orders.status_counts` kanıtını taşımıştır. Aynı model repair çağrısı planı tek canonical read
adımına indirmiştir. Yalnız `orders.status_counts` çalışmış; görünür cevap authoritative
`Cancelled 110`, `Delivered 2957`, `UnDeliveredAndReturned 52`,
`110 + 2957 + 52 = 3119` ve `3119 = 3119` kanıtını doğru vermiştir. API sync, approval,
write, artifact yan etkisi veya fallback yoktur; requested/actual model aynıdır. Manuel review
sonrası acceptance `accepted=true / problems=[] / passed` kapanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r317-deepseek-v4-flash-minimal-status-total-2026-08-17.json`.
Güncel ortak typed runtime/Core regresyonu `387 passed / 396 skipped` sonucuyla geçmiştir.
R317 focused kanıttır; Faz 8B kapanışı değildir. Sıradaki kapı fresh process/artifact ve turn
1 ile başlayacak en az 50 turluk exact DeepSeek V4 Flash organik source-app kampanyasıdır.

2026-08-17 Karar 154, R318-R320 zincirinde güçlü model kalitesinden bağımsız turn-budget ve
provider JSON dialect dayanıklılığını bağlayıcı hale getirir. R318 organik kampanyasında doğal
no-operation sohbet turu geçmiş; ikinci turdaki basit local count+scope hedefi ise
interpretation -> interpretation repair -> plan -> plan repair çağrı zincirinde ortak 180
saniyelik runtime deadline'ı tüketmiştir. Üç model cevabı alınmasına rağmen son repair isteği
provider'a gönderilemeden `turn_deadline_exceeded` oluşmuş, hiçbir business tool çalışmamış ve
kullanıcı yalnız fail-closed mesaj görmüştür. Bu kota veya fallback değildir. Kampanya ilk
kritik görünür sapmada durdurulmuş ve failed artifact olarak korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r318-deepseek-v4-flash-organic-50-2026-08-17.json`.

Kök düzeltme timeout'u körlemesine büyütmez ve deterministic business plan yazmaz. Provider
structured-output cevabının istenen tek object'i singleton array içinde veya GoalPlan'ı
`goal_plan/plan/task_plan` object zarfında döndürmesi, içerideki operation ve arguments aynı
catalog/schema/policy verifier'dan geçmek şartıyla ortak JSON dialect canonicalization'dır.
İlk structured response parse/top-level schema doğrulamasından geçmezse raw içerik tutulmadan
yalnız hash/length/value-free shape gözlenir; aynı exact client sonraki planner fazlarında aynı
kanıtlanmış bozuk structured kanala tekrar girmez ve fallback/model değiştirmeden wired guarded
JSON kontratını kullanır. Semantik olarak yanlış fakat geçerli JSON bu transport-health
downgrade'ını tetiklemez; yine model repair/verifier sınırında kalır.

R319 görünür olarak `orders.count -> 3119 / MDB / TRENDYOL / production` sonucunu doğru vermiş,
ancak artifact finalize edilmeden source değiştirildiği için sürücü
`runtime_source_changed_restart_required` üretmiştir. Bu koşu bilerek passing kanıt sayılmaz.
Fresh R320, yeni fingerprint üzerinde exact `deepseek/deepseek-v4-flash`, fallback kapalıyken
67.953 saniyede yalnız üç model cevabıyla `interpretation -> plan -> final` akışını repair
olmadan tamamlamıştır. Yalnız canonical `orders.count` local read çalışmış; görünür cevap
authoritative `3119` ile `MDB / TRENDYOL / production` kapsamını vermiştir. API sync, approval,
write veya başka yan etki yoktur; acceptance `accepted=true / problems=[] / passed` kapanmıştır.
Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r320-deepseek-v4-flash-local-count-scope-contract-health-2026-08-17.json`.
Güncel runtime/provider/Core regresyonu `434 passed / 398 skipped` sonucuyla geçmiştir. R320
focused kanıttır; en az 50 turluk organik kampanya yine fresh process/artifact ve turn 1 ile
yeniden başlar.

2026-08-17 Karar 155, hedef yeniden başlatıldığında uygulanacak güçlü-model-öncelikli test
disiplinini yeniden teyit eder. Ücretli OpenRouter geliştirme ve kabul koşularının birincil
referansı exact `deepseek/deepseek-v4-flash`tır; fallback kapalıdır ve requested/actual model
eşleşmesi her turda kanıtlanır. Ücretsiz tarafta Gemini ile OpenRouter ayrı ayrı ele alınır ve
her provider için canlı erişim ile merkezi quality-tier politikasına göre erişilebilen en güçlü
ücretsiz model kullanılır. Bir ücretsiz modelin başarısı diğer provider'ın kabulünün yerine
geçmez. Nispeten düşük-tier cloud modeller, küçük modeller ve local modeller bu güçlü ücretli
ve ücretsiz baseline'lar kararlı biçimde geçmeden test sırasına alınmaz. Böylece mevcut aşamada
zayıf model dayanıklılığı değil, agentic runtime'ın en yüksek sinyalli modeller karşısındaki
gerçek kapasitesi ve sistemik kusurları ölçülür. Bu öncelik ürünün provider/model bağımsızlığı
hedefini kaldırmaz; düşük ve local modeller daha sonra ayrı capability/degradation matrisinde
dürüstçe sınıflandırılır.

2026-08-17 Karar 156, R321-R326 per-target hesaplama ve structured-contract latency zincirini
bağlayıcı kanıta dönüştürür. R321 organik kampanyasının üçüncü turunda kullanıcı Delivered ve
Cancelled yüzdelerini ayrı ayrı istemiş; typed contract iki status member'ı taşıdığı halde tek
formül kabul edilmiş ve görünür cevap yalnız `2957 / 3119 = 94.81%` ile kapanmıştır. Kampanya ilk
kritik sapmada durdurulmuş ve failed artifact olarak korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r321-deepseek-v4-flash-organic-50-2026-08-17.json`.

Typed hesap sözleşmesi artık hesap yok/tek sonuç/birleşik hedef/farklı bağımsız sonuç/hedef başına
aynı sonuç ilişkilerini sırasıyla `none`, `single_result`, `combined_targets`,
`independent_results` ve `per_target` olarak ayırır. `per_target` formül kümesi her typed target'ı
tam bir kez kapsamak zorundadır; eksik, beklenmeyen veya yinelenen target aynı exact modelin
bounded formula repair'ine gider. Runtime eksik yüzdeyi veya operandı kendisi yazmaz. Aynı
operator/denominator ile her named target'ı birebir kapsayan bağımsız formül kümesi kayıpsız
olarak `per_target` lehçesine canonicalize edilir. Formülle üretilen yüzde ayrıca authoritative
bir direct `ratio` observation gibi istenemez; base count/status/amount/scope projeksiyonları ise
bağımsız istendiyse korunur.

R322 ve fresh R323, daha ilk kullanıcı turunda 300 saniye boyunca model cevabı alamadan source-UI
timeout ile kapanmıştır. Her iki koşuda tool, API, DB, write, fallback veya tamamlanmış model
kanıtı yoktur ve passing evidence sayılmaz:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r322-deepseek-v4-flash-per-target-status-ratios-2026-08-17.json`,
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r323-deepseek-v4-flash-per-target-status-ratios-retry-2026-08-17.json`.
Aynı hesap/model için secret-safe minimal HTTP health çağrısı 1.938 saniyede `200` döndürmüş;
yalnız typed interpretation diagnostic'i ise 83.187 saniyede structured boş cevap -> guarded JSON
recovery ile tamamlanmıştır. Kök neden bakiye/model erişimi değil, boş structured kontratın aynı
exact modelde gereksiz ikinci kez beklenmesidir. Structured HTTP yanıtı boşsa adapter artık
model/provider/fallback değiştirmeden aynı exact modelin guarded JSON kanalına hemen geçer ve bu
contract-health sonucunu aynı client'ın sonraki planner fazlarında hatırlar.

R324'te ilk iki tur doğru geçmiş; üçüncü turda model aslında iki yüzde formülünü de eksiksiz
yazmış fakat türetilmiş `ratio` sonucunu ayrıca direct base projection ilan ettiği için verifier
hayali üçüncü oran kanıtı aramış ve fail-closed kalmıştır. R325'in ikinci turunda bounded model
repair `add(status_counts, total_count) == total_count` lehçesini üretmiştir. Tek collection,
tek scalar ve comparison operandı aynı scalar olduğunda yinelenen scalar artık kayıpsız biçimde
ana toplama operandlarından çıkarılır; farklı veya belirsiz collection/scalar formülleri hâlâ
reddedilir. İki failed artifact da korunur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r324-deepseek-v4-flash-per-target-status-ratios-2026-08-17.json`,
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r325-deepseek-v4-flash-per-target-status-ratios-2026-08-17.json`.

Fresh R326 exact `deepseek/deepseek-v4-flash`, fallback kapalı gerçek source-app yolunda üç turu
geçmiştir. Tur 1 yalnız `orders.count` ile `3119 / MDB / TRENDYOL / production`; tur 2 yalnız
`orders.status_counts` ile `Cancelled 110`, `Delivered 2957`, `UnDeliveredAndReturned 52` ve
`110 + 2957 + 52 = 3119` tutarlılığını vermiştir. Tur 3 hiçbir yeni tool çalıştırmadan önceki
authoritative observation'lardan `2957 / 3119 × 100 = 94.81%` ve
`110 / 3119 × 100 = 3.53%` sonuçlarını ayrı ayrı, iki ondalık ve işlem kanıtıyla üretmiştir.
Response source `deterministic_existing_observation_projection`, final projection verified,
requested/actual model aynı ve yan etki yoktur; acceptance `accepted=true / problems=[] / passed`
kapanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r326-deepseek-v4-flash-per-target-status-ratios-2026-08-17.json`.
Güncel ortak runtime/provider/Core regresyonu `437 passed / 401 skipped` sonucuyla geçmiştir.
R326 focused kanıttır; Faz 8B kapanışı değildir. Sıradaki kapı fresh process/artifact ve turn 1
ile başlayacak en az 50 turluk exact DeepSeek V4 Flash organik source-app kampanyasıdır.

2026-08-17 Karar 157, R327 organik kampanyasında bulunan birleşik-status hesaplama boşluğunu ve
fresh R330 kapanışını bağlayıcı kanıta dönüştürür. R327'nin ilk üç turu gündelik sohbet, capability
özeti ve tek `orders.summary` ile doğru `3119` toplam, `Cancelled 110 / Delivered 2957 /
UnDeliveredAndReturned 52`, `503446.47 TRY`, `161.41 TRY/sipariş` ve exact production scope
sonuçlarını geçmiştir. Dördüncü turda kullanıcı yeni sorgu istemeden Cancelled ile
UnDeliveredAndReturned bucket'larını birlikte ele alıp hem birleşik adedi hem bütün siparişler
içindeki yüzdesini işlemleriyle istemiştir. Model business hedefini ve bütün operandları doğru
yazmış; ancak yüzde formülünü üç düz operandlı `ratio(Cancelled,
UnDeliveredAndReturned, total_count)` lehçesinde serialize etmiştir. Formula repair aynı ilişkiyi
üç operandlı `divide` olarak tekrarlayınca binary contract bunu reddetmiş ve görünür gereksiz
clarification oluşmuştur. Failed artifact korunur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r327-deepseek-v4-flash-organic-50-2026-08-17.json`.

Typed aritmetik sözleşmesinde artık seçili iki veya daha fazla status bucket'ının kanıtlı toplamını
temsil eden first-class `orders.status_count_sum + members` operandı vardır. Modelin düz yazdığı
iki veya daha fazla `orders.status_count` numerator operandı ve son `orders.total_count`
denominator'ı; bütün business üyeleri ve denominator model tarafından seçilmişse kayıpsız biçimde
bu canonical operanda çevrilir. Üye eksikliği, yinelenen member, bilinmeyen status veya farklı
scalar/collection şekli fail-closed kalır. Her üye gerçek Orders status observation'ından çözülür;
iç toplama ve dış yüzde ayrı ayrı ortak Core verified-calculation primitive'iyle hesaplanır ve
nested evidence hash taşır. Böylece görünür çalışma hem `110 + 52 = 162` iç toplamını hem
`162 / 3119 × 100 = 5.19%` dış oranını kanıtlar; AI katmanında Orders hesabı veya prompt'a özel
sonuç yazılmaz. R327 birebir focused regresyonu ve önceki per-target/comparison vakaları geçmiş;
güncel geniş Orders runtime/provider/Core/domain paketi `523 passed / 402 skipped` sonucunu
vermiştir.

R328'de business sonucu geçmesine rağmen ilk turun final synthesis deadline notu ve hatalı CLI
finalize komutu; R329'da ise yanlış evidence metadata alanı nedeniyle acceptance geçerli
kapanmamıştır. Bu artifact'lar passing kanıt sayılmaz. Fresh R330 exact
`deepseek/deepseek-v4-flash`, fallback kapalı gerçek source-app yolunda iki adaptif turu
`accepted=true / problems=[] / passed` olarak kapatmıştır. Tur 1 tek `orders.summary` ile
`3119` ve aynı üçlü durum dağılımını görünür vermiştir. Tur 2 hiçbir yeni tool/API/DB veya etki
çalıştırmadan typed önceki observation'dan `110 + 52 = 162` ve
`(110 + 52 = 162) / 3119 × 100 = 5.19%` sonuçlarını işlemleriyle vermiştir. Requested/actual model
aynıdır, fallback kullanılmamış, her iki cevap Codex tarafından okunmuş ve source fingerprint
stale olmamıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r330-deepseek-v4-flash-combined-status-ratio-2026-08-17.json`.
R330 yalnız focused root closure'dır; Faz 8B kapanışı değildir. Sıradaki kapı yeni source
fingerprint, fresh process/artifact ve turn 1 ile başlayacak en az 50 turluk exact DeepSeek V4
Flash organik source-app kampanyasıdır.

2026-08-17 Karar 158, R331-R333 broad-summary zincirini bağlayıcı kanıta dönüştürür. Fresh R331
organik kampanyasının ilk iki turu doğal toolsuz sohbet ve katalog-grounded Orders capability
özetini geçmiştir. Üçüncü turdaki local genel fotoğraf hedefinde exact DeepSeek base count/status/
revenue projeksiyonlarını formula benzeri satırlar olarak serialize etmiş; aynı modelin bounded
repair'i unary `orders.total_count`, `orders.status_counts`, `orders.revenue_total` satırları ile
tek gerçek `orders.revenue_total / orders.total_count` ortalama formülünü birlikte döndürmüştür.
Runtime unary direct count ve revenue satırlarını elemiş fakat `orders.status_counts -> status`
direct-projection eşlemesi eksik olduğu için `result_kind=summary` satırını geçersiz formül saymış,
hiçbir tool çalıştırmadan gereksiz clarification üretmiştir. Kampanya ilk kritik sapmada failed
kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r331-deepseek-v4-flash-organic-50-2026-08-17.json`.

Canonical redundant-base-formula sınırı artık `orders.status_counts` collection ref'ini yalnız
kullanıcı status dağılımını bağımsız direct output olarak istediğinde `status` boyutuna eşler.
Unary satır yalnız canonical ref ile exact direct projection eşleşiyorsa elenir; üyeli status,
istenmemiş metric veya gerçek çok-operandlı formül bu yolla kaybolamaz. R331 focused regresyonu ve
geniş paket bu değişiklikte geçmiş, fakat fresh R332 daha derin iki contract boşluğu göstermiştir:
model açık `sipariş başına ortalama` hedefini typed calculation'a taşımamış ve kullanıcı ürün
analizi istemediği halde `item_sales_rows` eklemiştir. Runtime bunu kabul ederek gereksiz
`orders.item_sales_summary` çalıştırmış; görünür cevapta istenmemiş top-5 ürün payı ile formula
contract'ı tarafından zorunlu tutulmayan `167.31 TRY` iptal-dışı ortalamasını göstermiştir. R332
failed artifact'tır ve passing kanıt sayılmaz:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r332-deepseek-v4-flash-broad-summary-2026-08-17.json`.

Yeni genel invariant'lar şunlardır. Kullanıcı açık average/difference/division/comparison gibi
aritmetik bir ilişki istediğinde model bunu ilk typed kararda atlamışsa runtime operator veya
operand yazmaz; aynı exact modelden bounded canonical formula ister. Canonical status-ratio ve
item-sales report aggregation kendi typed sözleşmelerini kullandığından bu generic formula
zorunluluğuna sokulmaz. Kullanıcı iki veya daha fazla açık summary boyutu saymış ve hiçbir ürün/
item-sales hedefi vermemişse provider'ın eklediği `item_sales_rows` projection'ı izinsiz kapsam
genişlemesi olarak kaldırılır. Buna karşılık yalnız `count + genel analiz` gibi gerçekten açık uçlu
hedefler veya açık ürün boyutu item-sales analiz yeteneğini korur. Böylece belirli bir prompt
yaması değil; model-authored arithmetic zorunluluğu ile specialized projection permission sınırı
oluşur.

Fresh R333 exact `deepseek/deepseek-v4-flash`, fallback kapalı source-app yolunda aynı R331/R332
cümlesini yalnız `orders.summary` ile çözmüştür. Typed projection `scope/count/status/amount/
currency/calculation`, metric requirements yalnız total/status/revenue ve model-authored formula
`orders.revenue_total / orders.total_count`tır. Görünür cevap `3119`, doğru üçlü status dağılımı,
`503446.47 TRY`, `161.41 TRY/sipariş` ve `MDB / TRENDYOL / production` kapsamını vermiş; item-sales
tool veya ürün analizi üretmemiştir. Acceptance `accepted=true / problems=[] / passed`, source
stale false ve her cevap Codex-read-confirmed'dır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r333-deepseek-v4-flash-broad-summary-2026-08-17.json`.
Güncel geniş Orders runtime/provider/Core/domain regresyonu `526 passed / 405 skipped` sonucuyla
geçmiştir. R333 focused closure'dır; Faz 8B kapanışı değildir. Sıradaki kapı yeni source
fingerprint ve turn 1 ile başlayacak fresh 50+ exact DeepSeek V4 Flash organik kampanyasıdır.

2026-08-17 Karar 159, R334-R336 politika açıklaması ile genel capability kataloğu ayrımını
bağlayıcı hale getirir. Fresh R334 organik kampanyasının ilk toolsuz gündelik sohbet turu geçmiş;
ikinci turda kullanıcı API güncellemesi istemediğinde hangi verinin kullanılacağını ve hangi
durumda onay isteneceğini sormuştur. Model objective düzeyinde veri kaynağı/onay mekanizmasını
doğru anlamış olsa da bunu `intent_kind=capability_overview` olarak serialize etmiş; source Chat
objective'i yok sayarak bütün Orders capability kataloğunu göstermiş ve soruyu cevaplamamıştır.
Kampanya ilk kritik sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r334-deepseek-v4-flash-organic-50-2026-08-17.json`.

Typed turn sözleşmesi artık broad operasyon/yetenek envanteri için `capability_overview` ile veri
kaynağı, freshness, approval, verification, privacy ve model routing kurallarının nasıl çalıştığını
soran turlar için `policy_explanation + explanation_topics` ayrımını taşır. Policy turu business
projection veya tool üretemez. UI source Chat ve UI-independent conversation runtime aynı DRY
`canonical_runtime_policy` context'ini kullanır: Orders'ta açık sync yoksa son kalıcı local snapshot,
sessiz pazaryeri refresh'i yok, R0 read onaysız, dosya/DB/dış sistem etkisi exact prepare + açık
confirm sınırında, approval kartı execute değildir ve canonical verify/read-back geçmeden başarı
raporlanmaz. Capability soruları ise eskisi gibi canonical operation kataloğundan deterministic ve
grounded kalır.

Fresh R335'te görünür cevap doğru görünmüş fakat ilk typed seçim yalnız `data_source` topic'ini
taşırken model `approval` iddialarını trusted context dışında üretmiştir. Codex bu kanıtsız doğru
görünümlü cevabı geçirmemiş; artifact failed korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r335-deepseek-v4-flash-policy-explanation-2026-08-17.json`.
Runtime topic eksikliğini cümle/regex veya deterministic iş kuralıyla tamamlamaz. Aynı exact modelden
bounded canonical topic-completeness audit ister; ilk ve audited model-authored enum seçimlerini
kayıpsız birleştirir ve ancak bundan sonra trusted policy context kurulur.

Fresh R336 exact `deepseek/deepseek-v4-flash`, fallback kapalı gerçek offscreen source-app yolunda
iki adaptif turu geçmiştir. Tur 1 doğal ve toolsuz sohbet; tur 2 typed
`policy_explanation / data_source+approval`, boş business projection ve sıfır tool ile local snapshot,
no-implicit-API-sync, read/no-approval, effect/prepare-confirm, approval-is-not-execution ve
verify/read-back-before-success sınırlarını kısa ve doğru açıklamıştır. Requested/actual model aynı,
fallback ve yan etki yoktur; her cevap Codex tarafından okunmuş, source stale olmamış ve acceptance
`accepted=true / problems=[] / passed` kapanmıştır. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r336-deepseek-v4-flash-policy-explanation-2026-08-17.json`.
Güncel Chat/UI/task runtime regresyonu `486 passed / 406 skipped` sonucuyla geçmiştir. R336 yalnız
focused root closure'dır; Faz 8B kapanışı değildir. Sıradaki kapı yeni source fingerprint ve turn 1
ile başlayacak fresh 50+ exact DeepSeek V4 Flash organik source-app kampanyasıdır.

2026-08-17 Karar 160, kullanıcı tarafından yeniden teyit edilen güçlü-model-öncelikli kabul
sırasını bağlayıcı hale getirir. Hedef yeniden sürdürüldüğünde test sırası şöyledir:

1. Ücretli kontrol ve geliştirme koşuları exact `deepseek/deepseek-v4-flash` ile, fallback kapalı
   ve requested/actual model eşleşmesi kanıtlanarak yürütülür.
2. Aynı frozen yetenekler Gemini'nin o anda gerçekten erişilebilen en güçlü ücretsiz modeliyle
   fresh-process ürün yolunda sınanır.
3. Aynı frozen yetenekler OpenRouter'ın o anda gerçekten erişilebilen en güçlü ücretsiz modeliyle
   ayrı fresh-process ürün yolunda sınanır.

Bir provider'ın geçmesi diğerinin yerine sayılmaz. İlk ücretsiz aday kota veya erişim nedeniyle
çalışmıyorsa yalnız aynı provider'ın sıradaki **güçlü** ücretsiz adayı, normalize edilmiş quota
scope kanıtıyla denenebilir. Nispeten düşük quality-tier cloud modeller, küçük modeller, local
modeller ve degradation/dayanıklılık kampanyaları bu üç güçlü baseline kararlı biçimde geçene kadar
başlatılmaz. Bu erteleme provider/model bağımsızlığı vizyonunu kaldırmaz; mevcut geliştirme
döngüsünde en yüksek sinyalli modellerle agent runtime, state, plan, tool-composition, verifier ve
response-projection kusurlarını model yetersizliğiyle karıştırmadan ortaya çıkarmayı amaçlar.

2026-08-17 Karar 161, R340-R348 zincirinde açığa çıkan broad Orders summary ve türetilmiş hesap
sınıfını sistemik olarak kapatır. Direct projection ile gerçekten türetilmiş hesap aynı contract
değildir: model `count/status/revenue` gibi authoritative alanı tek operandlı namespaced formula
olarak tekrar ederse runtime bunu yeni aritmetik diye çalıştırmaz; yalnız açıkça istenen direct
projection'a indirger. Gerçek aritmetik typed operand ref'leri, result kind, precision ve show-work
ile kalır. Geçersiz formül repair prompt'una reddedilmiş ham sayı/formül gövdesi geri verilmez;
model mevcut kullanıcı hedefi, canonical metric ref'leri ve value-free reason category'lerinden
hesabı yeniden kurar. Kullanıcının istemediği ek percentage/rate hesabı geçerli başka bir hesabı
zehirleyemez; yalnız izinsiz boyut kaldırılır ve kalan typed hesap korunur.

Provider yolunda native structured-contract başarısızlığı bütün kullanıcı turunu sınırsızca
tüketemez. Guarded JSON bütçesi `2048` token ile sınırlıdır; HTTP çağrıları shared turn deadline'ını
gerçek wall-clock sınırında uygular. Aynı provider/model/schema rotasının yakın zamandaki structured
contract başarısızlığı secret-safe, yalnız hash ve reason-code taşıyan kısa ömürlü health kaydıyla
fresh process'te bilinir; bilinen bozuk native rota bounded guarded contract'a doğrudan geçer.
Provider/model adı, API anahtarı, prompt, cevap veya PII bu cache'e yazılmaz.

Fresh R348 offscreen source-app kabulü exact `deepseek/deepseek-v4-flash`, fallback kapalı ve
requested/actual model aynı koşulunda geçmiştir. Kullanıcının genel Orders fotoğrafı hedefi için
model yalnız minimal canonical `orders.summary` operasyonunu seçmiş; `3119` toplam sipariş,
`Cancelled 110 / Delivered 2957 / UnDeliveredAndReturned 52`, `503446.47 TRY` toplam ciro ve typed
`503446.47 / 3119 = 161.41 TRY/sipariş` hesabını aynı verified observation'dan üretmiştir. İlk model
synthesis'i bir status üyesini atladığında response projection verifier görünür cevabı kabul
etmemiş, exact model repair eksik üyeyi eklemiş ve final cevap `verified_model_repair` provenance'ı
ile geçmiştir. Artifact current source fingerprint'te stale olmadan
`accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r348-deepseek-v4-flash-summary-partial-formula-validity-2026-08-17.json`.
Güncel birleşik provider/Orders task/conversation/Chat/acceptance/domain regresyonu
`633 passed / 410 conditional skipped` sonucuyla hatasız geçmiştir. R348 yalnız focused root
closure'dır; Faz 8B veya Orders kapanışı değildir. Sıradaki kapı fresh process, fresh artifact ve
turn 1 ile başlayacak en az 50 turluk exact DeepSeek V4 Flash organik source-app kampanyasıdır.

2026-08-23 Karar 162, fresh R349 organik kampanyasının üçüncü turunda bulunan source-policy
karışmasını kapatır. İlk iki turdaki doğal sohbet ve canonical capability overview geçtikten sonra
kullanıcı "dışarıdan veri çekmeden elindeki siparişlerin genel fotoğrafını çıkar" demiştir. Runtime
bu cümledeki external-refresh yasağını hem yanlışlıkla `data_refresh / orders.fetch.prepare` diye
yorumlamış hem de bütün yeni operasyonları yasaklayan `existing_observations_only` politikasına
genişletmiştir. Sonuçta önceki capability-catalog observation'ı istenen business evidence olmadığı
hâlde lokal `orders.summary` çalıştırılmamış ve tur fail-closed kalmıştır. Artifact ilk kritik
sapmada `failed` korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r349-deepseek-v4-flash-organic-50-2026-08-23.json`.

Yeni typed invariant, **bilgi kaynağı** ile **operation iznini** bağımsız eksenlerde tutar.
"Dışarıdan/API'den/pazaryerinden veri çekme" external sync yasağıdır; aynı mesaj lokal Orders
okuması istiyorsa canonical R0 DB read'i engellemez ve negated fiil fetch intent'ine çevrilemez.
"Hiçbir tool/yeni sorgu çalıştırma; önceki observation'dan hesapla" ise gerçekten
`existing_observations_only` kalır. Bu ayrım shared Orders language boundary'de tek canonical
signal ile hem legacy/single-turn hem typed task runtime tarafından kullanılır; prompt'a özel
workflow veya AI içinde Orders business logic kopyası eklenmemiştir. `elindeki`, `eldeki`,
`programdaki` ve `sistemdeki siparişler` de durable local source referansı olarak typed read
sınırında normalize edilir.

Fresh R350 aynı üç turlu bağlamı exact `deepseek/deepseek-v4-flash`, fallback kapalı ve current
source fingerprint'te yeniden kurup geçmiştir. Kritik üçüncü turda `operation_policy` doğru biçimde
`allow_new_operations`, source `local_business_data` kalmış; yalnız `orders.summary` çalışmış,
external fetch/approval/yan etki oluşmamıştır. Güncel observation'dan `3120` toplam sipariş,
`Cancelled 110 / Delivered 2958 / UnDeliveredAndReturned 52`, `503546.47 TRY` ciro ve typed
`503546.47 / 3120 = 161.39 TRY/sipariş` hesabı model-authored, grounded ve projection-verified
cevapla gösterilmiştir. Artifact `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r350-deepseek-v4-flash-external-refresh-local-read-2026-08-23.json`.
Focused boundary kanıtı `13 passed / 10 conditional skipped`; tam agent+conversation paketi
`411 passed / 411 conditional skipped`; güncel birleşik provider/Orders task/conversation/Chat/
acceptance/domain regresyonu `635 passed / 411 conditional skipped` sonucuyla geçmiştir. R350
focused root closure'dır; R349'un ilk iki turu veya R350'nin üç turu 50+ kabulüne taşınamaz. Sonraki
organik kampanya fresh process/artifact ve turn 1 ile yeniden başlamalıdır.

2026-08-24 Karar 163, fresh R351 organik kampanyasının yedinci turunda bulunan contextual ürün
satış zinciri hatalarını sistemik olarak kapatır. Model doğru iki atomic adımı
`orders.product_public_identities -> orders.item_sales_summary` olarak kurmuş, fakat provider
`product_identities` whole-value dependency'sini tek elemanlı liste içine koymuştur. Compiler bunu
typed dataflow bağı olarak okuyamadığı için geçerli planı `contextual_item_sales_dependency_missing`
ile reddetmiştir. Ayrıca `son 3 hafta` gibi bounded dönem + satış ilişkisi aggregate population scope
sayılmadığından istenen adet ve brüt tutar projection'ları interpretation aşamasında düşmüştür.
R351 ilk kritik sapmada failed olarak korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r351-deepseek-v4-flash-organic-50-2026-08-23.json`.

Yeni compiler invariant'i yalnız `product_identities` whole-array bağı için exact singleton-wrapper
diyalektiğini canonical binding nesnesine indirger; literal listeler ve `web_observations` gibi
gerçekten binding listesi taşıyan argümanlar değişmez. Bounded semantic period + satış ilişkisi,
contextual ürün summary'sinde `quantity / distinct order count / gross amount` alanlarının birlikte
korunmasını zorunlu kılar. Geniş regresyon bu ayrımı ayrıca privacy-safe Orders -> web search/open ->
immutable report -> onaylı XLSX zinciriyle doğrulamıştır.

İlk focused tekrar R352'de plan ve iki atomic operasyon doğru çalışmış; seçili ürünün son 21 günlük
authoritative sonucu gerçekten sıfır satır, `0` farklı sipariş, `0` adet ve `0.00` brüt olmuştur.
Ancak verifier falsey sıfırları eksik kanıt, boş para birimini de hata saydığı için doğru cevap ve
repair fail-closed kalmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r352-deepseek-v4-flash-context-product-sales-2026-08-23.json`.
Canonical Orders sonucu artık sıfır eşleşmeyi açık `empty_result=true`, `metrics_complete=true`,
`currency_applicable=false` sözleşmesiyle taşır. Verifier yalnız bu tam ve tutarlı sözleşmede
`0 / 0 / 0.00` değerlerini authoritative kabul eder; para birimi uydurmaz. Privacy-minimized
contextual summary canonical dönemle typed observation'a yazılır, hash'i doğrulanır ve yalnız açık
`existing_observations_only` politikası altında yeniden kanıt olabilir; arbitrary eski observation
yeni business-data isteğini ground edemez.

Fresh R353 gerçek offscreen source-app tekrarında exact `deepseek/deepseek-v4-flash`, fallback
kapalı ve requested/actual/final model aynı koşulunda üç adaptif turu geçmiştir. Beş yerel sipariş
PII'siz listelenmiş, üçüncü kaydın ürünü ordinal continuity ile çözülmüş ve son turda model-authored
iki-adımlı identity -> item-sales planı çalışmıştır. Görünür cevap seçili ürün için `0` adet, `0`
farklı sipariş ve `0.00` brüt sonucu göstermiş; para birimi belirtilmediğini açıkça söylemiş, dosya
üretmemiş ve `verified_model_candidate` olarak kabul edilmiştir. Artifact current source fingerprint'te
stale olmadan `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r353-deepseek-v4-flash-context-product-zero-summary-2026-08-23.json`.
Odak zincir testleri `3 passed / 3 conditional skipped`; tam agent+conversation paketi
`414 passed / 414 conditional skipped`; güncel birleşik provider/Orders task/conversation/Chat/
acceptance/domain regresyonu `641 passed / 414 conditional skipped / 53 subtests` sonucuyla
hatasız geçmiştir. R353 focused root closure'dır; R351/R352 turları kampanyaya eklenemez. Sonraki
kapı fresh process, fresh artifact ve turn 1 ile yeniden başlayacak en az 50 turluk exact V4 Flash
organik kampanyadır; ilk kritik semantic/operational sapmada artifact failed kapanır, kök düzeltme
sonrası yine turn 1'den başlanır.

2026-08-24 Karar 164, fresh R354 organik kampanyasının üçüncü turunda bulunan arithmetic relation
sapmasını kapatır. İlk iki doğal/capability turu geçtikten sonra kullanıcı dış API yenilemesini
yasaklayıp yerel toplam sipariş, durum dağılımı, toplam ciro ve sipariş başına ortalama ciro istemiştir.
Canonical `orders.summary` doğru `3120 / 503546.47 TRY` kanıtını üretmiş; fakat model formula repair'i
ortalama ilişkisini `orders.total_count + orders.revenue_total` olarak yazmıştır. Yapısal validator
farklı boyuttaki iki metric'in toplanmasını kullanıcı hedefiyle bağlamadığı için formula çalışmış ve
provider final synthesis turn deadline'ını tüketince deterministic projection görünür toplamı atlayıp
`506666` adlı anlamsız sonucu göstermiştir. Artifact ilk kritik semantic sapmada failed kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r354-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni semantic verifier invariant'i explicit **sipariş başına ortalama ciro/tutar** ilişkisini yalnız
model-authored `divide([orders.revenue_total, orders.total_count]) -> amount_per_order` typed contract'ı
ile kabul eder. Runtime bu formülü kendisi yazmaz veya yanlış formülü sessizce dönüştürmez: ilk yanlış
ilişkide value-free reason code ile bounded model repair ister; repair de yanlışsa business read'e
düşmeden fail-closed kalır. Repair prompt'u canonical ref sırasını ve result dimension'ını açıklar;
base toplam/ciro/status metrikleri ayrı visible direct projection olarak kalır. Türkçe genitive
`tüm siparişlerin toplamı/toplamını` population count yetkisidir; `siparişlerin toplam tutarı/cirosu`
ise count'a genişletilmez.

Fresh R355 exact aynı üç turlu bağlamı current offscreen source-app'te yeniden kurup geçmiştir.
Kritik turda yalnız minimal `orders.summary` çalışmış; görünür cevap `3120` toplam sipariş,
`Cancelled 110 / Delivered 2958 / UnDeliveredAndReturned 52`, `503546.47 TRY` toplam ciro ve
typed `503546.47 / 3120 = 161.39 TRY/sipariş` hesabını eksiksiz göstermiştir. Requested/actual/final
model exact `deepseek/deepseek-v4-flash`, fallback kapalı, final kaynak `verified_model_candidate`,
external refresh ve yan etki yoktur. Artifact `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r355-deepseek-v4-flash-average-revenue-relation-2026-08-24.json`.
Arithmetic/count sınır odak testi `3 passed / 3 conditional skipped`; güncel birleşik provider/Orders
task/conversation/Chat/acceptance/domain regresyonu `643 passed / 416 conditional skipped /
53 subtests` sonucuyla hatasız geçmiştir. R355 focused closure'dır; yeni 50+ kampanya fresh process,
fresh artifact ve turn 1'den başlar.

2026-08-24 Karar 165, fresh R356 organik kampanyasının dokuzuncu turunda bulunan contextual ürün
dönem-düzeltme sapmasını kapatır. İlk sekiz tur doğal sohbet, çok-boyutlu policy explanation, lokal
summary+average, observation-only yüzde, PII-safe altılı liste, ordinal ürün detayı, 30 günlük üç
metrikli ürün özeti ve observation-only birim ortalamasını geçmiştir. Dokuzuncu turda kullanıcı
"son 30 gün değil son 21 gün" diyerek aynı ürünün farklı sipariş sayısı, adet ve brüt tutarını tekrar
istemiş; runtime calendar ifadesindeki `son 21` sayısını yanlışlıkla `son 21 sipariş` row limit'i
saymış, ilk geçen `last_30_days` dönemini korumuş ve contextual quantity/amount boyutlarını record
projection sanıp düşürmüştür. Model bu eksik contract'a uygun olarak yalnız `1 farklı sipariş` demiştir.
Artifact ilk kritik sapmada failed kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r356-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni typed correction invariant'leri şunlardır: bounded recent-order row limiti takvim birimiyle
devam eden sayıyı tüketmez; aynı cümlede `A dönem değil B dönem` varsa olumlu replacement period
contract'a yazılır; `pardon / kastettim / yerine / demek istedim` doğal correction sinyalleridir.
Explicit dönem + `aynı/seçili ürün` + tekrar/düzeltme + farklı sipariş/adet/brüt tutar boyutları,
önceki contextual sales population'ını korur. Böylece model tek alan döndürse bile açıkça tekrarlanan
`item_sales_quantity / item_sales_order_count / item_sales_amount / currency` projection'ları
canonical summary sözleşmesinde birlikte kalır; generic record count/amount/item/quantity alanlarıyla
karıştırılmaz.

Fresh R357 dört turlu exact tekrar current offscreen source-app'te geçmiştir. Altı PII-safe sipariş
listelenmiş, beşinci ürün ordinal continuity ile seçilmiş, son 30 gün için `1 farklı sipariş / 1 adet /
159.99 TRY` alınmış ve aynı doğal correction cümlesiyle dönem `last_21_days` olmuştur. Düzeltilmiş
authoritative cevap aynı exact ürünü ve üç metriği koruyarak `0 farklı sipariş / 0 adet / 0.00` demiş;
eşleşme olmadığı için para birimi uydurmamış ve dosya üretmemiştir. Requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback kapalı, artifact stale olmadan
`accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r357-deepseek-v4-flash-context-product-period-correction-2026-08-24.json`.
Contextual correction odak paketi `7 passed / 7 conditional skipped`; güncel birleşik provider/Orders
task/conversation/Chat/acceptance/domain regresyonu `644 passed / 417 conditional skipped /
53 subtests` sonucuyla hatasız geçmiştir. R357 focused closure'dır; R356'nın ilk sekiz başarılı turu
yeni kampanyaya taşınmaz ve 50+ kapı fresh turn 1'den yeniden başlar.

2026-08-24 Karar 166, fresh R358 organik kampanyasının ikinci turunda bulunan bağımsız kapsamlı
çoklu-count sapmasını kapatır. İlk doğal sohbet turu geçmiş; ikinci turda kullanıcı aynı cümlede
`kargoya hazır kaç sipariş` ile `bütün terminal olmayan siparişlerin toplamı` değerlerini ayrı ayrı
istemiştir. Exact `deepseek/deepseek-v4-flash` modeli doğru biçimde
`orders.ready_to_ship_count + orders.nonfinal_summary` atomic planını iki kez üretmiş; buna rağmen
typed turn contract `kargoya hazır` içindeki kargo sözcüğünü carrier projection, scope-qualified
`terminal olmayan siparişlerin toplamı` ifadesini de global `orders.total_count` sanmıştır. Doğru
model planı bu uydurulmuş global metriği karşılamadığı için execute öncesi fail-closed kalmış ve R358
ilk kritik sapmada failed kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r358-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni typed scope/metric invariant'i, `terminal/final olmayan`, `terminal/final dışı`, `nonfinal`,
`tamamlanmamış`, `sonlanmamış` ve `kapanmamış` Orders ifadelerini ortak nonfinal population sinyalinde
tutar. Scope-qualified `... siparişlerin toplamı` yalnız `orders.nonfinal_count` yetkisidir; aynı
cümlede ayrıca açık unqualified `tüm siparişlerin toplamı` bulunmadıkça `orders.total_count` eklenmez.
Tek turn birden fazla population scope içeriyorsa baskın tek `status_scope` diğerini silmez:
ready-to-ship ve nonfinal metric requirement'ları birlikte fakat bağımsız kalır. `Kargoya hazır`
lifecycle filtresi carrier/cargo response alanı değildir; kullanıcı ayrıca kargo/kargo firması
istemediği sürece aggregate projection'a eklenmez. Compiler doğru model-authored çok-adımlı planı
canonical metric coverage ile kabul eder; deterministic business step yazmaz.

Fresh R359 iki turlu exact focused tekrar current offscreen source-app'te geçmiştir. İlk tur doğal ve
effects-free kalmış; ikinci turda model yine aynı doğru iki atomic operation'ı yazmış ve ikisi de
çalışmıştır. Görünür verified cevap `Kargoya hazır 0 sipariş` ile `Sevkiyat süreci tamamlanmamış 0
sipariş` değerlerini ayrı etiketlemiştir. Typed contract yalnız `count` projection'ı taşımış,
metric requirement'lar exact `orders.ready_to_ship_count + orders.nonfinal_count` olmuş;
requested/actual/final model `deepseek/deepseek-v4-flash`, fallback kapalı, final kaynak
`verified_model_candidate` kalmıştır. Artifact stale olmadan `accepted=true / problems=[] / passed`
kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r359-deepseek-v4-flash-ready-nonfinal-distinct-counts-2026-08-24.json`.
Odak testleri `4 passed / 4 conditional skipped`; güncel birleşik provider/Orders task/conversation/
Chat/acceptance/domain regresyonu `646 passed / 419 conditional skipped / 53 subtests` sonucuyla
hatasız geçmiştir. R359 yalnız focused root closure'dır; R358'in ilk turu taşınmaz. Hedef yeniden
başlatıldığında sonraki kapı fresh process, fresh artifact ve turn 1'den başlayacak en az 50 turluk
exact V4 Flash organik kampanyadır; ücretli güçlü baseline kararlı olduktan sonra her provider'ın
erişilebilen en güçlü ücretsiz modeli ayrı fresh kampanyada sınanır. Düşük-tier cloud ve local modeller
bu güçlü baseline kapıları tamamlanana kadar bekler.

2026-08-24 Karar 167, fresh R360 organik kampanyasının yedinci turunda bulunan order-line identifier
projection açığını kapatır. İlk altı tur doğal/effects-free sohbet, source/freshness/approval policy
explanation, ready-to-ship + nonfinal bağımsız count composition, lokal summary + sipariş başına
ortalama, persisted observation'dan iki ayrı status yüzdesi ve PII-safe en yeni yedili listeyi
geçmiştir. Yedinci turda kullanıcı listedeki dördüncü siparişin her kalemi için ürün adı, SKU,
barkod ve adet istemiştir. Model doğru ordinal kaydı `orders.full_context` ile okumuş ve canonical
sonuç dört alanın tamamını taşımıştır; fakat turn schema yalnız generic `item + quantity` boyutlarını
ifade edebildiği için explicit SKU/barkod projection'dan düşmüş, görünür cevap iki alanı atlamıştır.
İlk model final adayı verifier'dan geçmemiş; bounded repair `empty_response` ile sonuçlanınca
deterministic fallback de eksik typed contract'ı eksiksiz sanmıştır. Artifact ilk kritik semantic
sapmada failed kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r360-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni item-detail invariant'i `item / sku / barcode / quantity` alanlarını ayrı typed projection
boyutları yapar. Kullanıcının açık SKU/stok kodu ve barkod/GTIN isteği provider omission'ına karşı
semantic authority'dir; model bu specialized alanları kullanıcı istemeden ekleyemez. Canonical
`orders.full_context` aynı domain operation'ı olarak kalır; AI içinde business sorgusu kopyalanmaz.
Response projection her kalem için yalnız istenen alanları üretir; SKU ve barkod değerleri aynı olsa
bile ayrı `SKU:` ve `Barkod:` etiketlerinin ikisini de gerektirir. Bir kodun ürün adında tesadüfen
geçmesi veya yalnız SKU etiketiyle görünmesi barkod kanıtı sayılmaz. Explicit istenmeyen SKU/barkod
etiketleri de projection expansion olarak reddedilir. Aynı failure'da açığa çıkan temporal parser
kusuru da ortak takvim gramerinde kapatılmıştır: `dördüncü` içindeki harfler `dün/yesterday` sayılmaz;
gerçek `dün/dünkü`, `bugün/bugünkü` ve `son 3 haftada` gibi Türkçe çekimler token + morphology
sınırıyla doğru döneme bağlanır.

Fresh R361 iki turlu exact focused tekrar current offscreen source-app'te geçmiştir. İlk tur exact
yedi newest-first kaydı aynı PII-safe alanlarla yeniden kurmuş; ikinci tur aynı doğal ordinal isteği
doğru dördüncü kayda `active_selection` üzerinden bağlamıştır. Görünür cevap authoritative ürün adı,
ayrı etiketli `SKU: 220MLSPREYMDB`, ayrı etiketli `Barkod: 220MLSPREYMDB` ve `adet: 2` değerlerini
eksiksiz göstermiş; müşteri verisi eklememiştir. Typed projection exact
`item + sku + barcode + quantity`, period `all`, tek detail operation `orders.full_context`, final
kaynak `verified_model_candidate`; requested/actual/final model exact `deepseek/deepseek-v4-flash`
ve fallback kapalıdır. Artifact stale olmadan `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r361-deepseek-v4-flash-ordinal-item-identifiers-2026-08-24.json`.
Odak paket `4 passed / 4 conditional skipped`; güncel birleşik provider/Orders task/conversation/Chat/
acceptance/domain regresyonu `648 passed / 421 conditional skipped / 53 subtests` sonucuyla hatasız
geçmiştir. R361 focused root closure'dır; R360'nın ilk altı başarılı turu yeni kampanyaya taşınmaz.
Sonraki kapı fresh process, fresh artifact ve turn 1'den başlayacak en az 50 turluk exact V4 Flash
organik kampanyadır.

2026-08-24 Karar 168, kullanıcının güçlü-model-first test önceliğini mevcut hedef için yeniden
bağlayıcı kılar. Bundan sonraki geliştirme ve kabul döngüsü önce fallback kapalı exact ücretli
`deepseek/deepseek-v4-flash` ile yürütülür. Ücretli kontrol kararlı olduktan sonra aynı frozen
yetenekler Gemini ve OpenRouter'ın **ayrı ayrı erişilebilen en güçlü ücretsiz modellerinde** fresh
process ve fresh artifact ile sınanır. Ücretsiz adayın yalnız kanıtlanmış model-kapsamlı kotaya veya
gerçek erişilemezliğe takılması halinde aynı provider'daki sıradaki güçlü ücretsiz adaya geçilir;
agent/runtime kusuru model değiştirerek örtülmez. Nispeten düşük-tier cloud modeller, küçük modeller
ve local inference şimdilik bekler. Bu erteleme provider/model özgürlüğü vizyonunu veya ilerideki
capability/degradation kabulünü silmez; önce mimariyi yüksek sinyalli güçlü modellerle doğru kurmayı
ve ücretsiz güçlü baseline'ı dürüstçe kanıtlamayı amaçlar.

2026-08-24 Karar 169, fresh R362 exact V4 Flash organik kampanyasının ikinci turunda bulunan
return-claim satır sözleşmesi açığını kapatır. Kullanıcı aksiyon bekleyen iadelerin sayısını ve
claim numarası, sipariş numarası, durum ve neden alanlarıyla **tam listesini** aynı cümlede istemiş;
runtime `kaç` boyutunu liste isteğinin önüne geçirerek typed metric'i `count` yapmış ve yalnız
`returns.waiting_action_count` çalıştırmıştır. Ayrıca typed projection'da iade nedeni için bağımsız
`reason` alanı bulunmadığından modelin `returns` alanı order-full-context anlamına kaymış; authoritative
boş return listesi claim/order satır kanıtı yok diye yanlış reddedilmiştir. R362 ilk kritik sapmada
failed kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r362-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te açık `listele/göster/sırala` satır şekli, aynı istekte count projection bulunsa da
`metric=list`tir; count listenin authoritative cardinality'sidir. `return_claim` satırı
`claim_id / order_number / status / reason` alanlarını ayrı taşır; entity sözcüğü olan `iade`, Orders
tam bağlamındaki `returns` projection'ı değildir. Waiting-action listesi yalnız canonical
`returns.query(filters.waiting_action_only=true, mode=list)` ile okunur. Empty-set başarı sayılabilmek
için `returns=[]`, exact `total_count=0` ve `truncated=false` birlikte gerekir; dolu listede her
istenen alan aynı claim satırında exact doğrulanır, eksik/truncated liste “tamamı” diye sunulamaz.
Müşteri/adres/telefon/e-posta yasağı response verifier ve privacy projection sınırında korunur.

Fresh R363 iki turlu offscreen source-app focused tekrarı geçmiştir. İlk tur effects-free doğal
sohbet kalmış; ikinci turda exact `deepseek/deepseek-v4-flash` model-authored typed contract
`return_claim/list/waiting_action/all_matching` ve projection
`claim_id + order_number + status + reason + count` olmuştur. Tek atomic `returns.query` çalışmış;
güncel authoritative sonuç `returns=[] / total_count=0 / listed_count=0 / truncated=false` olduğu
için görünür verified cevap `Aksiyon bekleyen iade yok; sorgu kapsamında 0 iade bulundu.` demiş ve
yasaklı PII göstermemiştir. Requested/actual/final model exact V4 Flash, fallback kapalı, final kaynak
`verified_model_candidate`, mutation yoktur. Artifact stale olmadan
`accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r363-deepseek-v4-flash-waiting-return-exhaustive-list-2026-08-24.json`.
Non-empty iki claim satırında bütün alanların aynı satırda tutulması ve PII minimizasyonu ayrıca
deterministic focused testle kanıtlanmıştır. Güncel tam Orders task runtime paketi
`410 passed / 424 conditional skipped`; komşu conversation/provider/Chat/live-eval/Orders pipeline
paketi `282 passed / 64 conditional skipped` geçmiştir. R363 focused kök kapanışıdır; R362'nin ilk
turu yeni kampanyaya taşınmaz. Sonraki kapı fresh process, fresh artifact ve turn 1'den başlayacak
en az 50 turluk exact V4 Flash organik kampanyadır.

2026-08-24 Karar 170, fresh R364 exact V4 Flash organik kampanyasının altıncı turunda bulunan
çoklu önceki-hesap composition açığını kaydeder. İlk beş tur doğal sohbet, policy açıklaması,
canonical `orders.summary`, yeni operation olmadan iki bağımsız durum yüzdesi ve kalan durum
yüzdesiyle doğru geçmiştir. Altıncı turda kullanıcı yalnız konuşmadaki doğrulanmış üç yüzdeyi
toplamayı ve yüzde 100'den görünen farkın veri hatası mı yuvarlama farkı mı olduğunu açıklamayı
istemiştir. Runtime bu açık anaforik izin sınırını `existing_observations_only` saymamış, gereksiz
`orders.summary` çalıştırmış ve aritmetik şemada farklı geçmiş sonuçları adresleyen bir ref olmadığı
için `derived.latest` değerini üç kez bağlayarak görünür `1.67 + 1.67 + 1.67 = 5.01` cevabı
üretmiştir. Bu kritik failure model kapasitesine atılmamış; R364 ilk sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r364-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni ortak invariant'te `yalnız/sadece konuşmadaki veya önceki doğrulanmış kanıtı kullan` türü
anaforik sınır bütün yeni operation'ları yasaklar; external API refresh yasağı + açık local snapshot
okumasıyla karıştırılmaz. Tek geçmiş hesap `derived.latest`, birden fazla farklı geçmiş hesap ise
`derived.recent + offset` ile typed ve exact adreslenir; aynı latest ref'i farklı operandların yerine
tekrarlanamaz. Geçmiş sonuçlar literal kopyalanmaz, yalnız immutable
`core.verified_calculation` observation'larından çözülür. Karşılaştırma farkı Core'un ortak decimal
comparison kanıtından gelir. Yuvarlama açıklaması ancak eklenen doğrulanmış yüzde bileşenlerinin ham
payları aynı paydayı kullanıyor ve pay toplamı paydayı exact tamamlıyorsa kabul edilir; aksi durumda
runtime “yuvarlama” sonucunu uyduramaz. `farklı sipariş` gibi kayıt çeşitliliği dili matematiksel
`fark` değildir. Focused deterministic regresyonlar geçmiş üç oranın distinct ref'lerini,
`94.81 + 3.53 + 1.67 = 100.01`, `|100.01 - 100| = 0.01 yüzde puan`, ham
`2958 + 110 + 52 = 3120` yuvarlama kanıtını ve sıfır tool çağrısını kapsar. Sonraki kapı mevcut
failure'ın fresh exact V4 Flash source-app focused tekrarıdır; bu geçse dahi R364'ün önceki beş turu
sayılmaz ve en az 50 turluk organik kampanya fresh process/artifact ile turn 1'den yeniden başlar.

2026-08-24 Karar 171, R364 kök kapanışını doğrulamak için açılan fresh R365 focused source-app
koşusunun üçüncü turunda daha erken bulunan projection kaybını kaydeder. Kullanıcı local Orders
snapshot'ından toplam sipariş sayısı, durum dağılımı, toplam ciro ve sipariş başına ortalama ciroyu
birlikte istemiştir. Exact V4 Flash objective içinde dört boyutu doğru anlamış ve canonical
`orders.summary` çalışmıştır; fakat görünür cevap bütün status bucket'larını atlayıp yalnız toplam,
ciro ve ortalamayı göstermiştir. Daha kritik olarak verifier bu eksik cevabı kabul etmiştir. Typed
normalizer açık `status` alanını önce geri eklemiş, derived calculation projection'ının son yeniden
kurma adımı ise onu `direct_projection` içine taşımadan tekrar silmiştir. R365 ilk kritik sapmada
failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r365-deepseek-v4-flash-prior-percentage-rounding-2026-08-24.json`.

Yeni invariant'te `broad_analysis + derived calculation` sözleşmesinde kullanıcı tarafından açıkça
istenen count/status/amount/currency/scope gibi görünür base boyutlar formül operandlarından ayrı
`direct_projection` olarak son projection yeniden-kurmasından önce sabitlenir. Semantic contract'ın
metric requirements listesi bunların canonical Orders metric'lerini taşır; model cevabı her istenen
status bucket'ını göstermeden response verifier geçemez. Bu, tek prompta özel status yaması değil;
her geniş türetilmiş analizde açık visible base metric'lerin formula-only operandlardan ayrılmasıdır.
Focused deterministic regresyon provider'ın status'u requested/direct alanlarından atmasını taklit
eder, normalizer'ın `orders.status_distribution` gereksinimini geri kurduğunu ve statüssüz görünür
adayın reddedildiğini kanıtlar. R365'in ilk iki/üç turu sonraki kanıta taşınmaz; sıradaki focused
source-app kanıtı fresh process ve fresh artifact ile yeniden başlar.

2026-08-24 Karar 172, R365 projection düzeltmesinin fresh kanıtı için açılan R366'nın ikinci
turunda policy/arithmetic intent eksenlerinin çakışmasını kaydeder. Kullanıcı siparişleri okumakla
değiştirmek arasındaki **güvenlik farkını**, onay koşulunu ve sonuç doğrulamasını sormuş; herhangi
bir veri/işlem çalıştırmayı yasaklamıştır. Provider policy objective ve explanation topics üretmesine
rağmen ortak `fark` aritmetik sinyali typed policy kararından sonra yeniden devreye girip modelden
Orders formülü istemiş; geçersiz repair sonunda sistem gereksiz kapsam netleştirmesiyle fail-closed
olmuştur. Mutation/tool çalışmamış olsa da istenen açıklama verilmediği için R366 ilk kritik sapmada
failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r366-deepseek-v4-flash-prior-percentage-rounding-2026-08-24.json`.

Yeni invariant'te `policy_explanation` typed intent/shape/topics sözleşmesi aritmetik relation
algılayıcısına karşı dışlayıcıdır. Güvenlik farkı, okuma/değiştirme farkı, onay veya verification
anlatımı `derived_calculation`/Orders metric repair başlatamaz; business projection temiz kalır ve
görünür cevap yalnız kayıtlı policy kanıtıyla sentezlenir. Matematiksel fark ancak policy contract
dışında açık nicel aggregate/karşı-değer ilişkisi olduğunda formül ister. Focused deterministic test
provider'ın policy cevabına yanlış `status` alanı eklemesini de taklit eder; son typed karar
`explain + policy_explanation`, projection boş, formula repair yoktur. R366'nın ilk turu sonraki
kanıta taşınmaz; source-app focused koşu yine fresh process/artifact ile sıfırdan başlar.

Fresh R367 altı turlu exact V4 Flash offscreen source-app focused koşusu bu birleşik zinciri
geçmiştir. Doğal selam effects-free kalmış; policy turu read/effect, prepare/onay/execute ve
verify/read-back ayrımını tool çalıştırmadan açıklamış; local summary turu tek canonical
`orders.summary` ile toplam `3120`, status bucket'ları `Cancelled 110 / Delivered 2958 /
UnDeliveredAndReturned 52`, ciro `503546.47 TRY` ve `503546.47 / 3120 = 161.39 TRY/sipariş`
sonuçlarının tamamını göstermiştir. Sonraki iki tur yeni operation olmadan distinct Delivered /
Cancelled yüzdelerini ve kalan UnDeliveredAndReturned yüzdesini doğrulamıştır. Altıncı tur typed
`existing_observations_only`, sıfır tool ve model-authored distinct
`derived.recent(offset=0,1,2)` operandlarıyla `1.67 + 3.53 + 94.81 = 100.01`; literal yüzde 100
comparison'ıyla exact `0.01 yüzde puan` fark; ham `52 + 110 + 2958 = 3120` kanıtıyla
`component_rounding_only` değerlendirmesi üretmiştir. Requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback kapalıdır. Artifact stale olmadan
`accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r367-deepseek-v4-flash-prior-percentage-rounding-2026-08-24.json`.
Güncel tam Orders task runtime paketi `415 passed / 427 conditional skipped` geçmiştir. R367
focused kök kapanışıdır; R364/R365/R366 turları yeni kampanyaya taşınmaz. Sonraki kapı fresh
process, fresh artifact ve turn 1'den başlayacak en az 50 turluk exact V4 Flash organik kampanyadır.

2026-08-24 Karar 173, R367 focused kapanışından sonra açılan fresh R368 50+ organik kampanyanın
ikinci turundaki capability hallucination'ını kaydeder. Kullanıcı Orders alanında hangi tür işleri
yapabildiğini sormuş ve yalnız açıklama isteyerek veri/aksiyon çalıştırmayı yasaklamıştır. Typed
shape `capability_overview` olmasına rağmen explicit no-operation cleanup intent'i `conversation`a
indirmiş; normal catalog yolu atlanınca model serbest prose içinde sipariş oluşturma/düzenleme/iptal,
müşteri-adres yönetimi, ödeme doğrulama, fatura ve sipariş notu yönetimi gibi kayıtlı olmayan
yetenekler uydurmuştur. Tool/effect oluşmaması bu yanlış envanteri kabul edilebilir kılmaz. R368 ilk
kritik sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r368-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te capability açıklaması bir business read/effect operation değildir; kullanıcının
“yalnız anlat, veri veya aksiyon çalıştırma” sınırı typed `capability_overview` intent/shape'ini
conversation'a düşüremez. Domain kayıtlıysa görünür cevap yalnız canonical
`operations.capability_catalog` ve operation registry metadata'sından deterministic olarak projekte
edilir; model yeni capability adı yazamaz. Catalog, desteklenen Orders read/analysis/return/label/
cargo prepare yeteneklerini ve effectful işlerde açık onay sınırını anlatır; sipariş oluşturma,
ödeme/fatura veya müşteri CRUD gibi kayıtsız iddiaları içermez. Focused conversation regresyonu R368
cümlesini birebir çalıştırır, typed intent'in korunmasını, tek catalog projection'ını, sıfır business
operation'ı ve hallucinated iddiaların yokluğunu kanıtlar. R368'in ilk turu sonraki kampanyaya
taşınmaz; 50+ organik exact V4 Flash kampanyası fresh process/artifact ile yeniden başlar.

2026-08-24 Karar 174, fresh R369 50+ exact V4 Flash kampanyasının üçüncü turunda bulunan
capability-policy follow-up açığını kaydeder. Catalog-grounded yetenek cevabı doğru geçtikten sonra
kullanıcı bunları doğrudan okunabilenler ile prepare + açık onay isteyen effect'ler olarak ayırmasını
istemiştir. Typed karar doğru `policy_explanation(approval, verification)` ve trusted canonical
runtime context üretmiş; model adayı ise genel “kanıtsız business state” filtresinin capability
dilindeki `kargoya hazır siparişleri okumak` ifadesini güncel siparişler hazır iddiası sanmasıyla
reddedilmiştir. Generic fallback `doğrulanmış operasyon verisi yok` diyerek doğru registry/policy
sorusunu cevapsız bırakmıştır. R369 ilk kritik sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r369-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te policy açıklaması evidence-free chat state filtresiyle değil
`TrustedPolicyContext.topics/assertions` sözleşmesiyle doğrulanır. Approval konusu hem canonical R0
read'lerin onaysız/salt-okunur sınırını hem effect'lerin prepare + açık onay + execute sınırını;
verification konusu canonical verify/read-back'i görünür cevapta zorunlu tutar. Capability dili
mevcut business record state'i sayılmaz. Model adayı seçili topic'lerin birini eksik bırakırsa generic
sohbet fallback'i kullanılmaz; aynı secret-free canonical policy assertions deterministic olarak
projekte edilir. Focused regresyon hem tam grounded model adayının kabulünü hem eksik adayın canonical
facts'e onarılmasını ve business tool/effect oluşmamasını kanıtlar. R369'un ilk iki turu yeni
kampanyaya taşınmaz; exact V4 Flash 50+ koşusu fresh process/artifact ile yeniden başlar.

2026-08-24 Karar 175, capability -> policy follow-up kök kapanışını fresh R370 exact V4 Flash
offscreen source-app koşusuyla doğrular. Doğal selam effects-free kalmış; ikinci tur yalnız
canonical Orders capability catalog'undan desteklenen yetenekleri açıklamış ve kayıt dışı CRUD,
ödeme veya fatura yeteneği uydurmamıştır. Üçüncü tur önceki yetenekleri salt-okunur/onaysız işler
ile exact scope -> prepare -> açık onay -> execute gerektiren etkili işler olarak ayırmış;
execute sonrası canonical verify/read-back olmadan tamamlandı denmeyeceğini görünür cevapta
korumuştur. Hiçbir business tool veya dış etki oluşmamış; requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback kapalı kalmıştır. Artifact stale olmadan
`accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r370-deepseek-v4-flash-capability-policy-followup-2026-08-24.json`.
Güncel Orders task + conversation paketi `431 passed / 427 conditional skipped` geçmektedir.
R370 yalnız focused kök kapanışıdır; hiçbir turu organik kabule taşınmaz. Sonraki kapı fresh
process/artifact ile turn 1'den başlayacak en az 50 turluk exact V4 Flash organik kampanyadır.

2026-08-24 Karar 176, fresh R371 50+ exact V4 Flash organik kampanyasının üçüncü turunda bulunan
açık kullanıcı kısıtı kaybını kaydeder. İlk iki tur doğal sohbet ve tek canonical `orders.summary`
ile doğru geçtikten sonra kullanıcı görünür toplam `3120` ile ciro `503546.47 TRY` üzerinden
ortalama hesaplanmasını ve “aynı veriyi tekrar okuma” diyerek yeni operation yapılmamasını açıkça
istemiştir. Provider yorumu bu sınırı doğru açıklamasına rağmen deterministic semantic correction,
Türkçe anaphoric no-reread kalıbını tanımadığı için `existing_observations_only` politikasını
`allow_new_operations`a çevirmiş ve gereksiz ikinci `orders.summary` okuması çalıştırmıştır. Sonuç
`161.39 TRY/sipariş` sayısal olarak doğru olsa da kullanıcı kısıtı ihlal edildiğinden R371 ilk
kritik sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r371-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te “aynı/bu/önceki veriyi tekrar/yeniden okuma-sorgulama-çekme” ve semantik İngilizce
eşdeğerleri, önceki doğrulanmış observation'lara bağlı açık bir no-new-operation permission
boundary'sidir. Bu sınır local snapshot okuma isteğinden ayrıdır: “API'ye gitme, yerelden oku” yeni
R0 local operation'a izin verirken “az önce söylediğin sayıları kullan, aynı veriyi tekrar okuma”
hiçbir yeni read/tool'a izin vermez. Modelin stricter `existing_observations_only` kararı bu açık
sınırda geri genişletilemez; doğrulanmış operandlar conversation state'ten çözülür ve hesap sıfır
tool ile yapılır. Exact Türkçe ve İngilizce boundary regresyonları ile typed derived contract
koruması focused pakette kanıtlanır. R371'in ilk iki turu yeni kampanyaya taşınmaz; önce aynı üç
turlu zincir fresh exact V4 Flash source-app koşusunda sıfır redundant operation ile geçmeli,
ardından 50+ organik kampanya yine turn 1'den başlamalıdır.

Fresh R372 üç turlu exact V4 Flash offscreen source-app focused koşusu R371 zincirini geçmiştir.
İlk business turunda yalnız bir `orders.summary` ile toplam `3120`, tam status dağılımı ve
`503546.47 TRY` ciro observation'ı üretilmiştir. Exact hata cümlesinin tekrarlandığı üçüncü tur
typed `existing_observations_only` politikasını korumuş; sıfır tool call, sıfır task step ve önceki
verified operandlarla `503546.47 / 3120 = 161.39 TRY/sipariş` hesabını göstermiştir. Deterministic
katman yeni business plan kurmamış, model-authored typed calculation'ı yalnız verified projection
olarak render etmiştir. Requested/actual/final model exact `deepseek/deepseek-v4-flash`, fallback
kapalıdır; artifact `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r372-deepseek-v4-flash-no-reread-followup-2026-08-24.json`.
R372 focused kanıttır ve turları organik kabule taşınmaz; sonraki kapı fresh 50+ exact V4 Flash
kampanyasını yeniden turn 1'den başlatmaktır.

2026-08-24 Karar 177, fresh R373 50+ exact V4 Flash organik kampanyasının ikinci turundaki explicit
projection kaybını kaydeder. Kullanıcı yalnız yerel kayıtlardan en son beş siparişi sipariş numarası,
durum, tarih ve “tutarıyla” istemiştir. Canonical `orders.recent` her satır için `total_price` ve
`currency` dahil doğru veriyi döndürmüş; ancak explicit-field grammar Türkçe araç/birliktelik çekimli
`tutarıyla` biçimini monetary amount talebi saymadığı için `unrequested_amount_list_projection_removed`
ve orphaned currency correction'ları alanları projection'dan atmıştır. Görünür cevap beş tutar
observation'da mevcutken yanlış biçimde “tutar bilgisi bulunmamaktadır” demiştir. R373 ilk kritik
sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r373-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te explicit projection sözleşmesi Türkçe alan adlarının doğal isim çekimlerini
canonical field'e kayıpsız bağlar; `tutarı/tutarını/tutarıyla/tutarlarıyla` monetary `amount`
authority'sidir, `tutarlı` sıfatı değildir. Explicit amount listesi currency boyutunu da korur;
verifier observation'da bulunan fiyatları “yok” diye raporlayamaz. Buna karşılık kullanıcı tutar
istemediğinde provider'ın uydurduğu amount/date alanlarını kaldıran privacy/minimal projection guard'ı
aynen kalır. Focused regresyon hem yeni çekimli biçimin tutulmasını hem eski unrequested-field
guard'ının korunmasını birlikte kanıtlar. Sonraki kapı exact cümleyi fresh source-app üzerinde beş
satırın numara/durum/tarih/tutar+para birimiyle görünmesiyle geçirmek, ardından organik 50+ koşuyu
yeniden turn 1'den başlatmaktır.

Fresh R374 iki turlu exact V4 Flash offscreen source-app focused koşusu R373 cümlesini geçmiştir.
Typed projection `order_number/status/date/amount/currency` olarak korunmuş; tek canonical
`orders.recent` read'i son beş kaydı sıralı biçimde getirmiş ve görünür cevap her satırda observed
tutarı `299.99 / 469.97 / 94.99 / 399.98 / 159.99 TRY` ile göstermiştir. API sync veya dış etki
yoktur; unrequested projection guard'ları tetiklenmemiştir. Requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback kapalıdır; artifact `accepted=true / problems=[] / passed`
kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r374-deepseek-v4-flash-inflected-amount-list-2026-08-24.json`.
R374 focused kanıttır; turları yeni organik kabule taşınmaz. Sonraki kapı fresh 50+ exact V4 Flash
kampanyasını tekrar turn 1'den başlatmaktır.

2026-08-24 Karar 178, fresh R375 50+ exact V4 Flash organik kampanyasının ikinci turundaki privacy
negation-scope açığını kaydeder. Kullanıcı “numarası, durumu, tarihi ve tutarı yeterli, müşteri ya
da adres bilgisi verme” diyerek ilk dört alanı açıkça istemiş ve yalnız müşteri/adresi yasaklamıştır.
Canonical `orders.recent` üç satırın bütün değerlerini döndürmüş; ancak negative projection guard
`verme` yükleminin geriye dönük penceresini tamamlanmış `... yeterli` pozitif isim öbeğinin ötesine
taşırarak status/date/amount alanlarını da yasaklamıştır. Görünür cevap bu nedenle yalnız sipariş
numaraları ile currency göstermiştir. R375 ilk kritik sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r375-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te privacy negation bir serbest mesafe penceresi değildir; olumsuz yüklem yalnız kendi
isim öbeği/clause kapsamındaki alanları yasaklar. `yeterli/kâfi/olsun/istiyorum` gibi tamamlanmış
pozitif projection yüklemleri ile `göster/listele/söyle/yaz/ekle` gibi önceki pozitif komut sınırının
solundaki alanlar sonraki `verme/gösterme` ile silinemez. Exact R375 cümlesinde prohibited set yalnız
`customer_name/address`; retained set `order_number/status/date/amount/currency` olmalıdır. Eski
“ürün/adet/kargo/tutar göster; müşteri ve adres verme” gizlilik regresyonu da korunmalıdır. Sonraki
kapı bu exact zinciri fresh source-app üzerinde doğru görünür satırlarla geçirmek, ardından 50+
organik exact V4 Flash koşusunu tekrar turn 1'den başlatmaktır.

Fresh R376 iki turlu exact V4 Flash offscreen source-app focused koşusu R375 cümlesini geçmiştir.
Tek canonical `orders.recent` read'i üç kaydı getirmiş; typed projection yalnız
`order_number/status/date/amount/currency` alanlarını korumuş ve görünür cevap üç satırın her birini
numara, durum, tarih ve observed TRY tutarıyla göstermiştir. Müşteri veya adres görünür cevaba
sızmamış; API sync/dış etki oluşmamıştır. Requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback kapalıdır; artifact `accepted=true / problems=[] / passed`
kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r376-deepseek-v4-flash-privacy-negation-scope-2026-08-24.json`.
R376 focused kanıttır ve yeni organik kabule tur taşımaz; sıradaki kapı fresh 50+ exact V4 Flash
kampanyasını yeniden turn 1'den başlatmaktır.

2026-08-24 Karar 179, fresh R377 50+ exact V4 Flash organik kampanyasının ilk turunda yeniden
görülen count/list parity açığını kaydeder. Kullanıcı yerel kargoya-hazır kuyruğun hem sayısını hem
de sipariş numaralarının tamamını aynı cevapta istemiştir. Typed yorum `record_list` ve
`count + order_number` projection'ını doğru taşırken metric'i `count` bırakmış; scalar
`orders.ready_to_ship_count` planı ready-count metric requirement'ını karşıladığı için record-shape
operation guard atlanmıştır. Tool sonucu `0`, boş `orders/order_numbers`, `listed_count=0` ve
`truncated=false` ile aslında authoritative boş selection kanıtı taşısa da contract `list`
olmadığından verifier bunu “sipariş numarası kanıtı yok” diye reddetmiş ve görünür cevap liste
isteğini karşılamamıştır. R377 ilk kritik sapmada failed kapatılmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r377-deepseek-v4-flash-organic-50-2026-08-24.json`.

Yeni invariant'te “kaç tane + bütün/tüm/tamam sipariş numaralarını ver/söyle/yaz” scalar count
değil, cardinality projection'ı da olan tek exhaustive `record_list` sözleşmesidir. Metric `list`,
scope `ready_to_ship/all_matching`, projection `count + order_number` olur; expected operation set
yalnız canonical `orders.query/orders.ready_to_ship` olabilir. Scalar metric requirement'ın mevcut
olması projection/record-shape operation doğrulamasını devre dışı bırakamaz; model count planı bounded
semantic repair ile list operation'a çevrilmeden execute edilmez. Authoritative boş sonuçta görünür
cevap hem `0` sayısını hem kuyruğun/listenin boş olduğunu söyler; “kanıt bulunamadı” demez. Focused
regresyon doğal exhaustive-identity dilini, count-plan rejection/repair'i ve eski empty-list
verification'ını birlikte kanıtlar. Sonraki kapı exact R377 cümlesini fresh source-app üzerinde tek
authoritative list selection ile geçirmek, ardından 50+ kampanyayı yeniden turn 1'den başlatmaktır.

2026-08-24 Karar 180, R377 kök kapanışını sınayan fresh R378 focused source-app koşusunun güvenli
ama ürün açısından yetersiz failure'ını kaydeder. Typed metric artık doğru `list`; scalar count planı
hem initial hem bounded model repair aşamasında `typed_read_contract_operation_mismatch` ile execute
öncesi reddedilmiştir. Ancak ready-list contract'ı eşdeğer görünen iki operation'a
`orders.query/orders.ready_to_ship` izin verdiği için unique typed-read recovery tek kanonik seçim
yapamamış ve tam belirtilmiş kullanıcı isteğine gereksiz clarification göstermiştir. Hiçbir business
tool/effect oluşmaması güvenlik başarısıdır; hedefin yapılmaması ürün kabulü değildir. R378 failed
kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r378-deepseek-v4-flash-ready-count-list-empty-2026-08-24.json`.

Yeni invariant'te her fully-specified typed atomic contract'ın tek preferred canonical operation'ı
vardır. Ready-to-ship exhaustive list için bu operation `orders.ready_to_ship`tir; generic
`orders.query` başka filtreli sorguların reusable primitive'i olarak kalır fakat bu contract'ın
eşdeğer primary lowering'i değildir. Initial ve repair model planları aynı scalar count'u tekrar
etse dahi ikisi policy/shape verifier tarafından reddedildikten sonra typed compiler yalnız bu tek
read-only, non-destructive, approval-free canonical operation'ı `typed_unique_read_recovery` olarak
lower edebilir; hedef/filtre/kimlik uyduramaz. Bu lowering modelin business hedefini icat etmez,
model-authored typed list contract'ını registry'deki tek kanonik callable'a bağlar. Focused test
double-count failure'ı, unique recovery provenance'ını ve canonical `orders.ready_to_ship` seçimini
kanıtlar. Sonraki kapı exact R377/R378 cümlesini yeni fresh source-app koşusunda authoritative boş
selection cevabıyla geçirmek, ardından 50+ kampanyayı yeniden başlatmaktır.

Fresh R379 tek turlu exact V4 Flash offscreen source-app focused koşusu R377/R378 zincirini
geçmiştir. Typed contract `list + ready_to_ship + all_matching`, projection
`count + order_number` kalmış; initial ve repair scalar count planları reddedildikten sonra tek
preferred canonical `orders.ready_to_ship` read'i `typed_unique_read_recovery` provenance'ıyla
çalışmıştır. Authoritative sonuç `ready_to_ship=0`, `listed_count=0`, boş `orders/order_numbers` ve
`truncated=false` taşımış; görünür model cevabı “Kargoya hazır 0 sipariş var. Sipariş numarası
bulunmamaktadır.” diyerek sayım ve boş identity setini aynı cevapta doğru yansıtmıştır. API sync veya
etki yoktur; requested/actual/final model exact `deepseek/deepseek-v4-flash`, fallback kapalıdır;
artifact `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r379-deepseek-v4-flash-ready-count-list-empty-2026-08-24.json`.
R379 focused kanıttır; sonraki organik kabule tur taşımaz. Sıradaki kapı fresh 50+ exact V4 Flash
kampanyasını tekrar turn 1'den başlatmaktır.

2026-08-24 Karar 181, R379 sonrasındaki tam Orders regresyonunda bulunan operation-shape guard
genişleme hatasını kaydeder. Metric requirement bulunsa dahi expected operation setini zorlamak
ready `record_list` için doğruyken, `count/status/revenue/item-sales` gibi birden çok metric'i
compose eden population analysis sözleşmesinde generic `metric=count` expected operation'ı bütün
geçerli summary + item planını yanlış reddetmiştir. Yeni invariant'te expected canonical operation
shape şu iki durumda zorunludur: contract record-shaped (`metric=list/detail`,
`request_shape=record_list/detail` veya `record_scope=exact_ids/active_selection`) ya da contract'ta
ayrı metric requirement yoktur. Aggregate multi-metric analizlerde doğrulama operation adıyla değil
minimal metric coverage ile yapılır. Focused regresyon hem R377 ready-list unique recovery'yi hem
genel analizde `orders.summary + orders.item_sales_summary` repair'ini birlikte geçirir. Bu düzeltme
runtime fingerprint'ini değiştirdiği için R379 tek başına güncel source kanıtı sayılmaz; exact ready
count/list empty zinciri fresh R380 source-app koşusunda yeniden geçmeden 50+ kampanya açılamaz.

Fresh R380 current-fingerprint tek turlu exact V4 Flash offscreen source-app koşusu son zinciri
geçmiştir. Contract `list + ready_to_ship + all_matching`, projection `order_number + count`; plan
source `typed_unique_read_recovery`; tek canonical operation `orders.ready_to_ship`tir. Authoritative
sonuç `ready_to_ship=0`, `listed_count=0`, boş `orders/order_numbers`, `truncated=false` taşımış;
görünür cevap “Kargoya hazır 0 sipariş var. Kargoya hazır sipariş kuyruğu boş; sorgu kapsamında
0 sipariş bulundu.” diyerek count/list parity'yi açıkça göstermiştir. İlk structured çağrıda
normalized retryable transport error oluşmuş, aynı exact modelde toparlanmıştır; requested/actual/
final model `deepseek/deepseek-v4-flash`, model fallback false kalmıştır. Artifact stale olmadan
`accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r380-deepseek-v4-flash-ready-count-list-empty-2026-08-24.json`.
Güncel birleşik Orders task + conversation regresyonu `434 passed / 1 conditional skipped`
geçmiştir. R380 focused kanıttır ve organik kabule tur taşımaz. Sonraki kapı fresh 50+ exact V4
Flash kampanyasını turn 1'den yeniden başlatmaktır.

2026-08-24 Karar 182, fresh R381 exact V4 Flash organik kampanyasının ilk turunda bulunan
canonical metric ayrıştırma hatasını kaydeder. Kullanıcının “iptal edilmiş kaç sipariş var ve iptal
nedenleri nasıl dağılıyor; dışarıdan güncelleme yapma” hedefinde model ilk planda doğru biçimde
`orders.cancellations` seçmiş; fakat deterministic compiler `reason` alanını genel status
dağılımıyla karıştırarak `orders.total_count + orders.status_distribution` istemiş, doğru planı
reddedip repair'i `orders.status_counts` yönüne itmiştir. Bu, güçlü modelin hatası değil bizim
semantic contract katmanımızın planı bozmasıdır. Yeni invariant'te `orders.cancelled_count` ve
`orders.cancellation_reason_distribution` ayrı first-class metric'tir; cancelled reason hedefi
global order total/status distribution'a indirgenemez. Canonical `orders.cancellations` tek read ile
hem `cancelled_orders` hem `cancel_reasons` kanıtını sağlar ve modelin doğru doğrudan planı repair
edilmeden kabul edilir. `reason` projection yalnız açık cancellation-reason talebinde korunur;
modelin aynı cümleye eklediği fakat kullanıcıca istenmeyen genel `status` projection'ı kaldırılır.
Response verifier iptal sayısının yanında authoritative reason map'teki her nedeni ve adedini
görünür cevapta zorunlu tutar; sıfır/boş ve reason-unavailable semantiği ayrıca doğrulanır.
`orders.cancellations` sonucu Cancelled status için de authoritative evidence sayılır. Focused
regresyon doğru planın `llm_direct` kaldığını, eksik neden cevabının reddedildiğini ve tam cevabın
geçtiğini kanıtlar; geniş `orders.summary + orders.item_sales_summary` analizi ve ready-list
recovery de birlikte korunmuştur. Güncel birleşik Orders task + conversation regresyonu
`435 passed / 1 conditional skipped` geçmiştir. R381 artifact'i intentional failure kanıtıdır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r381-deepseek-v4-flash-organic-50-2026-08-24.json`.
Kök nedenin kapanışı ancak aynı doğal ifadeyi fresh source-app exact V4 Flash R382 koşusunda
`orders.cancellations`, doğru reason dağılımı, eksiksiz görünür cevap ve model fallback olmadan
geçirmekle kanıtlanır; bundan sonra fresh 50+ kampanya yine turn 1'den başlar.

Fresh R382 current-fingerprint focused source-app tekrarı Karar 182 kapısını geçmiştir. Aynı doğal
Türkçe kullanıcı ifadesi typed contract'ta projection `count + reason`, status scope `cancelled` ve
metric requirements `orders.cancelled_count + orders.cancellation_reason_distribution` üretmiştir;
modelin tek adımlı `orders.cancellations` planı `llm_direct` kalmış, compiler repair'e gitmemiştir.
Authoritative sonuç 110 iptal siparişi ve altı neden/adet çiftini taşımış; görünür model cevabı
110 sayısını ve `Vazgeçtim (51), Yanlış ürün seçtim (48), Fiyat sebepli vazgeçtim (12), Yanlış
kartla ödeme yaptım (7), Teslimat tarihi gecikti (5), Mücbir sebep (2)` dağılımının tamamını
eksiksiz yansıtmıştır. Genel toplam veya global status distribution cevaba sızmamıştır. Response
projection ilk model adayında doğrulanmış, repair/fallback gerekmeden final kaynak
`verified_model_candidate` olmuştur. Requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback false; artifact `accepted=true / problems=[] / passed`
kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r382-deepseek-v4-flash-cancellation-reasons-2026-08-24.json`.
R382 focused kanıttır ve organik kabul turu değildir. Sıradaki kapı fresh process/artifact ile en az
50 turluk exact V4 Flash organik kampanyasını turn 1'den yeniden başlatmaktır.

2026-08-24 Karar 183, fresh R383 50+ exact V4 Flash organik kampanyasının üçüncü turunda bulunan
typed continuation ve no-new-read hatasını kaydeder. İlk turdaki `last_30_days` Orders summary
authoritative olarak 8 sipariş, 1964.88 TRY ve status map üretmiş; ikinci tur aynı observation'dan
sıfır tool ile 245.61 TRY/sipariş hesabını doğru tamamlamıştır. Üçüncü tur “aynı 30 günlük sonuç
içinde durum dağılımını söyle; veriyi yeniden okuma” dediğinde ise `_existing_observations_only`
Türkçedeki nesne -> yeniden -> olumsuz fiil sırasını ve `_repeat_previous_read_signal` anaforik
“aynı ... sonuç içinde” devamını tanımamıştır. Compiler modelin `allow_new_operations + period=all`
sapmasını düzeltmek yerine kabul etmiş; `orders.status_counts(period=all)` çalışıp 30 günlük 8
sipariş bağlamı yerine tüm dönem 3120 sipariş dağılımını göstermiştir. Yeni invariant'te açık
`veriyi/sonucu yeniden-tekrar okuma-sorgulama-çekme` kalıbı, belirteç cümlenin daha gerisinde olsa
dahi `existing_observations_only` permission boundary'dir. `aynı/bu/önceki ... sonuç/özet/dağılım/
veri içinde-üzerinden-göre` anaforu typed prior-read continuation sayılır: önceki period/status
scope korunur, yalnız son cümlede açıkça istenen projection alanları devralınır. R383 exact
regresyonu model `status+count`, `period=all`, `allow_new_operations` üretse dahi normalize edilmiş
sözleşmenin `status`, `last_30_days`, yalnız `orders.status_distribution` ve
`existing_observations_only` olduğunu; prior `orders.summary.status_counts` kanıtından sıfır tool ile
doğru dağılım üretildiğini kanıtlar. Güncel birleşik Orders task + conversation regresyonu
`436 passed / 1 conditional skipped` geçmiştir. R383 artifact'i intentional failure kanıtıdır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r383-deepseek-v4-flash-organic-50-2026-08-24.json`.
Kapanış fresh R384 exact V4 Flash source-app'te önce 30 günlük summary'yi kurup aynı follow-up'ı
sıfır yeni operation, inherited period ve eksiksiz status map ile geçirmek; ardından 50+ kampanyayı
yine turn 1'den başlatmaktır.

Fresh R384 iki turlu current-fingerprint focused source-app zinciri Karar 183 kapısını geçmiştir.
İlk tur exact `deepseek/deepseek-v4-flash` ile canonical `orders.summary(period=last_30_days)`
çalıştırmış ve authoritative 8 sipariş / 1964.88 TRY / `status_counts={Delivered: 8}` üretmiştir.
İkinci turda R383'teki aynı doğal “aynı 30 günlük sonuç ... veriyi yeniden okuma” follow-up'ı
projection `status`, period `last_30_days`, metric requirement `orders.status_distribution` ve
operation policy `existing_observations_only` olarak normalize edilmiştir. Yeni operation/tool
sayısı sıfırdır; görünür cevap yalnız prior summary observation'ındaki `Delivered 8` dağılımını
göstermiştir. Decision path `typed_existing_observation_verified_projection`, final source
`deterministic_existing_observation_projection`; requested/actual/final model exact V4 Flash,
fallback false ve artifact `accepted=true / problems=[] / passed` kapanmıştır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r384-deepseek-v4-flash-period-observation-followup-2026-08-24.json`.
R384 focused kanıttır, organik kabul turu değildir. Sonraki kapı fresh 50+ exact V4 Flash
kampanyasını turn 1'den yeniden başlatmaktır.

2026-08-24 Karar 184, fresh R385 50+ exact V4 Flash organik kampanyasının dördüncü turunda
bulunan Orders -> public web composition boşluğunu kaydeder. İlk üç tur capability catalog -> son
dört siparişin privacy-minimal listesi -> listedeki ikinci siparişin exact full-context bağlamı olarak
doğru ilerlemiştir. Dördüncü turda kullanıcı bu siparişteki ilk ürünü PII taşımadan internette
araştırıp açılan kaynak linkleriyle özetlemeyi istemiştir. Model turn interpreter bu cross-source
hedefi salt `domain=web / external_public_web` sınıflandırmış; task plan mevcut typed Orders
selection'ı ve ürün observation'ını bağlamadan kullanıcı cümlesini doğrudan `web.search.query`
yapmıştır. Privacy boundary ilk sorguyu haklı olarak engellemiş; fakat observation replanning
canonical public identity'ye dönmek yerine generic “first product in order type reviews opinions”
sorgusu ve statik `example.com/product-reviews` URL'si uydurmuştur. Private veri dışarı çıkmamış
olsa da hiçbir ilgili açılmış kaynak veya kullanıcı hedefi üretilmediği için güvenli ret ürün başarısı
değildir.

Yeni invariant'te typed prior Orders selection'a deictic ürün referansıyla bağlanan web hedefi
`domain=orders`, `information_source=mixed_local_and_public`, `record_scope=active_selection` ve
`contextual_public_product_web_research_required=true` sözleşmesidir. Görünür projection
`item + research_findings + web_sources` olur; modelin ilgisiz ratio veya private customer/order
alanları kaldırılır. Ürün ordinali (`ilk/birinci/ikinci/...`) typed `contextual_product_ordinal`
olarak korunur. Orders-owned `build_order_product_public_identities` ve ince AI tool şeması artık
`item_ordinal` destekler; seçili order içindeki yalnız hedef kalemi product name/barcode gibi
policy-onaylı kamu alanlarına çevirir, order/customer/address/tracking/SKU sızdırmaz. Execution
boundary modelin ordinal sapmasını typed contract değeriyle ezer.

Bu contract'ta canonical read operation `orders.product_public_identities`tir; `orders.full_context`
privacy-safe web girdisinin yerine geçemez. Model-authored planın identity -> search -> open typed
dependency zinciri compiler tarafından zorunlu tutulur: `web.search.query` ve
`public_product_fields` identity outputlarından, `web.open.url` ise gerçek search primary/secondary
URL outputundan gelmelidir. Kullanıcı prose'unu doğrudan query yapan, identity adımını atlayan veya
statik/uydurma URL kullanan plan reddedilip model-authored repair'e gönderilir. Response verifier
requested web research için en az bir gerçekten açılmış WebObservation, cevapta bütün açılmış URL
citations ve hedef public product adını zorunlu tutar; salt search snippet'i veya güvenli ret kabul
edilmez. R385 exact regresyonu modelin eski iki adımlı hatalı planını reddedip üç adımlı bound graph'a
repair ettiğini, aktif exact order ve ordinal 1'in execution boundary'de bağlandığını ve canonical
repository'nin yalnız ilk public ürünü PII'siz döndürdüğünü kanıtlar. Güncel birleşik Orders task +
conversation regresyonu `437 passed / 1 conditional skipped` geçmiştir. R385 artifact'i intentional
failure kanıtıdır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r385-deepseek-v4-flash-organic-50-2026-08-24.json`.
Kapanış fresh R386 exact V4 Flash source-app'te typed order selection -> target item ordinal -> public
identity -> dependency-bound search -> gerçekten açılmış ilgili source -> cited summary zincirini PII
sızmadan geçirmek; ardından fresh 50+ kampanyayı yine turn 1'den başlatmaktır.

2026-08-24 Karar 185, R386/R387 focused exact V4 Flash source-app zincirinde Karar 184'ün
ardından bulunan ikinci public-research boşluğunu kaydeder. R386'nın ilk iki turu en son dört
siparişi privacy-minimal sıralamış ve listedeki ikinci siparişin iki kalemini/adetlerini exact
selection ile doğru materialize etmiştir; kabul subprocess'i yeni komut beklerken operatör
tarafından yanlışlıkla kapatıldığı için kapanış artifact'i sayılmaz. Fresh R387 aynı iki halkayı
exact `deepseek/deepseek-v4-flash`, fallback kapalı ve görünür doğru cevapla yeniden geçmiştir.
Üçüncü turda ilk ürün doğru sipariş/ordinal ile `orders.product_public_identities` üzerinden
privacy-safe bağlanmış, gerçek web araması yapılmış ve search output'una bağlı URL açılmıştır.
Buna rağmen provider'ın `broad_analysis + item_sales_rows` sapması normalization sırasında
`research_findings/web_sources` alanlarını silip ilgisiz `orders.item_sales_summary` adımını plana
sokmuştur. İlk ürün sayfası ayrıca genel kategori sayfasına yönlenmiş; sayfadaki genel askı metni
ürün tipiyle kelime benzerliği taşıdığı için yeterli kanıt sanılmıştır. Görünür cevap yalnız dört
tool adımını ve bir linki saymış, kullanıcının “insanlar ne söylüyor” hedefini cevaplamamıştır.
R387 bu nedenle intentional failure'dır:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r387-deepseek-v4-flash-contextual-web-research-2026-08-24.json`.

Yeni invariant'te contextual public-product research kendi exact projection sözleşmesine sahiptir:
`item + research_findings + web_sources`, `request_shape=focused_analysis`,
`freshness=current_local`. Aynı cümlede ürün sözcüğü geçmesi satış analizi yetkisi değildir;
contextual web contract'ına eklenen `item_sales_rows`, ratio veya başka Orders aggregate alanları
silinir ve `orders.product_public_identities` dışındaki ilgisiz Orders operasyonları planı
semantic repair'e gönderir. Kullanıcının yorum/değerlendirme/deneyim veya insanların ne söylediği
amacı typed `public_research_facets=[user_opinions]` olarak korunur. Execution boundary bu facet'i
canonical Orders public-identity fonksiyonuna bağlar; fonksiyon private alan eklemeden ürün sorgusuna
genel public araştırma terimlerini (`kullanıcı yorumları değerlendirme deneyim`) ekler. Kaynak
erişilebilirliği yine kanıt yeterliliği değildir: opinion facet'inde açılmış metin gerçek yorum,
değerlendirme, deneyim, memnuniyet, şikâyet veya eşdeğer evidence izi taşımıyorsa kaynak başarısız
sayılır ve cite edilemez. URL içindeki `review` gibi domain/path parçaları kullanıcı opinion niyeti
sayılmaz. Focused R385/R387 sözleşme testleri ve birleşik Orders task + web regresyonu güncel olarak
`453 passed / 1 conditional skipped` geçmiştir. Kapanış fresh source-app zincirinde doğru ilk ürün
-> opinion-aware privacy-safe query -> ilgili gerçekten açılmış kaynak -> kısa grounded bulgular +
açılmış URL citations cevabını kanıtlamaktır; ardından 50+ exact V4 Flash organik kampanya yine
turn 1'den başlar.

2026-08-24 Karar 186, hedef yeniden başlatıldığında uygulanacak model-test önceliğini son kez
bağlayıcı kılar. Geliştirme, kök-neden ayırma ve ücretli kontrol koşuları fallback kapalı exact
`deepseek/deepseek-v4-flash` ile yürütülür; artifact her turda requested/actual/final model
kimliğinin aynı olduğunu kanıtlamalıdır. Ücretsiz ürün kabulünde Gemini ve OpenRouter ayrı ayrı
ele alınır ve her provider için canlı katalogda gerçekten erişilebilen, gerekli structured-output /
tool-use capability'sini taşıyan en güçlü ücretsiz adayla başlanır. Bir ücretsiz aday ancak
normalize edilmiş model-kapsamlı kota veya gerçek erişilemezlik kanıtıyla aynı provider'daki
sıradaki **güçlü** ücretsiz adaya devredilebilir; sessiz model fallback'i kabul kanıtı değildir.
Ücretli V4 Flash başarısı ücretsiz baseline'ın, bir provider'ın başarısı diğer provider'ın yerine
geçmez. Nispeten düşük quality-tier cloud modeller, küçük modeller, local inference ve degradation
kampanyaları güçlü ücretli kontrol ile iki provider'ın güçlü ücretsiz baseline'ları kararlı hale
gelene kadar bekletilir. Bu sıra zayıf/local model özgürlüğü hedefini kaldırmaz; mevcut geliştirme
bütçesini önce agent plan/state/tool/verifier mimarisindeki hataları en yüksek sinyalle bulmaya
ayırır. Bütün gerçek source-app yanıtları Codex tarafından tek tek okunmadan kampanya geçmiş
sayılmaz.

2026-08-30 Karar 187, R392-R395 zincirinde güçlü modelin doğru plan kurmasına rağmen final cevap ve
web-topic kanıtının provider-bağımsız taşıma sözleşmelerindeki iki açığı kapatır. Final sentez artık
provider'a özgü response_format davranışına bağlı değildir: aynı modelden alınan `final_text`
contract'ı, yeterli output bütçesi ve final kaynak provenance'ı ile taşınır; kardeş model fallback'i
kapalı kalır. Web evidence evaluator ürün bağlamlı araştırmada tüm serbest goal cümlesini değil aynı
`web.search` sonucundan `web.open`a taşınan typed `query_summary`yi topic basis kabul eder. Türkçe
`tutarlı` gibi sözcükler `tutar` niyeti değildir; measurement intent kök+izinli ek sınırıyla ayrılır.
Bu değişiklikler tek tek verilen sohbet cümlelerine cevap ezberletmek değil, plan -> observation ->
final response taşıma katmanlarını provider/model bağımsız hale getirmektir.

2026-08-30 Karar 188, R396-R398 public ürün araştırma failure sınıfını bağlayıcı hale getirir.
`web.open` yalnız URL'yi değil aynı `web.search` adımından gelen `query_summary` ve
`public_product_fields` bağlarını da taşımalıdır; üç provenance bağı aynı source step ve dependency
üzerinde doğrulanmadan plan çalışmaz. Açılmış sayfada `12 yorum` veya `14 değerlendirme` sayısı
görmek yorumların ne söylediğini kanıtlamaz: opinion count, opinion content/sentiment'ten ayrı typed
evidence'tır. Cevap görünür sayıları dürüstçe söyleyebilir, fakat yorum metni/puan özeti/dağılımı yoksa
duygu veya kullanıcı görüşü uyduramaz. R397 işlevsel geçse de adaptif insan inceleme metadata'sı
eksik olduğu için; R398 işlevsel geçse de persisted public citation redaksiyon sırasında bozulduğu
için intentional failure sayılmıştır. İnsan/Codex incelemesi ve geçerli kanıt linki kabulün zorunlu
parçasıdır.

2026-08-30 Karar 189, R399-R404 focused exact V4 Flash zincirinde görünür kimlik, semantic routing,
ordinal doğrulama ve artifact privacy sınırlarını kapatır. Kullanıcının ham sipariş kimliği yerine
sıra/ordinal istemesi typed `identifier_display=ordinal` sözleşmesidir; canonical order id içeride
selection key olarak kalır, requested projection'dan çıkar ve cevap `1. sipariş`, `2. sipariş` gibi
kararlı referanslar üretir. Markdown `- 3. sipariş` biçimi gerçek ordinaldir, uydurma business sayısı
değildir. `görünmüyor` sözcüğü tek başına stale iade reconciliation yetkisi vermez; bu route ancak
stale sinyaliyle birlikte açık `iade/return/claim` entity izi varsa seçilir. Olumsuz projection
bağlamında yalın `takip` ile `özel sipariş kimliği` de private field yasağıdır; olumlu `siparişi takip
et` cümlesi tracking-number projection'a çevrilmez. Live evidence redactor doğrulanmış public web
URL'lerini structured URL alanlarından toplar, cevap içindeki aynı citations'ı korur; private order,
claim, tracking, secret ve local path redaksiyonu devam eder. Source-UI artifact writer bu ortak
public-URL ön geçişini doğrudan kullanmak zorundadır.

Fresh R404 offscreen full-source-app koşusu exact `deepseek/deepseek-v4-flash`, fallback kapalı ve
adaptif insan incelemesiyle geçmiştir. Turn 1 son dört siparişi private order id/PII olmadan 1-4
ordinal olarak göstermiş; turn 2 ikinci ordinal siparişin iki ürününü doğru `adet: 1` ve `adet: 2`
ile, yasaklı müşteri/adres/takip/kimlik alanları olmadan vermiştir. Turn 3 aynı ilk ürünü
`orders.product_public_identities -> web.search -> web.open` provenance zinciriyle araştırmış; beş
ilgili açılmış kaynak, geçerli persisted citations, görünür 14 değerlendirme/12 yorum gibi count
kanıtları ve yorum içeriği yokluğunda doğrulanmış belirsizlik üretmiştir. Requested/actual/final
model her turda exact V4 Flash, sibling fallback yoktur. Kabul artifact'i:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r404-deepseek-v4-flash-contextual-web-research-2026-08-30.json`.

2026-08-30 Karar 190, R404 sonrasındaki current-source tam AI domain pytest kapısını
`1379 passed / 816 skipped / 0 failed` ile kapatır. Skip'ler bu çalışma alanında bulunmayan tarihsel
live fixture veya koşullu gerçek-provider kanıtlarıdır; aktif unit, integration, offscreen source-UI,
Orders task runtime, behavioral E2E, web research, artifact/redaction ve provider-routing testlerinde
failure yoktur. Bu focused kabul 50+ organik kampanyanın yerine geçmez. Sıradaki kapı fresh process,
fresh artifact ve turn 1'den başlayacak en az 50 turluk exact paid DeepSeek V4 Flash source-app
kampanyasıdır; her cevap Codex tarafından okunur ve ilk gerçek mimari/semantik hata kampanyayı durdurup
fresh kapanış gerektirir. Paid kapı kararlı olduktan sonra Gemini ve OpenRouter'ın ayrı ayrı canlı
katalogda erişilebilen en güçlü ücretsiz modelleri sınanır. Düşük-tier cloud ve local modeller bu üç
güçlü baseline tamamlanana kadar bekler.

2026-08-31 Karar 191, fresh R405 exact paid V4 Flash organik kampanyasının ilk gerçek failure'ını
bağlayıcı hale getirir. İlk tur gündelik sohbeti business tool'una kaçmadan, ikinci tur canonical
Orders capability kataloğunu işlem çalıştırmadan doğru cevaplamıştır. Üçüncü turda ise model yerel
snapshot tazelik sınırını doğru açıklamasına rağmen “salt okunur sorgular (veri çekme, listeleme)
onay gerektirmez” diyerek iki farklı operasyonu birleştirmiştir. Kalıcı yerel snapshot'tan R0
count/list/analysis okumak onaysızdır; pazaryeri API'sinden sipariş çekip yerel snapshot/DB'yi
güncellemek salt okuma değildir. Bu sync hedefi `orders.fetch.prepare` ile exact hesap kapsamında
hazırlanır, açık onaydan önce execute edilmez ve sonrasında DB read-back ile doğrulanır. R405 bu
tek görünür politika sapmasında kasıtlı `failed` kapatılmıştır; önceki iki tur yeni kampanyaya
devredilemez.

Canonical runtime policy artık marketplace sync'i hem freshness hem approval topic'inde açıkça
effectful olarak sınıflandırır. Policy candidate semantic verifier; API/pazaryeri refresh'ini veya
yerel kaynakla nitelendirilmemiş “veri çekme”yi onaysız R0 okuma sayan model cümlesini reddeder ve
yalnız trusted assertions'tan fail-safe projection üretir. Doğru ayrımı yapan model cevabı doğal
biçimiyle korunur. Focused R405 regresyonları geçmiştir. Sıradaki koşu source fingerprint değiştiği
için yeniden turn 1'den başlayan fresh 50+ exact `deepseek/deepseek-v4-flash` kampanyasıdır. Bu
ücretli güçlü kontrol tamamlanmadan ücretsiz baselinelara; Gemini ve OpenRouter'ın erişilebilen en
güçlü ücretsiz adayları tamamlanmadan düşük-tier veya local modellere geçilmez.

2026-08-31 Karar 192, fresh R406 exact V4 Flash kampanyasında prior-observation permission
sınırının yeni bir dil varyasyonunda kaybolduğunu kaydeder. Turn 1-3 doğal sohbet, canonical
capability ve yerel-read/marketplace-sync politikasıyla geçmiştir. Turn 4, aynı production yerel
snapshot'tan toplam 3120 sipariş, tam durum dağılımı, 503.546,47 TRY ciro ve açık formüllü ortalama
üretmiştir. Turn 5 hiçbir tool açmadan aynı typed observation'dan üç durum yüzdesini doğru
hesaplamıştır. Turn 6'da kullanıcı “yine yeni sorgu açmadan” dediği hâlde interpreter
`allow_new_operations` üretmiş ve gereksiz `orders.status_counts` çağırmıştır. Son matematik doğru
olsa dahi açık operation-policy kısıtı ihlal edildiği için R406 kasıtlı `failed` kapatılmıştır.

“Yeni sorgu açma/açmadan” ifadesi artık “tool çalıştırma/kullanma” ile aynı typed
`existing_observations_only` permission boundary'sidir. Bu sınır varken model
`allow_new_operations` önerse de normalization onu mevcut typed observation'a zorlar; yeterli
kanıt varsa hesap deterministic verified projection ile toolsuz yapılır, yetmiyorsa yeni sorgu
açmak yerine dürüst eksik-kanıt cevabı verilir. Yerel snapshot'tan ilk kez okuma isteği ile harici
API refresh yasağı yine ayrı eksenlerdir; “API'yi yenileme, mevcut yerel snapshot'tan oku” meşru R0
okumasını engellemez. Focused R406 regresyonunda 2958 / (110 + 52) = 18,26 hesabı prior
`orders.summary` kanıtından sıfır tool call ile geçmiştir. Source değişikliği nedeniyle 50+ exact
V4 Flash kampanyası yine fresh process ve turn 1'den başlayacaktır.

2026-08-31 Karar 193, kullanıcı tarafından güçlü-model-first test sırasını yeniden bağlayıcı
hale getirir. Mevcut geliştirme ve teşhis koşularında ücretli kontrol modeli fallback kapalı exact
`deepseek/deepseek-v4-flash`tır. Bunun ardından aynı frozen ürün-yolu senaryoları Gemini ve
OpenRouter'ın **ayrı ayrı**, canlı katalog/hesap erişiminde gerçekten kullanılabilen en yüksek
quality-tier ücretsiz modelleriyle yürütülür. Güçlü ücretsiz aday model-kapsamlı kota veya erişim
engeline takılırsa yalnız aynı provider içindeki sıradaki güçlü quality-tier adaya geçilebilir;
provider/account/project kapsamlı veya belirsiz limit daha zayıf modellere kaçış gerekçesi değildir.
Nispeten düşük-tier cloud modeller, küçük modeller, local inference ve degradation kampanyaları bu
üç güçlü baseline kararlı hale gelene kadar bekler. Exact-model artifact her turda requested,
actual ve final model kimliğini, fallback durumunu ve normalized quota scope'u taşımadıkça kabul
kanıtı sayılmaz. Ücretli V4 Flash ücretsiz uyumluluğun yerine geçmez; fakat güçlü V4 Flash'ta da
görülen hata öncelikle model yetersizliği değil runtime/state/operation/projection sözleşmesi kusuru
olarak ele alınır.

Fresh R407 exact V4 Flash kampanyası yeni bir typed projection ayrımını ortaya çıkarmıştır. “Son
beş siparişi sıra numarası, tarih, durum, tutar ve kalem sayısıyla göster” hedefindeki `kalem sayısı`,
ürün adı/ürün içeriği isteyen `item` veya sipariş nüfusu isteyen `count` değildir; her sipariş
satırının `item_count` alanıdır. Bu hedef canonical `orders.recent(limit=5)` ile karşılanabilir;
yalnız kalem sayısı istendi diye `orders.full_context` zorlanamaz. Domain-owned recent-order
projection seçilen sınırlı siparişlerin latest OrderItem satırlarını tek sorguyla sayar; AI katmanı
bu sayıyı yalnız typed `item_count` olarak taşır ve kullanıcı istemediyse order id, müşteri, adres
ve takip bilgisini açığa çıkarmaz. R407 ilk gerçek sapmada kasıtlı failed kapanmıştır; focused
regresyonda ordinal satırlar, tutar/para birimi ve kalem sayısı private kimlik sızdırmadan geçmiştir.
Yeni hedef başladığında source değiştiği için organik paid V4 Flash kampanyası eski turları devralmaz;
fresh process, fresh artifact ve turn 1 ile yeniden başlar.

2026-08-31 Karar 194, fresh R408 exact V4 Flash kampanyasındaki ilk genuine failure'ı ve aynı
tur içi hesap bağımlılığı sözleşmesini bağlayıcı yapar. Turn 1-4 doğal sohbet, capability, production
yerel özet ve üç ayrı prior-observation yüzdesiyle geçmiştir. Turn 5'te model `110 + 52 = 162` ara
sonucunu doğru üretmiş, fakat sonraki `2958 / ara sonuç` formülünün paydasını aynı turdaki 162 yerine
önceki turun son doğrulanmış `%1,67` sonucu olarak bağlamış ve anlamsız `%177125,75` göstermiştir.
R408 bu ilk sapmada `failed` kapatılmıştır. Bu hata bir sayı/cümle özel durumu değil, typed formula
graph içinde “önceki tur sonucu” ile “bu batch'teki önceki node sonucu”nun aynı ref'e yüklenmesidir.

Derived calculation batch artık ileri referans ve döngüyü reddeden sıralı bir DAG'dır. Sonraki
formula yalnız kendinden önceki doğrulanmış node'u `derived.current + 0-tabanlı index` ile
kullanabilir; `derived.latest` ve `derived.recent+offset` yalnız önceki turlarda persisted
`core.verified_calculation` observation'larını ifade eder. Current-batch bağımlılığı bulunan kontrat
typed `calculation_grouping=sequential_results` olur; `independent_results` diye saklanamaz. Her node
Core verified calculation primitive'iyle sırayla çözülür, önceki node'un verified payload/evidence
zincirini taşır ve bütün batch doğrulanamazsa görünür sonuç üretmez. Açık “A'yı B'ye böl, oranı ver”
ifadesi yüzde/% demiyorsa `divide + scalar`dır; `oran` sözcüğü tek başına örtük `×100` yetkisi vermez.

Fresh R410 tekrarında model broad summary için istenen tek `revenue_total / total_count ->
amount_per_order` ilişkisi yerine alakasız/tekrarlı status toplama formülleri üretmiş; tool verisi
doğru olsa da görünür ortalama doğrulanamadığı için koşu turn 3'te `failed` durmuştur. Final persisted
semantic contract artık normalization/merge sonrasında kullanıcı tarafından açıkça adlandırılan
aritmetik ilişkilere karşı yeniden doğrulanır. “Sipariş başına ortalama ciro” kontratı exact
`orders.revenue_total / orders.total_count`, `divide`, `amount_per_order` ilişkisini taşımıyorsa plan
başlamaz; bounded aynı-model repair doğru formülü üretmezse fail-closed kalır. Böylece erken formula
audit'i ile persisted execution authority arasında ilişki kaybolamaz.

Fresh R411 unchanged-source focused source-app zinciri beş turda geçmiştir. Production local summary
3120 toplam sipariş, tam status dağılımı, 503.546,47 TRY ve `503.546,47 / 3.120 = 161,39
TRY/sipariş` formülünü doğru vermiş; sonraki üç yüzde sıfır yeni operation ile hesaplanmış; final tur
`110 + 52 = 162` ve `2958 / derived.current(0) = 18,26` sonuçlarını typed
`sequential_results` kontratıyla üretmiştir. Requested/actual/final model exact
`deepseek/deepseek-v4-flash`, fallback kapalıdır; artifact `accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r411-deepseek-v4-flash-derived-chain-2026-08-31.json`.
Focused kabul 50+ organik kapanış değildir; source değiştiği için sıradaki paid kampanya fresh process,
fresh artifact ve turn 1'den yeniden başlar.

2026-08-31 Karar 195, güçlü-model-first koşum sırasını ve R413 row-projection failure'ını bağlayıcı
kılar. Aktif geliştirme/kabul sırası değişmemiştir: önce fallback kapalı exact ücretli
`deepseek/deepseek-v4-flash` ile 50+ organik ürün-yolu kampanyası; sonra Gemini'nin erişilebilen en
güçlü ücretsiz modeli ve OpenRouter'ın erişilebilen en güçlü ücretsiz modeliyle ayrı fresh kampanyalar.
Bu üç güçlü baseline kapanmadan düşük-tier cloud, küçük model veya local kampanya başlatılmaz. Ücretli
başarı ücretsiz kabulün yerine geçmez; ücretsiz adaylar da katalog varsayımıyla değil canlı erişim,
exact requested/actual/final model ve no-sibling-fallback kanıtıyla seçilir.

Fresh R413 exact V4 Flash koşusu ilk beş turda sohbet/policy, authoritative broad summary, persisted
observation yüzdeleri ve same-turn derived DAG hesabını doğru tamamlamıştır. Turn 6'daki “en son 5
siparişi sıra, tarih, durum, tutar ve ürün kalemi adediyle; PII/kimliksiz listele” hedefinde
`orders.query` doğru beş satırı üretmesine rağmen görünür cevap yalnız “all döneminde 3120 sipariş
eşleşti” olmuştur. Koşu ilk genuine failure'da durdurulup `failed` kapatılmıştır. Kök neden iki
katmanlıdır: `ürün kalemi adedi` typed projection'da hem satır cardinality `item_count` hem ürün
içeriği/per-line `item+quantity` diye genişliyor; ayrıca canonical `Orders.query_orders` satırları,
`Orders.list_recent_orders` aksine, authoritative `item_count` taşımıyordu. Modelin liste adımları ve
beş doğru kayıt observation'da mevcut olduğundan bu model/tool-choice hatası değil semantic
projection + domain evidence parity kusurudur.

Line-item cardinality ile ürün içeriği/miktarı artık birbirini dışlayan typed boyutlardır. `ürün
kalemi adedi`, `kalem sayısı`, `item count` gibi bileşik ifadeler bütünüyle cardinality olarak
ayrıştırılır; bileşiğin başındaki `ürün` sözcüğü yanlışlıkla full-context izni bırakamaz. Line-count
okuması `item` veya `quantity`, full order context ya da PII yetkisi vermez. Orders domaininde sayfa
satırlarının kalem cardinality'sini üreten tek ortak helper hem `list_recent_orders` hem
`query_orders` tarafından kullanılır; AI katmanı item join/business hesabını kopyalamaz. Query sonucu
her satır için authoritative `item_count` taşır ve ordinal/privacy-safe projeksiyon bu değeri “kalem
sayısı” etiketiyle doğrular. R407 + exact R413 regresyonları ve tam Orders agent runtime sonucu
`436 passed / 446 skipped / 0 failed` olmuştur. Source değiştiğinden güçlü paid 50+ kampanya bir
sonraki koşuda yine fresh process, fresh artifact ve turn 1'den başlar.

Fresh R414 exact V4 Flash source-app focused kabulü altı turda `accepted=true / problems=[] /
passed` olmuştur. R413 exact cümlesi bu kez en yeni beş Order satırını doğru sıra, tarih, durum,
tutar ve satır başına authoritative kalem sayısıyla göstermiş; order number/customer/address/
phone/cargo/tracking projection'ı yapmamıştır. Sonraki ordinal “listedeki ikinci sipariş” turu aynı
typed selection'dan exact tek kayda inmiş, yalnız iki ürün içeriğini ve miktarlarını göstermiş, bütün
yasak özel alanları kapalı tutmuştur. Requested/actual/final model
`deepseek/deepseek-v4-flash`, sibling fallback yoktur. Artifact:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r414-deepseek-v4-flash-row-list-focused-2026-08-31.json`.
Bu focused kanıt yalnız R413 sınıfını kapatır; 50+ organik paid kabulün yerine geçmez.

2026-08-31 Karar 196, fresh R415 exact V4 Flash organik kampanyasının turn 5 genuine failure'ını
bağlayıcı yapar. Kullanıcı “aynı veriden” iki sıralı hesap istemiş ve açıkça “yüzdeye çevirme”
demiştir. Sistem nihai `110+52=162`, `2958/162=18,26` matematiğini doğru üretmesine rağmen gereksiz
`orders.status_counts` operation'ı açmış ve cevabın başına “Sipariş durum oranı authoritative sonuç
içinde bulunamadı” satırı eklemiştir. Modelin typed formula DAG'ı doğru olduğundan failure'ın sahibi
model zekâsı veya atomic operation eksikliği değil; negatif projection ile contextual observation
reuse permission sözleşmesidir. R415 ilk sapmada `failed` kapatılmıştır.

“Aynı/bu/önceki veri-sayı-sonuç üzerinden hesapla/topla/böl/çıkar/karşılaştır” yapısı, önceki typed
observation mevcutsa `existing_observations_only` permission boundary'sidir; yeni read operation
açılmaz. Bu kural artifact üretimi, mutation veya refresh gibi effectful hedeflere genellenmez.
“Yüzdeye çevirme/hesaplama/gösterme”, “yüzde istemiyorum/değil” ve eşdeğer English negation pozitif
`ratio` yetkisi değildir. Formula operand isimleri de bağımsız direct projection yetkisi vermez;
direct base fields yalnız kullanıcı onları ayrıca görünür istediğinde kalır. Pozitif named-status
yüzde isteğinde geçmiş sözleşme korunur: status ve count taban değerleri formula yanında görünür,
ratio ise derived result olarak kalır. Exact R408/R410/R415 ve pozitif R324 uyumluluk regresyonları
geçmiş; tam Orders agent runtime `437 passed / 447 skipped / 0 failed` olmuştur. Yeni paid kampanya
source değişikliği nedeniyle fresh process/artifact/turn 1 ile yeniden başlar.

2026-08-31 Karar 197, R416-R419 güçlü-model failure zincirini bağlayıcı yapar. R416'da kullanıcı
yalnız Delivered ve Cancelled yüzdelerini istemesine rağmen verifier bütün status observation'ını
zorunlu saymış ve model görünür cevaba istenmeyen üçüncü statusu eklemiştir. Typed
`status_members` artık hem beklenen hem izin verilen exact projection kümesidir; named-status
hesabında bu küme dışındaki authoritative status görünür cevaba sızamaz. R417'de “sipariş numarası
ile tüm müşteri/kargo özel alanlarını gizle” ifadesindeki alan adları model tarafından pozitif
projection izni sayılmıştır. Negatif alan sözleşmesi artık grouped müşteri ve kargo özel alanlarını
canonical field setlerine açar; carrier adı da açık `cargo` yetkisi yoksa verifier tarafından
reddedilir.

R418'de “Selam başkan, siparişlerde privacy-safe kısa bir kontrol yapacağız” gelecek/meta
koordinasyon cümlesi, somut güncel yürütme yüklemi olmadığı halde `inspect/data_read` sayılmış ve
`orders.query` çalıştırılmıştır. Domain adı tek başına business operation yetkisi değildir. Gelecek
veya planlama clause'u; ayrı bir clause içinde somut güncel emir, metric sorusu ya da açıklama
talebi yoksa `chat/general/conversation`, boş projection ve sıfır business operation olarak
sınırlandırılır. Bu sınır “siparişleri kontrol et” ve “bugün inceleyeceğiz; önce bekleyenleri getir”
gibi gerçek emirleri engellemez; ayrıca “hangi veriyi kullanacağını anlat” gibi policy/explain
hedefini chat'e düşürmez. Kural prompt cümlesine özel tool router değildir: model yorumundan sonra
business execution authority açılmasını denetleyen genel grammatical permission boundary'sidir.

R416-R418 focused regresyonları ve tam Orders agent runtime `440 passed / 449 skipped / 0 failed`
geçmiştir. Fresh R419 offscreen gerçek source-app koşusunda exact, fallback-kapalı
`deepseek/deepseek-v4-flash` ilk cümleye doğal sohbet cevabı vermiş ve `tool=null` kalmış; aynı fresh
oturumdaki ayrı “kargoya hazır bekleyen siparişlerin sayısını getir” emri ise yalnız canonical
`orders.ready_to_ship_count` çalıştırıp authoritative `0` sonucunu göstermiştir. Requested/actual/
final model exact, sibling fallback yoktur; artifact `accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r419-deepseek-v4-flash-future-command-boundary-focused-2026-08-31.json`.
Bu focused kanıt paid 50+ kapanışı değildir; kaynak değiştiği için sıradaki V4 Flash organik
kampanya yine fresh process, fresh artifact ve turn 1'den başlar.

2026-08-31 Karar 198, fresh R420 exact V4 Flash organik kampanyasının turn 3 görünür kalite
failure'ını bağlayıcı yapar. Önceki authoritative `3120` toplam ve `Cancelled=110`,
`Delivered=2958`, `UnDeliveredAndReturned=52` dağılımından üç ayrı yüzde sıfır yeni operation ile
matematiksel olarak doğru hesaplanmış; fakat deterministic existing-observation projector üç satırı
da yalnız “Hesaplanan oran” diye göstermiştir. Formül sırasına veya önceki cevabın satır sırasına
bakarak hangi sonucun hangi statusa ait olduğunu tahmin etmek kabul değildir. Per-target derived
sonuç, yalnız numeric result değil semantic target identity de taşır.

Canonical verified calculation artık tek `orders.status_count+member` hedefli percentage için
authoritative `result_member` üretir ve görünür `result_label`i bu üyeye bağlar. Response verifier,
her per-target status member adı ile kendi yüzde sonucunun aynı görünür segmentte bulunmasını ister;
status adlarını ayrı bir başlıkta bırakıp etiketsiz sayı/formül satırları göstermek geçmez. Decimal
noktaları segmenti bölmez. Bu kural hesap sonucunu modele ezberletmez; formula operandındaki typed
business identity'nin projection boyunca kaybolmamasını sağlayan genel evidence-label invariant'ıdır.
R324/R416/R418/R421 focused regresyonları ve tam Orders agent runtime
`441 passed / 449 skipped / 0 failed` geçmiştir.

Fresh R422 offscreen gerçek source-app koşusunda exact, fallback-kapalı
`deepseek/deepseek-v4-flash` önce `orders.status_counts` ile authoritative dağılımı kurmuş; sonraki
tur aynı observation'ı `tool=null` ile kullanarak `Cancelled ... 3.53%`, `Delivered ... 94.81%` ve
`UnDeliveredAndReturned ... 1.67%` sonuçlarının her birini kendi `110/3120`, `2958/3120`,
`52/3120` işlemiyle aynı satırda göstermiştir. Artifact `accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r422-deepseek-v4-flash-status-result-label-focused-2026-08-31.json`.
R420 failed artifact korunur; R422 yalnız failure sınıfını kapatır. Paid 50+ kampanya source
değişikliği nedeniyle yine fresh process, fresh artifact ve turn 1'den başlar.

2026-08-31 Karar 199, fresh R423 exact V4 Flash organik kampanyasının ikinci turunda yakalanan
typed calculation canonicalization failure'ını bağlayıcı yapar. Geniş sipariş özeti için model
authoritative toplam, tam durum dağılımı, toplam ciro ve doğru sipariş başına ortalama formülünü
kurmuş; fakat aynı `divide(orders.revenue_total, orders.total_count)` hesabını
`independent_results` içinde iki özdeş kayıt olarak bildirmiştir. Bu nedenle görünür sonuçta aynı
ortalama iki kez yer almıştır. Exact duplicate bağımsız hesaplar artık semantic contract
normalizasyonunda stable typed signature ile tekilleştirilir; tek sonuç kaldığında sözleşme
`single_result + derived_calculation` biçimine canonicalize edilir. Sequential veya per-target
hesaplar bu kurala dahil değildir; deterministic katman yeni business formülü yazmaz, yalnız
modelin schema-equivalent özdeş tekrarını kaldırır.

R424 regresyonu duplicate provider output'un tek typed ve tek görünür sonuç olmasını kanıtlamış;
tam Orders agent runtime `442 passed / 449 skipped / 52 subtests passed / 0 failed` geçmiştir.
Fresh R425 offscreen gerçek source-app oturumunda fallback kapalı exact
`deepseek/deepseek-v4-flash`, önce gelecek zamanlı niyet cümlesini `tool=null` doğal sohbet olarak
korumuş; ardından tek `orders.summary` observation'ından `3120` sipariş, `110/2958/52` tam durum
dağılımı, `503546.47 TRY` toplam ciro ve yalnız bir kez `503546.47 / 3120 = 161.39 TRY/sipariş`
sonucunu göstermiştir. Requested/actual/final model aynıdır; artifact
`accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r425-deepseek-v4-flash-single-average-focused-2026-08-31.json`.
R423 failed artifact korunur; R425 yalnız bu failure sınıfını kapatır. Paid 50+ organik kampanya
yeni source fingerprint nedeniyle yine fresh process, fresh artifact ve turn 1'den başlar. Bağlayıcı
model sırası değişmez: önce exact paid V4 Flash; sonra Gemini'nin ve OpenRouter'ın birbirinden ayrı
en güçlü erişilebilir ücretsiz adayları. Bu üç güçlü baseline tamamlanmadan düşük-tier cloud, küçük
ve local model kampanyası başlatılmaz.

2026-08-31 Karar 200, fresh R426 exact V4 Flash organik kampanyasının turn 4 genuine görünür
failure'ını bağlayıcı yapar. Model prior authoritative status dağılımından `minimum(110, 2958, 52)`
ve `2958 - 110` hesaplarını doğru kurmuş; deterministic projector sırasıyla `52` ve `2848`
sonuçlarını doğru göstermiştir. Ancak kullanıcı “en az görülen durum hangisi?” diye sorduğu halde
minimumun sahibi `UnDeliveredAndReturned` görünür sonuçta kaybolmuştur. Numeric doğruluk tek başına
semantic doğruluk değildir; extrema sonucu değerle birlikte kazanan typed operand identity'sini de
taşır. Eşit minimum/maksimum varsa bütün kazanan üyeler korunur ve her biri görünür sonuçla aynı
segmentte bağlanır.

R427 regresyonu bu `value + winner identity` invariant'ını minimum/maximum calculation verifier ve
projection sınırında kurmuş; tam Orders agent runtime
`443 passed / 449 skipped / 52 subtests passed / 0 failed` geçmiştir. Fresh R428 offscreen gerçek
source-app oturumunda fallback kapalı exact `deepseek/deepseek-v4-flash`, authoritative
`Cancelled=110`, `Delivered=2958`, `UnDeliveredAndReturned=52` observation'ından sıfır yeni
operation ile “En az görülen durum UnDeliveredAndReturned ... = 52 adet” ve
`2958 - 110 = 2848 adet` sonuçlarını eksiksiz göstermiştir. Artifact
`accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r428-deepseek-v4-flash-extrema-member-focused-2026-08-31.json`.
R426 failed artifact korunur; R428 yalnız bu failure sınıfını kapatır. Paid 50+ kampanya kaynak
değiştiği için yine fresh process, fresh artifact ve turn 1'den başlar.

2026-08-31 Karar 201, fresh R429 exact V4 Flash organik kampanyasının turn 3 typed-plan
failure'ını bağlayıcı yapar. Kullanıcı prior `3120 / 110 / 2958 / 52` observation'ından üç status
yüzdesini ayrı ayrı hesaplama, görünen yüzdeleri toplama ve toplamın 100'den farkını açıklama
hedefini açıkça vermiştir. Model üç percentage formula ile bunları kullanan sequential add
formülünü doğru kurmuş; yalnız nihai toplamın `literal 100` ile ilişkisinde canonical `comparison`
alanını eksik bırakmıştır. Eski runtime tek eksik relation yüzünden dört geçerli formülü de silip
aynı modele bütün aritmetiği baştan yazdırmış; bu geniş repair status operandlarını bozup gereksiz
clarification'a yol açmıştır.

Yeni invariant: birden fazla normalize edilmiş model-authored formula geçerliyken yalnız explicit
comparison bağı eksikse aritmetik formüller immutable korunur; aynı modelden bounded typed pass ile
yalnız `formula_index + comparison` istenir. Targeted pass business formülü, operandı veya tool'u
yeniden yazamaz. Tek-formül ve comparison-pseudo legacy dialect'leri mevcut bounded full-formula
repair yolunu korur. R430 regresyonu bu ayrımı ve dört formülün korunmasını kanıtlamış; tam Orders
agent runtime `444 passed / 449 skipped / 52 subtests passed / 0 failed` geçmiştir.

Fresh R431 offscreen gerçek source-app oturumunda fallback kapalı exact
`deepseek/deepseek-v4-flash`, üç status için `3.53% / 94.81% / 1.67%`, görünür bileşen toplamı
`100.01%`, `100%` hedefinden `0.01 yüzde puan` fark ve bunun iki ondalıklı bileşen
yuvarlamasından kaynaklandığı doğrulanmış açıklamayı sıfır yeni business operation ile göstermiştir.
İlk turdaki structured-output transport hatası aynı exact model guarded-JSON recovery ile
toparlanmış; sibling/model fallback olmamıştır. Artifact `accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r431-deepseek-v4-flash-comparison-repair-focused-2026-08-31.json`.
R429 failed artifact korunur; R431 yalnız bu failure sınıfını kapatır. Paid 50+ organik kampanya
yeni source fingerprint nedeniyle yine fresh process, fresh artifact ve turn 1'den başlar.

2026-08-31 Karar 202, R432-R436 ordinal detail zincirini bağlayıcı yapar. Fresh R432 paid
kampanyasında son beş siparişten ikinci kayıt doğru seçilmiş; item, quantity, SKU, cargo ve tracking
kanıtı `orders.full_context` ile doğru materialize edilmiştir. İlk görünür cevap doğruya yakın olsa
da verifier, açıkça istenen alfanümerik `PNSJDU27366243` SKU içindeki uzun sayısal parçayı bağımsız
uydurulmuş kimlik sayarak deterministic projection'ı reddetmiştir. R433 invariant'ı, yalnız
kullanıcının istediği ve authoritative item satırında exact bulunan tam etiketli SKU/barkod içindeki
uzun sayısal parçayı grounded kabul eder; farklı SKU/barkod hâlâ reddedilir. Tam runtime bu aşamada
`445 passed / 449 skipped / 52 subtests passed / 0 failed` geçmiştir.

Fresh R434 aynı yolu yeniden çalıştırdığında SKU grounding geçmiş; fakat projection contract
reconciler, kullanıcı takip numarasını açıkça istemiş ve atomic plan aynı alanı expected evidence
olarak taşımış olmasına rağmen alanı tekrar modele oylatıp `internal_only` kararıyla görünür
sözleşmeden silmiştir. Bu nedenle model cevabı tracking olmadan bitmiş ve verifier eksik cevabı
yanlışlıkla kabul etmiştir. Yeni projection authority invariant'ı: kullanıcı metninde açıkça
istenmiş, explicit olarak yasaklanmamış ve typed requested_fields içinde mevcut privacy-gated alan
`locked_visible` olur; plan uzlaştırması bu yetkiyi tekrar silemez. Kullanıcı açıkça istememişse veya
alan interpretation/plan arasında gerçekten uyuşmuyorsa bounded model reconciliation devam eder;
örneğin yalnız ürün isteyen kullanıcının customer evidence'ı internal kalır. R435 ve eski privacy
reconciliation regresyonları birlikte geçmiş; tam Orders agent runtime
`446 passed / 449 skipped / 52 subtests passed / 0 failed` olmuştur.

Fresh R436 offscreen gerçek source-app oturumunda fallback kapalı exact
`deepseek/deepseek-v4-flash`, son beş siparişin ordinal ikinci kaydını seçip iki ürün kalemini,
`1/2` adetlerini, exact SKU'ları, `Trendyol Express Marketplace` kargo firmasını ve authoritative
tracking değerini aynı görünür cevapta göstermiş; customer/phone/address PII taşımamıştır. Runtime
`verified_model_candidate`, artifact `accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r436-deepseek-v4-flash-tracking-detail-focused-2026-08-31.json`.
R432 ve R434 failed artifact'ları korunur; R436 yalnız bu iki failure sınıfını kapatır. Paid 50+
organik kampanya yeni source fingerprint nedeniyle yine fresh process, fresh artifact ve turn 1'den
başlar; güçlü-model-first sırası değişmez.

2026-08-31 Karar 203, R437-R443 aynı rapor/dönem düzeltmesi zincirini namespaced typed
projection invariant'ıyla kapatır. Fresh R437 exact paid V4 kampanyasında ilk turdaki son 21 günlük
ürün-satış raporu authoritative boş dönmüş; ikinci turdaki "aynı raporu tüm yerel dönem için"
hedefini model doğru anlamış ve doğru `orders.item_sales_summary` atomic operation'ını seçmiştir.
Ancak compiler, `item_sales_rows + item` projection'ındaki bare `item` alanını tekil sipariş detayı
sanıp doğru planı `typed_read_contract_operation_mismatch` ile reddetmiştir. R438 ile ortak
`expected_order_read_operations` sınırı, ürün-satış projection namespace'ini Orders metric
registry'sine bağlar; satır içindeki ürün etiketi artık `orders.full_context` yetkisi veya kanıtı
sayılmaz.

Fresh R439 doğru planı kabul etmiş fakat aynı yanlış `active_selection` scope'u, `bu kez`
ifadesindeki genel demonstrative'i sipariş seçimi sanarak optional `order_numbers` için olmayan bir
dependency istemiş ve execution'ı durdurmuştur. R440 invariant'ı, `item_sales_rows` ile tanımlı ürün
satış listesini provider `metric=list / record_scope=active_selection` üretse dahi population
aggregate olarak canonicalize eder; gerçek exact record intent yoksa scope `all_matching` olur ve
stale/unbound order selection raporu daraltamaz. Bu düzeltme prompt cümlesine veya tool adına özel
business plan yazmaz; typed aggregate field namespace'ini normalize eder.

Fresh R441 bir katman daha ilerleyip `orders.item_sales_summary` ile tüm dönem ilk beş satırı doğru
çekmiş, fakat response verifier redundant bare `item` alanı yüzünden hem model cevabını hem doğru
deterministic projection'ı `full_order_context_evidence_missing` ile reddetmiş ve kullanıcıya yalnız
ham tool mesajını göstermiştir. R442 response invariant'ı, `item_sales_rows` içindeki product label'ı
zorunlu tutarken redundant order-line `item` alias'ını typed visible contract'tan kaldırır. Böylece
ürün adı + satış adedi + farklı sipariş sayısı + brüt tutar aynı aggregate satır sözleşmesinde
doğrulanır; sipariş line-item/PII alanlarına yetki açılmaz. Tam
`tests.domain_ai.test_orders_agentic_task_runtime` modülü bu kaynakla
`448 tests / 447 passed / 1 skipped / 0 failed` geçmiştir.

Fresh R443 offscreen gerçek source-app oturumunda fallback kapalı exact
`deepseek/deepseek-v4-flash`, son 21 günlük authoritative boş rapordan anaforik olarak tüm yerel
döneme geçmiş, `orders.item_sales_summary` çalıştırmış ve ilk beş ürünün tamamını ürün adı,
`293/252/243/228/195` adet, `216/222/88/81/169` farklı sipariş ve authoritative brüt TRY
tutarlarıyla görünür cevapta sıralamıştır. Her satır Codex tarafından tool sonucuyla tek tek
karşılaştırılmış; runtime/final model exact V4, model fallback false, artifact
`accepted=true / problems=[] / passed` olmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r443-deepseek-v4-flash-same-report-period-focused-2026-08-31.json`.
R437, R439 ve R441 failed artifact'ları korunur; R443 yalnız bu failure zincirini kapatır. Paid 50+
organik kampanya yeni source fingerprint nedeniyle fresh process, fresh artifact ve turn 1'den
yeniden başlar.

2026-08-31 Karar 204, R444-R446 broad-analysis kalite kapısını domain-owned göstergelerle bağlar.
Fresh R444 exact paid V4 organik kampanyasının ilk doğal sorusunda `orders.summary` ve
`orders.item_sales_report` doğru compose edilmiş; toplam `3120`, durum dağılımı, `503546.47 TRY`
ciro ve ilk beş ürünün üç metriği doğru görünmüştür. Fakat kullanıcı açıkça "birlikte yorumla"
dediği hâlde V4'ün grounded analitik yorumu katı projection biçimi nedeniyle reddedilmiş ve
deterministic cevap yalnız ham veri dökümü bırakmıştır. Doğru rakamlar, eksik analitik hedefi
tamamlanmış saydırmaz; R444 ilk turda failed olarak kapatılmıştır.

R445 invariant'ı analitik göstergeleri AI içinde yeniden hesaplamaz. Canonical
`Orders.processors.agentic_repository.build_order_item_sales_report_snapshot`, zaten aynı
`summarize_order_item_sales` sonucunda domain tarafından hesaplanan `leading_five_quantity` ve
`leading_five_quantity_share` değerlerini immutable ReportSnapshot metadata'sına ve operation
sonucuna taşır. Ortak response projection hem `orders.item_sales_summary` hem explicit
`orders.item_sales_report_snapshot` metric contract'ını broad analysis kanıtı kabul eder; explicit
rapor istendiğinde ilk beş ürün satırı analitik yoğunluk yorumuyla ikame edilmez, ikisi birlikte
gösterilir. Bu kaynakla tam AI runtime `449 tests / 448 passed / 1 skipped / 0 failed`, tam Orders
pipeline `85 passed / 0 failed` geçmiştir.

Fresh R446 offscreen gerçek source-app oturumunda fallback kapalı exact
`deepseek/deepseek-v4-flash`, aynı geniş kullanıcı hedefinde toplam/durum/ciro ve beş ürün satırının
yanına authoritative analitik yorumu eklemiştir: Delivered `2958 / %94.81`, iptal `%3.53`, iptal
dışı sipariş başına ortalama `167.29 TRY`, ilk beş ürün `1211 / 5835 / %20.75`. Codex bütün base
değerleri ve göstergeleri tool sonuçlarıyla karşılaştırmış; model fallback false, artifact
`accepted=true / problems=[] / passed`:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r446-deepseek-v4-flash-broad-analysis-focused-2026-08-31.json`.
R444 failed artifact korunur; R446 yalnız bu kalite failure'ını kapatır. Paid 50+ organik kampanya
fresh process, fresh artifact ve turn 1'den tekrar başlar.

2026-09-04 Karar 205, R447 organik exact paid V4 Flash kampanyasının ikinci turunda
status-complement derived-calculation sözleşmesinin gerçek failure'ını kaydeder. İlk turdaki
authoritative `orders.summary + orders.item_sales_report` cevabı geçmiş; ikinci turda kullanıcı yeni
business tool çalıştırmadan `Cancelled + UnDeliveredAndReturned`, bu ara toplam ile `Delivered`
arasındaki adet farkı ve ara toplamın bütün siparişlere yüzdesini istemiştir. Model business hedefini
ve üç sıralı hesabın temel operandlarını seçmiş; fakat fark formülüne kullanıcı tarafından istenmeyen
bir sıfır karşılaştırması eklemiş, bounded repair ise seçili member kümesini guarded JSON lehçesinde
`orders.status_count + members[]` olarak vermiştir. Eski normalizer bu lehçeyi birleşik status
operandına çevirdikten sonra Core'un en az iki scalar operand invariant'ına bağlayamadığı için tur
`derived_calculation_repair_failed` olmuş ve kullanıcıya gereksiz clarification gösterilmiştir.
R447 failed artifact korunur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r447-deepseek-v4-flash-organic-50-2026-08-31.json`.

R448 invariant'ı iki genel typed sınır getirir. Birincisi, `comparison` ayrı bir görünür iddiadır ve
yalnız kullanıcı açık bir eşitlik/tutarlılık/karşılaştırma ilişkisi istediğinde korunur; salt adet
farkı `subtract` aritmetiğidir, provider'ın eklediği `!= 0` kontrolü business hedefini bozamadan
atılır. İkincisi, provider'ın exact seçtiği `status_count + members[]` lehçesi canonical member-set
sum olarak tanınır ve Core verified arithmetic'e aynı exact üyelerden oluşan scalar operandlar
halinde kayıpsız açılır; hiçbir status, operator veya hedef deterministic katman tarafından icat
edilmez. R448 deterministic source contract ve mevcut-observation yürütmesi `162` birleşik adet,
`2796` adet farkı ve `%5.19` oranı sıfır yeni business tool çağrısıyla doğrulamış; tam Orders agent
runtime paketi `451 passed / 449 skipped / 0 failed` geçmiştir.

Fresh R449 offscreen source-app focused kabulü current fingerprint ile başlatılmış, ancak 0.3.5
manuel ürün kabulü için temizlenmiş aktif uygulama DB'sinde `ai_provider_account` kaydı bulunmadığı
için provider/model çözümlemesinden önce effectsiz kapanmıştır. Model invocation ve ücret oluşmamış;
bu sonuç R448'in canlı kabulü değildir. Ham credential bu belgeye veya artifact'a yazılmaz. Kayıtlı
OpenRouter hesabı geri geldiğinde bağlayıcı sıra: fresh R449 iki turluk exact V4 focused konuşması,
ardından yeni fingerprint/process/artifact ile turn 1'den başlayan 50+ exact V4 organik kampanya;
sonra Gemini ve OpenRouter ücretsiz güçlü-model provider matrisi.

2026-09-05 Karar 206, yeni hedefin Faz 0 denetimi ve R449/R451 canlı failure'larıyla
typed talep izni, hesap zinciri ve görünür sayı doğrulaması arasındaki sınırı bağlayıcı kılar.
Secret-safe yeniden başlatma kanıtı `AI/docs/orders_phase0_restart_audit_2026_09_05.json` içindedir.
Aktif temiz DB'de başlangıçta provider satırı yoktur; diskteki yönetilen OpenRouter credential
canonical save üzerinden yeniden bağlanmış, exact ücretli V4 erişimi doğrulanmıştır. Bu işlem
pazaryeri kaydı değiştirme veya production yetkisi değildir. Güncel veri yalnız Stage seller
2738'e aittir: 570 gerçek sipariş; eski production 3120 toplamı yeni oracle olarak kullanılamaz.

R449 ikinci turda kullanıcı karşılaştırmayı yasakladığı halde lexical matcher karşılaştırma
zorunluluğu üretmiş; yeterli önceki veriyle hesaplanabilen hedef literal 0 onarımında durmuştur.
R450'de yeni model sözleşmesi `comparison_policy=not_requested|required|prohibited` taşır.
Bu karar ilk normalizasyon, formula repair ve görünür comparison doğrulamasında korunur;
kod yeni operator, durum veya hedef uydurmaz. Eski alanı taşımayan decoder çağrıları
`legacy_inference` olarak ayrılır; yeni cloud kanıtında `comparison_policy_source=model_authored`
görülmeden bu mimari geçiş kanıtlanmış sayılmaz. Eski intent inference'ın genel kaldırılması açıktır.
`existing_observations_only` turuna sync niyeti ve fetch operation metadata'sı eklenemez.
Negatif sonucun işareti numeric grounding boyunca korunur: `-74`, `74` veya `+74` ile aynı
kanıt değildir. Unicode eksi, yerel ondalık/binlik ayırıcı ve subtraction/date ayrımı testlidir.

R451 ikinci turda yalnız `86 + 13 = 99` cevabı üretmiş, `-74` ve `%17.37` sonuçlarını atladığı
halde success dönmüştür. Bu bir ürün failure'ıdır; comparison düzeltmesinin varlığı eksik sonucu
geçerli kılamaz. R452 invariant'ı modelin `sequential_results` sözleşmesini en az iki ve ilan
ettiği sayı kadar formülle tamamlamasını ister. Eksik zincir aynı modele bounded repair için
geri verilir; repair de eksikse tur effectsiz fail-closed kalır. Formül sayısını eksik çıktıya
uydurup başarı üretmek yasaktır. Türkçe/İngilizce yasaklar, olumlu comparison, signed negatif
sonuç, eksik ilk cevap ve eksik repair aynı mevcut-observation ürün yolunda sınanır.

R449 ve R451 redacted failed artifact'ları `AI/docs/live_llm_transcripts/source-ui/` altında
korunur. R449 controller girdisinde `reason` yerine `selection_reason` kullanıldığı için kayıtlı
selection gerekçeleri boştur; bu koşu yalnız failure teşhisidir. Sonraki koşular doğru `reason`
alanını kullanır. R453 bir doğru scope/status turundan sonra `interrupted` kapanmıştır;
geniş testte modelin ilk yanlış üç-hesap sözleşmesini tek gerçek ortalamaya düzeltmesi de
gerekli olduğundan runtime yeniden ele alınmıştır. R454 `result_contract_revision` ile
modelin yeni sayı, gruplama ve gerekçesini açıkça vermesini ister; yeni sayı doğrulanmış
formüllerle eşleşir ve önceki/yeni sözleşme provenance içinde saklanır. Gerekçesiz eksik
repair reddedilir, doğru model revizyonu korunur. Bu bir keyword veya örnek-cümle istisnası
değildir. Current fingerprint'te fresh focused kabul bitmeden 50+ organik kampanya geçmiş
sayılmaz; focused kabulden sonra tam kampanya yeni artifact ve turn 1'den başlar.

R454 sonrası Orders task runtime, Chat source-app orchestration, operation catalog ve Core
verified calculations paketi `549 passed / 449 skipped / 74 subtests passed / 0 failed`
geçmiştir. Bu deterministic taban üzerinde fresh R455 exact V4 focused konuşması açılmıştır;
sonuç ve güncel fingerprint yeniden başlatma audit'inde tutulur. Test yeşili canlı kabul
yerine geçmez.

2026-09-05 Karar 207, R455 focused koşusunun üçüncü turundaki yeni failure'ı kaydeder.
İlk tur Stage 2738'in 570 toplamını ve dokuz durumunu doğru vermiş; ikinci tur exact
`Cancelled + UnDeliveredAndReturned = 99`, `Delivered - 99 = -74`, `99 / 570 * 100 = %17.37`
zincirini doğru, eksiksiz ve yeni business tool olmadan tamamlamıştır. Modelin comparison
yasağı `comparison_policy=prohibited` olarak korunmuştur. Bu yalnız dar regresyon kanıtıdır.

Üçüncü turdaki "bulduğun negatif adet farkı 0'dan küçük mü" isteğinde model önceki tur
sonucunu mevcut batch `derived.current` ile karıştırmış; bounded repair önceki-result ref'i
taşıyan relation-only `operator=less_than` üretmiştir. Arithmetic-only normalizer bu biçimi
reddetmiş; boş normalize sonuç üzerinden yapılan result-contract revision kontrolü
`result_contract_revision_invalid` ile asıl formül hatasını maskelemiştir. Görünür cevap
gereksiz bağlam clarification'ıdır; runtime `success=true` olsa da ürün kabulü failed'dır.
R455 üç turdan sonra durdurulmuş, artifact korunmuştur:
`AI/docs/live_llm_transcripts/source-ui/orders-phase8b-r455-deepseek-v4-flash-typed-calculation-contract-focused-2026-09-05.json`.

Bağlayıcı sonraki iş önceki typed sonuç kimliği/offset ile sayısal comparison'ın ortak
sözleşmesini tamamlamak, saf karşılaştırma için business aritmetiği icat etmemek ve birincil
normalizasyon reason code'unu sonraki metadata kontrolünde kaybetmemektir. Cümleye özel
regex veya sıfır ekleyerek formül uydurma kabul edilmez. Focused ve 50+ organik gate açık
kalır; bu yeni failure düzeltildikten sonra current fingerprint'te fresh focused ve ardından
fresh turn 1 organik kampanya gerekir.

2026-09-05 Karar 208, R455 failure'ının sahibi olan typed formula/observation/projection
sözleşmesini genişletir. R456 saf sayısal ilişkileri mevcut Core verified-comparison
primitive'ine bağlar; karşılaştırma için ekleme veya çıkarma işlemi icat edilmez. Altı
canonical ilişki boolean sonuç verir; önceki numeric result ref'i ve evidence hash'i
korunur. Boolean observation ayrı `core.verified_comparison` olarak saklanır ve önceki
sayısal hesapların latest/recent sırasını değiştirmez; boolean değer aritmetiğe giremez.

Her görünür karar kendi operand/operator ifadesine bağlanır. Kaynak hesabın gösterilen
işlem adımları yalnız o referansın doğrulanmış kanıtından grounded edilir; ilgisiz geçmiş
sayılara izin açılmaz. Ters doğru/yanlış, ters işaret ve karşılaştırma yasağı deterministic
kontrollerde reddedilir. Bounded repair'de geçersiz formülün birincil hata kodu, sonraki
result-contract revision metadata kontrolünden önce korunur. Bunlar ortak sözleşme
invariant'larıdır; focused gerçek cloud kabulü ve fresh 50+ organik kampanya hâlâ gereklidir.

2026-09-05 Karar 209, R457 üçüncü turunda tekrarlayan comparison failure'ını formül
şeması ve onarım sözleşmesine bağlar. Önceki negatif sonuç ve canonical `less_than`
ilişkisi model tarafından seçilmiş olsa da singleton array minimumu ve yanlış sequential
gruplama bounded repair'i tetiklemiştir. Repair talimatı saf boolean ilişkiye de nested
comparison istediği için model aynı ilişkiyi çelişen iki biçimde yazmıştır. Primary
diagnostic artık korunur; görünür gereksiz clarification yine failed kabul edilir.

R458 formülün taşıma biçimini sonuç sayısından ayırır: dizi bir formül içerebilir; bağımlı
ve bağımsız hesapların deklare sonuç sayısı, sequential zincirin en az iki sonucu ayrı
doğrulanır. İlişkinin sahibi ana
operator'dür: comparison operator doğrudan boolean verir ve nested comparison istemez;
aritmetik operator sonucu ayrıca karşılaştırılacaksa nested comparison kullanılır. İlk
yorum, tek-formül onarımı ve formül-dizisi onarımı aynı ilişki varlığı kontrolünden geçer.
Yanlış gruplamanın model-authored açık revizyonu mümkündür; çelişkili operand veya eksik
istenen ilişki kabul edilmez. Eski prompt'a cümle bazlı istisna eklemek yerine çelişen
schema/repair talimatları değiştirilmiştir. R457 failed artifact korunur; current-source
focused ve fresh 50+ organik kabul hâlâ açıktır.

2026-09-05 Karar 210, R459'da önceki-sonuç karşılaştırmasının dar kabulünü ve takip
hesabındaki yeni failure'ı ayırır. İlk üç cevap doğrudan okunmuştur: Stage 2738'in 570
siparişi, `99 / -74 / %17.37` zinciri ve `-74 < 0 → Doğru` ilişkisi doğrudur. Üçüncü
turda model `derived.recent+offset=1`, `less_than`, boolean ve single-result sözleşmesini
tek çağrıda seçmiş; onarım veya yeni business tool gerekmemiştir. Final hesap metinleri
deterministic verified projection'dır, model-authored son prose kabulü diye sayılmaz.

Dördüncü istek, karşılaştırmadan önce bulunan yüzde sonucunu ikiye bölüp üç ondalıkla
göstermektir. Model doğru önceki sayısal sonucu `derived.recent+offset=0` ile seçmiş;
boolean observation numeric geçmişi kaydırmamıştır. Ancak `operator=percentage` ile
`17.37 % / 2 × 100 = 868.500 %` üretmiştir. Beklenen `17.37 % / 2 = 8.685 %` olduğundan
Core formülü doğru yürütse de kullanıcı hedefi karşılanmamıştır. Kampanya dört turda
durdurulmuş ve failed artifact korunmuştur.

Sonraki sahip iş ortak quantity/unit/scale sözleşmesidir: yüzde olarak ifade edilen
operand, yeni oran→yüzde dönüştürme işlemiyle karışmamalı; hesap operator'ü, operandın
ölçeği ve sonucun gösterim birimi ayrı ve doğrulanabilir olmalıdır. Cümlede yüzde veya
böl kelimesi geçtiği için operation değiştiren regex/prompt istisnası eklenmez. Mevcut
Core primitive'leri üzerinden ölçü/ölçek bağlama ve model-authored formula doğrulaması
kurulur. R458'in `554 passed / 449 skipped / 91 subtests passed` tabanı ve dar üçüncü
tur başarısı bu yeni failure'ı kapatmaz; fresh focused ve ardından fresh 50+ organik kabul
açıktır.

2026-09-05 Karar 211, R459 kök nedeninin sonraki kod incelemesiyle daha kesin
sınırlandırıldığını kaydeder. Normalizer, `operator=divide` ve `result_kind=percentage`
birlikte olduğunda işlemi koşulsuz `percentage` yapmaktadır. R459 ham model operator'ünü
saklamadığı için önceki kayıttaki "model percentage seçti" atfı tek başına kanıtlanmış
değildir; kabul edilmiş formülde yüzde işlemi bulunduğu ve runtime'ın böyle bir dönüşüm
yapabildiği kesindir. Eski artifact/review değiştirilmez; bu düzeltme yeni kanıta dayanır.

R460 sonuç türüne bakarak işlem değiştirmeyi kaldırır. Ortak Core primitive, gösterilen
operandların pozitif ölçeklerini kullanarak baz değerlerde hesap yapar ve yalnız sonunda
sonucun gösterim ölçeğine dönüp yuvarlar. Yüzde gösteriminin ölçeği `0.01`'dir: adet/adet
oranını yüzdeye dönüştürmek ile zaten yüzde olan değeri bölmek aynı ×100 adımını
gerektirmez. `divide` ve `percentage` operator kimlikleri korunur; gerekli sayısal gösterim
çarpanlarını Core açık provenance olarak üretir. İlk yorum ve bounded repair aynı ayrımı
korur. Core arithmetic hash'ine ölçekler; typed proof'a contract, operand birimleri,
önceki kanıt hash'leri ve sonuç türü/birimi bağlanır. Yeni pre/post operator ve result-kind provenance, model
seçimini normalizasyondan ayrı gösterir ve iş değerlerini kopyalamaz. Genel birim dönüşüm
cebirinin tamamlandığı iddia edilmez. Mevcut yüzde sonucunu bölme, sıfırdan oran yüzdesi
hesaplama ve diğer bağımlı hesaplar geniş regresyon ve fresh source-app yolunda birlikte
doğrulanmadan focused veya organik gate kapanmaz.

2026-09-05 Karar 212, R461 fresh exact V4 source-app focused kabulünün dört doğrudan
okunmuş turla `accepted=true / problems=[]` kapandığını kaydeder. Stage 2738'in 570
siparişi ve dokuz durumu, üç sonuç zinciri `99 / -74 / %17.37`, önceki negatif sonuca
`-74 < 0 → Doğru` ilişkisi ve boolean turundan sonra `%17.37 / 2 = %8.685` takip hesabı
doğrudur. Dördüncü turda modelin ham `divide` seçimi kabul edilmiş `divide` olarak
korunmuş; result_kind percentage ve önceki offset0 değişmemiştir. Hesap turlarında
repair, yeni business tool veya action yoktur. Core dahil 29 dosyalık source fingerprint
süreç boyunca değişmemiştir.

Bu dar regresyon kapanışı genel ürün kapanışı değildir. Hesapların son görünür metinleri
deterministic verified projection'dır; model-authored son prose kabulü olarak sayılmaz.
558 test/112 subtest tabanı ve R461 konuşması, ayrı fresh süreç/artifact ile turn1'den
başlayacak 50+ organik exact V4 kampanyasının yerine geçmez. Ücretsiz provider, immutable
action/read-back, artifact/web, UI ve diğer domain gereksinimleri açık kalır.

### Faz 9 — UI entegrasyon kontrolü

- Yalnız yeni runtime state'lerinin onaylı v3 component grammar içinde doğru görünmesi
- Plan/observation/pending/superseded/verify-failed durumları
- Local -> Cloud -> Local gerçek click/async refresh döngüsünün art arda tekrarı
- Minimum/orta/authoritative/geniş viewport ile 96/125/150% ölçek matrisi
- Splitter kapalı/varsayılan/genişletilmiş durumlarında responsive geometri
- Her geçişte anlık ve settled gerçek source-app screenshot, component-tree ve geometry
- Loading/empty/error/dolu liste, provider accordion/filter ve advanced popup durumları
- Codex'in bütün kritik transition karelerini doğrudan görsel incelemesi
- Başarı kriteri: scaffold ve authoritative tasarım değişmeden runtime eksiksiz görünür;
  Local/Cloud geçişlerinde tek karelik dahi taşma, overlap, kesilme, boyut sıçraması veya
  splitter drift'i yoktur.

### Faz 10 — Diğer domainlere yayılım

Orders yeni agent runtime üzerinde kapandıktan sonra aynı mimari Stock, Listing,
Finance, Logistics, Marketplaces, Labels ve gelecekteki domainlere uygulanır. Her domain
kendi goals/parity/risk/evidence sözleşmesini taşır; ortak runtime yeniden yazılmaz.

## 20. Orders Tamamlanma Tanımı

Orders ancak aşağıdakilerin tamamı sağlandığında `completed` olabilir:

- Bölüm 19.0'daki stabilizasyon reseti ve Faz 8A -> 8B -> 8C kapı sırası atlanmadan
  uygulanmış.
- Bölüm 15'teki bütün gerçek kullanıcı regresyonları kapanmış.
- Business intent'leri modelden önce preempt eden regex tool router kalmamış.
- Basit ve çok adımlı işler ortak dynamic agent loop'ta çalışıyor.
- Typed state raw history scan'in yerini almış.
- Manuel Orders/Returns/Labels capability parity'si yalnız katalogda değil doğal
  composition testlerinde kanıtlanmış.
- Count/list/selection/prepare/execute/verify exact set invariant'ı geçiyor.
- Item aggregation ve selected return reason aggregation çalışıyor.
- UI'da hazır ekranı olmayan ad-hoc Orders raporu domain operation'ıyla üretilebiliyor;
  son üç hafta en çok satanlar listesi ile doğrulanmış XLSX aynı snapshot'ı taşıyor.
- Önceden birleşik tool'u bulunmayan latest-order -> web-research -> Excel hedefi atomic
  Orders/web/artifact operation'larıyla dinamik planlanıp tamamlanıyor.
- Cargo change doğru Orders operation'ıyla, exact target ve semantic verifier ile
  Stage'de uçtan uca kanıtlanmış.
- Hypothetical/explain/correct mesajları yanlış mutation üretmiyor.
- Cancellation/supersession/stale approval yaşam döngüsü güvenilir.
- Kapsam düzeltmesi persisted eski action'ı `superseded` yapıyor; eski action ID restart
  sonrasında dahi çalışmıyor ve yeni action authoritative exact setle yeniden hazırlanıyor.
- Response projection ve PII minimizasyonu gerçek sohbetlerde geçiyor.
- Gemini ve OpenRouter'dan erişilebilen güçlü cloud modeller yeni runtime'da kabul
  edilmiş; güçlü cloud kontrol koşusu model/runtime ayrımını kanıtlamış.
- Mevcut provider'ların her birinde en az bir erişilebilir güçlü ücretsiz cloud model temel
  full-agentic Orders baseline'ını ve Bölüm 15'teki frozen regresyonları geçmiş; Gemini
  başarısı OpenRouter'ın, OpenRouter başarısı Gemini'nin yerine geçmemiş. Local kabul
  mevcut Orders kapanış kapısı değildir.
- Cloud modellerle 50/60/100 ve gerektiğinde 200+ mesaj kampanyalarının her cevabı Codex
  tarafından doğrudan incelenmiş.
- Production R0/R1 ve Stage R0/R1/R2 doğru environment read-back ile kanıtlanmış.
- UI runtime durumlarını offscreen ve scaffold-faithful biçimde gösteriyor.
- Local <-> Cloud kaynak geçişi minimum/orta/authoritative/geniş viewport ve ölçek
  matrisinde anlık + settled screenshot kabulünü geçiyor.
- Secret/PII evidence'a sızmıyor.
- En yeni gerçek kullanıcı konuşması eski artifact'larla değil fresh process/source
  kanıtıyla geçiyor.

Tek başına test sayısı, tool seçimi, approval kartı, başarılı execute dönüşü, ücretli
model başarısı veya closure JSON'u Orders kapanışı değildir.

## 21. AI Domaininin Nihai Tamamlanma Tanımı

Nihai ürün:

- Bütün ana e-ticaret domainlerinde aynı gerçek agent loop'u kullanır.
- Kullanıcının manuel yapabildiği hedefleri aynı canonical domain operasyonlarıyla
  konuşarak yapabilir.
- Yeni domain, marketplace, provider ve model eklemeyi düşük maliyetli kılar.
- Tool'ları dinamik biçimde compose eder; sabit workflow veya regex cümlelerine bağımlı
  değildir.
- Önceden düşünülmemiş spesifik kullanıcı hedeflerini mevcut capability primitives,
  typed GoalPlan ve observation-driven replanning ile çözebilir; her hedef için özel
  mega-tool gerektirmez.
- UI'da hazır ekran bulunmasa da domain verisinden güvenilir ad-hoc rapor hedefi kurar;
  ReportSnapshot'ı doğrulanmış Excel/CSV/PDF artifact'ına dönüştürebilir.
- Güncel dış bilgi gerektiğinde provider-independent web tool'larıyla çok adımlı,
  privacy-safe ve kaynaklı araştırma yapar.
- Uzun görevleri ve konuşma state'ini restart/fallback/topic switch boyunca korur.
- Ücretsiz cloud ve local modeller için dürüst capability baseline'ı sunar; kullanıcıyı
  tek ücretli modele mahkûm etmez.
- Yanlış model planını deterministic policy ve semantic verification ile güvenli tutar.
- Production'da doğru, dış etkide kullanıcı kontrollü ve sonucunu bağımsız doğrulayan
  bir sistemdir.
- OrderScout'un Core scaffold, tema ve mimari düzeninin doğal parçasıdır.

```text
Doğal sohbet ve doğru mode
+ model-led dynamic planning
+ typed persistent state
+ zengin parametreli atomic domain tools
+ domain-owned ad-hoc rapor ve doğrulanmış artifact/Excel üretimi
+ gerektiğinde kaynaklı ve privacy-safe web araştırması
+ açık uçlu cross-source GoalPlan composition
+ act -> observe -> verify -> replan döngüsü
+ deterministic scope/policy/semantic verifier
+ immutable approval ve authoritative read-back
+ provider/model özgürlüğü
+ manuel UI ile aynı canonical iş mantığı
+ scaffold-faithful UI
= e-ticaret operasyonları için Codex benzeri OrderScout AI
```

## 22. Bu Hedefte Çalışacak Codex İçin Bağlayıcı Disiplin

- Hedef açıldığında önce Faz 0'dan başla; eski `ready` raporunu sürdürme.
- İlk çalışma olarak UI açma veya redesign yapma; kullanıcı ayrıca istemedikçe UI Faz
  9'a kadar görsel tasarım olarak frozen kabul edilir. Faz 9'da responsive kaynak
  geçişleri gerçek interaction ve offscreen source-app screenshot'larıyla mutlaka
  düzeltilir; eski tek-state screenshot baseline'ıyla geçiştirilmez.
- Yeni hataya yeni regex/keyword yaması eklemeyi varsayılan çözüm yapma.
- Önce canonical domain action ve Core primitive ara; tekrar yazma.
- AI tool sarmalayıcısını schema/scope/policy/approval/result/verify katmanında ince tut;
  domain iş mantığını AI içinde kopyalama.
- Manuel UI ve AI aynı işi yapıyorsa ikisinin aynı canonical domain callable'ına
  bağlandığını test ve parity raporuyla kanıtla.
- Yeni tool için gereken business fonksiyonu yoksa önce sahibi domainde headless
  canonical operation olarak tasarla ve test et; fonksiyonu AI tool içine gömme.
- UI'da hazır olmayan rapor isteğini reddetme veya AI içinde geçici hesap yazma; önce
  sahibi domainde ReportSnapshot üreten canonical analiz operation'ı kur, sonra ortak
  artifact renderer ile doğrulanmış Excel/CSV/PDF üret.
- Kullanıcının her spesifik cümlesi için birleşik tool yazma; mevcut atomic
  capability'leri typed GoalPlan ile compose et, eksik reusable capability varsa sahibi
  domain sözleşmesine ekle.
- Web gerektiğinde ortak web operation'larını kullan; aramadan önce privacy sanitizer,
  sonuçtan sonra source-open/citation ve prompt-injection sınırlarını uygula.
- `agent.py` veya eşdeğer monolit içinde aynı intent/state kuralını çoğaltma.
- Her değişikliği mimari hedef, gerçek failure ve ölçülebilir invariant'a bağla.
- İlerlemeyi değişen dosya, yazılan kod veya geçen focused test sayısıyla ölçme. Tek
  authoritative ölçüt, gerçek kullanıcı dilindeki hedefin source-app üzerinde doğru
  anlaşılması, gerekli operation'ların hedefe göre compose edilmesi, görünür cevabın
  observation ile eksiksiz uyuşması ve varsa etkinin read-back ile doğrulanmasıdır.
- Aynı hata sınıfı farklı cümlelerde yeniden ortaya çıkıyorsa yeni special-case, prompt
  eki, operation adına özel verifier dalı veya legacy guard eklemeyi durdur. Tekrarlayan
  semptom ortak state/plan/observation/projection sözleşmesindeki mimari kusur sayılır;
  sahip katman sadeleştirilip tek birleşik agent loop'u esas alınır.
- Testleri görünür pencere açmadan offscreen çalıştır.
- İzole test veya doğrudan tool çağrısını ürün kabulü diye sunma; aynı senaryoyu gerçek
  Chat source-app orchestration yolunda, fresh process ve kullanıcıya görünen cevapla
  doğrula.
- Focused cloud tekrar yalnız belirlenen kök nedenin kapandığını gösterebilir. Her focused
  düzeltmeden sonra tam organik cloud kampanyası sıfırdan başlatılır; önceki turları veya
  eski artifact'ı yeni source fingerprint'i için geçmiş sayma. Tek kritik görünür sapmada
  kampanyayı durdur, kök nedeni düzelt ve tam kampanyayı yeniden başlat.
- "Dördünü değil bütün bekleyenleri" frozen düzeltme zincirinde yalnız yeni kartın doğru
  görünmesine bakma: eski persisted action'ın terminal `superseded` state'ini, eski onayın
  reddini, yeni exact selection/action'ı ve execute sonrası authoritative read-back'i tek
  offscreen ürün-yolu testinde birlikte kanıtla.
- Deterministic compiler/fallback modelin yerine business plan kuruyorsa bunu başarı
  değil mimari ihlal olarak raporla; yalnız schema/policy/eşdeğer canonicalization
  sınırında kal.
- Güçlü model basit manuel parity hedefinde kötü sonuç verdiğinde modeli suçlayıp geçme;
  Bölüm 17.4'teki katmanları provenance ile ayır, failure'ı tek bir sahip katmana bağla ve
  kök nedeni orada düzelt.
- Yeni cloud kampanyasını önce fallback kapalı exact `deepseek/deepseek-v4-flash` ücretli
  kontrolüyle yürüt; ardından aynı frozen yetenekleri Gemini ve OpenRouter'ın ayrı ayrı
  erişilebilen en güçlü ücretsiz adaylarında sınayarak karşılaştır. Güçlü baseline'lar
  kararlı olmadan düşük-tier cloud, küçük veya local model kampanyası başlatma.
- Ücretli model sonucunu ücretsiz provider kabulünün yerine koyma; mevcut her provider'ın
  erişilebilen en iyi ücretsiz modelini ayrı fresh-process ürün-yolu kanıtıyla geçir.
- `429` gördüğünde status code'dan kota kapsamı uydurma. Önce secret-safe normalized
  `quota_scope` kanıtını üret; yalnız model scope'unda sıradaki quality-route modeline geç,
  proje/hesap/provider veya belirsiz scope'ta dur. Normal ürün fallback'i ile fallback
  kapalı exact-model kabulünü aynı kanıt gibi raporlama.
- Gerçek production R0/R1 çalışmalarını gereksiz yere durdurma; R2/R3 sınırlarını koru.
- Stage Seller `2738` dışına credential, record veya action taşıma; Stage hatasında
  production fallback yapma.
- Kullanıcı istemeden production mutation veya fiziksel baskı çalıştırma.
- Kanıtlanmamış işi tamamlanmış gösterme.
- Orders'i yalnız count/list gibi dar okumalar geçti diye `ready` veya `completed` ilan
  etme. Doğal sohbet sürekliliği, exact scope ve selection, detay/risk, prepare-cancel,
  approval-resume-execute-read-back, ad-hoc rapor/Excel, public web research ve private-web
  sınırı aynı birleşik ürün yolunda birlikte geçmeden Orders kapanmaz.
- Her yeni gerçek kullanıcı failure'ını eski passing evidence'ın önüne koy.
- Gerekli 50/60/100/200+ mesaj kampanyalarında her assistant cevabını bizzat oku.
- Sistemik yeni bulguyu gerekçe ve acceptance invariant'ıyla bu belgeye ekle; dar bug
  ayrıntılarını regression/evidence dosyalarında tut.
- Hedef gerçekten tamamlanana veya gerçek dış engel oluşana kadar güvenli ve sıralı
  çalışmayı sürdür.


### Karar 213 — R462 organik ilk kritik hata ve R463 kapsam/projeksiyon sınırı (2026-09-05)

R462 fresh process / exact ücretli OpenRouter deepseek/deepseek-v4-flash / fallback kapalı / offscreen Stage seller 2738 yolunda 1. turdan başlayan 50+ organik kampanyadır. İlk cevap 570 sipariş, 917.169,66 TRY ve 1.609,07 TRY/sipariş ile doğruydu. İkinci tur ReadyToShip 48 kaydın tamamını sıra+sipariş numarası, ürün ve kargoyla istedi. Tam cevap `Tüm dönemlerde kargoya hazir 286 siparis var.` oldu. İlk kritik hatada failed finalize edildi ve süreç kaynak değişikliğinden önce kapatıldı; onay/mutasyon yok. Artifact SHA256: `e91813221f1cad0bb204f47d80e6f5eb49b4a4fb09636fb29416253a0ae5dbfd`.

Coarse status_scope ready_to_ship, Created/Picking/ReadyToShip iş kuyruğuna bağlandı; model sözleşmesinde ayrı exact durum kodu yoktu. identifier_display ordinal, açık order_number projeksiyonunu kaldırdı. Ürün kanıtı olmayan liste için final verifier başarısızken tool count metni gösterildi. R463 model-authored status_codes, ortak compile/execute filtre doğrulaması, bağımsız sıra/kimlik görünürlüğü ve canonical Orders.query_orders üzerinden filtreli tam bağlam okumayı ekler. Tam bağlamda 100 kayıt tavanı/pagination ve exact-set varsayılanı vardır; eksik/genişleyen durum listesi yanıt doğrulamasından geçmez. Yeni dört test geçti; geniş regresyon ve fresh canlı focused bekliyor. R461 yüzde ölçekleme kabulü tarihsel/bounded kalır. Orders ve organik-50 açık.
