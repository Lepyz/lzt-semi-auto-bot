# Boostera — sade sipariş işleyicisi

Python 3.12+ / FastAPI / PostgreSQL. Çalışan bot Upstash kullanmaz.
Eski sürümden müşteri linki ve webhook okuma uyumluluğu korunmuştur.

## Sipariş davranışı

- Webhook, sipariş PostgreSQL'e kaydedildikten sonra başarılı cevap alır.
- Aynı Itemsatış sipariş kimliği tekrar gelirse ikinci satın alma oluşturulmaz.
- Aktif sipariş bulunmayan hedefe yeni satın alma otomatik gönderilir.
- Aynı hedefte aktif sipariş varsa yeni satın alma tutulur ve bir kez haber verilir.
- Önceki sipariş Completed / Partial / Canceled / Refunded vb. sonuçlanınca sıradaki
  satın alma için **gönderebilirsin** bildirimi gelir. **Otomatik gönderilmez.**
- Gönderim için Telegram butonu veya admin panelindeki buton kullanılır. Aktif
  sipariş tekrar kontrol edilir; daha eski bekletilmiş satın alma atlanmaz.
- Panel add isteği zaman aşımına uğrarsa otomatik tekrar yapılmaz. Panelde açılmış
  olabilir: bulunan SMM kimliğini kaydet veya açılmadığını açıkça doğrula.
- Paket bileşenlerinin SMM kimlikleri ayrı saklanır. Başarılı bileşen yeniden açılmaz.
- Bilgisi/eşleştirmesi eksik veya türü tanınmayan sipariş biçimindeki webhooklar
  kontrol listesinde kalır; yeni event türü diye sessizce silinmez.
- İlk kurulumda gönderimler duraklatılmıştır. Eşleştirme ve geçiş doğrulandıktan
  sonra admin panelinden etkinleştirilir. Duraklatılmış kayıtlar elle gönderilir.

## Kaldırılan işler

Gecikme alarmı, sürekli tamamlanma taraması, otomatik bakiye sorguları, bakiye
geçmişi, kur/kâr/zarar/fiyat takibi, boş Redis kuyruk taraması ve çalışmayan
favori/istatistik ekranları yoktur. Panel hata sayaçları için veritabanı kullanılmaz.
Sipariş kayıtları tek tek güncellenir. Telegram bildirimi sipariş işleyicisini bekletmez.
Gönderilmiş bildirimlerin metni tutulmaz; tekrar bildirimi önleyen kısa anahtar kalır.
Komut cevapları veritabanına yazılmaz.

Yalnızca yeni satın almayı engelleyen aktif panel siparişleri varsayılan 15 dakikada
bir kontrol edilir. Aynı linkteki bekleyenler tek kontrolü paylaşır. Hiç bekletilen
satın alma yoksa arka planda **sıfır veritabanı ve panel sorgusu** yapılır.
Admin sayfaları kendiliğinden veritabanı yenilemesi yapmaz.

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

1. Neon'da Free proje oluştur, PostgreSQL bağlantısını al. Bağlantı adresini yalnızca
   Render Environment → DATABASE_URL alanına ve yerelde geçici ortam değişkenine
   ekle. GitHub dosyasına, sohbet mesajına veya terminal çıktısına yazdırma.
2. Mevcut panel API değişkenlerini, ADMIN_PASSWORD, BOT_TOKEN ve CHAT_ID'yi koru.
   Ortam değişkenlerinin listesi .env.example dosyasında. Kod .env dosyasını kendiliğinden
   okumaz; Render ortam değişkenlerini kullanır.
3. Build: pip install -r requirements.txt
   Start: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers
   Bir Uvicorn işçisi/tek Render instance kullan. İçeride farklı hedefler için
   varsayılan dört gönderim thread'i vardır; aynı hedef veritabanı kilidiyle korunur.
4. İlk gerçek gönderimden önce aşağıdaki aktarımı yap. Yeni sürüm varsayılan
   duraklatılmış açılır. Eski Upstash URL'si ortamda duruyorsa geçiş tamamlanmadan
   gönderimleri etkinleştirmek de engellenir.
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

### Eski kayıtları aktarma

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
- Kesin sipariş kimliği bulunmayan satışlar otomatik gönderilmez; kontrol ister.
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
