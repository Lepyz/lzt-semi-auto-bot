# Boostera — sade sipariş işleyicisi

Python 3.12+ / FastAPI / PostgreSQL. Çalışan bot Upstash kullanmaz.
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

## Kaldırılan işler

Gecikme alarmı, sık aralıklı tamamlanma taraması, otomatik bakiye sorguları, bakiye
geçmişi, kur/kâr/zarar/fiyat takibi, boş Redis kuyruk taraması ve çalışmayan
favori/istatistik ekranları yoktur. Panel hata sayaçları için veritabanı kullanılmaz.
Sipariş kayıtları tek tek güncellenir. Telegram bildirimi sipariş işleyicisini bekletmez.
Gönderilmiş bildirimlerin metni tutulmaz; tekrar bildirimi önleyen kısa anahtar kalır.
Komut cevapları veritabanına yazılmaz.

Aktif panel siparişleri varsayılan 30 dakikada (`ACTIVE_CHECK_INTERVAL_SECONDS`),
yeni satın almayı engelleyenler 15 dakikada (`BLOCKED_CHECK_INTERVAL_SECONDS`) kontrol edilir.
Kontroller her siparişin kendi saatinde değil, ortak zaman dilimlerinde toplu yapılır
(30 dakikalık dilimler 15 dakikalıkların üzerine denk gelir). Panel durumu bellekteki
son durumla aynıysa veritabanı hiç açılmaz; yalnızca durum değiştiğinde, sipariş
sonuçlandığında veya panel üç kez cevap vermediğinde kayıt okunup yazılır.
Aynı linkteki bekleyenler tek kontrolü paylaşır. Zamanlama bellektedir; hiçbir
kontrolün zamanı gelmemişse monitör SQL veya panel sorgusu yapmaz. Açılıştaki tek
seferlik kurtarma işlemi dışında aktif/bekleyen kayıt yokken arka plan sorgusu yoktur.
Admin sayfaları kendiliğinden veritabanı yenilemesi yapmaz.

## Ücretsiz kota (Neon + Render + UptimeRobot)

Yönetim panelindeki **Kota** sayfası (`/admin/usage`) bu açılıştan beri bellekte
tutulan tahminleri gösterir: Neon compute'unun ne kadar uyanık kaldığı ve ay sonu
CU-saat tahmini, veritabanı boyutu, UptimeRobot'tan son /health isteği, takipteki
sipariş sayısı ve sonraki kontrol saati. Sayfa yalnızca açıldığında tek kısa okuma
yapar. Telegram `/durum` da sonraki kontrolü ve (6 saatlik veriden sonra) Neon tahminini yazar.

- **Neon Free:** proje başına ayda 100 CU-saat, 0.5 GB depolama, 5 GB çıkış trafiği.
  Compute son sorgudan 5 dakika sonra uyur ve uyurken saat harcamaz. Sınır aşılırsa
  compute ay sonuna kadar durur ve webhooklar kaydedilemez. 0.25 CU sürekli açık
  kalırsa ayda ~182 CU-saat eder; bu yüzden her sorgu önemlidir.
  - Compute boyutunu 0.25 CU'ya sabitle (autoscaling en az/en çok 0.25).
  - Neon bölgesini Render'a yakın seç (ör. ikisi de Frankfurt).
  - Neon SQL Editor gibi dış sorgular da compute'u uyandırır ve tahmine dahil değildir.
  - Kota sayfasında oran %60'ı geçerse kontrol aralıklarını uzat
    (örn. `ACTIVE_CHECK_INTERVAL_SECONDS=3600`, `BLOCKED_CHECK_INTERVAL_SECONDS=1800`;
    biri diğerinin katı olursa dilimler çakışır).
- **Render Free:** çalışma alanı başına ayda 750 saat; tek servis 7/24 açık ≈ 720–744 saat.
  İkinci bir ücretsiz servisi sürekli açık tutma: saatler ortak harcanır ve bitince
  bütün ücretsiz servisler ay sonuna kadar durur. 15 dakika trafik almayan servis uyur.
- **UptimeRobot Free:** 5 dakikalık aralık. Tek HTTP(s) monitörü yeterli: adres
  `/health`, yöntem HEAD. /health veritabanına veya panele gitmez. Arka plan işleri
  (kontrol veya Telegram iş parçacığı) durmuşsa 503 döner; UptimeRobot e-postası gelir.
  Render'da Health Check Path olarak da `/health` girilebilir. UptimeRobot'un ücretsiz
  planı kişisel kullanım için tanımlanıyor; ticari kullanım koşullarını kendi
  sözleşmesinden kontrol et.

Sipariş listesi varsayılan olarak son 100 kaydı gösterir; «Daha fazla kayıt göster»
500 kayda çıkar. Böylece her yenilemede Neon'dan ve Render'dan daha az veri taşınır.

## Mobil yönetim ve az bildirim

Ana ekran İşlem bekleyenler kutusudur. Kayıtlar mobil kartlarda neden ve yapılacak
işlemle görünür. İsteğe bağlı «İlgileniyorum» işareti, hedefe ait en son 50 kayıt,
numara/link kopyalama, link düzeltme ve gönderim önizlemesi vardır. Bilgi düzeltmek
veya eşleştirmek sipariş göndermez. İstenerek eşleştirilmemiş ilanlar işlem kutusu
ve Telegram dışında, Tüm kayıtlar bölümünde korunur.

Normal başarılı gönderim ve sorunsuz tamamlanma Telegram'a yazılmaz.
Başlatılamayan, aktif hedef nedeniyle bekletilen veya duraklatılan her ayrı satın alma
kendi kayıt numarası, hedefi ve sebebiyle bildirilir. Bir ilanın/sorunun gün içinde
daha önce bildirilmiş olması sonraki satın almanın uyarısını bastırmaz. Aynı kaydın
değişmeyen durumunu izlemek tekrar bildirim üretmez; açık bir manuel deneme yeniden
engellenirse o denemenin sonucu bildirilir. İstenerek eşleştirilmemiş ilanlar sessiz kalır.
Gönderime hazır kayıt için bir uyarı gelir. İptal/kısmi/iade sonuçları Türkçe gösterilir;
aynı sonuç bekleyen kaydı hazır yaptıysa sonuç ve hazır bildirimi tek mesaj olur.
Ret ve belirsiz cevap uyarıları her sipariş için ayrıdır; zamanlayıcıyla hatırlatma gönderilmez.
Panel üç durum kontrolünde cevap vermemişse aktif kilit korunur, webde uyarı ve
tek seferlik bildirim oluşturulur. İptal gerekçesi/iade tutarı tahmin edilmez.

Telegram'da `/start` veya `/yardim` menüyü açar. `/bekleyen`, `/sorunlar`, `/durum`,
`/ara kayıt-no` komutları Türkçe cevap verir; eski komut adları da çalışır.

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
4. Yeni sürümü gönderimler duraklatılmış olarak dağıt. Eski sürümün artık çalışmadığını
   Render dağıtım durumundan doğrula. Ardından aşağıdaki yönetim ekranıyla aktarımı yap.
   Eski Upstash URL'si ortamda duruyorsa geçiş tamamlanmadan gönderimleri etkinleştirmek
   engellenir. İlk kurulum duraklatılmış açılır; bunu değiştirme.
5. Itemsatış webhook adresi aynı kalır: /itemsatis-webhook. Geçiş aralığında gelen
   satın almaları Itemsatış sipariş listesiyle karşılaştır. Kaynak platformun başarısız
   webhookları tekrar göndermesi doğrulanmadan uçtan uca sipariş kaybı garantisi verilemez.
6. İlan-servis/paket eşleştirmelerini ve içe alınan SMM kimliklerini kontrol et.
   Ardından yeni gönderimleri admin panelinden etkinleştir.
7. UptimeRobot adresi /health veya /test olsun (HEAD, 5 dakika). Eski check-orders /
   check-services / check-balances adresleri de artık yalnızca hafif ayakta olma
   cevabı verir. Bu adresler veritabanı veya panel çağırmaz; arka plan işleri
   durmuşsa 503 döner.
8. Telegram için aşağıdaki kurulumu tamamla. Geçiş doğrulandıktan sonra Render'dan
   Upstash değişkenlerini kaldırabilirsin. Kaynak verileri hemen silme.

### Eski kayıtları aktarma

Ücretsiz Render'da terminal veya yerel bağlantı anahtarı gerektirmeyen yol:

1. Yeni sürüm dağıtıldıktan sonra /admin/migration adresini aç veya üst menüden
   Veri aktarımı bağlantısına tıkla. Mevcut admin kullanıcı adı/parolası kullanılır.
2. Eski kayıtları kontrol et düğmesine bas. Yalnızca eski kayıt sayıları okunur.
3. Yeni gönderimler duraklatılmış ve eski sürüm artık çalışmıyorken ilgili kutuyu
   işaretle, Kayıtları yeni veritabanına aktar düğmesine bas.
4. Aktarım tamamlandı sonucunu bekle. İşlem sırasında durum göstergesi yalnızca
   sunucu belleğini okur; Upstash veya PostgreSQL sorgusu üretmez.
5. Eşleştirmeleri ve eski SMM kimliklerini kontrol et. Bundan sonra yeni gönderimleri
   etkinleştir. Eski kuyruktan taşınan kayıtlar kendiliğinden gönderilmez.

Bağlantılar Render Environment içinden okunur; HTML veya sonuç ekranında gösterilmez.
Aktarım çalışırken diğer admin değişiklikleri engellenir. Yarım kalan aktarımda
gönderimler kapalı tutulur, kaynak kayıtlar korunur; işlem tekrar çalıştırılabilir.

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

### Telegram gönderme butonu

- Render'a güçlü, rastgele bir TELEGRAM_WEBHOOK_SECRET ve PUBLIC_BASE_URL ekle.
- Kişisel sohbette CHAT_ID sahibi gönderme yetkisine sahiptir.
- Grupta ayrıca TELEGRAM_ADMIN_USER_IDS alanına yetkili kullanıcıların sayısal
  Telegram kimliklerini ekle. Grup üyelerinin tamamına sipariş açma izni verilmez.
- Aynı ortam değişkenleriyle açıkça çalıştır:

    python scripts/configure_telegram.py

Bu komut Telegram setWebhook kaydını günceller; bekleyen güncellemeleri silmez.
Webhook secret kurulmadan Telegram'da para harcatan gönderme butonu gösterilmez.
Admin panelindeki manuel gönderme her zaman kullanılabilir.

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
