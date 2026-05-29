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
import html
import requests
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
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

app = FastAPI(title="Boostera API", description="Boostera private SMM automation panel", version="2.0.0", docs_url=None, redoc_url=None)
security = HTTPBasic()

# Optional favicon/static assets. If the static folder is not in the repo, bot still starts.
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
CHAT_ID_ERRORS = os.getenv("CHAT_ID_ERRORS", "") or CHAT_ID
CHAT_ID_SALES = os.getenv("CHAT_ID_SALES", "") or CHAT_ID
CHAT_ID_ALERTS = os.getenv("CHAT_ID_ALERTS", "") or CHAT_ID
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
REQUIRE_WEBHOOK_SECRET = os.getenv("REQUIRE_WEBHOOK_SECRET", "false").lower() == "true"
WEBHOOK_IP_WHITELIST = [ip.strip() for ip in os.getenv("WEBHOOK_IP_WHITELIST", "").split(",") if ip.strip()]
STATE_LOCK = threading.RLock()
TR_TIMEZONE = timezone(timedelta(hours=3))


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
ITEMSATIS_PROFILE_URL = os.getenv("ITEMSATIS_PROFILE_URL", "").strip()
ITEMSATIS_ADVERT_CACHE_KEY = os.getenv("ITEMSATIS_ADVERT_CACHE_KEY", "itemsatis_advert_cache")
ITEMSATIS_ADVERT_MANUAL_KEY = os.getenv("ITEMSATIS_ADVERT_MANUAL_KEY", "itemsatis_advert_manual_items")
ITEMSATIS_PROFILE_URL_OVERRIDE_KEY = os.getenv("ITEMSATIS_PROFILE_URL_OVERRIDE_KEY", "itemsatis_profile_url_override")
ITEMSATIS_ADVERT_CACHE_MAX_AGE_SEC = int(os.getenv("ITEMSATIS_ADVERT_CACHE_MAX_AGE_SEC", "21600"))
ITEMSATIS_ADVERT_MAX_PAGES = int(os.getenv("ITEMSATIS_ADVERT_MAX_PAGES", "12"))
ITEMSATIS_EXPECTED_ADVERT_COUNT = int(os.getenv("ITEMSATIS_EXPECTED_ADVERT_COUNT", "0"))
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

SMM_SERVICE_MAP = {}

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
FAVORITE_SERVICES = {}
BALANCE_HISTORY = {}
LINK_AUDIT_HISTORY = []

# ─── YENİ: LOG GEÇMİŞİ (son 200 log dashboard için) ───────────────────────────
MAX_LOG_HISTORY = 200
LOG_HISTORY = deque(maxlen=MAX_LOG_HISTORY)
_RATE_LIMIT_STORE = defaultdict(list)
MESSAGE_TEMPLATES = {}
BALANCE_WARN_LAST = {}
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

# Anti-loss ve toplu retry ayarları
ANTI_LOSS_ENABLED = os.getenv("ANTI_LOSS_ENABLED", "true").lower() == "true"
ANTI_LOSS_MIN_PROFIT_TL = float(os.getenv("ANTI_LOSS_MIN_PROFIT_TL", "0"))
ANTI_LOSS_MIN_PROFIT_PERCENT = float(os.getenv("ANTI_LOSS_MIN_PROFIT_PERCENT", "0"))
ANTI_LOSS_BLOCK_UNKNOWN_COST = os.getenv("ANTI_LOSS_BLOCK_UNKNOWN_COST", "true").lower() == "true"
BULK_RETRY_MAX = int(os.getenv("BULK_RETRY_MAX", "30"))
BULK_RETRY_DELAY_SECONDS = float(os.getenv("BULK_RETRY_DELAY_SECONDS", "2"))
BALANCE_WARN_REPEAT_MINUTES = int(os.getenv("BALANCE_WARN_REPEAT_MINUTES", "60"))
BALANCE_WARN_THRESHOLD_TL = float(os.getenv("BALANCE_WARN_THRESHOLD_TL", "100"))
# Örn Render env: LOW_BALANCE_DISABLED_PANELS=morethanpanel
LOW_BALANCE_DISABLED_PANELS = {
    p.strip().lower()
    for p in os.getenv("LOW_BALANCE_DISABLED_PANELS", "").split(",")
    if p.strip()
}
LOW_BALANCE_WARN_REPEAT_MINUTES_BY_PANEL = {
    part.split(":", 1)[0].strip().lower(): int(part.split(":", 1)[1].strip())
    for part in os.getenv("LOW_BALANCE_WARN_REPEAT_MINUTES_BY_PANEL", "").split(",")
    if ":" in part and part.split(":", 1)[0].strip() and part.split(":", 1)[1].strip().isdigit()
}

CHECK_BALANCE_INTERVAL_SECONDS = int(os.getenv("CHECK_BALANCE_INTERVAL_SECONDS", "300"))
VIP_ORDER_THRESHOLD = int(os.getenv("VIP_ORDER_THRESHOLD", "5"))
PROFIT_TARGET_MARGIN_PERCENT = float(os.getenv("PROFIT_TARGET_MARGIN_PERCENT", "30"))
PROFIT_MIN_TL = float(os.getenv("PROFIT_MIN_TL", "2"))
HIGH_VALUE_ORDER_TL = float(os.getenv("HIGH_VALUE_ORDER_TL", "250"))
PRODUCT_HEALTH_MIN_MARGIN_PERCENT = float(os.getenv("PRODUCT_HEALTH_MIN_MARGIN_PERCENT", "18"))
BLACKLIST_AUTO_LEARN = os.getenv("BLACKLIST_AUTO_LEARN", "true").lower() == "true"
BLACKLIST_AUTO_FAIL_COUNT = int(os.getenv("BLACKLIST_AUTO_FAIL_COUNT", "2"))
_BULK_RETRY_LOCK = threading.Lock()
_BACKGROUND_TASKS = {}
PANEL_STATS = {}
SERVICE_COMPLETION_STATS = {}
BUYER_STATS = {}
ORDER_NOTES = {}
LINK_FAIL_COUNT = {}
PROCESSED_ORDERS_MAX = int(os.getenv("PROCESSED_ORDERS_MAX", "3000"))
PROCESSED_LINKS_MAX = int(os.getenv("PROCESSED_LINKS_MAX", "3000"))

# ─── PROFESYONEL PANEL DAYANIKLILIĞI: CIRCUIT BREAKER + REDIS QUEUE ──────────
CIRCUIT_THRESHOLD = int(os.getenv("CIRCUIT_THRESHOLD", "3"))
CIRCUIT_RECOVERY_SEC = int(os.getenv("CIRCUIT_RECOVERY_SEC", "600"))

ITEMSATIS_WEBHOOK_QUEUE_KEY = os.getenv("ITEMSATIS_WEBHOOK_QUEUE_KEY", "queue:itemsatis:webhooks")
ITEMSATIS_WEBHOOK_PROCESSING_KEY = os.getenv("ITEMSATIS_WEBHOOK_PROCESSING_KEY", "queue:itemsatis:processing")
ITEMSATIS_WEBHOOK_DEAD_KEY = os.getenv("ITEMSATIS_WEBHOOK_DEAD_KEY", "queue:itemsatis:dead")

QUEUE_ITEM_MAX_ATTEMPTS = int(os.getenv("QUEUE_ITEM_MAX_ATTEMPTS", "5"))
QUEUE_WORKER_SLEEP_SEC = float(os.getenv("QUEUE_WORKER_SLEEP_SEC", "2"))
QUEUE_RETRY_DELAY_SEC = int(os.getenv("QUEUE_RETRY_DELAY_SEC", "120"))
QUEUE_CIRCUIT_RETRY_DELAY_SEC = int(os.getenv("QUEUE_CIRCUIT_RETRY_DELAY_SEC", "600"))
QUEUE_STUCK_RECOVERY_SEC = int(os.getenv("QUEUE_STUCK_RECOVERY_SEC", "600"))

QUEUE_CONTEXT = threading.local()


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
    if REQUIRE_WEBHOOK_SECRET and not WEBHOOK_SECRET_TOKEN and "WEBHOOK_SECRET_TOKEN" not in missing:
        missing.append("WEBHOOK_SECRET_TOKEN")
    if missing:
        try:
            logger.warning("environment_missing_or_unsafe", missing=missing)
        except Exception:
            print("ENV WARNING:", missing, flush=True)
    if not WEBHOOK_SECRET_TOKEN:
        try:
            logger.warning("webhook_secret_token_empty", message="Üretimde WEBHOOK_SECRET_TOKEN tanımlaman önerilir.")
        except Exception:
            pass
    return missing


def get_request_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def check_rate_limit(ip: str, limit: int = 60, window: int = 60) -> bool:
    """Basit bellek içi rate-limit. Render tek worker kullanımında yeterlidir."""
    if not ip:
        return True
    now_ts = time.time()
    cutoff = now_ts - window
    with STATE_LOCK:
        recent = [t for t in _RATE_LIMIT_STORE[ip] if t > cutoff]
        _RATE_LIMIT_STORE[ip] = recent
        if len(recent) >= limit:
            return False
        _RATE_LIMIT_STORE[ip].append(now_ts)
        return True


def is_webhook_authorized(request: Request) -> bool:
    """Webhook güvenliği: opsiyonel IP whitelist + opsiyonel token + basit rate limit."""
    client_ip = get_request_ip(request)

    if WEBHOOK_IP_WHITELIST and client_ip not in WEBHOOK_IP_WHITELIST:
        log("warning", "webhook_ip_blocked", ip=client_ip)
        return False

    if not check_rate_limit(client_ip, limit=120, window=60):
        log("warning", "webhook_rate_limited", ip=client_ip)
        return False

    if not WEBHOOK_SECRET_TOKEN:
        if REQUIRE_WEBHOOK_SECRET:
            log("warning", "webhook_secret_required_but_missing", ip=client_ip)
            return False
        return True

    provided = (
        request.headers.get("X-Webhook-Token")
        or request.headers.get("X-Boostera-Token")
        or request.query_params.get("token")
        or ""
    )
    return secrets.compare_digest(str(provided), WEBHOOK_SECRET_TOKEN)


def now_tr():
    return datetime.now(TR_TIMEZONE)


# ─── YENİ: GELİŞMİŞ LOGLAMA ──────────────────────────────────────────────────
def flush_logs(force: bool = False):
    """Log geçmişini Redis'e kontrollü yazar; her logda Redis yazıp yavaşlatmaz."""
    global _LOG_DIRTY, _LOG_LAST_FLUSH
    if not force and not _LOG_DIRTY:
        return
    now_ts = time.time()
    if force or (now_ts - _LOG_LAST_FLUSH) >= LOG_FLUSH_INTERVAL_SECONDS:
        redis_set_json("log_history", list(LOG_HISTORY)[-MAX_LOG_HISTORY:])
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
        _LOG_DIRTY = True

    # Sadece aralık dolduysa Redis'e yaz.
    try:
        flush_logs(force=False)
    except Exception:
        pass


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def _send_telegram_to(text: str, chat_id: str, channel: str = "default") -> bool:
    """Telegram mesajı gönderir. parse_mode kullanmaz; < > karakterleri mesajı bozmaz.
    Başarılıysa True döner; alert fallback için kullanılır.
    """
    if not BOT_TOKEN or not chat_id:
        log("warning", "telegram_skip", reason="BOT_TOKEN veya chat_id eksik", channel=channel)
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        log("info", "telegram_sent", status=r.status_code, channel=channel)
        return 200 <= int(r.status_code) < 300
    except Exception as e:
        log("error", "telegram_error", error=str(e), channel=channel)
        return False


def send_telegram(text: str):
    _send_telegram_to(text, CHAT_ID, "main")


def send_telegram_error(text: str):
    _send_telegram_to(text, CHAT_ID_ERRORS, "errors")


def send_telegram_sale(text: str):
    _send_telegram_to(text, CHAT_ID_SALES, "sales")


def send_telegram_alert(text: str):
    # CHAT_ID_ALERTS yanlış/boş ise ana CHAT_ID'ye düşer; düşük bakiye uyarıları kaybolmaz.
    ok = _send_telegram_to(text, CHAT_ID_ALERTS, "alerts")
    if not ok and CHAT_ID_ALERTS != CHAT_ID:
        _send_telegram_to(text, CHAT_ID, "main_alert_fallback")


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


DEFAULT_MESSAGE_TEMPLATES = {
    "started": (
        "Merhaba! '{product}' siparişiniz alındı ve işleme girdi.\n\n"
        "Hesabınız: {link}\n\n"
        "Siparişiniz genellikle 0-24 saat içinde tamamlanmaya başlar. Teşekkürler."
    ),
    "completed": (
        "Merhaba! '{product}' siparişiniz tamamlandı! 🎉\n\n"
        "Hesabınız: {link}\n\n"
        "Memnun kaldıysanız değerlendirme bırakırsanız çok seviniriz. Tekrar alışveriş için görüşmek üzere."
    ),
    "failed": (
        "Merhaba! '{product}' siparişinizde teknik bir sorun yaşandı. "
        "En kısa sürede çözüp siparişinizi işleme alacağız. Rahatsızlık için özür dileriz."
    ),
}


def render_customer_template(key: str, **kwargs) -> str:
    template = str(MESSAGE_TEMPLATES.get(key) or DEFAULT_MESSAGE_TEMPLATES.get(key) or "")
    try:
        return template.format(**kwargs)
    except Exception:
        return DEFAULT_MESSAGE_TEMPLATES.get(key, "").format(**kwargs)


def notify_customer_order_started(order_id: str, product_name: str, link: str):
    """Sipariş panele girilince müşteriye bildirim gönder."""
    message = render_customer_template("started", product=product_name, link=link, order_id=order_id)
    return send_itemsatis_message(order_id, message)


def notify_customer_order_completed(order_id: str, product_name: str, link: str):
    """Sipariş tamamlanınca müşteriye bildirim gönder."""
    message = render_customer_template("completed", product=product_name, link=link, order_id=order_id)
    return send_itemsatis_message(order_id, message)


def notify_customer_order_failed(order_id: str, product_name: str):
    """Sipariş başarısız olunca müşteriye bildirim gönder."""
    message = render_customer_template("failed", product=product_name, link="", order_id=order_id)
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
        if r.status_code >= 400:
            logger.error("redis_http_error", status=r.status_code, response=r.text[:300])
            return None
        try:
            result = r.json()
        except Exception as e:
            logger.error("redis_json_error", error=str(e), response=r.text[:300])
            return None
        if isinstance(result, dict) and result.get("error"):
            logger.error("redis_command_error", error=str(result.get("error"))[:300], command=str(command)[:120])
            return None
        return result
    except Exception as e:
        try:
            logger.error("redis_error", error=str(e))
        except Exception:
            print("REDIS ERROR:", str(e), flush=True)
        return None


def redis_response_ok(result) -> bool:
    return isinstance(result, dict) and not result.get("error")


def redis_set_succeeded(result) -> bool:
    return redis_response_ok(result) and str(result.get("result", "")).upper() == "OK"


def redis_lpush_succeeded(result) -> bool:
    if not redis_response_ok(result):
        return False
    try:
        return int(result.get("result", 0) or 0) > 0
    except Exception:
        return False


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


def redis_mset_json(data_dict: dict):
    """Birden fazla state alanını tek Redis MSET isteğiyle yazar.
    Redis yoksa veya hata olursa botu düşürmez.
    """
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None

    try:
        command = ["MSET"]
        for key, value in data_dict.items():
            command.extend([key, json.dumps(value, ensure_ascii=False)])
        return redis_request(command)
    except Exception as e:
        try:
            logger.error("redis_mset_error", error=str(e))
        except Exception:
            print("REDIS MSET ERROR:", str(e), flush=True)
        return None



# ─── PROFESYONEL PANEL DAYANIKLILIĞI: REDIS RAW HELPERS ──────────────────────
def redis_command_result(command, default=None):
    """redis_request(command) cevabındaki result alanını güvenli döndürür."""
    try:
        result = redis_request(command)
        if not isinstance(result, dict):
            return default
        return result.get("result", default)
    except Exception as e:
        log("error", "redis_command_result_error", command=str(command)[:120], error=str(e))
        return default


def redis_get_raw(key: str, default=None):
    return redis_command_result(["GET", key], default)


def redis_set_raw(key: str, value, ex: int | None = None, nx: bool = False):
    command = ["SET", key, str(value)]
    if ex:
        command.extend(["EX", int(ex)])
    if nx:
        command.append("NX")
    return redis_request(command)


def redis_delete_key(key: str):
    return redis_request(["DEL", key])


def redis_lpush_json(key: str, value: dict):
    return redis_request(["LPUSH", key, json.dumps(value, ensure_ascii=False, default=str)])


def redis_lrem_value(key: str, raw_value: str):
    return redis_request(["LREM", key, 1, raw_value])


def redis_lrange_raw(key: str, start: int = 0, end: int = -1):
    result = redis_command_result(["LRANGE", key, start, end], [])
    return result if isinstance(result, list) else []


def redis_llen(key: str) -> int:
    try:
        return int(redis_command_result(["LLEN", key], 0) or 0)
    except Exception:
        return 0


def redis_rpoplpush_raw(src_key: str, dst_key: str):
    return redis_command_result(["RPOPLPUSH", src_key, dst_key], None)


class CircuitOpenForOrder(Exception):
    """Webhook worker içinde panel geçici kapalıysa siparişi failed'a düşürmeden requeue eder."""
    def __init__(self, panel_name: str, message: str = "", retry_after: int | None = None):
        self.panel_name = str(panel_name or "unknown")
        self.retry_after = int(retry_after or QUEUE_CIRCUIT_RETRY_DELAY_SEC)
        super().__init__(message or f"Panel circuit open: {self.panel_name}")


def _queue_context_active() -> bool:
    return bool(getattr(QUEUE_CONTEXT, "active", False))


def circuit_failures_key(panel_name: str) -> str:
    return f"circuit:{normalize_panel_key(panel_name or 'unknown')}:failures"


def circuit_open_until_key(panel_name: str) -> str:
    return f"circuit:{normalize_panel_key(panel_name or 'unknown')}:opened_until"


def is_panel_circuit_open(panel_name: str) -> bool:
    """Panel circuit breaker açık mı? True ise panele istek atılmaz."""
    panel_name = normalize_panel_key(panel_name or "unknown")
    try:
        opened_until_raw = redis_get_raw(circuit_open_until_key(panel_name), "")
        if not opened_until_raw:
            return False
        opened_until = int(opened_until_raw)
        now_ts = int(time.time())
        if opened_until > now_ts:
            return True
        redis_delete_key(circuit_open_until_key(panel_name))
        redis_delete_key(circuit_failures_key(panel_name))
        log("info", "circuit_auto_recovered", panel=panel_name)
        return False
    except Exception as e:
        log("error", "circuit_check_error", panel=panel_name, error=str(e))
        return False


def get_panel_circuit_retry_after(panel_name: str) -> int:
    try:
        opened_until = int(redis_get_raw(circuit_open_until_key(panel_name), "0") or 0)
        return max(QUEUE_RETRY_DELAY_SEC, opened_until - int(time.time()))
    except Exception:
        return QUEUE_CIRCUIT_RETRY_DELAY_SEC


def record_panel_failure(panel_name: str, reason: str = ""):
    """Panel bağlantı/timeout/5xx hatalarında hata sayacını artırır."""
    panel_name = normalize_panel_key(panel_name or "unknown")
    try:
        key = circuit_failures_key(panel_name)
        failures = int(redis_get_raw(key, "0") or 0) + 1
        redis_set_raw(key, failures, ex=max(CIRCUIT_RECOVERY_SEC * 2, 1200))
        log("warning", "panel_failure_recorded", panel=panel_name, failures=failures, reason=str(reason)[:240])
        if failures >= CIRCUIT_THRESHOLD:
            opened_until = int(time.time()) + CIRCUIT_RECOVERY_SEC
            already_open = is_panel_circuit_open(panel_name)
            redis_set_raw(circuit_open_until_key(panel_name), opened_until, ex=CIRCUIT_RECOVERY_SEC + 120)
            if not already_open:
                send_telegram_error(
                    f"🚨 Panel geçici kapatıldı\n\n"
                    f"Panel: {panel_name}\n"
                    f"Hata sayısı: {failures}\n"
                    f"Süre: {CIRCUIT_RECOVERY_SEC // 60} dakika\n\n"
                    f"Bu panele yeni sipariş gönderilmeyecek. Webhook siparişleri failed yerine kuyruğa alınacak."
                )
    except Exception as e:
        log("error", "record_panel_failure_error", panel=panel_name, error=str(e))


def record_panel_success(panel_name: str):
    """Panel başarılı cevap verirse circuit sayaçlarını sıfırlar."""
    panel_name = normalize_panel_key(panel_name or "unknown")
    try:
        had_failures = redis_get_raw(circuit_failures_key(panel_name), "")
        had_open = redis_get_raw(circuit_open_until_key(panel_name), "")
        redis_delete_key(circuit_failures_key(panel_name))
        redis_delete_key(circuit_open_until_key(panel_name))
        if had_failures or had_open:
            log("success", "circuit_reset", panel=panel_name)
    except Exception as e:
        log("error", "record_panel_success_error", panel=panel_name, error=str(e))


def enqueue_itemsatis_webhook(data: dict, *, attempts: int = 0, queue_id: str = "", not_before: int = 0, last_error: str = "") -> str:
    """Itemsatış payload'unu Redis kuyruğuna yazar. Render restart olsa bile sipariş kaybolmaz."""
    if not isinstance(data, dict):
        data = {"raw_payload": str(data)}
    if not queue_id:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
        queue_id = hashlib.sha1(f"{time.time()}:{raw}".encode("utf-8", errors="ignore")).hexdigest()[:20]
    item = {
        "id": queue_id,
        "created_at": int(time.time()),
        "attempts": int(attempts or 0),
        "not_before": int(not_before or 0),
        "last_error": str(last_error or "")[:500],
        "payload": data,
    }
    result = redis_lpush_json(ITEMSATIS_WEBHOOK_QUEUE_KEY, item)
    if not redis_lpush_succeeded(result):
        log("error", "itemsatis_webhook_queue_write_failed", queue_id=queue_id, redis_result=str(result)[:300])
        raise RuntimeError("Itemsatis webhook Redis kuyruğuna yazılamadı")
    log("info", "itemsatis_webhook_queued", queue_id=queue_id, attempts=attempts, not_before=not_before)
    return queue_id


def push_itemsatis_queue_item(item: dict, event: str = "itemsatis_queue_requeued") -> bool:
    """Var olan queue item'ını ana kuyruğa güvenli döndürür; Redis yazımı doğrulanmadan başarılı saymaz."""
    safe_item = item if isinstance(item, dict) else {"payload": item}
    result = redis_lpush_json(ITEMSATIS_WEBHOOK_QUEUE_KEY, safe_item)
    if redis_lpush_succeeded(result):
        log("info", event, queue_id=safe_item.get("id"), attempts=safe_item.get("attempts"))
        return True
    log("error", "itemsatis_queue_requeue_failed", queue_id=safe_item.get("id"), event=event, redis_result=str(result)[:300])
    send_telegram_error(
        f"Itemsatış kuyruğuna yeniden yazma başarısız.\n\n"
        f"Queue ID: {safe_item.get('id', '-')}\n"
        f"İşlem: {event}\n"
        f"Redis sonucu: {str(result)[:300]}"
    )
    return False


def move_queue_item_to_dead(item: dict, reason: str):
    item = item if isinstance(item, dict) else {"payload": item}
    item["dead_at"] = int(time.time())
    item["dead_reason"] = str(reason)[:500]
    redis_lpush_json(ITEMSATIS_WEBHOOK_DEAD_KEY, item)
    log("error", "itemsatis_queue_dead", queue_id=item.get("id"), reason=reason)


def recover_stuck_itemsatis_processing():
    """Worker crash/restart sırasında processing listesinde kalan eski işleri ana kuyruğa geri taşır."""
    try:
        raw_items = redis_lrange_raw(ITEMSATIS_WEBHOOK_PROCESSING_KEY, 0, -1)
        now_ts = int(time.time())
        recovered = 0
        for raw in raw_items:
            try:
                item = json.loads(raw)
            except Exception:
                continue
            started_at = int(item.get("processing_started_at", item.get("created_at", 0)) or 0)
            if started_at and now_ts - started_at < QUEUE_STUCK_RECOVERY_SEC:
                continue
            item["attempts"] = int(item.get("attempts", 0) or 0) + 1
            item["not_before"] = now_ts + QUEUE_RETRY_DELAY_SEC
            item["last_error"] = "Recovered from stuck processing queue"
            if item["attempts"] >= QUEUE_ITEM_MAX_ATTEMPTS:
                move_queue_item_to_dead(item, "Max attempts after stuck recovery")
                redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
            else:
                if push_itemsatis_queue_item(item, "itemsatis_stuck_job_requeued"):
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
            recovered += 1
        if recovered:
            log("warning", "itemsatis_stuck_jobs_recovered", count=recovered)
    except Exception as e:
        log("error", "recover_stuck_processing_error", error=str(e))


async def itemsatis_queue_worker():
    """Redis tabanlı mini webhook worker. Ekstra paket istemez; siparişleri sırayla işler."""
    log("info", "itemsatis_queue_worker_started")
    recover_stuck_itemsatis_processing()
    last_stuck_recovery = int(time.time())
    while True:
        try:
            now_loop = int(time.time())
            if now_loop - last_stuck_recovery >= max(60, int(QUEUE_STUCK_RECOVERY_SEC / 2)):
                recover_stuck_itemsatis_processing()
                last_stuck_recovery = now_loop
            raw = redis_rpoplpush_raw(ITEMSATIS_WEBHOOK_QUEUE_KEY, ITEMSATIS_WEBHOOK_PROCESSING_KEY)
            if not raw:
                await asyncio.sleep(QUEUE_WORKER_SLEEP_SEC)
                continue
            try:
                item = json.loads(raw)
            except Exception as e:
                redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                move_queue_item_to_dead({"raw": str(raw)[:1000]}, f"Queue JSON parse error: {e}")
                continue
            now_ts = int(time.time())
            not_before = int(item.get("not_before", 0) or 0)
            if not_before > now_ts:
                if push_itemsatis_queue_item(item, "itemsatis_not_before_requeued"):
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                await asyncio.sleep(min(QUEUE_WORKER_SLEEP_SEC + 3, max(1, not_before - now_ts)))
                continue
            item["processing_started_at"] = now_ts
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
            try:
                result = await asyncio.to_thread(process_itemsatis_webhook_payload, payload)
                redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                log("info", "itemsatis_queue_processed", queue_id=item.get("id"), result=str(result)[:300])
            except CircuitOpenForOrder as e:
                attempts = int(item.get("attempts", 0) or 0) + 1
                item["attempts"] = attempts
                item["not_before"] = int(time.time()) + int(e.retry_after)
                item["last_error"] = str(e)
                if attempts >= QUEUE_ITEM_MAX_ATTEMPTS:
                    move_queue_item_to_dead(item, f"Circuit open max attempts: {e}")
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                else:
                    if push_itemsatis_queue_item(item, "itemsatis_requeued_circuit_open"):
                        redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                        log("warning", "itemsatis_requeued_circuit_open", queue_id=item.get("id"), panel=e.panel_name, attempts=attempts)
            except Exception as e:
                attempts = int(item.get("attempts", 0) or 0) + 1
                item["attempts"] = attempts
                item["not_before"] = int(time.time()) + QUEUE_RETRY_DELAY_SEC
                item["last_error"] = str(e)
                if attempts >= QUEUE_ITEM_MAX_ATTEMPTS:
                    move_queue_item_to_dead(item, f"Max attempts: {e}")
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                    send_telegram_error(
                        f"Itemsatış queue dead\'e düştü.\n\n"
                        f"Queue ID: {item.get('id')}\n"
                        f"Deneme: {attempts}\n"
                        f"Hata: {str(e)[:500]}"
                    )
                else:
                    if push_itemsatis_queue_item(item, "itemsatis_requeued_error"):
                        redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                        log("warning", "itemsatis_requeued_error", queue_id=item.get("id"), attempts=attempts, error=str(e))
        except Exception as e:
            log("error", "itemsatis_queue_worker_error", error=str(e))
            send_telegram_error(f"Itemsatış queue worker kritik hata:\n{str(e)[:700]}")
            await asyncio.sleep(max(5, QUEUE_WORKER_SLEEP_SEC))


def read_queue_items(key: str, limit: int = 100) -> list:
    """Redis queue/list içeriğini admin ve API için güvenli şekilde okur."""
    rows = []
    raw_items = redis_lrange_raw(key, 0, max(0, int(limit or 100) - 1))
    for raw in raw_items:
        try:
            item = json.loads(raw)
        except Exception:
            item = {"id": "", "raw": str(raw)[:1000]}
        if isinstance(item, dict):
            item["_raw"] = raw
            rows.append(item)
    return rows


def build_queue_status() -> dict:
    """Itemsatış webhook queue derinliği ve circuit durumlarını döndürür."""
    circuits = []
    now_ts = int(time.time())

    for panel_key in PANEL_MAP.keys():
        panel_id = normalize_panel_key(panel_key)
        opened_until_raw = redis_get_raw(circuit_open_until_key(panel_id), "0") or "0"
        failures_raw = redis_get_raw(circuit_failures_key(panel_id), "0") or "0"

        try:
            opened_until = int(opened_until_raw or 0)
        except Exception:
            opened_until = 0

        try:
            failures = int(failures_raw or 0)
        except Exception:
            failures = 0

        circuits.append({
            "panel": panel_id,
            "open": opened_until > now_ts,
            "failures": failures,
            "opened_until": opened_until,
            "retry_after": max(0, opened_until - now_ts),
        })

    latest_waiting = read_queue_items(ITEMSATIS_WEBHOOK_QUEUE_KEY, 5)
    latest_processing = read_queue_items(ITEMSATIS_WEBHOOK_PROCESSING_KEY, 5)
    latest_dead = read_queue_items(ITEMSATIS_WEBHOOK_DEAD_KEY, 5)

    return {
        "ok": True,
        "time_tr": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "queue": {
            "waiting": redis_llen(ITEMSATIS_WEBHOOK_QUEUE_KEY),
            "processing": redis_llen(ITEMSATIS_WEBHOOK_PROCESSING_KEY),
            "dead": redis_llen(ITEMSATIS_WEBHOOK_DEAD_KEY),
        },
        "latest": {
            "waiting": [
                {
                    "id": item.get("id", ""),
                    "created_at": item.get("created_at", ""),
                    "attempts": item.get("attempts", 0),
                    "not_before": item.get("not_before", 0),
                    "last_error": item.get("last_error", ""),
                    "order_id": get_order_id(item.get("payload", {}) if isinstance(item.get("payload"), dict) else item),
                }
                for item in latest_waiting
            ],
            "processing": [
                {
                    "id": item.get("id", ""),
                    "created_at": item.get("created_at", ""),
                    "attempts": item.get("attempts", 0),
                    "processing_started_at": item.get("processing_started_at", ""),
                    "last_error": item.get("last_error", ""),
                    "order_id": get_order_id(item.get("payload", {}) if isinstance(item.get("payload"), dict) else item),
                }
                for item in latest_processing
            ],
            "dead": [
                {
                    "id": item.get("id", ""),
                    "created_at": item.get("created_at", ""),
                    "attempts": item.get("attempts", 0),
                    "dead_reason": item.get("dead_reason", ""),
                    "order_id": get_order_id(item.get("payload", {}) if isinstance(item.get("payload"), dict) else item),
                }
                for item in latest_dead
            ],
        },
        "circuits": circuits,
    }


def retry_dead_queue_item(queue_id: str = "", retry_all: bool = False) -> int:
    """Dead queue'dan seçili veya tüm işleri ana kuyruğa geri alır."""
    queue_id = str(queue_id or "").strip()
    moved = 0
    raw_items = redis_lrange_raw(ITEMSATIS_WEBHOOK_DEAD_KEY, 0, -1)

    for raw in raw_items:
        try:
            item = json.loads(raw)
        except Exception:
            continue

        item_id = str(item.get("id", "")).strip()
        if not retry_all and queue_id and item_id != queue_id:
            continue
        if not retry_all and not queue_id:
            continue

        item["attempts"] = 0
        item["not_before"] = 0
        item["last_error"] = f"Admin tarafından dead queue'dan tekrar kuyruğa alındı: {now_tr().strftime('%Y-%m-%d %H:%M:%S')}"
        item.pop("dead_at", None)
        item.pop("dead_reason", None)
        if push_itemsatis_queue_item(item, "dead_queue_requeued_by_admin"):
            redis_lrem_value(ITEMSATIS_WEBHOOK_DEAD_KEY, raw)
            moved += 1

    if moved:
        log("warning", "dead_queue_requeued_by_admin", queue_id=queue_id, retry_all=retry_all, moved=moved)

    return moved



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
    global RECORDED_SALES, LOG_HISTORY, PRODUCT_NAME_CACHE, PANEL_SERVICE_NAME_CACHE, DYNAMIC_SERVICES, PACKAGE_CONFIGS, SALES_HISTORY, ORDER_HISTORY, BLACKLIST, FAVORITE_SERVICES, BALANCE_HISTORY, LINK_AUDIT_HISTORY, MESSAGE_TEMPLATES, BALANCE_WARN_LAST, LOW_BALANCE_DISABLED_PANELS, PANEL_STATS, SERVICE_COMPLETION_STATS, BUYER_STATS, ORDER_NOTES, LINK_FAIL_COUNT

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
    LOG_HISTORY = deque(redis_get_json("log_history", [])[-MAX_LOG_HISTORY:], maxlen=MAX_LOG_HISTORY)
    PRODUCT_NAME_CACHE = redis_get_json("product_name_cache", {})
    PANEL_SERVICE_NAME_CACHE = redis_get_json("panel_service_name_cache", {})
    DYNAMIC_SERVICES = redis_get_json("dynamic_services", {})
    PACKAGE_CONFIGS = redis_get_json("package_configs", {})
    SALES_HISTORY = redis_get_json("sales_history", {})
    ORDER_HISTORY = redis_get_json("order_history", [])
    BLACKLIST = set(redis_get_json("blacklist", []))
    FAVORITE_SERVICES = redis_get_json("favorite_services", {})
    BALANCE_HISTORY = redis_get_json("balance_history", {})
    LINK_AUDIT_HISTORY = redis_get_json("link_audit_history", [])
    MESSAGE_TEMPLATES = redis_get_json("message_templates", {})
    BALANCE_WARN_LAST = redis_get_json("balance_warn_last", {})
    LOW_BALANCE_DISABLED_PANELS = set(redis_get_json("low_balance_disabled_panels", list(LOW_BALANCE_DISABLED_PANELS)))
    PANEL_STATS = redis_get_json("panel_stats", {})
    SERVICE_COMPLETION_STATS = redis_get_json("service_completion_stats", {})
    BUYER_STATS = redis_get_json("buyer_stats", {})
    ORDER_NOTES = redis_get_json("order_notes", {})
    LINK_FAIL_COUNT = redis_get_json("link_fail_count", {})
    trim_processed_memory()

    log("info", "state_loaded", pending=len(PENDING_ORDERS), failed=len(FAILED_ORDERS))


def save_state():
    """State verilerini tek Redis MSET isteğiyle kaydeder.
    Eski tek tek SET sistemine göre daha hızlıdır ve yarım kayıt riskini azaltır.
    """
    with STATE_LOCK:
        sanitize_pending_orders_for_storage()
        trim_processed_memory()

        data_to_save = {
            "recorded_sales": list(RECORDED_SALES),
            "processed_orders": list(PROCESSED_ORDERS),
            "processed_links": list(PROCESSED_LINKS),
            "failed_orders": FAILED_ORDERS,
            "pending_orders": PENDING_ORDERS,
            "daily_stats": DAILY_STATS,
            "last_daily_report_date": LAST_DAILY_REPORT_DATE,
            "service_price_cache": SERVICE_PRICE_CACHE,
            "weekly_stats": WEEKLY_STATS,
            "monthly_stats": MONTHLY_STATS,
            "last_weekly_report_date": LAST_WEEKLY_REPORT_DATE,
            "last_monthly_report_date": LAST_MONTHLY_REPORT_DATE,
            "product_name_cache": PRODUCT_NAME_CACHE,
            "panel_service_name_cache": PANEL_SERVICE_NAME_CACHE,
            "dynamic_services": DYNAMIC_SERVICES,
            "package_configs": PACKAGE_CONFIGS,
            "sales_history": SALES_HISTORY,
            "order_history": ORDER_HISTORY[-500:],
            "blacklist": list(BLACKLIST),
            "favorite_services": FAVORITE_SERVICES,
            "balance_history": BALANCE_HISTORY,
            "link_audit_history": LINK_AUDIT_HISTORY[-300:],
            "message_templates": MESSAGE_TEMPLATES,
            "balance_warn_last": BALANCE_WARN_LAST,
            "low_balance_disabled_panels": sorted(LOW_BALANCE_DISABLED_PANELS),
            "panel_stats": PANEL_STATS,
            "service_completion_stats": SERVICE_COMPLETION_STATS,
            "buyer_stats": BUYER_STATS,
            "order_notes": ORDER_NOTES,
            "link_fail_count": LINK_FAIL_COUNT,
        }

        result = redis_mset_json(data_to_save)
        if result is None:
            log("warning", "redis_mset_skipped_or_failed")

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


def cap_set_size(values, limit: int) -> set:
    """Processed order/link setlerinin Redis ve RAM'de sınırsız büyümesini engeller."""
    try:
        limit = max(100, int(limit or 3000))
        if not isinstance(values, set):
            values = set(values or [])
        if len(values) <= limit:
            return values
        return set(list(values)[-limit:])
    except Exception:
        return set(values or [])


def trim_processed_memory():
    global PROCESSED_ORDERS, PROCESSED_LINKS
    PROCESSED_ORDERS = cap_set_size(PROCESSED_ORDERS, PROCESSED_ORDERS_MAX)
    PROCESSED_LINKS = cap_set_size(PROCESSED_LINKS, PROCESSED_LINKS_MAX)


def is_valid_smm_order_id(value) -> bool:
    """Panelden gelen SMM order id gerçek mi? Bilinmiyor/boş değer pending'e girmemeli."""
    text = str(value or "").strip()
    if not text:
        return False
    bad_values = {"bilinmiyor", "none", "null", "false", "0", "-", "nan"}
    return text.lower() not in bad_values


def get_smm_order_id_from_result(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("order", "order_id", "id"):
        value = result.get(key)
        if is_valid_smm_order_id(value):
            return str(value).strip()
    return ""


def build_finance_summary(price_tl: float, cost_tl: float | None = None) -> str:
    """Telegram sipariş mesajları için satış / maliyet / kâr özeti üretir."""
    try:
        sale = float(price_tl or 0)
    except Exception:
        sale = 0.0

    if cost_tl is None:
        cost_tl = 0.0
    try:
        cost = float(cost_tl or 0)
    except Exception:
        cost = 0.0

    profit = calculate_profit(sale, cost)
    lines = [
        "💰 Finans Özeti:",
        f"Satış: {format_tl_amount(profit.get('sale_price', sale))}",
        f"Panel maliyeti: {format_tl_amount(profit.get('panel_cost', cost))}" if cost > 0 else "Panel maliyeti: Hesaplanamadı",
        f"Itemsatış komisyonu (%{int(ITEMSATIS_COMMISSION_RATE * 100)}): {format_tl_amount(profit.get('commission', 0))}" if sale > 0 else "Itemsatış komisyonu: Hesaplanamadı",
    ]
    if sale > 0 and cost > 0:
        lines.append(f"Net kâr: {format_tl_amount(profit.get('profit', 0))} | Marj: %{profit.get('margin_pct', 0)}")
        lines.append(build_pricing_advice(sale, cost))
    elif sale > 0:
        lines.append("Net kâr: Panel maliyeti bilinmediği için hesaplanamadı")
    return "\n".join(lines)


def build_buyer_summary(buyer: str) -> str:
    """Telegram sipariş mesajları için müşteri geçmişi özeti üretir."""
    buyer = str(buyer or "Bilinmiyor").strip() or "Bilinmiyor"
    stats = BUYER_STATS.get(buyer, {}) if isinstance(BUYER_STATS, dict) else {}
    try:
        count = int(stats.get("count", 0) or 0)
        total_spent = float(stats.get("total_spent", 0) or 0)
    except Exception:
        count, total_spent = 0, 0.0
    vip = "Evet" if count >= VIP_ORDER_THRESHOLD else "Hayır"
    return f"👤 Müşteri: {buyer}\nSipariş sayısı: {count}\nToplam harcama: {format_tl_amount(total_spent)}\nVIP: {vip}"


def estimate_order_cost_from_service(service: dict, quantity=None) -> float | None:
    """Servis config/cache üzerinden sipariş maliyetini TL tahmin eder."""
    if not isinstance(service, dict):
        return None
    panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
    service_id = str(service.get("service_id") or "").strip()
    qty = quantity if quantity is not None else service.get("quantity")
    if not panel_key or not service_id:
        return None
    rate = SERVICE_PRICE_CACHE.get(f"{panel_key}:{service_id}")
    if not rate:
        try:
            fetched = fetch_panel_service_rate(service)
            if fetched.get("ok"):
                rate = fetched.get("rate")
        except Exception as e:
            log("warning", "service_cost_estimate_failed", panel=panel_key, service_id=service_id, error=str(e))
            rate = None
    if not rate:
        return None
    return estimate_service_cost_tl(panel_key, rate, qty)


def estimate_package_cost_tl(components: list) -> float | None:
    total = 0.0
    found = False
    for component in components or []:
        try:
            service = get_service_config(normalize_package_component(component))
            cost = estimate_order_cost_from_service(service)
            if cost is not None:
                total += float(cost)
                found = True
        except Exception:
            continue
    return round(total, 4) if found else None


def add_failed_order(order_id, advert_id, product_name, reason, detail="", **extra):
    """Başarısız siparişi kaydeder. Retry için güvenli alanlar extra ile eklenebilir."""
    entry = {
        "order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "reason": str(reason),
        "detail": str(detail),
        "category": classify_failed_reason(reason, detail),
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
        # save_state burada çağrılmaz; record_itemsatis_sale tek sefer yazdırır.


def record_itemsatis_sale(data, order_id, advert_id, buyer, product_name, price, link="") -> bool:
    """Itemsatış satışını belleğe işler; kalıcı kayıt caller tarafından tek save_state ile yapılır."""
    global RECORDED_SALES
    sale_key = make_sale_key(data, order_id, advert_id, buyer, product_name, price, link)
    with STATE_LOCK:
        if sale_key in RECORDED_SALES:
            return False
        add_daily_stat(product_name, price)
        RECORDED_SALES.add(sale_key)
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


def add_order_history(order_id, advert_id, product_name, panel, smm_order_id, link, price=0, duration_minutes=None, estimated_completion_minutes=None):
    entry = {
        "order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "panel": str(panel),
        "smm_order_id": str(smm_order_id),
        "link": str(link),
        "price": float(price or 0),
        "duration_minutes": int(duration_minutes or 0) if duration_minutes is not None else "",
        "estimated_completion_minutes": float(estimated_completion_minutes or 0) if estimated_completion_minutes else "",
        "completed_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with STATE_LOCK:
        ORDER_HISTORY.append(entry)
        if len(ORDER_HISTORY) > 500:
            del ORDER_HISTORY[:-500]
        save_state()


def record_buyer_stats(buyer: str, price: float = 0):
    """Müşteri bazlı sipariş sayısı ve harcama istatistiği tutar."""
    global BUYER_STATS
    buyer = str(buyer or "Bilinmiyor").strip() or "Bilinmiyor"
    now_s = now_tr().strftime("%Y-%m-%d %H:%M:%S")
    item = BUYER_STATS.get(buyer, {}) if isinstance(BUYER_STATS, dict) else {}
    try:
        count = int(item.get("count", 0) or 0) + 1
        total_spent = float(item.get("total_spent", 0) or 0) + float(price or 0)
    except Exception:
        count, total_spent = 1, float(price or 0)
    BUYER_STATS[buyer] = {
        "count": count,
        "total_spent": round(total_spent, 2),
        "first_order": item.get("first_order") or now_s,
        "last_order": now_s,
    }
    if count == VIP_ORDER_THRESHOLD:
        send_telegram_sale(
            f"VIP müşteri eşiğine ulaştı.\n\n"
            f"Müşteri: {buyer}\n"
            f"Toplam sipariş: {count}\n"
            f"Toplam harcama: {format_tl_amount(total_spent)}"
        )


def update_panel_stats(panel_key: str, result: str, duration_minutes: int | None = None):
    """Panel bazında başarı/başarısız/partial istatistikleri tutar."""
    global PANEL_STATS
    panel_key = normalize_panel_key(panel_key or "unknown")
    item = PANEL_STATS.get(panel_key, {}) if isinstance(PANEL_STATS, dict) else {}
    item.setdefault("success", 0)
    item.setdefault("failed", 0)
    item.setdefault("partial", 0)
    item.setdefault("completed_total_minutes", 0)
    item.setdefault("completed_count", 0)
    item.setdefault("last_update", "")
    if result == "success":
        item["success"] += 1
        if duration_minutes is not None:
            item["completed_total_minutes"] += max(0, int(duration_minutes))
            item["completed_count"] += 1
    elif result == "partial":
        item["partial"] += 1
    else:
        item["failed"] += 1
    item["last_update"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
    PANEL_STATS[panel_key] = item


def make_service_completion_key(panel_key: str, service_id: str) -> str:
    panel_key = normalize_panel_key(panel_key or "unknown")
    service_id = str(service_id or "").strip() or "unknown"
    return f"{panel_key}:{service_id}"


def update_service_completion_stats(panel_key: str, service_id: str, duration_minutes: int):
    """Servis bazında ortalama tamamlanma süresi tutar; yeni siparişlerde daha doğru tahmin verir."""
    global SERVICE_COMPLETION_STATS
    key = make_service_completion_key(panel_key, service_id)
    item = SERVICE_COMPLETION_STATS.get(key, {}) if isinstance(SERVICE_COMPLETION_STATS, dict) else {}
    count = int(item.get("completed_count", 0) or 0) + 1
    total_minutes = int(item.get("completed_total_minutes", 0) or 0) + max(0, int(duration_minutes or 0))
    SERVICE_COMPLETION_STATS[key] = {
        "panel_key": normalize_panel_key(panel_key or "unknown"),
        "service_id": str(service_id or ""),
        "completed_count": count,
        "completed_total_minutes": total_minutes,
        "avg_completion_minutes": round(total_minutes / count, 1) if count else 0,
        "last_duration_minutes": max(0, int(duration_minutes or 0)),
        "last_update": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_average_completion_minutes(panel_key: str = "", service_id: str = "", panel_name: str = "") -> tuple[float, str]:
    """Önce servis ortalamasını, yoksa panel ortalamasını döndürür."""
    panel_key = normalize_panel_key(panel_key or panel_name or "unknown")
    service_id = str(service_id or "").strip()
    if service_id:
        row = (SERVICE_COMPLETION_STATS or {}).get(make_service_completion_key(panel_key, service_id), {})
        try:
            service_count = int(row.get("completed_count", 0) or 0)
            service_avg = float(row.get("avg_completion_minutes", 0) or 0)
            if service_count > 0 and service_avg > 0:
                return service_avg, "servis"
        except Exception:
            pass

    panel_row = (PANEL_STATS or {}).get(panel_key, {})
    try:
        completed_count = int(panel_row.get("completed_count", 0) or 0)
        total_minutes = int(panel_row.get("completed_total_minutes", 0) or 0)
        if completed_count > 0 and total_minutes > 0:
            return round(total_minutes / completed_count, 1), "panel"
    except Exception:
        pass
    return 0, ""


def format_duration_minutes(minutes) -> str:
    try:
        minutes = int(round(float(minutes or 0)))
    except Exception:
        minutes = 0
    if minutes <= 0:
        return "Henüz veri yok"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} saat {mins} dk"
    if hours:
        return f"{hours} saat"
    return f"{mins} dk"


def build_completion_estimate(panel_key: str = "", service_id: str = "", panel_name: str = "") -> dict:
    avg_minutes, source = get_average_completion_minutes(panel_key, service_id, panel_name)
    estimated_at = ""
    if avg_minutes > 0:
        estimated_at = (now_tr() + timedelta(minutes=int(round(avg_minutes)))).strftime("%H:%M")
    return {
        "avg_minutes": round(float(avg_minutes or 0), 1),
        "source": source,
        "text": format_duration_minutes(avg_minutes),
        "estimated_at": estimated_at,
    }


def build_completion_estimate_text(panel_key: str = "", service_id: str = "", panel_name: str = "") -> str:
    estimate = build_completion_estimate(panel_key, service_id, panel_name)
    if not estimate.get("avg_minutes"):
        return "Ortalama tamamlanma: Henüz veri yok"
    source = "servis" if estimate.get("source") == "servis" else "panel"
    return f"Ortalama tamamlanma: {estimate['text']} ({source} ortalaması, tahmini {estimate['estimated_at']})"


def get_delay_alert_threshold_seconds(item: dict) -> int:
    """Gecikme alarmını sabit süre yerine geçmiş tamamlanma ortalamasına göre ayarlar."""
    try:
        avg_minutes = float((item or {}).get("avg_completion_minutes", 0) or 0)
    except Exception:
        avg_minutes = 0
    if avg_minutes <= 0:
        return 5400
    return max(1800, int(avg_minutes * 1.75 * 60))


def increment_link_fail_count(link: str):
    """Aynı link tekrar tekrar hata üretirse otomatik blacklist'e alır."""
    if not BLACKLIST_AUTO_LEARN:
        return
    global LINK_FAIL_COUNT
    normalized = normalize_link_for_check(link or "")
    if not normalized:
        return
    current = int((LINK_FAIL_COUNT or {}).get(normalized, 0) or 0) + 1
    LINK_FAIL_COUNT[normalized] = current
    if current >= BLACKLIST_AUTO_FAIL_COUNT and normalized not in BLACKLIST:
        BLACKLIST.add(normalized)
        send_telegram_alert(
            f"Link otomatik blacklist'e alındı.\n\n"
            f"Link: {normalized}\n"
            f"Hata sayısı: {current}"
        )


def add_order_note(smm_order_id: str, note: str):
    smm_order_id = str(smm_order_id or "").strip()
    note = str(note or "").strip()
    if smm_order_id and note:
        ORDER_NOTES[smm_order_id] = {"note": note, "updated_at": now_tr().strftime("%Y-%m-%d %H:%M:%S")}
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


def round_price_for_market(value: float) -> float:
    """Önerilen satış fiyatını pazaryeri için okunur bir etikete yuvarlar."""
    try:
        value = float(value or 0)
    except Exception:
        return 0.0
    if value <= 0:
        return 0.0
    if value < 20:
        return round(max(1, value) + 0.49, 2)
    return round(int(value) + 0.90, 2)


def calculate_recommended_sale_price(cost_tl: float, target_margin_pct: float | None = None, min_profit_tl: float | None = None) -> dict:
    """Panel maliyetinden komisyon sonrası hedef kâra göre önerilen satış fiyatı üretir."""
    try:
        cost = float(cost_tl or 0)
    except Exception:
        cost = 0.0
    if cost <= 0:
        return {"ok": False, "error": "cost_missing", "recommended_price": 0}

    target_margin = float(PROFIT_TARGET_MARGIN_PERCENT if target_margin_pct is None else target_margin_pct)
    min_profit = float(PROFIT_MIN_TL if min_profit_tl is None else min_profit_tl)
    target_profit = max(min_profit, cost * max(0, target_margin) / 100)
    required_net = cost + target_profit
    divisor = max(0.01, 1 - ITEMSATIS_COMMISSION_RATE)
    raw_price = required_net / divisor
    recommended = round_price_for_market(raw_price)
    profit = calculate_profit(recommended, cost)
    return {
        "ok": True,
        "cost_tl": round(cost, 2),
        "target_margin_percent": target_margin,
        "min_profit_tl": min_profit,
        "recommended_price": recommended,
        "projected_profit_tl": round(float(profit.get("profit", 0) or 0), 2),
        "projected_margin_percent": profit.get("margin_pct", 0),
    }


def build_pricing_advice(price_tl: float, cost_tl: float | None = None) -> str:
    """Sipariş mesajlarında fiyat doğru mu sorusuna kısa, aksiyon alınabilir cevap verir."""
    try:
        sale = float(price_tl or 0)
    except Exception:
        sale = 0.0
    try:
        cost = float(cost_tl or 0) if cost_tl is not None else 0.0
    except Exception:
        cost = 0.0
    if sale <= 0 or cost <= 0:
        return "Fiyat önerisi: Maliyet veya satış fiyatı eksik olduğu için hesaplanamadı."

    profit = calculate_profit(sale, cost)
    advice = calculate_recommended_sale_price(cost)
    recommended = float(advice.get("recommended_price", 0) or 0)
    margin = float(profit.get("margin_pct", 0) or 0)
    current_profit = float(profit.get("profit", 0) or 0)
    if recommended > sale:
        gap = recommended - sale
        return f"Fiyat önerisi: Bu ürün {format_tl_amount(recommended)} civarına çıkarılırsa hedef kâr daha sağlıklı olur. Fark: {format_tl_amount(gap)}"
    if margin >= PRODUCT_HEALTH_MIN_MARGIN_PERCENT:
        return f"Fiyat önerisi: Mevcut fiyat sağlıklı görünüyor. Net kâr: {format_tl_amount(current_profit)}"
    return f"Fiyat önerisi: Marj düşük (%{round(margin, 1)}). Fiyat veya panel servisi kontrol edilmeli."


def build_order_growth_tip(platform: str = "", product_name: str = "") -> str:
    """Satıcıya sipariş başı geliri artırabilecek kısa upsell önerisi verir."""
    text = normalize_text(f"{platform} {product_name}")
    if "instagram" in text or "insta" in text:
        return "Ek satış önerisi: Takipçi alan müşteriye beğeni, kaydetme veya keşfet paketi sun."
    if "tiktok" in text:
        return "Ek satış önerisi: İzlenme alan müşteriye beğeni + takipçi paketi sun."
    if "youtube" in text or "yt" in text:
        return "Ek satış önerisi: İzlenme alan müşteriye abone + beğeni paketi sun."
    if "twitter" in text or "x " in text:
        return "Ek satış önerisi: Etkileşim alan müşteriye takipçi + görüntülenme paketi sun."
    return "Ek satış önerisi: Müşteriye aynı platform için tamamlayıcı paket öner."


def classify_failed_reason(reason: str, detail: str = "") -> str:
    text = normalize_text(f"{reason} {detail}")
    if "bakiye" in text or "balance" in text:
        return "balance"
    if "link" in text:
        return "link"
    if "zarar" in text or "anti_loss" in text or "maliyet" in text or "cost" in text:
        return "profit"
    if "blacklist" in text or "kara" in text:
        return "blacklist"
    if "order id" in text or "belirsiz" in text:
        return "manual_check"
    if "panel" in text or "api" in text or "servis" in text:
        return "panel"
    return "other"


def build_lost_order_summary(limit: int = 50) -> dict:
    """Başarısız siparişleri hafifçe sınıflandırır; ağır panel sorgusu yapmaz."""
    buckets = defaultdict(lambda: {"count": 0, "estimated_lost_tl": 0.0})
    rows = FAILED_ORDERS[-max(1, int(limit or 50)):]
    for item in rows:
        if not isinstance(item, dict):
            continue
        category = classify_failed_reason(item.get("reason", ""), item.get("detail", ""))
        buckets[category]["count"] += 1
        try:
            buckets[category]["estimated_lost_tl"] += float(item.get("price", 0) or 0)
        except Exception:
            pass
    return {
        "total_failed_sample": len(rows),
        "items": {k: {"count": v["count"], "estimated_lost_tl": round(v["estimated_lost_tl"], 2)} for k, v in buckets.items()},
    }


def get_advert_sales_stat(advert_id: str, product_name: str = "") -> dict:
    report_name = get_itemsatis_report_name(advert_id, product_name)
    sources = [DAILY_STATS, WEEKLY_STATS, MONTHLY_STATS]
    best = {"count": 0, "gross": 0.0, "source": ""}
    for name, source in [("daily", DAILY_STATS), ("weekly", WEEKLY_STATS), ("monthly", MONTHLY_STATS)]:
        item = normalize_stat_item((source or {}).get(report_name, {}))
        if item["count"] >= best["count"]:
            best = {"count": item["count"], "gross": item["gross"], "source": name}
    avg_sale = round(best["gross"] / best["count"], 2) if best["count"] else 0
    best["avg_sale_tl"] = avg_sale
    best["product_name"] = report_name
    return best


def score_product_health(cost_tl: float | None, avg_sale_tl: float, failed_count: int = 0, completion_avg: float = 0) -> tuple[int, list[str]]:
    score = 100
    notes = []
    if not cost_tl or cost_tl <= 0:
        score -= 28
        notes.append("maliyet bilinmiyor")
    if avg_sale_tl <= 0:
        score -= 14
        notes.append("satış ortalaması yok")
    if cost_tl and avg_sale_tl:
        profit = calculate_profit(avg_sale_tl, cost_tl)
        margin = float(profit.get("margin_pct", 0) or 0)
        if margin < PRODUCT_HEALTH_MIN_MARGIN_PERCENT:
            score -= 26
            notes.append(f"marj düşük (%{round(margin, 1)})")
    if failed_count >= 3:
        score -= 20
        notes.append("hata sayısı yüksek")
    elif failed_count:
        score -= 8
        notes.append("hata var")
    if completion_avg and completion_avg > 180:
        score -= 10
        notes.append("tamamlanma yavaş")
    return max(0, min(100, score)), notes


def build_product_growth_insights(limit: int = 12) -> dict:
    """Kâr, fiyat ve sağlık skorlarını mevcut cache/state üzerinden hesaplar."""
    rows = []
    failed_by_advert = defaultdict(int)
    for item in FAILED_ORDERS[-100:]:
        if isinstance(item, dict):
            failed_by_advert[str(item.get("advert_id", ""))] += 1

    for advert_id, raw in get_all_services(include_inactive=True).items():
        service = get_service_config(raw)
        cost = estimate_order_cost_from_service(service)
        sales = get_advert_sales_stat(advert_id)
        avg_sale = float(sales.get("avg_sale_tl", 0) or 0)
        advice = calculate_recommended_sale_price(cost or 0)
        completion_avg, completion_source = get_average_completion_minutes(service.get("panel_key", ""), service.get("service_id", ""), service.get("panel", ""))
        score, notes = score_product_health(cost, avg_sale, failed_by_advert.get(str(advert_id), 0), completion_avg)
        profit = calculate_profit(avg_sale, cost or 0) if avg_sale and cost else {}
        rows.append({
            "advert_id": str(advert_id),
            "product_name": sales.get("product_name") or str(advert_id),
            "panel": service.get("panel", ""),
            "service_id": service.get("service_id", ""),
            "sales_count": int(sales.get("count", 0) or 0),
            "avg_sale_tl": avg_sale,
            "estimated_cost_tl": round(float(cost or 0), 2),
            "estimated_profit_tl": round(float(profit.get("profit", 0) or 0), 2) if profit else 0,
            "margin_percent": profit.get("margin_pct", 0) if profit else 0,
            "recommended_price_tl": advice.get("recommended_price", 0) if advice.get("ok") else 0,
            "health_score": score,
            "notes": notes,
            "avg_completion_minutes": completion_avg,
            "completion_source": completion_source,
        })

    rows.sort(key=lambda x: (x["health_score"], -x["sales_count"]))
    needs_attention = rows[:max(1, int(limit or 12))]
    top_profit = sorted([r for r in rows if r["estimated_profit_tl"] > 0], key=lambda x: x["estimated_profit_tl"], reverse=True)[:5]
    price_raise = [r for r in rows if r["recommended_price_tl"] and r["avg_sale_tl"] and r["recommended_price_tl"] > r["avg_sale_tl"]]
    price_raise = sorted(price_raise, key=lambda x: x["recommended_price_tl"] - x["avg_sale_tl"], reverse=True)[:5]
    return {
        "generated_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "total_products": len(rows),
        "needs_attention": needs_attention,
        "top_profit": top_profit,
        "price_raise_candidates": price_raise,
        "lost_orders": build_lost_order_summary(),
    }


def build_growth_report_text() -> str:
    insights = build_product_growth_insights(limit=8)
    lines = ["Kâr ve Satış Fırsat Raporu\n"]
    price_rows = insights.get("price_raise_candidates", [])[:5]
    if price_rows:
        lines.append("Fiyatı artırılabilecek ürünler:")
        for row in price_rows:
            lines.append(
                f"- {row.get('product_name')} | Ortalama satış {format_tl_amount(row.get('avg_sale_tl', 0))} -> öneri {format_tl_amount(row.get('recommended_price_tl', 0))}"
            )
    else:
        lines.append("Fiyat artışı için net aday görünmüyor.")

    top_profit = insights.get("top_profit", [])[:5]
    if top_profit:
        lines.append("\nEn iyi kâr bırakanlar:")
        for row in top_profit:
            lines.append(f"- {row.get('product_name')} | tahmini kâr {format_tl_amount(row.get('estimated_profit_tl', 0))} | marj %{row.get('margin_percent', 0)}")

    attention = insights.get("needs_attention", [])[:5]
    if attention:
        lines.append("\nKontrol edilmesi gereken ürünler:")
        for row in attention:
            note = ", ".join(row.get("notes", [])[:3]) or "not yok"
            lines.append(f"- Skor {row.get('health_score')}/100 | {row.get('product_name')} | {note}")

    lost = insights.get("lost_orders", {}).get("items", {})
    if lost:
        lines.append("\nKayıp sipariş nedenleri:")
        for key, item in sorted(lost.items(), key=lambda x: x[1].get("count", 0), reverse=True):
            lines.append(f"- {key}: {item.get('count', 0)} adet")
    return "\n".join(lines)


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
    completion_estimate = build_completion_estimate(panel_key or panel, service_id, panel)
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
            "avg_completion_minutes": completion_estimate.get("avg_minutes", 0),
            "avg_completion_source": completion_estimate.get("source", ""),
            "estimated_completion_at": completion_estimate.get("estimated_at", ""),
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


ITEMSATIS_PURCHASE_EVENT_KEYWORDS = {
    "order.created", "order_create", "order_created", "order.paid", "order_paid",
    "purchase.created", "purchase_create", "purchase_created", "purchase.paid", "purchase_paid",
    "sale.created", "sale_create", "sale_created", "sale.paid", "sale_paid",
    "advert.sold", "advert_sold", "ilan.satildi", "ilan_satildi", "ilanınız satıldı", "ilaniniz satildi",
    "new_order", "new order", "siparis", "sipariş", "satildi", "satıldı",
}

ITEMSATIS_NON_ORDER_EVENT_KEYWORDS = {
    "listing_chat_started", "listing_chat", "chat_started",
    "message", "message.created", "new_message", "conversation", "chat",
    "notification", "comment", "review", "question", "support",
    "ticket", "delivery_message", "order.message", "order_message",
}


def is_itemsatis_purchase_event(data: dict) -> bool:
    """Itemsatış'tan gelen mesaj/bildirim webhooklarını sipariş sanmayı engeller.
    Sadece gerçek satış/sipariş sinyali varsa True döner.
    """
    event = normalize_text(get_event(data))
    event_simple = (
        event.replace("ı", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )

    if event_simple:
        if any(key in event_simple for key in ITEMSATIS_NON_ORDER_EVENT_KEYWORDS):
            return False
        if any(key in event_simple for key in ITEMSATIS_PURCHASE_EVENT_KEYWORDS):
            return True

    # Event yoksa payload içeriğine bakılır ama sadece güçlü sipariş kanıtı varsa kabul edilir.
    order_id = get_order_id(data)
    advert_id = get_advert_id(data)
    product_name = get_product_name(data)
    link = extract_customer_link(data)
    price = get_order_price(data)

    has_order_id = bool(order_id and str(order_id) != "Bilinmiyor")
    has_advert_id = bool(advert_id)
    has_product = bool(product_name and not is_generic_itemsatis_title(product_name))
    has_link = bool(link)
    has_price = float(price or 0) > 0

    # Gerçek sipariş için en az order/advert + ürün + fiyat/link kombinasyonu aranır.
    if has_order_id and has_advert_id and has_product and (has_price or has_link):
        return True

    # Bazı webhooklarda order_id gelmeyebilir; advert + ürün + fiyat + link varsa yine kabul edilebilir.
    if has_advert_id and has_product and has_price and has_link:
        return True

    return False



def is_generic_itemsatis_title(value: str) -> bool:
    """Itemsatış webhooklarında gerçek ilan adı yerine gelen genel başlıkları filtreler.
    Türkçe büyük İ gibi karakterlerde Python lower() birleşik nokta üretebildiği için
    ASCII sadeleştirme de yapılır.
    """
    text = normalize_text(value)
    simplified = (
        text.replace("i̇", "i")
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
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
    generic_simplified = {
        item.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
        for item in generic_values
    }
    return text in generic_values or simplified in generic_simplified


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
    """Müşterinin girdiği gerçek sosyal medya linkini bulur.

    ÖNEMLİ GÜVENLİK KURALI:
    Itemsatış webhook içinde ilan görseli gibi CDN linkleri de gelebiliyor.
    Paket sisteminde bu CDN linki yanlışlıkla panele gönderilmesin diye,
    platform belli ise sadece o platformun domainlerini kabul ederiz.
    Link bulunamazsa boş döner ve sipariş panele gönderilmez.
    """
    platform = normalize_text(platform)

    priority_paths = [
        # Önce müşterinin doldurduğu post_datas alanları
        "post_datas.Profil Linki",
        "post_datas.Link",
        "post_datas.Video Linki",
        "post_datas.Gönderi Linki",
        "post_datas.Kanal Linki",
        "post_datas.TikTok Linki",
        "post_datas.Instagram Linki",
        "post_datas.YouTube Linki",
        "post_datas.Youtube Linki",
        "details.post_datas.Profil Linki",
        "details.post_datas.Link",
        "details.post_datas.Video Linki",
        "details.post_datas.Gönderi Linki",
        "details.post_datas.Kanal Linki",
        "details.post_datas.TikTok Linki",
        "details.post_datas.Instagram Linki",
        "details.post_datas.YouTube Linki",
        "details.post_datas.Youtube Linki",
        "data.post_datas.Profil Linki",
        "data.post_datas.Link",
        "data.post_datas.Video Linki",
        "data.post_datas.Gönderi Linki",
        "data.post_datas.Kanal Linki",
        "data.post_datas.TikTok Linki",
        "data.post_datas.Instagram Linki",
        "data.post_datas.YouTube Linki",
        "data.post_datas.Youtube Linki",
        # Sonra açık link alanları
        "url", "link", "profile_link", "account_link", "video_link", "post_link",
        "instagram", "instagram_link", "tiktok", "tiktok_link", "youtube", "youtube_link",
        "details.url", "details.link", "details.instagram_link", "details.tiktok_link", "details.youtube_link",
        "data.url", "data.link", "data.instagram_link", "data.tiktok_link", "data.youtube_link",
        # Not alanları en son; burada ilan görseli/linki de olabilir, bu yüzden domain filtresi uygulanır.
        "note", "message", "order_note", "customer_note",
        "details.note", "details.message", "details.order_note", "details.customer_note",
        "data.note", "data.message", "data.order_note", "data.customer_note",
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

    blocked_url_markers = [
        "cdn.itemsatis.com",
        "itemsatis.com/uploads",
        "/uploads/",
        "post_images",
        "product_images",
        "advert_images",
        "ilan-resim",
    ]
    blocked_extensions = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".avif")

    def clean_candidate(value: str) -> str:
        v = str(value or "").strip()
        # Noktalama/HTML kırıntılarını temizle
        return v.strip().strip("'\"<>.,;)])}")

    def is_asset_or_itemsatis_image(value: str) -> bool:
        v = str(value or "").strip().lower()
        if not v:
            return True
        if any(marker in v for marker in blocked_url_markers):
            return True
        no_query = v.split("?")[0]
        if no_query.endswith(blocked_extensions):
            return True
        return False

    def has_allowed_platform_domain(value: str) -> bool:
        v = str(value or "").lower()
        domains = platform_domains.get(platform, [])
        return bool(domains and any(domain in v for domain in domains))

    def looks_like_link(value: str) -> bool:
        v = clean_candidate(value).lower()
        if not v:
            return False
        if is_asset_or_itemsatis_image(v):
            return False

        domains = platform_domains.get(platform, [])

        # Instagram kullanıcı adı desteklenir.
        if platform == "instagram" and v.startswith("@") and len(v) > 2:
            return True

        # Platform belliyse sadece o platformun domainleri kabul edilir.
        # Böylece cdn.itemsatis.com ilan görseli TikTok linki sanılmaz.
        if domains:
            return any(domain in v for domain in domains)

        # Platform other/general ise asset olmayan genel URL kabul edilir.
        if v.startswith("http://") or v.startswith("https://"):
            return True
        if "." in v and " " not in v:
            return True
        return False

    # Öncelikli alanlarda tek alan direkt link ise al.
    # Önemli: Itemsatış bazen asıl alanları raw string içindeki dict olarak gönderir;
    # bu yüzden hem ana payload hem raw içindeki gömülü payload taranır.
    for payload in payload_variants(data):
        for path in priority_paths:
            value = get_nested(payload, path)
            if isinstance(value, str) and looks_like_link(value):
                return normalize_panel_link(clean_candidate(value), platform)

    all_strings = collect_strings(data)
    joined = "\n".join(all_strings)

    # Platform belliyse önce sadece o platformun domainini ara.
    domains = platform_domains.get(platform, [])
    if platform == "instagram":
        match = re.search(r"(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._/\-?=&%]+", joined, re.IGNORECASE)
        if match:
            candidate = clean_candidate(match.group(0))
            if not is_asset_or_itemsatis_image(candidate):
                return normalize_panel_link(candidate, platform)
        for text in all_strings:
            text = clean_candidate(text)
            if text.startswith("@") and len(text) > 2:
                return normalize_panel_link(text, platform)
        return ""

    if domains:
        domain_pattern = "|".join(re.escape(d) for d in domains)
        match = re.search(rf"(?:https?://)?(?:www\.)?(?:{domain_pattern})/[^\s<>'\"]+", joined, re.IGNORECASE)
        if match:
            value = clean_candidate(match.group(0))
            if not value.startswith("http"):
                value = "https://" + value
            if not is_asset_or_itemsatis_image(value):
                return normalize_panel_link(value, platform)
        return ""

    # Platform bilinmiyorsa genel URL ara ama ilan görseli/CDN linklerini reddet.
    for match in re.finditer(r"https?://[^\s<>'\"]+", joined, re.IGNORECASE):
        candidate = clean_candidate(match.group(0))
        if not is_asset_or_itemsatis_image(candidate):
            return normalize_panel_link(candidate, platform)

    return ""



def find_package_order_link(data: dict, package: dict) -> tuple[str, str]:
    """Paket siparişlerinde müşteri linkini güvenli şekilde bulur.

    Paketlerde Itemsatış webhook'u ilan görseli/CDN URL'si de taşıyabiliyor.
    Bu yüzden önce paket platformu ve aktif bileşen platformları denenir; platform
    domaini eşleşmeyen URL kesinlikle panele gönderilmez. Böylece müşterinin gerçek
    TikTok/Instagram/YouTube linki varken cdn.itemsatis.com görsel linki seçilmez.
    """
    platforms = []

    def add_platform(value):
        value = normalize_text(value or "")
        if value and value not in platforms:
            platforms.append(value)

    add_platform((package or {}).get("platform"))
    for component in (package or {}).get("components", []) or []:
        comp = normalize_package_component(component)
        if comp.get("active", True):
            add_platform(comp.get("platform"))

    # Sosyal platformları önce dene. other/general en sona kalsın.
    preferred = [p for p in platforms if p not in ["other", "general", ""]]
    fallback = [p for p in platforms if p in ["other", "general", ""]]

    for platform in preferred + fallback:
        link = find_order_link(data, platform)
        if link:
            return link, platform

    return "", (platforms[0] if platforms else "")

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
    component_id = str(component.get("id") or component.get("component_id") or f"cmp_{secrets.token_hex(8)}")
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
        "id": f"cmp_{secrets.token_hex(8)}",
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
    if name and not is_generic_itemsatis_title(name):
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
        text = re.sub(r"[^0-9.]", "", text)
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


def guess_panel_rate_currency(panel_key: str, rate_value="") -> str:
    """Panel servis fiyatlarının para birimini tahmin eder. Mesajlarda her şeyi TL gösterir."""
    text = str(rate_value or "").upper()
    key = normalize_panel_key(panel_key)
    if "TL" in text or "TRY" in text or "₺" in text:
        return "TRY"
    if "USD" in text or "$" in text or "USDT" in text:
        return "USD"
    # MedyaBayim TL çalışıyor; diğer global paneller çoğunlukla USD döndürüyor.
    if key == "medyabayim":
        return "TRY"
    return "USD"


def format_panel_rate_tl(panel_key: str, rate_value) -> str:
    """Panel service rate değerini TL olarak formatlar. USD panelleri güncel kura göre çevirir."""
    numeric = parse_numeric_balance(rate_value)
    if numeric is None:
        return "Bilinmiyor"
    currency = guess_panel_rate_currency(panel_key, rate_value)
    if currency == "USD":
        numeric = numeric * get_usd_to_try_rate()
    return format_tl_amount(numeric)



def panel_rate_to_tl(panel_key: str, rate_value) -> float | None:
    """Panel servis fiyatını TL cinsine çevirir. Rate çoğu panelde 1000 adet fiyatıdır."""
    numeric = parse_numeric_balance(rate_value)
    if numeric is None:
        return None
    currency = guess_panel_rate_currency(panel_key, rate_value)
    if currency == "USD":
        numeric *= get_usd_to_try_rate()
    return float(numeric)


def estimate_service_cost_tl(panel_key: str, rate_value, quantity) -> float | None:
    """Panel rate değerinden sipariş maliyetini TL olarak hesaplar.
    SMM panel standardında rate genelde 1000 adet fiyatıdır.
    """
    rate_tl = panel_rate_to_tl(panel_key, rate_value)
    if rate_tl is None:
        return None
    try:
        qty = int(quantity or 0)
    except Exception:
        qty = 0
    return round((rate_tl / 1000.0) * qty, 4)


def fetch_panel_service_rate(service: dict) -> dict:
    """Servis ID için panelden güncel rate bilgisini çeker ve cache'i günceller."""
    panel_key = normalize_panel_key((service or {}).get("panel_key") or (service or {}).get("panel") or "")
    service_id = str((service or {}).get("service_id") or "").strip()
    if not panel_key or not service_id:
        return {"ok": False, "error": "panel_key_or_service_id_missing"}

    api_url = (service or {}).get("api_url")
    api_key = (service or {}).get("api_key")
    panel_name = (service or {}).get("panel") or get_panel_config(panel_key).get("name", panel_key)
    if not api_url or not api_key:
        return {"ok": False, "error": "panel_config_missing"}

    cache_key = f"{panel_key}:{service_id}"
    cache_ts_key = f"rate_checked_at:{cache_key}"
    cached_rate = SERVICE_PRICE_CACHE.get(cache_key)
    last_checked = int(SERVICE_PRICE_CACHE.get(cache_ts_key, 0) or 0)
    throttle_seconds = int(os.getenv("SERVICE_RATE_FETCH_THROTTLE_SECONDS", "300"))
    if cached_rate and last_checked and (int(time.time()) - last_checked) < throttle_seconds:
        return {"ok": True, "rate": cached_rate, "service_name": get_panel_service_display_name(service), "cached": True}

    services_data = get_panel_services(api_url, api_key, panel_name)
    if isinstance(services_data, dict) and "error" in services_data:
        return {"ok": False, "error": services_data.get("error")}
    if not isinstance(services_data, list):
        return {"ok": False, "error": "services_response_not_list"}

    for item in services_data:
        if isinstance(item, dict) and str(item.get("service")) == service_id:
            service_name = get_panel_service_display_name(service, item)
            rate_raw = str(item.get("rate", ""))
            if rate_raw:
                SERVICE_PRICE_CACHE[f"{panel_key}:{service_id}"] = rate_raw
                SERVICE_PRICE_CACHE[f"rate_checked_at:{panel_key}:{service_id}"] = int(time.time())
                SERVICE_PRICE_CACHE.pop(f"missing:{panel_key}:{service_id}", None)
            return {"ok": True, "rate": rate_raw, "service_name": service_name, "raw": item}

    return {"ok": False, "error": "service_not_found"}


def check_anti_loss_guardrail_for_services(services: list[dict], sale_price_tl: float, context: str = "") -> dict:
    """Sipariş panele gitmeden önce tahmini toplam panel maliyetini net satış geliriyle karşılaştırır."""
    if not ANTI_LOSS_ENABLED:
        return {"ok": True, "disabled": True}
    try:
        sale_price_tl = float(sale_price_tl or 0)
    except Exception:
        sale_price_tl = 0.0
    if sale_price_tl <= 0:
        return {"ok": True, "skipped": "sale_price_missing"}

    total_cost = 0.0
    service_rows = []
    unknown_rows = []

    for service in services:
        panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
        rate_info = fetch_panel_service_rate(service)
        if not rate_info.get("ok"):
            unknown_rows.append({
                "panel": service.get("panel", panel_key),
                "service_id": service.get("service_id", ""),
                "error": rate_info.get("error", "rate_unknown"),
            })
            continue
        cost_tl = estimate_service_cost_tl(panel_key, rate_info.get("rate"), service.get("quantity"))
        if cost_tl is None:
            unknown_rows.append({
                "panel": service.get("panel", panel_key),
                "service_id": service.get("service_id", ""),
                "error": "cost_unknown",
            })
            continue
        total_cost += float(cost_tl)
        service_rows.append({
            "panel": service.get("panel", panel_key),
            "panel_key": panel_key,
            "service_id": service.get("service_id", ""),
            "quantity": service.get("quantity", ""),
            "rate": rate_info.get("rate", ""),
            "service_name": rate_info.get("service_name", ""),
            "cost_tl": round(float(cost_tl), 2),
        })

    net_income = round(sale_price_tl * (1 - ITEMSATIS_COMMISSION_RATE), 2)
    min_profit_tl = float(ANTI_LOSS_MIN_PROFIT_TL or 0)
    min_profit_percent = float(ANTI_LOSS_MIN_PROFIT_PERCENT or 0)
    min_profit_by_percent = round(net_income * (min_profit_percent / 100), 2) if min_profit_percent > 0 else 0
    min_profit = max(min_profit_tl, min_profit_by_percent)
    projected_profit = round(net_income - total_cost, 2)

    if unknown_rows and ANTI_LOSS_BLOCK_UNKNOWN_COST:
        return {
            "ok": False,
            "reason": "unknown_cost_blocked",
            "sale_price_tl": round(sale_price_tl, 2),
            "net_income_tl": net_income,
            "panel_cost_tl": round(total_cost, 2),
            "projected_profit_tl": projected_profit,
            "min_profit_tl": min_profit,
            "min_profit_fixed_tl": min_profit_tl,
            "min_profit_percent": min_profit_percent,
            "services": service_rows,
            "unknown": unknown_rows,
            "context": context,
        }

    if total_cost > 0 and projected_profit < min_profit:
        return {
            "ok": False,
            "reason": "low_profit_blocked",
            "sale_price_tl": round(sale_price_tl, 2),
            "net_income_tl": net_income,
            "panel_cost_tl": round(total_cost, 2),
            "projected_profit_tl": projected_profit,
            "min_profit_tl": min_profit,
            "min_profit_fixed_tl": min_profit_tl,
            "min_profit_percent": min_profit_percent,
            "services": service_rows,
            "unknown": unknown_rows,
            "context": context,
        }

    if unknown_rows:
        log("warning", "anti_loss_rate_unknown", context=context, unknown=unknown_rows)

    return {
        "ok": True,
        "sale_price_tl": round(sale_price_tl, 2),
        "net_income_tl": net_income,
        "panel_cost_tl": round(total_cost, 2),
        "projected_profit_tl": projected_profit,
        "min_profit_tl": min_profit,
        "min_profit_fixed_tl": min_profit_tl,
        "min_profit_percent": min_profit_percent,
        "services": service_rows,
        "unknown": unknown_rows,
    }


def format_anti_loss_message(title: str, product_name: str, order_id: str, guard: dict) -> str:
    service_lines = []
    for row in guard.get("services", [])[:10]:
        service_lines.append(
            f"- {row.get('panel')} | ID {row.get('service_id')} | {row.get('quantity')} adet | Maliyet: {format_tl_amount(row.get('cost_tl', 0))}"
        )
    if guard.get("unknown"):
        service_lines.append(f"- Fiyatı okunamayan servis: {len(guard.get('unknown', []))} adet")
    details = "\n".join(service_lines) or "- Detay yok"
    reason = str(guard.get("reason") or "")
    reason_text = "\nSebep: Panel maliyeti okunamadı; güvenli mod siparişi durdurdu.\n" if reason == "unknown_cost_blocked" else ""
    min_profit_text = ""
    if guard.get("min_profit_tl") is not None:
        min_profit_text = f"Minimum kâr: {format_tl_amount(guard.get('min_profit_tl', 0))}\n"
    return (
        f"{title}\n\n"
        f"Ürün/Paket: {product_name}\n"
        f"Itemsatış ID: {order_id}\n"
        f"Satış: {format_tl_amount(guard.get('sale_price_tl', 0))}\n"
        f"Net gelir: {format_tl_amount(guard.get('net_income_tl', 0))}\n"
        f"Panel maliyeti: {format_tl_amount(guard.get('panel_cost_tl', 0))}\n"
        f"Tahmini kâr: {format_tl_amount(guard.get('projected_profit_tl', 0))}\n"
        f"{min_profit_text}"
        f"{reason_text}\n"
        f"Servisler:\n{details}\n\n"
        f"Sipariş panele gönderilmedi. Fiyat/ilan/panel servisini kontrol et."
    )

def record_balance_history(panel_key: str, balance_data: dict):
    """Panel bakiyesini günlük geçmişe yazar."""
    global BALANCE_HISTORY
    try:
        panel_key = normalize_panel_key(panel_key)
        balance_tl = convert_balance_to_try((balance_data or {}).get("balance"), (balance_data or {}).get("currency", ""))
        if balance_tl is None:
            return
        today = now_tr().strftime("%Y-%m-%d")
        BALANCE_HISTORY.setdefault(today, {})[panel_key] = {
            "balance_tl": round(float(balance_tl), 2),
            "panel_name": get_panel_config(panel_key).get("name", panel_key),
            "updated_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        }
        # Son 60 günü tut.
        keep_from = (now_tr() - timedelta(days=60)).strftime("%Y-%m-%d")
        BALANCE_HISTORY = {k: v for k, v in BALANCE_HISTORY.items() if str(k) >= keep_from}
    except Exception as e:
        log("warning", "balance_history_record_failed", error=str(e))


def record_link_audit(order_id: str, advert_id: str, product_name: str, platform: str, link: str, status: str, note: str = ""):
    """Webhook link yakalama geçmişi. Yanlış link olaylarını admin panelden izlemek için."""
    global LINK_AUDIT_HISTORY
    try:
        LINK_AUDIT_HISTORY.append({
            "ts": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
            "order_id": str(order_id),
            "advert_id": str(advert_id),
            "product_name": str(product_name),
            "platform": str(platform),
            "link": str(link or ""),
            "status": str(status),
            "note": str(note or ""),
        })
        if len(LINK_AUDIT_HISTORY) > 300:
            del LINK_AUDIT_HISTORY[:-300]
    except Exception as e:
        log("warning", "link_audit_failed", error=str(e))



def _strip_html_tags(value: str) -> str:
    """Scraper sonuçlarındaki HTML parçalarını sade metne çevirir."""
    text_value = re.sub(r"<script.*?</script>|<style.*?</style>", " ", str(value or ""), flags=re.I | re.S)
    text_value = re.sub(r"<[^>]+>", " ", text_value)
    text_value = html.unescape(text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def _itemsatis_advert_id_from_url(url: str) -> str:
    """Itemsatış ilan linkinden ilan ID yakalar. Genelde /kategori/slug-3010679.html formatındadır."""
    raw_url = html.unescape(str(url or "")).strip()
    if not raw_url:
        return ""
    absolute = raw_url if raw_url.startswith("http") else urljoin("https://www.itemsatis.com", raw_url)
    parsed = urlparse(absolute)
    lowered = (parsed.path or "").lower()
    blocked_parts = ["/profil", "/profile", "/magaza", "/mağaza", "/kullanici", "/user", "/arama", "/search", "/sss/", "/bildirim", "/mesaj", "/ilanlarim"]
    if any(part in lowered for part in blocked_parts):
        return ""
    patterns = [
        r"-(\d{5,})(?:\.html)?(?:[/?#]|$)",
        r"/(?:ilan|advert|urun|ürün|product)/(?:[^/?#]*?)(\d{5,})(?:\.html)?(?:[/?#]|$)",
        r"(?:ilan|advert|product|id|advert_id|data-id|data-advert-id)[=/\-_](\d{5,})",
        r"[?&](?:id|ilan|advert|advert_id|product_id)=(\d{5,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, absolute, re.I)
        if match:
            return match.group(1)
    return ""

def _itemsatis_is_bad_title(title: str) -> bool:
    title = _strip_html_tags(title)
    simplified = normalize_text(title)
    simplified = (
        simplified.replace("i̇", "i")
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    bad_exact = {
        "", "aç", "ac", "detay", "detaylar", "incele", "satın al", "satin al",
        "sepete ekle", "kopyala", "ilan", "ürün", "urun", "itemsatış", "itemsatis",
        "favori", "mağazaya git", "magazaya git", "hemen al",
    }
    if simplified in bad_exact:
        return True
    if len(simplified) < 3:
        return True
    if len(simplified) > 240:
        return True
    return False


def _itemsatis_clean_title(title: str) -> str:
    title = _strip_html_tags(title)
    title = re.sub(r"\s+", " ", title).strip(" -|•\t\n\r")
    title = re.sub(r"\b(?:TL|₺)\s*[0-9.,]+\b", "", title, flags=re.I)
    title = re.sub(r"\b[0-9.,]+\s*(?:TL|₺)\b", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" -|•")
    return title[:220]


def _itemsatis_title_from_segment(segment: str) -> str:
    """İlan linkinin çevresindeki HTML kartından başlık çıkarmaya çalışır."""
    segment = str(segment or "")
    candidates = []

    for pattern in [
        r"<h[1-6][^>]*>(.*?)</h[1-6]>",
        r"<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>",
        r"(?:title|aria-label|alt)=[\"']([^\"']+)[\"']",
        r"<a\b[^>]*>(.*?)</a>",
    ]:
        for value in re.findall(pattern, segment, flags=re.I | re.S):
            cleaned = _itemsatis_clean_title(value)
            if cleaned and not _itemsatis_is_bad_title(cleaned):
                candidates.append(cleaned)

    plain = _strip_html_tags(segment)
    for part in re.split(r"\s{2,}|\|", plain):
        cleaned = _itemsatis_clean_title(part)
        if cleaned and not _itemsatis_is_bad_title(cleaned):
            candidates.append(cleaned)

    if not candidates:
        return ""

    candidates = sorted(set(candidates), key=lambda x: (not (8 <= len(x) <= 120), len(x)))
    return candidates[0]


def _itemsatis_absolute_url(href: str, profile_url: str = "") -> str:
    base = profile_url or "https://www.itemsatis.com"
    return urljoin(base, html.unescape(str(href or "")).strip())


def is_placeholder_itemsatis_profile_url(url: str) -> bool:
    url = str(url or "").strip().lower()
    if not url:
        return True
    placeholders = ["profil-linkin", "profile-link", "profil_url", "profile_url", "ornek", "örnek", "example"]
    return any(p in url for p in placeholders)


def get_itemsatis_profile_url() -> str:
    """Profil URL'ini env veya admin panelde kayıtlı Redis override üzerinden döndürür."""
    env_url = str(ITEMSATIS_PROFILE_URL or "").strip()
    if env_url and not is_placeholder_itemsatis_profile_url(env_url):
        return env_url
    try:
        saved = str(redis_get_raw(ITEMSATIS_PROFILE_URL_OVERRIDE_KEY, "") or "").strip()
        if saved and not is_placeholder_itemsatis_profile_url(saved):
            return saved
    except Exception:
        pass
    return env_url


def save_itemsatis_profile_url(url: str) -> bool:
    url = str(url or "").strip()
    if not url:
        redis_delete_key(ITEMSATIS_PROFILE_URL_OVERRIDE_KEY)
        return True
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    redis_set_raw(ITEMSATIS_PROFILE_URL_OVERRIDE_KEY, url)
    return True

def _itemsatis_profile_page_candidates(profile_url: str) -> list[str]:
    """Profil ilanları pagination ile gelebilir; güvenli sayfa URL'leri üretir."""
    profile_url = str(profile_url or "").strip()
    if not profile_url:
        return []
    if not profile_url.startswith("http"):
        profile_url = "https://" + profile_url.lstrip("/")
    max_pages = max(1, min(int(ITEMSATIS_ADVERT_MAX_PAGES or 1), 50))
    urls = []
    def add(url):
        url = str(url or "").strip()
        if url and url not in urls:
            urls.append(url)
    add(profile_url)
    parsed = urlparse(profile_url)
    existing_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    base_path = parsed.path.rstrip("/") or "/"
    for page in range(2, max_pages + 1):
        for key in ("page", "sayfa", "p"):
            q = dict(existing_query)
            q[key] = str(page)
            add(urlunparse(parsed._replace(query=urlencode(q))))
        add(urlunparse(parsed._replace(path=f"{base_path}/sayfa/{page}", query="")))
        add(urlunparse(parsed._replace(path=f"{base_path}/page/{page}", query="")))
    return urls

def parse_itemsatis_adverts_from_html(page_html: str, profile_url: str = "") -> list[dict]:
    """Public Itemsatış HTML'inden gerçek ilan ID + ilan adı yakalar."""
    page_html = str(page_html or "")
    found = {}
    def add_found(advert_id: str, name: str = "", url: str = "", source: str = "profile_scrape"):
        advert_id = str(advert_id or "").strip()
        if not advert_id or advert_id.startswith("0") or len(advert_id) < 5:
            return
        name = _itemsatis_clean_title(name)
        if _itemsatis_is_bad_title(name):
            name = PRODUCT_NAME_CACHE.get(advert_id, "") or f"Itemsatış İlanı {advert_id}"
        url = _itemsatis_absolute_url(url, profile_url) if url else ""
        current = found.get(advert_id, {})
        current_name = current.get("name", "")
        better_name = (not current_name) or current_name.startswith("Itemsatış İlanı") or (name and len(name) > len(current_name) and not name.startswith("Itemsatış İlanı"))
        if not current or better_name:
            found[advert_id] = {"advert_id": advert_id, "name": name[:220], "url": url or current.get("url", ""), "source": source}

    anchor_pattern = re.compile(r"<a\b(?P<attrs>[^>]*href=[^>]*)>(?P<body>.*?)</a>", re.I | re.S)
    href_pattern = re.compile(r"href=[\"'](?P<href>[^\"']+)[\"']", re.I)
    attr_title_pattern = re.compile(r"(?:title|aria-label|alt)=[\"'](?P<title>[^\"']+)[\"']", re.I)
    for match in anchor_pattern.finditer(page_html):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        href_match = href_pattern.search(attrs)
        if not href_match:
            continue
        href = href_match.group("href")
        advert_id = _itemsatis_advert_id_from_url(href)
        if not advert_id:
            continue
        start = max(0, match.start() - 2200)
        end = min(len(page_html), match.end() + 2200)
        segment = page_html[start:end]
        title = ""
        title_match = attr_title_pattern.search(attrs)
        if title_match:
            title = title_match.group("title")
        if not title:
            title = _itemsatis_title_from_segment(segment)
        if not title:
            title = body
        add_found(advert_id, title, href, "profile_link")

    id_patterns = [
        r"(?:data-advert-id|data-advert|data-id|advert_id|advertId|ilan_id|product_id)[\"'\s:=]+(\d{5,})",
        r"[\"'](?:id|advert_id|advertId|ilan_id|product_id)[\"']\s*:\s*[\"']?(\d{5,})",
    ]
    for pattern in id_patterns:
        for match in re.finditer(pattern, page_html, flags=re.I):
            advert_id = match.group(1)
            start = max(0, match.start() - 2200)
            end = min(len(page_html), match.end() + 2200)
            segment = page_html[start:end]
            if not re.search(r"itemsatis\.com/.+?-\d{5,}\.html|href=[\"'][^\"']+-\d{5,}\.html", segment, re.I):
                continue
            title = _itemsatis_title_from_segment(segment)
            add_found(advert_id, title, "", "profile_data")

    json_like_patterns = [
        r"[\{,]\s*[\"'](?:id|advert_id|advertId|ilan_id|product_id)[\"']\s*:\s*[\"']?(?P<id>\d{5,})[\"']?.{0,1600}?[\"'](?:title|name|subject)[\"']\s*:\s*[\"'](?P<title>[^\"']{3,220})[\"']",
        r"[\{,]\s*[\"'](?:title|name|subject)[\"']\s*:\s*[\"'](?P<title>[^\"']{3,220})[\"'].{0,1600}?[\"'](?:id|advert_id|advertId|ilan_id|product_id)[\"']\s*:\s*[\"']?(?P<id>\d{5,})",
    ]
    for pattern in json_like_patterns:
        for match in re.finditer(pattern, page_html, flags=re.I | re.S):
            add_found(match.group("id"), match.group("title"), "", "profile_json")
    return sorted(found.values(), key=lambda x: str(x.get("name", "")).lower())

def _advert_link_status(advert_id: str) -> dict:
    advert_id = str(advert_id or "").strip()
    service = get_dynamic_services().get(advert_id) or SMM_SERVICE_MAP.get(advert_id)
    package = get_package_configs(include_inactive=True).get(advert_id)
    if service and package:
        label = "Servis + Paket bağlı"
        status = "both"
    elif service:
        label = "Servise bağlı"
        status = "service"
    elif package:
        label = "Pakete bağlı"
        status = "package"
    else:
        label = "Eşleşmemiş"
        status = "missing"
    return {"status": status, "label": label}


def parse_itemsatis_adverts_from_text(raw_text: str) -> list[dict]:
    """Admin panelde yapıştırılan Itemsatış ilan linkleri/HTML/metinden ID + ad çıkarır."""
    raw_text = str(raw_text or "")
    items = {}
    for item in parse_itemsatis_adverts_from_html(raw_text, get_itemsatis_profile_url() or "https://www.itemsatis.com"):
        if item.get("advert_id"):
            item["source"] = "manual_import"
            items[str(item["advert_id"])] = item
    url_pattern = re.compile(r"https?://[^\s'\"<>]+|/(?:[^\s'\"<>]+-\d{5,}\.html)", re.I)
    for match in url_pattern.finditer(raw_text):
        url = match.group(0)
        advert_id = _itemsatis_advert_id_from_url(url)
        if not advert_id:
            continue
        line_start = raw_text.rfind("\n", 0, match.start()) + 1
        line_end = raw_text.find("\n", match.end())
        if line_end == -1:
            line_end = len(raw_text)
        line = raw_text[line_start:line_end]
        title_raw = line.replace(url, "")
        title_raw = re.sub(rf"(?:^|[|\s-]){re.escape(advert_id)}(?:$|[|\s-])", " ", title_raw)
        title_raw = title_raw.replace("|", " ")
        title = _itemsatis_clean_title(title_raw)
        if _itemsatis_is_bad_title(title):
            title = f"Itemsatış İlanı {advert_id}"
        items[advert_id] = {"advert_id": advert_id, "name": title, "url": _itemsatis_absolute_url(url, get_itemsatis_profile_url()), "source": "manual_import"}
    return sorted(items.values(), key=lambda x: str(x.get("name", "")).lower())




def build_itemsatis_import_preview(raw_text: str) -> dict:
    """Yapıştırılan ilan çıktısını güvenli önizleme formatına çevirir.

    Bu fonksiyon Redis'e yazmaz. Önce admin'e tablo gösterilir; sadece seçilenler kaydedilir.
    """
    raw_text = str(raw_text or "")
    parsed = parse_itemsatis_adverts_from_text(raw_text)
    existing_rows = collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=False)
    existing_ids = {str(item.get("advert_id")) for item in existing_rows if isinstance(item, dict)}

    accepted = []
    suspicious = []
    seen = set()

    for item in parsed:
        advert_id = str((item or {}).get("advert_id", "")).strip()
        name = _itemsatis_clean_title((item or {}).get("name", ""))
        url = str((item or {}).get("url", "")).strip()
        reasons = []

        if not advert_id or not advert_id.isdigit() or len(advert_id) < 5:
            reasons.append("ID geçersiz")
        if advert_id in seen:
            reasons.append("Aynı ID tekrar ediyor")
        if _itemsatis_is_bad_title(name) or name.startswith("Itemsatış İlanı"):
            reasons.append("Başlık zayıf/otomatik")
        if not url:
            reasons.append("Link yok")
        if advert_id in existing_ids:
            reasons.append("Zaten listede var; seçersen güncellenir")

        row = {
            "advert_id": advert_id,
            "name": name or f"Itemsatış İlanı {advert_id}",
            "url": url,
            "source": "manual_import_preview",
            "reasons": reasons,
            "default_checked": not any(r in reasons for r in ["ID geçersiz", "Aynı ID tekrar ediyor", "Başlık zayıf/otomatik", "Link yok"]),
        }
        seen.add(advert_id)
        if row["default_checked"]:
            accepted.append(row)
        else:
            suspicious.append(row)

    line_count = len([line for line in raw_text.splitlines() if line.strip()])
    return {
        "line_count": line_count,
        "parsed_count": len(parsed),
        "accepted": accepted,
        "suspicious": suspicious,
        "total_preview": len(accepted) + len(suspicious),
    }


def remove_itemsatis_advert_from_cache(advert_id: str) -> bool:
    """Yanlış içe aktarılan ilanı manuel/cache listelerinden siler. Servis/paket eşleşmesini silmez."""
    advert_id = str(advert_id or "").strip()
    if not advert_id:
        return False
    changed = False

    manual_items = [item for item in get_manual_itemsatis_adverts() if str((item or {}).get("advert_id")) != advert_id]
    if len(manual_items) != len(get_manual_itemsatis_adverts()):
        redis_set_json(ITEMSATIS_ADVERT_MANUAL_KEY, manual_items)
        changed = True

    cache = redis_get_json(ITEMSATIS_ADVERT_CACHE_KEY, {})
    if isinstance(cache, dict):
        cached_items = cache.get("items", []) or []
        new_cached = [item for item in cached_items if str((item or {}).get("advert_id")) != advert_id]
        if len(new_cached) != len(cached_items):
            cache["items"] = new_cached
            cache["scraped_count"] = len(new_cached)
            cache["updated_at"] = int(time.time())
            cache["updated_at_text"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
            redis_set_json(ITEMSATIS_ADVERT_CACHE_KEY, cache)
            changed = True

    return changed


def clear_itemsatis_advert_import_cache():
    """İlan içe aktarma/cache kayıtlarını temizler; dinamik servis ve paket ayarlarına dokunmaz."""
    redis_set_json(ITEMSATIS_ADVERT_MANUAL_KEY, [])
    redis_set_json(ITEMSATIS_ADVERT_CACHE_KEY, {"items": [], "updated_at": int(time.time()), "updated_at_text": now_tr().strftime("%Y-%m-%d %H:%M:%S"), "source": "cleared", "scraped_count": 0})

def get_manual_itemsatis_adverts() -> list[dict]:
    data = redis_get_json(ITEMSATIS_ADVERT_MANUAL_KEY, [])
    return data if isinstance(data, list) else []


def save_manual_itemsatis_adverts(items: list[dict], merge: bool = True) -> int:
    current = {str(i.get("advert_id")): i for i in get_manual_itemsatis_adverts() if isinstance(i, dict) and i.get("advert_id")} if merge else {}
    for item in items or []:
        advert_id = str((item or {}).get("advert_id", "")).strip()
        if not advert_id:
            continue
        current[advert_id] = {"advert_id": advert_id, "name": str(item.get("name") or f"Itemsatış İlanı {advert_id}")[:220], "url": str(item.get("url") or ""), "source": "manual_import"}
    rows = sorted(current.values(), key=lambda x: str(x.get("name", "")).lower())
    redis_set_json(ITEMSATIS_ADVERT_MANUAL_KEY, rows)
    return len(rows)

def collect_itemsatis_adverts_from_local_state(include_cache: bool = True, include_history: bool = False) -> list[dict]:
    """Itemsatış ilan listesini cache/manual/admin eşleşmelerden oluşturur.

    Varsayılan olarak test webhook/geçmiş siparişleri ana ilan listesine karıştırmaz.
    """
    rows = {}
    def is_bad_advert(advert_id_s: str, name_s: str = "", source: str = "") -> bool:
        advert_id_s = str(advert_id_s or "").strip()
        name_s = normalize_text(name_s)
        if not advert_id_s or advert_id_s.startswith("manual-") or not advert_id_s.isdigit():
            return True
        if source in {"order_history", "pending_orders", "failed_orders", "product_name_cache"} and not include_history:
            return True
        test_words = ["test", "deneme", "webhook", "raw", "bilinmeyen ürün", "bilinmeyen urun"]
        if any(w in name_s for w in test_words):
            return True
        return False
    def add(advert_id, name="", source="local", url=""):
        advert_id_s = str(advert_id or "").strip()
        name_s = str(name or "").strip() or PRODUCT_NAME_CACHE.get(advert_id_s, "") or f"Itemsatış İlanı {advert_id_s}"
        if is_bad_advert(advert_id_s, name_s, source):
            return
        existing = rows.get(advert_id_s, {})
        if advert_id_s not in rows or (not existing.get("name") or existing.get("name", "").startswith("Itemsatış İlanı")):
            rows[advert_id_s] = {"advert_id": advert_id_s, "name": name_s[:220], "url": url, "source": source}
    if include_cache:
        cache = redis_get_json(ITEMSATIS_ADVERT_CACHE_KEY, {})
        if isinstance(cache, dict):
            for item in cache.get("items", []) or []:
                if isinstance(item, dict):
                    add(item.get("advert_id"), item.get("name"), item.get("source", "cache"), item.get("url", ""))
    for item in get_manual_itemsatis_adverts():
        if isinstance(item, dict):
            add(item.get("advert_id"), item.get("name"), "manual_import", item.get("url", ""))
    for advert_id, service in get_all_services(include_inactive=True).items():
        add(advert_id, (service or {}).get("name") or PRODUCT_NAME_CACHE.get(str(advert_id), ""), "service_mapping")
    for advert_id, package in get_package_configs(include_inactive=True).items():
        add(advert_id, (package or {}).get("name") or PRODUCT_NAME_CACHE.get(str(advert_id), ""), "package_mapping")
    if include_history:
        for advert_id, name in (PRODUCT_NAME_CACHE or {}).items():
            add(advert_id, name, "product_name_cache")
        for item in (ORDER_HISTORY or [])[-500:]:
            if isinstance(item, dict):
                add(item.get("advert_id"), item.get("product_name"), "order_history")
        for item in (PENDING_ORDERS or [])[-300:]:
            if isinstance(item, dict):
                add(item.get("advert_id"), item.get("product_name"), "pending_orders")
        for item in (FAILED_ORDERS or [])[-100:]:
            if isinstance(item, dict):
                add(item.get("advert_id"), item.get("product_name"), "failed_orders")
    enriched = []
    for row in rows.values():
        row.update(_advert_link_status(row.get("advert_id")))
        enriched.append(row)
    return sorted(enriched, key=lambda x: (x.get("status") != "missing", str(x.get("name", "")).lower()))

def fetch_itemsatis_public_adverts(force: bool = False, include_history: bool = False) -> dict:
    """Public profil ilanlarını çeker; başarısızsa sadece güvenli cache/manual/admin kayıtlarını gösterir."""
    cache = redis_get_json(ITEMSATIS_ADVERT_CACHE_KEY, {})
    now_ts = int(time.time())
    cached_items = (cache.get("items", []) if isinstance(cache, dict) else []) or []
    profile_url = get_itemsatis_profile_url()

    # Hız optimizasyonu: admin sayfası her açıldığında Itemsatış'a istek atma.
    # Itemsatış Render isteklerine sık sık 403 verdiği için canlı kontrol sadece buton/refresh ile yapılır.
    if not force:
        items = collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=include_history)
        return {
            "ok": True,
            "cached": True,
            "source": cache.get("source", "local_cache_manual") if isinstance(cache, dict) else "local_cache_manual",
            "items": items,
            "scraped_count": len(cached_items),
            "live_count": int(cache.get("scraped_count", len(cached_items)) or len(cached_items)) if isinstance(cache, dict) else len(cached_items),
            "updated_at_text": cache.get("updated_at_text", "") if isinstance(cache, dict) else "",
            "error": "",
            "profile_url": profile_url,
        }

    if not profile_url or is_placeholder_itemsatis_profile_url(profile_url):
        local_items = collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=include_history)
        return {"ok": False, "cached": bool(cached_items), "source": "safe_fallback", "items": local_items, "scraped_count": 0, "live_count": 0, "updated_at_text": cache.get("updated_at_text", "") if isinstance(cache, dict) else "", "error": "Gerçek Itemsatış profil URL'i tanımlı değil. Aşağıdaki formdan profil linkini kaydet.", "profile_url": profile_url}
    parsed_by_id = {}
    fetched_urls = []
    errors = []
    try:
        for url in _itemsatis_profile_page_candidates(profile_url):
            try:
                response = requests.get(url, headers={**HEADERS, "Referer": profile_url, "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"}, timeout=20)
                fetched_urls.append(url)
                if response.status_code >= 400:
                    errors.append(f"{url} HTTP {response.status_code}")
                    continue
                for item in parse_itemsatis_adverts_from_html(response.text, url):
                    advert_id = str(item.get("advert_id", ""))
                    if advert_id:
                        parsed_by_id[advert_id] = item
            except Exception as page_error:
                errors.append(f"{url}: {page_error}")
        parsed_items = sorted(parsed_by_id.values(), key=lambda x: str(x.get("name", "")).lower())
        if parsed_items:
            payload = {"items": parsed_items, "updated_at": now_ts, "updated_at_text": now_tr().strftime("%Y-%m-%d %H:%M:%S"), "profile_url": profile_url, "source": "profile_scrape_multi_page", "fetched_urls": fetched_urls[-80:], "scraped_count": len(parsed_items), "errors": errors[-10:]}
            redis_set_json(ITEMSATIS_ADVERT_CACHE_KEY, payload)
            log("info", "itemsatis_adverts_refreshed", found=len(parsed_items), pages=len(fetched_urls))
            items = collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=include_history)
            return {"ok": True, "cached": False, "source": "profile_scrape_multi_page", "items": items, "scraped_count": len(parsed_items), "live_count": len(parsed_items), "updated_at_text": payload.get("updated_at_text", ""), "error": "", "profile_url": profile_url}
        items = collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=include_history)
        return {"ok": False, "cached": bool(cached_items), "source": "safe_fallback", "items": items, "scraped_count": 0, "live_count": 0, "updated_at_text": cache.get("updated_at_text", "") if isinstance(cache, dict) else "", "error": "Profil sayfalarında public ilan linki yakalanamadı. Özel/gizli ilanlar public profilde görünmeyebilir; ilan linklerini aşağıdaki yapıştırma alanıyla içe aktarabilirsin. " + " | ".join(errors[-3:]), "profile_url": profile_url}
    except Exception as e:
        log("warning", "itemsatis_adverts_fetch_failed", error=str(e))
        return {"ok": False, "cached": bool(cached_items), "source": "safe_fallback", "items": collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=include_history), "scraped_count": 0, "live_count": 0, "updated_at_text": cache.get("updated_at_text", "") if isinstance(cache, dict) else "", "error": str(e), "profile_url": profile_url}

def build_service_cost_quote(panel_key: str, service_id: str, quantity: int = 1000) -> dict:
    """Panel servis ID + adet için tahmini maliyet hesaplar."""
    panel_key = normalize_panel_key(panel_key)
    service_id = str(service_id or "").strip()
    try:
        qty = max(1, int(quantity or 1))
    except Exception:
        qty = 1
    panel = get_panel_config(panel_key)
    service = {
        "panel_key": panel_key,
        "panel": panel.get("name", panel_key),
        "api_url": panel.get("api_url", ""),
        "api_key": panel.get("api_key", ""),
        "service_id": service_id,
    }
    rate_data = fetch_panel_service_rate(service)
    if not rate_data.get("ok"):
        return {"ok": False, "error": rate_data.get("error", "rate_fetch_failed")}
    rate = rate_data.get("rate", "")
    cost_tl = estimate_service_cost_tl(panel_key, rate, qty)
    return {
        "ok": True,
        "panel": panel.get("name", panel_key),
        "panel_key": panel_key,
        "service_id": service_id,
        "service_name": rate_data.get("service_name", ""),
        "quantity": qty,
        "rate_raw": rate,
        "rate_tl": format_panel_rate_tl(panel_key, rate),
        "cost_tl": cost_tl,
        "cost_tl_text": format_tl_amount(cost_tl) if cost_tl is not None else "Bilinmiyor",
        "cached": bool(rate_data.get("cached")),
    }

def search_panel_services(panel_key: str, query: str = "", limit: int = 50):
    """Panel services listesinden servis arar; API key döndürmez."""
    panel_key = normalize_panel_key(panel_key)
    panel = get_panel_config(panel_key)
    if not panel.get("api_url") or not panel.get("api_key"):
        return {"ok": False, "error": "Panel API bilgileri eksik", "items": []}
    data = get_panel_services(panel["api_url"], panel["api_key"], panel.get("name", panel_key))
    if isinstance(data, dict) and "error" in data:
        return {"ok": False, "error": data.get("error"), "items": []}
    if not isinstance(data, list):
        return {"ok": False, "error": "Panel services cevabı liste değil", "items": []}
    q = normalize_text(query)
    items = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("service") or "")
        name = extract_panel_service_name(item) or f"Panel Servisi {sid}"
        category = str(item.get("category") or "")
        rate = str(item.get("rate") or "")
        haystack = normalize_text(" ".join([sid, name, category, rate]))
        if q and q not in haystack:
            continue
        if sid and name:
            cache_panel_service_name(panel_key, sid, name)
        rate_tl_value = panel_rate_to_tl(panel_key, rate)
        items.append({
            "panel_key": panel_key,
            "panel_name": panel.get("name", panel_key),
            "service_id": sid,
            "name": name,
            "category": category,
            "rate_tl": format_panel_rate_tl(panel_key, rate),
            "rate_tl_value": rate_tl_value,
            "cost_1000_tl": format_tl_amount(rate_tl_value) if rate_tl_value is not None else "Bilinmiyor",
            "rate_raw": rate,
            "min": item.get("min", ""),
            "max": item.get("max", ""),
        })
        if len(items) >= int(limit or 50):
            break
    return {"ok": True, "items": items, "panel_name": panel.get("name", panel_key)}


def add_favorite_service(panel_key: str, service_id: str, name: str = "", platform: str = "other", quantity: int = 1000):
    global FAVORITE_SERVICES
    panel_key = normalize_panel_key(panel_key)
    service_id = str(service_id or "").strip()
    if not panel_key or not service_id:
        raise ValueError("Panel ve servis ID gerekli")
    if not str(quantity).isdigit() or int(quantity) <= 0:
        quantity = 1000
    key = f"{panel_key}:{service_id}"
    service_name = str(name or get_cached_panel_service_name(panel_key, service_id) or fetch_panel_service_name_by_id(panel_key, service_id) or f"{get_panel_config(panel_key).get('name', panel_key)} Servis {service_id}").strip()
    FAVORITE_SERVICES[key] = {
        "panel": panel_key,
        "service_id": service_id,
        "name": service_name,
        "platform": normalize_text(platform or "other") or "other",
        "quantity": int(quantity),
        "created_at": int(time.time()),
    }
    save_state()
    return FAVORITE_SERVICES[key]


def delete_favorite_service(favorite_key: str) -> bool:
    global FAVORITE_SERVICES
    favorite_key = str(favorite_key or "").strip()
    if favorite_key in FAVORITE_SERVICES:
        FAVORITE_SERVICES.pop(favorite_key, None)
        save_state()
        return True
    return False

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
            record_balance_history(key, balance_data)
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

    record_balance_history(panel["key"], balance_data)
    save_state()
    currency_note = get_balance_currency_label(balance_data.get("currency", ""))
    extra = f"\n{currency_note}" if currency_note else ""
    send_telegram(
        f"{panel['name']} Bakiyesi:\n\n"
        f"Bakiye: {format_panel_balance_tl(balance_data)}{extra}"
    )


def _panel_api_request(api_url, api_key, action, extra_data=None, panel_name="", timeout=30):
    """Circuit Breaker + güvenli retry korumalı panel API çağrısı.

    Kritik kural:
    - add action otomatik retry yapmaz. Timeout/connection belirsizliğinde çift siparişi önler.
    - balance/status/services gibi okuma işlemlerinde kısa güvenli retry devam eder.
    - Webhook worker içinde circuit açık/bağlantı sorunu olursa sipariş failed'a düşmeden Redis queue'ya geri alınır.
    """
    if not api_url or not api_key:
        return {"error": "API URL veya API KEY eksik"}
    panel_id = normalize_panel_key(panel_name or api_url or "unknown")
    if is_panel_circuit_open(panel_id):
        msg = f"Circuit Breaker aktif. {panel_id} geçici kapalı."
        log("warning", "circuit_open_skip_request", panel=panel_id, action=action)
        if _queue_context_active():
            raise CircuitOpenForOrder(panel_id, msg, retry_after=get_panel_circuit_retry_after(panel_id))
        return {"error": msg, "circuit_open": True, "retryable": True}
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
            log(level, "panel_api_performance", panel=panel_id, action=action, duration=f"{elapsed:.2f}s", status_code=r.status_code, attempt=attempt)
            if r.status_code >= 500:
                last_error = f"HTTP {r.status_code}"
                record_panel_failure(panel_id, last_error)
                if action != "add" and attempt < max_attempts:
                    time.sleep(PANEL_RETRY_SLEEP_SECONDS)
                    continue
                if _queue_context_active() and action in {"balance", "services"}:
                    raise CircuitOpenForOrder(panel_id, last_error, retry_after=QUEUE_RETRY_DELAY_SEC)
            try:
                result = r.json()
            except Exception:
                result = {"error": f"Panel {action} JSON cevap vermedi", "raw": r.text[:300]}
            if isinstance(result, dict):
                result.setdefault("_duration", elapsed)
                result.setdefault("_attempt", attempt)
            if isinstance(result, dict) and "error" not in result:
                record_panel_success(panel_id)
            return result
        except CircuitOpenForOrder:
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            elapsed = time.perf_counter() - started
            last_error = f"{type(e).__name__}: {e}"
            record_panel_failure(panel_id, last_error)
            log("warning", "panel_api_connection_problem", panel=panel_id, action=action, duration=f"{elapsed:.2f}s", attempt=attempt, error=str(e))
            if action != "add" and attempt < max_attempts:
                time.sleep(PANEL_RETRY_SLEEP_SECONDS)
                continue
            if _queue_context_active() and action in {"balance", "services"}:
                raise CircuitOpenForOrder(panel_id, last_error, retry_after=get_panel_circuit_retry_after(panel_id))
            return {"error": last_error, "duration": elapsed, "attempt": attempt, "retryable": action != "add", "manual_check_required": action == "add"}
        except requests.exceptions.RequestException as e:
            elapsed = time.perf_counter() - started
            last_error = f"RequestException: {e}"
            record_panel_failure(panel_id, last_error)
            log("error", "panel_api_request_exception", panel=panel_id, action=action, duration=f"{elapsed:.2f}s", attempt=attempt, error=str(e))
            if action != "add" and attempt < max_attempts:
                time.sleep(PANEL_RETRY_SLEEP_SECONDS)
                continue
            if _queue_context_active() and action in {"balance", "services"}:
                raise CircuitOpenForOrder(panel_id, last_error, retry_after=get_panel_circuit_retry_after(panel_id))
            return {"error": last_error, "duration": elapsed, "attempt": attempt, "retryable": action != "add", "manual_check_required": action == "add"}
        except Exception as e:
            elapsed = time.perf_counter() - started
            last_error = str(e)
            log("error", "panel_api_error", panel=panel_id, action=action, duration=f"{elapsed:.2f}s", attempt=attempt, error=str(e))
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



def is_low_balance_warning_disabled(panel_key: str = "", panel_name: str = "") -> bool:
    panel_key = normalize_panel_key(panel_key or panel_name or "")
    panel_name_norm = normalize_text(panel_name or "")
    return panel_key in LOW_BALANCE_DISABLED_PANELS or panel_name_norm in LOW_BALANCE_DISABLED_PANELS


def get_low_balance_repeat_minutes(panel_key: str = "", panel_name: str = "") -> int:
    panel_key = normalize_panel_key(panel_key or panel_name or "")
    panel_name_norm = normalize_text(panel_name or "")
    if panel_key in LOW_BALANCE_WARN_REPEAT_MINUTES_BY_PANEL:
        return int(LOW_BALANCE_WARN_REPEAT_MINUTES_BY_PANEL[panel_key])
    if panel_name_norm in LOW_BALANCE_WARN_REPEAT_MINUTES_BY_PANEL:
        return int(LOW_BALANCE_WARN_REPEAT_MINUTES_BY_PANEL[panel_name_norm])
    return int(BALANCE_WARN_REPEAT_MINUTES)

def check_low_balance(balance, currency, panel_name="Panel", panel_key: str = "", force_alert: bool = False):
    """Panel bakiyesi eşik altındaysa Telegram uyarısı gönderir.

    Düzeltmeler:
    - BALANCE_WARN_THRESHOLD_TL env değeri tanımlı.
    - Aynı düşük bakiye uyarısını repeat_minutes aralığıyla tekrarlar.
    - Bakiye eşik üstüne çıkınca alarm hafızasını temizler.
    """
    panel_key = normalize_panel_key(panel_key or panel_name or "")
    if is_low_balance_warning_disabled(panel_key, panel_name):
        log("info", "low_balance_warning_disabled", panel=panel_name or panel_key, balance_tl=balance_tl)
        return False

    repeat_minutes = get_low_balance_repeat_minutes(panel_key, panel_name)
    try:
        balance_tl = convert_balance_to_try(balance, currency)
        if balance_tl is None:
            log("warning", "balance_parse_failed", panel=panel_name, balance=balance, currency=currency)
            return False

        key = normalize_panel_key(panel_key or panel_name)
        now_ts = int(time.time())
        threshold = float(BALANCE_WARN_THRESHOLD_TL)
        repeat_seconds = max(60, int(repeat_minutes) * 60)

        if balance_tl > threshold:
            if key in BALANCE_WARN_LAST:
                BALANCE_WARN_LAST.pop(key, None)
                save_state()
                log("info", "low_balance_recovered", panel=panel_name, balance_tl=round(balance_tl, 2), threshold=threshold)
            return False

        last_warn = int(BALANCE_WARN_LAST.get(key, 0) or 0)
        if (not force_alert) and last_warn and (now_ts - last_warn) < repeat_seconds:
            log(
                "info",
                "low_balance_warning_suppressed",
                panel=panel_name,
                balance_tl=round(balance_tl, 2),
                threshold=threshold,
                next_warn_seconds=repeat_seconds - (now_ts - last_warn),
            )
            return False

        BALANCE_WARN_LAST[key] = now_ts
        save_state()
        log("warning", "low_balance", panel=panel_name, balance=balance, currency=currency, balance_tl=round(balance_tl, 2), threshold=threshold)
        send_telegram_alert(
            f"{panel_name} bakiyesi {format_tl_amount(threshold)} altına düştü.\n\n"
            f"Kalan: {format_tl_amount(balance_tl)}\n"
            f"Tekrar uyarı aralığı: {repeat_minutes} dk\n\n"
            f"Lütfen panel bakiyesini kontrol et."
        )
        return True
    except Exception as e:
        log("error", "balance_check_error", panel=panel_name, error=str(e))
        return False


def check_all_panel_balances(force_alert: bool = False):
    """Tüm panelleri kontrol eder; düşük bakiye uyarısını periyodik çalıştırır.
    force_alert=True manuel check-up için tekrar aralığını bypass eder.
    """
    results = {}
    changed = False
    for key in PANEL_MAP.keys():
        panel = get_panel_config(key)
        if not panel.get("api_url") or not panel.get("api_key"):
            results[key] = {"ok": False, "error": "Eksik env"}
            continue
        balance_data = panel_balance(panel["api_url"], panel["api_key"], panel.get("name", key))
        if isinstance(balance_data, dict) and "error" in balance_data:
            log("error", "panel_balance_check_error", panel=key, error=balance_data.get("error"))
            results[key] = {"ok": False, "error": balance_data.get("error")}
            continue
        record_balance_history(key, balance_data)
        alerted = check_low_balance(
            balance_data.get("balance", 0),
            balance_data.get("currency", ""),
            panel.get("name", key),
            panel_key=key,
            force_alert=force_alert,
        )
        changed = True
        results[key] = {"ok": True, "balance": format_panel_balance_tl(balance_data), "alerted": alerted}
    if changed:
        save_state()
    return {"ok": True, "panels": results}


async def periodic_runner(name: str, interval_seconds: int, func, initial_delay: int = 30):
    """FastAPI içinde hafif periyodik görev çalıştırıcı.
    APScheduler gibi ekstra paket gerektirmez. Senkron fonksiyonları thread içinde çalıştırır, event loop'u kilitlemez.
    """
    await asyncio.sleep(initial_delay)

    while True:
        try:
            log("info", f"{name}_start")
            await asyncio.to_thread(func)
            log("info", f"{name}_done")
        except Exception as e:
            log("error", f"{name}_error", error=str(e))

        await asyncio.sleep(max(30, int(interval_seconds or 300)))


@app.on_event("startup")
async def startup_event():
    validate_environment()

    task_specs = {
        "background_check_orders": (int(os.getenv("CHECK_ORDERS_INTERVAL_SECONDS", "300")), check_orders, 45),
        "background_check_services": (int(os.getenv("CHECK_SERVICES_INTERVAL_SECONDS", "300")), check_services, 90),
        "background_check_balances": (CHECK_BALANCE_INTERVAL_SECONDS, check_all_panel_balances, 20),
    }

    for name, (interval, func, delay) in task_specs.items():
        existing = _BACKGROUND_TASKS.get(name)
        if existing and not existing.done():
            log("info", "background_task_already_running", task=name)
            continue
        _BACKGROUND_TASKS[name] = asyncio.create_task(periodic_runner(name, interval, func, delay))


    existing_queue_worker = _BACKGROUND_TASKS.get("itemsatis_queue_worker")
    if existing_queue_worker and not existing_queue_worker.done():
        log("info", "background_task_already_running", task="itemsatis_queue_worker")
    else:
        _BACKGROUND_TASKS["itemsatis_queue_worker"] = asyncio.create_task(itemsatis_queue_worker())
        log("info", "background_itemsatis_queue_worker_started")

    try:
        startup_check = build_system_check()
        if startup_check.get("duplicate_routes"):
            log("error", "duplicate_routes_detected_on_startup", duplicate_routes=startup_check.get("duplicate_routes"))
    except Exception as e:
        log("warning", "startup_system_check_failed", error=str(e))

    log("info", "background_tasks_started", tasks=list(_BACKGROUND_TASKS.keys()))


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
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
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
  <a href="/admin/service-search"><button type="button">Servis Ara</button></a>
  <a href="/admin/itemsatis-adverts"><button type="button">Itemsatış İlanları</button></a>
  <a href="/admin/adverts-bind"><button type="button">İlan Bağla</button></a>
  <a href="/admin/queue-dead"><button type="button">Queue Dead</button></a>
  <a href="/admin/favorites"><button type="button">Favoriler</button></a>
  <a href="/admin/package-test"><button type="button">Paket Test</button></a>
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

<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      var heads = Array.from(table.querySelectorAll('thead th')).map(function(th){return (th.textContent||'').trim();});
      table.querySelectorAll('tbody tr').forEach(function(row){
        Array.from(row.children).forEach(function(cell, i){
          if(heads[i] && !cell.getAttribute('data-label')) cell.setAttribute('data-label', heads[i]);
        });
      });
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyTableLabels); else applyTableLabels();
})();
</script>


</body>
</html>
"""



@app.post("/admin/low-balance-toggle")
def admin_low_balance_toggle(panel: str = Form(...), disabled: str = Form("true"), user: str = Depends(get_current_admin)):
    """Panel bazlı düşük bakiye uyarısını aç/kapatır."""
    panel_key = normalize_panel_key(panel)
    if not panel_key:
        return RedirectResponse("/admin", status_code=303)

    if str(disabled).lower() in {"1", "true", "yes", "on", "disable", "disabled"}:
        LOW_BALANCE_DISABLED_PANELS.add(panel_key)
        log("warning", "low_balance_panel_disabled_by_admin", panel=panel_key)
    else:
        LOW_BALANCE_DISABLED_PANELS.discard(panel_key)
        log("info", "low_balance_panel_enabled_by_admin", panel=panel_key)

    redis_set_json("low_balance_disabled_panels", sorted(LOW_BALANCE_DISABLED_PANELS))
    return RedirectResponse("/admin", status_code=303)


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




def build_admin_post_confirm_page(title: str, message: str, action: str, fields: dict, cancel_url: str = "/admin") -> HTMLResponse:
    """GET ile gelen state-changing admin işlemlerini direkt çalıştırmak yerine POST onayı ister."""
    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{html.escape(str(k))}" value="{html.escape(str(v))}">'
        for k, v in (fields or {}).items()
    )
    content = f"""
    <!doctype html>
    <html lang="tr">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{html.escape(title)}</title>
      <style>
        body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#050816; color:#f8fafc; font-family:Inter,system-ui,Arial,sans-serif; padding:18px; }}
        .box {{ width:min(560px,100%); background:linear-gradient(180deg,rgba(15,23,42,.96),rgba(2,6,23,.88)); border:1px solid rgba(148,163,184,.22); border-radius:24px; padding:26px; box-shadow:0 20px 60px rgba(0,0,0,.35); }}
        h1 {{ margin:0 0 12px; font-size:28px; letter-spacing:-.04em; }}
        p {{ color:#cbd5e1; line-height:1.65; }}
        .actions {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:22px; }}
        button,a {{ min-height:48px; border-radius:14px; border:1px solid rgba(148,163,184,.24); display:flex; align-items:center; justify-content:center; text-decoration:none; font-weight:800; color:#fff; }}
        button {{ background:linear-gradient(135deg,#22c55e,#16a34a); cursor:pointer; }}
        a {{ background:rgba(15,23,42,.8); }}
        @media(max-width:560px) {{ .actions {{ grid-template-columns:1fr; }} .box {{ padding:20px; }} }}
      </style>
    </head>
    <body>
      <div class="box">
        <h1>{html.escape(title)}</h1>
        <p>{html.escape(message)}</p>
        <form method="post" action="{html.escape(action)}">
          {hidden_inputs}
          <div class="actions">
            <button type="submit">Onayla</button>
            <a href="{html.escape(cancel_url)}">Vazgeç</a>
          </div>
        </form>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=content)

@app.get("/admin/add-service")
def admin_add_service_get(
    advert_id: str = "",
    panel: str = "",
    service_id: str = "",
    quantity: int = 0,
    platform: str = "instagram",
    user: str = Depends(get_current_admin),
):
    """GET ile servis ekleme gelirse 405 yerine güvenli POST onay sayfası gösterir."""
    advert_id = str(advert_id or "").strip()
    panel = str(panel or "").strip()
    service_id = str(service_id or "").strip()
    platform = str(platform or "instagram").strip() or "instagram"
    if advert_id and panel and service_id and int(quantity or 0) > 0:
        return build_admin_post_confirm_page(
            "Servis Ekleme Onayı",
            f"İlan {advert_id} için {panel} panelindeki {service_id} servisi {int(quantity or 0)} adet olarak eklensin mi?",
            "/admin/add-service",
            {"advert_id": advert_id, "panel": panel, "service_id": service_id, "quantity": int(quantity or 0), "platform": platform},
            "/admin",
        )
    log("warning", "admin_add_service_get_missing_fields", advert_id=advert_id, panel=panel, service_id=service_id, quantity=quantity)
    return RedirectResponse("/admin", status_code=303)


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
        prime_service_price_cache(panel, service_id, f"Itemsatış ilanı {advert_id}")
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




@app.get("/admin/delete-service")
def admin_delete_service_get(advert_id: str = "", user: str = Depends(get_current_admin)):
    """GET ile silme gelirse 405 yerine güvenli POST onay sayfası gösterir."""
    advert_id = str(advert_id or "").strip()
    if advert_id:
        return build_admin_post_confirm_page(
            "Servis Silme Onayı",
            f"İlan {advert_id} için kayıtlı dinamik servis silinsin mi?",
            "/admin/delete-service",
            {"advert_id": advert_id},
            "/admin",
        )
    log("warning", "admin_service_delete_get_missing_advert_id")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/toggle-service")
def admin_toggle_service(advert_id: str = Form(...), user: str = Depends(get_current_admin)):
    toggle_dynamic_service(advert_id)
    log("info", "admin_service_toggled", advert_id=advert_id)
    return RedirectResponse("/admin", status_code=303)




@app.get("/admin/toggle-service")
def admin_toggle_service_get(advert_id: str = "", user: str = Depends(get_current_admin)):
    """GET ile aktif/pasif gelirse 405 yerine güvenli POST onay sayfası gösterir."""
    advert_id = str(advert_id or "").strip()
    if advert_id:
        return build_admin_post_confirm_page(
            "Servis Durumu Değiştirme Onayı",
            f"İlan {advert_id} servisinin aktif/pasif durumu değiştirilsin mi?",
            "/admin/toggle-service",
            {"advert_id": advert_id},
            "/admin",
        )
    log("warning", "admin_service_toggle_get_missing_advert_id")
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


@app.post("/admin/reset-sales-all")
def admin_reset_sales_all(user: str = Depends(get_current_admin)):
    """Admin panelden tüm satış raporlarını sıfırlar. Servis, paket, ilan, queue ve pending verilerine dokunmaz."""
    reset_sales_stats("all")
    log("warning", "admin_all_sales_reports_reset", user=user)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/reset-sales-all")
def admin_reset_sales_all_get(user: str = Depends(get_current_admin)):
    """Yanlışlıkla GET açılırsa 404 yerine admin paneline döndürür."""
    return RedirectResponse("/admin", status_code=303)


ADMIN_PACKAGES_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Paketler</title>
<link rel="icon" type="image/png" href="/static/favicon.png?v=4">
<link rel="shortcut icon" href="/static/favicon.png?v=4">
<style>
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
}

</style>
</head>
<body>
<div class="topbar"><a class="back" href="/admin">← Admin Paneline Dön</a><a class="btn slate" href="/">Dashboard</a></div>
<main class="wrap"><section class="shell">
<h1>Boostera Paket Sistemi</h1>
<div class="muted">Tek Itemsatış ilanından birden fazla panel siparişi oluşturur. Aynı müşteri linki paket içindeki tüm bileşenlere gönderilir.</div>
<div class="notice">Paket oluştururken ilk bileşeni de gir. Sonradan aynı pakete izlenme, beğeni, favori, yorum gibi ek bileşenler ekleyebilirsin.</div>

<h2>Paket Oluştur / Güncelle</h2>
<form class="form-grid" method="post" action="/admin/packages/add">
  <input name="advert_id" placeholder="Itemsatış İlan ID" pattern="^\\d+$" required maxlength="20">
  <input class="wide" name="name" placeholder="Paket adı (örn: TikTok Fenomen Paket)" required maxlength="120">
  <select name="platform" required>
    <option value="tiktok">TikTok</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option><option value="x">X/Twitter</option><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="other">Diğer</option>
  </select>
  <input name="first_component_name" placeholder="İlk bileşen adı: İzlenme / Beğeni" required maxlength="80">
  <select name="first_panel" required>{% for key, panel in panels.items() %}<option value="{{ key|e }}">{{ panel.name|e }} ({{ key|e }})</option>{% endfor %}</select>
  <input name="first_service_id" placeholder="İlk panel servis ID" pattern="^\\d+$" required maxlength="20">
  <input name="first_quantity" type="number" min="1" max="1000000" placeholder="İlk adet" required>
  <select name="first_platform" required>
    <option value="tiktok">TikTok</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option><option value="x">X/Twitter</option><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="other">Diğer</option>
  </select>
  <button type="submit">Paketi ve İlk Bileşeni Kaydet</button>
</form>

<h2>Paketler</h2>
<div class="packages">
{% for advert_id, package in packages.items() %}
  <article class="package-card">
    <div class="package-head">
      <div>
        <div class="pkg-title">{{ package.name|e }}</div>
        <div class="pkg-meta">
          <span class="pill">İlan ID: {{ advert_id|e }}</span>
          <span class="pill">Platform: {{ package.platform|e }}</span>
          <span class="pill {{ 'ok' if package.active else 'off' }}">{{ 'Aktif' if package.active else 'Pasif' }}</span>
          <span class="pill">{{ package.components|length }} bileşen</span>
        </div>
      </div>
      <div class="pkg-actions">
        <form method="post" action="/admin/packages/toggle"><input type="hidden" name="advert_id" value="{{ advert_id|e }}"><button class="slate" type="submit">Aktif/Pasif</button></form>
        <form method="post" action="/admin/packages/delete" onsubmit="return confirm('Paket tamamen silinsin mi?')"><input type="hidden" name="advert_id" value="{{ advert_id|e }}"><button class="red" type="submit">Paketi Sil</button></form>
      </div>
    </div>
    <div class="pkg-body">
      <div class="component-form">
        <h3>Bileşen Ekle</h3>
        <form class="stack" method="post" action="/admin/packages/add-component">
          <input type="hidden" name="advert_id" value="{{ advert_id|e }}">
          <input name="name" placeholder="Bileşen adı: İzlenme / Beğeni" required maxlength="80">
          <select name="panel" required>{% for key, panel in panels.items() %}<option value="{{ key|e }}">{{ panel.name|e }} ({{ key|e }})</option>{% endfor %}</select>
          <input name="service_id" placeholder="Panel Servis ID" pattern="^\\d+$" required maxlength="20">
          <input name="quantity" type="number" min="1" max="1000000" placeholder="Adet" required>
          <select name="platform" required>
            <option value="{{ package.platform|e }}">Paket platformu: {{ package.platform|e }}</option>
            <option value="instagram">Instagram</option><option value="tiktok">TikTok</option><option value="youtube">YouTube</option><option value="x">X/Twitter</option><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="other">Diğer</option>
          </select>
          <button class="green" type="submit">Bileşen Ekle</button>
        </form>
      </div>
      <div class="components">
        <h3>Bileşenler</h3>
        <div class="components-grid">
        {% for comp in package.components %}
          <div class="component-card">
            <div class="component-name">{{ comp.name|e }}</div>
            <div class="component-line">Panel: <b>{{ comp.panel_name|e }}</b></div>
            <div class="component-line">Servis ID: <b>{{ comp.service_id|e }}</b> · Adet: <b>{{ comp.quantity|e }}</b></div>
            <div class="component-line">Platform: {{ comp.platform|e }}</div>
            <div class="service-name">{{ comp.panel_service_name or 'Panel servis adı güncellenmedi' }}</div>
            <form class="mt8" method="post" action="/admin/packages/delete-component" onsubmit="return confirm('Bileşen silinsin mi?')">
              <input type="hidden" name="advert_id" value="{{ advert_id|e }}"><input type="hidden" name="component_id" value="{{ comp.id|e }}"><button class="red" type="submit">Bileşeni Sil</button>
            </form>
          </div>
        {% else %}<div class="empty">Bileşen yok.</div>{% endfor %}
        </div>
      </div>
    </div>
  </article>
{% else %}<div class="empty">Henüz paket yok.</div>{% endfor %}
</div>
</section></main>

<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      var heads = Array.from(table.querySelectorAll('thead th')).map(function(th){return (th.textContent||'').trim();});
      table.querySelectorAll('tbody tr').forEach(function(row){
        Array.from(row.children).forEach(function(cell, i){
          if(heads[i] && !cell.getAttribute('data-label')) cell.setAttribute('data-label', heads[i]);
        });
      });
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyTableLabels); else applyTableLabels();
})();
</script>


</body>
</html>
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
def admin_package_add(
    advert_id: str = Form(...),
    name: str = Form(...),
    platform: str = Form("tiktok"),
    first_component_name: str = Form(...),
    first_panel: str = Form(...),
    first_service_id: str = Form(...),
    first_quantity: int = Form(...),
    first_platform: str = Form("tiktok"),
    user: str = Depends(get_current_admin),
):
    try:
        set_package(advert_id, name, platform, True)
        comp = add_package_component(advert_id, first_component_name, first_panel, first_service_id, first_quantity, first_platform)
        panel_service_name = fetch_panel_service_name_by_id(first_panel, first_service_id)
        if panel_service_name:
            cache_panel_service_name(first_panel, first_service_id, panel_service_name)
        prime_service_price_cache(first_panel, first_service_id, f"Paket: {name} / {first_component_name}")
        log("success", "admin_package_saved", advert_id=advert_id, name=name, first_component=comp.get("name"))
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
        package_name = str((PACKAGE_CONFIGS.get(str(advert_id), {}) or {}).get("name") or f"Paket {advert_id}")
        prime_service_price_cache(panel, service_id, f"Paket: {package_name} / {name}")
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
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
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
{% if favorites %}
<div class="notice">Favori servis seçerek panel/servis/adet/platform alanlarını hızlıca doldurabilirsin.</div>
<select id="favoriteSelect" onchange="fillFavorite()">
  <option value="">Favori servis seç</option>
  {% for key, fav in favorites.items() %}
    <option value="{{ key|e }}" data-panel="{{ fav.panel|e }}" data-service="{{ fav.service_id|e }}" data-quantity="{{ fav.quantity|e }}" data-platform="{{ fav.platform|e }}" data-name="{{ fav.name|e }}">{{ fav.name|e }} | {{ fav.panel|e }} #{{ fav.service_id|e }}</option>
  {% endfor %}
</select>
<script>function fillFavorite(){const s=document.getElementById('favoriteSelect');const o=s.options[s.selectedIndex];if(!o||!o.dataset.panel)return;document.querySelector('[name=panel]').value=o.dataset.panel;document.querySelector('[name=service_id]').value=o.dataset.service;document.querySelector('[name=quantity]').value=o.dataset.quantity;document.querySelector('[name=platform]').value=o.dataset.platform;document.querySelector('[name=product_name]').value=o.dataset.name;setTimeout(updateManualCost,80);}</script>
{% endif %}
<form class="grid" method="post" action="/admin/manual-order">
  <label>Panel
    <select id="manualPanel" name="panel" required>
      {% for key, panel in panels.items() %}
        <option value="{{ key|e }}">{{ panel.name|e }} ({{ key|e }})</option>
      {% endfor %}
    </select>
  </label>
  <label>Panel Servis ID
    <input id="manualServiceId" name="service_id" placeholder="Örn: 93" pattern="^\\d+$" title="Sadece rakam giriniz" required maxlength="20">
  </label>
  <label>Adet
    <input id="manualQuantity" name="quantity" type="number" min="1" max="1000000" placeholder="Örn: 1000" required>
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
  <div class="notice full" id="manualCostBox">Panel maliyeti: Panel + servis ID + adet girince otomatik hesaplanır.</div>
  <button class="full" type="submit" onclick="return confirm('Bu sipariş seçilen dış panele gönderilecek. Devam edilsin mi?')">Siparişi Panele Gönder</button>
</form>
</div>

<script>
async function updateManualCost(){
  const panel=document.getElementById('manualPanel')?.value||'';
  const service=document.getElementById('manualServiceId')?.value||'';
  const quantity=document.getElementById('manualQuantity')?.value||'';
  const box=document.getElementById('manualCostBox');
  if(!box) return;
  if(!panel||!service||!quantity){box.textContent='Panel maliyeti: Panel + servis ID + adet girince otomatik hesaplanır.';return;}
  box.textContent='Panel maliyeti hesaplanıyor...';
  try{
    const r=await fetch(`/api/service-cost?panel=${encodeURIComponent(panel)}&service_id=${encodeURIComponent(service)}&quantity=${encodeURIComponent(quantity)}`);
    const d=await r.json();
    if(!d.ok){box.textContent='Panel maliyeti hesaplanamadı: '+(d.error||'bilinmeyen hata');return;}
    box.innerHTML=`Panel fiyatı: <b>${d.rate_tl}</b> / 1000 · Adet: <b>${d.quantity}</b> · Tahmini maliyet: <b>${d.cost_tl_text}</b>`;
  }catch(e){box.textContent='Panel maliyeti hesaplanamadı.';}
}
['manualPanel','manualServiceId','manualQuantity'].forEach(id=>{document.addEventListener('input',e=>{if(e.target&&e.target.id===id) updateManualCost();});document.addEventListener('change',e=>{if(e.target&&e.target.id===id) updateManualCost();});});
</script>

<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      var heads = Array.from(table.querySelectorAll('thead th')).map(function(th){return (th.textContent||'').trim();});
      table.querySelectorAll('tbody tr').forEach(function(row){
        Array.from(row.children).forEach(function(cell, i){
          if(heads[i] && !cell.getAttribute('data-label')) cell.setAttribute('data-label', heads[i]);
        });
      });
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyTableLabels); else applyTableLabels();
})();
</script>


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
    return HTMLResponse(content=template.render(panels=PANEL_MAP, message=message, error=error, favorites=FAVORITE_SERVICES))


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
    manual_service = {
        "panel_key": panel_key,
        "panel": panel_conf.get("name", panel_key),
        "api_url": panel_conf.get("api_url", ""),
        "api_key": panel_conf.get("api_key", ""),
        "service_id": service_id,
        "quantity": quantity,
    }
    balance_data = panel_balance(panel_conf["api_url"], panel_conf["api_key"], panel_conf.get("name", panel_key))
    if "error" in balance_data:
        raise HTTPException(status_code=400, detail=f"Panel bakiyesi alınamadı: {balance_data.get('error')}")
    manual_cost = estimate_order_cost_from_service(manual_service)
    current_balance_tl = convert_balance_to_try(balance_data.get("balance"), balance_data.get("currency", ""))
    if current_balance_tl is not None and manual_cost is not None and current_balance_tl < manual_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Panel bakiyesi yetersiz. Bakiye: {format_tl_amount(current_balance_tl)}, tahmini maliyet: {format_tl_amount(manual_cost)}",
        )

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

    smm_order_id = get_smm_order_id_from_result(smm_result)
    if not smm_order_id:
        log("error", "manual_order_missing_smm_id", panel=panel_key, service_id=service_id, response=str(smm_result)[:500])
        raise HTTPException(status_code=400, detail="Panel siparişi oluştu gibi görünüyor ama SMM order ID dönmedi. Panelden manuel kontrol et; bot pending'e eklemedi.")

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
    manual_cost = estimate_order_cost_from_service(manual_service)
    completion_estimate_text = build_completion_estimate_text(panel_key, service_id, panel_conf.get("name", panel_key))
    send_telegram(
        f"Manuel SMM siparişi panele girildi.\n\n"
        f"Ürün: {final_product_name}\n"
        f"Panel: {panel_conf.get('name', panel_key)}\n"
        f"Servis ID: {service_id}\n"
        f"SMM ID: {smm_order_id}\n"
        f"Adet: {quantity}\n"
        f"Link: {panel_link}\n"
        f"{completion_estimate_text}\n\n"
        f"{build_finance_summary(0, manual_cost)}"
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
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
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

<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      var heads = Array.from(table.querySelectorAll('thead th')).map(function(th){return (th.textContent||'').trim();});
      table.querySelectorAll('tbody tr').forEach(function(row){
        Array.from(row.children).forEach(function(cell, i){
          if(heads[i] && !cell.getAttribute('data-label')) cell.setAttribute('data-label', heads[i]);
        });
      });
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyTableLabels); else applyTableLabels();
})();
</script>


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
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
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

<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      var heads = Array.from(table.querySelectorAll('thead th')).map(function(th){return (th.textContent||'').trim();});
      table.querySelectorAll('tbody tr').forEach(function(row){
        Array.from(row.children).forEach(function(cell, i){
          if(heads[i] && !cell.getAttribute('data-label')) cell.setAttribute('data-label', heads[i]);
        });
      });
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyTableLabels); else applyTableLabels();
})();
</script>


</body>
</html>
"""


@app.get("/admin/failed-orders", response_class=HTMLResponse)
def admin_failed_orders(user: str = Depends(get_current_admin)):
    template = Template(ADMIN_FAILED_HTML)
    html = template.render(failed_orders=list(reversed(FAILED_ORDERS[-50:])))
    return HTMLResponse(content=html)



def retry_failed_order_item(target: dict) -> dict:
    """Tek bir failed order kaydını güvenli şekilde yeniden dener."""
    if not target:
        return {"ok": False, "error": "target_missing"}
    if target.get("retried"):
        return {"ok": False, "error": "already_retried"}
    if not target.get("retryable"):
        return {"ok": False, "error": "not_retryable"}

    advert_id = str(target.get("advert_id", ""))
    raw_service = get_all_services(include_inactive=True).get(advert_id)
    if not raw_service:
        return {"ok": False, "error": "service_config_missing"}

    service = get_service_config(raw_service)
    if not service.get("api_url") or not service.get("api_key"):
        return {"ok": False, "error": "panel_config_missing"}

    smm_result = create_panel_order(
        service["api_url"],
        service["api_key"],
        service["service_id"],
        target.get("link", ""),
        service["quantity"],
        service.get("panel", ""),
    )

    if "error" in smm_result:
        return {"ok": False, "error": smm_result.get("error")}

    new_smm_order_id = get_smm_order_id_from_result(smm_result)
    if not new_smm_order_id:
        return {"ok": False, "error": "panel_order_id_missing", "manual_check_required": True}

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
    target["retried_at"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
    save_state()
    return {"ok": True, "new_smm_order_id": new_smm_order_id, "panel": service.get("panel", "")}


def bulk_retry_failed_orders_worker():
    """Retryable failed siparişleri arka planda sırayla yeniden dener; lock ile çift çalışmayı engeller."""
    if not _BULK_RETRY_LOCK.acquire(blocking=False):
        log("warning", "bulk_retry_already_running")
        return

    success_count = 0
    failed_count = 0
    skipped_count = 0
    errors = []
    try:
        candidates = [item for item in FAILED_ORDERS if item.get("retryable") and not item.get("retried")]
        candidates = candidates[:max(1, BULK_RETRY_MAX)]
        log("info", "bulk_retry_started", total=len(candidates))
        for item in candidates:
            result = retry_failed_order_item(item)
            if result.get("ok"):
                success_count += 1
            else:
                err = str(result.get("error", "unknown"))
                if err in {"already_retried", "not_retryable"}:
                    skipped_count += 1
                else:
                    failed_count += 1
                    errors.append(f"{item.get('smm_order_id', item.get('order_id', '-'))}: {err}")
            time.sleep(max(0, BULK_RETRY_DELAY_SECONDS))
    except Exception as e:
        failed_count += 1
        errors.append(str(e))
        log("error", "bulk_retry_error", error=str(e))
    finally:
        _BULK_RETRY_LOCK.release()
        send_telegram(
            "Bulk retry tamamlandı.\n\n"
            f"Başarılı: {success_count}\n"
            f"Hatalı: {failed_count}\n"
            f"Atlanan: {skipped_count}\n"
            f"Limit: {BULK_RETRY_MAX}\n"
            + (("\nHatalar:\n" + "\n".join(errors[:10])) if errors else "")
        )
        log("info", "bulk_retry_finished", success=success_count, failed=failed_count, skipped=skipped_count)


@app.post("/admin/retry-order")
def admin_retry_order(smm_order_id: str = Form(...), user: str = Depends(get_current_admin)):
    target = None
    for item in reversed(FAILED_ORDERS):
        if str(item.get("smm_order_id", "")) == str(smm_order_id) and item.get("retryable"):
            target = item
            break

    if not target:
        raise HTTPException(status_code=404, detail="Retry yapılabilir başarısız sipariş bulunamadı")

    result = retry_failed_order_item(target)
    if not result.get("ok"):
        log("error", "retry_order_failed", smm_order_id=smm_order_id, error=result.get("error"))
        send_telegram(f"Retry başarısız.\n\nSMM ID: {smm_order_id}\nHata: {result.get('error')}")
        raise HTTPException(status_code=400, detail=str(result.get("error")))

    send_telegram(
        f"Retry başlatıldı.\n\nÜrün: {target.get('product_name', 'Bilinmiyor')}\nPanel: {result.get('panel', '')}\n"
        f"Eski SMM ID: {smm_order_id}\nYeni SMM ID: {result.get('new_smm_order_id')}"
    )
    return RedirectResponse("/admin/failed-orders", status_code=303)


@app.post("/admin/retry-all")
def admin_retry_all(user: str = Depends(get_current_admin)):
    if _BULK_RETRY_LOCK.locked():
        raise HTTPException(status_code=409, detail="Bulk retry zaten çalışıyor")
    thread = threading.Thread(target=bulk_retry_failed_orders_worker, daemon=True)
    thread.start()
    send_telegram("Bulk retry başlatıldı. Uygun başarısız siparişler sırayla yeniden denenecek.")
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
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
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

<script>
(function(){
  function applyTableLabels(){
    document.querySelectorAll('table').forEach(function(table){
      var heads = Array.from(table.querySelectorAll('thead th')).map(function(th){return (th.textContent||'').trim();});
      table.querySelectorAll('tbody tr').forEach(function(row){
        Array.from(row.children).forEach(function(cell, i){
          if(heads[i] && !cell.getAttribute('data-label')) cell.setAttribute('data-label', heads[i]);
        });
      });
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyTableLabels); else applyTableLabels();
})();
</script>


</body>
</html>
"""




# ─── STABLE CLEAN DASHBOARD OVERRIDE ─────────────────────────────────────────
# v12: Eski ağır Chart.js dashboard yerine daha hafif ve stabil dashboard.
# Sipariş/webhook/Redis/queue mantığına dokunmaz; sadece ana panel görünümünü sadeleştirir.
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#070a17;--panel:#0d1326;--card:#111a32;--card2:#0b1022;--border:rgba(148,163,184,.18);--text:#f8fafc;--muted:#94a3b8;--green:#22c55e;--red:#ef4444;--yellow:#f59e0b;--blue:#38bdf8;--purple:#a78bfa;--shadow:0 18px 55px rgba(0,0,0,.30);--radius:22px}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 10% 0%,rgba(124,58,237,.18),transparent 32%),radial-gradient(circle at 90% 0%,rgba(34,211,238,.10),transparent 28%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",Arial,sans-serif;line-height:1.5}.wrap{max-width:1280px;margin:0 auto;padding:24px}.top{display:flex;gap:14px;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap}.brand h1{margin:0;font-size:28px;letter-spacing:-.04em}.brand p{margin:4px 0 0;color:var(--muted)}.nav{display:flex;gap:10px;flex-wrap:wrap}.btn,button{border:1px solid var(--border);background:rgba(15,23,42,.75);color:var(--text);border-radius:14px;padding:11px 14px;text-decoration:none;font-weight:800;cursor:pointer}.btn:hover,button:hover{border-color:rgba(167,139,250,.55);transform:translateY(-1px)}button.green,.green{background:linear-gradient(135deg,#22c55e,#16a34a);border:0;color:white}.red{background:linear-gradient(135deg,#ef4444,#b91c1c);border:0;color:white}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(180deg,rgba(17,26,50,.95),rgba(11,16,34,.92));border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow);min-width:0}.stat .label{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:900}.stat .value{font-size:38px;font-weight:950;margin-top:8px;letter-spacing:-.04em;word-break:break-word}.stat .sub{color:var(--muted);font-size:13px;margin-top:4px}.line{height:3px;border-radius:9px;background:var(--purple);margin:-20px -20px 16px}.line.green{background:var(--green)}.line.red{background:var(--red)}.line.yellow{background:var(--yellow)}.line.blue{background:var(--blue)}.two{display:grid;grid-template-columns:1.2fr .8fr;gap:16px;margin-top:16px}.list{display:grid;gap:10px}.row{display:flex;justify-content:space-between;gap:12px;border:1px solid rgba(148,163,184,.10);background:rgba(2,6,23,.28);border-radius:14px;padding:12px}.muted{color:var(--muted)}.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:900;background:rgba(148,163,184,.12);color:var(--muted)}.pill.ok{background:rgba(34,197,94,.15);color:#86efac}.pill.bad{background:rgba(239,68,68,.15);color:#fca5a5}.pill.warn{background:rgba(245,158,11,.15);color:#fcd34d}pre{white-space:pre-wrap;word-break:break-word;margin:0;font-size:12px;color:#cbd5e1}.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}.danger-note{border-color:rgba(239,68,68,.30);background:rgba(239,68,68,.08)}@media(max-width:980px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}}@media(max-width:640px){.wrap{padding:14px}.grid{grid-template-columns:1fr}.top{align-items:stretch}.nav{display:grid;grid-template-columns:1fr 1fr;width:100%}.btn,button{width:100%;text-align:center}.stat .value{font-size:34px}.row{display:grid;grid-template-columns:1fr}.card{padding:16px;border-radius:18px}.line{margin:-16px -16px 14px}}
/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
}

</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><h1>Boostera Dashboard</h1><p>Stabil, hafif ve hızlı kontrol paneli</p></div>
    <div class="nav">
      <a class="btn" href="/admin">Admin</a>
      <a class="btn" href="/admin/adverts-bind">İlan Bağla</a>
      <a class="btn" href="/admin/itemsatis-adverts">İlanlar</a>
      <a class="btn" href="/admin/queue-dead">Queue Dead</a>
    </div>
  </div>

  <div class="grid">
    <div class="card stat"><div class="line green"></div><div class="label">Bugünkü Sipariş</div><div id="todayCount" class="value">-</div><div id="todaySub" class="sub">yükleniyor</div></div>
    <div class="card stat"><div class="line yellow"></div><div class="label">Bugünkü Brüt</div><div id="todayGross" class="value">-</div><div id="todayNet" class="sub">net hesaplanıyor</div></div>
    <div class="card stat"><div class="line blue"></div><div class="label">Bekleyen</div><div id="pendingCount" class="value">-</div><div class="sub">panel takibindeki sipariş</div></div>
    <div class="card stat"><div class="line red"></div><div class="label">Başarısız</div><div id="failedCount" class="value">-</div><div class="sub">kontrol gereken sipariş</div></div>
  </div>

  <div class="two">
    <div class="card">
      <h2>Operasyon Durumu</h2>
      <div class="list" id="opsRows"><div class="muted">Yükleniyor...</div></div>
      <div class="toolbar">
        <a class="btn" href="/api/system-check" target="_blank">System Check JSON</a>
        <a class="btn" href="/api/queue-status" target="_blank">Queue JSON</a>
        <button onclick="loadAll()">Yenile</button>
      </div>
    </div>
    <div class="card danger-note">
      <h2>Veri Temizliği</h2>
      <p class="muted">Test webhookları yüzünden dashboard tutarları şiştiyse buradan sadece rapor/satış sayaçlarını sıfırlayabilirsin. Servisler, paketler, ilanlar ve Redis queue silinmez.</p>
      <form method="post" action="/admin/reset-dashboard" onsubmit="return confirm('Bu ayın dashboard/rapor verisi sıfırlansın mı?')"><button class="red">Bu Ay Dashboard Sıfırla</button></form>
      <form method="post" action="/admin/reset-sales-all" onsubmit="return confirm('Tüm satış rapor geçmişi sıfırlansın mı? Servis/paket/ilan ayarları silinmez.')" style="margin-top:10px"><button class="red">Tüm Satış Raporlarını Sıfırla</button></form>
    </div>
  </div>

  <div class="two">
    <div class="card">
      <h2>Kâr ve Satış Fırsatları</h2>
      <div class="list" id="growthRows"><div class="muted">Yükleniyor...</div></div>
      <div class="toolbar"><a class="btn green" href="/api/growth-insights" target="_blank">Fırsat JSON</a></div>
    </div>
    <div class="card">
      <h2>Kayıp Sipariş Analizi</h2>
      <div class="list" id="lostRows"><div class="muted">Yükleniyor...</div></div>
    </div>
  </div>

  <div class="two">
    <div class="card"><h2>Son Loglar</h2><div id="logs" class="list"><div class="muted">Yükleniyor...</div></div></div>
    <div class="card"><h2>Hızlı Linkler</h2><div class="list">
      <a class="btn" href="/admin/manual-order">Manuel Sipariş</a>
      <a class="btn" href="/admin/service-search">Servis Ara</a>
      <a class="btn" href="/admin/packages">Paketler</a>
      <a class="btn" href="/api/system-check" target="_blank">Sistem Kontrol</a>
    </div></div>
  </div>
</div>
<script>
function money(v){v=Number(v||0);return v.toLocaleString('tr-TR',{maximumFractionDigits:2})+' ₺'}
function pill(ok,text){return '<span class="pill '+(ok?'ok':'bad')+'">'+text+'</span>'}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'}); if(!r.ok) throw new Error(url+' '+r.status); return await r.json();}
async function loadAll(){
  try{
    const stats=await getJSON('/api/stats');
    document.getElementById('todayCount').textContent=stats.today_count||0;
    document.getElementById('todaySub').textContent='bugünkü kayıtlı satış';
    document.getElementById('todayGross').textContent=money(stats.today_gross||0);
    document.getElementById('todayNet').textContent='net '+money(stats.today_net||0);
    document.getElementById('pendingCount').textContent=stats.pending_count||0;
    document.getElementById('failedCount').textContent=stats.failed_count||0;
  }catch(e){console.error(e)}
  try{
    const sys=await getJSON('/api/system-check');
    const qraw=sys.queue_status||{};
    const q=qraw.queue||qraw;
    const rows=[];
    rows.push('<div class="row"><b>Redis</b><span>'+pill(sys.redis&&sys.redis.ok, sys.redis&&sys.redis.ok?'Sağlıklı':'Kontrol gerekli')+'</span></div>');
    rows.push('<div class="row"><b>Queue bekleyen</b><span>'+(q.waiting||0)+'</span></div>');
    rows.push('<div class="row"><b>Processing</b><span>'+(q.processing||0)+'</span></div>');
    rows.push('<div class="row"><b>Dead queue</b><span class="pill '+((q.dead||0)>0?'bad':'ok')+'">'+(q.dead||0)+'</span></div>');
    rows.push('<div class="row"><b>Dinamik servis</b><span>'+(sys.dynamic_services_count||0)+'</span></div>');
    rows.push('<div class="row"><b>Paket</b><span>'+(sys.packages_count||0)+'</span></div>');
    rows.push('<div class="row"><b>Route çakışması</b><span>'+pill(!(sys.duplicate_routes||[]).length, (sys.duplicate_routes||[]).length?'Var':'Yok')+'</span></div>');
    document.getElementById('opsRows').innerHTML=rows.join('');
  }catch(e){document.getElementById('opsRows').innerHTML='<pre>'+String(e)+'</pre>';}
  try{
    const growth=await getJSON('/api/growth-insights');
    const raises=(growth.price_raise_candidates||[]).slice(0,5);
    const attention=(growth.needs_attention||[]).slice(0,5);
    const growthRows=[];
    if(raises.length){
      raises.forEach(x=>growthRows.push('<div class="row"><div><b>'+String(x.product_name||x.advert_id)+'</b><div class="muted">Fiyat önerisi</div></div><span>'+money(x.avg_sale_tl||0)+' -> '+money(x.recommended_price_tl||0)+'</span></div>'));
    }
    if(!growthRows.length && attention.length){
      attention.forEach(x=>growthRows.push('<div class="row"><div><b>'+String(x.product_name||x.advert_id)+'</b><div class="muted">'+String((x.notes||[]).join(', ')||'Kontrol önerilir')+'</div></div><span class="pill warn">'+(x.health_score||0)+'/100</span></div>'));
    }
    document.getElementById('growthRows').innerHTML=growthRows.length?growthRows.join(''):'<div class="muted">Şu an belirgin fiyat/kâr fırsatı görünmüyor.</div>';
    const lost=growth.lost_orders&&growth.lost_orders.items?growth.lost_orders.items:{};
    const lostRows=Object.keys(lost).sort((a,b)=>(lost[b].count||0)-(lost[a].count||0)).map(k=>'<div class="row"><b>'+k+'</b><span>'+(lost[k].count||0)+' adet</span></div>');
    document.getElementById('lostRows').innerHTML=lostRows.length?lostRows.join(''):'<div class="muted">Kayıp sipariş kaydı yok.</div>';
  }catch(e){
    const g=document.getElementById('growthRows'); if(g) g.innerHTML='<pre>'+String(e)+'</pre>';
  }
  try{
    const data=await getJSON('/api/logs');
    const logs=(data.logs||[]).slice(-12).reverse();
    document.getElementById('logs').innerHTML=logs.length?logs.map(x=>'<div class="row"><div><b>'+String(x.level||'info').toUpperCase()+'</b><div class="muted">'+(x.ts||'')+'</div></div><pre>'+String(x.event||'')+'</pre></div>').join(''):'<div class="muted">Log yok</div>';
  }catch(e){document.getElementById('logs').innerHTML='<pre>'+String(e)+'</pre>';}
}
loadAll(); setInterval(loadAll,30000);
</script>
</body>
</html>
"""



@app.get("/admin/search-services")
def admin_search_services_redirect(user: str = Depends(get_current_admin)):
    return RedirectResponse("/admin/service-search", status_code=303)


@app.get("/admin/system-check")
def admin_system_check_redirect(user: str = Depends(get_current_admin)):
    return RedirectResponse("/api/system-check", status_code=303)

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
    return {"logs": list(LOG_HISTORY)[-80:]}


@app.get("/api/history")
def api_history(user: str = Depends(get_current_admin)):
    return {"orders": ORDER_HISTORY[-200:]}


@app.get("/api/blacklist")
def api_blacklist(user: str = Depends(get_current_admin)):
    return {"items": sorted(BLACKLIST)}


@app.get("/api/balance-history")
def api_balance_history(user: str = Depends(get_current_admin)):
    return {"history": BALANCE_HISTORY}


@app.get("/api/link-audit")
def api_link_audit(user: str = Depends(get_current_admin)):
    return {"items": LINK_AUDIT_HISTORY[-300:]}


@app.get("/api/favorites")
def api_favorites(user: str = Depends(get_current_admin)):
    return {"items": FAVORITE_SERVICES}



@app.get("/api/panel-stats")
def api_panel_stats(user: str = Depends(get_current_admin)):
    """Panel başarı/başarısız/partial istatistikleri."""
    rows = {}
    for panel_key, item in (PANEL_STATS or {}).items():
        try:
            success = int(item.get("success", 0) or 0)
            failed = int(item.get("failed", 0) or 0)
            partial = int(item.get("partial", 0) or 0)
            total = success + failed + partial
            completed_count = int(item.get("completed_count", 0) or 0)
            total_minutes = int(item.get("completed_total_minutes", 0) or 0)
            avg_minutes = round(total_minutes / completed_count, 1) if completed_count else 0
            success_rate = round((success / total) * 100, 2) if total else 0
        except Exception:
            success = failed = partial = total = completed_count = total_minutes = avg_minutes = success_rate = 0
        rows[panel_key] = {
            "success": success,
            "failed": failed,
            "partial": partial,
            "total": total,
            "success_rate": success_rate,
            "avg_completion_minutes": avg_minutes,
            "last_update": item.get("last_update", "") if isinstance(item, dict) else "",
        }
    return {"items": rows}


@app.get("/api/service-completion-stats")
def api_service_completion_stats(user: str = Depends(get_current_admin)):
    """Servis bazlı ortalama tamamlanma süreleri."""
    rows = {}
    for key, item in (SERVICE_COMPLETION_STATS or {}).items():
        if not isinstance(item, dict):
            continue
        rows[key] = {
            "panel_key": item.get("panel_key", ""),
            "service_id": item.get("service_id", ""),
            "completed_count": int(item.get("completed_count", 0) or 0),
            "avg_completion_minutes": float(item.get("avg_completion_minutes", 0) or 0),
            "last_duration_minutes": int(item.get("last_duration_minutes", 0) or 0),
            "last_update": item.get("last_update", ""),
        }
    return {"items": rows}


@app.get("/api/growth-insights")
def api_growth_insights(user: str = Depends(get_current_admin)):
    """Satış, kâr ve kayıp sipariş fırsatlarını hafif state verilerinden hesaplar."""
    return build_product_growth_insights()


@app.get("/api/buyer-stats")
def api_buyer_stats(user: str = Depends(get_current_admin)):
    """Müşteri bazlı sipariş istatistikleri."""
    return {"items": BUYER_STATS or {}}


@app.get("/api/order-notes")
def api_order_notes(user: str = Depends(get_current_admin)):
    """Sipariş notları."""
    return {"items": ORDER_NOTES or {}}



QUEUE_DEAD_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Dead Queue</title>
<style>
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}

/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
}

</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>Boostera Dead Queue</h1>
    <p class="small">Buraya düşen webhooklar otomatik işlenememiştir. Kontrol edip tekrar kuyruğa alabilirsin.</p>
    <p><a href="/admin">← Admin panele dön</a></p>
  </div>

  <div class="card grid">
    <div class="stat"><span class="small">Bekleyen</span><b>{{ status.queue.waiting }}</b></div>
    <div class="stat"><span class="small">İşlenen</span><b>{{ status.queue.processing }}</b></div>
    <div class="stat"><span class="small">Dead</span><b>{{ status.queue.dead }}</b></div>
  </div>

  <div class="card">
    <form method="post" action="/admin/queue-dead/retry" onsubmit="return confirm('Tüm dead queue tekrar kuyruğa alınsın mı?')">
      <input type="hidden" name="retry_all" value="1">
      <button class="btn red" type="submit">Tüm Dead Queue'yu Tekrar Dene</button>
    </form>
  </div>

  <div class="card">
    <h2>Dead kayıtlar</h2>
    {% if rows %}
    <table>
      <thead>
        <tr>
          <th>Queue ID</th>
          <th>Order ID</th>
          <th>Deneme</th>
          <th>Sebep</th>
          <th>Payload</th>
          <th>İşlem</th>
        </tr>
      </thead>
      <tbody>
      {% for row in rows %}
        <tr>
          <td>{{ row.id | e }}</td>
          <td>{{ row.order_id | e }}</td>
          <td>{{ row.attempts }}</td>
          <td>{{ row.dead_reason | e }}</td>
          <td><pre>{{ row.payload_preview | e }}</pre></td>
          <td>
            <form method="post" action="/admin/queue-dead/retry">
              <input type="hidden" name="queue_id" value="{{ row.id | e }}">
              <button class="btn" type="submit">Tekrar Kuyruğa Al</button>
            </form>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
      <p class="small">Dead queue boş.</p>
    {% endif %}
  </div>
</div>
</body>
</html>
"""


@app.get("/admin/queue-dead", response_class=HTMLResponse)
def admin_queue_dead(user: str = Depends(get_current_admin)):
    raw_rows = read_queue_items(ITEMSATIS_WEBHOOK_DEAD_KEY, 100)
    rows = []
    for item in raw_rows:
        payload = item.get("payload", {}) if isinstance(item, dict) else {}
        rows.append({
            "id": item.get("id", ""),
            "order_id": get_order_id(payload if isinstance(payload, dict) else item),
            "attempts": item.get("attempts", 0),
            "dead_reason": item.get("dead_reason", item.get("last_error", "")),
            "payload_preview": json.dumps(payload or item, ensure_ascii=False, indent=2, default=str)[:3000],
        })
    return HTMLResponse(Template(QUEUE_DEAD_HTML).render(rows=rows, status=build_queue_status()))


@app.post("/admin/queue-dead/retry")
def admin_queue_dead_retry(
    queue_id: str = Form(""),
    retry_all: str = Form(""),
    user: str = Depends(get_current_admin),
):
    moved = retry_dead_queue_item(queue_id=queue_id, retry_all=bool(retry_all))
    send_telegram_alert(
        f"Dead queue yeniden deneme işlemi yapıldı.\n\n"
        f"Taşınan kayıt: {moved}\n"
        f"Queue ID: {queue_id or 'Tümü'}"
    )
    return RedirectResponse("/admin/queue-dead", status_code=303)


@app.get("/api/queue-status")
def api_queue_status(user: str = Depends(get_current_admin)):
    return build_queue_status()



def build_redis_health() -> dict:
    """Upstash Redis REST bağlantısını güvenli şekilde kontrol eder."""
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return {"ok": False, "configured": False, "result": "missing_env"}
    try:
        started = time.perf_counter()
        result = redis_request(["PING"])
        elapsed = round(time.perf_counter() - started, 3)
        ok = isinstance(result, dict) and str(result.get("result", "")).upper() == "PONG"
        return {"ok": ok, "configured": True, "duration_sec": elapsed, "result": result.get("result") if isinstance(result, dict) else result}
    except Exception as e:
        return {"ok": False, "configured": True, "error": str(e)[:300]}

def build_system_check() -> dict:
    """Genel bot check-up: deploy kıran ve operasyonel riskleri tek yerde özetler."""
    missing_env = validate_environment()
    configured_panels = []
    missing_panels = []
    for key in PANEL_MAP.keys():
        panel = get_panel_config(key)
        row = {"key": key, "name": panel.get("name", key), "configured": is_panel_configured(key)}
        if row["configured"]:
            configured_panels.append(row)
        else:
            missing_panels.append(row)

    background = {}
    for name, task in (_BACKGROUND_TASKS or {}).items():
        background[name] = {
            "running": bool(task and not task.done()),
            "done": bool(task.done()) if task else True,
        }

    duplicate_routes = []
    seen_routes = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = tuple(sorted(getattr(route, "methods", []) or []))
        key = (path, methods)
        if key in seen_routes:
            duplicate_routes.append({"path": path, "methods": list(methods)})
        seen_routes.add(key)

    return {
        "ok": not bool(duplicate_routes),
        "time_tr": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "webhook_security": {
            "secret_configured": bool(WEBHOOK_SECRET_TOKEN),
            "require_secret": bool(REQUIRE_WEBHOOK_SECRET),
            "ip_whitelist_count": len(WEBHOOK_IP_WHITELIST),
            "warning": "" if WEBHOOK_SECRET_TOKEN else "WEBHOOK_SECRET_TOKEN boş. Üretimde token tanımlaman önerilir.",
        },
        "routes_count": len(app.routes),
        "duplicate_routes": duplicate_routes,
        "missing_env": missing_env,
        "configured_panels": configured_panels,
        "missing_panels": missing_panels,
        "pending_count": len(PENDING_ORDERS),
        "failed_count": len(FAILED_ORDERS),
        "packages_count": len(PACKAGE_CONFIGS or {}),
        "dynamic_services_count": len(DYNAMIC_SERVICES or {}),
        "balance_alerts": {
            "threshold_tl": BALANCE_WARN_THRESHOLD_TL,
            "repeat_minutes": BALANCE_WARN_REPEAT_MINUTES,
            "last_warn": BALANCE_WARN_LAST,
        },
        "background_tasks": background,
        "redis": build_redis_health(),
        "queue_status": build_queue_status(),
        "itemsatis_adverts": {
            "profile_url_configured": bool(ITEMSATIS_PROFILE_URL),
            "cached_count": len((redis_get_json(ITEMSATIS_ADVERT_CACHE_KEY, {}) or {}).get("items", []) or []),
            "local_count": len(collect_itemsatis_adverts_from_local_state()),
        },
        "telegram": {
            "main_configured": bool(BOT_TOKEN and CHAT_ID),
            "alerts_configured": bool(BOT_TOKEN and CHAT_ID_ALERTS),
            "sales_configured": bool(BOT_TOKEN and CHAT_ID_SALES),
            "errors_configured": bool(BOT_TOKEN and CHAT_ID_ERRORS),
        },
        "state": {
            "processed_orders": len(PROCESSED_ORDERS),
            "processed_links": len(PROCESSED_LINKS),
            "log_history": len(LOG_HISTORY),
            "link_audit": len(LINK_AUDIT_HISTORY),
            "service_completion_stats": len(SERVICE_COMPLETION_STATS or {}),
        },
    }


@app.get("/api/system-check")
def api_system_check(user: str = Depends(get_current_admin)):
    return build_system_check()


@app.get("/api/profit")
def api_profit(sale: float = 0, cost: float = 0, user: str = Depends(get_current_admin)):
    return calculate_profit(sale, cost)


@app.get("/api/export")
def api_export(user: str = Depends(get_current_admin)):
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["order_id", "advert_id", "product_name", "panel", "smm_order_id", "link", "price", "duration_minutes", "estimated_completion_minutes", "completed_at"],
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
    return check_all_panel_balances(force_alert=False)


@app.get("/check-balances")
@app.head("/check-balances")
def check_balances_now(user: str = Depends(get_current_admin)):
    """Admin manuel bakiye check-up. Düşük bakiyelerde tekrar uyarı aralığını bypass eder."""
    return check_all_panel_balances(force_alert=True)



ADMIN_TOOL_CSS = """
<style>
:root {
  color-scheme: dark;
  --bg: #050713;
  --bg2: #090d1c;
  --surface: rgba(15, 23, 42, 0.86);
  --surface2: rgba(17, 24, 39, 0.92);
  --surface3: rgba(30, 41, 59, 0.72);
  --card: rgba(15, 23, 42, 0.88);
  --card2: rgba(2, 6, 23, 0.55);
  --border: rgba(148, 163, 184, 0.16);
  --border2: rgba(148, 163, 184, 0.26);
  --text: #f8fafc;
  --muted: #94a3b8;
  --muted2: #64748b;
  --primary: #8b5cf6;
  --primary2: #6d28d9;
  --primary-soft: rgba(139, 92, 246, 0.16);
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --green2: #15803d;
  --yellow: #f59e0b;
  --red: #ef4444;
  --red2: #dc2626;
  --shadow: 0 22px 70px rgba(0, 0, 0, 0.36);
  --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.24);
  --radius: 22px;
  --radius2: 16px;
}

* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  background:
    radial-gradient(circle at 8% -6%, rgba(139, 92, 246, .26), transparent 30%),
    radial-gradient(circle at 98% 0%, rgba(34, 211, 238, .14), transparent 28%),
    radial-gradient(circle at 50% 105%, rgba(59, 130, 246, .10), transparent 34%),
    linear-gradient(180deg, #050713 0%, #080b18 46%, #04050b 100%);
  overflow-x: hidden;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.55), transparent 78%);
  z-index: -1;
}
a { color: #c4b5fd; text-decoration: none; transition: color .15s ease, opacity .15s ease; }
a:hover { color: #ede9fe; }
img, svg, canvas { max-width: 100%; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { color: #e9d5ff; background: rgba(139, 92, 246, .12); padding: 2px 6px; border-radius: 8px; }
pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; background: rgba(2,6,23,.56); border: 1px solid var(--border); border-radius: 14px; padding: 12px; color: #cbd5e1; }

/* Layout */
header, .topbar {
  width: min(1560px, calc(100% - 32px));
  margin: 16px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(15,23,42,.82), rgba(15,23,42,.68));
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  position: sticky;
  top: 10px;
  z-index: 20;
}
.logo { font-size: 25px; font-weight: 950; letter-spacing: -.055em; color: var(--text); }
.logo span { color: var(--primary); text-shadow: 0 0 22px rgba(139,92,246,.36); }
.wrap, .container, .shell {
  width: min(1560px, calc(100% - 32px));
  margin: 18px auto 42px;
  background: linear-gradient(180deg, rgba(15,23,42,.72), rgba(2,6,23,.36));
  border: 1px solid var(--border);
  border-radius: 28px;
  padding: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
  min-width: 0;
}
.wrap { background: transparent; border: 0; box-shadow: none; padding: 0; }
.shell, .container { overflow: hidden; }
h1 { margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); line-height: 1.02; letter-spacing: -.06em; }
h2 { margin: 30px 0 16px; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.1; letter-spacing: -.045em; }
h3 { margin: 0 0 13px; color: #cbd5e1; font-size: 13px; text-transform: uppercase; letter-spacing: .11em; }
.muted, .small { color: var(--muted); font-size: 13px; line-height: 1.58; }
.notice {
  background: linear-gradient(90deg, rgba(59,130,246,.22), rgba(139,92,246,.12));
  border: 1px solid rgba(147,197,253,.18);
  color: #dbeafe;
  padding: 13px 15px;
  border-radius: 16px;
  margin: 16px 0;
  font-size: 14px;
  line-height: 1.58;
}

/* Navigation / toolbars */
.toolbar, .top-actions, .filters, .pkg-actions, .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 18px 0 22px;
}
.toolbar a:not(:has(button)), .top-actions a:not(:has(button)) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #d8b4fe;
  background: rgba(15,23,42,.68);
  font-weight: 850;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03);
}
.toolbar a:not(:has(button)):hover, .top-actions a:not(:has(button)):hover { border-color: rgba(139,92,246,.50); background: rgba(139,92,246,.14); }

/* Grids */
.g4, .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 15px; margin-bottom: 18px; }
.g2, .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; margin-bottom: 18px; }
.grid, form.grid, .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 13px; margin: 18px 0 22px; }
.form-grid .wide { grid-column: span 2; }
.packages { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 16px; }
.components-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 13px; align-items: stretch; }

/* Cards */
.card, .package-card, .component-card, .component-form, .stat {
  position: relative;
  background: linear-gradient(180deg, rgba(15,23,42,.92), rgba(2,6,23,.60));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-soft);
  min-width: 0;
  overflow: hidden;
}
.card::after, .package-card::after, .component-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
}
.card { margin-bottom: 0; }
.card:hover, .package-card:hover, .component-card:hover { border-color: rgba(139,92,246,.30); }
.sc, .stat-card { position: relative; overflow: hidden; }
.sc::before, .stat-card::before, .stat::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--cyan));
}
.sc.ok::before, .stat-card.success::before { background: linear-gradient(90deg, var(--green), #86efac); }
.sc.warn::before, .stat-card.warning::before { background: linear-gradient(90deg, var(--yellow), #fde68a); }
.sc.err::before, .stat-card.danger::before { background: linear-gradient(90deg, var(--red), #fca5a5); }
.sc.cy::before, .stat-card.cyan::before { background: linear-gradient(90deg, var(--cyan), var(--blue)); }
.sl, .stat-label, .ct, .card-title {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 900;
}
.sl, .stat-label { margin-bottom: 8px; }
.sv, .stat-value, .stat b { font-size: clamp(27px, 3.6vw, 44px); font-weight: 950; letter-spacing: -.06em; color: #fff; line-height: 1.05; }
.ss, .stat-sub { margin-top: 5px; color: var(--muted); font-size: 12px; }
.ct, .card-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 11px; border-bottom: 1px solid var(--border); }
.empty { color: var(--muted); text-align: center; padding: 22px; border: 1px dashed var(--border2); border-radius: 16px; background: rgba(15,23,42,.38); }

/* Forms */
label { color: #cbd5e1; font-size: 13px; font-weight: 750; }
input, select, textarea {
  width: 100%;
  min-height: 48px;
  padding: 12px 13px;
  border-radius: 15px;
  border: 1px solid var(--border2);
  background: rgba(15,23,42,.78);
  color: var(--text);
  outline: none;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}
input::placeholder, textarea::placeholder { color: #64748b; }
input:focus, select:focus, textarea:focus { border-color: rgba(139,92,246,.76); box-shadow: 0 0 0 4px rgba(139,92,246,.16); }
input[type="checkbox"], input[type="radio"] { width: auto; min-height: 0; }
select { appearance: auto; }
button, .btn, .rbtn, .link-btn, .refresh-btn {
  min-height: 46px;
  border-radius: 15px;
  border: 0;
  padding: 11px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  background: linear-gradient(135deg, var(--primary), var(--primary2));
  color: #fff;
  font-weight: 900;
  font: inherit;
  line-height: 1.18;
  text-align: center;
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease, border-color .16s ease;
  text-decoration: none;
  white-space: normal;
  touch-action: manipulation;
  box-shadow: 0 10px 22px rgba(109,40,217,.22);
}
button:hover, .btn:hover, .rbtn:hover, .refresh-btn:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: 0 14px 28px rgba(109,40,217,.30); }
button.delete, button.red, .btn.red { background: linear-gradient(135deg, var(--red), var(--red2)); color:#fff; box-shadow: 0 10px 22px rgba(220,38,38,.22); }
button.green, .btn.green { background: linear-gradient(135deg, #22c55e, var(--green2)); color:#fff; box-shadow: 0 10px 22px rgba(21,128,61,.22); }
button.toggle, button.slate, .btn.slate { background: linear-gradient(135deg, #475569, #334155); color:#fff; box-shadow: none; }
.inline-form, .actions form { display: inline-flex; margin: 0 5px 6px 0; }

/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 18px; border: 1px solid var(--border); background: rgba(2,6,23,.34); }
table, .table { width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border-radius: 18px; background: rgba(2,6,23,.30); }
th, td, .table th, .table td { padding: 14px 13px; border-bottom: 1px solid rgba(148,163,184,.10); text-align: left; vertical-align: middle; }
th, .table th { background: rgba(15,23,42,.90); color: #cbd5e1; font-size: 12px; letter-spacing: .10em; text-transform: uppercase; font-weight: 950; white-space: nowrap; }
td, .table td { color: var(--text); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tr:hover td { background: rgba(139,92,246,.045); }
.service-name, .component-name, .pkg-title, .rdet, .order-detail, .lm, .log-meta, td, a, .history-title, .history-meta, .history-link { overflow-wrap: anywhere; word-break: break-word; }
.service-name { max-width: 440px; color: #dbeafe; line-height: 1.42; }
.service-name.missing { color: #8a8fa3; font-style: italic; }

/* Packages */
.package-card { background: linear-gradient(180deg, rgba(15,23,42,.95), rgba(2,6,23,.68)); }
.package-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: start; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
.pkg-title { font-size: 20px; font-weight: 950; letter-spacing: -.035em; color: #fff; }
.pkg-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.pkg-actions { justify-content: flex-end; margin: 0; }
.pkg-actions form { flex: 0 1 170px; }
.pkg-body { display: grid; grid-template-columns: minmax(300px, 440px) minmax(0,1fr); gap: 16px; align-items: start; }
.component-form { background: rgba(15,23,42,.60); }
.component-form .stack { display: grid; gap: 10px; }
.component-card { display: flex; flex-direction: column; gap: 9px; background: rgba(15,23,42,.76); border-color: rgba(96,165,250,.16); }
.component-card form { margin-top: auto; }
.component-name { font-size: 16px; font-weight: 950; color:#fff; }
.component-line { color: #cbd5e1; font-size: 13px; line-height: 1.45; }

/* Badges */
.pill, .badge, .price-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.15;
  background: rgba(30,41,59,.90);
  color: #cbd5e1;
  border: 1px solid rgba(148,163,184,.12);
}
.pill.ok, .badge.ok, .badge.active, .active { background: rgba(5,150,105,.18); color: #86efac; border-color: rgba(34,197,94,.22); }
.pill.off, .badge.off, .badge.passive, .passive { background: rgba(239,68,68,.15); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.badge.pending { background: rgba(245,158,11,.16); color: #fcd34d; border-color: rgba(245,158,11,.25); }
.badge.failed { background: rgba(239,68,68,.16); color: #fca5a5; border-color: rgba(239,68,68,.25); }
.price-badge { background: rgba(139,92,246,.16); color: #ddd6fe; border-color: rgba(139,92,246,.28); }

/* Dashboard lists/logs */
.row, .order-row, .history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(148,163,184,.09); min-width: 0; }
.row:last-child, .order-row:last-child, .history-row:last-child { border-bottom: 0; }
.row > div, .order-row > div, .history-row > div { min-width: 0; }
.rdet, .order-detail, .history-meta { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; margin-top: 3px; }
.history-title { font-weight: 850; color: #e2e8f0; }
.history-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.ll, .log-list { max-height: 390px; overflow-y: auto; padding-right: 4px; scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.32) transparent; }
.ll::-webkit-scrollbar, .log-list::-webkit-scrollbar, pre::-webkit-scrollbar { width: 6px; height: 6px; }
.ll::-webkit-scrollbar-thumb, .log-list::-webkit-scrollbar-thumb, pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,.30); border-radius: 999px; }
.le, .log-entry { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.lts, .log-ts { color: var(--muted); font-size: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; flex: 0 0 auto; }
.lv, .log-level { flex: 0 0 auto; font-size: 9px; padding: 3px 7px; border-radius: 8px; font-weight: 950; text-transform: uppercase; }
.lv.info, .log-level.info { background: rgba(139,92,246,.22); color:#c4b5fd; }
.lv.success, .log-level.success { background: rgba(16,185,129,.18); color:#86efac; }
.lv.warning, .log-level.warning { background: rgba(245,158,11,.18); color:#fcd34d; }
.lv.error, .log-level.error { background: rgba(239,68,68,.18); color:#fca5a5; }
.lev, .log-event { min-width: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.lm, .log-meta { color: var(--muted); font-size: 10px; }
.bar-wrap { display:flex; align-items:flex-end; height:88px; gap:5px; margin-top:10px; }
.bar { flex:1; min-width:4px; min-height:2px; border-radius:5px 5px 0 0; background: linear-gradient(180deg,#c4b5fd,#7c3aed); opacity:.76; }
.bar:hover { opacity:1; }
.tab { padding:8px 13px; border-radius:12px; cursor:pointer; color:var(--muted); font-size:12px; font-weight:950; background:rgba(15,23,42,.54); border:1px solid var(--border); }
.tab.active { background: linear-gradient(135deg, var(--primary), var(--primary2)); color:#fff; border-color: transparent; }

/* Chart area */
canvas { max-width: 100%; }
.chart-wrap, .chart-card { min-height: 280px; }

/* Mobile */
@media (max-width: 1180px) {
  .g4, .grid-4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .g2, .grid-2, .pkg-body { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: span 2; }
}
@media (max-width: 780px) {
  body { font-size: 14px; }
  body::before { opacity: .55; background-size: 30px 30px; }
  header, .topbar, .container, .wrap, .shell { width: 100%; max-width: 100%; margin: 0; border-left: 0; border-right: 0; border-radius: 0; }
  header, .topbar { position: static; flex-direction: column; align-items: stretch; padding: 14px 12px; }
  .wrap, .container, .shell { padding: 13px; overflow-x: hidden; }
  h1 { font-size: 28px; letter-spacing: -.045em; }
  h2 { font-size: 22px; }
  .logo { font-size: 22px; }
  .g4, .grid-4, .g2, .grid-2, .grid, form.grid, .form-grid, .components-grid { grid-template-columns: 1fr; }
  .form-grid .wide { grid-column: auto; }
  .toolbar, .top-actions, .filters, .pkg-actions { display: grid; grid-template-columns: 1fr; width: 100%; gap: 9px; }
  .toolbar a, .toolbar form, .toolbar button, .top-actions a, .top-actions form, .pkg-actions form, .pkg-actions button, .btn, .rbtn, .link-btn { width: 100%; justify-content: center; }
  input, select, textarea, button, .btn, .rbtn, .link-btn { min-height: 50px; font-size: 16px; width: 100%; }
  .card, .package-card, .component-card, .component-form { padding: 14px; border-radius: 18px; }
  .ct, .card-title { flex-direction: column; align-items: flex-start; }
  .package-head { grid-template-columns: 1fr; }
  .pkg-actions { justify-content: stretch; }
  .pkg-body, .package-head, .components-grid { grid-template-columns: 1fr !important; }
  .pkg-meta { gap: 6px; }
  .pill, .badge { font-size: 11px; padding: 5px 9px; }
  .row, .order-row, .history-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .history-meta { gap: 6px; }
  .bar-wrap { height: 76px; }
  .ll, .log-list { max-height: 330px; }

  .table-wrap { overflow: visible; border: 0; background: transparent; }
  table, .table { width: 100%; display: block; background: transparent; border: 0; border-radius: 0; overflow: visible; white-space: normal; }
  thead { display: none !important; }
  tbody { display: grid !important; gap: 12px; width: 100%; }
  tr { display: grid !important; width: 100%; background: linear-gradient(180deg, rgba(15,23,42,.94), rgba(2,6,23,.72)); border: 1px solid var(--border); border-radius: 18px; padding: 8px; box-shadow: var(--shadow-soft); overflow: hidden; }
  tr:hover td { background: transparent; }
  th { display: none; }
  td, .table td { display: grid !important; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: start; width: 100%; min-width: 0; max-width: 100%; padding: 10px 8px; border-bottom: 1px solid rgba(148,163,184,.10); white-space: normal !important; overflow-wrap: anywhere; word-break: break-word; font-size: 14px; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); color: var(--muted); font-size: 10px; line-height: 1.35; font-weight: 950; letter-spacing: .10em; text-transform: uppercase; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  td[data-label="İşlem"], td[data-label="İŞLEM"], td[data-label="Bileşen Ekle"], td[data-label="BİLEŞEN EKLE"], td[data-label="Payload"] { grid-template-columns: 1fr; }
  td[data-label="İşlem"]::before, td[data-label="İŞLEM"]::before, td[data-label="Bileşen Ekle"]::before, td[data-label="BİLEŞEN EKLE"]::before, td[data-label="Payload"]::before { margin-bottom: 4px; }
  td form, td .inline-form, .actions form { width: 100%; display: grid; gap: 8px; margin: 0 0 8px 0; }
  td button, td .btn, td .rbtn { width: 100%; }
}
@media (max-width: 430px) {
  td, .table td { grid-template-columns: 1fr; gap: 5px; }
  td::before { margin-bottom: 2px; }
  .wrap, .container, .shell { padding: 10px; }
  .card, .package-card, .component-card, .component-form { padding: 12px; border-radius: 16px; }
  h1 { font-size: 24px; }
  .sv, .stat-value, .stat b { font-size: 27px; }
  .notice, .muted, .small { font-size: 13px; }
  .toolbar a:not(:has(button)), .top-actions a:not(:has(button)) { min-height: 46px; }
}


/* Itemsatış ilan sayfası mobil düzeltme */
.itemsatis-stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.itemsatis-stat { min-width:0; overflow:hidden; }
@media (max-width: 700px) { .itemsatis-stats { grid-template-columns:1fr !important; } .itemsatis-stat { width:100%; } }
/* ─── BOOSTERA V15 UI POLISH: daha profesyonel + mobil dostu ─────────────── */
:root {
  --v15-bg-deep: #050816;
  --v15-panel: rgba(15, 23, 42, .78);
  --v15-panel-strong: rgba(15, 23, 42, .94);
  --v15-border: rgba(148, 163, 184, .20);
  --v15-border-strong: rgba(168, 85, 247, .32);
  --v15-glow-purple: rgba(139, 92, 246, .28);
  --v15-glow-cyan: rgba(34, 211, 238, .18);
  --v15-shadow: 0 18px 55px rgba(0, 0, 0, .34);
  --v15-radius: 24px;
}

html { scroll-behavior: smooth; }

body {
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 10%, rgba(139, 92, 246, .14), transparent 30%),
    radial-gradient(circle at 86% 18%, rgba(34, 211, 238, .10), transparent 26%),
    linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, .24) 100%);
  z-index: -2;
}

header,
.topbar {
  border-color: var(--v15-border);
  background: linear-gradient(180deg, rgba(15, 23, 42, .86), rgba(2, 6, 23, .72));
  box-shadow: 0 16px 44px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.04);
}

.logo,
.brand,
h1,
h2,
h3 {
  letter-spacing: -0.035em;
}

.container,
.shell,
.wrap {
  width: min(1560px, calc(100% - 32px));
}

.card,
.stat,
.stat-card,
.notice,
.filter-box,
.package-card,
.component-card,
.chart-wrap {
  border: 1px solid var(--v15-border);
  background:
    linear-gradient(180deg, rgba(15,23,42,.88), rgba(2,6,23,.62)),
    radial-gradient(circle at top left, rgba(139,92,246,.10), transparent 32%);
  box-shadow: var(--v15-shadow), inset 0 1px 0 rgba(255,255,255,.035);
  border-radius: var(--v15-radius);
}

.card:hover,
.stat:hover,
.stat-card:hover,
.package-card:hover,
.component-card:hover {
  border-color: rgba(196,181,253,.34);
  transform: translateY(-1px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.card-title,
.stat-label,
.label {
  letter-spacing: .12em;
}

.stat-value,
.value {
  letter-spacing: -0.055em;
}

.badge,
.pill,
.price-badge {
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
  white-space: nowrap;
}

button,
.btn,
.link-btn,
.refresh-btn,
input[type="submit"] {
  min-height: 42px;
  touch-action: manipulation;
  font-weight: 800;
  letter-spacing: -.01em;
}

button:hover,
.btn:hover,
.link-btn:hover,
.refresh-btn:hover,
input[type="submit"]:hover {
  transform: translateY(-1px);
}

input,
select,
textarea {
  min-height: 44px;
  border-color: rgba(148,163,184,.22) !important;
  background: rgba(2,6,23,.45) !important;
  color: #f8fafc !important;
  outline: none;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(168,85,247,.72) !important;
  box-shadow: 0 0 0 4px rgba(139,92,246,.14);
}

textarea { resize: vertical; }

table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

th {
  color: #c4b5fd;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}

td, th { vertical-align: middle; }

.log-list,
pre,
textarea {
  scrollbar-width: thin;
  scrollbar-color: rgba(139,92,246,.45) rgba(15,23,42,.45);
}

.log-list::-webkit-scrollbar,
pre::-webkit-scrollbar,
textarea::-webkit-scrollbar,
.card::-webkit-scrollbar {
  height: 7px;
  width: 7px;
}

.log-list::-webkit-scrollbar-thumb,
pre::-webkit-scrollbar-thumb,
textarea::-webkit-scrollbar-thumb,
.card::-webkit-scrollbar-thumb {
  background: rgba(139,92,246,.45);
  border-radius: 999px;
}

.nav,
.top-actions,
.actions,
.toolbar {
  gap: 10px;
}

.nav a,
.top-actions a,
.actions a,
.toolbar a,
.toolbar button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.card:has(table),
.notice:has(table),
.filter-box:has(table) {
  overflow-x: auto;
}

.price-badge,
.value,
.stat-value {
  text-shadow: 0 0 24px rgba(139,92,246,.15);
}

@media (max-width: 900px) {
  header,
  .topbar {
    position: static;
    width: calc(100% - 20px);
    margin: 10px auto 0;
    padding: 12px;
    border-radius: 18px;
    flex-direction: column;
    align-items: stretch;
  }

  .logo,
  .brand {
    font-size: clamp(20px, 6vw, 28px);
    line-height: 1.05;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 20px);
    margin-left: auto;
    margin-right: auto;
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  .grid,
  .grid-2,
  .grid-3,
  .grid-4,
  .two,
  .form-grid,
  .components-grid,
  .packages {
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 14px !important;
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 18px !important;
    border-radius: 20px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  .nav a,
  .top-actions a,
  .actions a,
  .toolbar a,
  .toolbar button,
  .btn,
  .link-btn,
  .refresh-btn,
  button,
  input[type="submit"] {
    width: 100%;
    min-height: 48px;
    padding: 12px 14px !important;
    border-radius: 14px !important;
    font-size: 14px;
    text-align: center;
  }

  input,
  select,
  textarea {
    width: 100% !important;
    font-size: 16px !important;
    border-radius: 14px !important;
  }

  label,
  .label {
    font-size: 13px;
  }

  table {
    min-width: 720px;
    font-size: 13px;
  }

  td, th {
    padding: 10px 12px !important;
  }

  .stat-value,
  .value {
    font-size: clamp(30px, 12vw, 46px) !important;
    line-height: 1.05;
    word-break: break-word;
  }

  .stat-label {
    font-size: 11px !important;
  }

  .log-entry,
  .order-row,
  .history-row,
  .line,
  .component-line {
    align-items: flex-start !important;
    gap: 8px !important;
  }

  .muted,
  .small,
  .sub,
  .stat-sub,
  .order-detail {
    font-size: 13px !important;
    line-height: 1.55;
  }

  pre {
    max-height: 320px;
  }
}

@media (max-width: 560px) {
  body { font-size: 14px; }

  header,
  .topbar {
    width: calc(100% - 14px);
    margin-top: 7px;
    border-radius: 16px;
  }

  .container,
  .shell,
  .wrap {
    width: calc(100% - 14px);
  }

  .card,
  .stat,
  .stat-card,
  .notice,
  .filter-box,
  .package-card,
  .component-card,
  .chart-wrap {
    padding: 15px !important;
    border-radius: 18px !important;
  }

  .nav,
  .top-actions,
  .actions,
  .toolbar {
    grid-template-columns: 1fr !important;
  }

  h1 { font-size: clamp(28px, 10vw, 42px) !important; }
  h2 { font-size: clamp(22px, 8vw, 32px) !important; }
  h3 { font-size: clamp(18px, 6vw, 24px) !important; }

  .stat-value,
  .value {
    font-size: clamp(28px, 14vw, 42px) !important;
  }

  .badge,
  .pill,
  .price-badge {
    display: inline-flex;
    max-width: 100%;
    white-space: normal;
    line-height: 1.25;
  }

  .row,
  .order-row,
  .history-row,
  .line,
  .package-head,
  .component-line {
    flex-direction: column !important;
    align-items: stretch !important;
  }

  table {
    min-width: 640px;
  }

  .card:has(table),
  .notice:has(table),
  .filter-box:has(table) {
    margin-left: -2px;
    margin-right: -2px;
  }
}

@supports (padding: max(0px)) {
  body {
    padding-left: max(0px, env(safe-area-inset-left));
    padding-right: max(0px, env(safe-area-inset-right));
  }
}



/* BOOSTERA_PRO_UI_OVERRIDE_V19 */
:root {
  --action-primary: #2563eb;
  --action-primary2: #1d4ed8;
  --action-success: #16a34a;
  --action-success2: #15803d;
  --action-warn: #d97706;
  --action-warn2: #b45309;
  --action-danger: #dc2626;
  --action-danger2: #991b1b;
  --action-neutral: #475569;
  --action-neutral2: #334155;
  --touch: 44px;
}
body { letter-spacing: 0; }
.card, .panel, section, table, form { min-width: 0; }
button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
  min-height: var(--touch);
  border-radius: 10px !important;
  padding: 10px 14px !important;
  font-weight: 850 !important;
  letter-spacing: 0 !important;
  line-height: 1.15 !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px rgba(15, 23, 42, .22) !important;
}
button:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.btn:not(.red):not(.delete):not(.green):not(.slate):not(.toggle):not(.retry),
.refresh-btn {
  background: linear-gradient(135deg, var(--action-primary), var(--action-primary2)) !important;
  border-color: rgba(147,197,253,.28) !important;
  color: #fff !important;
}
button.green, .btn.green, input[type="submit"].green,
a[href*="manual-order"].btn, a[href*="bind"].btn, a[href*="service-search"].btn {
  background: linear-gradient(135deg, var(--action-success), var(--action-success2)) !important;
  border-color: rgba(134,239,172,.24) !important;
  color: #fff !important;
}
button.red, button.delete, .btn.red, .btn.delete,
form[action*="delete"] button, form[action*="reset"] button, form[action*="cancel"] button {
  background: linear-gradient(135deg, var(--action-danger), var(--action-danger2)) !important;
  border-color: rgba(252,165,165,.24) !important;
  color: #fff !important;
}
button.slate, button.toggle, .btn.slate, .btn.toggle,
a[href*="queue"].btn, a[href*="system-check"].btn, a[href*="api/"] .btn {
  background: linear-gradient(135deg, var(--action-neutral), var(--action-neutral2)) !important;
  border-color: rgba(203,213,225,.18) !important;
  color: #fff !important;
}
button.retry, .btn.retry, form[action*="retry"] button {
  background: linear-gradient(135deg, var(--action-warn), var(--action-warn2)) !important;
  border-color: rgba(253,230,138,.24) !important;
  color: #fff !important;
}
button:hover, .btn:hover, .rbtn:hover, .link-btn:hover, .refresh-btn:hover {
  filter: brightness(1.04) !important;
  transform: translateY(-1px) !important;
}
.toolbar, .top-actions, .nav, .pkg-actions, .tabs {
  gap: 8px !important;
  align-items: center !important;
}
.toolbar form, .top-actions form, .pkg-actions form { margin: 0 !important; }
input, select, textarea {
  border-radius: 10px !important;
  min-height: var(--touch);
  font-size: 15px !important;
}
table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
}
th, td { vertical-align: top !important; }
td form { display: inline-flex; gap: 6px; margin: 2px 0 !important; }
.row { align-items: center; }
.pill { border-radius: 999px !important; }
@media (max-width: 760px) {
  body { font-size: 14px !important; }
  header, .topbar, .wrap, .container, .shell {
    width: calc(100% - 18px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }
  header, .topbar {
    position: static !important;
    padding: 12px !important;
    border-radius: 16px !important;
    align-items: stretch !important;
  }
  .wrap, .container, .shell {
    padding: 12px !important;
    border-radius: 18px !important;
  }
  h1 { font-size: 28px !important; }
  h2 { font-size: 20px !important; margin-top: 20px !important; }
  .grid, .two, .cards, .stats, .form-grid {
    grid-template-columns: 1fr !important;
  }
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    width: 100% !important;
  }
  .toolbar > *, .top-actions > *, .nav > *, .pkg-actions > *, .tabs > * {
    width: 100% !important;
    min-width: 0 !important;
  }
  button, .btn, .rbtn, .link-btn, .refresh-btn, input[type="submit"] {
    width: 100% !important;
    min-height: 48px !important;
    justify-content: center !important;
    text-align: center !important;
    font-size: 14px !important;
  }
  input, select, textarea { width: 100% !important; font-size: 16px !important; }
  table { display: block !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
  thead, tbody, tr { min-width: max-content; }
  th, td { padding: 10px !important; font-size: 13px !important; }
  td button, td .btn, td .rbtn { min-width: 120px; }
  .row { display: grid !important; grid-template-columns: 1fr !important; gap: 8px !important; align-items: start !important; }
  pre { max-height: 220px !important; }
}
@media (max-width: 420px) {
  .toolbar, .top-actions, .nav, .pkg-actions, .tabs { grid-template-columns: 1fr !important; }
  h1 { font-size: 24px !important; }
  .stat .value { font-size: 30px !important; }
}

</style>
"""


def simple_admin_page(title: str, body: str) -> HTMLResponse:
    nav = """
    <div class="toolbar">
      <a href="/admin">Admin</a><a href="/">Dashboard</a><a href="/admin/service-search">Servis Ara</a>
      <a href="/admin/itemsatis-adverts">Itemsatış İlanları</a><a href="/admin/adverts-bind">İlan Bağla</a><a href="/admin/queue-dead">Queue Dead</a>
      <a href="/admin/favorites">Favoriler</a><a href="/admin/package-test">Paket Test</a>
      <a href="/admin/balance-history">Bakiye Geçmişi</a><a href="/admin/link-audit">Link Geçmişi</a>
      <a href="/admin/failed-actions">Hata Merkezi</a><a href="/admin/profit-calculator">Kâr Hesapla</a>
    </div>
    """
    html = f"<!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title>{ADMIN_TOOL_CSS}</head><body><main class='wrap'><h1>{title}</h1>{nav}{body}</main></body></html>"
    return HTMLResponse(html)



# ─── İLAN → SERVİS / PAKET BAĞLAMA SİHİRBAZI ────────────────────────────────
def infer_advert_binding_fields(name: str) -> dict:
    """İlan adından platform, adet ve arama terimini tahmin eder. Yanlışsa admin formdan düzeltir."""
    raw = str(name or "").strip()
    text = normalize_text(raw)
    platform = "other"
    platform_keywords = {
        "instagram": ["instagram", "insta", "ig"],
        "tiktok": ["tiktok", "tik tok"],
        "youtube": ["youtube", "yt", "shorts"],
        "x": ["twitter", " x ", "tweet"],
        "twitch": ["twitch"],
        "kick": ["kick"],
    }
    padded = f" {text} "
    for key, words in platform_keywords.items():
        if any(w in padded for w in words):
            platform = key
            break

    quantity = 1000
    try:
        # 20k / 20 bin / 20.000 gibi ifadeleri yakala.
        m = re.search(r"(\d+(?:[\.,]\d+)?)\s*(k|bin)\b", text)
        if m:
            number = float(m.group(1).replace(",", "."))
            quantity = int(number * 1000)
        else:
            numbers = []
            for m in re.finditer(r"\b(\d{1,7})(?:[\.,](\d{3}))?\b", text):
                token = m.group(0).replace(".", "").replace(",", "")
                try:
                    value = int(token)
                except Exception:
                    continue
                # yıl, ay, gün gibi ürün adlarındaki yanıltıcı küçük sayıları tamamen eleme; en büyük makul adet seçilir.
                if 1 <= value <= 1000000:
                    numbers.append(value)
            if numbers:
                quantity = max(numbers)
    except Exception:
        quantity = 1000
    quantity = max(1, min(int(quantity or 1000), 1000000))

    service_words = []
    if "takip" in text or "follower" in text:
        service_words.append("takipçi")
    if "beğeni" in text or "begeni" in text or "like" in text:
        service_words.append("beğeni")
    if "izlen" in text or "view" in text:
        service_words.append("izlenme")
    if "yorum" in text or "comment" in text:
        service_words.append("yorum")
    if "favori" in text or "kaydet" in text or "save" in text:
        service_words.append("favori")
    if "paylaş" in text or "paylas" in text or "share" in text:
        service_words.append("paylaşım")
    if "türk" in text or "turk" in text:
        service_words.append("türk")
    if "paket" in text:
        service_words.append("paket")

    query_parts = []
    if platform != "other":
        query_parts.append(platform)
    query_parts.extend(service_words[:4])
    search_query = " ".join(dict.fromkeys([p for p in query_parts if p])).strip()
    if not search_query:
        # Uzun ilan adını direkt arama diye göndermeyelim, ilk anlamlı kelimeleri kullan.
        search_query = " ".join([w for w in re.sub(r"[^a-zA-ZçğıöşüÇĞİÖŞÜ0-9 ]", " ", raw).split() if len(w) > 2][:4])

    is_package = "paket" in text or len([w for w in ["takip", "beğeni", "begeni", "izlen", "favori", "paylaş", "paylas", "yorum"] if w in text]) >= 2
    return {"platform": platform, "quantity": quantity, "search_query": search_query, "is_package": is_package}


def get_itemsatis_advert_record(advert_id: str) -> dict:
    advert_id = str(advert_id or "").strip()
    for item in collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=False):
        if str((item or {}).get("advert_id")) == advert_id:
            return dict(item or {})
    name = get_itemsatis_report_name(advert_id, "") if advert_id else ""
    return {"advert_id": advert_id, "name": name or f"Itemsatış İlanı {advert_id}", "url": "", "source": "fallback"}


def get_advert_binding_status(advert_id: str) -> dict:
    advert_id = str(advert_id or "").strip()
    has_service = advert_id in get_all_services(include_inactive=True)
    has_package = advert_id in get_package_configs(include_inactive=True)
    if has_service and has_package:
        return {"status": "both", "label": "Servis + Paket bağlı", "class": "ok"}
    if has_service:
        return {"status": "service", "label": "Servise bağlı", "class": "ok"}
    if has_package:
        return {"status": "package", "label": "Pakete bağlı", "class": "ok"}
    return {"status": "missing", "label": "Bağlanmamış", "class": "pending"}


def build_panel_select_options(selected: str = "") -> str:
    selected_key = normalize_panel_key(selected or "")
    return "".join([
        f'<option value="{html.escape(k)}" {"selected" if k == selected_key else ""}>{html.escape(v.get("name", k))} ({html.escape(k)})</option>'
        for k, v in PANEL_MAP.items()
    ])


def build_platform_options(selected: str = "") -> str:
    selected = normalize_text(selected or "other") or "other"
    platforms = ["instagram", "tiktok", "youtube", "x", "twitch", "kick", "other"]
    return "".join([f'<option value="{p}" {"selected" if p == selected else ""}>{p}</option>' for p in platforms])


def service_search_rows_for_binding(items: list, advert_id: str, quantity: int, platform: str, mode: str = "service", component_name: str = "") -> str:
    rows = []
    advert_id_e = html.escape(str(advert_id))
    for item in items or []:
        panel_key = str(item.get("panel_key", ""))
        service_id = str(item.get("service_id", ""))
        safe_name = html.escape(str(item.get("name", "")))
        safe_category = html.escape(str(item.get("category", "")))
        safe_panel = html.escape(str(item.get("panel_name", panel_key)))
        rate_tl = html.escape(str(item.get("rate_tl", "")))
        rate_value = "" if item.get("rate_tl_value") is None else str(item.get("rate_tl_value"))
        cost_html = "-"
        try:
            if rate_value:
                cost = (float(rate_value) / 1000) * int(quantity or 0)
                cost_html = f"{cost:.4f} TL"
        except Exception:
            pass
        if mode == "package":
            action = (
                f"<form method='post' action='/admin/bind-package/add-component'>"
                f"<input type='hidden' name='advert_id' value='{advert_id_e}'>"
                f"<input type='hidden' name='panel' value='{html.escape(panel_key)}'>"
                f"<input type='hidden' name='service_id' value='{html.escape(service_id)}'>"
                f"<input type='number' name='quantity' value='{int(quantity or 1000)}' min='1' max='1000000' required>"
                f"<input name='component_name' value='{html.escape(component_name or str(item.get('name',''))[:60])}' placeholder='Bileşen adı'>"
                f"<input type='hidden' name='platform' value='{html.escape(platform)}'>"
                f"<button class='green'>Bileşen Olarak Ekle</button></form>"
            )
        else:
            action = (
                f"<form method='post' action='/admin/bind-service/save'>"
                f"<input type='hidden' name='advert_id' value='{advert_id_e}'>"
                f"<input type='hidden' name='panel' value='{html.escape(panel_key)}'>"
                f"<input type='hidden' name='service_id' value='{html.escape(service_id)}'>"
                f"<input type='hidden' name='quantity' value='{int(quantity or 1000)}'>"
                f"<input type='hidden' name='platform' value='{html.escape(platform)}'>"
                f"<button class='green'>Bu Servise Bağla</button></form>"
            )
        rows.append(
            f"<tr data-rate-tl='{html.escape(rate_value)}'><td data-label='Panel'>{safe_panel}</td>"
            f"<td data-label='ID'><code>{html.escape(service_id)}</code></td>"
            f"<td data-label='Servis'>{safe_name}</td>"
            f"<td data-label='Kategori'>{safe_category}</td>"
            f"<td data-label='Fiyat'>{rate_tl} / 1000</td>"
            f"<td data-label='Tahmini Maliyet'>{html.escape(cost_html)}</td>"
            f"<td data-label='Min/Max'>{html.escape(str(item.get('min','')))} / {html.escape(str(item.get('max','')))}</td>"
            f"<td data-label='İşlem'>{action}</td></tr>"
        )
    return "".join(rows)


@app.get("/admin/service-search", response_class=HTMLResponse)
def admin_service_search(panel: str = "medyabayim", q: str = "", user: str = Depends(get_current_admin)):
    result = {"items": []}
    panel_key = normalize_panel_key(panel)
    if q:
        result = search_panel_services(panel_key, q, 80)

    row_parts = []
    for item in result.get("items", []):
        safe_name = html.escape(str(item.get("name", "")))
        safe_category = html.escape(str(item.get("category", "")))
        safe_panel_name = html.escape(str(item.get("panel_name", "")))
        safe_service_id = html.escape(str(item.get("service_id", "")))
        safe_panel_key = html.escape(str(item.get("panel_key", "")))
        safe_rate_tl = html.escape(str(item.get("rate_tl", "")))
        safe_rate_value = "" if item.get("rate_tl_value") is None else str(item.get("rate_tl_value"))
        row_parts.append(
            f"<tr data-rate-tl='{safe_rate_value}'>"
            f"<td data-label='Panel'>{safe_panel_name}</td>"
            f"<td data-label='ID'><code>{safe_service_id}</code></td>"
            f"<td data-label='Servis'>{safe_name}</td>"
            f"<td data-label='Kategori'>{safe_category}</td>"
            f"<td data-label='Fiyat TL'>{safe_rate_tl} / 1000</td>"
            f"<td data-label='Maliyet'><input class='costQty' type='number' min='1' value='50' style='min-height:38px' oninput='calcServiceSearchCosts()'><div class='muted costOut'>Adet girince hesaplanır</div></td>"
            f"<td data-label='Min/Max'>{html.escape(str(item.get('min','')))} / {html.escape(str(item.get('max','')))}</td>"
            f"<td data-label='İşlem'><form method='post' action='/admin/favorites/add'>"
            f"<input type='hidden' name='panel' value='{safe_panel_key}'>"
            f"<input type='hidden' name='service_id' value='{safe_service_id}'>"
            f"<input type='hidden' name='name' value=\"{safe_name}\">"
            f"<input type='number' name='quantity' placeholder='Adet' value='1000'>"
            f"<select name='platform'><option>tiktok</option><option>instagram</option><option>youtube</option><option>x</option><option>twitch</option><option>kick</option><option>other</option></select>"
            f"<button class='green'>Favoriye Ekle</button></form></td></tr>"
        )
    rows = "".join(row_parts)
    error = "" if result.get("ok", True) else f"<div class='card'>Hata: {html.escape(str(result.get('error')))}</div>"
    options = "".join([
        f'<option value="{html.escape(k)}" {"selected" if k==panel_key else ""}>{html.escape(v.get("name",k))} ({html.escape(k)})</option>'
        for k, v in PANEL_MAP.items()
    ])
    body = f"""
    <div class='card'><div class='muted'>Panel servislerini isim, ID veya kategoriyle ara. Fiyat ve adet bazlı tahmini maliyet TL olarak gösterilir.</div>
    <form class='grid' method='get'><select name='panel'>{options}</select><input name='q' value='{html.escape(str(q))}' placeholder='Örn: tiktok views, takipçi, 123'><button>Ara</button></form></div>
    {error}
    <div class='card'><table class='table'><thead><tr><th>Panel</th><th>ID</th><th>Servis</th><th>Kategori</th><th>Fiyat TL</th><th>Adet Maliyeti</th><th>Min/Max</th><th>İşlem</th></tr></thead><tbody>{rows or '<tr><td>Arama yap veya sonuç yok.</td></tr>'}</tbody></table></div>
    <script>
    function calcServiceSearchCosts(){{
      document.querySelectorAll('tr[data-rate-tl]').forEach(function(row){{
        var rate=parseFloat(row.getAttribute('data-rate-tl')||'');
        var qty=parseFloat((row.querySelector('.costQty')||{{}}).value||'0');
        var out=row.querySelector('.costOut');
        if(!out) return;
        if(!rate||!qty){{out.textContent='Hesaplanamadı';return;}}
        out.textContent='Tahmini maliyet: '+((rate/1000)*qty).toFixed(4)+' TL';
      }});
    }}
    calcServiceSearchCosts();
    </script>
    """
    return simple_admin_page("Panel Servis Arama", body)


@app.get("/api/service-cost")
def api_service_cost(panel: str, service_id: str, quantity: int = 1000, user: str = Depends(get_current_admin)):
    return build_service_cost_quote(panel, service_id, quantity)


@app.get("/admin/itemsatis-adverts", response_class=HTMLResponse)
def admin_itemsatis_adverts(refresh: int = 0, history: int = 0, user: str = Depends(get_current_admin)):
    result = fetch_itemsatis_public_adverts(force=bool(refresh), include_history=bool(history))
    items = result.get("items", []) or []
    total_count = len(items)
    scraped_count = int(result.get("scraped_count", 0) or 0)
    live_count = int(result.get("live_count", 0) or scraped_count or 0)
    updated_at_text = html.escape(str(result.get("updated_at_text", "")))
    profile_url = str(result.get("profile_url") or get_itemsatis_profile_url() or "")
    count_warning = ""
    if not result.get("ok"):
        count_warning = f"<div class='notice danger'>Profil çekimi uyarısı: {html.escape(str(result.get('error','')))} </div>"
    elif scraped_count == 0:
        count_warning = "<div class='notice warning'>Profil kontrolü yapıldı ama public ilandan ID yakalanamadı.</div>"
    rows = []
    for item in items:
        advert_id = str(item.get("advert_id", ""))
        name = html.escape(str(item.get("name", "")))
        source = html.escape(str(item.get("source", "")))
        status = item.get("status", "missing")
        label = html.escape(str(item.get("label", "Eşleşmemiş")))
        pill_class = "green" if status in {"service", "package", "both"} else ""
        url = str(item.get("url", ""))
        url_html = f"<a href='{html.escape(url)}' target='_blank' rel='noopener'>Aç</a>" if url else "-"
        rows.append(
            f"""<tr>
<td data-label='İlan ID'><code>{html.escape(advert_id)}</code><button type='button' onclick="navigator.clipboard&&navigator.clipboard.writeText('{html.escape(advert_id)}')">Kopyala</button></td>
<td data-label='İlan Adı'>{name}</td>
<td data-label='Durum'><span class='pill {pill_class}'>{label}</span></td>
<td data-label='Kaynak'>{source}</td>
<td data-label='Link'>{url_html}</td>
<td data-label='İşlem'><div class='toolbar' style='gap:6px;align-items:stretch;'><a class='btn' href='/admin/bind-service?advert_id={html.escape(advert_id)}'>Servise Bağla</a><a class='btn' href='/admin/bind-package?advert_id={html.escape(advert_id)}'>Pakete Bağla</a><form method='post' action='/admin/itemsatis-adverts/delete' onsubmit="return confirm('Bu ilan cache listesinden silinsin mi? Servis/paket eşleşmesi silinmez.');"><input type='hidden' name='advert_id' value='{html.escape(advert_id)}'><button class='red'>Sil</button></form></div></td>
</tr>"""
        )
    history_link = "/admin/itemsatis-adverts?history=1" if not history else "/admin/itemsatis-adverts"
    history_text = "Geçmiş webhook kayıtlarını da göster" if not history else "Geçmiş webhook kayıtlarını gizle"
    body = f"""
    <style>
      .itemsatis-stats {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:18px; }}
      .itemsatis-stat {{ min-width:0; padding:16px; border:1px solid var(--border); border-radius:18px; background:rgba(15,23,42,.55); }}
      .itemsatis-stat b {{ display:block; color:var(--text); font-size:14px; line-height:1.35; margin-bottom:7px; }}
      .itemsatis-stat .stat {{ display:block; font-size:28px; line-height:1; color:var(--accent2); font-weight:950; }}
      .itemsatis-tools {{ display:grid; grid-template-columns:1fr; gap:14px; }}
      .itemsatis-tools textarea {{ min-height:150px; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
      @media(max-width:700px) {{ .itemsatis-stats {{ grid-template-columns:1fr; }} .itemsatis-stat {{ padding:14px; }} .itemsatis-stat .stat {{ font-size:25px; }} }}
    
</style>
    <div class='card'>
      <div class='muted'>Bu sayfa gerçek public profil ilanlarını yakalamaya çalışır. Özel/gizli kişiye özel ilanlar public profilde görünmeyebilir; bu durumda ilan linklerini aşağıdaki alana yapıştırarak ID + isim olarak cache'e alabilirsin. Test webhook/geçmiş siparişler artık ana listeye otomatik karışmaz.</div>
      <div class='toolbar'>
        <form method='post' action='/admin/itemsatis-adverts/refresh' style='display:inline;'><button class='green' type='submit'>İlanları ve Sayıyı Tekrar Kontrol Et</button></form>
        <a class='btn' href='/admin/itemsatis-adverts?refresh=1'>Hızlı Yenile</a>
        <a class='btn' href='{history_link}'>{history_text}</a>
        <form method='post' action='/admin/itemsatis-adverts/clear' style='display:inline;' onsubmit="return confirm('İçe aktarılan ilan cache temizlensin mi? Dinamik servis/paket ayarları silinmez.');"><button class='red' type='submit'>İlan Cache Temizle</button></form>
        <a class='btn' href='/admin/adverts-bind'>İlan Bağlama Sihirbazı</a>
      </div>
      <div class='itemsatis-stats'>
        <div class='itemsatis-stat'><b>Listelenen ilan</b><span class='stat'>{total_count}</span></div>
        <div class='itemsatis-stat'><b>Profilden yakalanan</b><span class='stat'>{scraped_count}</span></div>
        <div class='itemsatis-stat'><b>Son canlı sayım</b><span class='stat'>{live_count or '-'}</span></div>
      </div>
      <div class='muted' style='margin-top:14px'>Profil URL: {html.escape(profile_url or 'Tanımlı değil')}</div>
      <div class='muted'>Kaynak: {html.escape(str(result.get('source','')))} | Cache: {html.escape(str(result.get('cached', False)))} | Son kontrol: {updated_at_text or '-'}</div>
      {count_warning}
    </div>
    <div class='card itemsatis-tools'><h2>Profil URL Ayarı</h2><form method='post' action='/admin/itemsatis-adverts/settings' class='grid'><input name='profile_url' value='{html.escape(profile_url)}' placeholder='https://www.itemsatis.com/profil/mağaza-adın veya public profil linkin'><button class='green'>Profil URL Kaydet</button></form><div class='muted'>Render Environment yerine buradan da profil linkini kaydedebilirsin. Kaydettikten sonra “İlanları ve Sayıyı Tekrar Kontrol Et” butonuna bas.</div></div>
    <div class='card itemsatis-tools'><h2>Toplu İlan İçe Aktar</h2><form method='post' action='/admin/itemsatis-adverts/import-preview'><textarea name='raw_text' placeholder='Tarayıcı konsolundan çıkan listeyi buraya yapıştır. Örnek:
Instagram 100 Türk Takipçi | 1234567 | https://www.itemsatis.com/kategori/instagram-100-turk-takipci-1234567.html'></textarea><button class='green'>Önizle ve Seç</button></form><div class='muted'>Bot önce önizleme yapar. Sadece işaretlediğin ilanlar Redis'e kaydedilir; 125 satır gelse bile yanlış olanları elemek kolaylaşır.</div></div>
    <div class='card'><table class='table'><thead><tr><th>İlan ID</th><th>İlan Adı</th><th>Durum</th><th>Kaynak</th><th>Link</th><th>İşlem</th></tr></thead><tbody>{''.join(rows) or '<tr><td>Henüz ilan bulunamadı. Profil URL kaydet veya ilan linklerini içe aktar.</td></tr>'}</tbody></table></div>
    """
    return simple_admin_page("Itemsatış İlanları", body)


@app.post("/admin/itemsatis-adverts/settings")
def admin_itemsatis_adverts_settings(profile_url: str = Form(""), user: str = Depends(get_current_admin)):
    save_itemsatis_profile_url(profile_url)
    return RedirectResponse("/admin/itemsatis-adverts?refresh=1", status_code=303)


@app.post("/admin/itemsatis-adverts/import-preview", response_class=HTMLResponse)
def admin_itemsatis_adverts_import_preview(raw_text: str = Form(""), user: str = Depends(get_current_admin)):
    preview = build_itemsatis_import_preview(raw_text)
    rows = []
    all_rows = [("Temiz Görünenler", preview.get("accepted", [])), ("Şüpheli / Kontrol Gerekli", preview.get("suspicious", []))]
    for group_title, group_items in all_rows:
        if not group_items:
            continue
        rows.append(f"<tr><td colspan='5'><b>{html.escape(group_title)}</b></td></tr>")
        for idx, item in enumerate(group_items):
            payload = html.escape(json.dumps({"advert_id": item.get("advert_id"), "name": item.get("name"), "url": item.get("url"), "source": "manual_import"}, ensure_ascii=False), quote=True)
            checked = "checked" if item.get("default_checked") else ""
            reasons = ", ".join(item.get("reasons") or []) or "-"
            rows.append(
                f"<tr>"
                f"<td data-label='Seç'><input class='import-check' type='checkbox' name='selected_items' value='{payload}' {checked}></td>"
                f"<td data-label='İlan ID'><code>{html.escape(str(item.get('advert_id','')))}</code></td>"
                f"<td data-label='İlan Adı'>{html.escape(str(item.get('name','')))}</td>"
                f"<td data-label='Link'>{('<a href=' + repr(html.escape(str(item.get('url','')))) + ' target=_blank>Aç</a>') if item.get('url') else '-'}</td>"
                f"<td data-label='Not'>{html.escape(reasons)}</td>"
                f"</tr>"
            )
    body = f"""
    <div class='card'>
      <h2>İlan İçe Aktarma Önizleme</h2>
      <div class='itemsatis-stats'>
        <div class='itemsatis-stat'><b>Yapıştırılan satır</b><span class='stat'>{int(preview.get('line_count', 0))}</span></div>
        <div class='itemsatis-stat'><b>Okunan benzersiz ilan</b><span class='stat'>{int(preview.get('parsed_count', 0))}</span></div>
        <div class='itemsatis-stat'><b>Şüpheli</b><span class='stat'>{len(preview.get('suspicious', []))}</span></div>
      </div>
      <div class='notice warning'>Sadece işaretli ilanlar kaydedilir. Şüpheli olanları kontrol etmeden işaretleme.</div>
      <div class='toolbar'><button type='button' onclick="document.querySelectorAll('.import-check').forEach(x=>x.checked=true)">Tümünü Seç</button><button type='button' onclick="document.querySelectorAll('.import-check').forEach(x=>x.checked=false)">Tümünü Kaldır</button><a class='btn' href='/admin/itemsatis-adverts'>Geri Dön</a></div>
    </div>
    <form method='post' action='/admin/itemsatis-adverts/import-confirm'>
      <div class='card'><table class='table'><thead><tr><th>Seç</th><th>ID</th><th>İlan Adı</th><th>Link</th><th>Not</th></tr></thead><tbody>{''.join(rows) or '<tr><td>Hiç ilan okunamadı. Konsol çıktısını veya ilan linklerini kontrol et.</td></tr>'}</tbody></table></div>
      <div class='card'><button class='green'>Seçili İlanları Kaydet</button> <a class='btn' href='/admin/itemsatis-adverts'>İptal</a></div>
    </form>
    """
    return simple_admin_page("İlan İçe Aktarma Önizleme", body)


@app.post("/admin/itemsatis-adverts/import-confirm")
async def admin_itemsatis_adverts_import_confirm(request: Request, user: str = Depends(get_current_admin)):
    form = await request.form()
    selected_values = form.getlist("selected_items")
    items = []
    for raw in selected_values:
        try:
            item = json.loads(str(raw))
            advert_id = str(item.get("advert_id", "")).strip()
            if advert_id and advert_id.isdigit():
                items.append({"advert_id": advert_id, "name": _itemsatis_clean_title(item.get("name", "")) or f"Itemsatış İlanı {advert_id}", "url": str(item.get("url", "")), "source": "manual_import"})
        except Exception as e:
            log("warning", "itemsatis_import_confirm_item_skip", error=str(e))
    save_manual_itemsatis_adverts(items, merge=True)
    return RedirectResponse("/admin/itemsatis-adverts", status_code=303)


@app.post("/admin/itemsatis-adverts/import")
def admin_itemsatis_adverts_import(raw_text: str = Form(""), user: str = Depends(get_current_admin)):
    # Eski endpoint geriye dönük kalsın; artık doğrudan kaydetmek yerine önizleme önerilir.
    items = parse_itemsatis_adverts_from_text(raw_text)
    save_manual_itemsatis_adverts(items, merge=True)
    return RedirectResponse("/admin/itemsatis-adverts", status_code=303)


@app.post("/admin/itemsatis-adverts/delete")
def admin_itemsatis_adverts_delete(advert_id: str = Form(""), user: str = Depends(get_current_admin)):
    remove_itemsatis_advert_from_cache(advert_id)
    return RedirectResponse("/admin/itemsatis-adverts", status_code=303)


@app.post("/admin/itemsatis-adverts/clear")
def admin_itemsatis_adverts_clear(user: str = Depends(get_current_admin)):
    clear_itemsatis_advert_import_cache()
    return RedirectResponse("/admin/itemsatis-adverts", status_code=303)


@app.post("/admin/itemsatis-adverts/refresh")
def admin_itemsatis_adverts_refresh(user: str = Depends(get_current_admin)):
    fetch_itemsatis_public_adverts(force=True)
    return RedirectResponse("/admin/itemsatis-adverts", status_code=303)

@app.get("/admin/adverts-bind", response_class=HTMLResponse)
def admin_adverts_bind(status: str = "missing", q: str = "", user: str = Depends(get_current_admin)):
    status = normalize_text(status or "missing")
    q_norm = normalize_text(q or "")
    items = collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=False)
    rows = []
    counts = {"all": 0, "missing": 0, "service": 0, "package": 0, "both": 0}
    for item in items:
        advert_id = str((item or {}).get("advert_id", "")).strip()
        if not advert_id:
            continue
        name_raw = str((item or {}).get("name") or f"Itemsatış İlanı {advert_id}")
        bind = get_advert_binding_status(advert_id)
        counts["all"] += 1
        counts[bind["status"]] = counts.get(bind["status"], 0) + 1
        if status not in {"", "all"} and bind["status"] != status:
            continue
        if q_norm and q_norm not in normalize_text(f"{advert_id} {name_raw}"):
            continue
        infer = infer_advert_binding_fields(name_raw)
        source = html.escape(str((item or {}).get("source", "")))
        rows.append(
            f"<tr><td data-label='İlan ID'><code>{html.escape(advert_id)}</code></td>"
            f"<td data-label='İlan'>{html.escape(name_raw)}<div class='muted'>Kaynak: {source}</div></td>"
            f"<td data-label='Durum'><span class='badge {html.escape(bind['class'])}'>{html.escape(bind['label'])}</span></td>"
            f"<td data-label='Tahmin'>{html.escape(infer['platform'])} / {int(infer['quantity'])}<div class='muted'>{html.escape(infer['search_query']) or '-'}</div></td>"
            f"<td data-label='İşlem'><div class='toolbar' style='gap:6px;align-items:stretch;'>"
            f"<a class='btn' href='/admin/bind-service?advert_id={html.escape(advert_id)}'>Servise Bağla</a>"
            f"<a class='btn' href='/admin/bind-package?advert_id={html.escape(advert_id)}'>Pakete Bağla</a>"
            f"<a class='btn' href='/admin/itemsatis-adverts'>İlan Listesi</a>"
            f"</div></td></tr>"
        )
    filters = " ".join([
        f"<a class='btn' href='/admin/adverts-bind?status={key}'>{label}: {counts.get(key,0)}</a>"
        for key, label in [("missing","Bağlanmamış"),("service","Servis"),("package","Paket"),("both","İkisi"),("all","Tümü")]
    ])
    body = f"""
    <div class='card'><div class='muted'>İlanları servis veya paketle hızlı bağlamak için bu sihirbazı kullan. İlan adından platform/adet/arama önerisi otomatik tahmin edilir; yanlışsa formda düzeltebilirsin.</div>
      <div class='toolbar'>{filters}</div>
      <form class='grid' method='get'><input type='hidden' name='status' value='{html.escape(status)}'><input name='q' value='{html.escape(q)}' placeholder='İlan adı veya ID ara'><button>Filtrele</button></form>
    </div>
    <div class='card'><table class='table'><thead><tr><th>ID</th><th>İlan</th><th>Durum</th><th>Tahmin</th><th>İşlem</th></tr></thead><tbody>{''.join(rows) or '<tr><td>Bu filtrede ilan yok. Önce Itemsatış İlanları sayfasından içe aktar.</td></tr>'}</tbody></table></div>
    """
    return simple_admin_page("İlan Bağlama Sihirbazı", body)


@app.get("/admin/bind-service", response_class=HTMLResponse)
def admin_bind_service_page(advert_id: str, panel: str = "", q: str = "", quantity: int = 0, platform: str = "", user: str = Depends(get_current_admin)):
    advert = get_itemsatis_advert_record(advert_id)
    name = str(advert.get("name") or f"Itemsatış İlanı {advert_id}")
    infer = infer_advert_binding_fields(name)
    panel_key = normalize_panel_key(panel or "medyabayim")
    quantity = int(quantity or infer.get("quantity") or 1000)
    platform = normalize_text(platform or infer.get("platform") or "other") or "other"
    q = str(q or infer.get("search_query") or "")
    result = search_panel_services(panel_key, q, 80) if q else {"items": []}
    rows = service_search_rows_for_binding(result.get("items", []), advert_id, quantity, platform, "service")
    existing = get_all_services(include_inactive=True).get(str(advert_id), {})
    existing_note = ""
    if existing:
        existing_note = f"<div class='notice warning'>Bu ilan zaten servise bağlı: {html.escape(str(existing.get('panel')))} / {html.escape(str(existing.get('service_id')))} / {html.escape(str(existing.get('quantity')))}</div>"
    body = f"""
    <div class='card'><h2>{html.escape(name)}</h2><div class='muted'>İlan ID: <code>{html.escape(str(advert_id))}</code></div>{existing_note}</div>
    <div class='card'><h2>Direkt Servis Bağla</h2><form class='grid' method='post' action='/admin/bind-service/save'>
      <input type='hidden' name='advert_id' value='{html.escape(str(advert_id))}'>
      <select name='panel'>{build_panel_select_options(panel_key)}</select>
      <input name='service_id' placeholder='Panel Servis ID' pattern='^\\d+$' required>
      <input type='number' name='quantity' value='{quantity}' min='1' max='1000000' required>
      <select name='platform'>{build_platform_options(platform)}</select>
      <button class='green'>Kaydet</button>
    </form></div>
    <div class='card'><h2>Servis Ara ve Tek Tıkla Bağla</h2><form class='grid' method='get'>
      <input type='hidden' name='advert_id' value='{html.escape(str(advert_id))}'>
      <select name='panel'>{build_panel_select_options(panel_key)}</select>
      <input name='q' value='{html.escape(q)}' placeholder='Örn: instagram türk takipçi'>
      <input type='number' name='quantity' value='{quantity}' min='1' max='1000000'>
      <select name='platform'>{build_platform_options(platform)}</select>
      <button>Ara</button>
    </form></div>
    <div class='card'><table class='table'><thead><tr><th>Panel</th><th>ID</th><th>Servis</th><th>Kategori</th><th>Fiyat</th><th>Maliyet</th><th>Min/Max</th><th>İşlem</th></tr></thead><tbody>{rows or '<tr><td>Arama yap veya sonuç yok.</td></tr>'}</tbody></table></div>
    """
    return simple_admin_page("İlanı Servise Bağla", body)


@app.get("/admin/bind-service/save")
def admin_bind_service_save_get(
    advert_id: str = "",
    panel: str = "",
    service_id: str = "",
    quantity: int = 0,
    platform: str = "instagram",
    user: str = Depends(get_current_admin),
):
    """GET ile tek tık bağlama gelirse 405 yerine güvenli POST onay sayfası gösterir."""
    advert_id = str(advert_id or "").strip()
    panel = str(panel or "").strip()
    service_id = str(service_id or "").strip()
    platform = str(platform or "instagram").strip() or "instagram"
    if advert_id and panel and service_id and int(quantity or 0) > 0:
        return build_admin_post_confirm_page(
            "İlan Servise Bağlama Onayı",
            f"İlan {advert_id}, {panel} panelindeki {service_id} servisine {int(quantity or 0)} adet olarak bağlansın mı?",
            "/admin/bind-service/save",
            {"advert_id": advert_id, "panel": panel, "service_id": service_id, "quantity": int(quantity or 0), "platform": platform},
            "/admin/adverts-bind?status=missing",
        )
    log("warning", "advert_bind_service_get_missing_fields", advert_id=advert_id, panel=panel, service_id=service_id, quantity=quantity)
    return RedirectResponse("/admin/adverts-bind?status=missing", status_code=303)


@app.post("/admin/bind-service/save")
def admin_bind_service_save(advert_id: str = Form(...), panel: str = Form(...), service_id: str = Form(...), quantity: int = Form(...), platform: str = Form("other"), user: str = Depends(get_current_admin)):
    try:
        set_dynamic_service(advert_id, panel, service_id, quantity, platform, True)
        advert = get_itemsatis_advert_record(advert_id)
        panel_service_name = fetch_panel_service_name_by_id(panel, service_id)
        if panel_service_name:
            cache_panel_service_name(panel, service_id, panel_service_name)
        prime_service_price_cache(panel, service_id, str(advert.get("name") or f"Itemsatış ilanı {advert_id}"))
        log("success", "advert_bound_to_service", advert_id=advert_id, panel=panel, service_id=service_id, quantity=quantity)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/admin/adverts-bind?status=missing", status_code=303)


@app.get("/admin/bind-package", response_class=HTMLResponse)
def admin_bind_package_page(advert_id: str, panel: str = "", q: str = "", quantity: int = 0, platform: str = "", component_name: str = "", user: str = Depends(get_current_admin)):
    advert = get_itemsatis_advert_record(advert_id)
    name = str(advert.get("name") or f"Paket {advert_id}")
    infer = infer_advert_binding_fields(name)
    platform = normalize_text(platform or infer.get("platform") or "tiktok") or "tiktok"
    quantity = int(quantity or infer.get("quantity") or 1000)
    q = str(q or infer.get("search_query") or "")
    panel_key = normalize_panel_key(panel or "medyabayim")
    package = get_package_configs(include_inactive=True).get(str(advert_id), {})
    if not component_name:
        component_name = "Paket Bileşeni"
    comp_rows = []
    for comp in (package or {}).get("components", []) or []:
        comp_rows.append(f"<tr><td data-label='Bileşen'>{html.escape(str(comp.get('name','')))}</td><td data-label='Panel'>{html.escape(str(comp.get('panel','')))}</td><td data-label='Servis ID'><code>{html.escape(str(comp.get('service_id','')))}</code></td><td data-label='Adet'>{html.escape(str(comp.get('quantity','')))}</td><td data-label='Platform'>{html.escape(str(comp.get('platform','')))}</td></tr>")
    result = search_panel_services(panel_key, q, 80) if q else {"items": []}
    search_rows = service_search_rows_for_binding(result.get("items", []), advert_id, quantity, platform, "package", component_name)
    body = f"""
    <div class='card'><h2>{html.escape(name)}</h2><div class='muted'>İlan ID: <code>{html.escape(str(advert_id))}</code></div><div class='notice'>Paket yoksa ilk bileşen eklerken otomatik oluşturulur.</div></div>
    <div class='card'><h2>Paket Oluştur / Güncelle</h2><form class='grid' method='post' action='/admin/bind-package/save'>
      <input type='hidden' name='advert_id' value='{html.escape(str(advert_id))}'>
      <input name='name' value='{html.escape(str((package or {}).get('name') or name))}' placeholder='Paket adı'>
      <select name='platform'>{build_platform_options(platform)}</select>
      <button class='green'>Paketi Kaydet / Aktif Et</button>
    </form></div>
    <div class='card'><h2>Mevcut Bileşenler</h2><table class='table'><thead><tr><th>Bileşen</th><th>Panel</th><th>Servis ID</th><th>Adet</th><th>Platform</th></tr></thead><tbody>{''.join(comp_rows) or '<tr><td>Henüz bileşen yok.</td></tr>'}</tbody></table></div>
    <div class='card'><h2>Direkt Bileşen Ekle</h2><form class='grid' method='post' action='/admin/bind-package/add-component'>
      <input type='hidden' name='advert_id' value='{html.escape(str(advert_id))}'>
      <input name='component_name' value='{html.escape(component_name)}' placeholder='Bileşen adı örn: İzlenme'>
      <select name='panel'>{build_panel_select_options(panel_key)}</select>
      <input name='service_id' placeholder='Panel Servis ID' pattern='^\\d+$' required>
      <input type='number' name='quantity' value='{quantity}' min='1' max='1000000' required>
      <select name='platform'>{build_platform_options(platform)}</select>
      <button class='green'>Bileşen Ekle</button>
    </form></div>
    <div class='card'><h2>Servis Ara ve Bileşen Olarak Ekle</h2><form class='grid' method='get'>
      <input type='hidden' name='advert_id' value='{html.escape(str(advert_id))}'>
      <select name='panel'>{build_panel_select_options(panel_key)}</select>
      <input name='q' value='{html.escape(q)}' placeholder='Örn: tiktok izlenme'>
      <input name='component_name' value='{html.escape(component_name)}' placeholder='Bileşen adı'>
      <input type='number' name='quantity' value='{quantity}' min='1' max='1000000'>
      <select name='platform'>{build_platform_options(platform)}</select>
      <button>Ara</button>
    </form></div>
    <div class='card'><table class='table'><thead><tr><th>Panel</th><th>ID</th><th>Servis</th><th>Kategori</th><th>Fiyat</th><th>Maliyet</th><th>Min/Max</th><th>İşlem</th></tr></thead><tbody>{search_rows or '<tr><td>Arama yap veya sonuç yok.</td></tr>'}</tbody></table></div>
    """
    return simple_admin_page("İlanı Pakete Bağla", body)


@app.post("/admin/bind-package/save")
def admin_bind_package_save(advert_id: str = Form(...), name: str = Form(""), platform: str = Form("tiktok"), user: str = Depends(get_current_admin)):
    try:
        advert = get_itemsatis_advert_record(advert_id)
        set_package(advert_id, name or str(advert.get("name") or f"Paket {advert_id}"), platform, True)
        log("success", "advert_package_saved", advert_id=advert_id, platform=platform)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/admin/bind-package?advert_id={advert_id}", status_code=303)


@app.post("/admin/bind-package/add-component")
def admin_bind_package_add_component(advert_id: str = Form(...), component_name: str = Form("Paket Bileşeni"), panel: str = Form(...), service_id: str = Form(...), quantity: int = Form(...), platform: str = Form("tiktok"), user: str = Depends(get_current_admin)):
    try:
        advert = get_itemsatis_advert_record(advert_id)
        if str(advert_id) not in PACKAGE_CONFIGS:
            set_package(advert_id, str(advert.get("name") or f"Paket {advert_id}"), platform, True)
        comp = add_package_component(advert_id, component_name, panel, service_id, quantity, platform)
        panel_service_name = fetch_panel_service_name_by_id(panel, service_id)
        if panel_service_name:
            cache_panel_service_name(panel, service_id, panel_service_name)
        prime_service_price_cache(panel, service_id, f"Paket: {str(advert.get('name') or advert_id)} / {component_name}")
        log("success", "advert_package_component_added", advert_id=advert_id, panel=panel, service_id=service_id, component=comp.get("name"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/admin/bind-package?advert_id={advert_id}", status_code=303)


@app.get("/admin/favorites", response_class=HTMLResponse)
def admin_favorites(user: str = Depends(get_current_admin)):
    rows = "".join([
        f"<tr><td data-label='Ad'>{v.get('name')}</td><td data-label='Panel'>{get_panel_config(v.get('panel')).get('name')}</td><td data-label='Servis ID'>{v.get('service_id')}</td><td data-label='Adet'>{v.get('quantity')}</td><td data-label='Platform'>{v.get('platform')}</td><td data-label='İşlem'><form method='post' action='/admin/favorites/delete'><input type='hidden' name='favorite_key' value='{k}'><button class='red'>Sil</button></form></td></tr>"
        for k,v in sorted(FAVORITE_SERVICES.items())
    ])
    body = f"""
    <div class='card'><div class='muted'>Sık kullandığın panel servislerini burada tut. Manuel sipariş ekranında bu bilgilerle hızlı işlem yapabilirsin.</div>
    <form class='grid' method='post' action='/admin/favorites/add'><select name='panel'>{''.join([f'<option value="{k}">{v.get("name",k)} ({k})</option>' for k,v in PANEL_MAP.items()])}</select><input name='service_id' placeholder='Servis ID' required><input name='name' placeholder='Favori adı'><input type='number' name='quantity' value='1000'><select name='platform'><option>tiktok</option><option>instagram</option><option>youtube</option><option>x</option><option>twitch</option><option>kick</option><option>other</option></select><button class='green'>Favori Ekle</button></form></div>
    <div class='card'><table class='table'><thead><tr><th>Ad</th><th>Panel</th><th>Servis ID</th><th>Adet</th><th>Platform</th><th>İşlem</th></tr></thead><tbody>{rows or '<tr><td>Favori yok.</td></tr>'}</tbody></table></div>
    """
    return simple_admin_page("Servis Favorileri", body)


@app.post("/admin/favorites/add")
def admin_favorites_add(panel: str = Form(...), service_id: str = Form(...), name: str = Form(""), quantity: int = Form(1000), platform: str = Form("other"), user: str = Depends(get_current_admin)):
    add_favorite_service(panel, service_id, name, platform, quantity)
    return RedirectResponse("/admin/favorites", status_code=303)


@app.post("/admin/favorites/delete")
def admin_favorites_delete(favorite_key: str = Form(...), user: str = Depends(get_current_admin)):
    delete_favorite_service(favorite_key)
    return RedirectResponse("/admin/favorites", status_code=303)


@app.get("/admin/package-test", response_class=HTMLResponse)
def admin_package_test(advert_id: str = "", link: str = "", user: str = Depends(get_current_admin)):
    packages = get_package_configs(include_inactive=True)
    options = "".join([f"<option value='{aid}' {'selected' if aid==advert_id else ''}>{pkg.get('name') or aid} - {aid}</option>" for aid,pkg in packages.items()])
    result_html = ""
    if advert_id and advert_id in packages:
        pkg = packages[advert_id]
        detected_link, detected_platform = find_package_order_link({"post_datas": {"Link": link}, "raw": link}, pkg)
        rows = []
        for comp in pkg.get("components", []) or []:
            comp = normalize_package_component(comp)
            service = get_service_config(comp)
            comp_link = normalize_panel_link(detected_link, service.get("platform", detected_platform)) if detected_link else ""
            status = "Hazır" if detected_link and service.get("api_url") and service.get("api_key") else "Eksik"
            rows.append(f"<tr><td data-label='Bileşen'>{comp.get('name')}</td><td data-label='Panel'>{service.get('panel')}</td><td data-label='Servis ID'>{service.get('service_id')}</td><td data-label='Adet'>{service.get('quantity')}</td><td data-label='Link'>{comp_link or 'Link yok/geçersiz'}</td><td data-label='Durum'><span class='pill'>{status}</span></td></tr>")
        result_html = f"<div class='card'><h2>Test Sonucu</h2><div class='muted'>Paket panele gönderilmedi. Sadece simülasyon yapıldı.</div><p>Yakalanan link: <b>{detected_link or 'Bulunamadı'}</b> · Platform: {detected_platform or '-'}</p><table class='table'><thead><tr><th>Bileşen</th><th>Panel</th><th>Servis ID</th><th>Adet</th><th>Link</th><th>Durum</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    body = f"""
    <div class='card'><div class='muted'>Gerçek sipariş açmadan paket bileşenlerini ve link yakalamayı test eder.</div><form class='grid' method='get'><select name='advert_id'>{options}</select><input name='link' value='{link}' placeholder='Test linki'><button>Paketi Test Et</button></form></div>{result_html}
    """
    return simple_admin_page("Paket Test", body)


@app.get("/admin/profit-calculator", response_class=HTMLResponse)
def admin_profit_calculator(sale: float = 0, cost: float = 0, user: str = Depends(get_current_admin)):
    result = calculate_profit(sale, cost)
    body = f"""
    <div class='card'><form class='grid' method='get'><input type='number' step='0.01' name='sale' value='{sale}' placeholder='Satış TL'><input type='number' step='0.01' name='cost' value='{cost}' placeholder='Panel maliyeti TL'><button>Hesapla</button></form></div>
    <div class='card'><h2>Sonuç</h2><p>Brüt satış: <b>{format_tl_amount(result['sale_price'])}</b></p><p>Itemsatış komisyonu: <b>{format_tl_amount(result['commission'])}</b></p><p>Panel maliyeti: <b>{format_tl_amount(result['panel_cost'])}</b></p><p>Net kâr: <b>{format_tl_amount(result['profit'])}</b> · Marj: <b>%{result['margin_pct']}</b></p></div>
    """
    return simple_admin_page("Kâr Hesaplayıcı", body)


@app.get("/admin/balance-history", response_class=HTMLResponse)
def admin_balance_history(user: str = Depends(get_current_admin)):
    rows = []
    for day, panels in sorted(BALANCE_HISTORY.items(), reverse=True):
        for key, item in sorted((panels or {}).items()):
            rows.append(f"<tr><td data-label='Tarih'>{day}</td><td data-label='Panel'>{item.get('panel_name', key)}</td><td data-label='Bakiye'>{format_tl_amount(item.get('balance_tl',0))}</td><td data-label='Güncelleme'>{item.get('updated_at','')}</td></tr>")
    body = f"<div class='card'><div class='muted'>/balance, /balance-all veya panel health çalıştıkça bakiye geçmişi dolar.</div><table class='table'><thead><tr><th>Tarih</th><th>Panel</th><th>Bakiye</th><th>Güncelleme</th></tr></thead><tbody>{''.join(rows[:200]) or '<tr><td>Kayıt yok.</td></tr>'}</tbody></table></div>"
    return simple_admin_page("Panel Bakiye Geçmişi", body)


@app.get("/admin/link-audit", response_class=HTMLResponse)
def admin_link_audit(user: str = Depends(get_current_admin)):
    rows = "".join([f"<tr><td data-label='Saat'>{x.get('ts')}</td><td data-label='Sipariş'>{x.get('order_id')}</td><td data-label='Ürün'>{x.get('product_name')}</td><td data-label='Platform'>{x.get('platform')}</td><td data-label='Link'>{x.get('link')}</td><td data-label='Durum'>{x.get('status')}</td><td data-label='Not'>{x.get('note')}</td></tr>" for x in reversed(LINK_AUDIT_HISTORY[-200:])])
    body = f"<div class='card'><div class='muted'>Botun siparişte hangi linki yakaladığını gösterir. Yanlış CDN/görsel link olaylarını burada takip edebilirsin.</div><table class='table'><thead><tr><th>Saat</th><th>Sipariş</th><th>Ürün</th><th>Platform</th><th>Link</th><th>Durum</th><th>Not</th></tr></thead><tbody>{rows or '<tr><td>Kayıt yok.</td></tr>'}</tbody></table></div>"
    return simple_admin_page("Link Yakalama Geçmişi", body)


@app.get("/admin/failed-actions", response_class=HTMLResponse)
def admin_failed_actions(user: str = Depends(get_current_admin)):
    rows = "".join([f"<tr><td data-label='Ürün'>{o.get('product_name')}</td><td data-label='Sipariş'>{o.get('order_id')}</td><td data-label='SMM'>{o.get('smm_order_id','-')}</td><td data-label='Panel'>{o.get('panel','-')}</td><td data-label='Sebep'>{o.get('reason')}</td><td data-label='Link'>{o.get('link','')}</td><td data-label='İşlem'><form method='post' action='/admin/failed/mark-completed'><input type='hidden' name='smm_order_id' value='{o.get('smm_order_id','')}'><input type='hidden' name='order_id' value='{o.get('order_id','')}'><button class='green' type='submit'>Tamamlandı İşaretle</button></form><form method='post' action='/admin/failed/blacklist-link'><input type='hidden' name='link' value=\"{str(o.get('link','')).replace(chr(34),'&quot;')}\"><button class='red'>Linki Blacklist</button></form></td></tr>" for o in reversed(FAILED_ORDERS[-50:])])
    body = f"<div class='card'><div class='muted'>Başarısız siparişler için hızlı çözüm merkezi.</div><table class='table'><thead><tr><th>Ürün</th><th>Sipariş</th><th>SMM</th><th>Panel</th><th>Sebep</th><th>Link</th><th>İşlem</th></tr></thead><tbody>{rows or '<tr><td>Başarısız sipariş yok.</td></tr>'}</tbody></table></div>"
    return simple_admin_page("Hatalı Sipariş Çözüm Merkezi", body)


@app.post("/admin/failed/blacklist-link")
def admin_failed_blacklist_link(link: str = Form(...), user: str = Depends(get_current_admin)):
    if link:
        blacklist_add(link)
    return RedirectResponse("/admin/failed-actions", status_code=303)


@app.post("/admin/failed/mark-completed")
def admin_failed_mark_completed(
    smm_order_id: str = Form(""),
    order_id: str = Form(""),
    user: str = Depends(get_current_admin),
):
    """Hata merkezindeki siparişi manuel tamamlandı sayar, geçmişe taşır ve failed listesinden kaldırır."""
    target_smm_id = str(smm_order_id or "").strip()
    target_order_id = str(order_id or "").strip()
    removed = False
    for index, item in enumerate(list(FAILED_ORDERS)):
        item_smm_id = str(item.get("smm_order_id", "")).strip()
        item_order_id = str(item.get("order_id", "")).strip()
        matches_smm = bool(target_smm_id) and item_smm_id == target_smm_id
        matches_order = bool(target_order_id) and item_order_id == target_order_id
        if matches_smm or matches_order:
            item["manual_completed"] = True
            item["manual_completed_at"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
            add_order_history(
                item.get("order_id", "Bilinmiyor"),
                item.get("advert_id", ""),
                item.get("product_name", "Bilinmeyen Ürün"),
                item.get("panel", ""),
                item.get("smm_order_id", ""),
                item.get("link", ""),
                item.get("price", 0),
            )
            try:
                FAILED_ORDERS.pop(index)
            except Exception:
                pass
            removed = True
            save_state()
            send_telegram(
                f"Sipariş manuel tamamlandı işaretlendi.\n\n"
                f"Itemsatış ID: {item.get('order_id', '-') }\n"
                f"SMM ID: {item.get('smm_order_id', '-') }\n"
                f"Ürün: {item.get('product_name', '-')}"
            )
            break
    if not removed:
        log("warning", "manual_completed_failed_not_found", smm_order_id=target_smm_id, order_id=target_order_id)
    return RedirectResponse("/admin/failed-actions", status_code=303)


@app.get("/health")
def health():
    try:
        redis_ok = bool(build_redis_health().get("ok")) if "build_redis_health" in globals() else bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)
    except Exception:
        redis_ok = False
    return {
        "ok": True,
        "status": "running",
        "time_tr": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "redis_ok": redis_ok,
        "pending": len(PENDING_ORDERS),
        "failed": len(FAILED_ORDERS),
        "queue": {
            "waiting": redis_llen(ITEMSATIS_WEBHOOK_QUEUE_KEY),
            "processing": redis_llen(ITEMSATIS_WEBHOOK_PROCESSING_KEY),
            "dead": redis_llen(ITEMSATIS_WEBHOOK_DEAD_KEY),
        },
    }


@app.head("/health")
def health_head():
    return {"ok": True}

@app.get("/test")
def test_message():
    return {"ok": True}


@app.head("/test")
def test_head():
    return {"ok": True}


@app.get("/my-ip")
def my_ip(user: str = Depends(get_current_admin)):
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=30)
        return r.json()
    except Exception as e:
        log("error", "my_ip_lookup_failed", error=str(e))
        return {"ok": False, "error": str(e)}


@app.head("/check-orders")
def check_orders_head():
    return {"ok": True, "status": "alive", "endpoint": "check-orders"}


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
            update_panel_stats(item.get("panel_key") or runtime_service.get("panel_key") or item.get("panel", ""), "partial" if status == "partial" else "failed")
            increment_link_fail_count(item.get("link", ""))
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
            delay_threshold_seconds = get_delay_alert_threshold_seconds(item)
            if waited_seconds >= delay_threshold_seconds:
                log("warning", "order_delayed", smm_order_id=item.get("smm_order_id"), waited_minutes=waited_seconds//60)
                send_telegram(
                    f"Sipariş gecikti.\n\nÜrün: {item.get('product_name', 'Bilinmiyor')}\nPanel: {item.get('panel', 'Bilinmiyor')}\n"
                    f"Itemsatış ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\nSMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
                    f"Link: {item.get('link', '')}\n\n"
                    f"Geçen süre: {format_duration_minutes(waited_seconds / 60)}\n"
                    f"Beklenen ortalama: {format_duration_minutes(item.get('avg_completion_minutes', 0))}\n"
                    f"Paneli kontrol et."
                )
                item["delay_alert_sent"] = True
                changed = True

        if status in COMPLETED_PANEL_STATUSES:
            log("success", "order_completed", smm_order_id=item.get("smm_order_id"), product=item.get("product_name"))
            duration_minutes = int((time.time() - int(item.get("created_at", time.time()) or time.time())) / 60)
            update_panel_stats(item.get("panel_key") or runtime_service.get("panel_key") or item.get("panel", ""), "success", duration_minutes)
            update_service_completion_stats(
                item.get("panel_key") or runtime_service.get("panel_key") or item.get("panel", ""),
                item.get("service_id") or runtime_service.get("service_id", ""),
                duration_minutes,
            )
            send_telegram(
                f"SMM siparişi tamamlandı.\n\nÜrün: {item.get('product_name', 'Bilinmiyor')}\nPanel: {item.get('panel', 'Bilinmiyor')}\n"
                f"Itemsatış ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\nSMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\nLink: {item.get('link', '')}\n\n"
                f"Tamamlanma süresi: {format_duration_minutes(duration_minutes)}\n"
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
                duration_minutes,
                item.get("avg_completion_minutes", ""),
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
    return {"ok": True, "status": "alive", "endpoint": "daily-report"}


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
    return {"ok": True, "status": "alive", "endpoint": "weekly-report"}


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
    return {"ok": True, "status": "alive", "endpoint": "monthly-report"}


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


def get_price_check_targets(include_inactive: bool = False):
    """Normal servisler + paket bileşenleri için fiyat/servis varlık kontrol hedefleri.
    Aynı panel:service_id birden fazla yerde kullanılıyorsa tek kez kontrol eder,
    fakat tüm kullanım yerlerini context içinde birleştirir.
    """
    targets_by_key = {}

    def add_target(service: dict, context: str, advert_id: str = ""):
        if not service or not service.get("service_id"):
            return
        key = f'{service.get("panel_key")}:{service.get("service_id")}'
        if key not in targets_by_key:
            item = dict(service)
            item["contexts"] = []
            item["advert_ids"] = []
            targets_by_key[key] = item
        if context and context not in targets_by_key[key]["contexts"]:
            targets_by_key[key]["contexts"].append(context)
        if advert_id and str(advert_id) not in targets_by_key[key]["advert_ids"]:
            targets_by_key[key]["advert_ids"].append(str(advert_id))
        targets_by_key[key]["context"] = " | ".join(targets_by_key[key]["contexts"])
        targets_by_key[key]["advert_id"] = ",".join(targets_by_key[key]["advert_ids"])

    for advert_id, raw_service in get_all_services(include_inactive=include_inactive).items():
        service = get_service_config(raw_service)
        add_target(service, f"Itemsatış ilanı {advert_id}", str(advert_id))

    for advert_id, package in get_package_configs(include_inactive=include_inactive).items():
        package_name = str(package.get("name") or f"Paket {advert_id}")
        for comp in package.get("components", []) or []:
            comp = normalize_package_component(comp)
            if not comp.get("active", True):
                continue
            service = get_service_config({
                "panel": comp.get("panel"),
                "service_id": comp.get("service_id"),
                "quantity": comp.get("quantity"),
                "platform": comp.get("platform"),
            })
            add_target(service, f"Paket: {package_name} / {comp.get('name')}", str(advert_id))

    return list(targets_by_key.values())


def normalize_panel_rate(value) -> str:
    """Panel rate alanını karşılaştırma için normalize eder.
    12,82 / 12.82 / '12.8200' gibi değerleri aynı kabul eder.
    """
    try:
        text = str(value or "").strip()
        if not text:
            return ""
        text = text.replace("₺", "").replace("TL", "").replace("TRY", "").replace("$", "").replace("USD", "")
        text = text.replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        text = re.sub(r"[^0-9.]", "", text)
        if not text:
            return ""
        return f"{float(text):.6f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value or "").strip()


def prime_service_price_cache(panel_key: str, service_id: str, context: str = "") -> dict:
    """Yeni eklenen normal/paket servis için fiyat takip başlangıç değerini cache'e alır.
    Eğer aynı servis daha önce izleniyorsa ve rate farklıysa anında uyarı gönderir.
    """
    global SERVICE_PRICE_CACHE
    panel_key = normalize_panel_key(panel_key)
    service_id = str(service_id or "").strip()
    if not panel_key or not service_id:
        return {"ok": False, "error": "panel_key_or_service_id_missing"}
    panel = get_panel_config(panel_key)
    if not panel.get("api_url") or not panel.get("api_key"):
        return {"ok": False, "error": "panel_config_missing"}

    services_data = get_panel_services(panel["api_url"], panel["api_key"], panel.get("name", panel_key))
    if isinstance(services_data, dict) and "error" in services_data:
        return {"ok": False, "error": services_data.get("error")}
    if not isinstance(services_data, list):
        return {"ok": False, "error": "services_response_not_list"}

    target_service = None
    for item in services_data:
        if isinstance(item, dict) and str(item.get("service")) == service_id:
            target_service = item
            break
    if not target_service:
        missing_key = f"missing:{panel_key}:{service_id}"
        if not SERVICE_PRICE_CACHE.get(missing_key):
            send_telegram(
                f"Servis panelde bulunamadı.\n\n"
                f"Panel: {panel.get('name', panel_key)}\n"
                f"Servis ID: {service_id}\n"
                f"Kullanım: {context or 'Yeni eklenen servis'}\n\n"
                f"Bu servis ID panelde silinmiş/pasif olabilir."
            )
            SERVICE_PRICE_CACHE[missing_key] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
            save_state()
        return {"ok": False, "error": "service_not_found"}

    service_name = get_panel_service_display_name({"panel_key": panel_key, "panel": panel.get("name"), "service_id": service_id}, target_service)
    current_rate_raw = str(target_service.get("rate", ""))
    current_rate = normalize_panel_rate(current_rate_raw)
    cache_key = f"{panel_key}:{service_id}"
    old_rate = SERVICE_PRICE_CACHE.get(cache_key)
    old_norm = normalize_panel_rate(old_rate)

    if old_rate is not None and old_norm and current_rate and old_norm != current_rate:
        send_telegram(
            f"Servis fiyatı değişti.\n\n"
            f"Panel Servisi: {service_name}\n"
            f"Panel: {panel.get('name', panel_key)}\n"
            f"Servis ID: {service_id}\n"
            f"Kullanım: {context or 'Yeni eklenen servis'}\n"
            f"Eski: {format_panel_rate_tl(panel_key, old_rate)} → Yeni: {format_panel_rate_tl(panel_key, current_rate_raw)}\n"
            f"Not: Fiyatlar TL olarak gösterilmiştir.\n\n"
            f"Bu servis ID'sini kullanan ilanı veya paketi kontrol et."
        )

    SERVICE_PRICE_CACHE[cache_key] = current_rate_raw
    SERVICE_PRICE_CACHE.pop(f"missing:{cache_key}", None)
    save_state()
    return {"ok": True, "rate": current_rate_raw, "service_name": service_name}


@app.head("/check-services")
def check_services_head():
    return {"ok": True, "status": "alive", "endpoint": "check-services"}


@app.get("/check-services")
def check_services():
    global SERVICE_PRICE_CACHE
    changed_count = 0
    missing_count = 0

    for service in get_price_check_targets(include_inactive=False):
        if not service.get("api_url") or not service.get("api_key"):
            log("warning", "service_panel_missing", advert_id=service.get("advert_id"), panel=service.get("panel_key"))
            continue

        services_data = get_panel_services(service["api_url"], service["api_key"], service.get("panel", ""))
        if isinstance(services_data, dict) and "error" in services_data:
            continue

        target_service = None
        for item in services_data if isinstance(services_data, list) else []:
            if str(item.get("service")) == str(service["service_id"]):
                target_service = item
                break

        cache_key = f'{service["panel_key"]}:{service["service_id"]}'
        missing_key = f"missing:{cache_key}"

        if not target_service:
            # Servis panelden silindiyse ya da ID artık listede yoksa bir kez uyar.
            # Yeni eklenen paket bileşenlerinde cache daha önce yoksa bile uyarı verir.
            if not SERVICE_PRICE_CACHE.get(missing_key):
                panel_service_name = get_panel_service_display_name(service)
                log("warning", "service_missing_from_panel", panel=service["panel"], service_id=service["service_id"], context=service.get("context"))
                send_telegram(
                    f"Servis panelde bulunamadı.\n\n"
                    f"Panel Servisi: {panel_service_name}\n"
                    f"Panel: {service['panel']}\n"
                    f"Servis ID: {service['service_id']}\n"
                    f"Kullanım: {service.get('context', 'Bilinmiyor')}\n\n"
                    f"Bu servis silinmiş/pasif olmuş olabilir. İlan veya paket bileşenini kontrol et."
                )
                SERVICE_PRICE_CACHE[missing_key] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
                missing_count += 1
            continue

        SERVICE_PRICE_CACHE.pop(missing_key, None)
        panel_service_name = get_panel_service_display_name(service, target_service)
        current_rate = str(target_service.get("rate", ""))
        old_rate = SERVICE_PRICE_CACHE.get(cache_key)
        current_rate_norm = normalize_panel_rate(current_rate)
        old_rate_norm = normalize_panel_rate(old_rate)

        if old_rate is None:
            SERVICE_PRICE_CACHE[cache_key] = current_rate
            save_state()
            continue

        if old_rate_norm != current_rate_norm:
            log("warning", "service_price_changed", panel=service["panel"], service_id=service["service_id"],
                service_name=panel_service_name, old=old_rate, new=current_rate, context=service.get("context"))
            send_telegram(
                f"Servis fiyatı değişti.\n\n"
                f"Panel Servisi: {panel_service_name}\n"
                f"Panel: {service['panel']}\n"
                f"Servis ID: {service['service_id']}\n"
                f"Kullanım: {service.get('context', 'Bilinmiyor')}\n"
                f"Eski: {format_panel_rate_tl(service.get('panel_key', service.get('panel', '')), old_rate)} → Yeni: {format_panel_rate_tl(service.get('panel_key', service.get('panel', '')), current_rate)}\n"
                f"Not: Fiyatlar TL olarak gösterilmiştir.\n\n"
                f"Bu servis ID'sini kullanan Itemsatış ilanlarını veya paketleri kontrol et."
            )
            SERVICE_PRICE_CACHE[cache_key] = current_rate
            changed_count += 1

    if changed_count or missing_count:
        save_state()
    return {"ok": True, "changed_count": changed_count, "missing_count": missing_count}


def process_itemsatis_webhook_payload(data: dict):
    """Eski Itemsatış webhook işleme mantığı. Worker tarafından thread içinde çağrılır."""
    if not is_itemsatis_purchase_event(data):
        event = get_event(data)
        log("info", "itemsatis_non_order_webhook_ignored", event=event, order_id=get_order_id(data), advert_id=get_advert_id(data))
        return {"ok": True, "ignored": True, "reason": "non_order_webhook", "event": event}

    QUEUE_CONTEXT.active = True
    try:
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

        sale_recorded = record_itemsatis_sale(data=data, order_id=order_id, advert_id=advert_id, buyer=buyer,
                              product_name=report_product_name, price=price)
        if sale_recorded:
            record_buyer_stats(buyer, price)
            # record_itemsatis_sale bu sürümde Redis'e yazmaz; buyer stats ile birlikte tek save yeterlidir.
            save_state()

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
            customer_link, detected_link_platform = find_package_order_link(data, package)

            if not customer_link:
                record_link_audit(order_id, advert_id, package_name, package_platform, "", "blocked", "Paket linki bulunamadı")
                add_failed_order(order_id, advert_id, package_name, "Paket sipariş linki bulunamadı")
                notify_customer_order_failed(order_id, package_name)
                send_telegram(
                    f"Paket sipariş linki bulunamadı.\n\nSipariş ID: {order_id}\nPaket: {package_name}\nPlatform: {package_platform}\nMüşteri: {buyer}\n\n"
                    f"Bot hiçbir panel siparişi açmadı. Itemsatış müşteri bilgi alanında gerçek sosyal medya linki olduğundan emin ol."
                )
                return {"ok": False, "error": "package_link_not_found"}

            log("info", "package_customer_link_detected", advert_id=advert_id, platform=detected_link_platform, link=customer_link)
            record_link_audit(order_id, advert_id, package_name, detected_link_platform or package_platform, customer_link, "ok", "Paket linki yakalandı")


            if is_blacklisted(customer_link) or is_blacklisted(buyer):
                add_failed_order(order_id, advert_id, package_name, "Blacklist engeli", customer_link, link=customer_link)
                send_telegram(f"Blacklisted paket sipariş engellendi.\n\nSipariş ID: {order_id}\nMüşteri: {buyer}\nLink: {customer_link}")
                return {"ok": False, "error": "blacklisted"}

            normalized_link = normalize_link_for_check(customer_link, detected_link_platform or package_platform)
            duplicate_link_key = f"package:{advert_id}:{normalized_link}"
            order_key = make_order_key(order_id, advert_id, buyer, customer_link, detected_link_platform or package_platform)

            if order_key in PROCESSED_ORDERS:
                return {"ignored": True, "reason": "duplicate_package_order"}
            if duplicate_link_key in PROCESSED_LINKS:
                return {"ignored": True, "reason": "duplicate_package_link"}

            success_rows = []
            failed_rows = []
            components = package.get("components", []) or []

            guard_services = []
            for guard_component in components:
                guard_component = normalize_package_component(guard_component)
                if guard_component.get("active", True):
                    guard_services.append(get_service_config(guard_component))
            anti_loss = check_anti_loss_guardrail_for_services(guard_services, price, f"Paket: {package_name}")
            if not anti_loss.get("ok"):
                add_failed_order(order_id, advert_id, package_name, "Zararına satış engellendi", json.dumps(anti_loss, ensure_ascii=False)[:500], link=customer_link, panel="package", retryable=False)
                send_telegram(format_anti_loss_message("Dikkat: Zararına paket satış engellendi.", package_name, order_id, anti_loss))
                return {"ok": False, "error": "anti_loss_guardrail", "type": "package_order", "guard": anti_loss}

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

                component_link = normalize_panel_link(customer_link, service.get("platform", detected_link_platform or package_platform))
                balance_data = panel_balance(service["api_url"], service["api_key"], service.get("panel", ""))
                if "error" in balance_data:
                    error_text = f"Bakiye alınamadı: {balance_data.get('error')}"
                    failed_rows.append((component_name, service.get("panel", "Panel"), error_text))
                    add_failed_order(order_id, advert_id, component_label, "Paket panel bakiyesi alınamadı", error_text, link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""), retryable=True)
                    continue
                balance = balance_data.get("balance", "")
                currency = balance_data.get("currency", "")
                check_low_balance(balance, currency, service.get("panel", ""), service.get("panel_key", ""))
                estimated_cost = estimate_order_cost_from_service(service)
                current_balance_tl = convert_balance_to_try(balance, currency)
                if current_balance_tl is not None and estimated_cost is not None and current_balance_tl < estimated_cost:
                    error_text = f"Panel bakiyesi yetersiz. Bakiye: {format_tl_amount(current_balance_tl)}, tahmini maliyet: {format_tl_amount(estimated_cost)}"
                    failed_rows.append((component_name, service.get("panel", "Panel"), error_text))
                    add_failed_order(order_id, advert_id, component_label, "Paket panel bakiyesi yetersiz", error_text, link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""), retryable=True)
                    continue
                smm_result = create_panel_order(
                    service["api_url"],
                    service["api_key"],
                    service["service_id"],
                    component_link,
                    service["quantity"],
                    service.get("panel", ""),
                )

                if "error" in smm_result:
                    error_text = str(smm_result.get("error") or smm_result)
                    failed_rows.append((component_name, service.get("panel", "Panel"), error_text))
                    add_failed_order(order_id, advert_id, component_label, "Paket panel sipariş hatası", error_text, link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""))
                    continue

                smm_order_id = get_smm_order_id_from_result(smm_result)
                if not smm_order_id:
                    error_text = f"Panel order ID dönmedi. Cevap: {str(smm_result)[:300]}"
                    failed_rows.append((component_name, service.get("panel", "Panel"), error_text))
                    add_failed_order(order_id, advert_id, component_label, "Panel order ID eksik", error_text, link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""), retryable=False)
                    continue

                add_pending_order(
                    order_id,
                    advert_id,
                    component_label,
                    service["panel"],
                    service["api_url"],
                    service["api_key"],
                    smm_order_id,
                    component_link,
                    service_id=service.get("service_id", ""),
                    quantity=service.get("quantity", ""),
                    platform=service.get("platform", ""),
                    panel_key=service.get("panel_key", ""),
                    price=0,
                )
                completion_text = build_completion_estimate_text(service.get("panel_key", ""), service.get("service_id", ""), service.get("panel", ""))
                success_rows.append((component_name, service.get("panel", "Panel"), smm_order_id, completion_text))

            if success_rows:
                PROCESSED_LINKS.add(duplicate_link_key)
                PROCESSED_ORDERS.add(order_key)
                save_state()
                notify_customer_order_started(order_id, package_name, customer_link)

            success_text = "\n".join([f"✅ {name} | {panel} | SMM ID: {smm_id} | {completion_text}" for name, panel, smm_id, completion_text in success_rows]) or "Yok"
            failed_text = "\n".join([f"❌ {name} | {panel} | {err}" for name, panel, err in failed_rows]) or "Yok"
            package_cost = estimate_package_cost_tl(components)
            send_telegram(
                f"Paket sipariş işlendi.\n\nPaket: {package_name}\nItemsatış ID: {order_id}\nLink: {customer_link}\n\n"
                f"Başarılı:\n{success_text}\n\nHatalı:\n{failed_text}\n\n"
                f"{build_finance_summary(price, package_cost)}\n\n"
                f"{build_buyer_summary(buyer)}\n\n"
                f"{build_order_growth_tip(package_platform, package_name)}"
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
                record_link_audit(order_id, advert_id, service_name, platform, "", "blocked", "Sipariş linki bulunamadı")
                add_failed_order(order_id, advert_id, service_name, "Sipariş linki bulunamadı")
                notify_customer_order_failed(order_id, service_name)
                send_telegram(f"Sipariş linki bulunamadı.\n\nSipariş ID: {order_id}\nÜrün: {service_name}\nPlatform: {platform or 'belirsiz'}\nMüşteri: {buyer}")
                return {"ok": False, "error": "order_link_not_found"}

            record_link_audit(order_id, advert_id, service_name, platform, customer_link, "ok", "Servis linki yakalandı")

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

            anti_loss = check_anti_loss_guardrail_for_services([service], price, f"Itemsatış ilanı {advert_id}")
            if not anti_loss.get("ok"):
                add_failed_order(order_id, advert_id, service_name, "Zararına satış engellendi", json.dumps(anti_loss, ensure_ascii=False)[:500], link=customer_link, panel=service.get("panel", ""), retryable=False)
                send_telegram(format_anti_loss_message("Dikkat: Zararına satış engellendi.", service_name, order_id, anti_loss))
                return {"ok": False, "error": "anti_loss_guardrail", "guard": anti_loss}

            balance_data = panel_balance(service["api_url"], service["api_key"], service.get("panel", ""))

            if "error" in balance_data:
                add_failed_order(order_id, advert_id, service_name, "Panel bakiyesi alınamadı", balance_data.get("error"))
                notify_customer_order_failed(order_id, service_name)
                send_telegram(f"Panel bakiyesi alınamadı.\n\nSipariş ID: {order_id}\nHata: {balance_data.get('error')}")
                return {"ok": False, "error": "balance_failed"}

            balance = balance_data.get("balance", "Bilinmiyor")
            currency = balance_data.get("currency", "")
            check_low_balance(balance, currency, service["panel"])
            estimated_cost = estimate_order_cost_from_service(service)
            current_balance_tl = convert_balance_to_try(balance, currency)
            if current_balance_tl is not None and estimated_cost is not None and current_balance_tl < estimated_cost:
                detail = f"Bakiye: {format_tl_amount(current_balance_tl)}, tahmini maliyet: {format_tl_amount(estimated_cost)}"
                add_failed_order(order_id, advert_id, service_name, "Panel bakiyesi yetersiz", detail, link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""), retryable=True)
                notify_customer_order_failed(order_id, service_name)
                send_telegram(
                    f"Panel bakiyesi yetersiz olduğu için sipariş panele gönderilmedi.\n\n"
                    f"Sipariş ID: {order_id}\nÜrün: {service_name}\nPanel: {service.get('panel', '')}\n{detail}"
                )
                return {"ok": False, "error": "insufficient_panel_balance"}

            smm_result = create_panel_order(service["api_url"], service["api_key"],
                                            service["service_id"], customer_link, service["quantity"], service.get("panel", ""))

            if "error" in smm_result:
                add_failed_order(order_id, advert_id, service_name, "Panel sipariş hatası", smm_result.get("error"))
                notify_customer_order_failed(order_id, service_name)
                send_telegram(f"Panel siparişi başarısız.\n\nSipariş ID: {order_id}\nHata: {smm_result.get('error')}")
                return {"ok": False, "error": "panel_order_error"}

            smm_order_id = get_smm_order_id_from_result(smm_result)
            if not smm_order_id:
                add_failed_order(order_id, advert_id, service_name, "Panel order ID eksik", str(smm_result)[:500], link=customer_link, panel=service.get("panel", ""), service_id=service.get("service_id", ""), retryable=False)
                notify_customer_order_failed(order_id, service_name)
                send_telegram(
                    f"Panel siparişi belirsiz cevap verdi.\n\n"
                    f"Sipariş ID: {order_id}\nÜrün: {service_name}\nPanel: {service.get('panel', '')}\n"
                    f"Panel order ID dönmediği için bot pending'e eklemedi. Panelden manuel kontrol gerekli."
                )
                return {"ok": False, "error": "panel_order_id_missing", "manual_check_required": True}

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

            estimated_cost = estimate_order_cost_from_service(service)
            current_balance_tl = convert_balance_to_try(balance, currency)
            after_balance_text = ""
            if current_balance_tl is not None and estimated_cost is not None:
                after_balance_text = f"\nTahmini sipariş sonrası bakiye: {format_tl_amount(current_balance_tl - estimated_cost)}"
            completion_estimate_text = build_completion_estimate_text(service.get("panel_key", ""), service.get("service_id", ""), service.get("panel", ""))

            send_telegram(
                f"SMM siparişi panele girildi.\n\nÜrün: {service_name}\nPanel: {service['panel']}\n"
                f"Itemsatış ID: {order_id}\nSMM ID: {smm_order_id}\nLink: {customer_link}\n"
                f"Adet: {service['quantity']}\n{completion_estimate_text}\nBakiye: {format_tl_amount(current_balance_tl or 0)}{after_balance_text}\n\n"
                f"{build_finance_summary(price, estimated_cost)}\n\n"
                f"{build_buyer_summary(buyer)}\n\n"
                f"{build_order_growth_tip(platform, service_name)}"
            )

            return {"ok": True, "type": "smm_order", "smm_order_id": smm_order_id}

        log("info", "webhook_unmatched", advert_id=advert_id, product=product_name)
        return {"ignored": True, "product": product_name, "advert_id": advert_id}

    finally:
        QUEUE_CONTEXT.active = False


@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    """Itemsatış webhook'u hızlıca alır ve Redis kuyruğuna yazar."""
    if not is_webhook_authorized(request):
        log("warning", "webhook_unauthorized", ip=get_request_ip(request))
        raise HTTPException(status_code=401, detail="Unauthorized webhook")
    try:
        data = await request.json()
    except Exception:
        body = await request.body()
        data = {"raw_body": body.decode("utf-8", errors="ignore")}
    log("info", "webhook_received_queued", raw=str(data)[:200])
    event = get_event(data)

    # Itemsatış sohbet/mesaj/bildirim webhooklarını kuyruğa bile alma.
    # Örn: listing_chat_started sipariş değildir.
    if not is_itemsatis_purchase_event(data):
        log("info", "webhook_ignored_before_queue", event=event, advert_id=get_advert_id(data), order_id=get_order_id(data), reason="non_order_webhook")
        return {"ok": True, "ignored": True, "event": event, "reason": "non_order_webhook"}

    ignored_events = {"review_received", "review_created", "message_created", "question_created", "advert_updated"}
    if event in ignored_events:
        log("info", "webhook_ignored_before_queue", event=event)
        return {"ok": True, "ignored": True, "event": event}
    order_id = get_order_id(data)
    seen_key = ""
    seen_locked = False
    if order_id and str(order_id) != "Bilinmiyor":
        seen_key = f"itemsatis:webhook_seen:{order_id}"
        seen = redis_set_raw(seen_key, "1", ex=86400, nx=True)
        if isinstance(seen, dict) and seen.get("result") is None:
            log("warning", "webhook_duplicate_seen_before_queue", order_id=order_id)
            return {"ok": True, "status": "already_queued", "order_id": order_id}
        if not redis_set_succeeded(seen):
            log("error", "webhook_duplicate_lock_failed", order_id=order_id, redis_result=str(seen)[:300])
            raise HTTPException(status_code=503, detail="Redis duplicate lock failed")
        seen_locked = True
    try:
        queue_id = enqueue_itemsatis_webhook(data)
    except Exception as e:
        if seen_locked and seen_key:
            redis_delete_key(seen_key)
        log("error", "webhook_queue_failed", order_id=order_id, error=str(e))
        raise HTTPException(status_code=503, detail="Webhook queue write failed")
    return {"ok": True, "status": "queued", "queue_id": queue_id}


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
            "/check-balances - Bakiye alarm check-up\n"
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
            "/panel-stats - Panel başarı oranları\n"
            "/growth-report - Kâr ve satış fırsat raporu\n"
            "/note smm_id not - Sipariş notu ekle\n"
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

    if command in ["/check-balances", "/balance-check"]:
        result = check_all_panel_balances(force_alert=True)
        lines = ["Bakiye check-up tamamlandı:\n"]
        for key, item in (result.get("panels") or {}).items():
            if item.get("ok"):
                alert_text = " | Uyarı gönderildi" if item.get("alerted") else ""
                lines.append(f"{key}: {item.get('balance')}{alert_text}")
            else:
                lines.append(f"{key}: Hata - {item.get('error')}")
        send_telegram("\n".join(lines))
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


    if command == "/panel-stats":
        if not PANEL_STATS:
            send_telegram("Panel istatistiği henüz yok.")
            return {"ok": True}
        lines = ["Panel Başarı Raporu:\n"]
        for key, item in PANEL_STATS.items():
            success = int(item.get("success", 0) or 0)
            failed = int(item.get("failed", 0) or 0)
            partial = int(item.get("partial", 0) or 0)
            total = success + failed + partial
            rate = (success / total * 100) if total else 0
            avg = 0
            if int(item.get("completed_count", 0) or 0) > 0:
                avg = int(item.get("completed_total_minutes", 0) or 0) / int(item.get("completed_count", 1) or 1)
            panel_name = get_panel_config(key).get("name", key)
            lines.append(f"{panel_name}: %{rate:.1f} başarı | Başarılı {success} | Hata {failed} | Partial {partial} | Ortalama {avg:.0f} dk")
        send_telegram("\n".join(lines))
        return {"ok": True}

    if command in ["/growth-report", "/profit-report"]:
        send_telegram(build_growth_report_text())
        return {"ok": True}

    if command == "/note":
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            send_telegram("Kullanım: /note smm_id not metni")
            return {"ok": True}
        add_order_note(parts[1], parts[2])
        send_telegram(f"Not kaydedildi.\nSMM ID: {parts[1]}")
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
