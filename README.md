# Boostera — sade sipariş işleyicisi

Python 3.14 (.python-version) / FastAPI / PostgreSQL. Çalışan bot Upstash kullanmaz.
Eski sürümden müşteri linki ve webhook okuma uyumluluğu korunmuştur.

## Sipariş davranışı

- Webhook, sipariş PostgreSQL'e kaydedildikten sonra başarılı cevap alır.
- Aynı Itemsatış sipariş kimliği tekrar gelirse ikinci satın alma oluşturulmaz.
- Aktif sipariş bulunmayan hedefe yeni satın alma otomatik gönderilir.
- Aynı hedefte aktif sipariş varsa yeni satın alma tutulur; kendi bilgileri ve sebebiyle Telegram'a bildirilir.
- Önceki sipariş Completed / Partial / Canceled / Refunded vb. sonuçlanınca sıradaki
  satın alma için **gönderebilirsin** bildirimi gelir. **Otomatik gönderilmez.**
- Telegram'daki düğme webdeki gönderim önizlemesini açar; son onay webden verilir. Aktif
  sipariş tekrar kontrol edilir; daha eski bekletilmiş satın alma atlanmaz.
- Panel add isteği zaman aşımına uğrarsa otomatik tekrar yapılmaz. Panelde açılmış
  olabilir: bulunan SMM kimliğini kaydet veya açılmadığını açıkça doğrula.
- Render dağıtımında yeni örnek, eski örnek işini bitirirken açılır. Yarım kalan
  kayıtlar bu yüzden açılıştan ~2 dakika sonra ve yalnızca eskimişse ele alınır:
  panele gitmemiş kayıt kuyruğa geri alınır, panel cevabı bilinmeyen kayıt
  "Panelden kontrol et" durumuna geçer ve tekrar gönderilmez.
- Paket bileşenlerinin SMM kimlikleri ayrı saklanır. Başarılı bileşen yeniden açılmaz.
- Bilgisi/eşleştirmesi eksik veya türü tanınmayan sipariş biçimindeki webhooklar
  kontrol listesinde kalır; yeni event türü diye sessizce silinmez.
- İlk kurulumda gönderimler duraklatılmıştır. Eşleştirme ve geçiş doğrulandıktan
  sonra admin panelinden etkinleştirilir. Duraklatılmış kayıtlar elle gönderilir.

## Takılan sipariş ve kısa geçmiş

Botun kaydettiği bir satın alma, işlem sırası / hazırlık / gönderim aşamasında
5 dakika gerçek ilerleme göstermezse bir Telegram uyarısı oluşturulur. Aktif SMM
siparişinin uzun sürmesi veya bilerek bekletilmiş bir kayıt bu alarma dahil değildir.
Bilerek eşleştirilmemiş ilanlar sessiz kalır. Aynı gönderim denemesi için uyarı bir
kez oluşturulur; yeniden başlatma veya aynı bildirimin tekrarı yeni uyarı üretmez.
Sen açıkça yeni bir gönderim denemesi başlatırsan o deneme ayrıca izlenir.

Kontrol siparişi yeniden göndermez, durumunu/revizyonunu veya hedef kilidini değiştirmez.
Geç dönen gerçek panel cevabı kaydedilebilir. Mesaj gönderilmeden önce ilerleme yeniden
kontrol edilir; çözülmüş uyarı iptal edilir. Takılan kayıtlar web işlem kutusunda ve
ayrıntıda işaretlenir. Kontrol yalnızca bota ulaşmış kayıtlar içindir.

İzleme zamanları RAM'dedir; yalnızca süresi dolmuş kayıtlar kimlikleriyle okunur.
Boşta veya süre dolmadan ek SQL sorgusu yoktur. Başlangıçta yarım kayıtlar bir kez
yüklenir ve eski Render örneğinin işi bitirmesi için mevcut açılış beklemesi korunur.
Webdeki takılanlar listesi sayfa açıldığında hesaplanır; arka planda tablo taranmaz.

Sipariş ayrıntısındaki İşlem geçmişi, son 10 önemli değişikliği mevcut kayıt içinde
tutar: kaydedilme, bekletilme, manuel onay, panel numarası, sonuç ve bilgi/fiyat düzeltme.
Tekrarlanan durum sorguları geçmişi doldurmaz; ham API cevapları veya müşteri linki
geçmişe kopyalanmaz. Eski kayıtlara uydurma geçmiş eklenmez. Silme geçmişi de temizler.
Geçmiş, normal kayıt güncellemesiyle aynı işlemde kaydedilir; ek tablo veya servis yoktur.

## Zarar koruması

Sipariş panele gönderilmeden hemen önce tahmini kâr hesaplanır:
doğrulanmış satış fiyatı − sabit Itemsatış komisyonu (%7) − panelin o anki
servis fiyatı (panel API `services` listesi; 1000 adet fiyatı, Package türünde sipariş başı).
Panel fiyat listesi yalnızca gönderim veya gönderim özeti açılırken okunur ve 5 dakika
bellekte tutulur; başarısız sorguda 1 dakika beklenir ve eşzamanlı siparişler aynı
fiyat sorgusunu paylaşır. Boştayken istek yapılmaz. Tüm paneller TL fiyat kullanır.
Tutarlar Decimal ile hesaplanır ve kuruşa yuvarlanır. Örnek: 100 TL satış − 7 TL
komisyon − 40 TL panel maliyeti = 53 TL tahmini kâr. Web ve CSV'de komisyon sonrası
kalan, marj, başa baş fiyatı ve seçilen kâr hedefi için satış fiyatı da bulunur.
Komisyon/kesinti tutarları satış fiyatı olarak okunmaz; mesajdan yalnızca açık satış
bedeli kalıpları kabul edilir. Çelişkide fiyat bilinmiyor sayılır. Eski sürümün
belirsiz metin fiyatı onaysız kullanılmaz. Satış fiyatı webden doğrulanıp düzeltilebilir;
bu işlem sipariş göndermez veya panel sorgulamaz. Hesap tahminidir; iptal/kısmi iade
tutarının doğrulandığı gerçekleşen kâr raporu değildir.

Bağlantılar sayfasından mod seçilir: Kapalı / Gözlem / Koruma açık. Gözlemde yalnızca
hesaplanıp siparişte ve CSV'de gösterilir. Koruma açıkken kâr sınırın (varsayılan 10 TL)
altındaysa, panel fiyatı alınamazsa veya satış fiyatı yoksa sipariş bekletilir ve bir kez
bildirilir. Gönderim özetinde kâr onayı işaretlenerek o tek gönderim için geçilebilir.

## Kaldırılan işler

Gecikme alarmı, sık aralıklı tamamlanma taraması, otomatik bakiye sorguları, bakiye
geçmişi, kur/kâr/zarar/fiyat takibi, boş Redis kuyruk taraması ve çalışmayan
favori/istatistik ekranları yoktur. Panel hata sayaçları için veritabanı kullanılmaz.
Sipariş kayıtları tek tek güncellenir. Telegram bildirimi sipariş işleyicisini bekletmez.
Gönderilmiş bildirimlerin metni tutulmaz; tekrar bildirimi önleyen kısa anahtar kalır.
Komut cevapları veritabanına yazılmaz.

Aktif panel siparişleri varsayılan 30 dakikada (`ACTIVE_CHECK_INTERVAL_SECONDS`),
yeni satın almayı engelleyenler 15 dakikada (`BLOCKED_CHECK_INTERVAL_SECONDS`) kontrol edilir.
Aynı linkteki bekleyenler tek kontrolü paylaşır. Zamanlama bellektedir; hiçbir
kontrolün zamanı gelmemişse monitör SQL veya panel sorgusu yapmaz. Açılıştaki tek
seferlik kurtarma işlemi dışında aktif/bekleyen kayıt yokken arka plan sorgusu yoktur.
Admin sayfaları kendiliğinden veritabanı yenilemesi yapmaz.

## Mobil yönetim ve az bildirim

Ana ekran İşlem bekleyenler kutusudur. Kayıtlar mobil kartlarda neden ve yapılacak
işlemle görünür. İsteğe bağlı «İlgileniyorum» işareti, hedefe ait en son 50 kayıt,
numara/link kopyalama, link düzeltme ve gönderim önizlemesi vardır. Bilgi düzeltmek
veya eşleştirmek sipariş göndermez. İstenerek eşleştirilmemiş ilanlar işlem kutusu
ve Telegram dışında, Tüm kayıtlar bölümünde korunur.

Başarılı panel gönderimi, panel sipariş numaraları ve adetleriyle bir kez Telegram'a
bildirilir. Aynı kaydın tekrarı veya yeniden başlatma ikinci başarı mesajı üretmez.
Sorunsuz tamamlanma ayrıca bildirilmez. Eski sessiz başarı kayıtları topluca gönderilmez.
Başlatılamayan, aktif hedef nedeniyle bekletilen veya duraklatılan her ayrı satın alma
kendi kayıt numarası, hedefi ve sebebiyle bildirilir. Bir ilanın/sorunun gün içinde
daha önce bildirilmiş olması sonraki satın almanın uyarısını bastırmaz. Aynı kaydın
değişmeyen durumunu izlemek tekrar bildirim üretmez; açık bir manuel deneme yeniden
engellenirse o denemenin sonucu bildirilir. İstenerek eşleştirilmemiş ilanlar sessiz kalır.
Satın alma olduğu anlaşılan fakat ilan numarası okunamayan kayıt ise tek inceleme
uyarısı üretir; ilan numarası webde düzeltilebilir, kaydetmek otomatik göndermez.
Gönderime hazır kayıt için bir uyarı gelir. İptal/kısmi/iade sonuçları Türkçe gösterilir;
aynı sonuç bekleyen kaydı hazır yaptıysa sonuç ve hazır bildirimi tek mesaj olur.
Ret ve belirsiz cevap uyarıları her sipariş için ayrıdır; zamanlayıcıyla hatırlatma gönderilmez.
Panel üç durum kontrolünde cevap vermemişse aktif kilit korunur, webde uyarı ve
tek seferlik bildirim oluşturulur. İptal gerekçesi/iade tutarı tahmin edilmez.

Telegram'da `/start` veya `/yardim` menüyü açar. `/bekleyen`, `/sorunlar`, `/durum`,
`/ara kayıt-no` komutları Türkçe cevap verir; eski komut adları da çalışır.

Toplu eşleştirme önizlemesinin değişiklikleri ve sürüm özeti aynı veriden üretilir.
Tekli/toplu ekleme, düzenleme ve silme aynı işlem kilidini paylaşır; sürüm kontrolü
ile kaydetme arasına başka bir eşleştirme yazması giremez. Ek tablo veya tarama yoktur.

Webde her uygun kayıtta **Kaydı kapat** ve **Sil** düğmeleri bulunur. Seçim kutularıyla
görüntülenen kayıtlar topluca da temizlenebilir; işlemden önce sayı ve etkisi gösterilir,
son onay gerekir. Kapatma, gönderilmemiş kaydı Sonuçlananlar'a taşır. Silme, müşteri,
ürün ve panel ayrıntılarını kaldırır; çift siparişe karşı yalnızca küçük bir kimlik
kaydı korunur. Bu kayıt normal listelerde, aramada veya dışa aktarımda görünmez.
Aktif, işlenmekte olan ve sonucu belirsiz kayıtlar kapatılamaz veya silinemez.
Bir seçimde uygun olmayan veya değişmiş kayıt varsa işlem bütünüyle durur.
Temizlik panelde iptal/iade isteği veya yeni sipariş göndermez; seçilen kayıtların
henüz gönderilmemiş uyarıları kaldırılır. Sonraki bekleyen kayıt hazır olursa yine
manuel onay gerekir. Bu özellik için yeni tablo veya zamanlanmış tarama yoktur.
Komut cevapları kalıcı bildirim geçmişi oluşturmaz. Eski «gönder» düğmeleri yeni
sipariş açmak yerine kullanıcıyı web önizlemesine yönlendirir.

## Yerelde doğrulama

    python -m venv .venv
    python -m pip install -r requirements-dev.txt
    python -m pytest -q

Ortamda DATABASE_URL=sqlite:///work/local.sqlite ve güçlü bir ADMIN_PASSWORD tanımla.
Sanal ortam etkinleştirildikten sonra:

    python -m uvicorn main:app --workers 1

SQLite yalnızca yerel çalışma/test içindir. Render ortamında SQLite ile başlatma
reddedilir; ücretsiz Render'ın yerel dosyaları kalıcı değildir.

## Render / Neon geçişi

Neon Free bir seçenektir; kullanım sınırları vardır, ücretsiz kesintisiz hizmet
garantisi yoktur. Güncel koşullar: https://neon.com/pricing

1. Neon'da Free proje oluştur, PostgreSQL bağlantısını al. Bağlantı adresini
   Render Environment → DATABASE_URL alanına ekle. GitHub dosyasına, sohbet
   mesajına veya terminal çıktısına yazdırma.
2. Mevcut panel API değişkenlerini, ADMIN_PASSWORD, BOT_TOKEN ve CHAT_ID'yi koru.
   Ortam değişkenlerinin listesi .env.example dosyasında. Kod .env dosyasını kendiliğinden
   okumaz; Render ortam değişkenlerini kullanır.
3. Build: pip install -r requirements.txt
   Start: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers
   Bir Uvicorn işçisi/tek Render instance kullan. İçeride farklı hedefler için
   varsayılan dört gönderim thread'i vardır; aynı hedef veritabanı kilidiyle korunur.
4. Yeni kurulum duraklatılmış açılır. Upstash geçişi tamamlandı; yönetim panelindeki
   aktarım ekranı kaldırıldı, gerekirse aşağıdaki komut satırı aracı kullanılır.
5. Itemsatış webhook adresi aynı kalır: /itemsatis-webhook. Geçiş aralığında gelen
   satın almaları Itemsatış sipariş listesiyle karşılaştır. Kaynak platformun başarısız
   webhookları tekrar göndermesi doğrulanmadan uçtan uca sipariş kaybı garantisi verilemez.
6. İlan-servis/paket eşleştirmelerini ve içe alınan SMM kimliklerini kontrol et.
   Ardından yeni gönderimleri admin panelinden etkinleştir.
7. UptimeRobot adresi /health veya /test olsun. Eski check-orders /
   check-services / check-balances adresleri de artık yalnızca hafif ayakta olma
   cevabı verir. Bu adresler veritabanı veya panel çağırmaz.
8. Telegram için aşağıdaki kurulumu tamamla. Geçiş doğrulandıktan sonra Render'dan
   Upstash değişkenlerini kaldırabilirsin. Kaynak verileri hemen silme.

### Eski kayıtları aktarma (tamamlandı)

Geçiş Ekim 2026'da tamamlandı. Yanlışlıkla yeniden çalıştırılıp gönderimleri
duraklatmasın diye yönetim panelindeki aktarım ekranı kaldırıldı.

Komut satırı alternatifi:

Araç Upstash'a yalnızca GET/LRANGE gönderir; hiçbir kaynak anahtarı silmez veya
değiştirmez. Log/fiyat/bakiye cache'lerini taşımaz.

Yerelde DATABASE_URL ve eski UPSTASH_REDIS_REST_URL / TOKEN ortam değişkenlerini
tanımla. Değerleri kabuk geçmişine yazmayan bir gizli giriş yöntemi kullan.

    python scripts/migrate_upstash.py

Bu varsayılan komut yalnızca mevcut kayıt sayılarını gösterir. Yazma yapmaz.
Eski sipariş işleyicisi durduktan sonra, yeni gönderimler de duraklatılmışken:

    python scripts/migrate_upstash.py --apply --old-service-stopped

Taşınanlar: ilan-servis eşleştirmeleri, paketler, mevcut aktif SMM kimlikleri,
işlenmiş satın alma kimlikleri, elde kalan başarısız siparişler ve üç kuyruk.
Eski kuyruk kayıtları otomatik gönderime açılmaz; kontrol listesine alınır.
Eski processing kuyruğu belirsiz kabul edilir, panelden doğrulama ister.
Araç aynı snapshot için tekrar çalıştırılabilir; satın alma ve SMM kimlikleri çoğalmaz.
Hatalı/tanınmayan panel eşleştirmesi varsa aktarım tamamlanmış sayılmaz.

Eski sürümün önceden silmiş olduğu başarısız kayıtlar veya hiç ulaşmamış siparişler
bu araçla geri getirilemez. Aktarım sırasında manuel karşılaştırma gerekir.

### Telegram

- Bildirimlerdeki düğmeler ilgili web paneli sayfasını açar. Son gönderim onayı her
  zaman web panelinden verilir; Telegram'da para harcatan bir düğme yoktur.
- Komutlar (/bekleyen, /sorunlar, /durum, /ara) için webhook gerekir. Bağlantılar
  sayfasındaki "Telegram webhook'unu kaydet" düğmesi gizli anahtarı üretip kaydeder.
- Grupta komut kullanacak kişilerin sayısal Telegram kimlikleri TELEGRAM_ADMIN_USER_IDS
  alanına eklenir.

## Kontroller ve sınırlar

- Otomatik gönderim, yalnızca yapılandırılmış panel API adreslerine yapılır.
- Link/servis/adet doğrulaması yereldir; bakiye veya fiyat sorgusu gerektirmez.
- Panelin API anahtarları sipariş kayıtlarında veya HTML'de tutulmaz.
- Admin Basic Auth, POST işlemlerinde CSRF ve revision kontrolü vardır.
- Bilinen satış olayı ve ilan kimliği varsa, sipariş kimliği gönderilmeyen eski
  Itemsatış bildirimleri de link/eşleştirme doğrulamasından sonra işlenir. Tekrar
  gönderimler tüm bildirim içeriğinin özetiyle engellenir. Bilinmeyen olaylar kontrol ister.
- Geçiş, eski itemsatis_payload koruma özetlerini de taşır. Aynı eski bildirim
  yeniden gelirse ikinci panel siparişi açılmaz. Kaynak hiçbir ayırt edici kimlik
  veya zaman bilgisi göndermiyorsa tamamen aynı iki ayrı satın alma ayırt edilemez.
- Bekletme takibi yalnızca bu botun bildiği/içe alınmış panel siparişlerini kapsar.
  Panelin sitesinden ayrıca elle açılan siparişleri otomatik keşfetmez.
- TikTok kısa linkleri ağdan çözülmez. Aynı hedefin iki farklı kısa linkini
  eşleştirme garantisi yoktur; kanonik profil/video linkini kullan.
- Bağlantı belirsizliğinde tek seferlik dış API işlemini mutlak olarak garanti etmek,
  panelin idempotency desteği olmadan mümkün değildir. Bu sürüm belirsiz işlemi
  yeniden açmayıp insan kontrolüne bırakır.
- Telegram teslimi belirsizse tekrar yağmuru yapılmaz. Sipariş admin panelinde kalır.
  Açık 429/5xx cevaplarında en fazla üç gönderim denemesi yapılır.
- Günlük kayıtlar konsola kısa hata türü olarak yazılır; ham webhook, müşteri mesajı,
  sorgu logu veya API anahtarı veritabanına eklenmez.
