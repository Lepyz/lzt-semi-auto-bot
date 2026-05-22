import os
import re
import json
import csv
import io
import time
import hashlib
import ast
import asyncio
import secrets
import threading
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Template
from fastapi.staticfiles import StaticFiles
try:
    import structlog
    from structlog import get_logger

    # ─── STRUCTLOG SETUP ───────────────────────────────────────────────────────
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )
    logger = get_logger()
except Exception:
    import logging

    logging.basicConfig(level=logging.INFO)

    class _FallbackLogger:
        def info(self, event, **kwargs):
            logging.info("%s %s", event, kwargs)
        def warning(self, event, **kwargs):
            logging.warning("%s %s", event, kwargs)
        def error(self, event, **kwargs):
            logging.error("%s %s", event, kwargs)

    logger = _FallbackLogger()

app = FastAPI()
security = HTTPBasic()

# Optional favicon/static assets. If the static folder is not in the repo, bot still starts.
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
STATE_LOCK = threading.RLock()


ITEMSATIS_COMMISSION_RATE = 0.07
RECORDED_SALES = set()

SMM_API_URL = os.getenv("SMM_API_URL", "https://smmrush.com/api/v2")
SMM_API_KEY = os.getenv("SMM_API_KEY", "")
MEDYABAYIM_API_URL = os.getenv("MEDYABAYIM_API_URL", "https://medyabayim.com/api/v2")
MEDYABAYIM_API_KEY = os.getenv("MEDYABAYIM_API_KEY", "")
LIONFOLLOW_API_URL = os.getenv("LIONFOLLOW_API_URL", "https://lionfollow.com/api/v2")
LIONFOLLOW_API_KEY = os.getenv("LIONFOLLOW_API_KEY", "")

MORETHANPANEL_API_URL = os.getenv("MORETHANPANEL_API_URL", "https://morethanpanel.com/api/v2")
MORETHANPANEL_API_KEY = os.getenv("MORETHANPANEL_API_KEY", "")

UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

# Itemsatış API - müşteri mesajı göndermek için
ITEMSATIS_API_KEY = os.getenv("ITEMSATIS_API_KEY", "")
ITEMSATIS_API_URL = "https://itemsatis.com/api"
CUSTOMER_NOTIFY_ENABLED = os.getenv("CUSTOMER_NOTIFY_ENABLED", "false").lower() == "true"

CS2_ADVERT_ID = "5282114"

PANEL_MAP = {
    "smmrush": {
        "name": "SMMRush",
        "api_url": SMM_API_URL,
        "api_key": SMM_API_KEY,
    },
    "medyabayim": {
        "name": "MedyaBayim",
        "api_url": MEDYABAYIM_API_URL,
        "api_key": MEDYABAYIM_API_KEY,
    },
    "lionfollow": {
        "name": "LionFollow",
        "api_url": LIONFOLLOW_API_URL,
        "api_key": LIONFOLLOW_API_KEY,
    },
    "morethanpanel": {
        "name": "MoreThanPanel",
        "api_url": MORETHANPANEL_API_URL,
        "api_key": MORETHANPANEL_API_KEY,
    },

    # 3-4 yeni panel eklemek için Render Environment içine şunları koy:
    # PANEL3_NAME, PANEL3_API_URL, PANEL3_API_KEY
    # PANEL4_NAME, PANEL4_API_URL, PANEL4_API_KEY
    # PANEL5_NAME, PANEL5_API_URL, PANEL5_API_KEY
    # PANEL6_NAME, PANEL6_API_URL, PANEL6_API_KEY
    "panel3": {
        "name": os.getenv("PANEL3_NAME", "Panel 3"),
        "api_url": os.getenv("PANEL3_API_URL", ""),
        "api_key": os.getenv("PANEL3_API_KEY", ""),
    },
    "panel4": {
        "name": os.getenv("PANEL4_NAME", "Panel 4"),
        "api_url": os.getenv("PANEL4_API_URL", ""),
        "api_key": os.getenv("PANEL4_API_KEY", ""),
    },
    "panel5": {
        "name": os.getenv("PANEL5_NAME", "Panel 5"),
        "api_url": os.getenv("PANEL5_API_URL", ""),
        "api_key": os.getenv("PANEL5_API_KEY", ""),
    },
    "panel6": {
        "name": os.getenv("PANEL6_NAME", "Panel 6"),
        "api_url": os.getenv("PANEL6_API_URL", ""),
        "api_key": os.getenv("PANEL6_API_KEY", ""),
    },
}

PANEL_ALIASES = {
    "smmrush": "smmrush",
    "smm": "smmrush",
    "medyabayim": "medyabayim",
    "medya": "medyabayim",
    "lionfollow": "lionfollow",
    "lion": "lionfollow",
    "lf": "lionfollow",
    "morethanpanel": "morethanpanel",
    "morethan": "morethanpanel",
    "mtp": "morethanpanel",
    "panel3": "panel3",
    "panel4": "panel4",
    "panel5": "panel5",
    "panel6": "panel6",
}

SMM_SERVICE_MAP = {
    "5098093": {
        "panel": "smmrush",
        "service_id": "63",
        "quantity": 1000,
        "platform": "instagram",
    },
    "5191839": {
        "panel": "medyabayim",
        "service_id": "13743",
        "quantity": 90,
        "platform": "instagram",
    },

    # Servisleri sonra buraya ekleyeceğiz.
    # Örnek:
    # "ITEMSATIS_ILAN_ID": {
    #     "panel": "panel3",  # smmrush / medyabayim / panel3 / panel4 / panel5 / panel6
    #     "service_id": "PANEL_SERVIS_ID",
    #     "quantity": 1000,
    #     "platform": "tiktok",
    # },
}

# /admin panelinden Redis'e kaydedilen dinamik ilan-servis eşleştirmeleri.
# API key burada tutulmaz; panel API bilgileri PANEL_MAP ve Render Environment üzerinden gelir.
DYNAMIC_SERVICES = {}
PACKAGE_CONFIGS = {}

PROCESSED_ORDERS = set()
PROCESSED_LINKS = set()
FAILED_ORDERS = []
PENDING_ORDERS = []
DAILY_STATS = {}
LAST_DAILY_REPORT_DATE = ""
SERVICE_PRICE_CACHE = {}
WEEKLY_STATS = {}
MONTHLY_STATS = {}
LAST_WEEKLY_REPORT_DATE = ""
LAST_MONTHLY_REPORT_DATE = ""
PRODUCT_NAME_CACHE = {}
PANEL_SERVICE_NAME_CACHE = {}
SALES_HISTORY = {}
ORDER_HISTORY = []
BLACKLIST = set()

# ─── YENİ: LOG GEÇMİŞİ (son 200 log dashboard için) ───────────────────────────
LOG_HISTORY = []
MAX_LOG_HISTORY = 200
LOG_FLUSH_INTERVAL_SECONDS = int(os.getenv("LOG_FLUSH_INTERVAL_SECONDS", "30"))
_LOG_DIRTY = False
_LOG_LAST_FLUSH = 0

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}

FAILED_PANEL_STATUSES = {"cancelled", "canceled", "partial", "fail", "failed", "refunded"}
COMPLETED_PANEL_STATUSES = {"completed", "complete", "tamamlandı"}
SLOW_API_THRESHOLD_SECONDS = float(os.getenv("SLOW_API_THRESHOLD_SECONDS", "8"))
PANEL_SAFE_RETRY_COUNT = int(os.getenv("PANEL_SAFE_RETRY_COUNT", "2"))
PANEL_RETRY_SLEEP_SECONDS = float(os.getenv("PANEL_RETRY_SLEEP_SECONDS", "1"))
USD_TO_TRY_RATE = float(os.getenv("USD_TO_TRY_RATE", "46"))
USD_TO_TRY_CACHE = {"rate": USD_TO_TRY_RATE, "updated_at": 0}
USD_TO_TRY_REFRESH_SECONDS = int(os.getenv("USD_TO_TRY_REFRESH_SECONDS", "21600"))




def validate_environment():
    """Başlangıçta kritik ayarları kontrol eder; eksik olanları loglar.
    Panel API keyleri zorunlu değildir; sadece ilgili panel kullanılırken gerekir.
    """
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "CHAT_ID": CHAT_ID,
        "UPSTASH_REDIS_REST_URL": UPSTASH_REDIS_REST_URL,
        "UPSTASH_REDIS_REST_TOKEN": UPSTASH_REDIS_REST_TOKEN,
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
    }
    missing = [name for name, value in required.items() if not value or (name == "ADMIN_PASSWORD" and value == "changeme")]
    if missing:
        try:
            logger.warning("environment_missing_or_unsafe", missing=missing)
        except Exception:
            print("ENV WARNING:", missing, flush=True)
    return missing


def is_webhook_authorized(request: Request) -> bool:
    """Opsiyonel webhook token kontrolü.
    WEBHOOK_SECRET_TOKEN boşsa eski sistem gibi herkese açık kalır.
    Token ayarlanırsa Itemsatış webhook URL'sine ?token=... ekleyebilir veya X-Webhook-Token header kullanabilirsin.
    """
    if not WEBHOOK_SECRET_TOKEN:
        return True
    provided = (
        request.headers.get("X-Webhook-Token")
        or request.headers.get("X-Boostera-Token")
        or request.query_params.get("token")
        or ""
    )
    return secrets.compare_digest(str(provided), WEBHOOK_SECRET_TOKEN)


def now_tr():
    return datetime.utcnow() + timedelta(hours=3)


# ─── YENİ: GELİŞMİŞ LOGLAMA ──────────────────────────────────────────────────
def flush_logs(force: bool = False):
    """Log geçmişini Redis'e kontrollü yazar; her logda Redis yazıp yavaşlatmaz."""
    global _LOG_DIRTY, _LOG_LAST_FLUSH
    if not force and not _LOG_DIRTY:
        return
    now_ts = time.time()
    if force or (now_ts - _LOG_LAST_FLUSH) >= LOG_FLUSH_INTERVAL_SECONDS:
        redis_set_json("log_history", LOG_HISTORY[-MAX_LOG_HISTORY:])
        _LOG_LAST_FLUSH = now_ts
        _LOG_DIRTY = False


def log(level: str, event: str, **kwargs):
    """Hem structlog ile JSON log yazar hem de dashboard için hafızada tutar."""
    global _LOG_DIRTY
    entry = {
        "ts": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "event": event,
        **kwargs,
    }

    log_fn = getattr(logger, level if level != "success" else "info", logger.info)
    log_fn(event, **kwargs)

    with STATE_LOCK:
        LOG_HISTORY.append(entry)
        if len(LOG_HISTORY) > MAX_LOG_HISTORY:
            LOG_HISTORY.pop(0)
        _LOG_DIRTY = True

    # Sadece aralık dolduysa Redis'e yaz.
    try:
        flush_logs(force=False)
    except Exception:
        pass


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        log("warning", "telegram_skip", reason="BOT_TOKEN veya CHAT_ID eksik")
        return

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        log("info", "telegram_sent", status=r.status_code)
    except Exception as e:
        log("error", "telegram_error", error=str(e))


# ─── YENİ: MÜŞTERİ BİLDİRİM SİSTEMİ ─────────────────────────────────────────
def send_itemsatis_message(order_id: str, message: str) -> bool:
    """
    Itemsatış siparişine müşteriye mesaj gönderir.
    Itemsatış API'nin mesaj endpoint'ini kullanır.
    """
    if not CUSTOMER_NOTIFY_ENABLED:
        log("info", "customer_notify_skip", reason="CUSTOMER_NOTIFY_ENABLED false", order_id=order_id)
        return False

    if not ITEMSATIS_API_KEY:
        log("warning", "customer_notify_skip", reason="ITEMSATIS_API_KEY eksik", order_id=order_id)
        return False

    if not order_id or str(order_id) == "Bilinmiyor":
        log("warning", "customer_notify_skip", reason="order_id geçersiz", order_id=order_id)
        return False

    try:
        r = requests.post(
            f"{ITEMSATIS_API_URL}/orders/{order_id}/message",
            headers={
                "Authorization": f"Bearer {ITEMSATIS_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"message": message},
            timeout=30,
        )

        if r.status_code == 200:
            log("success", "customer_notified", order_id=order_id)
            return True
        else:
            log("warning", "customer_notify_failed", order_id=order_id, status=r.status_code, response=r.text[:200])
            return False

    except Exception as e:
        log("error", "customer_notify_error", order_id=order_id, error=str(e))
        return False


def notify_customer_order_started(order_id: str, product_name: str, link: str):
    """Sipariş panele girilince müşteriye bildirim gönder."""
    message = (
        f"Merhaba! '{product_name}' siparişiniz alındı ve işleme girdi.\n\n"
        f"Hesabınız: {link}\n\n"
        f"Siparişiniz genellikle 0-24 saat içinde tamamlanmaya başlar. "
        f"Herhangi bir sorun olursa bize ulaşabilirsiniz. Teşekkürler."
    )
    return send_itemsatis_message(order_id, message)


def notify_customer_order_completed(order_id: str, product_name: str, link: str):
    """Sipariş tamamlanınca müşteriye bildirim gönder."""
    message = (
        f"Merhaba! '{product_name}' siparişiniz tamamlandı! 🎉\n\n"
        f"Hesabınız: {link}\n\n"
        f"Memnun kaldıysanız değerlendirme bırakırsanız çok seviniriz. "
        f"Tekrar alışveriş için görüşmek üzere."
    )
    return send_itemsatis_message(order_id, message)


def notify_customer_order_failed(order_id: str, product_name: str):
    """Sipariş başarısız olunca müşteriye bildirim gönder."""
    message = (
        f"Merhaba! '{product_name}' siparişinizde teknik bir sorun yaşandı. "
        f"En kısa sürede çözüp siparişinizi işleme alacağız. "
        f"Rahatsızlık için özür dileriz."
    )
    return send_itemsatis_message(order_id, message)


# ─── REDIS ────────────────────────────────────────────────────────────────────
def redis_request(command):
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None

    try:
        r = requests.post(
            UPSTASH_REDIS_REST_URL,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            json=command,
            timeout=20,
        )
        return r.json()
    except Exception as e:
        try:
            logger.error("redis_error", error=str(e))
        except Exception:
            print("REDIS ERROR:", str(e), flush=True)
        return None


def redis_get_json(key, default):
    result = redis_request(["GET", key])
    try:
        value = result.get("result") if result else None
        if not value:
            return default
        return json.loads(value)
    except Exception:
        return default


def redis_set_json(key, value):
    redis_request(["SET", key, json.dumps(value, ensure_ascii=False)])



def sanitize_pending_order(item: dict) -> dict:
    """API cevaplarında ve Redis kayıtlarında panel API key sızmasını engeller."""
    if not isinstance(item, dict):
        return {}
    clean = dict(item)
    clean.pop("api_key", None)
    return clean


def sanitize_pending_orders_for_storage():
    global PENDING_ORDERS
    PENDING_ORDERS = [sanitize_pending_order(item) for item in PENDING_ORDERS if isinstance(item, dict)]


def get_runtime_service_for_pending(item: dict) -> dict:
    """Pending sipariş için panel API bilgilerini güvenli şekilde yeniden oluşturur."""
    advert_id = str((item or {}).get("advert_id", ""))
    raw_service = get_all_services(include_inactive=True).get(advert_id, {}) if advert_id else {}
    service = get_service_config(raw_service) if raw_service else {}

    if not service:
        panel_key = (item or {}).get("panel_key") or (item or {}).get("panel")
        panel = get_panel_config(panel_key)
        service = {
            "panel_key": panel.get("key", ""),
            "panel": panel.get("name", (item or {}).get("panel", "")),
            "api_url": panel.get("api_url", ""),
            "api_key": panel.get("api_key", ""),
            "service_id": (item or {}).get("service_id", ""),
            "quantity": (item or {}).get("quantity", ""),
            "platform": (item or {}).get("platform", ""),
        }

    # Eski kayıtlarda api_url duruyorsa ama api_key yoksa panelden tamamlanır.
    if not service.get("api_url"):
        service["api_url"] = (item or {}).get("api_url", "")
    return service

def load_state():
    global PROCESSED_ORDERS, PROCESSED_LINKS, FAILED_ORDERS, PENDING_ORDERS
    global DAILY_STATS, LAST_DAILY_REPORT_DATE, SERVICE_PRICE_CACHE
    global WEEKLY_STATS, MONTHLY_STATS, LAST_WEEKLY_REPORT_DATE, LAST_MONTHLY_REPORT_DATE
    global RECORDED_SALES, LOG_HISTORY, PRODUCT_NAME_CACHE, PANEL_SERVICE_NAME_CACHE, DYNAMIC_SERVICES, PACKAGE_CONFIGS, SALES_HISTORY, ORDER_HISTORY, BLACKLIST

    RECORDED_SALES = set(redis_get_json("recorded_sales", []))
    PROCESSED_ORDERS = set(redis_get_json("processed_orders", []))
    PROCESSED_LINKS = set(redis_get_json("processed_links", []))
    FAILED_ORDERS = redis_get_json("failed_orders", [])
    PENDING_ORDERS = redis_get_json("pending_orders", [])
    sanitize_pending_orders_for_storage()
    DAILY_STATS = redis_get_json("daily_stats", {})
    LAST_DAILY_REPORT_DATE = redis_get_json("last_daily_report_date", "")
    SERVICE_PRICE_CACHE = redis_get_json("service_price_cache", {})
    WEEKLY_STATS = redis_get_json("weekly_stats", {})
    MONTHLY_STATS = redis_get_json("monthly_stats", {})
    LAST_WEEKLY_REPORT_DATE = redis_get_json("last_weekly_report_date", "")
    LAST_MONTHLY_REPORT_DATE = redis_get_json("last_monthly_report_date", "")
    LOG_HISTORY = redis_get_json("log_history", [])
    PRODUCT_NAME_CACHE = redis_get_json("product_name_cache", {})
    PANEL_SERVICE_NAME_CACHE = redis_get_json("panel_service_name_cache", {})
    DYNAMIC_SERVICES = redis_get_json("dynamic_services", {})
    PACKAGE_CONFIGS = redis_get_json("package_configs", {})
    SALES_HISTORY = redis_get_json("sales_history", {})
    ORDER_HISTORY = redis_get_json("order_history", [])
    BLACKLIST = set(redis_get_json("blacklist", []))

    log("info", "state_loaded", pending=len(PENDING_ORDERS), failed=len(FAILED_ORDERS))


def save_state():
    with STATE_LOCK:
        sanitize_pending_orders_for_storage()
        redis_set_json("recorded_sales", list(RECORDED_SALES))
        redis_set_json("processed_orders", list(PROCESSED_ORDERS))
        redis_set_json("processed_links", list(PROCESSED_LINKS))
        redis_set_json("failed_orders", FAILED_ORDERS)
        redis_set_json("pending_orders", PENDING_ORDERS)
        redis_set_json("daily_stats", DAILY_STATS)
        redis_set_json("last_daily_report_date", LAST_DAILY_REPORT_DATE)
        redis_set_json("service_price_cache", SERVICE_PRICE_CACHE)
        redis_set_json("weekly_stats", WEEKLY_STATS)
        redis_set_json("monthly_stats", MONTHLY_STATS)
        redis_set_json("last_weekly_report_date", LAST_WEEKLY_REPORT_DATE)
        redis_set_json("last_monthly_report_date", LAST_MONTHLY_REPORT_DATE)
        redis_set_json("product_name_cache", PRODUCT_NAME_CACHE)
        redis_set_json("panel_service_name_cache", PANEL_SERVICE_NAME_CACHE)
        redis_set_json("dynamic_services", DYNAMIC_SERVICES)
        redis_set_json("package_configs", PACKAGE_CONFIGS)
        redis_set_json("sales_history", SALES_HISTORY)
        redis_set_json("order_history", ORDER_HISTORY[-500:])
        redis_set_json("blacklist", list(BLACKLIST))
        flush_logs(force=True)


# ─── YARDIMCI FONKSİYONLAR ────────────────────────────────────────────────────
def normalize_text(text: str) -> str:
    return str(text or "").lower().strip()


def normalize_instagram_link(link: str) -> str:
    link = str(link or "").strip()
    if not link:
        return ""
    if link.startswith("@"):
        link = f"https://www.instagram.com/{link[1:]}"
    if not link.startswith("http"):
        if "instagram.com" not in link:
            link = f"https://www.instagram.com/{link.lstrip('@')}"
        else:
            link = "https://" + link

    # Sadece Instagram için soru işaretinden sonrasını temizle.
    # YouTube/TikTok/X gibi platformlarda ?v= veya benzeri kısımlar linkin parçası olabilir.
    link = link.split("?")[0]
    link = link.rstrip("/")
    return link


def normalize_panel_link(link: str, platform: str = "") -> str:
    link = str(link or "").strip()
    platform = normalize_text(platform)

    if not link:
        return ""

    if platform == "instagram":
        return normalize_instagram_link(link)

    # Instagram dışındaki tüm platformlarda linki panele aynen gönder.
    return link


def normalize_link_for_check(link: str, platform: str = "") -> str:
    platform = normalize_text(platform)
    check_link = normalize_panel_link(link, platform)
    return (
        check_link
        .lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .rstrip("/")
    )


def make_order_key(order_id, advert_id, buyer, link="", platform=""):
    if order_id and str(order_id) != "Bilinmiyor":
        return f"order:{order_id}"
    return f"fallback:{advert_id}:{buyer}:{normalize_link_for_check(link, platform)}"


def make_sale_key(data, order_id, advert_id, buyer, product_name, price, link=""):
    if order_id and str(order_id) != "Bilinmiyor":
        return f"sale_order:{order_id}"
    try:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(data)
    fingerprint = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    safe_link = normalize_link_for_check(link)
    return f"sale_fallback:{advert_id}:{buyer}:{product_name}:{price}:{safe_link}:{fingerprint}"


def add_failed_order(order_id, advert_id, product_name, reason, detail="", **extra):
    """Başarısız siparişi kaydeder. Retry için güvenli alanlar extra ile eklenebilir."""
    entry = {
        "order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "reason": str(reason),
        "detail": str(detail),
        "created_at": int(time.time()),
    }

    for key, value in extra.items():
        if value not in [None, ""]:
            entry[key] = value

    with STATE_LOCK:
        FAILED_ORDERS.append(entry)
        if len(FAILED_ORDERS) > 50:
            FAILED_ORDERS.pop(0)

        log(
            "error",
            "order_failed",
            order_id=order_id,
            reason=reason,
            product=product_name,
            smm_order_id=extra.get("smm_order_id", ""),
            panel=extra.get("panel", ""),
        )
        save_state()


def parse_price_value(value) -> float:
    """TL/TRY/₺ formatındaki fiyatları güvenli şekilde float'a çevirir."""
    try:
        if value is None:
            return 0.0

        text = str(value or "").strip()
        if not text:
            return 0.0

        # Öncelik: içinde para birimi olan değerler. Örn: "39.90 TL", "1.250,50 TL"
        money_match = re.search(
            r"(\d{1,3}(?:[.\s]\d{3})*(?:[,\.]\d{1,2})|\d+(?:[,\.]\d{1,2})?)\s*(?:TL|TRY|₺)",
            text,
            re.IGNORECASE,
        )
        if money_match:
            text = money_match.group(1)
        else:
            # Para birimi yoksa sadece doğrudan sayı gibi görünen alanları kabul et.
            # Böylece "Kalan stok sayısı: 71" gibi metinlerden fiyat sanıp değer çekmeyiz.
            if not re.fullmatch(r"\s*\d+(?:[,\.]\d{1,2})?\s*", text):
                return 0.0

        text = text.replace("TL", "").replace("TRY", "").replace("₺", "")
        text = text.replace("tl", "").replace("try", "")
        text = text.replace(" ", "").strip()

        # TR formatı: 1.250,50 -> 1250.50
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")

        text = re.sub(r"[^0-9.]", "", text)
        if not text:
            return 0.0

        return float(text)
    except Exception:
        return 0.0


def find_price_recursive(obj) -> float:
    """Itemsatış farklı JSON/string formatları gönderdiğinde fiyatı tüm payload içinde arar."""
    price_keys = {
        "price", "total", "amount", "total_price", "order_price", "sale_price",
        "paid_price", "payment_amount", "product_price", "advert_price",
        "earning", "seller_earning", "cost", "fee", "subtotal",
    }

    if isinstance(obj, dict):
        # Önce güvenilir fiyat alanları.
        for key, value in obj.items():
            key_lower = str(key).lower()
            if key_lower in price_keys or "price" in key_lower or "amount" in key_lower or "total" in key_lower:
                parsed = parse_price_value(value)
                if parsed > 0:
                    return parsed

        # Sonra nested alanlar ve raw/content içindeki "39.90 TL" gibi metinler.
        for value in obj.values():
            nested = find_price_recursive(value)
            if nested > 0:
                return nested

    elif isinstance(obj, list):
        for item in obj:
            nested = find_price_recursive(item)
            if nested > 0:
                return nested

    elif isinstance(obj, str):
        return parse_price_value(obj)

    return 0.0


def get_order_price(data: dict) -> float:
    value = get_nested(
        data,
        "price", "total", "amount", "total_price", "order_price",
        "sale_price", "paid_price", "payment_amount", "product_price",
        "advert.price", "advert.amount", "advert.total", "advert.sale_price",
        "details.price", "details.total", "details.amount", "details.total_price",
        "details.order_price", "details.sale_price", "details.paid_price", "details.payment_amount",
        "details.advert.price", "details.advert.amount", "details.advert.total",
        "data.price", "data.total", "data.amount", "data.total_price",
        "data.order_price", "data.sale_price", "data.paid_price", "data.payment_amount",
        "data.advert.price", "data.advert.amount", "data.advert.total",
        "payment.price", "payment.total", "payment.amount", "payment.total_price", "payment.paid_price",
        "data.payment.price", "data.payment.total", "data.payment.amount",
        "details.payment.price", "details.payment.total", "details.payment.amount",
    )

    parsed = parse_price_value(value)
    if parsed > 0:
        return parsed

    return find_price_recursive(data)


def normalize_stat_item(value):
    if isinstance(value, dict):
        return {
            "count": int(value.get("count", 0) or 0),
            "gross": float(value.get("gross", 0) or 0),
        }
    try:
        return {"count": int(value or 0), "gross": 0.0}
    except Exception:
        return {"count": 0, "gross": 0.0}


def add_sales_history(price: float = 0):
    """Dashboard grafiği için günlük satış geçmişini tutar."""
    global SALES_HISTORY
    today = now_tr().strftime("%Y-%m-%d")
    item = SALES_HISTORY.get(today, {})
    try:
        count = int(item.get("count", 0) or 0)
        gross = float(item.get("gross", 0) or 0)
    except Exception:
        count = 0
        gross = 0.0

    SALES_HISTORY[today] = {
        "count": count + 1,
        "gross": gross + float(price or 0),
    }

    # Eski verileri şişirmemek için son 90 günü tut.
    try:
        keep_from = (now_tr() - timedelta(days=90)).strftime("%Y-%m-%d")
        SALES_HISTORY = {k: v for k, v in SALES_HISTORY.items() if str(k) >= keep_from}
    except Exception:
        pass


def add_daily_stat(product_name: str, price: float = 0):
    global DAILY_STATS, WEEKLY_STATS, MONTHLY_STATS
    product_name = str(product_name or "Bilinmeyen Ürün").strip() or "Bilinmeyen Ürün"

    def add_to(stats):
        stats[product_name] = normalize_stat_item(stats.get(product_name, {}))
        stats[product_name]["count"] += 1
        stats[product_name]["gross"] += float(price or 0)

    with STATE_LOCK:
        add_to(DAILY_STATS)
        add_to(WEEKLY_STATS)
        add_to(MONTHLY_STATS)
        add_sales_history(price)
        save_state()


def record_itemsatis_sale(data, order_id, advert_id, buyer, product_name, price, link="") -> bool:
    global RECORDED_SALES
    sale_key = make_sale_key(data, order_id, advert_id, buyer, product_name, price, link)
    with STATE_LOCK:
        if sale_key in RECORDED_SALES:
            return False
        add_daily_stat(product_name, price)
        RECORDED_SALES.add(sale_key)
        save_state()
    return True


def is_blacklisted(value: str) -> bool:
    value = str(value or "").lower().strip()
    if not value:
        return False
    return value in BLACKLIST or any(str(item).lower().strip() and str(item).lower().strip() in value for item in BLACKLIST)


def blacklist_add(value: str):
    value = str(value or "").lower().strip()
    if value:
        with STATE_LOCK:
            BLACKLIST.add(value)
            save_state()


def blacklist_remove(value: str):
    value = str(value or "").lower().strip()
    with STATE_LOCK:
        BLACKLIST.discard(value)
        save_state()


def add_order_history(order_id, advert_id, product_name, panel, smm_order_id, link, price=0):
    entry = {
        "order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "panel": str(panel),
        "smm_order_id": str(smm_order_id),
        "link": str(link),
        "price": float(price or 0),
        "completed_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with STATE_LOCK:
        ORDER_HISTORY.append(entry)
        if len(ORDER_HISTORY) > 500:
            del ORDER_HISTORY[:-500]
        save_state()


def calculate_profit(sale_tl: float, cost_tl: float) -> dict:
    sale_tl = float(sale_tl or 0)
    cost_tl = float(cost_tl or 0)
    commission = sale_tl * ITEMSATIS_COMMISSION_RATE
    net_sale = sale_tl - commission
    profit = net_sale - cost_tl
    margin_pct = (profit / sale_tl * 100) if sale_tl > 0 else 0
    return {
        "sale_price": sale_tl,
        "commission": commission,
        "net_sale": net_sale,
        "panel_cost": cost_tl,
        "profit": profit,
        "margin_pct": round(margin_pct, 2),
    }


def build_sales_report(title: str, stats: dict, empty_text: str):
    lines = [f"{title}\n"]
    total_count = 0
    gross_total = 0.0

    if stats:
        normalized_items = []
        for product_name, raw_value in stats.items():
            item = normalize_stat_item(raw_value)
            count = item["count"]
            gross = item["gross"]
            if count <= 0:
                continue
            normalized_items.append((product_name, count, gross))
            total_count += count
            gross_total += gross

        normalized_items.sort(key=lambda x: x[1], reverse=True)
        if normalized_items:
            for product_name, count, gross in normalized_items:
                if gross > 0:
                    lines.append(f"{product_name} | {count}x | {gross:.2f} TL")
                else:
                    lines.append(f"{product_name} | {count}x")
        else:
            lines.append(empty_text)
    else:
        lines.append(empty_text)

    commission = gross_total * ITEMSATIS_COMMISSION_RATE
    net_total = gross_total - commission
    lines.append(f"\nToplam Sipariş: {total_count}")
    if gross_total > 0:
        lines.append(f"Brüt Kazanç: {gross_total:.2f} TL")
        lines.append(f"Itemsatış Komisyonu (%7): {commission:.2f} TL")
        lines.append(f"Net Kazanç: {net_total:.2f} TL")
    else:
        lines.append("Kazanç: Tutar bilgisi gelmediği için hesaplanamadı.")

    lines.append(f"Başarısız Sipariş: {len(FAILED_ORDERS)}")
    lines.append(f"Bekleyen SMM Sipariş: {len(PENDING_ORDERS)}")
    return "\n".join(lines)


def reset_sales_stats(scope: str = "daily"):
    global DAILY_STATS, WEEKLY_STATS, MONTHLY_STATS, RECORDED_SALES, SALES_HISTORY
    scope = str(scope or "daily").lower().strip()
    now = now_tr()

    with STATE_LOCK:
        if scope == "daily":
            DAILY_STATS = {}
            SALES_HISTORY.pop(now.strftime("%Y-%m-%d"), None)
        elif scope == "weekly":
            WEEKLY_STATS = {}
            week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            SALES_HISTORY = {k: v for k, v in SALES_HISTORY.items() if str(k) < week_start}
        elif scope in ["monthly", "current_month"]:
            # Mevcut ayı komple temizler. Dashboard bugünkü kartları da sıfırlansın diye
            # günlük/haftalık sayaçlar da temizlenir.
            DAILY_STATS = {}
            WEEKLY_STATS = {}
            MONTHLY_STATS = {}
            month_start = now.replace(day=1).strftime("%Y-%m-%d")
            SALES_HISTORY = {k: v for k, v in SALES_HISTORY.items() if str(k) < month_start}
        elif scope == "all":
            DAILY_STATS = {}
            WEEKLY_STATS = {}
            MONTHLY_STATS = {}
            SALES_HISTORY = {}
            RECORDED_SALES = set()
        else:
            return False
        save_state()
    return True


def add_pending_order(
    order_id,
    advert_id,
    product_name,
    panel,
    api_url,
    api_key,
    smm_order_id,
    link,
    service_id="",
    quantity="",
    platform="",
    panel_key="",
    price=0,
):
    if not smm_order_id or str(smm_order_id) == "Bilinmiyor":
        return
    if any(str(item.get("smm_order_id")) == str(smm_order_id) for item in PENDING_ORDERS):
        return
    with STATE_LOCK:
        PENDING_ORDERS.append({
            "itemsatis_order_id": str(order_id),
            "advert_id": str(advert_id),
            "product_name": str(product_name),
            "panel": str(panel),
            "panel_key": str(panel_key),
            "api_url": str(api_url),
            "service_id": str(service_id),
            "quantity": int(quantity or 0) if str(quantity or "").isdigit() else quantity,
            "platform": str(platform),
            "smm_order_id": str(smm_order_id),
            "link": str(link),
            "created_at": int(time.time()),
            "delay_alert_sent": False,
            "cancelled": False,
            "price": float(price or 0),
        })
        log("info", "order_queued", order_id=order_id, smm_order_id=smm_order_id, product=product_name)
        save_state()


def get_lzt_links() -> str:
    return """
LZT arama linkleri:

1) 5 years medal:
https://lzt.market/steam/?order_by=price_to_up&title=5%20years%20medal

2) CS2 5 years:
https://lzt.market/steam/?order_by=price_to_up&title=cs2%205%20years

3) CS2 medal:
https://lzt.market/steam/?order_by=price_to_up&title=cs2%20medal
"""


def get_nested(data: dict, *paths):
    for path in paths:
        current = data
        ok = True
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                ok = False
                break
        if ok and current not in [None, ""]:
            return current
    return ""


def parse_embedded_itemsatis_payload(data: dict) -> dict:
    """Itemsatış bazen asıl payload'u raw/raw_body içinde Python dict stringi olarak gönderir."""
    if not isinstance(data, dict):
        return {}
    for key in ["raw", "raw_body", "body", "payload"]:
        raw_value = data.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        raw_text = raw_value.strip()
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(raw_text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def payload_variants(data: dict):
    """Önce ana payload, sonra varsa raw içindeki gömülü payload'u döndürür."""
    yield data
    embedded = parse_embedded_itemsatis_payload(data)
    if embedded:
        yield embedded


def extract_product_name_from_content(text: str) -> str:
    """'... başlıklı ilanınız 39.90 TL...' metninden gerçek ilan adını çeker."""
    text = str(text or "").strip()
    if not text:
        return ""
    patterns = [
        r"^(.*?)\s+başlıklı\s+ilanınız\s+",
        r"^(.*?)\s+baslikli\s+ilaniniz\s+",
        r"^(.*?)\s+başlıklı\s+ilaniniz\s+",
        r"^(.*?)\s+baslikli\s+ilanınız\s+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .:-|\n\t")
            if candidate and not is_generic_itemsatis_title(candidate):
                return candidate
    return ""


def get_event(data: dict) -> str:
    for payload in payload_variants(data):
        event = normalize_text(get_nested(payload, "event", "type", "action", "details.event", "data.event"))
        if event:
            return event
    return ""


def is_generic_itemsatis_title(value: str) -> bool:
    """Itemsatış webhooklarında gerçek ilan adı yerine gelen genel başlıkları filtreler."""
    text = normalize_text(value)
    generic_values = {
        "ilanınız satıldı",
        "ilaniniz satildi",
        "advert sold",
        "advert_sold",
        "satıldı",
        "satildi",
        "order sold",
        "sipariş",
        "siparis",
    }
    return text in generic_values


def get_order_id(data: dict) -> str:
    for payload in payload_variants(data):
        value = get_nested(
            payload,
            "order_id", "id", "purchaseId", "purchase_id", "sale_id", "transaction_id",
            "order.id", "order.order_id", "order.purchase_id",
            "purchase.id", "purchase.order_id", "purchase.purchase_id",
            "data.order_id", "data.id", "data.purchaseId", "data.purchase_id", "data.order.id",
            "details.order_id", "details.id", "details.purchaseId", "details.purchase_id", "details.order.id",
        )
        if value:
            return str(value)
    return "Bilinmiyor"


def get_advert_id(data: dict) -> str:
    for payload in payload_variants(data):
        value = get_nested(
            payload,
            "advert.id", "details.advert.id", "data.advert.id",
            "advert_id", "details.advert_id", "data.advert_id",
            "advertId", "advert_id", "ilan_id", "ilan.id",
        )
        if value:
            return str(value)
    return ""


def get_product_name(data: dict) -> str:
    """Itemsatış ilan adını mümkün olan tüm alanlardan yakalar; genel webhook başlıklarını ürün adı sanmaz."""
    candidate_paths = [
        "advert.title", "advert.name", "advert.subject",
        "details.advert.title", "details.advert.name", "details.advert.subject",
        "data.advert.title", "data.advert.name", "data.advert.subject",
        "order.advert.title", "order.advert.name", "order.advert.subject",
        "purchase.advert.title", "purchase.advert.name", "purchase.advert.subject",
        "product_name", "product.title", "product.name",
        "details.product_name", "details.product.title", "details.product.name",
        "data.product_name", "data.product.title", "data.product.name",
        "order.product_name", "order.product.title", "order.product.name",
        "purchase.product_name", "purchase.product.title", "purchase.product.name",
        "content", "details.content", "data.content",
        "title", "name", "details.title", "data.title",
    ]

    for payload in payload_variants(data):
        for path in candidate_paths:
            value = get_nested(payload, path)
            if isinstance(value, dict):
                value = value.get("title") or value.get("name") or value.get("subject") or value.get("content") or ""
            value = str(value or "").strip()
            if not value:
                continue
            from_content = extract_product_name_from_content(value)
            if from_content:
                return from_content
            if value and not is_generic_itemsatis_title(value):
                return value

    # Son çare: tüm stringlerde "başlıklı ilanınız" kalıbını ara.
    for text in collect_strings(data):
        from_content = extract_product_name_from_content(text)
        if from_content:
            return from_content

    return ""


def cache_itemsatis_product_name(advert_id: str, product_name: str):
    """Webhook ile gelen ilan adını kaydeder; raporlarda Itemsatış ilan adı kullanılmasını sağlar."""
    global PRODUCT_NAME_CACHE
    advert_id = str(advert_id or "").strip()
    product_name = str(product_name or "").strip()
    if advert_id and product_name:
        PRODUCT_NAME_CACHE[advert_id] = product_name
        redis_set_json("product_name_cache", PRODUCT_NAME_CACHE)


def get_itemsatis_report_name(advert_id: str, product_name: str = "") -> str:
    """Rapor için gerçek Itemsatış ilan adını kullanır; genel webhook başlığını kullanmaz."""
    product_name = str(product_name or "").strip()
    if product_name and not is_generic_itemsatis_title(product_name):
        cache_itemsatis_product_name(advert_id, product_name)
        return product_name

    cached_name = str(PRODUCT_NAME_CACHE.get(str(advert_id or ""), "")).strip()
    if cached_name and not is_generic_itemsatis_title(cached_name):
        return cached_name

    service = get_all_services(include_inactive=True).get(str(advert_id or ""), {})
    configured_name = str((service or {}).get("name") or "").strip()
    if configured_name and not is_generic_itemsatis_title(configured_name):
        return configured_name

    if str(advert_id or "") == CS2_ADVERT_ID:
        return "CS2 5 Yıllık Hesap"

    if advert_id:
        return f"Itemsatış İlanı {advert_id}"

    return "Bilinmeyen Ürün"


def get_buyer(data: dict) -> str:
    for payload in payload_variants(data):
        buyer = get_nested(
            payload,
            "buyer", "buyer.username", "buyer.name", "buyer.user_name",
            "customer", "customer.username", "customer.name", "customer.user_name",
            "user", "user.username", "user.name",
            "details.buyer", "details.buyer.username", "details.buyer.name",
            "details.customer", "details.customer.username", "details.customer.name",
            "data.buyer", "data.buyer.username", "data.buyer.name",
            "data.customer", "data.customer.username", "data.customer.name",
            "order.buyer", "order.buyer.username", "order.customer.username",
        )
        if isinstance(buyer, dict):
            buyer = buyer.get("username") or buyer.get("name") or buyer.get("user_name") or buyer.get("id") or ""
        buyer = str(buyer or "").strip()
        if buyer and not is_generic_itemsatis_title(buyer):
            return buyer
    return "Bilinmiyor"


def collect_strings(obj, results=None):
    if results is None:
        results = []
    if isinstance(obj, dict):
        for value in obj.values():
            collect_strings(value, results)
    elif isinstance(obj, list):
        for value in obj:
            collect_strings(value, results)
    elif isinstance(obj, str):
        results.append(obj)
    return results


def find_order_link(data: dict, platform: str = "") -> str:
    platform = normalize_text(platform)

    priority_paths = [
        "post_datas.Profil Linki",
        "post_datas.Link",
        "post_datas.Video Linki",
        "post_datas.Gönderi Linki",
        "post_datas.Kanal Linki",
        "details.post_datas.Profil Linki",
        "details.post_datas.Link",
        "details.post_datas.Video Linki",
        "details.post_datas.Gönderi Linki",
        "details.post_datas.Kanal Linki",
        "data.post_datas.Profil Linki",
        "data.post_datas.Link",
        "data.post_datas.Video Linki",
        "data.post_datas.Gönderi Linki",
        "data.post_datas.Kanal Linki",
        "url", "link", "profile_link", "account_link", "video_link", "post_link",
        "instagram", "instagram_link", "tiktok", "tiktok_link", "youtube", "youtube_link",
        "note", "message", "content", "description", "order_note", "customer_note",
        "details.url", "details.link", "details.note", "details.message", "details.content", "details.description",
        "data.url", "data.link", "data.note", "data.message", "data.content", "data.description",
    ]

    platform_domains = {
        "instagram": ["instagram.com"],
        "tiktok": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
        "youtube": ["youtube.com", "youtu.be"],
        "x": ["x.com", "twitter.com"],
        "twitter": ["x.com", "twitter.com"],
        "twitch": ["twitch.tv"],
        "kick": ["kick.com"],
        "facebook": ["facebook.com", "fb.watch"],
        "telegram": ["t.me", "telegram.me"],
    }

    def looks_like_link(value: str) -> bool:
        v = str(value or "").strip().lower()
        if not v:
            return False
        if platform == "instagram" and v.startswith("@"):
            return True
        if v.startswith("http://") or v.startswith("https://"):
            return True
        domains = platform_domains.get(platform, [])
        if domains and any(domain in v for domain in domains):
            return True
        if not domains and "." in v and " " not in v:
            return True
        return False

    for path in priority_paths:
        value = get_nested(data, path)
        if isinstance(value, str) and looks_like_link(value):
            return normalize_panel_link(value, platform)

    all_strings = collect_strings(data)
    joined = "\n".join(all_strings)

    if platform == "instagram":
        match = re.search(r"(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._/\-?=&%]+", joined, re.IGNORECASE)
        if match:
            return normalize_panel_link(match.group(0), platform)
        for text in all_strings:
            text = text.strip()
            if text.startswith("@") and len(text) > 2:
                return normalize_panel_link(text, platform)
        return ""

    # Genel link yakalama: YouTube/TikTok vb. linklerin ? sonrasını KESMEZ.
    match = re.search(r"https?://[^\s<>'\"]+", joined, re.IGNORECASE)
    if match:
        return normalize_panel_link(match.group(0), platform)

    domains = platform_domains.get(platform, [])
    if domains:
        domain_pattern = "|".join(re.escape(d) for d in domains)
        match = re.search(rf"(?:www\.)?(?:{domain_pattern})/[^\s<>'\"]+", joined, re.IGNORECASE)
        if match:
            value = match.group(0)
            if not value.startswith("http"):
                value = "https://" + value
            return normalize_panel_link(value, platform)

    return ""


def find_instagram_link(data: dict) -> str:
    return find_order_link(data, "instagram")

def normalize_panel_key(panel_key: str) -> str:
    key = normalize_text(panel_key).replace(" ", "").replace("-", "")
    return PANEL_ALIASES.get(key, key)


def get_panel_config(panel_key: str) -> dict:
    key = normalize_panel_key(panel_key)
    panel = PANEL_MAP.get(key, {})
    return {
        "key": key,
        "name": panel.get("name", key or "Bilinmeyen Panel"),
        "api_url": panel.get("api_url", ""),
        "api_key": panel.get("api_key", ""),
    }


def get_service_config(service_or_advert_id) -> dict:
    if isinstance(service_or_advert_id, str):
        raw_service = SMM_SERVICE_MAP.get(service_or_advert_id, {})
    else:
        raw_service = service_or_advert_id or {}

    service = dict(raw_service)
    panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
    panel = get_panel_config(panel_key)

    service["panel_key"] = panel_key
    service["panel"] = panel["name"]
    service["api_url"] = service.get("api_url") or panel["api_url"]
    service["api_key"] = service.get("api_key") or panel["api_key"]
    service["platform"] = normalize_text(service.get("platform", "instagram")) or "general"
    return service


def get_service_name(service: dict, advert_id: str = "", product_name: str = "") -> str:
    """Öncelik Itemsatış ilan adı. SMM_SERVICE_MAP içinde name zorunlu değil."""
    name = str(product_name or "").strip()
    if name:
        return name
    name = str((service or {}).get("name") or "").strip()
    if name:
        return name
    if str(advert_id or "") == CS2_ADVERT_ID:
        return "CS2 5 Yıllık Hesap"
    if advert_id:
        return f"Itemsatış İlanı {advert_id}"
    return "Bilinmeyen Ürün"


def extract_panel_service_name(service_item: dict) -> str:
    """Panelin services cevabından servis adını yakalar."""
    if not isinstance(service_item, dict):
        return ""

    for key in ["name", "service_name", "title", "service_title", "description"]:
        value = service_item.get(key)
        if value not in [None, ""]:
            return str(value).strip()

    return ""


def make_panel_service_cache_key(panel_key: str, service_id: str) -> str:
    return f"{normalize_panel_key(panel_key)}:{str(service_id or '').strip()}"


def cache_panel_service_name(panel_key: str, service_id: str, service_name: str):
    """Panel servis ID -> panel servis adı eşleşmesini Redis'e kaydeder."""
    global PANEL_SERVICE_NAME_CACHE
    service_name = str(service_name or "").strip()
    service_id = str(service_id or "").strip()
    if not service_id or not service_name:
        return

    cache_key = make_panel_service_cache_key(panel_key, service_id)
    PANEL_SERVICE_NAME_CACHE[cache_key] = service_name
    redis_set_json("panel_service_name_cache", PANEL_SERVICE_NAME_CACHE)


def get_cached_panel_service_name(panel_key: str, service_id: str) -> str:
    cache_key = make_panel_service_cache_key(panel_key, service_id)
    return str(PANEL_SERVICE_NAME_CACHE.get(cache_key, "")).strip()


def get_panel_service_display_name(service: dict, target_service: dict = None) -> str:
    """Fiyat/servis kontrollerinde Itemsatış adı yerine paneldeki gerçek servis adını gösterir."""
    panel_key = (service or {}).get("panel_key") or (service or {}).get("panel") or ""
    service_id = str((service or {}).get("service_id") or "").strip()

    panel_service_name = extract_panel_service_name(target_service or {})
    if panel_service_name:
        cache_panel_service_name(panel_key, service_id, panel_service_name)
        return panel_service_name

    cached_name = get_cached_panel_service_name(panel_key, service_id)
    if cached_name:
        return cached_name

    if service_id:
        return f"Panel Servisi {service_id}"

    return "Bilinmeyen Panel Servisi"



def fetch_panel_service_name_by_id(panel_key: str, service_id: str) -> str:
    """Panel services listesinden verilen servis ID'nin gerçek servis adını çeker ve cache'ler."""
    panel_key = normalize_panel_key(panel_key)
    service_id = str(service_id or "").strip()
    if not panel_key or not service_id:
        return ""

    cached = get_cached_panel_service_name(panel_key, service_id)
    if cached:
        return cached

    panel = get_panel_config(panel_key)
    if not panel.get("api_url") or not panel.get("api_key"):
        return ""

    services_data = get_panel_services(panel["api_url"], panel["api_key"], panel.get("name", panel_key))
    if isinstance(services_data, dict) and "error" in services_data:
        log("warning", "manual_service_name_fetch_failed", panel=panel_key, service_id=service_id, error=services_data.get("error"))
        return ""

    if not isinstance(services_data, list):
        return ""

    for item in services_data:
        if str(item.get("service")) == service_id:
            service_name = get_panel_service_display_name(
                {"panel_key": panel_key, "panel": panel.get("name"), "service_id": service_id},
                item,
            )
            if service_name and not service_name.startswith("Panel Servisi"):
                return service_name
            return extract_panel_service_name(item) or ""

    return ""


def normalize_dynamic_service(advert_id: str, service: dict) -> dict:
    """Admin panelden gelen servis kaydını güvenli formata çevirir."""
    advert_id = str(advert_id or "").strip()
    service = dict(service or {})
    panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
    platform = normalize_text(service.get("platform") or "instagram") or "instagram"

    try:
        quantity = int(service.get("quantity") or 0)
    except Exception:
        quantity = 0

    return {
        "advert_id": advert_id,
        "panel": panel_key,
        "panel_key": panel_key,
        "service_id": str(service.get("service_id") or "").strip(),
        "quantity": quantity,
        "platform": platform,
        "active": bool(service.get("active", True)),
        "source": service.get("source") or "dynamic",
        "created_at": service.get("created_at") or int(time.time()),
    }


def get_dynamic_services() -> dict:
    """Redis'teki dinamik servisleri temizleyerek döndürür."""
    cleaned = {}
    for advert_id, service in (DYNAMIC_SERVICES or {}).items():
        advert_id = str(advert_id or "").strip()
        if not advert_id:
            continue
        normalized = normalize_dynamic_service(advert_id, service)
        if normalized.get("panel") and normalized.get("service_id") and normalized.get("quantity") > 0:
            cleaned[advert_id] = normalized
    return cleaned


def get_all_services(include_inactive: bool = False) -> dict:
    """Kod içindeki servislerle /admin üzerinden eklenen dinamik servisleri birleştirir."""
    services = {}
    for advert_id, service in SMM_SERVICE_MAP.items():
        item = dict(service or {})
        item.setdefault("active", True)
        item.setdefault("source", "code")
        services[str(advert_id)] = item

    for advert_id, service in get_dynamic_services().items():
        services[str(advert_id)] = service

    if include_inactive:
        return services

    return {
        advert_id: service
        for advert_id, service in services.items()
        if bool(service.get("active", True))
    }


def save_dynamic_services():
    redis_set_json("dynamic_services", DYNAMIC_SERVICES)
    redis_set_json("sales_history", SALES_HISTORY)


def set_dynamic_service(advert_id: str, panel: str, service_id: str, quantity: int, platform: str, active: bool = True):
    global DYNAMIC_SERVICES
    advert_id = str(advert_id or "").strip()
    if not advert_id:
        raise ValueError("Itemsatış ilan ID boş olamaz")

    panel_key = normalize_panel_key(panel)
    if panel_key not in PANEL_MAP:
        raise ValueError("Panel bulunamadı")

    if not advert_id.isdigit():
        raise ValueError("Itemsatış ilan ID sadece rakam olmalı")

    service_id = str(service_id or "").strip()
    if not service_id:
        raise ValueError("Panel servis ID boş olamaz")
    if not service_id.isdigit():
        raise ValueError("Panel servis ID sadece rakam olmalı")

    quantity = int(quantity or 0)
    if quantity <= 0:
        raise ValueError("Adet 0'dan büyük olmalı")
    if quantity > 1000000:
        raise ValueError("Adet en fazla 1.000.000 olabilir")

    DYNAMIC_SERVICES[advert_id] = normalize_dynamic_service(
        advert_id,
        {
            "panel": panel_key,
            "service_id": service_id,
            "quantity": quantity,
            "platform": platform,
            "active": active,
            "source": "dynamic",
            "created_at": int(time.time()),
        },
    )
    save_dynamic_services()
    return DYNAMIC_SERVICES[advert_id]


def delete_dynamic_service(advert_id: str) -> bool:
    global DYNAMIC_SERVICES
    advert_id = str(advert_id or "").strip()
    if advert_id in DYNAMIC_SERVICES:
        DYNAMIC_SERVICES.pop(advert_id, None)
        save_dynamic_services()
        return True
    return False


def toggle_dynamic_service(advert_id: str) -> bool:
    global DYNAMIC_SERVICES
    advert_id = str(advert_id or "").strip()
    if advert_id not in DYNAMIC_SERVICES:
        return False
    current = bool(DYNAMIC_SERVICES[advert_id].get("active", True))
    DYNAMIC_SERVICES[advert_id]["active"] = not current
    save_dynamic_services()
    return True




def normalize_package_component(component: dict) -> dict:
    component = dict(component or {})
    panel_key = normalize_panel_key(component.get("panel_key") or component.get("panel") or "")
    platform = normalize_text(component.get("platform") or "tiktok") or "tiktok"
    try:
        quantity = int(component.get("quantity") or 0)
    except Exception:
        quantity = 0
    component_id = str(component.get("id") or component.get("component_id") or f"cmp_{int(time.time() * 1000)}")
    return {
        "id": component_id,
        "name": str(component.get("name") or component.get("type") or "Paket Bileşeni").strip() or "Paket Bileşeni",
        "panel": panel_key,
        "panel_key": panel_key,
        "service_id": str(component.get("service_id") or "").strip(),
        "quantity": quantity,
        "platform": platform,
        "active": bool(component.get("active", True)),
    }


def normalize_package_config(advert_id: str, package: dict) -> dict:
    advert_id = str(advert_id or "").strip()
    package = dict(package or {})
    platform = normalize_text(package.get("platform") or "tiktok") or "tiktok"
    components = []
    for component in package.get("components", []) or []:
        normalized = normalize_package_component(component)
        if normalized.get("panel") and normalized.get("service_id") and normalized.get("quantity", 0) > 0:
            components.append(normalized)
    return {
        "advert_id": advert_id,
        "name": str(package.get("name") or "").strip(),
        "platform": platform,
        "active": bool(package.get("active", True)),
        "components": components,
        "source": "package",
        "created_at": package.get("created_at") or int(time.time()),
    }


def get_package_configs(include_inactive: bool = False) -> dict:
    cleaned = {}
    for advert_id, package in (PACKAGE_CONFIGS or {}).items():
        advert_id = str(advert_id or "").strip()
        if not advert_id:
            continue
        normalized = normalize_package_config(advert_id, package)
        if normalized.get("components") and (include_inactive or normalized.get("active", True)):
            cleaned[advert_id] = normalized
    return cleaned


def save_package_configs():
    redis_set_json("package_configs", PACKAGE_CONFIGS)


def set_package(advert_id: str, name: str, platform: str = "tiktok", active: bool = True):
    global PACKAGE_CONFIGS
    advert_id = str(advert_id or "").strip()
    if not advert_id or not advert_id.isdigit():
        raise ValueError("Itemsatış ilan ID sadece rakam olmalı")
    existing = normalize_package_config(advert_id, PACKAGE_CONFIGS.get(advert_id, {}))
    PACKAGE_CONFIGS[advert_id] = {
        "advert_id": advert_id,
        "name": str(name or existing.get("name") or f"Paket {advert_id}").strip(),
        "platform": normalize_text(platform or existing.get("platform") or "tiktok") or "tiktok",
        "active": active,
        "components": existing.get("components", []),
        "source": "package",
        "created_at": existing.get("created_at") or int(time.time()),
    }
    save_package_configs()
    return PACKAGE_CONFIGS[advert_id]


def delete_package(advert_id: str) -> bool:
    global PACKAGE_CONFIGS
    advert_id = str(advert_id or "").strip()
    if advert_id in PACKAGE_CONFIGS:
        PACKAGE_CONFIGS.pop(advert_id, None)
        save_package_configs()
        return True
    return False


def toggle_package(advert_id: str) -> bool:
    advert_id = str(advert_id or "").strip()
    if advert_id not in PACKAGE_CONFIGS:
        return False
    current = bool(PACKAGE_CONFIGS[advert_id].get("active", True))
    PACKAGE_CONFIGS[advert_id]["active"] = not current
    save_package_configs()
    return True


def add_package_component(advert_id: str, name: str, panel: str, service_id: str, quantity: int, platform: str):
    advert_id = str(advert_id or "").strip()
    if advert_id not in PACKAGE_CONFIGS:
        raise ValueError("Önce paketi oluşturmalısın")
    panel_key = normalize_panel_key(panel)
    if panel_key not in PANEL_MAP:
        raise ValueError("Panel bulunamadı")
    service_id = str(service_id or "").strip()
    if not service_id.isdigit():
        raise ValueError("Servis ID sadece rakam olmalı")
    quantity = int(quantity or 0)
    if quantity <= 0 or quantity > 1000000:
        raise ValueError("Adet 1 ile 1.000.000 arasında olmalı")
    component = normalize_package_component({
        "id": f"cmp_{int(time.time() * 1000)}",
        "name": name or "Paket Bileşeni",
        "panel": panel_key,
        "service_id": service_id,
        "quantity": quantity,
        "platform": platform,
        "active": True,
    })
    PACKAGE_CONFIGS[advert_id].setdefault("components", []).append(component)
    save_package_configs()
    return component


def delete_package_component(advert_id: str, component_id: str) -> bool:
    advert_id = str(advert_id or "").strip()
    component_id = str(component_id or "").strip()
    if advert_id not in PACKAGE_CONFIGS:
        return False
    components = PACKAGE_CONFIGS[advert_id].get("components", []) or []
    new_components = [c for c in components if str(c.get("id")) != component_id]
    if len(new_components) == len(components):
        return False
    PACKAGE_CONFIGS[advert_id]["components"] = new_components
    save_package_configs()
    return True


def get_package_display_name(advert_id: str, package: dict, product_name: str = "") -> str:
    name = str(product_name or "").strip()
    if name and not is_generic_title(name):
        return name
    name = str((package or {}).get("name") or "").strip()
    if name:
        return name
    return f"Paket İlanı {advert_id}"

def build_services_list_text() -> str:
    services = get_all_services(include_inactive=True)
    if not services:
        return "Aktif servis kaydı yok."

    lines = ["Servis Eşleştirmeleri:\n"]
    for advert_id, raw_service in sorted(services.items(), key=lambda x: x[0]):
        service = get_service_config(raw_service)
        source = raw_service.get("source", "code")
        active = "Aktif" if raw_service.get("active", True) else "Pasif"
        lines.append(
            f"{advert_id} | {active} | {source} | {service['panel']} | "
            f"Servis ID: {service.get('service_id')} | Adet: {service.get('quantity')} | Platform: {service.get('platform')}"
        )
    return "\n".join(lines)


def is_panel_configured(panel_key: str) -> bool:
    panel = get_panel_config(panel_key)
    return bool(panel.get("api_url") and panel.get("api_key"))


def panel_status_line(panel_key: str) -> str:
    panel = get_panel_config(panel_key)
    configured = "Aktif" if is_panel_configured(panel_key) else "Eksik"
    api_url = panel.get("api_url") or "API URL yok"
    return f"{panel['key']} | {panel['name']} | {configured} | {api_url}"


def build_panels_list_text() -> str:
    lines = ["Ekli Paneller:\n"]
    for key in PANEL_MAP.keys():
        lines.append(panel_status_line(key))
    lines.append("\nBakiye için: /balance paneladi")
    lines.append("Örnek: /balance lionfollow")
    lines.append("Tüm bakiyeler: /balance-all")
    return "\n".join(lines)



def parse_numeric_balance(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        text = str(value).strip()
        text = text.replace("TL", "").replace("₺", "").replace("TRY", "")
        text = text.replace("USD", "").replace("$", "").strip()
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        text = re.sub(r"[^0-9.\-]", "", text)
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def get_usd_to_try_rate() -> float:
    """USD bakiyeleri TL göstermek için güncel kura yakın değeri döndürür.
    Önce cache kullanır, sonra ücretsiz kur API'lerinden çekmeyi dener.
    API başarısız olursa env'deki USD_TO_TRY_RATE fallback olarak kullanılır.
    """
    now_ts = int(time.time())

    try:
        cached_rate = float(USD_TO_TRY_CACHE.get("rate") or 0)
        updated_at = int(USD_TO_TRY_CACHE.get("updated_at") or 0)
        if cached_rate > 0 and updated_at and (now_ts - updated_at) < USD_TO_TRY_REFRESH_SECONDS:
            return cached_rate
    except Exception:
        pass

    urls = [
        "https://open.er-api.com/v6/latest/USD",
        "https://api.frankfurter.app/latest?from=USD&to=TRY",
    ]

    for url in urls:
        try:
            r = requests.get(url, timeout=10, headers=HEADERS)
            data = r.json()

            rate = None
            if isinstance(data, dict):
                rates = data.get("rates") or {}
                rate = rates.get("TRY")

            if rate:
                rate = float(rate)
                if rate > 0:
                    USD_TO_TRY_CACHE["rate"] = rate
                    USD_TO_TRY_CACHE["updated_at"] = now_ts
                    return rate
        except Exception as e:
            log("warning", "usd_try_rate_fetch_failed", url=url, error=str(e))

    return float(os.getenv("USD_TO_TRY_RATE", USD_TO_TRY_RATE))


def convert_balance_to_try(balance, currency="") -> float | None:
    numeric_balance = parse_numeric_balance(balance)
    if numeric_balance is None:
        return None
    cur = str(currency or "").upper().strip()
    if cur in ["USD", "USDT", "$"]:
        return numeric_balance * get_usd_to_try_rate()
    return numeric_balance


def get_balance_currency_label(currency="") -> str:
    cur = str(currency or "").upper().strip()
    if cur in ["USD", "USDT", "$"]:
        return f"USD kuru: {get_usd_to_try_rate():.2f} TL"
    return ""


def format_tl_amount(value) -> str:
    try:
        return f"{float(value):.2f} TL"
    except Exception:
        return "Bilinmiyor"


def format_panel_balance_tl(balance_data: dict) -> str:
    if not isinstance(balance_data, dict):
        return "Bilinmiyor"
    balance = balance_data.get("balance", "Bilinmiyor")
    currency = balance_data.get("currency", "")
    balance_tl = convert_balance_to_try(balance, currency)
    if balance_tl is None:
        return "Bilinmiyor"
    return format_tl_amount(balance_tl)

def build_all_panel_balances_text() -> str:
    lines = ["Panel Bakiyeleri:\n"]
    used_usd_rate = False
    for key in PANEL_MAP.keys():
        panel = get_panel_config(key)
        if not is_panel_configured(key):
            lines.append(f"{panel['name']}: Eksik env")
            continue
        balance_data = panel_balance(panel["api_url"], panel["api_key"], panel.get("name", key))
        if "error" in balance_data:
            lines.append(f"{panel['name']}: Hatalı - {balance_data.get('error')}")
        else:
            if get_balance_currency_label(balance_data.get("currency", "")):
                used_usd_rate = True
            lines.append(f"{panel['name']}: {format_panel_balance_tl(balance_data)}")
    if used_usd_rate:
        lines.append(f"\n{get_balance_currency_label('USD')}")
    return "\n".join(lines)


def handle_panel_balance_command(text: str):
    parts = text.strip().split(maxsplit=1)
    panel_key = "all" if len(parts) == 1 else parts[1].strip()

    if normalize_text(panel_key) in ["all", "hepsi", "tümü", "tum"]:
        send_telegram(build_all_panel_balances_text())
        return

    panel = get_panel_config(panel_key)
    if panel["key"] not in PANEL_MAP:
        send_telegram(f"Panel bulunamadı: {panel_key}\n\nPanelleri görmek için: /panels")
        return

    if not is_panel_configured(panel["key"]):
        send_telegram(
            f"{panel['name']} panel bilgileri eksik.\n\n"
            f"Render Environment içine API URL ve API KEY eklenmeli.\n"
            f"Panelleri görmek için: /panels"
        )
        return

    balance_data = panel_balance(panel["api_url"], panel["api_key"])
    if "error" in balance_data:
        send_telegram(f"{panel['name']} bakiye alınamadı.\n\nHata: {balance_data.get('error')}")
        return

    currency_note = get_balance_currency_label(balance_data.get("currency", ""))
    extra = f"\n{currency_note}" if currency_note else ""
    send_telegram(
        f"{panel['name']} Bakiyesi:\n\n"
        f"Bakiye: {format_panel_balance_tl(balance_data)}{extra}"
    )


def _panel_api_request(api_url, api_key, action, extra_data=None, panel_name="", timeout=30):
    """Panel API çağrılarını tek yerden yapar.
    balance/status/services gibi güvenli okuma çağrılarında kısa retry uygular.
    add action otomatik retry yapmaz; çift sipariş riskini önler.
    """
    if not api_url or not api_key:
        return {"error": "API URL veya API KEY eksik"}

    payload = {"key": api_key, "action": action}
    if extra_data:
        payload.update(extra_data)

    max_attempts = 1 if action == "add" else max(1, PANEL_SAFE_RETRY_COUNT)
    last_error = None

    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            r = requests.post(api_url, data=payload, headers=HEADERS, timeout=timeout)
            elapsed = time.perf_counter() - started
            level = "warning" if elapsed >= SLOW_API_THRESHOLD_SECONDS else "info"
            log(
                level,
                "panel_api_performance",
                panel=panel_name or api_url,
                action=action,
                duration=f"{elapsed:.2f}s",
                status_code=r.status_code,
                attempt=attempt,
            )

            # 5xx panel hatalarında güvenli okuma işlemlerini tekrar deneyebiliriz.
            if action != "add" and r.status_code >= 500 and attempt < max_attempts:
                last_error = f"HTTP {r.status_code}"
                time.sleep(PANEL_RETRY_SLEEP_SECONDS)
                continue

            try:
                result = r.json()
            except Exception:
                result = {"error": f"Panel {action} JSON cevap vermedi", "raw": r.text[:300]}

            if isinstance(result, dict):
                result.setdefault("_duration", elapsed)
                result.setdefault("_attempt", attempt)
            return result

        except requests.exceptions.Timeout as e:
            elapsed = time.perf_counter() - started
            last_error = f"timeout: {e}"
            log(
                "warning",
                "panel_api_timeout",
                panel=panel_name or api_url,
                action=action,
                duration=f"{elapsed:.2f}s",
                attempt=attempt,
            )
            if action != "add" and attempt < max_attempts:
                time.sleep(PANEL_RETRY_SLEEP_SECONDS)
                continue
            return {"error": last_error, "duration": elapsed, "attempt": attempt}

        except Exception as e:
            elapsed = time.perf_counter() - started
            last_error = str(e)
            log(
                "error",
                "panel_api_error",
                panel=panel_name or api_url,
                action=action,
                duration=f"{elapsed:.2f}s",
                attempt=attempt,
                error=str(e),
            )
            if action != "add" and attempt < max_attempts:
                time.sleep(PANEL_RETRY_SLEEP_SECONDS)
                continue
            return {"error": str(e), "duration": elapsed, "attempt": attempt}

    return {"error": last_error or "Panel API isteği başarısız"}

def panel_balance(api_url, api_key, panel_name=""):
    return _panel_api_request(api_url, api_key, "balance", panel_name=panel_name)


def create_panel_order(api_url, api_key, service_id, link, quantity, panel_name=""):
    return _panel_api_request(
        api_url,
        api_key,
        "add",
        extra_data={"service": service_id, "link": link, "quantity": quantity},
        panel_name=panel_name,
    )


def check_panel_order_status(api_url, api_key, order_id, panel_name=""):
    if not order_id:
        return {"error": "Status için order ID eksik"}
    return _panel_api_request(
        api_url,
        api_key,
        "status",
        extra_data={"order": order_id},
        panel_name=panel_name,
    )


def get_panel_services(api_url, api_key, panel_name=""):
    return _panel_api_request(api_url, api_key, "services", panel_name=panel_name)


def check_low_balance(balance, currency, panel_name="Panel"):
    try:
        balance_tl = convert_balance_to_try(balance, currency)
        if balance_tl is None:
            return
        if balance_tl <= 100:
            log("warning", "low_balance", panel=panel_name, balance=balance, currency=currency, balance_tl=balance_tl)
            send_telegram(f"{panel_name} bakiyesi 100 TL altına düştü.\n\nKalan: {format_tl_amount(balance_tl)}\n\nLütfen kontrol et.")
    except Exception as e:
        log("error", "balance_check_error", error=str(e))



async def background_scheduler():
    """Render açık kaldığı sürece sipariş ve servis kontrollerini otomatik çalıştırır."""
    await asyncio.sleep(30)
    while True:
        try:
            log("info", "background_check_orders_start")
            check_orders()
        except Exception as e:
            log("error", "background_check_orders_error", error=str(e))

        try:
            log("info", "background_check_services_start")
            check_services()
        except Exception as e:
            log("error", "background_check_services_error", error=str(e))

        await asyncio.sleep(300)


@app.on_event("startup")
async def startup_event():
    validate_environment()
    asyncio.create_task(background_scheduler())


load_state()



# ─── ADMIN SERVİS YÖNETİM PANELİ ──────────────────────────────────────────────
def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not ADMIN_PASSWORD or ADMIN_PASSWORD == "changeme":
        log("error", "admin_locked", reason="ADMIN_PASSWORD güvenli ayarlanmamış")
        raise HTTPException(
            status_code=503,
            detail="Admin panel kilitli. Render Environment içinde ADMIN_PASSWORD ayarla.",
            headers={"WWW-Authenticate": "Basic"},
        )

    correct_username = secrets.compare_digest(credentials.username or "", ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password or "", ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


ADMIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Admin</title>
<link rel="icon" type="image/png" href="/static/favicon.png?v=3">
<link rel="shortcut icon" href="/static/favicon.png?v=3">
<style>
body { font-family: Arial, sans-serif; background:#0a0a0f; color:#e2e8f0; margin:0; padding:24px; }
.container { max-width:1180px; margin:auto; background:#111118; border:1px solid #1e1e2e; border-radius:14px; padding:24px; }
h1 { margin:0 0 6px; color:#fff; } .muted { color:#8a8fa3; font-size:13px; margin-bottom:22px; }
form.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:22px; }
input, select, button { padding:11px; border-radius:8px; border:1px solid #2a2a3a; background:#181824; color:#e2e8f0; font-size:14px; }
input:focus, select:focus { border-color:#7c3aed; outline:none; }
button { background:#7c3aed; border:none; cursor:pointer; font-weight:700; transition:background .2s; }
button:hover { background:#5b27b1; }
button.delete { background:#ef4444; } button.delete:hover { background:#dc2626; }
button.toggle { background:#334155; } button.green { background:#16a34a; } button.green:hover { background:#15803d; }
table { width:100%; border-collapse:collapse; overflow:hidden; border-radius:10px; }
th, td { padding:12px; border-bottom:1px solid #242436; text-align:left; font-size:14px; }
th { background:#181824; color:#a8adbd; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
.badge { padding:4px 8px; border-radius:99px; font-size:12px; font-weight:700; }
.active { background:#064e3b; color:#86efac; } .passive { background:#3f1d1d; color:#fca5a5; }
a { color:#a78bfa; text-decoration:none; } .actions form { display:inline; }
.notice { background:#172554; color:#bfdbfe; padding:10px 12px; border-radius:8px; margin-bottom:14px; font-size:13px; }
.service-name { max-width:360px; white-space:normal; line-height:1.35; color:#dbeafe; }
.service-name.missing { color:#8a8fa3; font-style:italic; }
.toolbar { display:flex; flex-wrap:wrap; gap:10px; margin:18px 0 22px; align-items:center; }
@media (max-width: 900px) {
  body { padding: 12px; }
  .container { padding: 16px; border-radius: 12px; }
  h1 { font-size: 24px; }
  .toolbar { display:grid; grid-template-columns:1fr; gap:8px; }
  .toolbar a, .toolbar form, .toolbar button { width:100%; }
  form.grid { grid-template-columns: 1fr !important; gap:10px; }
  input, select, button { width:100%; min-height:44px; font-size:16px; }
  table { font-size:12px; display:block; overflow-x:auto; white-space:nowrap; -webkit-overflow-scrolling:touch; }
  th, td { padding:10px 9px; }
  .service-name { max-width:220px; }
  .actions form { display:block; margin:4px 0; }
}
@media (max-width: 520px) {
  body { padding: 8px; }
  .container { padding: 12px; }
  .muted, .notice { font-size:12px; line-height:1.45; }
  .badge { display:inline-block; margin-top:4px; }
}
</style>
</head>
<body>
<div class="container">
<h1>Boostera Admin</h1>
<div class="muted">API key girilmez. API keyler Render Environment içinde kalır. Buradan sadece Itemsatış ilanını panel servisine bağlarsın.</div>
<div class="notice">Yeni servis ekleme: Itemsatış İlan ID + Panel + Panel Servis ID + Adet + Platform. İlan adı raporlarda Itemsatış webhookundan otomatik alınır.</div>

<div class="toolbar">
  <a href="/"><button type="button">Dashboard</button></a>
  <a href="/admin/pending-orders"><button type="button">Bekleyen Siparişler</button></a>
  <a href="/admin/failed-orders"><button type="button">Başarısız Siparişler</button></a>
  <a href="/admin/manual-order"><button type="button">Manuel SMM Sipariş</button></a>
  <a href="/admin/packages"><button type="button">Paketler</button></a>
  <form method="post" action="/admin/update-service-names" style="display:inline;">
    <button class="green" type="submit">Servis İsimlerini Güncelle</button>
  </form>
  <form method="post" action="/admin/update-services" style="display:inline;">
    <button class="green" type="submit">Servis Fiyatlarını Kontrol Et</button>
  </form>
  <form method="post" action="/admin/reset-dashboard" style="display:inline;" onsubmit="return confirm('Bu ayın dashboard ve rapor verileri sıfırlansın mı?')">
    <button class="delete" type="submit">Bu Ayı Sıfırla</button>
  </form>
</div>

<form class="grid" method="post" action="/admin/add-service">
  <input name="advert_id" placeholder="Itemsatış İlan ID" pattern="^\\d+$" title="Sadece rakam giriniz" required maxlength="20" oninvalid="this.setCustomValidity('Lütfen geçerli bir İlan ID giriniz. Sadece rakam olmalı.')" oninput="setCustomValidity('')">
  <select name="panel" required>
    {% for key, panel in panels.items() %}
      <option value="{{ key|e }}">{{ panel.name|e }} ({{ key|e }})</option>
    {% endfor %}
  </select>
  <input name="service_id" placeholder="Panel Servis ID" pattern="^\\d+$" title="Sadece rakam giriniz" required maxlength="20" oninvalid="this.setCustomValidity('Lütfen geçerli bir Servis ID giriniz. Sadece rakam olmalı.')" oninput="setCustomValidity('')">
  <input name="quantity" type="number" min="1" max="1000000" placeholder="Adet" required oninvalid="this.setCustomValidity('Lütfen 1 ile 1.000.000 arasında bir adet giriniz')" oninput="setCustomValidity('')">
  <select name="platform" required>
    <option value="instagram">Instagram</option>
    <option value="tiktok">TikTok</option>
    <option value="youtube">YouTube</option>
    <option value="x">X/Twitter</option>
    <option value="twitch">Twitch</option>
    <option value="kick">Kick</option>
    <option value="other">Diğer</option>
  </select>
  <button type="submit">Ekle / Güncelle</button>
</form>
<script>
document.querySelector('form.grid').addEventListener('submit', function(event) {
  if (!this.checkValidity()) {
    event.preventDefault();
    alert('Formda hatalı veya eksik alanlar var. Lütfen düzeltin.');
  }
});
</script>

<table>
<thead><tr><th>İlan ID</th><th>Panel</th><th>Servis ID</th><th>Panel Servis Adı</th><th>Adet</th><th>Platform</th><th>Durum</th><th>Kaynak</th><th>İşlem</th></tr></thead>
<tbody>
{% for advert_id, service in services.items() %}
<tr>
<td>{{ advert_id|e }}</td>
<td>{{ service.panel|e }}</td>
<td>{{ service.service_id|e }}</td>
<td class="service-name {{ 'missing' if not service.panel_service_name else '' }}">{{ service.panel_service_name or 'Güncellenmedi' }}</td>
<td>{{ service.quantity|e }}</td>
<td>{{ service.platform|e }}</td>
<td><span class="badge {{ 'active' if service.active else 'passive' }}">{{ 'Aktif' if service.active else 'Pasif' }}</span></td>
<td>{{ service.source }}</td>
<td class="actions">
  {% if service.source == 'dynamic' %}
  <form method="post" action="/admin/toggle-service"><input type="hidden" name="advert_id" value="{{ advert_id|e }}"><button class="toggle" type="submit">Aktif/Pasif</button></form>
  <form method="post" action="/admin/delete-service" onsubmit="return confirm('Silinsin mi?')"><input type="hidden" name="advert_id" value="{{ advert_id|e }}"><button class="delete" type="submit">Sil</button></form>
  {% else %}
  Kod içi servis
  {% endif %}
</td>
</tr>
{% else %}
<tr><td colspan="9" style="text-align:center;color:#8a8fa3;">Servis yok.</td></tr>
{% endfor %}
</tbody>
</table>
</div>
</body>
</html>
"""


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(user: str = Depends(get_current_admin)):
    template = Template(ADMIN_HTML)
    services = {}
    for advert_id, raw_service in get_all_services(include_inactive=True).items():
        service = get_service_config(raw_service)
        panel_key = service.get("panel_key") or raw_service.get("panel") or ""
        service_id = str(service.get("service_id") or "")
        services[advert_id] = {
            "panel": service.get("panel"),
            "service_id": service_id,
            "panel_service_name": get_cached_panel_service_name(panel_key, service_id),
            "quantity": service.get("quantity"),
            "platform": service.get("platform"),
            "active": bool(raw_service.get("active", True)),
            "source": raw_service.get("source", "code"),
        }
    html = template.render(services=services, panels=PANEL_MAP)
    return HTMLResponse(content=html)


@app.post("/admin/add-service")
def admin_add_service(
    advert_id: str = Form(...),
    panel: str = Form(...),
    service_id: str = Form(...),
    quantity: int = Form(...),
    platform: str = Form("instagram"),
    user: str = Depends(get_current_admin),
):
    try:
        set_dynamic_service(advert_id, panel, service_id, quantity, platform, True)
        log("success", "admin_service_saved", advert_id=advert_id, panel=panel, service_id=service_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/delete-service")
def admin_delete_service(advert_id: str = Form(...), user: str = Depends(get_current_admin)):
    removed = delete_dynamic_service(advert_id)
    if removed:
        log("warning", "admin_service_deleted", advert_id=advert_id)
    else:
        log("warning", "admin_service_delete_skipped", advert_id=advert_id, reason="dynamic_service_not_found")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/toggle-service")
def admin_toggle_service(advert_id: str = Form(...), user: str = Depends(get_current_admin)):
    toggle_dynamic_service(advert_id)
    log("info", "admin_service_toggled", advert_id=advert_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/update-services")
def admin_update_services(user: str = Depends(get_current_admin)):
    """Admin panelden servis fiyat kontrolünü manuel başlatır."""
    check_services()
    return RedirectResponse("/admin", status_code=303)


def refresh_panel_service_names() -> dict:
    """Kayıtlı servislerin paneldeki gerçek servis adlarını çekip cache'e kaydeder."""
    updated = 0
    missing = 0
    checked = 0
    services_by_panel = {}

    for advert_id, raw_service in get_all_services(include_inactive=True).items():
        service = get_service_config(raw_service)
        panel_key = service.get("panel_key") or raw_service.get("panel") or ""
        service_id = str(service.get("service_id") or "").strip()
        if not panel_key or not service_id:
            continue
        services_by_panel.setdefault(panel_key, []).append((advert_id, service_id, service))

    for package_advert_id, package in get_package_configs(include_inactive=True).items():
        for component in package.get("components", []) or []:
            component = normalize_package_component(component)
            panel_key = component.get("panel")
            service_id = str(component.get("service_id") or "").strip()
            if panel_key and service_id:
                services_by_panel.setdefault(panel_key, []).append((package_advert_id, service_id, component))

    for panel_key, rows in services_by_panel.items():
        panel = get_panel_config(panel_key)
        if not panel.get("api_url") or not panel.get("api_key"):
            missing += len(rows)
            continue

        services_data = get_panel_services(panel["api_url"], panel["api_key"], panel.get("name", panel_key))
        if isinstance(services_data, dict) and "error" in services_data:
            log("warning", "panel_service_names_fetch_failed", panel=panel_key, error=services_data.get("error"))
            missing += len(rows)
            continue
        if not isinstance(services_data, list):
            missing += len(rows)
            continue

        service_index = {str(item.get("service")): item for item in services_data if isinstance(item, dict)}
        for advert_id, service_id, service in rows:
            checked += 1
            item = service_index.get(service_id)
            service_name = extract_panel_service_name(item or {})
            if service_name:
                before = get_cached_panel_service_name(panel_key, service_id)
                cache_panel_service_name(panel_key, service_id, service_name)
                if before != service_name:
                    updated += 1
            else:
                missing += 1

    save_state()
    return {"checked": checked, "updated": updated, "missing": missing}


@app.post("/admin/update-service-names")
def admin_update_service_names(user: str = Depends(get_current_admin)):
    result = refresh_panel_service_names()
    log("info", "admin_service_names_updated", **result)
    send_telegram(
        "Servis isimleri güncellendi.\n\n"
        f"Kontrol edilen: {result.get('checked', 0)}\n"
        f"Güncellenen: {result.get('updated', 0)}\n"
        f"Bulunamayan: {result.get('missing', 0)}"
    )
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/reset-dashboard")
def admin_reset_dashboard(user: str = Depends(get_current_admin)):
    """Admin panelden mevcut ayın dashboard/rapor verisini sıfırlar."""
    reset_sales_stats("current_month")
    log("warning", "admin_month_dashboard_reset", user=user)
    return RedirectResponse("/admin", status_code=303)





ADMIN_PACKAGES_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Paketler</title>
<link rel="icon" type="image/png" href="/static/favicon.png?v=3">
<style>
body { font-family: Arial, sans-serif; background:#0a0a0f; color:#e2e8f0; margin:0; padding:24px; }
.container { max-width:1200px; margin:auto; background:#111118; border:1px solid #1e1e2e; border-radius:14px; padding:24px; }
h1 { margin:0 0 6px; color:#fff; } .muted { color:#8a8fa3; font-size:13px; margin-bottom:18px; }
form.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin:18px 0 22px; }
input, select, button { padding:11px; border-radius:8px; border:1px solid #2a2a3a; background:#181824; color:#e2e8f0; font-size:14px; }
button { background:#7c3aed; border:none; cursor:pointer; font-weight:700; } button:hover { background:#5b27b1; }
button.delete { background:#ef4444; } button.green { background:#16a34a; } button.toggle { background:#334155; }
table { width:100%; border-collapse:collapse; margin-top:12px; }
th, td { padding:10px; border-bottom:1px solid #242436; text-align:left; font-size:13px; vertical-align:top; }
th { background:#181824; color:#a8adbd; font-size:12px; text-transform:uppercase; }
.badge { padding:4px 8px; border-radius:99px; font-size:12px; font-weight:700; }
.active { background:#064e3b; color:#86efac; } .passive { background:#3f1d1d; color:#fca5a5; }
a { color:#a78bfa; text-decoration:none; } .actions form { display:inline; }
.notice { background:#172554; color:#bfdbfe; padding:10px 12px; border-radius:8px; margin-bottom:14px; font-size:13px; }
.component { background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:10px; margin:8px 0; }
.service-name { color:#dbeafe; font-size:12px; margin-top:4px; }
@media (max-width: 900px) {
  body { padding: 12px; }
  .container { padding: 16px; border-radius: 12px; }
  h1 { font-size:24px; }
  form.grid { grid-template-columns: 1fr !important; gap:10px; }
  input, select, button { width:100%; min-height:44px; font-size:16px; }
  table { display:block; overflow-x:auto; white-space:nowrap; -webkit-overflow-scrolling:touch; }
  th, td { padding:10px 9px; }
  .component { overflow-wrap:anywhere; }
  .actions form { display:block; margin:4px 0; }
}
@media (max-width: 520px) {
  body { padding:8px; }
  .container { padding:12px; }
  .muted, .notice { font-size:12px; line-height:1.45; }
}
</style>
</head>
<body><div class="container">
<h1>Boostera Paket Sistemi</h1>
<div class="muted">Tek Itemsatış ilanından birden fazla panel siparişi oluşturur. Aynı müşteri linki paket içindeki tüm bileşenlere gönderilir.</div>
<div class="notice">Örnek: TikTok paket ilanı → izlenme + beğeni + favori. Raporlarda tek satış sayılır, pending tarafında her SMM ID ayrı takip edilir.</div>
<p><a href="/admin">← Admin Paneline Dön</a></p>

<h2>Paket Oluştur / Güncelle</h2>
<form class="grid" method="post" action="/admin/packages/add">
  <input name="advert_id" placeholder="Itemsatış İlan ID" pattern="^\\d+$" required maxlength="20">
  <input name="name" placeholder="Paket adı (örn: TikTok Fenomen Paket)" required maxlength="120">
  <select name="platform" required>
    <option value="tiktok">TikTok</option>
    <option value="instagram">Instagram</option>
    <option value="youtube">YouTube</option>
    <option value="x">X/Twitter</option>
    <option value="twitch">Twitch</option>
    <option value="kick">Kick</option>
    <option value="other">Diğer</option>
  </select>
  <button type="submit">Paket Kaydet</button>
</form>

<h2>Paketler</h2>
<table>
<thead><tr><th>İlan ID</th><th>Paket</th><th>Platform</th><th>Durum</th><th>Bileşen Ekle</th><th>Bileşenler</th><th>İşlem</th></tr></thead>
<tbody>
{% for advert_id, package in packages.items() %}
<tr>
<td>{{ advert_id|e }}</td>
<td>{{ package.name|e }}</td>
<td>{{ package.platform|e }}</td>
<td><span class="badge {{ 'active' if package.active else 'passive' }}">{{ 'Aktif' if package.active else 'Pasif' }}</span></td>
<td>
  <form method="post" action="/admin/packages/add-component" style="min-width:330px;">
    <input type="hidden" name="advert_id" value="{{ advert_id|e }}">
    <input name="name" placeholder="Bileşen adı: İzlenme / Beğeni" required maxlength="80" style="width:100%;margin-bottom:6px;">
    <select name="panel" required style="width:100%;margin-bottom:6px;">
      {% for key, panel in panels.items() %}<option value="{{ key|e }}">{{ panel.name|e }} ({{ key|e }})</option>{% endfor %}
    </select>
    <input name="service_id" placeholder="Panel Servis ID" pattern="^\\d+$" required maxlength="20" style="width:100%;margin-bottom:6px;">
    <input name="quantity" type="number" min="1" max="1000000" placeholder="Adet" required style="width:100%;margin-bottom:6px;">
    <select name="platform" required style="width:100%;margin-bottom:6px;">
      <option value="{{ package.platform|e }}">Paket platformu: {{ package.platform|e }}</option>
      <option value="instagram">Instagram</option><option value="tiktok">TikTok</option><option value="youtube">YouTube</option><option value="x">X/Twitter</option><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="other">Diğer</option>
    </select>
    <button class="green" type="submit">Bileşen Ekle</button>
  </form>
</td>
<td>
  {% for comp in package.components %}
    <div class="component">
      <b>{{ comp.name|e }}</b><br>
      Panel: {{ comp.panel_name|e }} | ID: {{ comp.service_id|e }} | Adet: {{ comp.quantity|e }} | Platform: {{ comp.platform|e }}
      <div class="service-name">{{ comp.panel_service_name or 'Panel servis adı güncellenmedi' }}</div>
      <form method="post" action="/admin/packages/delete-component" onsubmit="return confirm('Bileşen silinsin mi?')" style="margin-top:6px;">
        <input type="hidden" name="advert_id" value="{{ advert_id|e }}">
        <input type="hidden" name="component_id" value="{{ comp.id|e }}">
        <button class="delete" type="submit">Bileşeni Sil</button>
      </form>
    </div>
  {% else %}
    <span style="color:#8a8fa3;">Bileşen yok.</span>
  {% endfor %}
</td>
<td class="actions">
  <form method="post" action="/admin/packages/toggle"><input type="hidden" name="advert_id" value="{{ advert_id|e }}"><button class="toggle" type="submit">Aktif/Pasif</button></form>
  <form method="post" action="/admin/packages/delete" onsubmit="return confirm('Paket tamamen silinsin mi?')"><input type="hidden" name="advert_id" value="{{ advert_id|e }}"><button class="delete" type="submit">Sil</button></form>
</td>
</tr>
{% else %}
<tr><td colspan="7" style="text-align:center;color:#8a8fa3;">Paket yok.</td></tr>
{% endfor %}
</tbody>
</table>
</div></body></html>
"""


def build_packages_for_admin() -> dict:
    packages = {}
    for advert_id, package in get_package_configs(include_inactive=True).items():
        row = dict(package)
        comps = []
        for comp in package.get("components", []) or []:
            comp = normalize_package_component(comp)
            panel_key = comp.get("panel")
            panel = get_panel_config(panel_key)
            comp_row = dict(comp)
            comp_row["panel_name"] = panel.get("name", panel_key)
            comp_row["panel_service_name"] = get_cached_panel_service_name(panel_key, comp.get("service_id"))
            comps.append(comp_row)
        row["components"] = comps
        packages[advert_id] = row
    return packages


@app.get("/admin/packages", response_class=HTMLResponse)
def admin_packages(user: str = Depends(get_current_admin)):
    template = Template(ADMIN_PACKAGES_HTML)
    return HTMLResponse(template.render(packages=build_packages_for_admin(), panels=PANEL_MAP))


@app.post("/admin/packages/add")
def admin_package_add(advert_id: str = Form(...), name: str = Form(...), platform: str = Form("tiktok"), user: str = Depends(get_current_admin)):
    try:
        set_package(advert_id, name, platform, True)
        log("success", "admin_package_saved", advert_id=advert_id, name=name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/admin/packages", status_code=303)


@app.post("/admin/packages/delete")
def admin_package_delete(advert_id: str = Form(...), user: str = Depends(get_current_admin)):
    delete_package(advert_id)
    log("warning", "admin_package_deleted", advert_id=advert_id)
    return RedirectResponse("/admin/packages", status_code=303)


@app.post("/admin/packages/toggle")
def admin_package_toggle(advert_id: str = Form(...), user: str = Depends(get_current_admin)):
    toggle_package(advert_id)
    log("info", "admin_package_toggled", advert_id=advert_id)
    return RedirectResponse("/admin/packages", status_code=303)


@app.post("/admin/packages/add-component")
def admin_package_add_component(
    advert_id: str = Form(...),
    name: str = Form(...),
    panel: str = Form(...),
    service_id: str = Form(...),
    quantity: int = Form(...),
    platform: str = Form("tiktok"),
    user: str = Depends(get_current_admin),
):
    try:
        comp = add_package_component(advert_id, name, panel, service_id, quantity, platform)
        panel_service_name = fetch_panel_service_name_by_id(panel, service_id)
        if panel_service_name:
            cache_panel_service_name(panel, service_id, panel_service_name)
        log("success", "admin_package_component_added", advert_id=advert_id, panel=panel, service_id=service_id, component=comp.get("name"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/admin/packages", status_code=303)


@app.post("/admin/packages/delete-component")
def admin_package_delete_component(advert_id: str = Form(...), component_id: str = Form(...), user: str = Depends(get_current_admin)):
    delete_package_component(advert_id, component_id)
    log("warning", "admin_package_component_deleted", advert_id=advert_id, component_id=component_id)
    return RedirectResponse("/admin/packages", status_code=303)

ADMIN_MANUAL_ORDER_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Manuel SMM Sipariş</title>
<link rel="icon" type="image/png" href="/static/favicon.png?v=3">
<link rel="shortcut icon" href="/static/favicon.png?v=3">
<style>
body { font-family: Arial, sans-serif; background:#0a0a0f; color:#e2e8f0; margin:0; padding:24px; }
.container { max-width:980px; margin:auto; background:#111118; border:1px solid #1e1e2e; border-radius:14px; padding:24px; }
h1 { margin:0 0 8px; } .muted { color:#8a8fa3; font-size:13px; margin-bottom:18px; line-height:1.5; }
a { color:#a78bfa; text-decoration:none; }
form.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin-top:18px; }
input, select, button, textarea { padding:11px; border-radius:8px; border:1px solid #2a2a3a; background:#181824; color:#e2e8f0; font-size:14px; }
textarea { grid-column:1/-1; min-height:72px; resize:vertical; }
input:focus, select:focus, textarea:focus { border-color:#7c3aed; outline:none; }
button { background:#7c3aed; border:none; cursor:pointer; font-weight:700; }
button:hover { background:#5b27b1; }
.notice { background:#172554; color:#bfdbfe; padding:10px 12px; border-radius:8px; margin-bottom:14px; font-size:13px; }
.service-name { max-width:360px; white-space:normal; line-height:1.35; color:#dbeafe; }
.service-name.missing { color:#8a8fa3; font-style:italic; }
.ok { background:#064e3b; color:#86efac; padding:10px 12px; border-radius:8px; margin-bottom:14px; }
.err { background:#3f1d1d; color:#fca5a5; padding:10px 12px; border-radius:8px; margin-bottom:14px; }
.full { grid-column:1/-1; }
label { display:flex; flex-direction:column; gap:6px; color:#a8adbd; font-size:12px; text-transform:uppercase; letter-spacing:.06em; }
small { color:#8a8fa3; text-transform:none; letter-spacing:0; font-size:12px; }

@media (max-width: 900px) {
  body { padding: 12px; }
  .container { padding: 16px; border-radius: 12px; }
  h1 { font-size:24px; }
  form.grid { grid-template-columns: 1fr !important; gap:10px; }
  textarea { min-height:96px; }
  input, select, button, textarea { width:100%; min-height:44px; font-size:16px; }
  label { font-size:11px; }
}
@media (max-width: 520px) {
  body { padding:8px; }
  .container { padding:12px; }
  .muted, .notice { font-size:12px; line-height:1.45; }
}
</style>
</head>
<body>
<div class="container">
<h1>Manuel SMM Sipariş</h1>
<div class="muted">Bu sayfa sadece senin kullanımın içindir. Panel panel dolaşmadan direkt Boostera üzerinden dış panele sipariş girer. Müşteri paneli değildir.</div>
<p><a href="/admin">← Admin Paneline Dön</a></p>
{% if message %}<div class="ok">{{ message|e }}</div>{% endif %}
{% if error %}<div class="err">{{ error|e }}</div>{% endif %}
<div class="notice">Servis adını boş bırakırsan bot seçtiğin paneldeki servis ID'den gerçek servis adını çekmeye çalışır.</div>
<form class="grid" method="post" action="/admin/manual-order">
  <label>Panel
    <select name="panel" required>
      {% for key, panel in panels.items() %}
        <option value="{{ key|e }}">{{ panel.name|e }} ({{ key|e }})</option>
      {% endfor %}
    </select>
  </label>
  <label>Panel Servis ID
    <input name="service_id" placeholder="Örn: 93" pattern="^\\d+$" title="Sadece rakam giriniz" required maxlength="20">
  </label>
  <label>Adet
    <input name="quantity" type="number" min="1" max="1000000" placeholder="Örn: 1000" required>
  </label>
  <label>Platform
    <select name="platform" required>
      <option value="instagram">Instagram</option>
      <option value="tiktok">TikTok</option>
      <option value="youtube">YouTube</option>
      <option value="x">X/Twitter</option>
      <option value="twitch">Twitch</option>
      <option value="kick">Kick</option>
      <option value="other">Diğer</option>
    </select>
  </label>
  <label class="full">Link
    <input name="link" placeholder="Müşteri/profil/video/gönderi linki" required maxlength="500">
    <small>Instagram seçiliyse link temizlenir, diğer platformlarda link olduğu gibi panele gider.</small>
  </label>
  <label class="full">Servis adı / not (opsiyonel)
    <input name="product_name" placeholder="Boş bırakırsan paneldeki servis adı çekilir" maxlength="180">
  </label>
  <button class="full" type="submit" onclick="return confirm('Bu sipariş seçilen dış panele gönderilecek. Devam edilsin mi?')">Siparişi Panele Gönder</button>
</form>
</div>
</body>
</html>
"""


@app.get("/admin/manual-order", response_class=HTMLResponse)
def admin_manual_order_page(
    message: str = "",
    error: str = "",
    user: str = Depends(get_current_admin),
):
    template = Template(ADMIN_MANUAL_ORDER_HTML)
    return HTMLResponse(content=template.render(panels=PANEL_MAP, message=message, error=error))


@app.post("/admin/manual-order")
def admin_manual_order_submit(
    panel: str = Form(...),
    service_id: str = Form(...),
    quantity: int = Form(...),
    platform: str = Form("other"),
    link: str = Form(...),
    product_name: str = Form(""),
    user: str = Depends(get_current_admin),
):
    panel_key = normalize_panel_key(panel)
    panel_conf = get_panel_config(panel_key)

    if panel_key not in PANEL_MAP:
        raise HTTPException(status_code=400, detail="Panel bulunamadı")
    if not panel_conf.get("api_url") or not panel_conf.get("api_key"):
        raise HTTPException(status_code=400, detail="Panel API URL veya API KEY eksik")

    service_id = str(service_id or "").strip()
    if not service_id.isdigit():
        raise HTTPException(status_code=400, detail="Panel servis ID sadece rakam olmalı")
    if quantity <= 0 or quantity > 1000000:
        raise HTTPException(status_code=400, detail="Adet 1 ile 1.000.000 arasında olmalı")

    raw_link = str(link or "").strip()
    if not raw_link:
        raise HTTPException(status_code=400, detail="Link boş olamaz")

    platform = normalize_text(platform or "other") or "other"
    panel_link = normalize_panel_link(raw_link, platform)

    if is_blacklisted(panel_link):
        raise HTTPException(status_code=400, detail="Bu link blacklist içinde")

    fetched_service_name = fetch_panel_service_name_by_id(panel_key, service_id)
    final_product_name = str(product_name or "").strip() or fetched_service_name or f"{panel_conf['name']} Servis {service_id}"

    smm_result = create_panel_order(
        panel_conf["api_url"],
        panel_conf["api_key"],
        service_id,
        panel_link,
        quantity,
        panel_conf.get("name", panel_key),
    )

    if "error" in smm_result:
        log("error", "manual_order_failed", panel=panel_key, service_id=service_id, error=smm_result.get("error"))
        raise HTTPException(status_code=400, detail=f"Panel sipariş hatası: {smm_result.get('error')}")

    smm_order_id = smm_result.get("order", "Bilinmiyor")
    manual_order_id = f"manual-{now_tr().strftime('%Y%m%d%H%M%S')}"
    manual_advert_id = f"manual-{panel_key}-{service_id}"

    add_pending_order(
        manual_order_id,
        manual_advert_id,
        final_product_name,
        panel_conf.get("name", panel_key),
        panel_conf["api_url"],
        panel_conf["api_key"],
        smm_order_id,
        panel_link,
        service_id=service_id,
        quantity=quantity,
        platform=platform,
        panel_key=panel_key,
        price=0,
    )

    log("success", "manual_order_created", panel=panel_key, service_id=service_id, smm_order_id=smm_order_id)
    send_telegram(
        f"Manuel SMM siparişi panele girildi.\n\n"
        f"Ürün: {final_product_name}\n"
        f"Panel: {panel_conf.get('name', panel_key)}\n"
        f"Servis ID: {service_id}\n"
        f"SMM ID: {smm_order_id}\n"
        f"Adet: {quantity}\n"
        f"Link: {panel_link}"
    )

    msg = f"Sipariş panele girildi. SMM ID: {smm_order_id}"
    return RedirectResponse(f"/admin/manual-order?message={msg}", status_code=303)


ADMIN_PENDING_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Bekleyen Siparişler</title>
<style>
body { font-family: Arial, sans-serif; background:#0a0a0f; color:#e2e8f0; margin:0; padding:24px; }
.container { max-width:1180px; margin:auto; background:#111118; border:1px solid #1e1e2e; border-radius:14px; padding:24px; }
h1 { margin:0 0 8px; } .muted { color:#8a8fa3; font-size:13px; margin-bottom:18px; }
a { color:#a78bfa; text-decoration:none; }
button { padding:8px 12px; border-radius:8px; border:none; background:#7c3aed; color:#fff; cursor:pointer; font-weight:700; }
button.delete { background:#ef4444; }
table { width:100%; border-collapse:collapse; margin-top:20px; }
th, td { padding:12px; border-bottom:1px solid #242436; text-align:left; font-size:14px; }
th { background:#181824; color:#a8adbd; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
.badge { padding:4px 8px; border-radius:99px; font-size:12px; font-weight:700; }
.active { background:#064e3b; color:#86efac; } .cancelled { background:#3f1d1d; color:#fca5a5; }
@media (max-width: 900px) {
  body { padding:12px; }
  .container { padding:16px; border-radius:12px; }
  h1 { font-size:24px; }
  table { display:block; overflow-x:auto; white-space:nowrap; -webkit-overflow-scrolling:touch; }
  th, td { padding:10px 9px; font-size:12px; }
  button { min-height:40px; width:100%; }
}
@media (max-width: 520px) {
  body { padding:8px; }
  .container { padding:12px; }
  .muted { font-size:12px; line-height:1.45; }
}
</style>
</head>
<body>
<div class="container">
<h1>Bekleyen Siparişler</h1>
<div class="muted">Buradaki iptal işlemi panelde gerçek iptal yapmaz; sadece bot takip listesinde iptal işaretler.</div>
<p><a href="/admin">← Admin Paneline Dön</a></p>
<table>
<thead>
<tr><th>Ürün</th><th>SMM ID</th><th>Link</th><th>Panel</th><th>Bekleme</th><th>Durum</th><th>İşlem</th></tr>
</thead>
<tbody>
{% for order in pending_orders %}
<tr>
<td>{{ order.product_name|e }}</td>
<td>{{ order.smm_order_id|e }}</td>
<td><a href="{{ order.link|e }}" target="_blank">Link</a></td>
<td>{{ order.panel|e }}</td>
<td>{{ ((now_ts - order.created_at) // 60) }} dk</td>
<td>{% if order.cancelled %}<span class="badge cancelled">İptal İşaretli</span>{% else %}<span class="badge active">Aktif</span>{% endif %}</td>
<td>
{% if not order.cancelled %}
<form method="post" action="/admin/cancel-order" onsubmit="return confirm('Bu sipariş sadece bot takip listesinde iptal işaretlenecek. Devam edilsin mi?')">
<input type="hidden" name="smm_order_id" value="{{ order.smm_order_id|e }}">
<button class="delete" type="submit">İptal İşaretle</button>
</form>
{% else %}-{% endif %}
</td>
</tr>
{% else %}
<tr><td colspan="7" style="text-align:center;color:#8a8fa3;">Bekleyen sipariş yok.</td></tr>
{% endfor %}
</tbody>
</table>
</div>
</body>
</html>
"""


@app.get("/admin/pending-orders", response_class=HTMLResponse)
def admin_pending_orders(user: str = Depends(get_current_admin)):
    template = Template(ADMIN_PENDING_HTML)
    html = template.render(pending_orders=PENDING_ORDERS, now_ts=int(time.time()))
    return HTMLResponse(content=html)


@app.post("/admin/cancel-order")
def admin_cancel_order(smm_order_id: str = Form(...), user: str = Depends(get_current_admin)):
    for order in PENDING_ORDERS:
        if str(order.get("smm_order_id")) == str(smm_order_id):
            if not order.get("cancelled"):
                order["cancelled"] = True
                save_state()
                log("warning", "order_cancelled_admin", smm_order_id=smm_order_id, product=order.get("product_name"))
                send_telegram(
                    f"Admin panelden sipariş bot takip listesinde iptal işaretlendi.\n\n"
                    f"SMM ID: {smm_order_id}\n"
                    f"Ürün: {order.get('product_name', 'Bilinmiyor')}\n"
                    f"Panel: {order.get('panel', 'Bilinmiyor')}\n\n"
                    f"Not: Bu işlem panelde gerçek iptal yapmaz. Panel tarafını ayrıca kontrol et."
                )
            return RedirectResponse("/admin/pending-orders", status_code=303)

    raise HTTPException(status_code=404, detail="Sipariş bulunamadı")


ADMIN_FAILED_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Başarısız Siparişler</title>
<style>
body { font-family: Arial, sans-serif; background:#0a0a0f; color:#e2e8f0; margin:0; padding:24px; }
.container { max-width:1180px; margin:auto; background:#111118; border:1px solid #1e1e2e; border-radius:14px; padding:24px; }
h1 { margin:0 0 8px; } .muted { color:#8a8fa3; font-size:13px; margin-bottom:18px; }
a { color:#a78bfa; text-decoration:none; }
button { padding:8px 12px; border-radius:8px; border:none; background:#7c3aed; color:#fff; cursor:pointer; font-weight:700; }
button.retry { background:#16a34a; }
table { width:100%; border-collapse:collapse; margin-top:20px; }
th, td { padding:12px; border-bottom:1px solid #242436; text-align:left; font-size:14px; vertical-align:top; }
th { background:#181824; color:#a8adbd; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
.badge { padding:4px 8px; border-radius:99px; font-size:12px; font-weight:700; background:#3f1d1d; color:#fca5a5; }
@media (max-width: 900px) {
  body { padding:12px; }
  .container { padding:16px; border-radius:12px; }
  h1 { font-size:24px; }
  table { display:block; overflow-x:auto; white-space:nowrap; -webkit-overflow-scrolling:touch; }
  th, td { padding:10px 9px; font-size:12px; }
  button { min-height:40px; width:100%; }
}
@media (max-width: 520px) {
  body { padding:8px; }
  .container { padding:12px; }
  .muted { font-size:12px; line-height:1.45; }
}
</style>
</head>
<body>
<div class="container">
<h1>Başarısız Siparişler</h1>
<div class="muted">Retry butonu aynı linki tekrar panele gönderir. Sadece panel durumunu kontrol ettikten sonra kullan.</div>
<p><a href="/admin">← Admin Paneline Dön</a></p>
<table>
<thead><tr><th>Ürün</th><th>Itemsatış</th><th>SMM ID</th><th>Panel</th><th>Sebep</th><th>Link</th><th>İşlem</th></tr></thead>
<tbody>
{% for order in failed_orders %}
<tr>
<td>{{ order.product_name|e }}</td>
<td>{{ order.order_id }}</td>
<td>{{ order.smm_order_id or '-' }}</td>
<td>{{ order.panel or '-' }}</td>
<td><span class="badge">{{ order.reason|e }}</span><br><small>{{ order.detail|e }}</small></td>
<td>{% if order.link %}<a href="{{ order.link|e }}" target="_blank">Link</a>{% else %}-{% endif %}</td>
<td>
{% if order.retryable and order.link and not order.retried %}
<form method="post" action="/admin/retry-order" onsubmit="return confirm('Bu işlem aynı linki tekrar panele gönderir. Devam edilsin mi?')">
<input type="hidden" name="smm_order_id" value="{{ order.smm_order_id|e }}">
<button class="retry" type="submit">Retry</button>
</form>
{% elif order.retried %}Tekrar denendi{% else %}-{% endif %}
</td>
</tr>
{% else %}
<tr><td colspan="7" style="text-align:center;color:#8a8fa3;">Başarısız sipariş yok.</td></tr>
{% endfor %}
</tbody>
</table>
</div>
</body>
</html>
"""


@app.get("/admin/failed-orders", response_class=HTMLResponse)
def admin_failed_orders(user: str = Depends(get_current_admin)):
    template = Template(ADMIN_FAILED_HTML)
    html = template.render(failed_orders=list(reversed(FAILED_ORDERS[-50:])))
    return HTMLResponse(content=html)


@app.post("/admin/retry-order")
def admin_retry_order(smm_order_id: str = Form(...), user: str = Depends(get_current_admin)):
    target = None
    for item in reversed(FAILED_ORDERS):
        if str(item.get("smm_order_id", "")) == str(smm_order_id) and item.get("retryable"):
            target = item
            break

    if not target:
        raise HTTPException(status_code=404, detail="Retry yapılabilir başarısız sipariş bulunamadı")

    if target.get("retried"):
        raise HTTPException(status_code=400, detail="Bu sipariş daha önce tekrar denendi")

    advert_id = str(target.get("advert_id", ""))
    all_services = get_all_services(include_inactive=True)
    raw_service = all_services.get(advert_id)
    if not raw_service:
        raise HTTPException(status_code=400, detail="Bu ilan için servis ayarı bulunamadı")

    service = get_service_config(raw_service)
    if not service.get("api_url") or not service.get("api_key"):
        raise HTTPException(status_code=400, detail="Panel bilgileri eksik")

    smm_result = create_panel_order(
        service["api_url"],
        service["api_key"],
        service["service_id"],
        target.get("link", ""),
        service["quantity"],
        service.get("panel", ""),
    )

    if "error" in smm_result:
        log("error", "retry_order_failed", smm_order_id=smm_order_id, error=smm_result.get("error"))
        send_telegram(f"Retry başarısız.\n\nSMM ID: {smm_order_id}\nHata: {smm_result.get('error')}")
        raise HTTPException(status_code=400, detail=smm_result.get("error"))

    new_smm_order_id = smm_result.get("order", "Bilinmiyor")
    add_pending_order(
        target.get("order_id", "Bilinmiyor"),
        advert_id,
        target.get("product_name", "Bilinmeyen Ürün"),
        service["panel"],
        service["api_url"],
        service["api_key"],
        new_smm_order_id,
        target.get("link", ""),
        service_id=service.get("service_id", ""),
        quantity=service.get("quantity", ""),
        platform=service.get("platform", ""),
        panel_key=service.get("panel_key", ""),
    )
    target["retried"] = True
    target["retry_smm_order_id"] = str(new_smm_order_id)
    save_state()

    send_telegram(
        f"Retry başlatıldı.\n\nÜrün: {target.get('product_name', 'Bilinmiyor')}\nPanel: {service['panel']}\n"
        f"Eski SMM ID: {smm_order_id}\nYeni SMM ID: {new_smm_order_id}"
    )
    return RedirectResponse("/admin/failed-orders", status_code=303)


# ─── DASHBOARD HTML ───────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Dashboard</title>
<link rel="icon" type="image/png" href="/static/favicon.png?v=3">
<link rel="shortcut icon" href="/static/favicon.png?v=3">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap');

  :root {
    --bg: #0a0a0f;
    --surface: #111118;
    --surface2: #15151f;
    --border: #1e1e2e;
    --accent: #7c3aed;
    --accent2: #06b6d4;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text: #e2e8f0;
    --muted: #64748b;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: radial-gradient(circle at top left, rgba(124,58,237,0.14), transparent 34%), var(--bg);
    color: var(--text);
    font-family: 'Syne', sans-serif;
    min-height: 100vh;
  }

  header {
    border-bottom: 1px solid var(--border);
    padding: 20px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    background: rgba(17,17,24,0.82);
    backdrop-filter: blur(12px);
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .logo {
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.5px;
  }

  .logo span { color: var(--accent); }
  .container { max-width: 1440px; margin: 0 auto; padding: 32px; }

  .top-actions { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  .last-updated { font-size: 11px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }

  .refresh-btn, .link-btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 8px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    transition: all 0.2s;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .refresh-btn:hover, .link-btn:hover { border-color: var(--accent); color: var(--accent); }

  .filters {
    display: flex;
    gap: 16px;
    margin-bottom: 20px;
    flex-wrap: wrap;
    align-items: center;
  }

  .filter-box {
    background: rgba(17,17,24,0.85);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .filter-box label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
  }

  select {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 13px;
    outline: none;
  }

  .grid-4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }

  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 28px;
  }

  .card {
    background: rgba(17,17,24,0.92);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 18px 50px rgba(0,0,0,0.18);
  }

  .stat-card { position: relative; overflow: hidden; }
  .stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--accent); }
  .stat-card.success::before { background: var(--success); }
  .stat-card.warning::before { background: var(--warning); }
  .stat-card.danger::before { background: var(--danger); }
  .stat-card.cyan::before { background: var(--accent2); }

  .stat-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 10px;
  }

  .stat-value { font-size: 32px; font-weight: 800; letter-spacing: -1px; }
  .stat-sub { font-size: 12px; color: var(--muted); margin-top: 4px; font-family: 'JetBrains Mono', monospace; }

  .card-title {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
    display:flex;
    justify-content:space-between;
    gap:12px;
    align-items:center;
  }

  .chart-wrap { height: 310px; }
  .chart-wrap canvas { width: 100% !important; height: 100% !important; }

  .log-list { font-family: 'JetBrains Mono', monospace; font-size: 12px; max-height: 380px; overflow-y: auto; }
  .log-list::-webkit-scrollbar { width: 4px; }
  .log-list::-webkit-scrollbar-track { background: transparent; }
  .log-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .log-entry { display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,0.03); align-items: flex-start; }
  .log-ts { color: var(--muted); flex-shrink: 0; font-size: 11px; }
  .log-level { flex-shrink: 0; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase; }
  .log-level.info { background: rgba(124,58,237,0.2); color: var(--accent); }
  .log-level.success { background: rgba(16,185,129,0.2); color: var(--success); }
  .log-level.warning { background: rgba(245,158,11,0.2); color: var(--warning); }
  .log-level.error { background: rgba(239,68,68,0.2); color: var(--danger); }
  .log-event { color: var(--text); flex: 1; }
  .log-meta { color: var(--muted); font-size: 11px; word-break: break-all; }

  .order-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 13px; }
  .order-row:last-child { border-bottom: none; }
  .badge { font-size: 10px; padding: 3px 8px; border-radius: 20px; font-family: 'JetBrains Mono', monospace; font-weight: 600; white-space:nowrap; }
  .badge.pending { background: rgba(245,158,11,0.15); color: var(--warning); }
  .badge.failed { background: rgba(239,68,68,0.15); color: var(--danger); }
  .empty { color: var(--muted); font-size: 13px; text-align: center; padding: 24px; }
  .order-detail { font-size: 11px; color: var(--muted); font-family: 'JetBrains Mono', monospace; word-break: break-word; overflow-wrap:anywhere; }
  .history-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:14px; align-items:center; padding:13px 0; border-bottom:1px solid rgba(255,255,255,0.04); }
  .history-row:last-child { border-bottom:none; }
  .history-title { font-size:13px; font-weight:700; color:var(--text); line-height:1.35; word-break:break-word; overflow-wrap:anywhere; }
  .history-meta { margin-top:5px; display:flex; flex-wrap:wrap; gap:7px 10px; align-items:center; color:var(--muted); font-size:11px; font-family:'JetBrains Mono',monospace; }
  .history-meta span { max-width:100%; overflow-wrap:anywhere; }
  .history-link { color:var(--accent2); text-decoration:none; max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:inline-block; vertical-align:bottom; }
  .history-link:hover { text-decoration:underline; }
  .price-badge { font-size:11px; padding:5px 9px; border-radius:999px; font-family:'JetBrains Mono',monospace; font-weight:700; white-space:nowrap; background:rgba(245,158,11,0.16); color:var(--warning); }

  @media (max-width: 1050px) {
    .grid-4 { grid-template-columns: repeat(2, 1fr); }
    .grid-2 { grid-template-columns: 1fr; }
    .container { padding: 24px; }
  }
  @media (max-width: 700px) {
    header { padding: 14px; align-items:stretch; flex-direction:column; gap:12px; }
    .logo { font-size:20px; }
    .top-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; width:100%; }
    .top-actions .last-updated { grid-column:1/-1; order:10; text-align:center; }
    .refresh-btn, .link-btn { justify-content:center; min-height:42px; width:100%; padding:9px 10px; font-size:11px; }
    .container { padding: 14px; }
    .filters { display:grid; grid-template-columns:1fr; gap:10px; }
    .filter-box { width:100%; justify-content:space-between; padding:10px; }
    .filter-box label { font-size:10px; }
    select { flex:1; min-height:42px; font-size:14px; }
    .grid-4 { grid-template-columns: 1fr; gap:12px; margin-bottom:16px; }
    .grid-2 { gap:14px; margin-bottom:16px; }
    .card { padding:14px; border-radius:12px; }
    .stat-value { font-size:26px; }
    .chart-wrap { height:240px; }
    .order-row { align-items:flex-start; flex-direction:column; gap:6px; }
    .badge { align-self:flex-start; }
    .history-row { grid-template-columns:1fr; gap:8px; }
    .history-meta { display:grid; grid-template-columns:1fr; gap:5px; }
    .history-link { max-width:100%; white-space:normal; overflow-wrap:anywhere; }
    .price-badge { justify-self:flex-start; width:max-content; }
    .log-entry { display:grid; grid-template-columns:auto auto 1fr; gap:6px; }
    .log-meta { display:block; margin-top:3px; }
  }
  @media (max-width: 420px) {
    .top-actions { grid-template-columns:1fr; }
    .container { padding:10px; }
    .card-title { align-items:flex-start; flex-direction:column; }
    .chart-wrap { height:220px; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">Boostera <span>SMM</span></div>
  <div class="top-actions">
    <a class="link-btn" href="/admin">Admin</a>
    <a class="link-btn" href="/admin/manual-order">Manuel Sipariş</a>
    <a class="link-btn" href="/api/export">CSV İndir</a>
    <span class="last-updated" id="lastUpdated">—</span>
    <button class="refresh-btn" onclick="loadAll()">↻ Yenile</button>
  </div>
</header>

<div class="container">

  <div class="filters">
    <div class="filter-box">
      <label for="dateFilter">Tarih</label>
      <select id="dateFilter">
        <option value="7">Son 7 Gün</option>
        <option value="14">Son 14 Gün</option>
        <option value="30" selected>Son 30 Gün</option>
      </select>
    </div>
    <div class="filter-box">
      <label for="viewType">Grafik</label>
      <select id="viewType">
        <option value="orders">Satış Sayısı</option>
        <option value="gross">Brüt Gelir</option>
        <option value="net">Net Gelir</option>
      </select>
    </div>
  </div>

  <div class="grid-4" id="statsGrid">
    <div class="card stat-card success">
      <div class="stat-label">Seçili Süre Sipariş</div>
      <div class="stat-value" id="rangeOrders">—</div>
      <div class="stat-sub" id="todayCount">bugün —</div>
    </div>
    <div class="card stat-card warning">
      <div class="stat-label">Seçili Süre Brüt</div>
      <div class="stat-value" id="rangeGross">—</div>
      <div class="stat-sub" id="rangeNet">net —</div>
    </div>
    <div class="card stat-card cyan">
      <div class="stat-label">Bekleyen</div>
      <div class="stat-value" id="pendingCount">—</div>
    </div>
    <div class="card stat-card danger">
      <div class="stat-label">Başarısız</div>
      <div class="stat-value" id="failedCount">—</div>
    </div>
  </div>

  <div class="card" style="margin-bottom:28px;">
    <div class="card-title">
      <span id="chartTitle">Satış Grafiği</span>
      <span id="chartSummary" style="font-size:11px;color:var(--muted)"></span>
    </div>
    <div class="chart-wrap"><canvas id="mainChart"></canvas></div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">Bekleyen Siparişler <a class="link-btn" href="/admin/pending-orders" style="padding:5px 9px">Yönet</a></div>
      <div id="pendingList"><div class="empty">Yükleniyor...</div></div>
    </div>
    <div class="card">
      <div class="card-title">Son Başarısız Siparişler <a class="link-btn" href="/admin/failed-orders" style="padding:5px 9px">Retry</a></div>
      <div id="failedList"><div class="empty">Yükleniyor...</div></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:28px;">
    <div class="card-title">
      <span>Sipariş Geçmişi</span>
      <span id="historyCount" style="color:var(--muted);font-size:11px"></span>
    </div>
    <div id="historyList"><div class="empty">Yükleniyor...</div></div>
  </div>

  <div class="card">
    <div class="card-title">
      <span>Canlı Log</span>
      <span id="logCount" style="color:var(--muted);font-size:11px"></span>
    </div>
    <div class="log-list" id="logList"><div class="empty">Yükleniyor...</div></div>
  </div>

</div>

<script>
const dateFilter = document.getElementById('dateFilter');
const viewType = document.getElementById('viewType');
let mainChart = null;

function money(value) {
  return Number(value || 0).toLocaleString('tr-TR', { maximumFractionDigits: 0 }) + ' ₺';
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[ch]));
}

async function loadAll() {
  document.getElementById('lastUpdated').textContent = 'Güncelleniyor...';
  await Promise.all([loadStatsAndChart(), loadPending(), loadFailed(), loadHistory(), loadLogs()]);
  const now = new Date().toLocaleTimeString('tr-TR');
  document.getElementById('lastUpdated').textContent = `Son güncelleme: ${now}`;
}

async function loadStatsAndChart() {
  const days = Number(dateFilter.value || 30);
  const type = viewType.value || 'orders';
  const [statsRes, salesRes] = await Promise.all([
    fetch('/api/stats'),
    fetch(`/api/sales-data?days=${days}`)
  ]);
  const stats = await statsRes.json();
  const sales = await salesRes.json();

  document.getElementById('rangeOrders').textContent = sales.total_orders ?? 0;
  document.getElementById('todayCount').textContent = `bugün ${stats.today_count ?? 0}`;
  document.getElementById('rangeGross').textContent = money(sales.total_gross ?? 0);
  document.getElementById('rangeNet').textContent = `net ${money(sales.total_net ?? 0)}`;
  document.getElementById('pendingCount').textContent = stats.pending_count ?? 0;
  document.getElementById('failedCount').textContent = stats.failed_count ?? 0;

  const map = {
    orders: { label: 'Satış Sayısı', values: sales.order_values || [] },
    gross: { label: 'Brüt Gelir', values: sales.gross_values || [] },
    net: { label: 'Net Gelir', values: sales.net_values || [] },
  };
  const selected = map[type] || map.orders;
  document.getElementById('chartTitle').textContent = `${selected.label} · Son ${days} Gün`;
  document.getElementById('chartSummary').textContent = `Toplam ${sales.total_orders || 0} sipariş · ${money(sales.total_gross || 0)} brüt`;
  createOrUpdateChart(sales.labels || [], selected.values, selected.label, type);
}

function createOrUpdateChart(labels, values, label, type) {
  const canvas = document.getElementById('mainChart');
  if (!canvas || typeof Chart === 'undefined') return;
  const ctx = canvas.getContext('2d');

  if (mainChart) {
    mainChart.data.labels = labels;
    mainChart.data.datasets[0].label = label;
    mainChart.data.datasets[0].data = values;
    mainChart.options.scales.y.ticks.callback = type === 'orders' ? (v) => v : (v) => money(v);
    mainChart.update();
    return;
  }

  mainChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        fill: true,
        borderColor: 'rgba(124, 58, 237, 0.95)',
        backgroundColor: 'rgba(124, 58, 237, 0.12)',
        tension: 0.32,
        pointRadius: 3,
        pointHoverRadius: 5,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#e2e8f0' } },
        tooltip: {
          callbacks: {
            label: (ctx) => type === 'orders' ? `${ctx.dataset.label}: ${ctx.raw}` : `${ctx.dataset.label}: ${money(ctx.raw)}`
          }
        }
      },
      scales: {
        x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { beginAtZero: true, ticks: { color: '#64748b', precision: 0, callback: type === 'orders' ? (v) => v : (v) => money(v) }, grid: { color: 'rgba(255,255,255,0.05)' } }
      }
    }
  });
}

async function loadPending() {
  const r = await fetch('/api/pending');
  const d = await r.json();
  const el = document.getElementById('pendingList');
  const orders = d.orders || [];
  if (!orders.length) { el.innerHTML = '<div class="empty">Bekleyen sipariş yok</div>'; return; }
  el.innerHTML = orders.slice(-8).reverse().map(o => {
    const mins = Math.floor((Date.now()/1000 - Number(o.created_at || 0)) / 60);
    return `<div class="order-row">
      <div>
        <div>${escapeHtml(o.product_name)}</div>
        <div class="order-detail">${escapeHtml(o.link)} · ${escapeHtml(o.panel)} #${escapeHtml(o.smm_order_id)}</div>
      </div>
      <span class="badge pending">${mins}dk</span>
    </div>`;
  }).join('');
}

async function loadFailed() {
  const r = await fetch('/api/failed');
  const d = await r.json();
  const el = document.getElementById('failedList');
  const orders = d.orders || [];
  if (!orders.length) { el.innerHTML = '<div class="empty">Başarısız sipariş yok</div>'; return; }
  el.innerHTML = orders.slice(-8).reverse().map(o => `
    <div class="order-row">
      <div>
        <div>${escapeHtml(o.product_name)}</div>
        <div class="order-detail">${escapeHtml(o.reason)}${o.smm_order_id ? ' · SMM #' + escapeHtml(o.smm_order_id) : ''}${o.panel ? ' · ' + escapeHtml(o.panel) : ''}</div>
      </div>
      <span class="badge failed">hata</span>
    </div>`).join('');
}


async function loadHistory() {
  const r = await fetch('/api/history');
  const d = await r.json();
  const el = document.getElementById('historyList');
  const orders = d.orders || [];
  document.getElementById('historyCount').textContent = `${orders.length} kayıt`;
  if (!orders.length) { el.innerHTML = '<div class="empty">Sipariş geçmişi yok</div>'; return; }
  el.innerHTML = orders.slice(-12).reverse().map(o => {
    const rawLink = String(o.link || '');
    const linkPart = new RegExp('^https?://', 'i').test(rawLink)
      ? `<a class="history-link" href="${escapeHtml(rawLink)}" target="_blank" rel="noopener">Linki Aç</a>`
      : `<span>${escapeHtml(rawLink || 'Link yok')}</span>`;
    return `<div class="history-row">
      <div class="history-main">
        <div class="history-title">${escapeHtml(o.product_name || 'Bilinmeyen Ürün')}</div>
        <div class="history-meta">
          <span>${escapeHtml(o.completed_at || '')}</span>
          <span>${escapeHtml(o.panel || 'Panel yok')}</span>
          <span>SMM #${escapeHtml(o.smm_order_id || '—')}</span>
          ${linkPart}
        </div>
      </div>
      <span class="price-badge">${money(o.price || 0)}</span>
    </div>`;
  }).join('');
}

async function loadLogs() {
  const r = await fetch('/api/logs');
  const d = await r.json();
  document.getElementById('logCount').textContent = `${(d.logs || []).length} kayıt`;
  const el = document.getElementById('logList');
  const logs = d.logs || [];
  if (!logs.length) { el.innerHTML = '<div class="empty">Log yok</div>'; return; }
  el.innerHTML = [...logs].reverse().map(l => {
    const meta = Object.entries(l)
      .filter(([k]) => !['ts','level','event'].includes(k))
      .map(([k,v]) => `${escapeHtml(k)}=${escapeHtml(v)}`).join(' ');
    return `<div class="log-entry">
      <span class="log-ts">${escapeHtml(String(l.ts || '').slice(11,19))}</span>
      <span class="log-level ${escapeHtml(l.level)}">${escapeHtml(l.level)}</span>
      <span class="log-event">${escapeHtml(l.event)} <span class="log-meta">${meta}</span></span>
    </div>`;
  }).join('');
}

dateFilter.addEventListener('change', loadStatsAndChart);
viewType.addEventListener('change', loadStatsAndChart);
loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>
"""


# ─── API ENDPOINTS ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard(user: str = Depends(get_current_admin)):
    return DASHBOARD_HTML


@app.get("/api/stats")
def api_stats(user: str = Depends(get_current_admin)):
    today_count = sum(normalize_stat_item(v)["count"] for v in DAILY_STATS.values())
    today_gross = sum(normalize_stat_item(v)["gross"] for v in DAILY_STATS.values())
    commission = today_gross * ITEMSATIS_COMMISSION_RATE
    return {
        "today_count": today_count,
        "today_gross": today_gross,
        "today_net": today_gross - commission,
        "pending_count": len(PENDING_ORDERS),
        "failed_count": len(FAILED_ORDERS),
    }


@app.get("/api/sales-data")
def api_sales_data(days: int = 30, user: str = Depends(get_current_admin)):
    """Dashboard grafiği için tarih bazlı satış geçmişi döndürür."""
    try:
        days = int(days)
    except Exception:
        days = 30

    if days not in [7, 14, 30, 60, 90]:
        days = 30

    labels = []
    order_values = []
    gross_values = []
    net_values = []
    now = now_tr()

    total_orders = 0
    total_gross = 0.0

    for i in range(days - 1, -1, -1):
        day_dt = now - timedelta(days=i)
        day_key = day_dt.strftime("%Y-%m-%d")
        labels.append(day_dt.strftime("%d.%m"))

        item = SALES_HISTORY.get(day_key, {})
        try:
            count = int(item.get("count", 0) or 0)
            gross = float(item.get("gross", 0) or 0)
        except Exception:
            count = 0
            gross = 0.0

        net = gross * (1 - ITEMSATIS_COMMISSION_RATE)
        order_values.append(count)
        gross_values.append(round(gross, 2))
        net_values.append(round(net, 2))
        total_orders += count
        total_gross += gross

    total_net = total_gross * (1 - ITEMSATIS_COMMISSION_RATE)

    return {
        "labels": labels,
        "order_values": order_values,
        "gross_values": gross_values,
        "net_values": net_values,
        "total_orders": total_orders,
        "total_gross": round(total_gross, 2),
        "total_net": round(total_net, 2),
        # Eski dashboard parçalarıyla geriye uyumluluk için:
        "values": order_values,
    }

@app.get("/api/pending")
def api_pending(user: str = Depends(get_current_admin)):
    return {"orders": [sanitize_pending_order(item) for item in PENDING_ORDERS]}


@app.get("/api/failed")
def api_failed(user: str = Depends(get_current_admin)):
    return {"orders": FAILED_ORDERS}


@app.get("/api/logs")
def api_logs(user: str = Depends(get_current_admin)):
    return {"logs": LOG_HISTORY}




@app.get("/api/history")
def api_history(user: str = Depends(get_current_admin)):
    return {"orders": ORDER_HISTORY[-500:]}


@app.get("/api/blacklist")
def api_blacklist(user: str = Depends(get_current_admin)):
    return {"items": sorted(BLACKLIST)}


@app.get("/api/profit")
def api_profit(sale: float = 0, cost: float = 0, user: str = Depends(get_current_admin)):
    return calculate_profit(sale, cost)


@app.get("/api/export")
def api_export(user: str = Depends(get_current_admin)):
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["order_id", "advert_id", "product_name", "panel", "smm_order_id", "link", "price", "completed_at"],
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in ORDER_HISTORY:
        writer.writerow(row)
    output.seek(0)
    filename = f"boostera_orders_{now_tr().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/check-panel-health")
@app.head("/check-panel-health")
def check_panel_health():
    results = {}
    for key, panel in PANEL_MAP.items():
        if not panel.get("api_url") or not panel.get("api_key"):
            continue
        balance_data = panel_balance(panel["api_url"], panel["api_key"], panel.get("name", key))
        if "error" in balance_data:
            log("error", "panel_health_error", panel=key, error=balance_data.get("error"))
            results[key] = {"ok": False, "error": balance_data.get("error")}
        else:
            check_low_balance(balance_data.get("balance", 0), balance_data.get("currency", ""), panel.get("name", key))
            results[key] = {"ok": True, "balance": format_panel_balance_tl(balance_data)}
    return {"ok": True, "panels": results}


@app.get("/test")
def test_message():
    return {"ok": True}


@app.head("/test")
def test_head():
    return {"ok": True}


@app.get("/my-ip")
def my_ip():
    r = requests.get("https://api.ipify.org?format=json", timeout=30)
    return r.json()


@app.head("/check-orders")
def check_orders_head():
    return check_orders()


@app.get("/check-orders")
def check_orders():
    completed_indexes = []
    changed = False
    failed_count = 0

    for index, item in enumerate(PENDING_ORDERS):
        if item.get("cancelled"):
            completed_indexes.append(index)
            changed = True
            continue

        runtime_service = get_runtime_service_for_pending(item)
        status_data = check_panel_order_status(
            runtime_service.get("api_url", ""),
            runtime_service.get("api_key", ""),
            item.get("smm_order_id", ""),
            runtime_service.get("panel", item.get("panel", "")),
        )

        if "error" in status_data:
            log(
                "error",
                "status_check_error",
                smm_order_id=item.get("smm_order_id"),
                panel=item.get("panel", ""),
                error=status_data,
            )
            continue

        status = str(status_data.get("status", "")).lower().strip()
        created_at = int(item.get("created_at", 0) or 0)
        delay_alert_sent = bool(item.get("delay_alert_sent", False))

        if status in FAILED_PANEL_STATUSES:
            failed_count += 1
            log(
                "warning",
                "order_failed_panel_status",
                smm_order_id=item.get("smm_order_id"),
                status=status,
                product=item.get("product_name"),
                panel=item.get("panel", ""),
            )
            add_failed_order(
                item.get("itemsatis_order_id", "Bilinmiyor"),
                item.get("advert_id", ""),
                item.get("product_name", "Bilinmeyen Ürün"),
                f"Panel durumu: {status}",
                detail=json.dumps(status_data, ensure_ascii=False)[:500],
                smm_order_id=item.get("smm_order_id", ""),
                link=item.get("link", ""),
                panel=item.get("panel", ""),
                panel_key=item.get("panel_key", runtime_service.get("panel_key", "")),
                service_id=item.get("service_id", runtime_service.get("service_id", "")),
                quantity=item.get("quantity", runtime_service.get("quantity", "")),
                platform=item.get("platform", runtime_service.get("platform", "")),
                retryable=True,
            )
            send_telegram(
                f"⚠️ SMM sipariş sorunlu duruma düştü.\n\n"
                f"Ürün: {item.get('product_name', 'Bilinmiyor')}\n"
                f"Panel: {item.get('panel', 'Bilinmiyor')}\n"
                f"Itemsatış ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\n"
                f"SMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
                f"Durum: {status}\n"
                f"Link: {item.get('link', '')}\n\n"
                f"Admin panelden kontrol et. Otomatik tekrar sipariş verilmedi."
            )
            completed_indexes.append(index)
            changed = True
            continue

        if created_at and not delay_alert_sent:
            waited_seconds = int(time.time()) - created_at
            if waited_seconds >= 5400:
                log("warning", "order_delayed", smm_order_id=item.get("smm_order_id"), waited_minutes=waited_seconds//60)
                send_telegram(
                    f"Sipariş gecikti.\n\nÜrün: {item.get('product_name', 'Bilinmiyor')}\nPanel: {item.get('panel', 'Bilinmiyor')}\n"
                    f"Itemsatış ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\nSMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
                    f"Link: {item.get('link', '')}\n\n1 saat 30 dakika geçti. Paneli kontrol et."
                )
                item["delay_alert_sent"] = True
                changed = True

        if status in COMPLETED_PANEL_STATUSES:
            log("success", "order_completed", smm_order_id=item.get("smm_order_id"), product=item.get("product_name"))
            send_telegram(
                f"SMM siparişi tamamlandı.\n\nÜrün: {item.get('product_name', 'Bilinmiyor')}\nPanel: {item.get('panel', 'Bilinmiyor')}\n"
                f"Itemsatış ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\nSMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\nLink: {item.get('link', '')}\n\n"
                f"Müşteriye değerlendirme mesajı gönderildi."
            )
            notify_customer_order_completed(item.get("itemsatis_order_id", ""), item.get("product_name", ""), item.get("link", ""))
            add_order_history(
                item.get("itemsatis_order_id", "Bilinmiyor"),
                item.get("advert_id", ""),
                item.get("product_name", "Bilinmeyen Ürün"),
                item.get("panel", ""),
                item.get("smm_order_id", ""),
                item.get("link", ""),
                item.get("price", 0),
            )
            completed_indexes.append(index)
            changed = True

    for index in reversed(completed_indexes):
        PENDING_ORDERS.pop(index)

    if changed:
        save_state()

    return {"ok": True, "pending_count": len(PENDING_ORDERS), "completed_count": len(completed_indexes), "failed_count": failed_count}


# ─── YENİ: /cancel KOMUTU (Telegram'dan SMM siparişini iptal et) ──────────────
def handle_cancel_command(text: str):
    """
    /cancel smm_order_id — bekleyen siparişi iptal eder.
    Örnek: /cancel 12345
    """
    parts = text.strip().split()
    if len(parts) < 2:
        send_telegram(
            "Kullanım: /cancel smm_order_id\n\n"
            "Bekleyen siparişleri görmek için: /pending"
        )
        return

    target_id = parts[1].strip()
    found = False

    for item in PENDING_ORDERS:
        if str(item.get("smm_order_id")) == target_id:
            item["cancelled"] = True
            found = True
            log("warning", "order_cancelled", smm_order_id=target_id, product=item["product_name"])
            send_telegram(
                f"Sipariş iptal edildi.\n\n"
                f"SMM ID: {target_id}\n"
                f"Ürün: {item['product_name']}\n"
                f"Link: {item['link']}\n\n"
                f"Not: Panel tarafında iptali ayrıca kontrol et."
            )
            break

    if not found:
        send_telegram(f"SMM sipariş bulunamadı: {target_id}\n\nMevcut siparişler için: /pending")

    save_state()


@app.head("/daily-report")
def daily_report_head():
    return daily_report()


@app.get("/daily-report")
def daily_report():
    global LAST_DAILY_REPORT_DATE, DAILY_STATS
    now = now_tr()
    today = now.strftime("%Y-%m-%d")
    if now.hour != 0:
        return {"ok": True, "message": "Rapor saati değil"}
    if LAST_DAILY_REPORT_DATE == today:
        return {"ok": True, "message": "Bugünün raporu zaten gönderildi"}
    report_text = build_sales_report("Günlük Satış Özeti", DAILY_STATS, "Bugün kayıtlı sipariş yok.")
    send_telegram(report_text)
    LAST_DAILY_REPORT_DATE = today
    DAILY_STATS = {}
    save_state()
    return {"ok": True, "sent": True}


@app.head("/weekly-report")
def weekly_report_head():
    return weekly_report()


@app.get("/weekly-report")
def weekly_report():
    global LAST_WEEKLY_REPORT_DATE, WEEKLY_STATS
    now = now_tr()
    today = now.strftime("%Y-%m-%d")
    if now.weekday() != 0 or now.hour != 0:
        return {"ok": True, "message": "Haftalık rapor saati değil"}
    if LAST_WEEKLY_REPORT_DATE == today:
        return {"ok": True, "message": "Bu haftanın raporu zaten gönderildi"}
    report_text = build_sales_report("Haftalık Satış Raporu", WEEKLY_STATS, "Bu hafta kayıtlı sipariş yok.")
    send_telegram(report_text)
    LAST_WEEKLY_REPORT_DATE = today
    WEEKLY_STATS = {}
    save_state()
    return {"ok": True, "sent": True}


@app.head("/monthly-report")
def monthly_report_head():
    return monthly_report()


@app.get("/monthly-report")
def monthly_report():
    global LAST_MONTHLY_REPORT_DATE, MONTHLY_STATS
    now = now_tr()
    today = now.strftime("%Y-%m-%d")
    if now.day != 1 or now.hour != 0:
        return {"ok": True, "message": "Aylık rapor saati değil"}
    if LAST_MONTHLY_REPORT_DATE == today:
        return {"ok": True, "message": "Bu ayın raporu zaten gönderildi"}
    report_text = build_sales_report("Aylık Satış Raporu", MONTHLY_STATS, "Bu ay kayıtlı sipariş yok.")
    send_telegram(report_text)
    LAST_MONTHLY_REPORT_DATE = today
    MONTHLY_STATS = {}
    save_state()
    return {"ok": True, "sent": True}


@app.head("/check-services")
def check_services_head():
    return check_services()


@app.get("/check-services")
def check_services():
    global SERVICE_PRICE_CACHE
    changed_count = 0
    for advert_id, raw_service in get_all_services().items():
        service = get_service_config(raw_service)

        if not service.get("api_url") or not service.get("api_key"):
            log("warning", "service_panel_missing", advert_id=advert_id, panel=service.get("panel_key"))
            continue

        services_data = get_panel_services(service["api_url"], service["api_key"], service.get("panel", ""))
        if isinstance(services_data, dict) and "error" in services_data:
            continue
        target_service = None
        for item in services_data:
            if str(item.get("service")) == str(service["service_id"]):
                target_service = item
                break
        if not target_service:
            continue

        panel_service_name = get_panel_service_display_name(service, target_service)
        current_rate = str(target_service.get("rate", ""))
        cache_key = f'{service["panel_key"]}:{service["service_id"]}'
        old_rate = SERVICE_PRICE_CACHE.get(cache_key)
        if old_rate is None:
            SERVICE_PRICE_CACHE[cache_key] = current_rate
            save_state()
            continue
        if str(old_rate) != str(current_rate):
            panel_service_name = get_panel_service_display_name(service, target_service)
            log("warning", "service_price_changed", panel=service["panel"], service_id=service["service_id"],
                service_name=panel_service_name, old=old_rate, new=current_rate)
            send_telegram(
                f"Servis fiyatı değişti.\n\nPanel Servisi: {panel_service_name}\nPanel: {service['panel']}\n"
                f"Servis ID: {service['service_id']}\nEski: {old_rate} → Yeni: {current_rate}\n\n"
                f"Bu servis ID'sini kullanan Itemsatış ilanlarını kontrol et."
            )
            SERVICE_PRICE_CACHE[cache_key] = current_rate
            changed_count += 1
    if changed_count:
        save_state()
    return {"ok": True, "changed_count": changed_count}


@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    if not is_webhook_authorized(request):
        log("warning", "webhook_unauthorized", ip=request.client.host if request.client else "")
        raise HTTPException(status_code=401, detail="Unauthorized webhook")

    try:
        data = await request.json()
    except Exception:
        body = await request.body()
        data = {"raw_body": body.decode("utf-8", errors="ignore")}

    log("info", "webhook_received", raw=str(data)[:200])

    event = get_event(data)
    order_id = get_order_id(data)
    advert_id = get_advert_id(data)
    product_name = get_product_name(data)
    buyer = get_buyer(data)
    price = get_order_price(data)

    ignored_events = {"review_received", "review_created", "message_created", "question_created", "advert_updated"}
    if event in ignored_events:
        log("info", "webhook_ignored", event=event)
        return {"ignored": True, "event": event}

    report_product_name = get_itemsatis_report_name(advert_id, product_name)

    record_itemsatis_sale(data=data, order_id=order_id, advert_id=advert_id, buyer=buyer,
                          product_name=report_product_name, price=price)

    log("info", "sale_received", order_id=order_id, product=report_product_name, buyer=buyer, price=price)

    send_telegram(
        f"Itemsatış webhook geldi.\n\nEvent: {event or 'Yok'}\nAdvert ID: {advert_id or 'Yok'}\n"
        f"Ürün: {report_product_name}\nSipariş ID: {order_id}\nMüşteri: {buyer}\nTutar: {price:.2f} TL"
    )

    if advert_id == CS2_ADVERT_ID:
        order_key = make_order_key(order_id, advert_id, buyer)
        if order_key in PROCESSED_ORDERS:
            return {"ignored": True, "reason": "duplicate_cs2_order"}
        PROCESSED_ORDERS.add(order_key)
        save_state()
        send_telegram(f"Yeni CS2 5 yıllık hesap siparişi.\n\nSipariş ID: {order_id}\nMüşteri: {buyer}\n\n{get_lzt_links()}")
        return {"ok": True, "type": "cs2", "order_id": order_id}

    all_packages = get_package_configs()
    if advert_id in all_packages:
        package = all_packages[advert_id]
        package_name = get_package_display_name(advert_id, package, product_name)
        package_platform = normalize_text(package.get("platform", "tiktok")) or "tiktok"
        customer_link = find_order_link(data, package_platform)

        if not customer_link:
            add_failed_order(order_id, advert_id, package_name, "Paket sipariş linki bulunamadı")
            notify_customer_order_failed(order_id, package_name)
            send_telegram(
                f"Paket sipariş linki bulunamadı.\n\nSipariş ID: {order_id}\nPaket: {package_name}\nPlatform: {package_platform}\nMüşteri: {buyer}"
            )
            return {"ok": False, "error": "package_link_not_found"}

        if is_blacklisted(customer_link) or is_blacklisted(buyer):
            add_failed_order(order_id, advert_id, package_name, "Blacklist engeli", customer_link, link=customer_link)
            send_telegram(f"Blacklisted paket sipariş engellendi.\n\nSipariş ID: {order_id}\nMüşteri: {buyer}\nLink: {customer_link}")
            return {"ok": False, "error": "blacklisted"}

        normalized_link = normalize_link_for_check(customer_link, package_platform)
        duplicate_link_key = f"package:{advert_id}:{normalized_link}"
        order_key = make_order_key(order_id, advert_id, buyer, customer_link, package_platform)

        if order_key in PROCESSED_ORDERS:
            return {"ignored": True, "reason": "duplicate_package_order"}
        if duplicate_link_key in PROCESSED_LINKS:
            return {"ignored": True, "reason": "duplicate_package_link"}

        success_rows = []
        failed_rows = []
        components = package.get("components", []) or []

        for component in components:
            component = normalize_package_component(component)
            if not component.get("active", True):
                continue
            component_name = component.get("name") or "Paket Bileşeni"
            service = get_service_config(component)
            component_label = f"{package_name} - {component_name}"

            if not service.get("api_url") or not service.get("api_key"):
                failed_rows.append((component_name, service.get("panel", "Panel"), "Panel bilgileri eksik"))
                add_failed_order(order_id, advert_id, component_label, "Panel bilgileri eksik", service.get("panel_key", ""), link=customer_link, panel=service.get("panel", ""))
                continue

            smm_result = create_panel_order(
                service["api_url"],
                service["api_key"],
                service["service_id"],
                customer_link,
                service["quantity"],
                service.get("panel", ""),
            )

            if "error" in smm_result:
                error_text = str(smm_result.get("error") or smm_result)
                failed_rows.append((component_name, service.get("panel", "Panel"), error_text))
                add_failed_order(order_id, advert_id, component_label, "Paket panel sipariş hatası", error_text, link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""))
                continue

            smm_order_id = smm_result.get("order", "Bilinmiyor")
            add_pending_order(
                order_id,
                advert_id,
                component_label,
                service["panel"],
                service["api_url"],
                service["api_key"],
                smm_order_id,
                customer_link,
                service_id=service.get("service_id", ""),
                quantity=service.get("quantity", ""),
                platform=service.get("platform", ""),
                panel_key=service.get("panel_key", ""),
                price=0,
            )
            success_rows.append((component_name, service.get("panel", "Panel"), smm_order_id))

        if success_rows:
            PROCESSED_LINKS.add(duplicate_link_key)
            PROCESSED_ORDERS.add(order_key)
            save_state()
            notify_customer_order_started(order_id, package_name, customer_link)

        success_text = "\n".join([f"✅ {name} | {panel} | SMM ID: {smm_id}" for name, panel, smm_id in success_rows]) or "Yok"
        failed_text = "\n".join([f"❌ {name} | {panel} | {err}" for name, panel, err in failed_rows]) or "Yok"
        send_telegram(
            f"Paket sipariş işlendi.\n\nPaket: {package_name}\nItemsatış ID: {order_id}\nLink: {customer_link}\n\nBaşarılı:\n{success_text}\n\nHatalı:\n{failed_text}"
        )

        if not success_rows:
            return {"ok": False, "type": "package_order", "error": "all_package_components_failed", "failed_count": len(failed_rows)}
        return {"ok": True, "type": "package_order", "success_count": len(success_rows), "failed_count": len(failed_rows)}

    all_services = get_all_services()
    if advert_id in all_services:
        service = get_service_config(all_services[advert_id])
        service_name = get_itemsatis_report_name(advert_id, product_name)
        platform = normalize_text(service.get("platform", "instagram"))
        customer_link = find_order_link(data, platform)

        if not customer_link:
            add_failed_order(order_id, advert_id, service_name, "Sipariş linki bulunamadı")
            notify_customer_order_failed(order_id, service_name)
            send_telegram(f"Sipariş linki bulunamadı.\n\nSipariş ID: {order_id}\nÜrün: {service_name}\nPlatform: {platform or 'belirsiz'}\nMüşteri: {buyer}")
            return {"ok": False, "error": "order_link_not_found"}

        if is_blacklisted(customer_link) or is_blacklisted(buyer):
            add_failed_order(order_id, advert_id, service_name, "Blacklist engeli", customer_link, link=customer_link, panel=service.get("panel", ""))
            send_telegram(
                f"Blacklisted sipariş engellendi.\n\nSipariş ID: {order_id}\nMüşteri: {buyer}\nLink: {customer_link}"
            )
            return {"ok": False, "error": "blacklisted"}

        normalized_link = normalize_link_for_check(customer_link, platform)
        duplicate_link_key = f"{advert_id}:{normalized_link}"
        order_key = make_order_key(order_id, advert_id, buyer, customer_link, platform)

        if order_key in PROCESSED_ORDERS:
            return {"ignored": True, "reason": "duplicate_order"}

        if duplicate_link_key in PROCESSED_LINKS:
            return {"ignored": True, "reason": "duplicate_link"}

        if not service.get("api_url") or not service.get("api_key"):
            add_failed_order(order_id, advert_id, service_name, "Panel bilgileri eksik", service.get("panel_key", ""))
            send_telegram(f"Panel bilgileri eksik.\n\nSipariş ID: {order_id}\nÜrün: {service_name}\nPanel: {service['panel']}\n\nRender Environment ayarlarını kontrol et.")
            return {"ok": False, "error": "panel_config_missing"}

        balance_data = panel_balance(service["api_url"], service["api_key"], service.get("panel", ""))

        if "error" in balance_data:
            add_failed_order(order_id, advert_id, service_name, "Panel bakiyesi alınamadı", balance_data.get("error"))
            notify_customer_order_failed(order_id, service_name)
            send_telegram(f"Panel bakiyesi alınamadı.\n\nSipariş ID: {order_id}\nHata: {balance_data.get('error')}")
            return {"ok": False, "error": "balance_failed"}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")
        check_low_balance(balance, currency, service["panel"])

        smm_result = create_panel_order(service["api_url"], service["api_key"],
                                        service["service_id"], customer_link, service["quantity"], service.get("panel", ""))

        if "error" in smm_result:
            add_failed_order(order_id, advert_id, service_name, "Panel sipariş hatası", smm_result.get("error"))
            notify_customer_order_failed(order_id, service_name)
            send_telegram(f"Panel siparişi başarısız.\n\nSipariş ID: {order_id}\nHata: {smm_result.get('error')}")
            return {"ok": False, "error": "panel_order_error"}

        smm_order_id = smm_result.get("order", "Bilinmiyor")

        PROCESSED_LINKS.add(duplicate_link_key)
        PROCESSED_ORDERS.add(order_key)
        add_pending_order(
            order_id,
            advert_id,
            service_name,
            service["panel"],
            service["api_url"],
            service["api_key"],
            smm_order_id,
            customer_link,
            service_id=service.get("service_id", ""),
            quantity=service.get("quantity", ""),
            platform=service.get("platform", ""),
            panel_key=service.get("panel_key", ""),
            price=price,
        )
        save_state()

        # YENİ: Müşteriye sipariş başladı bildirimi
        notify_customer_order_started(order_id, service_name, customer_link)

        send_telegram(
            f"SMM siparişi panele girildi.\n\nÜrün: {service_name}\nPanel: {service['panel']}\n"
            f"Itemsatış ID: {order_id}\nSMM ID: {smm_order_id}\nLink: {customer_link}\n"
            f"Adet: {service['quantity']}\nBakiye: {format_tl_amount(convert_balance_to_try(balance, currency) or 0)}"
        )

        return {"ok": True, "type": "smm_order", "smm_order_id": smm_order_id}

    log("info", "webhook_unmatched", advert_id=advert_id, product=product_name)
    return {"ignored": True, "product": product_name, "advert_id": advert_id}


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "").strip()
    command = text.split()[0].split("@")[0].lower() if text else ""
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != str(CHAT_ID):
        return {"ignored": True, "reason": "unauthorized_chat"}

    log("info", "telegram_command", command=text[:50])

    if command in ["/start", "/help"]:
        send_telegram(
            "Bot komutları:\n\n"
            "/panels - Ekli panelleri göster\n"
            "/balance - Tüm panel bakiyeleri\n"
            "/balance paneladi - Seçili panel bakiyesi\n"
            "/balance-all - Tüm panel bakiyeleri\n"
            "/medyabalance - MedyaBayim bakiyesi\n"
            "/status - Bot durumu\n"
            "/health - Sistem durumu\n"
            "/failed - Başarısız siparişler\n"
            "/pending - Bekleyen siparişler\n"
            "/services - Servis eşleştirmeleri\n"
            "/admin - Web servis yönetim paneli\n"
            "/cancel smm_id - Siparişi iptal et\n"
            "/blacklist add değer - Kara listeye ekle\n"
            "/blacklist remove değer - Kara listeden çıkar\n"
            "/blacklist list - Kara listeyi göster\n"
            "/report - Bugünkü özet\n"
            "/week-report - Haftalık özet\n"
            "/month-report - Aylık özet\n"
            "/report-all - Tüm özetler\n"
            "/reset-report - Bu ayın rapor/dashboard verilerini sıfırla\n"
            "/reset-all-reports - Tüm raporları sıfırla\n"
            "/help - Komutları gösterir"
        )
        return {"ok": True}

    if command == "/status":
        send_telegram("Bot aktif çalışıyor.\n\nRender: Aktif\nTelegram: Aktif\nItemsatış Webhook: Aktif")
        return {"ok": True}

    if command == "/panels":
        send_telegram(build_panels_list_text())
        return {"ok": True}

    if command == "/services":
        send_telegram(build_services_list_text())
        return {"ok": True}

    if command == "/balance":
        balance_text = text
        if text.split()[0].startswith("/balance@"):
            balance_text = "/balance" + (" " + " ".join(text.split()[1:]) if len(text.split()) > 1 else "")
        handle_panel_balance_command(balance_text)
        return {"ok": True}

    if command == "/balance-all":
        handle_panel_balance_command("/balance all")
        return {"ok": True}

    if command == "/medyabalance":
        handle_panel_balance_command("/balance medyabayim")
        return {"ok": True}

    if command == "/health":
        redis_t = "Redis: Aktif" if UPSTASH_REDIS_REST_URL else "Redis: Eksik"
        panel_lines = []
        for key in PANEL_MAP.keys():
            panel = get_panel_config(key)
            if not is_panel_configured(key):
                panel_lines.append(f"{panel['name']}: Eksik")
                continue
            balance_data = panel_balance(panel["api_url"], panel["api_key"])
            if "error" in balance_data:
                panel_lines.append(f"{panel['name']}: Hatalı - {balance_data.get('error')}")
            else:
                panel_lines.append(f"{panel['name']}: Aktif - {format_panel_balance_tl(balance_data)}")

        panel_text = "\n".join(panel_lines)
        send_telegram(
            f"Sistem Durumu\n\nBot: Aktif\n{redis_t}\n{panel_text}\n\n"
            f"Başarısız: {len(FAILED_ORDERS)}\nBekleyen: {len(PENDING_ORDERS)}"
        )
        return {"ok": True}

    if command == "/failed":
        if not FAILED_ORDERS:
            send_telegram("Başarısız sipariş yok.")
            return {"ok": True}
        lines = ["Başarısız Siparişler:\n"]
        for item in FAILED_ORDERS[-10:]:
            lines.append(
                f"ID: {item.get('order_id', 'Bilinmiyor')}\n"
                f"Ürün: {item.get('product_name', 'Bilinmiyor')}\n"
                f"Panel: {item.get('panel', '-')}\n"
                f"SMM ID: {item.get('smm_order_id', '-')}\n"
                f"Sebep: {item.get('reason', '-')}\n"
                f"Retry: {'Uygun' if item.get('retryable') and not item.get('retried') else 'Yok'}\n"
            )
        send_telegram("\n".join(lines))
        return {"ok": True}

    if command == "/pending":
        if not PENDING_ORDERS:
            send_telegram("Bekleyen sipariş yok.")
            return {"ok": True}
        lines = ["Bekleyen Siparişler:\n"]
        for item in PENDING_ORDERS[-10:]:
            created_at = int(item.get("created_at", 0))
            waited_minutes = int((time.time() - created_at) / 60) if created_at else 0
            cancelled = " [İPTAL EDİLDİ]" if item.get("cancelled") else ""
            lines.append(f"Ürün: {item['product_name']}{cancelled}\nSMM ID: {item['smm_order_id']}\nBekleme: {waited_minutes}dk\nLink: {item['link']}\n")
        send_telegram("\n".join(lines))
        return {"ok": True}

    # YENİ: /cancel komutu
    if command == "/cancel":
        handle_cancel_command(text)
        return {"ok": True}


    if command == "/blacklist":
        parts = text.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "list"
        if action == "list":
            if not BLACKLIST:
                send_telegram("Kara liste boş.")
            else:
                send_telegram("Kara Liste:\n" + "\n".join(f"- {item}" for item in sorted(BLACKLIST)))
            return {"ok": True}
        if len(parts) < 3:
            send_telegram("Kullanım: /blacklist add değer veya /blacklist remove değer")
            return {"ok": True}
        value = parts[2].strip()
        if action == "add":
            blacklist_add(value)
            send_telegram(f"Kara listeye eklendi: {value}")
            return {"ok": True}
        if action == "remove":
            blacklist_remove(value)
            send_telegram(f"Kara listeden çıkarıldı: {value}")
            return {"ok": True}
        send_telegram("Kullanım: /blacklist add/remove/list")
        return {"ok": True}

    if command == "/report":
        send_telegram(build_sales_report("Bugünkü Sipariş Özeti", DAILY_STATS, "Bugün sipariş yok."))
        return {"ok": True}

    if command == "/week-report":
        send_telegram(build_sales_report("Haftalık Özet", WEEKLY_STATS, "Bu hafta sipariş yok."))
        return {"ok": True}

    if command == "/month-report":
        send_telegram(build_sales_report("Aylık Özet", MONTHLY_STATS, "Bu ay sipariş yok."))
        return {"ok": True}

    if command == "/report-all":
        daily = build_sales_report("Bugünkü Özet", DAILY_STATS, "Bugün sipariş yok.")
        weekly = build_sales_report("Haftalık Özet", WEEKLY_STATS, "Bu hafta sipariş yok.")
        monthly = build_sales_report("Aylık Özet", MONTHLY_STATS, "Bu ay sipariş yok.")
        send_telegram(daily + "\n\n---\n\n" + weekly + "\n\n---\n\n" + monthly)
        return {"ok": True}

    if command == "/reset-report":
        reset_sales_stats("current_month")
        send_telegram("Bu ayın rapor ve dashboard verileri sıfırlandı.")
        return {"ok": True}

    if command == "/reset-week-report":
        reset_sales_stats("weekly")
        send_telegram("Haftalık rapor sıfırlandı.")
        return {"ok": True}

    if command == "/reset-month-report":
        reset_sales_stats("monthly")
        send_telegram("Aylık rapor ve dashboard verileri sıfırlandı.")
        return {"ok": True}

    if command == "/reset-all-reports":
        reset_sales_stats("all")
        send_telegram("Tüm raporlar sıfırlandı.")
        return {"ok": True}

    send_telegram("Bilinmeyen komut. /help ile komutları gör.")
    return {"ok": True}
