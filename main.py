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
WEBHOOK_IP_WHITELIST = [ip.strip() for ip in os.getenv("WEBHOOK_IP_WHITELIST", "").split(",") if ip.strip()]
STATE_LOCK = threading.RLock()
TR_TIMEZONE = timezone(timedelta(hours=3))


ITEMSATIS_COMMISSION_RATE = 0.07

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
    "oldsmm": {
        "name": os.getenv("OldSmm", "Panel 3"),
        "api_url": os.getenv("OLDSMM_API_URL", ""),
        "api_key": os.getenv("OLDSMM_API_KEY", ""),
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
    "oldsmm": "oldsmm",
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
SERVICE_PRICE_CACHE = {}
PANEL_SERVICE_NAME_CACHE = {}

# ─── YENİ: LOG GEÇMİŞİ (son 200 log dashboard için) ───────────────────────────
MAX_LOG_HISTORY = 200
LOG_HISTORY = deque(maxlen=MAX_LOG_HISTORY)
_RATE_LIMIT_STORE = defaultdict(list)
MESSAGE_TEMPLATES = {}
BALANCE_WARN_LAST = {}
LOG_FLUSH_INTERVAL_SECONDS = int(os.getenv("LOG_FLUSH_INTERVAL_SECONDS", "30"))
DASHBOARD_REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "45"))
API_LOG_LIMIT = int(os.getenv("API_LOG_LIMIT", "40"))

_LOG_DIRTY = False
_LOG_LAST_FLUSH = 0

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}

FAILED_PANEL_STATUSES = {"cancelled", "canceled", "partial", "fail", "failed", "refunded"}
COMPLETED_PANEL_STATUSES = {
    "completed", "complete", "completed successfully", "success", "successful",
    "finished", "done", "tamamlandı", "tamamlandi", "başarılı", "basarili",
}
SLOW_API_THRESHOLD_SECONDS = float(os.getenv("SLOW_API_THRESHOLD_SECONDS", "8"))
PANEL_API_LOG_NORMAL = os.getenv("PANEL_API_LOG_NORMAL", "false").lower() == "true"
MIN_PENDING_STATUS_CHECK_DELAY_SECONDS = int(os.getenv("MIN_PENDING_STATUS_CHECK_DELAY_SECONDS", "180"))
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
PROFIT_TARGET_MARGIN_PERCENT = float(os.getenv("PROFIT_TARGET_MARGIN_PERCENT", "30"))
PROFIT_MIN_TL = float(os.getenv("PROFIT_MIN_TL", "2"))
_BULK_RETRY_LOCK = threading.Lock()
_BACKGROUND_TASKS = {}
_ADMIN_BACKGROUND_JOBS = {}
_ADMIN_BACKGROUND_LOCK = threading.Lock()
_LAST_UNBOUND_WEBHOOK = {}
_UNBOUND_ADVERT_ALERT_LAST = {}
UNBOUND_ADVERT_ALERT_COOLDOWN_SECONDS = int(os.getenv("UNBOUND_ADVERT_ALERT_COOLDOWN_SECONDS", "900"))
PROCESSED_ORDERS_MAX = int(os.getenv("PROCESSED_ORDERS_MAX", "1000"))
PROCESSED_LINKS_MAX = int(os.getenv("PROCESSED_LINKS_MAX", "1000"))
STATE_LAST_HASH = ""
STATE_LAST_SAVE_FAIL_LOG = 0
CACHE_STATE_LAST_HASH = ""
CACHE_STATE_LAST_SAVE_FAIL_LOG = 0
CACHE_STATE_DIRTY = False
# Panel fiyat cache timestampleri Redis'e yazılmaz; sadece RAM'de throttle amaçlı tutulur.
SERVICE_RATE_CHECK_TIMES = {}
DASHBOARD_OPS_CACHE_SECONDS = int(os.getenv("DASHBOARD_OPS_CACHE_SECONDS", "10"))
_DASHBOARD_OPS_CACHE = {"ts": 0.0, "data": None}
ITEMSATIS_LOCAL_ADVERTS_CACHE_SECONDS = int(os.getenv("ITEMSATIS_LOCAL_ADVERTS_CACHE_SECONDS", "30"))
_ITEMSATIS_LOCAL_ADVERTS_CACHE = {"ts": 0.0, "key": "", "rows": None}
REDIS_ERROR_BACKOFF_SECONDS = int(os.getenv("REDIS_ERROR_BACKOFF_SECONDS", "60"))
_REDIS_BACKOFF_UNTIL = 0
_REDIS_BACKOFF_REASON = ""
_REDIS_LAST_ERROR_LOG = 0

# ─── PROFESYONEL PANEL DAYANIKLILIĞI: CIRCUIT BREAKER + REDIS QUEUE ──────────
CIRCUIT_THRESHOLD = int(os.getenv("CIRCUIT_THRESHOLD", "3"))
CIRCUIT_RECOVERY_SEC = int(os.getenv("CIRCUIT_RECOVERY_SEC", "600"))

ITEMSATIS_WEBHOOK_QUEUE_KEY = os.getenv("ITEMSATIS_WEBHOOK_QUEUE_KEY", "queue:itemsatis:webhooks")
ITEMSATIS_WEBHOOK_PROCESSING_KEY = os.getenv("ITEMSATIS_WEBHOOK_PROCESSING_KEY", "queue:itemsatis:processing")
ITEMSATIS_WEBHOOK_DEAD_KEY = os.getenv("ITEMSATIS_WEBHOOK_DEAD_KEY", "queue:itemsatis:dead")

QUEUE_ITEM_MAX_ATTEMPTS = int(os.getenv("QUEUE_ITEM_MAX_ATTEMPTS", "5"))
QUEUE_WORKER_SLEEP_SEC = float(os.getenv("QUEUE_WORKER_SLEEP_SEC", "2"))
# Kuyruk boşken Redis RPOPLPUSH polling'i kademeli yavaşlatılır.
# Sipariş geldiğinde worker tekrar minimum bekleme süresine döner.
QUEUE_WORKER_EMPTY_MAX_SLEEP_SEC = float(os.getenv("QUEUE_WORKER_EMPTY_MAX_SLEEP_SEC", "15"))
QUEUE_STATUS_CACHE_SECONDS = int(os.getenv("QUEUE_STATUS_CACHE_SECONDS", "10"))
_QUEUE_STATUS_CACHE = {"ts": 0.0, "data": None}
QUEUE_RETRY_DELAY_SEC = int(os.getenv("QUEUE_RETRY_DELAY_SEC", "120"))
QUEUE_CIRCUIT_RETRY_DELAY_SEC = int(os.getenv("QUEUE_CIRCUIT_RETRY_DELAY_SEC", "600"))
QUEUE_STUCK_RECOVERY_SEC = int(os.getenv("QUEUE_STUCK_RECOVERY_SEC", "600"))

QUEUE_CONTEXT = threading.local()

# V39 safe-current-patch: ağır periyodik kontroller varsayılan kapalı.
# Queue worker ayrı tutulur ve açık kalır; manuel endpoint/butonlar çalışmaya devam eder.
ENABLE_BACKGROUND_CHECKS = os.getenv("ENABLE_BACKGROUND_CHECKS", "false").lower() == "true"
# Pending siparişlerin tamamlanmasını yakalamak için sadece status polling açık kalır.
# Ağır servis/bakiye kontrolleri ENABLE_BACKGROUND_CHECKS arkasında kalmaya devam eder.
ORDER_STATUS_CHECKS_ENABLED = os.getenv("ORDER_STATUS_CHECKS_ENABLED", "true").lower() == "true"
PENDING_AGE_ALERT_SECONDS = int(os.getenv("PENDING_AGE_ALERT_SECONDS", "7200"))
PENDING_AGE_ALERT_REPEAT_SECONDS = int(os.getenv("PENDING_AGE_ALERT_REPEAT_SECONDS", "21600"))


def run_admin_background_job(job_key: str, target, *args, **kwargs) -> dict:
    """Admin butonlarındaki ağır işleri HTTP isteğini bekletmeden arka planda çalıştırır."""
    job_key = str(job_key or "admin_background_job")
    with _ADMIN_BACKGROUND_LOCK:
        item = _ADMIN_BACKGROUND_JOBS.get(job_key, {})
        thread = item.get("thread") if isinstance(item, dict) else None
        if thread and getattr(thread, "is_alive", lambda: False)():
            return {"ok": True, "started": False, "already_running": True, "job": job_key}
        _ADMIN_BACKGROUND_JOBS[job_key] = {
            "status": "running",
            "started_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": "",
            "error": "",
            "result": None,
        }

    def _runner():
        try:
            result = target(*args, **kwargs)
            with _ADMIN_BACKGROUND_LOCK:
                _ADMIN_BACKGROUND_JOBS[job_key].update({
                    "status": "done",
                    "finished_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
                    "result": result,
                })
            log("info", "admin_background_job_done", job=job_key, result=str(result)[:300])
        except Exception as e:
            with _ADMIN_BACKGROUND_LOCK:
                _ADMIN_BACKGROUND_JOBS[job_key].update({
                    "status": "error",
                    "finished_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": str(e)[:500],
                })
            log("error", "admin_background_job_error", job=job_key, error=str(e))

    thread = threading.Thread(target=_runner, daemon=True)
    with _ADMIN_BACKGROUND_LOCK:
        _ADMIN_BACKGROUND_JOBS[job_key]["thread"] = thread
    thread.start()
    return {"ok": True, "started": True, "already_running": False, "job": job_key}


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
    """Webhook güvenliği: opsiyonel IP whitelist + basit rate limit."""
    client_ip = get_request_ip(request)

    if WEBHOOK_IP_WHITELIST and client_ip not in WEBHOOK_IP_WHITELIST:
        log("warning", "webhook_ip_blocked", ip=client_ip)
        return False

    if not check_rate_limit(client_ip, limit=120, window=60):
        log("warning", "webhook_rate_limited", ip=client_ip)
        return False

    return True


def now_tr():
    return datetime.now(TR_TIMEZONE)


def invalidate_dashboard_ops_cache():
    """Dashboard operasyon cache'ini temizler; pending/failed değişince admin panel hızlı güncellenir."""
    global _DASHBOARD_OPS_CACHE
    try:
        _DASHBOARD_OPS_CACHE = {"ts": 0.0, "data": None}
    except Exception:
        pass


def invalidate_itemsatis_local_adverts_cache():
    """Admin ilan listesinin kısa RAM cache'ini temizler."""
    global _ITEMSATIS_LOCAL_ADVERTS_CACHE
    try:
        _ITEMSATIS_LOCAL_ADVERTS_CACHE = {"ts": 0.0, "key": "", "rows": None}
    except Exception:
        pass


def invalidate_queue_status_cache():
    """Queue/circuit status cache'ini temizler. Redis'e yazmaz; sadece RAM cache sıfırlar."""
    global _QUEUE_STATUS_CACHE
    try:
        _QUEUE_STATUS_CACHE = {"ts": 0.0, "data": None}
    except Exception:
        pass


# ─── YENİ: GELİŞMİŞ LOGLAMA ──────────────────────────────────────────────────
def flush_logs(force: bool = False):
    """Log geçmişini Redis'e kontrollü yazar; her logda Redis yazıp yavaşlatmaz."""
    global _LOG_DIRTY
    _LOG_DIRTY = False
    return


def log(level: str, event_name: str, **kwargs):
    """Hem structlog ile JSON log yazar hem de dashboard için hafızada tutar.
    
    Not: kwargs içinde 'event' gelirse structlog/fallback logger ile çakışmaması için
    detail_event alanına taşınır. Bu, non-order webhook gibi kayıtların 500 hatası
    üretmesini engeller.
    """
    global _LOG_DIRTY
    if "event" in kwargs:
        kwargs = dict(kwargs)
        kwargs["detail_event"] = kwargs.pop("event")

    entry = {
        "ts": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "event": event_name,
        **kwargs,
    }

    log_fn = getattr(logger, level if level != "success" else "info", logger.info)
    log_fn(event_name, **kwargs)

    with STATE_LOCK:
        LOG_HISTORY.append(entry)
        _LOG_DIRTY = True


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
def is_redis_quota_error_text(text: str) -> bool:
    text = str(text or "").lower()
    return (
        "max requests limit exceeded" in text
        or "max monthly" in text
        or "quota exceeded" in text
        or "usage limit" in text
        or "request limit" in text
    )


def redis_request(command):
    global _REDIS_BACKOFF_UNTIL, _REDIS_BACKOFF_REASON, _REDIS_LAST_ERROR_LOG
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None

    now_ts = time.time()
    if _REDIS_BACKOFF_UNTIL and now_ts < _REDIS_BACKOFF_UNTIL:
        if now_ts - _REDIS_LAST_ERROR_LOG >= 60:
            _REDIS_LAST_ERROR_LOG = now_ts
            logger.error(
                "redis_backoff_active",
                reason=_REDIS_BACKOFF_REASON,
                retry_after_seconds=int(_REDIS_BACKOFF_UNTIL - now_ts),
            )
        return None

    try:
        r = requests.post(
            UPSTASH_REDIS_REST_URL,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            json=command,
            timeout=20,
        )
        if r.status_code >= 400:
            response_text = r.text[:300]
            if is_redis_quota_error_text(response_text):
                _REDIS_BACKOFF_UNTIL = time.time() + max(1, REDIS_ERROR_BACKOFF_SECONDS)
                _REDIS_BACKOFF_REASON = response_text
                _REDIS_LAST_ERROR_LOG = time.time()
                logger.error(
                    "redis_quota_backoff_started",
                    status=r.status_code,
                    retry_after_seconds=REDIS_ERROR_BACKOFF_SECONDS,
                    response=response_text,
                )
            else:
                logger.error("redis_http_error", status=r.status_code, response=response_text)
            return None
        try:
            result = r.json()
        except Exception as e:
            logger.error("redis_json_error", error=str(e), response=r.text[:300])
            return None
        if isinstance(result, dict) and result.get("error"):
            error_text = str(result.get("error"))[:300]
            if is_redis_quota_error_text(error_text):
                _REDIS_BACKOFF_UNTIL = time.time() + max(1, REDIS_ERROR_BACKOFF_SECONDS)
                _REDIS_BACKOFF_REASON = error_text
                _REDIS_LAST_ERROR_LOG = time.time()
                logger.error(
                    "redis_quota_backoff_started",
                    retry_after_seconds=REDIS_ERROR_BACKOFF_SECONDS,
                    error=error_text,
                )
            else:
                logger.error("redis_command_error", error=error_text, command=str(command)[:120])
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
    invalidate_queue_status_cache()
    log("info", "itemsatis_webhook_queued", queue_id=queue_id, attempts=attempts, not_before=not_before)
    return queue_id


def push_itemsatis_queue_item(item: dict, event: str = "itemsatis_queue_requeued") -> bool:
    """Var olan queue item'ını ana kuyruğa güvenli döndürür; Redis yazımı doğrulanmadan başarılı saymaz."""
    safe_item = item if isinstance(item, dict) else {"payload": item}
    result = redis_lpush_json(ITEMSATIS_WEBHOOK_QUEUE_KEY, safe_item)
    if redis_lpush_succeeded(result):
        invalidate_queue_status_cache()
        log("info", event, queue_id=safe_item.get("id"), attempts=safe_item.get("attempts"))
        return True
    log("error", "itemsatis_queue_requeue_failed", queue_id=safe_item.get("id"), queue_event=event, redis_result=str(result)[:300])
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
    invalidate_queue_status_cache()
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
    """Redis tabanlı mini webhook worker. Ekstra paket istemez; siparişleri sırayla işler.
    Kuyruk boşken adaptive sleep kullanır; boş Redis polling'i Upstash limitini zorlamasın.
    """
    log("info", "itemsatis_queue_worker_started")
    recover_stuck_itemsatis_processing()
    last_stuck_recovery = int(time.time())
    min_empty_sleep = max(0.5, float(QUEUE_WORKER_SLEEP_SEC or 2))
    max_empty_sleep = max(min_empty_sleep, float(QUEUE_WORKER_EMPTY_MAX_SLEEP_SEC or 15))
    current_empty_sleep = min_empty_sleep
    while True:
        try:
            now_loop = int(time.time())
            if now_loop - last_stuck_recovery >= max(60, int(QUEUE_STUCK_RECOVERY_SEC / 2)):
                recover_stuck_itemsatis_processing()
                last_stuck_recovery = now_loop
            raw = redis_rpoplpush_raw(ITEMSATIS_WEBHOOK_QUEUE_KEY, ITEMSATIS_WEBHOOK_PROCESSING_KEY)
            if not raw:
                await asyncio.sleep(current_empty_sleep)
                current_empty_sleep = min(max_empty_sleep, max(min_empty_sleep, current_empty_sleep * 2))
                continue

            # İş bulunduğu anda worker tekrar hızlı moda döner.
            current_empty_sleep = min_empty_sleep
            invalidate_queue_status_cache()
            try:
                item = json.loads(raw)
            except Exception as e:
                redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                invalidate_queue_status_cache()
                move_queue_item_to_dead({"raw": str(raw)[:1000]}, f"Queue JSON parse error: {e}")
                continue
            now_ts = int(time.time())
            not_before = int(item.get("not_before", 0) or 0)
            if not_before > now_ts:
                if push_itemsatis_queue_item(item, "itemsatis_not_before_requeued"):
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                    invalidate_queue_status_cache()
                await asyncio.sleep(min(min_empty_sleep + 3, max(1, not_before - now_ts)))
                continue
            item["processing_started_at"] = now_ts
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
            if isinstance(payload, dict) and item.get("id"):
                payload = dict(payload)
                payload["_queue_id"] = item.get("id")
            try:
                result = await asyncio.to_thread(process_itemsatis_webhook_payload, payload)
                redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                invalidate_queue_status_cache()
                log("info", "itemsatis_queue_processed", queue_id=item.get("id"), result=str(result)[:300])
            except CircuitOpenForOrder as e:
                attempts = int(item.get("attempts", 0) or 0) + 1
                item["attempts"] = attempts
                item["not_before"] = int(time.time()) + int(e.retry_after)
                item["last_error"] = str(e)
                if attempts >= QUEUE_ITEM_MAX_ATTEMPTS:
                    move_queue_item_to_dead(item, f"Circuit open max attempts: {e}")
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                    invalidate_queue_status_cache()
                else:
                    if push_itemsatis_queue_item(item, "itemsatis_requeued_circuit_open"):
                        redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                        invalidate_queue_status_cache()
                        log("warning", "itemsatis_requeued_circuit_open", queue_id=item.get("id"), panel=e.panel_name, attempts=attempts)
            except Exception as e:
                attempts = int(item.get("attempts", 0) or 0) + 1
                item["attempts"] = attempts
                item["not_before"] = int(time.time()) + QUEUE_RETRY_DELAY_SEC
                item["last_error"] = str(e)
                if attempts >= QUEUE_ITEM_MAX_ATTEMPTS:
                    move_queue_item_to_dead(item, f"Max attempts: {e}")
                    redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                    invalidate_queue_status_cache()
                    send_telegram_error(
                        f"Itemsatış queue dead'e düştü.\n\n"
                        f"Queue ID: {item.get('id')}\n"
                        f"Deneme: {attempts}\n"
                        f"Hata: {str(e)[:500]}"
                    )
                else:
                    if push_itemsatis_queue_item(item, "itemsatis_requeued_error"):
                        redis_lrem_value(ITEMSATIS_WEBHOOK_PROCESSING_KEY, raw)
                        invalidate_queue_status_cache()
                        log("warning", "itemsatis_requeued_error", queue_id=item.get("id"), attempts=attempts, error=str(e))
        except Exception as e:
            current_empty_sleep = min_empty_sleep
            log("error", "itemsatis_queue_worker_error", error=str(e))
            send_telegram_error(f"Itemsatış queue worker kritik hata:\n{str(e)[:700]}")
            await asyncio.sleep(max(5, min_empty_sleep))


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
    """Itemsatış webhook queue derinliği ve circuit durumlarını döndürür.
    Kısa RAM cache kullanır; admin panel açıkken aynı Redis LLEN/LRANGE/circuit GET çağrıları tekrarlanmaz.
    """
    global _QUEUE_STATUS_CACHE
    now_float = time.time()
    try:
        cached = _QUEUE_STATUS_CACHE.get("data")
        cached_ts = float(_QUEUE_STATUS_CACHE.get("ts", 0) or 0)
        if cached and (now_float - cached_ts) < max(1, int(QUEUE_STATUS_CACHE_SECONDS)):
            data = json.loads(json.dumps(cached, ensure_ascii=False, default=str))
            data["cached"] = True
            data["cache_age_seconds"] = round(now_float - cached_ts, 2)
            return data
    except Exception:
        pass

    circuits = []
    now_ts = int(now_float)

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

    data = {
        "ok": True,
        "cached": False,
        "cache_age_seconds": 0,
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
    try:
        _QUEUE_STATUS_CACHE = {"ts": now_float, "data": data}
    except Exception:
        pass
    return data


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
        invalidate_queue_status_cache()
        log("warning", "dead_queue_requeued_by_admin", queue_id=queue_id, retry_all=retry_all, moved=moved)

    return moved



def sanitize_pending_order(item: dict) -> dict:
    """API cevaplarında ve Redis kayıtlarında panel API key sızmasını engeller; eski kayıtları güvenli defaultlarla tamamlar."""
    if not isinstance(item, dict):
        return {}
    clean = dict(item)
    clean.pop("api_key", None)
    clean["itemsatis_order_id"] = str(clean.get("itemsatis_order_id") or clean.get("order_id") or "Bilinmiyor")
    clean["advert_id"] = str(clean.get("advert_id") or "")
    clean["product_name"] = str(clean.get("product_name") or "Bilinmeyen Ürün")
    clean["panel"] = str(clean.get("panel") or "")
    clean["panel_key"] = normalize_panel_key(clean.get("panel_key") or clean.get("panel") or "")
    clean["service_id"] = str(clean.get("service_id") or "")
    clean["platform"] = str(clean.get("platform") or "other")
    clean["smm_order_id"] = str(clean.get("smm_order_id") or "")
    clean["link"] = str(clean.get("link") or "")
    try:
        clean["created_at"] = int(clean.get("created_at", 0) or 0)
    except Exception:
        clean["created_at"] = 0
    clean["submitted_at"] = str(clean.get("submitted_at") or "")
    try:
        clean["price"] = float(clean.get("price", 0) or 0)
    except Exception:
        clean["price"] = 0.0
    clean["delay_alert_sent"] = bool(clean.get("delay_alert_sent", False))
    clean["cancelled"] = bool(clean.get("cancelled", False))
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

def build_cache_state_payload() -> dict:
    # rate_checked_at:* timestampleri sık değişir; Redis'e yazılırsa cache hash'i sürekli değişir.
    # Bu timestampler SERVICE_RATE_CHECK_TIMES içinde RAM'de tutulur.
    clean_price_cache = {
        str(k): v
        for k, v in (SERVICE_PRICE_CACHE or {}).items()
        if not str(k).startswith("rate_checked_at:")
    }
    return {
        "service_price_cache": clean_price_cache,
        "panel_service_name_cache": PANEL_SERVICE_NAME_CACHE,
    }


def _cache_state_hash() -> str:
    try:
        payload = json.dumps(build_cache_state_payload(), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()
    except Exception:
        return ""


def mark_cache_state_dirty():
    global CACHE_STATE_DIRTY
    CACHE_STATE_DIRTY = True


def save_cache_state(force: bool = False):
    """Fiyat/servis adı cache'lerini kritik state'ten ayrı ve seyrek kaydeder.
    Botun çalışması için kritik olmayan bu cache'ler normal save_state MSET'ini
    büyütmez; sadece gerçekten değiştiğinde aynı Redis key'lerine yazılır.
    """
    global CACHE_STATE_LAST_HASH, CACHE_STATE_LAST_SAVE_FAIL_LOG, CACHE_STATE_DIRTY
    with STATE_LOCK:
        current_hash = _cache_state_hash()
        if not force and not CACHE_STATE_DIRTY and current_hash == CACHE_STATE_LAST_HASH:
            return
        if current_hash and current_hash == CACHE_STATE_LAST_HASH:
            CACHE_STATE_DIRTY = False
            return

        result = redis_mset_json(build_cache_state_payload())
        if result is None:
            now_ts = int(time.time())
            if now_ts - int(CACHE_STATE_LAST_SAVE_FAIL_LOG or 0) >= 60:
                CACHE_STATE_LAST_SAVE_FAIL_LOG = now_ts
                log("warning", "redis_cache_mset_skipped_or_failed")
            return

        if current_hash:
            CACHE_STATE_LAST_HASH = current_hash
        CACHE_STATE_DIRTY = False
        invalidate_dashboard_ops_cache()


def load_state():
    global PROCESSED_ORDERS, PROCESSED_LINKS, FAILED_ORDERS, PENDING_ORDERS
    global SERVICE_PRICE_CACHE, PANEL_SERVICE_NAME_CACHE, DYNAMIC_SERVICES, PACKAGE_CONFIGS, MESSAGE_TEMPLATES, LOW_BALANCE_DISABLED_PANELS
    global CACHE_STATE_LAST_HASH, CACHE_STATE_DIRTY, SERVICE_RATE_CHECK_TIMES

    PROCESSED_ORDERS = set(redis_get_json("processed_orders", []))
    PROCESSED_LINKS = set(redis_get_json("processed_links", []))
    FAILED_ORDERS = [normalize_failed_order(item) for item in redis_get_json("failed_orders", []) if isinstance(item, dict)]
    PENDING_ORDERS = redis_get_json("pending_orders", [])
    sanitize_pending_orders_for_storage()
    SERVICE_PRICE_CACHE = redis_get_json("service_price_cache", {})
    if not isinstance(SERVICE_PRICE_CACHE, dict):
        SERVICE_PRICE_CACHE = {}
    # Eski Redis kayıtlarında kalmış rate_checked_at:* değerlerini RAM throttle alanına taşı.
    SERVICE_RATE_CHECK_TIMES = {}
    for key in list(SERVICE_PRICE_CACHE.keys()):
        key_text = str(key)
        if key_text.startswith("rate_checked_at:"):
            try:
                SERVICE_RATE_CHECK_TIMES[key_text.replace("rate_checked_at:", "", 1)] = int(SERVICE_PRICE_CACHE.get(key) or 0)
            except Exception:
                pass
            SERVICE_PRICE_CACHE.pop(key, None)
    PANEL_SERVICE_NAME_CACHE = redis_get_json("panel_service_name_cache", {})
    DYNAMIC_SERVICES = redis_get_json("dynamic_services", {})
    PACKAGE_CONFIGS = redis_get_json("package_configs", {})
    MESSAGE_TEMPLATES = redis_get_json("message_templates", {})
    LOW_BALANCE_DISABLED_PANELS = set(redis_get_json("low_balance_disabled_panels", list(LOW_BALANCE_DISABLED_PANELS)))
    CACHE_STATE_LAST_HASH = _cache_state_hash()
    CACHE_STATE_DIRTY = False
    trim_processed_memory()

    log("info", "state_loaded", pending=len(PENDING_ORDERS), failed=len(FAILED_ORDERS))


def save_state():
    """Kritik state'i sadece değiştiğinde Redis'e yazar.
    Aynı veri tekrar gelirse MSET atılmaz; bu Upstash request tüketimini azaltır.
    """
    global STATE_LAST_HASH, STATE_LAST_SAVE_FAIL_LOG
    with STATE_LOCK:
        sanitize_pending_orders_for_storage()
        trim_processed_memory()

        data_to_save = {
            "processed_orders": list(PROCESSED_ORDERS),
            "processed_links": list(PROCESSED_LINKS),
            "failed_orders": FAILED_ORDERS,
            "pending_orders": PENDING_ORDERS,
            "dynamic_services": DYNAMIC_SERVICES,
            "package_configs": PACKAGE_CONFIGS,
            "message_templates": MESSAGE_TEMPLATES,
            "low_balance_disabled_panels": sorted(LOW_BALANCE_DISABLED_PANELS),
        }

        try:
            payload = json.dumps(data_to_save, ensure_ascii=False, sort_keys=True, default=str)
            current_hash = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()
        except Exception:
            current_hash = ""

        if current_hash and current_hash == STATE_LAST_HASH:
            return

        result = redis_mset_json(data_to_save)
        if result is None:
            now_ts = int(time.time())
            if now_ts - int(STATE_LAST_SAVE_FAIL_LOG or 0) >= 60:
                STATE_LAST_SAVE_FAIL_LOG = now_ts
                log("warning", "redis_mset_skipped_or_failed")
            return

        if current_hash:
            STATE_LAST_HASH = current_hash
        invalidate_dashboard_ops_cache()
        invalidate_itemsatis_local_adverts_cache()



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


def normalize_tiktok_link(link: str) -> str:
    """TikTok paylaşım linklerini aynı hedef için kanonik hale getirir.

    TikTok aynı profil/video linkine _r, _t, utm vb. geçici query parametreleri
    ekleyebiliyor. Pending aynı-link koruması bu parametreler yüzünden kaçmasın
    diye TikTok linklerinde query ve fragment temizlenir. Kısa vt/vm linkleri
    canlı resolve edilmez; sadece üzerindeki query temizlenir.
    """
    link = str(link or "").strip()
    if not link:
        return ""

    if link.startswith("@"):
        handle = link.split("?", 1)[0].split("#", 1)[0].strip().lstrip("@").strip("/")
        return f"https://www.tiktok.com/@{handle}" if handle else ""

    lower = link.lower()
    if not lower.startswith(("http://", "https://")):
        if "tiktok.com" in lower:
            link = "https://" + link.lstrip("/")
        else:
            return link

    try:
        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").rstrip("/")
        if not host:
            return link.split("?", 1)[0].split("#", 1)[0].rstrip("/")

        canonical_host = host
        if host in {"tiktok.com", "m.tiktok.com", "www.tiktok.com"}:
            canonical_host = "www.tiktok.com"

        # Query/fragment TikTok hedefini değil paylaşım izleme parametrelerini taşır.
        return urlunparse((parsed.scheme or "https", canonical_host, path or "/", "", "", "")).rstrip("/")
    except Exception:
        return link.split("?", 1)[0].split("#", 1)[0].rstrip("/")


def is_tiktok_platform_or_link(link: str = "", platform: str = "") -> bool:
    platform = normalize_text(platform)
    link_text = str(link or "").lower()
    return platform in {"tiktok", "tik_tok", "tt"} or "tiktok.com" in link_text or "vm.tiktok.com" in link_text or "vt.tiktok.com" in link_text


def normalize_panel_link(link: str, platform: str = "") -> str:
    link = str(link or "").strip()
    platform = normalize_text(platform)

    if not link:
        return ""

    if platform == "instagram":
        return normalize_instagram_link(link)

    if is_tiktok_platform_or_link(link, platform):
        return normalize_tiktok_link(link)

    # Diğer platformlarda linki panele aynen gönder.
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


def find_active_pending_by_link(link: str, platform: str = "") -> dict | None:
    normalized = normalize_link_for_check(link, platform)
    if not normalized:
        return None

    for item in PENDING_ORDERS:
        if not isinstance(item, dict) or item.get("cancelled"):
            continue
        item_link = normalize_link_for_check(item.get("link", ""), item.get("platform", platform))
        if item_link and item_link == normalized:
            return item
    return None


def make_order_key(order_id, advert_id, buyer, link="", platform=""):
    """Gerçek Itemsatış order_id varsa kalıcı idempotency anahtarı üretir.

    Eski sürümlerde order_id bilinmiyorsa advert+buyer+link fallback anahtarı üretiliyordu.
    Bu, aynı müşterinin aynı linke ikinci kez satın almasını yanlışlıkla duplicate sayabiliyordu.
    Bu yüzden order_id yoksa zayıf fallback anahtarı artık üretilmez.
    """
    order_text = str(order_id or "").strip()
    if order_text and order_text != "Bilinmiyor":
        return f"order:{order_text}"
    return ""


def make_webhook_payload_fingerprint(data: dict) -> str:
    """Order ID gelmeyen Itemsatış webhookları için exact-payload fingerprint üretir.

    Amaç: aynı webhook tekrar gönderilirse duplicate yakalansın;
    fakat aynı müşteri aynı ilana/linke daha sonra tekrar sipariş verirse engellenmesin.
    Queue runtime alanları fingerprint dışına alınır.
    """
    try:
        safe = dict(data or {}) if isinstance(data, dict) else {"raw": str(data)}
        safe.pop("_queue_id", None)
        safe.pop("processing_started_at", None)
        raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(data)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def build_order_idempotency_keys(order_id, advert_id, buyer, link="", platform="", queue_id="", payload_fingerprint="") -> list[str]:
    """Aynı webhook'un tekrar gelmesi durumunda çift panel siparişini engelleyen uyumlu anahtarlar.

    Önemli: order_id yoksa advert+buyer+link gibi kalıcı fallback kullanılmaz.
    Çünkü aynı müşteri aynı linke tekrar sipariş verebilir. Bu durumda sadece exact payload
    fingerprint duplicate koruması olarak kullanılır.
    """
    keys = []
    order_text = str(order_id or "").strip()
    advert_text = str(advert_id or "").strip()

    base_key = make_order_key(order_text, advert_id, buyer, link, platform)
    if base_key:
        keys.append(base_key)

    if order_text and order_text != "Bilinmiyor":
        keys.append(f"itemsatis_order:{order_text}")
        if advert_text:
            keys.append(f"itemsatis_advert_order:{advert_text}:{order_text}")
    else:
        fingerprint_text = str(payload_fingerprint or "").strip()
        if fingerprint_text:
            keys.append(f"itemsatis_payload:{fingerprint_text}")

    queue_text = str(queue_id or "").strip()
    if queue_text:
        keys.append(f"queue:{queue_text}")
    return list(dict.fromkeys([k for k in keys if k]))


def has_processed_order(keys: list[str]) -> bool:
    return any(key in PROCESSED_ORDERS for key in (keys or []))


def mark_processed_order(keys: list[str]):
    for key in keys or []:
        if key:
            PROCESSED_ORDERS.add(key)
    trim_processed_memory()


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


def is_manual_itemsatis_order_id(order_id: str = "") -> bool:
    return str(order_id or "").strip().lower().startswith("manual-")


def normalize_panel_status_text(value) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    tr_map = str.maketrans({
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    })
    text = text.translate(tr_map)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def extract_panel_status(status_data: dict) -> str:
    """Panel status cevabını toleranslı okur.
    Farklı paneller status değerini root/result/data/order/response veya
    orders[0] gibi farklı seviyelerde döndürebiliyor. Tamamlandı/failed
    kararını sadece güvenilir status/state/order_status alanlarından verir.
    """
    status_keys = (
        "status", "Status",
        "state", "State",
        "order_status", "OrderStatus",
        "orderStatus", "order_state", "orderState",
    )

    def _read_direct(obj):
        if not isinstance(obj, dict):
            return ""
        for key in status_keys:
            value = obj.get(key)
            if value not in [None, ""]:
                normalized = normalize_panel_status_text(value)
                if normalized:
                    return normalized
        return ""

    if not isinstance(status_data, dict):
        return ""

    # Önce root seviyesini kontrol et.
    direct = _read_direct(status_data)
    if direct:
        return direct

    # Sonra sık kullanılan nested cevap formatları.
    for container_key in ("result", "data", "order", "response"):
        nested = status_data.get(container_key)
        if isinstance(nested, dict):
            found = _read_direct(nested)
            if found:
                return found
        elif isinstance(nested, list) and nested:
            for item in nested[:3]:
                found = _read_direct(item)
                if found:
                    return found

    # Bazı paneller orders: [{status: ...}] döndürür.
    orders = status_data.get("orders") or status_data.get("Orders")
    if isinstance(orders, list) and orders:
        for item in orders[:3]:
            found = _read_direct(item)
            if found:
                return found
    elif isinstance(orders, dict):
        found = _read_direct(orders)
        if found:
            return found

    return ""


def is_completed_panel_status(status_data: dict) -> bool:
    status = extract_panel_status(status_data)
    if not status:
        return False
    normalized_completed = {normalize_panel_status_text(v) for v in COMPLETED_PANEL_STATUSES}
    return status in normalized_completed or any(word in status for word in ["completed", "complete", "success", "successful", "finished", "done", "tamamlandi", "basarili"])


def is_failed_panel_status(status_data: dict) -> bool:
    status = extract_panel_status(status_data)
    if not status:
        return False
    normalized_failed = {normalize_panel_status_text(v) for v in FAILED_PANEL_STATUSES}
    return status in normalized_failed or any(word in status for word in ["cancelled", "canceled", "partial", "failed", "fail", "refunded", "refund", "iptal"])


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
    elif sale > 0:
        lines.append("Net kâr: Panel maliyeti bilinmediği için hesaplanamadı")
    return "\n".join(lines)


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
        if _queue_context_active():
            log("warning", "service_cost_cache_missing_in_queue", panel=panel_key, service_id=service_id)
            return None
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
    category = classify_failed_reason(reason, detail)
    retry_policy = classify_failed_retry_policy(category, reason, detail)
    entry = {
        "order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "reason": str(reason),
        "detail": str(detail),
        "category": category,
        "retryable": retry_policy.get("retryable", False),
        "retry_note": retry_policy.get("retry_note", ""),
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


def normalize_failed_order(item: dict) -> dict:
    """Eski/bozuk failed kayıtları admin ve retry akışını bozmasın diye hafifçe tamamlar."""
    item = dict(item or {})
    reason = str(item.get("reason") or "Bilinmeyen hata")
    detail = str(item.get("detail") or "")
    category = item.get("category") or classify_failed_reason(reason, detail)
    retry_policy = classify_failed_retry_policy(category, reason, detail)
    item["order_id"] = str(item.get("order_id") or item.get("itemsatis_order_id") or "Bilinmiyor")
    item["advert_id"] = str(item.get("advert_id") or "")
    item["product_name"] = str(item.get("product_name") or "Bilinmeyen Ürün")
    item["reason"] = reason
    item["detail"] = detail
    item["category"] = category
    if "retryable" not in item:
        item["retryable"] = retry_policy.get("retryable", False)
    if not item.get("retry_note"):
        item["retry_note"] = retry_policy.get("retry_note", "")
    try:
        item["created_at"] = int(item.get("created_at", 0) or int(time.time()))
    except Exception:
        item["created_at"] = int(time.time())
    return item


def sanitize_panel_response(value, limit: int = 700) -> str:
    """Panel cevabını failed_orders içine kısa ve güvenli şekilde yazar."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    text = re.sub(r"(?i)(key|api_key|token|secret|password)['\"]?\s*[:=]\s*['\"]?[^,'\"}\\s]+", r"\1=***", text)
    return text[:max(120, int(limit or 700))]


def is_blocked_customer_asset_link(link: str) -> bool:
    """Itemsatış görsel/CDN linklerinin panele müşteri linki diye gitmesini engeller."""
    value = str(link or "").strip().lower()
    if not value:
        return True
    blocked_markers = [
        "cdn.itemsatis.com",
        "itemsatis.com/uploads",
        "/uploads/",
        "post_images",
        "product_images",
        "listing_images",
        "avatar",
    ]
    if any(marker in value for marker in blocked_markers):
        return True
    return bool(re.search(r"\.(?:jpg|jpeg|png|gif|webp|svg)(?:$|[?#])", value))


def link_matches_platform(link: str, platform: str = "") -> bool:
    """Canlı API çağrısı yapmadan link/platform uyumunu kontrol eder."""
    link_text = str(link or "").strip().lower()
    platform = normalize_text(platform or "")
    if not link_text or platform in ["", "other", "general"]:
        return True
    domains = {
        "instagram": ["instagram.com", "instagr.am"],
        "tiktok": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
        "youtube": ["youtube.com", "youtu.be"],
        "x": ["x.com", "twitter.com"],
        "twitter": ["x.com", "twitter.com"],
        "twitch": ["twitch.tv"],
        "kick": ["kick.com"],
    }.get(platform, [])
    if not domains:
        return True
    return any(domain in link_text for domain in domains)


def validate_service_order_preflight(service: dict, link: str, context: str = "") -> dict:
    """Panel siparişi açılmadan önce sadece lokal veriyle güvenli ön kontrol yapar."""
    service = dict(service or {})
    context = str(context or "Sipariş")
    panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
    service_id = str(service.get("service_id") or "").strip()
    platform = normalize_text(service.get("platform") or "other") or "other"
    try:
        quantity = int(service.get("quantity") or 0)
    except Exception:
        quantity = 0
    normalized_link = normalize_panel_link(link, platform)

    checks = [
        (bool(panel_key), "panel_missing", "Panel eşleşmesi boş."),
        (panel_key in PANEL_MAP, "panel_unknown", f"Panel bulunamadı: {panel_key or '-'}"),
        (bool(service.get("api_url") and service.get("api_key")), "panel_config_missing", "Panel API bilgileri eksik."),
        (bool(service_id), "service_id_missing", "Panel servis ID boş."),
        (service_id.isdigit(), "service_id_invalid", f"Panel servis ID sadece rakam olmalı: {service_id or '-'}"),
        (quantity > 0, "quantity_invalid", f"Adet 0'dan büyük olmalı: {quantity}"),
        (quantity <= 1000000, "quantity_too_high", f"Adet çok yüksek: {quantity}"),
        (bool(normalized_link), "link_missing", "Müşteri linki boş veya normalize edilemedi."),
        (not is_blocked_customer_asset_link(normalized_link), "asset_link_blocked", "Itemsatış görsel/CDN linki müşteri linki olarak engellendi."),
        (link_matches_platform(normalized_link, platform), "platform_link_mismatch", f"Link platform ile uyumlu değil. Platform: {platform}, Link: {normalized_link}"),
    ]
    for ok, code, detail in checks:
        if not ok:
            return {"ok": False, "code": code, "reason": "Sipariş ön kontrol hatası", "detail": f"{context}: {detail}"}
    return {"ok": True, "link": normalized_link, "quantity": quantity, "panel_key": panel_key, "service_id": service_id}


def add_preflight_failed_order(order_id, advert_id, product_name, service: dict, check: dict, link: str = ""):
    service = dict(service or {})
    detail = str((check or {}).get("detail") or (check or {}).get("code") or "Ön kontrol başarısız")
    add_failed_order(
        order_id,
        advert_id,
        product_name,
        "Sipariş ön kontrol hatası",
        detail,
        link=link,
        panel=service.get("panel", ""),
        panel_key=service.get("panel_key", ""),
        service_id=service.get("service_id", ""),
        quantity=service.get("quantity", ""),
        platform=service.get("platform", ""),
        retryable=False,
        reason_code=(check or {}).get("code", "preflight_failed"),
    )


def validate_config_service_binding(service: dict, context: str, advert_id: str = "") -> list:
    """dynamic_services/package_configs kayıtlarını canlı API çağrısı yapmadan kontrol eder."""
    issues = []
    service = get_service_config(service or {})
    panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
    service_id = str(service.get("service_id") or "").strip()
    try:
        quantity = int(service.get("quantity") or 0)
    except Exception:
        quantity = 0

    def add_issue(code: str, detail: str):
        issues.append({
            "code": code,
            "detail": detail,
            "context": str(context or ""),
            "advert_id": str(advert_id or ""),
            "panel": service.get("panel", panel_key),
            "panel_key": panel_key,
            "service_id": service_id,
        })

    if not panel_key:
        add_issue("panel_missing", "Panel boş.")
    elif panel_key not in PANEL_MAP:
        add_issue("panel_unknown", f"Panel bulunamadı: {panel_key}")
    elif not is_panel_configured(panel_key):
        add_issue("panel_config_missing", "Panel API URL/API KEY eksik.")
    if not service_id:
        add_issue("service_id_missing", "Servis ID boş.")
    elif not service_id.isdigit():
        add_issue("service_id_invalid", f"Servis ID rakam değil: {service_id}")
    if quantity <= 0:
        add_issue("quantity_invalid", f"Adet geçersiz: {quantity}")
    elif quantity > 1000000:
        add_issue("quantity_too_high", f"Adet çok yüksek: {quantity}")
    return issues


def build_service_binding_safety_report() -> dict:
    """dynamic_services ve package_configs eşleşmelerini canlı panel çağrısı yapmadan tarar."""
    issues = []
    checked_dynamic = 0
    checked_package_components = 0

    for advert_id, raw_service in get_dynamic_services().items():
        checked_dynamic += 1
        issues.extend(validate_config_service_binding(raw_service, f"dynamic_service:{advert_id}", advert_id))

    for advert_id, package in get_package_configs(include_inactive=True).items():
        package_name = str((package or {}).get("name") or f"Paket {advert_id}")
        active_components = 0
        for component in (package or {}).get("components", []) or []:
            component = normalize_package_component(component)
            if not component.get("active", True):
                continue
            active_components += 1
            checked_package_components += 1
            issues.extend(validate_config_service_binding(component, f"package:{package_name}/{component.get('name')}", advert_id))
        if bool((package or {}).get("active", True)) and active_components == 0:
            issues.append({
                "code": "package_empty",
                "detail": "Aktif pakette aktif bileşen yok.",
                "context": f"package:{package_name}",
                "advert_id": str(advert_id),
                "panel": "",
                "panel_key": "",
                "service_id": "",
            })

    return {
        "ok": not bool(issues),
        "checked_dynamic": checked_dynamic,
        "checked_package_components": checked_package_components,
        "issue_count": len(issues),
        "issues": issues[:30],
    }


def format_service_binding_safety_summary(report: dict) -> str:
    report = report or {}
    if not report.get("issue_count"):
        return (
            "Servis eşleşme güvenlik kontrolü: temiz\n"
            f"Dynamic servis: {report.get('checked_dynamic', 0)} | Paket bileşeni: {report.get('checked_package_components', 0)}"
        )
    lines = [
        "Servis eşleşme güvenlik kontrolü: sorun bulundu",
        f"Dynamic servis: {report.get('checked_dynamic', 0)} | Paket bileşeni: {report.get('checked_package_components', 0)}",
        f"Sorun: {report.get('issue_count', 0)}",
    ]
    for issue in (report.get("issues") or [])[:8]:
        lines.append(f"- {issue.get('context', '-')}: {issue.get('detail', '-')}")
    if int(report.get("issue_count", 0) or 0) > 8:
        lines.append("- Devamı log/admin kaydında.")
    return "\n".join(lines)


def _safe_int_value(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _service_cache_key(panel_key: str, service_id: str) -> str:
    return f"{normalize_panel_key(panel_key)}:{str(service_id or '').strip()}"


def _service_price_cache_exists(panel_key: str, service_id: str) -> bool:
    key = _service_cache_key(panel_key, service_id)
    return key in (SERVICE_PRICE_CACHE or {}) and (SERVICE_PRICE_CACHE or {}).get(key) not in [None, ""]


def _active_config_service_rows() -> list[dict]:
    """Active service configs from local state only; no panel API call."""
    rows = []
    for advert_id, service in (SMM_SERVICE_MAP or {}).items():
        item = dict(service or {})
        item.setdefault("active", True)
        if not item.get("active", True):
            continue
        item["advert_id"] = str(advert_id)
        item["config_type"] = "code_service"
        rows.append(item)

    for advert_id, service in (DYNAMIC_SERVICES or {}).items():
        item = normalize_dynamic_service(str(advert_id), service or {})
        if not item.get("active", True):
            continue
        item["config_type"] = "dynamic_service"
        rows.append(item)

    for advert_id, package in (PACKAGE_CONFIGS or {}).items():
        package = dict(package or {})
        if not package.get("active", True):
            continue
        package_name = str(package.get("name") or f"Package {advert_id}")
        for component in package.get("components", []) or []:
            comp = normalize_package_component(component)
            if not comp.get("active", True):
                continue
            comp["advert_id"] = str(advert_id)
            comp["product_name"] = f"{package_name} / {comp.get('name', 'Component')}"
            comp["config_type"] = "package_component"
            rows.append(comp)
    return rows


def build_config_health_report() -> dict:
    """Local config check for system-check; it does not call live panel APIs."""
    issues = []
    price_cache_missing = []
    name_cache_missing = []
    checked_services = 0
    checked_packages = 0
    checked_components = 0

    for row in _active_config_service_rows():
        checked_services += 1
        if row.get("config_type") == "package_component":
            checked_components += 1
        panel_key = normalize_panel_key(row.get("panel_key") or row.get("panel") or "")
        service_id = str(row.get("service_id") or "").strip()
        quantity = _safe_int_value(row.get("quantity"), 0)
        context = f"{row.get('config_type', 'service')}:{row.get('advert_id', '-')}"

        for issue in validate_config_service_binding(row, context, row.get("advert_id", "")):
            issues.append(issue)

        if panel_key and service_id:
            if not get_cached_panel_service_name(panel_key, service_id):
                name_cache_missing.append({
                    "advert_id": str(row.get("advert_id", "")),
                    "panel_key": panel_key,
                    "service_id": service_id,
                    "context": context,
                })
            if not _service_price_cache_exists(panel_key, service_id):
                price_cache_missing.append({
                    "advert_id": str(row.get("advert_id", "")),
                    "panel_key": panel_key,
                    "service_id": service_id,
                    "context": context,
                })
        if quantity <= 0 or quantity > 1000000:
            issues.append({
                "code": "quantity_out_of_range",
                "detail": f"Quantity out of safe range: {quantity}",
                "context": context,
                "advert_id": str(row.get("advert_id", "")),
                "panel": row.get("panel", ""),
                "panel_key": panel_key,
                "service_id": service_id,
            })

    for advert_id, package in (PACKAGE_CONFIGS or {}).items():
        package = dict(package or {})
        if not package.get("active", True):
            continue
        checked_packages += 1
        active_components = 0
        for component in package.get("components", []) or []:
            comp = normalize_package_component(component)
            if comp.get("active", True):
                active_components += 1
        if active_components == 0:
            issues.append({
                "code": "package_without_active_component",
                "detail": "Active package has no active component.",
                "context": f"package:{package.get('name') or advert_id}",
                "advert_id": str(advert_id),
                "panel": "",
                "panel_key": "",
                "service_id": "",
            })

    return {
        "ok": not bool(issues),
        "checked_services": checked_services,
        "checked_packages": checked_packages,
        "checked_package_components": checked_components,
        "issue_count": len(issues),
        "issues": issues[:50],
        "panel_service_name_cache_missing_count": len(name_cache_missing),
        "panel_service_name_cache_missing": name_cache_missing[:30],
        "price_cache_missing_count": len(price_cache_missing),
        "price_cache_missing": price_cache_missing[:30],
    }


def calculate_service_health_score(panel_key: str, service_id: str, service: dict | None = None) -> dict:
    """Small local-only service score for admin decisions."""
    panel_key = normalize_panel_key(panel_key or (service or {}).get("panel_key") or (service or {}).get("panel") or "")
    service_id = str(service_id or (service or {}).get("service_id") or "").strip()
    score = 100
    notes = []

    if not panel_key or panel_key not in PANEL_MAP:
        score -= 30
        notes.append("panel_missing_or_unknown")
    elif not is_panel_configured(panel_key):
        score -= 25
        notes.append("panel_api_config_missing")

    if not service_id or not service_id.isdigit():
        score -= 30
        notes.append("service_id_invalid")

    if service is not None:
        quantity = _safe_int_value((service or {}).get("quantity"), 0)
        if quantity <= 0 or quantity > 1000000:
            score -= 20
            notes.append("quantity_out_of_range")

    if panel_key and service_id and not _service_price_cache_exists(panel_key, service_id):
        score -= 10
        notes.append("price_cache_missing")

    avg_minutes = 0
    completed_count = 0

    recent_failed = 0
    now_ts = int(time.time())
    for failed in (FAILED_ORDERS or [])[-250:]:
        if normalize_panel_key(failed.get("panel_key") or failed.get("panel") or "") != panel_key:
            continue
        if str(failed.get("service_id") or "").strip() != service_id:
            continue
        created_at = _safe_int_value(failed.get("created_at"), 0)
        if created_at and now_ts - created_at <= 7 * 86400:
            recent_failed += 1
    if recent_failed >= 5:
        score -= 25
        notes.append("many_recent_failed_orders")
    elif recent_failed >= 2:
        score -= 10
        notes.append("recent_failed_orders")

    score = max(0, min(100, int(score)))
    return {
        "panel_key": panel_key,
        "service_id": service_id,
        "score": score,
        "level": "good" if score >= 80 else ("watch" if score >= 55 else "risk"),
        "notes": notes[:8],
        "avg_completion_minutes": avg_minutes,
        "completed_count": completed_count,
        "recent_failed_7d": recent_failed,
    }


def build_service_health_summary(limit: int = 20) -> dict:
    rows = []
    seen = set()
    for service in _active_config_service_rows():
        panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
        service_id = str(service.get("service_id") or "").strip()
        key = (panel_key, service_id, str(service.get("advert_id", "")))
        if key in seen:
            continue
        seen.add(key)
        score = calculate_service_health_score(panel_key, service_id, service)
        score.update({
            "advert_id": str(service.get("advert_id", "")),
            "config_type": service.get("config_type", "service"),
            "product_name": str(service.get("product_name") or service.get("name") or ""),
        })
        rows.append(score)
    rows.sort(key=lambda item: (int(item.get("score", 0)), item.get("advert_id", "")))
    return {
        "checked": len(rows),
        "risk_count": sum(1 for item in rows if item.get("level") == "risk"),
        "watch_count": sum(1 for item in rows if item.get("level") == "watch"),
        "lowest": rows[:max(1, int(limit or 20))],
    }


def pending_age_seconds(item: dict, now_ts: int | None = None) -> int:
    try:
        now_ts = int(now_ts or time.time())
        created_at = int((item or {}).get("created_at", 0) or 0)
        if not created_at:
            return 0
        return max(0, now_ts - created_at)
    except Exception:
        return 0


def is_stale_pending_order(item: dict, now_ts: int | None = None) -> bool:
    if not isinstance(item, dict) or item.get("cancelled"):
        return False
    threshold = max(300, int(PENDING_AGE_ALERT_SECONDS))
    return pending_age_seconds(item, now_ts) >= threshold


def enrich_pending_order_for_display(item: dict, now_ts: int | None = None) -> dict:
    clean = sanitize_pending_order(item)
    now_ts = int(now_ts or time.time())
    age_seconds = pending_age_seconds(clean, now_ts)
    clean["age_seconds"] = age_seconds
    clean["age_minutes"] = int(age_seconds / 60) if age_seconds else 0
    clean["stale"] = is_stale_pending_order(clean, now_ts)
    clean["stale_threshold_seconds"] = max(300, int(PENDING_AGE_ALERT_SECONDS))
    return clean


def build_pending_admin_rows(now_ts: int | None = None) -> list[dict]:
    now_ts = int(now_ts or time.time())
    rows = [enrich_pending_order_for_display(item, now_ts) for item in PENDING_ORDERS if isinstance(item, dict)]
    rows.sort(key=lambda item: (bool(item.get("cancelled")), -int(item.get("age_seconds", 0) or 0)))
    return rows


def find_pending_order_index(smm_order_id: str = "", itemsatis_order_id: str = "") -> int:
    target_smm = str(smm_order_id or "").strip()
    target_itemsatis = str(itemsatis_order_id or "").strip()
    for index, item in enumerate(PENDING_ORDERS):
        if not isinstance(item, dict):
            continue
        if target_smm and str(item.get("smm_order_id", "")).strip() == target_smm:
            return index
        if target_itemsatis and str(item.get("itemsatis_order_id", "")).strip() == target_itemsatis:
            return index
    return -1


def remove_pending_order_by_smm_id(smm_order_id: str, action: str, admin_note: str = "") -> tuple[bool, dict]:
    """Admin onaylı pending temizleme. Panelde işlem yapmaz, yeni sipariş açmaz."""
    target_smm = str(smm_order_id or "").strip()
    if not target_smm:
        return False, {}

    with STATE_LOCK:
        index = find_pending_order_index(smm_order_id=target_smm)
        if index < 0 or index >= len(PENDING_ORDERS):
            return False, {}
        item = dict(PENDING_ORDERS.pop(index) or {})
        item["admin_pending_action"] = str(action or "removed")
        item["admin_pending_action_at"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
        if admin_note:
            item["admin_pending_note"] = str(admin_note)[:300]
        save_state()

    log(
        "warning" if action != "manual_completed" else "success",
        "pending_order_removed_by_admin",
        action=action,
        smm_order_id=target_smm,
        itemsatis_order_id=item.get("itemsatis_order_id", ""),
        product=item.get("product_name", ""),
    )
    return True, item


def build_pending_age_report(now_ts: int | None = None) -> dict:
    now_ts = int(now_ts or time.time())
    threshold = max(300, int(PENDING_AGE_ALERT_SECONDS))
    rows = []
    for item in PENDING_ORDERS or []:
        if not isinstance(item, dict) or item.get("cancelled"):
            continue
        created_at = _safe_int_value(item.get("created_at"), 0)
        if not created_at:
            continue
        age_seconds = max(0, now_ts - created_at)
        if age_seconds >= threshold:
            rows.append({
                "itemsatis_order_id": str(item.get("itemsatis_order_id", "")),
                "smm_order_id": str(item.get("smm_order_id", "")),
                "product_name": str(item.get("product_name", "")),
                "panel": str(item.get("panel", "")),
                "link": str(item.get("link", "")),
                "created_at": created_at,
                "age_seconds": age_seconds,
                "age_minutes": int(age_seconds / 60),
                "stale": True,
                "alert_sent": bool(item.get("delay_alert_sent") or item.get("pending_age_alert_sent_at")),
            })
    rows.sort(key=lambda item: item.get("age_minutes", 0), reverse=True)
    return {
        "threshold_seconds": threshold,
        "old_count": len(rows),
        "delayed_count": len(rows),
        "stale_count": len(rows),
        "oldest": rows[:20],
    }

def build_failed_24h_report() -> dict:
    now_ts = int(time.time())
    rows = []
    categories = defaultdict(int)
    for item in FAILED_ORDERS or []:
        if not isinstance(item, dict):
            continue
        created_at = _safe_int_value(item.get("created_at"), 0)
        if created_at and now_ts - created_at <= 86400:
            rows.append(item)
            categories[str(item.get("category") or classify_failed_reason(item.get("reason", ""), item.get("detail", "")))] += 1
    return {
        "count": len(rows),
        "high": len(rows) >= 10,
        "categories": dict(sorted(categories.items(), key=lambda pair: pair[1], reverse=True)[:10]),
    }


def build_recommended_actions(config_report: dict | None = None, health_report: dict | None = None, pending_report: dict | None = None, failed_report: dict | None = None) -> list[dict]:
    """Short local-only recommendations; no automatic action."""
    actions = []
    config_report = config_report or {}
    health_report = health_report or {}
    pending_report = pending_report or {}
    failed_report = failed_report or {}

    def add(priority: str, code: str, message: str, target: str = ""):
        actions.append({"priority": priority, "code": code, "message": message, "target": target})

    if int(config_report.get("issue_count", 0) or 0):
        add("high", "config_issues", f"{config_report.get('issue_count')} config issue found. Check service/package bindings.")
    if int(config_report.get("price_cache_missing_count", 0) or 0):
        add("medium", "price_cache_missing", f"{config_report.get('price_cache_missing_count')} active service has no price cache. Run service price update when traffic is calm.")
    if int(config_report.get("panel_service_name_cache_missing_count", 0) or 0):
        add("low", "service_name_cache_missing", f"{config_report.get('panel_service_name_cache_missing_count')} active service has no cached panel service name.")
    if int(pending_report.get("old_count", 0) or 0):
        add("medium", "old_pending_orders", f"{pending_report.get('old_count')} pending order is older than alert threshold. Manual panel check is recommended.")
    if failed_report.get("high"):
        add("high", "failed_spike_24h", f"{failed_report.get('count')} failed order in last 24h. Check recent panel/service problems.")

    for item in (health_report.get("lowest") or [])[:5]:
        if item.get("level") == "risk":
            add(
                "high",
                "service_health_risk",
                f"Service health risk: panel={item.get('panel_key')} service={item.get('service_id')} score={item.get('score')}.",
                str(item.get("advert_id", "")),
            )
        elif item.get("level") == "watch":
            add(
                "medium",
                "service_health_watch",
                f"Watch service: panel={item.get('panel_key')} service={item.get('service_id')} score={item.get('score')}.",
                str(item.get("advert_id", "")),
            )

    return actions[:25]


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


def get_delay_alert_threshold_seconds(item: dict) -> int:
    """Gecikme alarmını sabit süre yerine geçmiş tamamlanma ortalamasına göre ayarlar."""
    try:
        avg_minutes = float((item or {}).get("avg_completion_minutes", 0) or 0)
    except Exception:
        avg_minutes = 0
    if avg_minutes <= 0:
        return 5400
    return max(1800, int(avg_minutes * 1.75 * 60))


def add_order_note(smm_order_id: str, note: str):
    return False

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
    if margin >= PROFIT_TARGET_MARGIN_PERCENT:
        return f"Fiyat önerisi: Mevcut fiyat sağlıklı görünüyor. Net kâr: {format_tl_amount(current_profit)}"
    return f"Fiyat önerisi: Marj düşük (%{round(margin, 1)}). Fiyat veya panel servisi kontrol edilmeli."


def classify_failed_reason(reason: str, detail: str = "") -> str:
    text = normalize_text(f"{reason} {detail}")
    if "ön kontrol" in text or "on kontrol" in text or "preflight" in text:
        return "preflight"
    if "bakiye" in text or "balance" in text or "insufficient" in text:
        return "balance"
    if "link" in text or "url" in text or "cdn" in text or "görsel" in text or "gorsel" in text:
        return "link"
    if "zarar" in text or "anti_loss" in text or "maliyet" in text or "cost" in text:
        return "profit"
    if "timeout" in text or "connection" in text or "circuit" in text or "http 5" in text:
        return "panel_timeout"
    if "api key" in text or "env" in text or "config" in text or "panel bilgileri" in text:
        return "config"
    if "servis" in text or "service" in text or "panelde bulunamadı" in text or "bulunamadı" in text:
        return "service"
    if "order id" in text or "id eksik" in text or "belirsiz" in text:
        return "manual_check"
    if "panel" in text or "api" in text:
        return "panel"
    return "other"


def classify_failed_retry_policy(category: str, reason: str = "", detail: str = "") -> dict:
    """Failed kayıtlarında otomatik işlem başlatmadan retry uygunluğunu daha doğru etiketler."""
    category = str(category or "other")
    text = normalize_text(f"{reason} {detail}")
    if category in {"link", "preflight", "config", "manual_check"}:
        return {"retryable": False, "retry_note": "Manuel düzeltme gerekli"}
    if category == "balance":
        return {"retryable": True, "retry_note": "Bakiye doldurulduktan sonra retry uygun"}
    if category == "panel_timeout":
        return {"retryable": True, "retry_note": "Panel timeout/5xx sonrası retry uygun"}
    if category == "service":
        return {"retryable": False, "retry_note": "Servis ID/panel eşleşmesi kontrol edilmeli"}
    if category == "profit":
        return {"retryable": False, "retry_note": "Fiyat/maliyet kontrolü gerekli"}
    if category == "panel":
        if any(marker in text for marker in ["timeout", "http 5", "connection", "temporar", "geçici", "gecici"]):
            return {"retryable": True, "retry_note": "Geçici panel hatası sonrası retry uygun"}
        return {"retryable": False, "retry_note": "Panel cevabı manuel kontrol edilmeli"}
    return {"retryable": False, "retry_note": "Manuel kontrol gerekli"}


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
    return {"count": 0, "gross": 0.0, "source": "", "avg_sale_tl": 0, "product_name": report_name}


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
        if margin < PROFIT_TARGET_MARGIN_PERCENT:
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


def reset_sales_stats(scope: str = "daily"):
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
            "submitted_at": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
            "delay_alert_sent": False,
            "cancelled": False,
            "price": float(price or 0),
        })
        log("info", "order_queued", order_id=order_id, smm_order_id=smm_order_id, product=product_name)
        save_state()




def check_pending_order_age_alerts(now_ts: int | None = None) -> dict:
    """Bekleyen sipariş yaşını kontrol eder; silmez, retry yapmaz, sadece spam korumalı Telegram uyarısı atar."""
    now_ts = int(now_ts or time.time())
    threshold = max(300, int(PENDING_AGE_ALERT_SECONDS))
    repeat_seconds = max(threshold, int(PENDING_AGE_ALERT_REPEAT_SECONDS))
    alerted = 0
    checked = 0
    changed = False

    for item in PENDING_ORDERS:
        if not isinstance(item, dict) or item.get("cancelled"):
            continue
        created_at = int(item.get("created_at", 0) or 0)
        if not created_at:
            continue
        checked += 1
        age_seconds = max(0, now_ts - created_at)
        if age_seconds < threshold:
            continue
        last_alert = int(item.get("pending_age_alert_sent_at", 0) or 0)
        if last_alert and (now_ts - last_alert) < repeat_seconds:
            continue

        send_telegram(
            f"Bekleyen sipariş yaş uyarısı.\n\n"
            f"Ürün: {item.get('product_name', 'Bilinmiyor')}\n"
            f"Panel: {item.get('panel', '-')}\n"
            f"Itemsatış ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\n"
            f"SMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
            f"Bekleme: {format_duration_minutes(age_seconds / 60)}\n"
            f"Link: {item.get('link', '')}\n\n"
            f"Bot siparişi silmedi, retry yapmadı. Sadece kontrol uyarısıdır."
        )
        item["pending_age_alert_sent_at"] = now_ts
        item["delay_alert_sent"] = True
        alerted += 1
        changed = True

    if changed:
        save_state()
    return {"checked": checked, "alerted": alerted, "threshold_seconds": threshold, "repeat_seconds": repeat_seconds}


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


def parse_jsonish_post_datas(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return value
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else value
    except Exception:
        return value


def normalize_payload_post_datas(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    cloned = dict(data)
    keys = ("post_datas", "postData", "post_data")
    for key in keys:
        if key in cloned:
            cloned[key] = parse_jsonish_post_datas(cloned.get(key))
    for container_key in ("details", "data", "order", "purchase", "payload"):
        child = cloned.get(container_key)
        if isinstance(child, dict):
            child = dict(child)
            changed = False
            for key in keys:
                if key in child:
                    child[key] = parse_jsonish_post_datas(child.get(key))
                    changed = True
            if changed:
                cloned[container_key] = child
    return cloned


def payload_variants(data: dict):
    """Önce ana payload, sonra varsa raw içindeki gömülü payload'u döndürür."""
    yield normalize_payload_post_datas(data)
    embedded = parse_embedded_itemsatis_payload(data)
    if embedded:
        yield normalize_payload_post_datas(embedded)


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


def extract_customer_link(data: dict) -> str:
    """Webhook event filtresinde link kanıtı aramak için güvenli alias.

    Eski patch hattında is_itemsatis_purchase_event bu helper'ı çağırıyordu ama
    fonksiyon tanımlı değildi. Event bilgisi olmayan webhooklarda NameError üretip
    sipariş filtresini bozmasın diye find_order_link üzerinden tek noktaya bağlandı.
    """
    try:
        return find_order_link(data)
    except Exception as e:
        log("warning", "extract_customer_link_failed", error=str(e)[:240])
        return ""


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


def get_itemsatis_report_name(advert_id: str, product_name: str = "") -> str:
    product_name = str(product_name or "").strip()
    if product_name and not is_generic_itemsatis_title(product_name):
        return product_name
    return f"Itemsatış İlanı {str(advert_id or "").strip()}" if advert_id else "Bilinmeyen Ürün"


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
    if PANEL_SERVICE_NAME_CACHE.get(cache_key) != service_name:
        PANEL_SERVICE_NAME_CACHE[cache_key] = service_name
        mark_cache_state_dirty()


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

    previous = DYNAMIC_SERVICES.get(advert_id) if isinstance(DYNAMIC_SERVICES, dict) else {}
    created_at = int((previous or {}).get("created_at") or time.time())
    next_service = normalize_dynamic_service(
        advert_id,
        {
            "panel": panel_key,
            "service_id": service_id,
            "quantity": quantity,
            "platform": platform,
            "active": active,
            "source": "dynamic",
            "created_at": created_at,
        },
    )

    if previous:
        comparable_keys = ("panel", "panel_key", "service_id", "quantity", "platform", "active", "source")
        if all(previous.get(key) == next_service.get(key) for key in comparable_keys):
            return previous

    DYNAMIC_SERVICES[advert_id] = next_service
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


def format_optional_tl(value) -> str:
    if value is None:
        return "Bilinmiyor"
    return format_tl_amount(value)


def format_order_balance_line(balance_before_tl, cost_tl) -> str:
    """Telegram sipariş mesajları için mevcut ve tahmini sipariş sonrası bakiyeyi üretir."""
    before_text = format_optional_tl(balance_before_tl)
    if balance_before_tl is None or cost_tl is None:
        return f"Mevcut bakiye: {before_text}"
    return (
        f"Mevcut bakiye: {before_text}\n"
        f"Tahmini sipariş sonrası bakiye: {format_tl_amount(float(balance_before_tl) - float(cost_tl))}"
    )


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
    cached_rate = SERVICE_PRICE_CACHE.get(cache_key)
    last_checked = int(SERVICE_RATE_CHECK_TIMES.get(cache_key, 0) or 0)
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
                rate_key = f"{panel_key}:{service_id}"
                missing_key = f"missing:{panel_key}:{service_id}"
                old_rate = SERVICE_PRICE_CACHE.get(rate_key)
                had_missing = missing_key in SERVICE_PRICE_CACHE
                SERVICE_PRICE_CACHE[rate_key] = rate_raw
                SERVICE_RATE_CHECK_TIMES[rate_key] = int(time.time())
                SERVICE_PRICE_CACHE.pop(missing_key, None)
                if old_rate != rate_raw or had_missing:
                    mark_cache_state_dirty()
                    save_cache_state()
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

def build_admin_balance_rows() -> list:
    return [{"panel_key": normalize_panel_key(key), "panel_name": panel.get("name", key), "has_env": bool(panel.get("api_url") and panel.get("api_key")), "balance_text": "Hen?z kontrol edilmedi", "updated_at": "-", "alert_disabled": is_low_balance_warning_disabled(key, panel.get("name", key))} for key, panel in PANEL_MAP.items()]


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
            name = f"Itemsatis Ilani {advert_id}"
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

    if changed:
        invalidate_itemsatis_local_adverts_cache()
    return changed


def clear_itemsatis_advert_import_cache():
    """İlan içe aktarma/cache kayıtlarını temizler; dinamik servis ve paket ayarlarına dokunmaz."""
    redis_set_json(ITEMSATIS_ADVERT_MANUAL_KEY, [])
    redis_set_json(ITEMSATIS_ADVERT_CACHE_KEY, {"items": [], "updated_at": int(time.time()), "updated_at_text": now_tr().strftime("%Y-%m-%d %H:%M:%S"), "source": "cleared", "scraped_count": 0})
    invalidate_itemsatis_local_adverts_cache()

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
    invalidate_itemsatis_local_adverts_cache()
    return len(rows)

def collect_itemsatis_adverts_from_local_state(include_cache: bool = True, include_history: bool = False) -> list[dict]:
    global _ITEMSATIS_LOCAL_ADVERTS_CACHE
    cache_key = f"include_cache={bool(include_cache)}|include_history={bool(include_history)}"
    now_ts = time.time()
    try:
        if (
            _ITEMSATIS_LOCAL_ADVERTS_CACHE.get("key") == cache_key
            and _ITEMSATIS_LOCAL_ADVERTS_CACHE.get("rows") is not None
            and (now_ts - float(_ITEMSATIS_LOCAL_ADVERTS_CACHE.get("ts", 0) or 0)) < max(1, int(ITEMSATIS_LOCAL_ADVERTS_CACHE_SECONDS))
        ):
            return [dict(item) for item in (_ITEMSATIS_LOCAL_ADVERTS_CACHE.get("rows") or [])]
    except Exception:
        pass

    rows = {}

    def is_bad_advert(advert_id_s: str, name_s: str = "", source: str = "") -> bool:
        advert_id_s = str(advert_id_s or "").strip()
        name_s = normalize_text(name_s)
        if not advert_id_s or advert_id_s.startswith("manual-") or not advert_id_s.isdigit():
            return True
        if source in {"pending_orders", "failed_orders"} and not include_history:
            return True
        test_words = ["test", "deneme", "webhook", "raw", "bilinmeyen urun"]
        return any(w in name_s for w in test_words)

    def add(advert_id, name="", source="local", url=""):
        advert_id_s = str(advert_id or "").strip()
        name_s = str(name or "").strip() or f"Itemsatis Ilani {advert_id_s}"
        if is_bad_advert(advert_id_s, name_s, source):
            return
        existing = rows.get(advert_id_s, {})
        if advert_id_s not in rows or not existing.get("name"):
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
        add(advert_id, (service or {}).get("name", ""), "service_mapping")
    for advert_id, package in get_package_configs(include_inactive=True).items():
        add(advert_id, (package or {}).get("name", ""), "package_mapping")
    if include_history:
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
    result_rows = sorted(enriched, key=lambda x: (x.get("status") != "missing", str(x.get("name", "").lower())))
    try:
        _ITEMSATIS_LOCAL_ADVERTS_CACHE = {"ts": now_ts, "key": cache_key, "rows": [dict(item) for item in result_rows]}
    except Exception:
        pass
    return result_rows


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
    return {}


def delete_favorite_service(favorite_key: str) -> bool:
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
            if PANEL_API_LOG_NORMAL or elapsed >= SLOW_API_THRESHOLD_SECONDS or r.status_code >= 400:
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
    - Panel bildirimi kapalıysa hata üretmeden sessizce geçer.
    """
    panel_key = normalize_panel_key(panel_key or panel_name or "")
    repeat_minutes = get_low_balance_repeat_minutes(panel_key, panel_name)
    try:
        balance_tl = convert_balance_to_try(balance, currency)
        if balance_tl is None:
            log("warning", "balance_parse_failed", panel=panel_name, balance=balance, currency=currency)
            return False

        if is_low_balance_warning_disabled(panel_key, panel_name):
            log("info", "low_balance_warning_disabled", panel=panel_name or panel_key, balance_tl=round(balance_tl, 2))
            return False

        key = normalize_panel_key(panel_key or panel_name)
        now_ts = int(time.time())
        threshold = float(BALANCE_WARN_THRESHOLD_TL)
        repeat_seconds = max(60, int(repeat_minutes) * 60)

        if balance_tl > threshold:
            if key in BALANCE_WARN_LAST:
                BALANCE_WARN_LAST.pop(key, None)
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

    if ORDER_STATUS_CHECKS_ENABLED:
        existing = _BACKGROUND_TASKS.get("background_check_orders")
        if existing and not existing.done():
            log("info", "background_task_already_running", task="background_check_orders")
        else:
            _BACKGROUND_TASKS["background_check_orders"] = asyncio.create_task(
                periodic_runner("background_check_orders", int(os.getenv("CHECK_ORDERS_INTERVAL_SECONDS", "300")), check_orders, 45)
            )
            log("info", "background_order_status_checker_started")
    else:
        log("warning", "background_order_status_checker_disabled")

    if ENABLE_BACKGROUND_CHECKS:
        task_specs = {
            "background_check_services": (int(os.getenv("CHECK_SERVICES_INTERVAL_SECONDS", "300")), check_services, 90),
            "background_check_balances": (CHECK_BALANCE_INTERVAL_SECONDS, check_all_panel_balances, 20),
        }

        for name, (interval, func, delay) in task_specs.items():
            existing = _BACKGROUND_TASKS.get(name)
            if existing and not existing.done():
                log("info", "background_task_already_running", task=name)
                continue
            _BACKGROUND_TASKS[name] = asyncio.create_task(periodic_runner(name, interval, func, delay))
    else:
        log("info", "background_heavy_periodic_checks_disabled", mode="order_status_only")

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

/* BOOSTERA_MOBILE_USABILITY_SAFE_LAYER */
:focus-visible {
  outline: 3px solid rgba(125, 211, 252, .92) !important;
  outline-offset: 3px !important;
  box-shadow: 0 0 0 5px rgba(14, 165, 233, .16) !important;
}
button:disabled, .btn.disabled, input:disabled, select:disabled, textarea:disabled {
  opacity: .55 !important;
  cursor: not-allowed !important;
  transform: none !important;
  filter: grayscale(.2) !important;
}
.actions, .toolbar, .top-actions, .nav, .pkg-actions {
  row-gap: 10px !important;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
}
.actions form, .actions .btn, .toolbar form, .toolbar .btn {
  min-width: 0;
}
.notice.warning, .badge.warn, .pill.warn {
  border-color: rgba(245, 158, 11, .36) !important;
  background: rgba(245, 158, 11, .13) !important;
  color: #fde68a !important;
}
.notice.danger, .danger-note, .badge.bad, .pill.bad {
  border-color: rgba(239, 68, 68, .36) !important;
  background: rgba(239, 68, 68, .13) !important;
  color: #fecaca !important;
}
.card > table, .notice > table, .filter-box > table {
  min-width: 760px;
}
@media (min-width: 761px) {
  .card:has(> table), .notice:has(> table), .filter-box:has(> table) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
}
@media (max-width: 760px) {
  .card:has(> table), .notice:has(> table), .filter-box:has(> table) {
    overflow: visible !important;
  }
  .card > table, .notice > table, .filter-box > table, table.table {
    min-width: 0 !important;
    width: 100% !important;
    display: block !important;
    overflow: visible !important;
  }
  thead { display: none !important; }
  tbody {
    display: grid !important;
    gap: 12px !important;
    min-width: 0 !important;
    width: 100% !important;
  }
  tr {
    display: grid !important;
    min-width: 0 !important;
    width: 100% !important;
    border: 1px solid rgba(148, 163, 184, .18) !important;
    border-radius: 14px !important;
    background: rgba(15, 23, 42, .78) !important;
    padding: 8px !important;
  }
  td, .table td {
    display: grid !important;
    grid-template-columns: 118px minmax(0, 1fr) !important;
    gap: 10px !important;
    align-items: start !important;
    min-width: 0 !important;
    width: 100% !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
  }
  td::before, .table td::before {
    content: attr(data-label);
    color: #94a3b8;
    font-size: 10px;
    font-weight: 900;
    letter-spacing: .08em;
    text-transform: uppercase;
  }
  td[data-label="İşlem"], td[data-label="İşlem"] form, td[data-label="İşlem"] .btn,
  td[data-label="İşlem"], td[data-label="Islem"], td[data-label="İŞLEM"] {
    grid-template-columns: 1fr !important;
  }
  td form, td .actions, td .toolbar {
    display: grid !important;
    grid-template-columns: 1fr !important;
    width: 100% !important;
    gap: 8px !important;
  }
}
@media (max-width: 480px) {
  .wrap, .container, .shell {
    width: calc(100% - 12px) !important;
  }
  .card, .package-card, .component-card, .component-form, .notice {
    padding: 12px !important;
  }
  td, .table td {
    grid-template-columns: 1fr !important;
  }
  .pill, .badge, .price-badge {
    width: fit-content;
    max-width: 100%;
    white-space: normal !important;
    text-align: left;
  }
}

</style>
</head>
<body>
<div class="container">
<h1>Boostera Admin</h1>
<div class="muted">API key girilmez. API keyler Render Environment içinde kalır. Buradan sadece Itemsatış ilanını panel servisine bağlarsın.</div>
<div class="notice">Yeni servis ekleme: Itemsatış İlan ID + Panel + Panel Servis ID + Adet + Platform. İlan adı sipariş mesajlarında Itemsatış webhookundan otomatik alınır.</div>

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
</div>

<div class="notice">
  Panel bakiyeleri admin sayfası açılırken canlı API ile çekilmez; burada son bilinen değer gösterilir. Güncel değer için manuel olarak <b>Bakiyeleri Güncelle</b> butonuna bas.
</div>
<div class="toolbar" style="margin-top:12px;">
  <form method="post" action="/admin/refresh-balances" style="display:inline;">
    <button class="green" type="submit">Bakiyeleri Güncelle</button>
  </form>
  <a href="/check-balances"><button type="button">JSON Bakiye Kontrol</button></a>
</div>
<div class="table-wrap" style="margin:14px 0 18px;">
<table>
<thead><tr><th>Panel</th><th>Son Bilinen Bakiye</th><th>Son Kontrol</th><th>Env Durumu</th><th>Düşük Bakiye Bildirimi</th><th>İşlem</th></tr></thead>
<tbody>
{% for row in balance_rows %}
<tr>
<td>{{ row.panel_name|e }} <span class="muted">({{ row.panel_key|e }})</span></td>
<td>{{ row.balance_text|e }}</td>
<td>{{ row.updated_at|e }}</td>
<td><span class="badge {{ 'active' if row.has_env else 'passive' }}">{{ 'Hazır' if row.has_env else 'Eksik env' }}</span></td>
<td><span class="badge {{ 'passive' if row.alert_disabled else 'active' }}">{{ 'Kapalı' if row.alert_disabled else 'Açık' }}</span></td>
<td class="actions">
  <form method="post" action="/admin/low-balance-toggle">
    <input type="hidden" name="panel" value="{{ row.panel_key|e }}">
    {% if row.alert_disabled %}
      <input type="hidden" name="disabled" value="false"><button class="green" type="submit">Bildirimi Aç</button>
    {% else %}
      <input type="hidden" name="disabled" value="true"><button class="toggle" type="submit">Bildirimi Kapat</button>
    {% endif %}
  </form>
</td>
</tr>
{% endfor %}
</tbody>
</table>
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

<div class="filters" style="margin:16px 0; display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; align-items:end;">
  <div class="filter-box"><label>Hızlı Ara</label><input id="serviceQuickFilter" placeholder="İlan ID, panel, servis ID, isim..." autocomplete="off"></div>
  <div class="filter-box"><label>Panel</label><select id="servicePanelFilter"><option value="">Tümü</option>{% for key, panel in panels.items() %}<option value="{{ key|e }}">{{ panel.name|e }}</option>{% endfor %}</select></div>
  <div class="filter-box"><label>Platform</label><select id="servicePlatformFilter"><option value="">Tümü</option><option value="instagram">Instagram</option><option value="tiktok">TikTok</option><option value="youtube">YouTube</option><option value="x">X/Twitter</option><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="other">Diğer</option></select></div>
  <div class="filter-box"><label>Durum</label><select id="serviceStatusFilter"><option value="">Tümü</option><option value="aktif">Aktif</option><option value="pasif">Pasif</option></select></div>
</div>
<div class="muted" id="serviceFilterCount" style="margin:-4px 0 12px 0;"></div>
<table>
<thead><tr><th>İlan ID</th><th>Panel</th><th>Servis ID</th><th>Panel Servis Adı</th><th>Adet</th><th>Platform</th><th>Durum</th><th>Kaynak</th><th>İşlem</th></tr></thead>
<tbody>
{% for advert_id, service in services.items() %}
<tr class="service-row" data-panel="{{ service.panel_key|default(service.panel)|lower|e }}" data-platform="{{ service.platform|lower|e }}" data-status="{{ 'aktif' if service.active else 'pasif' }}">
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
  <a class="btn" href="/admin/bind-service?advert_id={{ advert_id|e }}&panel={{ service.panel_key|e }}&service_id={{ service.service_id|e }}&quantity={{ service.quantity|e }}&platform={{ service.platform|e }}">Düzenle</a>
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
  function norm(v){ return (v || '').toString().toLowerCase().trim(); }
  function filterServices(){
    var q = norm(document.getElementById('serviceQuickFilter') && document.getElementById('serviceQuickFilter').value);
    var panel = norm(document.getElementById('servicePanelFilter') && document.getElementById('servicePanelFilter').value);
    var platform = norm(document.getElementById('servicePlatformFilter') && document.getElementById('servicePlatformFilter').value);
    var status = norm(document.getElementById('serviceStatusFilter') && document.getElementById('serviceStatusFilter').value);
    var rows = Array.from(document.querySelectorAll('tr.service-row'));
    var visible = 0;
    rows.forEach(function(row){
      var body = norm(row.innerText);
      var rowPanel = norm(row.getAttribute('data-panel'));
      var rowPlatform = norm(row.getAttribute('data-platform'));
      var rowStatus = norm(row.getAttribute('data-status'));
      var ok = true;
      if(q && body.indexOf(q) === -1) ok = false;
      if(panel && rowPanel.indexOf(panel) === -1 && body.indexOf(panel) === -1) ok = false;
      if(platform && rowPlatform !== platform) ok = false;
      if(status && rowStatus !== status) ok = false;
      row.style.display = ok ? '' : 'none';
      if(ok) visible += 1;
    });
    var count = document.getElementById('serviceFilterCount');
    if(count) count.textContent = rows.length ? ('Gösterilen servis: ' + visible + ' / ' + rows.length) : '';
  }
  ['serviceQuickFilter','servicePanelFilter','servicePlatformFilter','serviceStatusFilter'].forEach(function(id){
    var el = document.getElementById(id);
    if(el) el.addEventListener('input', filterServices);
    if(el) el.addEventListener('change', filterServices);
  });
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', filterServices); else filterServices();
})();
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



@app.post("/admin/refresh-balances")
def admin_refresh_balances(user: str = Depends(get_current_admin)):
    """Admin manuel bakiye yenileme. Sayfa açılışında değil, sadece butonla canlı API çağırır."""
    check_all_panel_balances(force_alert=False)
    return RedirectResponse("/admin", status_code=303)


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
            "panel_key": panel_key,
            "service_id": service_id,
            "panel_service_name": get_cached_panel_service_name(panel_key, service_id),
            "quantity": service.get("quantity"),
            "platform": service.get("platform"),
            "active": bool(raw_service.get("active", True)),
            "source": raw_service.get("source", "code"),
        }
    html = template.render(services=services, panels=PANEL_MAP, balance_rows=build_admin_balance_rows())
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
        previous = DYNAMIC_SERVICES.get(str(advert_id).strip(), {}) if isinstance(DYNAMIC_SERVICES, dict) else {}
        previous_panel = normalize_panel_key((previous or {}).get("panel_key") or (previous or {}).get("panel") or "")
        previous_service_id = str((previous or {}).get("service_id") or "").strip()
        set_dynamic_service(advert_id, panel, service_id, quantity, platform, True)
        panel_key = normalize_panel_key(panel)
        service_id_s = str(service_id or "").strip()
        if (previous_panel != panel_key or previous_service_id != service_id_s) and not _service_price_cache_exists(panel_key, service_id_s):
            prime_service_price_cache(panel_key, service_id_s, f"Itemsatış ilanı {advert_id}")
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
    """Admin panelden servis fiyat kontrolünü arka planda başlatır."""
    def _job():
        safety = build_service_binding_safety_report()
        log("info", "service_binding_safety_report", issue_count=safety.get("issue_count", 0), checked_dynamic=safety.get("checked_dynamic", 0), checked_package_components=safety.get("checked_package_components", 0), issues=safety.get("issues", [])[:8])
        result = check_services()
        pending_age = check_pending_order_age_alerts()
        send_telegram(
            f"Servis fiyat kontrolü tamamlandı.\n\n"
            f"Kontrol sonucu:\n"
            f"Fiyat değişen: {result.get('changed_count', 0)}\n"
            f"Yeni cachelenen: {result.get('initialized_count', 0)}\n"
            f"Panelde bulunamayan: {result.get('missing_count', 0)}\n\n"
            f"{format_service_binding_safety_summary(safety)}\n\n"
            f"Pending yaş uyarısı: {pending_age.get('alerted', 0)}"
        )
        return {"price_check": result, "service_binding_safety": safety, "pending_age": pending_age}

    run_admin_background_job("check_services_manual", _job)
    return RedirectResponse("/admin?bg=check_services_started", status_code=303)


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

    if updated:
        save_cache_state()
    return {"checked": checked, "updated": updated, "missing": missing}


@app.post("/admin/update-service-names")
def admin_update_service_names(user: str = Depends(get_current_admin)):
    def _job():
        result = refresh_panel_service_names()
        log("info", "admin_service_names_updated", **result)
        try:
            send_telegram(
                "Servis isimleri güncellendi.\n\n"
                f"Kontrol edilen: {result.get('checked', 0)}\n"
                f"Güncellenen: {result.get('updated', 0)}\n"
                f"Bulunamayan: {result.get('missing', 0)}"
            )
        except Exception as e:
            log("warning", "service_name_update_telegram_failed", error=str(e))
        return result

    run_admin_background_job("refresh_panel_service_names", _job)
    return RedirectResponse("/admin?bg=service_names_started", status_code=303)


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
    <small>Instagram/TikTok seçiliyse paylaşım parametreleri temizlenir; diğer platformlarda link olduğu gibi panele gider.</small>
  </label>
  <label class="full">Servis adı / not (opsiyonel)
    <input name="product_name" placeholder="Boş bırakırsan paneldeki servis adı çekilir" maxlength="180">
  </label>
  <label>Satış fiyatı TL (opsiyonel)
    <input id="manualSalePrice" name="sale_price" inputmode="decimal" placeholder="Örn: 49.90">
    <small>Boş bırakılırsa sadece panel maliyeti ve bakiye gösterilir.</small>
  </label>
  <div class="notice full" id="manualCostBox">Panel maliyeti: Panel + servis ID + adet girince otomatik hesaplanır.</div>
  <button class="full" type="submit" onclick="if(!confirm('Bu sipariş seçilen dış panele gönderilecek. Devam edilsin mi?')) return false; this.disabled=true; this.textContent='Gönderiliyor...'; this.form.submit(); return false;">Siparişi Panele Gönder</button>
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
    const saleRaw=document.getElementById('manualSalePrice')?.value||'0';
    const sale=parseFloat(String(saleRaw).replace(',','.'))||0;
    const cost=parseFloat(d.cost_tl||0)||0;
    let extra='';
    if(sale>0 && cost>0){
      const commission=sale*0.07;
      const net=sale-commission-cost;
      const margin=sale>0?(net/sale*100):0;
      extra=` · Komisyon: <b>${commission.toFixed(2)} TL</b> · Net kâr: <b>${net.toFixed(2)} TL</b> · Marj: <b>%${margin.toFixed(1)}</b>`;
    }
    box.innerHTML=`Panel fiyatı: <b>${d.rate_tl}</b> / 1000 · Adet: <b>${d.quantity}</b> · Tahmini maliyet: <b>${d.cost_tl_text}</b>${extra}`;
  }catch(e){box.textContent='Panel maliyeti hesaplanamadı.';}
}
['manualPanel','manualServiceId','manualQuantity','manualSalePrice'].forEach(id=>{document.addEventListener('input',e=>{if(e.target&&e.target.id===id) updateManualCost();});document.addEventListener('change',e=>{if(e.target&&e.target.id===id) updateManualCost();});});
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
    return HTMLResponse(content=template.render(panels=PANEL_MAP, message=message, error=error, favorites={}))


def manual_order_redirect(message: str = "", error: str = ""):
    params = {}
    if message:
        params["message"] = str(message)[:500]
    if error:
        params["error"] = str(error)[:500]
    query = urlencode(params)
    return RedirectResponse(f"/admin/manual-order?{query}" if query else "/admin/manual-order", status_code=303)


@app.post("/admin/manual-order")
def admin_manual_order_submit(
    panel: str = Form(...),
    service_id: str = Form(...),
    quantity: int = Form(...),
    platform: str = Form("other"),
    link: str = Form(...),
    product_name: str = Form(""),
    sale_price: str = Form("0"),
    user: str = Depends(get_current_admin),
):
    panel_key = normalize_panel_key(panel)
    panel_conf = get_panel_config(panel_key)

    if panel_key not in PANEL_MAP:
        return manual_order_redirect(error="Panel bulunamadı")
    if not panel_conf.get("api_url") or not panel_conf.get("api_key"):
        return manual_order_redirect(error="Panel API URL veya API KEY eksik")

    service_id = str(service_id or "").strip()
    if not service_id.isdigit():
        return manual_order_redirect(error="Panel servis ID sadece rakam olmalı")
    if quantity <= 0 or quantity > 1000000:
        return manual_order_redirect(error="Adet 1 ile 1.000.000 arasında olmalı")

    raw_link = str(link or "").strip()
    if not raw_link:
        return manual_order_redirect(error="Link boş olamaz")

    platform = normalize_text(platform or "other") or "other"
    panel_link = normalize_panel_link(raw_link, platform)

    active_pending = find_active_pending_by_link(panel_link, platform)
    if active_pending:
        return manual_order_redirect(
            error=(
                "Bu link için hâlâ pending sipariş var. "
                f"Mevcut SMM ID: {active_pending.get('smm_order_id', '-')}"
            )
        )

    try:
        manual_sale_price = parse_numeric_balance(str(sale_price or "0").replace(",", ".")) or 0.0
        manual_sale_price = max(0.0, float(manual_sale_price))
    except Exception:
        manual_sale_price = 0.0

    fetched_service_name = fetch_panel_service_name_by_id(panel_key, service_id)
    final_product_name = str(product_name or "").strip() or fetched_service_name or f"{panel_conf['name']} Servis {service_id}"
    manual_service = {
        "panel_key": panel_key,
        "panel": panel_conf.get("name", panel_key),
        "api_url": panel_conf.get("api_url", ""),
        "api_key": panel_conf.get("api_key", ""),
        "service_id": service_id,
        "quantity": quantity,
        "platform": platform,
    }

    preflight = validate_service_order_preflight(manual_service, panel_link, "Manuel sipariş")
    if not preflight.get("ok"):
        return manual_order_redirect(error=preflight.get("detail") or preflight.get("reason") or "Manuel sipariş ön kontrol hatası")
    panel_link = preflight.get("link") or panel_link

    balance_data = panel_balance(panel_conf["api_url"], panel_conf["api_key"], panel_conf.get("name", panel_key))
    if "error" in balance_data:
        return manual_order_redirect(error=f"Panel bakiyesi alınamadı: {balance_data.get('error')}")

    manual_cost = estimate_order_cost_from_service(manual_service)
    current_balance_tl = convert_balance_to_try(balance_data.get("balance"), balance_data.get("currency", ""))
    if current_balance_tl is not None and manual_cost is not None and current_balance_tl < manual_cost:
        return manual_order_redirect(
            error=f"Panel bakiyesi yetersiz. Bakiye: {format_tl_amount(current_balance_tl)}, tahmini maliyet: {format_tl_amount(manual_cost)}"
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
        return manual_order_redirect(error=f"Panel sipariş hatası: {smm_result.get('error')}")

    smm_order_id = get_smm_order_id_from_result(smm_result)
    if not smm_order_id:
        log("error", "manual_order_missing_smm_id", panel=panel_key, service_id=service_id, response=str(smm_result)[:500])
        return manual_order_redirect(error="Panel siparişi oluştu gibi görünüyor ama SMM order ID dönmedi. Panelden manuel kontrol et; bot pending'e eklemedi.")

    manual_order_id = f"manual-{now_tr().strftime('%Y%m%d%H%M%S')}-{str(smm_order_id)[-6:]}"
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
        price=manual_sale_price,
    )

    balance_text = format_order_balance_line(current_balance_tl, manual_cost)
    finance_text = build_finance_summary(manual_sale_price, manual_cost)
    if manual_sale_price <= 0:
        finance_text += "\nNot: Manuel satış fiyatı girilmediği için net kâr hesaplanamadı."

    log("success", "manual_order_created", panel=panel_key, service_id=service_id, smm_order_id=smm_order_id)
    send_telegram(
        f"Manuel SMM siparişi panele girildi.\n\n"
        f"Ürün: {final_product_name}\n"
        f"Panel: {panel_conf.get('name', panel_key)}\n"
        f"Servis ID: {service_id}\n"
        f"SMM ID: {smm_order_id}\n"
        f"Adet: {quantity}\n"
        f"Link: {panel_link}\n\n"
        f"{balance_text}\n\n"
        f"{finance_text}"
    )

    msg = f"Sipariş panele girildi. SMM ID: {smm_order_id}"
    return manual_order_redirect(message=msg)


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
<div class="muted">Bu ekran sadece bot takip listesini yönetir. Butonlar panelde gerçek iptal/tamamlandı işlemi yapmaz ve yeni sipariş açmaz.</div>
<p><a href="/admin">← Admin Paneline Dön</a></p>
<table>
<thead>
<tr><th>Ürün</th><th>SMM ID</th><th>Link</th><th>Panel</th><th>Bekleme</th><th>Durum</th><th>İşlem</th></tr>
</thead>
<tbody>
{% for order in pending_orders %}
<tr {% if order.stale %}style="background:rgba(239,68,68,.08);"{% endif %}>
<td>{{ order.product_name|e }}<br><span style="color:#8a8fa3;font-size:12px;">{{ order.itemsatis_order_id|e }}</span></td>
<td>{{ order.smm_order_id|e }}</td>
<td><a href="{{ order.link|e }}" target="_blank">Link</a></td>
<td>{{ order.panel|e }}</td>
<td>{{ order.age_minutes }} dk</td>
<td>
  {% if order.cancelled %}
    <span class="badge cancelled">İptal İşaretli</span>
  {% elif order.stale %}
    <span class="badge cancelled">Gecikmiş</span>
  {% else %}
    <span class="badge active">Aktif</span>
  {% endif %}
</td>
<td style="min-width:220px;">
<form method="post" action="/admin/pending-orders/mark-completed" onsubmit="return confirm('Bu sipariş panelde tamamlandı mı? Bot sadece pending listesinden kaldıracak. Devam edilsin mi?')">
<input type="hidden" name="smm_order_id" value="{{ order.smm_order_id|e }}">
<button type="submit">Tamamlandı Say</button>
</form>
<form method="post" action="/admin/pending-orders/remove-cancelled" onsubmit="return confirm('Bu sipariş iptal/geri iade edildi olarak pending listesinden kaldırılacak. Panelde işlem yapılmaz. Devam edilsin mi?')">
<input type="hidden" name="smm_order_id" value="{{ order.smm_order_id|e }}">
<button class="delete" type="submit">İptal Olarak Kaldır</button>
</form>
{% if not order.cancelled %}
<form method="post" action="/admin/cancel-order" onsubmit="return confirm('Bu sipariş sadece bot takip listesinde iptal işaretlenecek. Devam edilsin mi?')">
<input type="hidden" name="smm_order_id" value="{{ order.smm_order_id|e }}">
<button class="delete" type="submit">Sadece İptal İşaretle</button>
</form>
{% endif %}
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
    now_ts = int(time.time())
    html = template.render(pending_orders=build_pending_admin_rows(now_ts), now_ts=now_ts)
    return HTMLResponse(content=html)


@app.post("/admin/pending-orders/mark-completed")
def admin_pending_mark_completed(smm_order_id: str = Form(...), user: str = Depends(get_current_admin)):
    removed, item = remove_pending_order_by_smm_id(smm_order_id, "manual_completed", "Admin pending ekranından tamamlandı sayıldı")
    if not removed:
        raise HTTPException(status_code=404, detail="Pending sipariş bulunamadı")
    send_telegram(
        f"Pending sipariş admin tarafından tamamlandı sayıldı.\n\n"
        f"Ürün: {item.get('product_name', 'Bilinmiyor')}\n"
        f"Panel: {item.get('panel', 'Bilinmiyor')}\n"
        f"Itemsatış/Manuel ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\n"
        f"SMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
        f"Link: {item.get('link', '')}\n\n"
        f"Not: Panelde işlem yapılmadı, yeni sipariş açılmadı. Sadece bot pending listesinden kaldırıldı."
    )
    return RedirectResponse("/admin/pending-orders", status_code=303)


@app.post("/admin/pending-orders/remove-cancelled")
def admin_pending_remove_cancelled(smm_order_id: str = Form(...), user: str = Depends(get_current_admin)):
    removed, item = remove_pending_order_by_smm_id(smm_order_id, "cancelled_removed", "Admin pending ekranından iptal/geri iade olarak kaldırıldı")
    if not removed:
        raise HTTPException(status_code=404, detail="Pending sipariş bulunamadı")
    send_telegram(
        f"Pending sipariş admin tarafından iptal/geri iade olarak kaldırıldı.\n\n"
        f"Ürün: {item.get('product_name', 'Bilinmiyor')}\n"
        f"Panel: {item.get('panel', 'Bilinmiyor')}\n"
        f"Itemsatış/Manuel ID: {item.get('itemsatis_order_id', 'Bilinmiyor')}\n"
        f"SMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
        f"Link: {item.get('link', '')}\n\n"
        f"Not: Panelde işlem yapılmadı, yeni sipariş açılmadı. Sadece bot pending listesinden kaldırıldı."
    )
    return RedirectResponse("/admin/pending-orders", status_code=303)


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


# ─── OPERATIONAL DASHBOARD OVERRIDE ─────────────────────────────────────────
# Eski rapor/satış dashboard'u yerine canlı operasyon paneli.
# Sipariş, queue, circuit, panel order akışı ve admin CSS yapısına dokunmaz.
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera Operasyon Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#070a17;--panel:#0d1326;--card:#111a32;--card2:#0b1022;--border:rgba(148,163,184,.18);--text:#f8fafc;--muted:#94a3b8;--green:#22c55e;--red:#ef4444;--yellow:#f59e0b;--blue:#38bdf8;--purple:#a78bfa;--shadow:0 18px 55px rgba(0,0,0,.30);--radius:22px}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 10% 0%,rgba(124,58,237,.18),transparent 32%),radial-gradient(circle at 90% 0%,rgba(34,211,238,.10),transparent 28%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",Arial,sans-serif;line-height:1.5}.wrap{max-width:1320px;margin:0 auto;padding:24px}.top{display:flex;gap:14px;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap}.brand h1{margin:0;font-size:28px;letter-spacing:-.04em}.brand p{margin:4px 0 0;color:var(--muted)}.nav{display:flex;gap:10px;flex-wrap:wrap}.btn,button{border:1px solid var(--border);background:rgba(15,23,42,.75);color:var(--text);border-radius:14px;padding:11px 14px;text-decoration:none;font-weight:800;cursor:pointer;min-height:44px}.btn:hover,button:hover{border-color:rgba(167,139,250,.55);transform:translateY(-1px)}.btn:focus-visible,button:focus-visible{outline:3px solid rgba(125,211,252,.9);outline-offset:3px}button:disabled{opacity:.55;cursor:not-allowed;transform:none}button.green,.green{background:linear-gradient(135deg,#22c55e,#16a34a);border:0;color:white}.red{background:linear-gradient(135deg,#ef4444,#b91c1c);border:0;color:white}.warn{background:linear-gradient(135deg,#f59e0b,#b45309);border:0;color:white}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(180deg,rgba(17,26,50,.95),rgba(11,16,34,.92));border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow);min-width:0}.card:hover{border-color:rgba(196,181,253,.34);transform:translateY(-1px);transition:transform .18s ease,border-color .18s ease}.stat .label{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:900}.stat .value{font-size:38px;font-weight:950;margin-top:8px;letter-spacing:-.04em;word-break:break-word}.stat .sub{color:var(--muted);font-size:13px;margin-top:4px}.line{height:3px;border-radius:9px;background:var(--purple);margin:-20px -20px 16px}.line.green{background:var(--green)}.line.red{background:var(--red)}.line.yellow{background:var(--yellow)}.line.blue{background:var(--blue)}.two{display:grid;grid-template-columns:1.1fr .9fr;gap:16px;margin-top:16px}.three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:16px}.list{display:grid;gap:10px}.row{display:flex;justify-content:space-between;gap:12px;border:1px solid rgba(148,163,184,.10);background:rgba(2,6,23,.28);border-radius:14px;padding:12px;align-items:flex-start}.row b{word-break:break-word}.muted{color:var(--muted)}.small{font-size:13px}.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:900;background:rgba(148,163,184,.12);color:var(--muted);white-space:normal;max-width:100%}.pill.ok{background:rgba(34,197,94,.15);color:#86efac}.pill.bad{background:rgba(239,68,68,.15);color:#fca5a5}.pill.warn{background:rgba(245,158,11,.15);color:#fcd34d}.pill.info{background:rgba(56,189,248,.15);color:#7dd3fc}pre{white-space:pre-wrap;word-break:break-word;margin:0;font-size:12px;color:#cbd5e1;max-height:320px;overflow:auto}.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}.notice{border:1px solid rgba(56,189,248,.22);background:rgba(56,189,248,.07);border-radius:18px;padding:14px;margin:16px 0;color:#cbd5e1}.danger-note{border-color:rgba(239,68,68,.30);background:rgba(239,68,68,.08)}@media(max-width:980px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two,.three{grid-template-columns:1fr}}@media(max-width:640px){.wrap{padding:14px}.grid{grid-template-columns:1fr}.top{align-items:stretch}.nav,.toolbar{display:grid;grid-template-columns:1fr 1fr;width:100%;gap:9px}.btn,button{width:100%;text-align:center;min-height:48px}.stat .value{font-size:34px}.row{display:grid;grid-template-columns:1fr}.card{padding:16px;border-radius:18px}.line{margin:-16px -16px 14px}}@media(max-width:420px){.nav,.toolbar{grid-template-columns:1fr}.brand h1{font-size:24px}.wrap{padding:10px}.card{padding:14px;border-radius:16px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><h1>Boostera Operasyon Dashboard</h1><p>Rapor/stat geçmişi yok. Sadece sipariş akışı, queue ve servis sağlığı.</p></div>
    <div class="nav">
      <a class="btn" href="/admin">Admin</a>
      <a class="btn" href="/admin/pending-orders">Pending</a>
      <a class="btn" href="/admin/failed-orders">Failed</a>
      <a class="btn" href="/admin/adverts-bind">İlan Bağla</a>
      <a class="btn" href="/admin/itemsatis-adverts">İlanlar</a>
      <a class="btn" href="/admin/queue-dead">Queue Dead</a>
    </div>
  </div>

  <div class="notice">Bu ekran Redis'e yeni satış/geçmiş/veri yazmaz. Canlı state'i okur; queue canlı sayımı sadece sayfa açılırken veya Queue Yenile butonuyla yapılır.</div>

  <div class="grid">
    <div class="card stat"><div class="line blue"></div><div class="label">Pending Sipariş</div><div id="pendingCount" class="value">-</div><div class="sub">panel takibindeki aktif sipariş</div></div>
    <div class="card stat"><div class="line red"></div><div class="label">Failed Sipariş</div><div id="failedCount" class="value">-</div><div class="sub">manuel kontrol gereken kayıt</div></div>
    <div class="card stat"><div class="line green"></div><div class="label">Aktif Servis</div><div id="activeServiceCount" class="value">-</div><div class="sub">tekil servis eşleşmesi</div></div>
    <div class="card stat"><div class="line yellow"></div><div class="label">Aktif Paket</div><div id="activePackageCount" class="value">-</div><div class="sub">paket ilan eşleşmesi</div></div>
  </div>

  <div class="two">
    <div class="card">
      <h2>Sistem ve Sipariş Akışı</h2>
      <div class="list" id="opsRows"><div class="muted">Yükleniyor...</div></div>
      <div class="toolbar">
        <button onclick="loadLocalOps()">Dashboard Yenile</button>
        <button class="green" onclick="loadQueueStatus()">Canlı Queue Yenile</button>
        <a class="btn" href="/api/system-check" target="_blank">System Check JSON</a>
        <a class="btn" href="/api/queue-status" target="_blank">Queue JSON</a>
      </div>
    </div>
    <div class="card">
      <h2>Canlı Queue / Circuit</h2>
      <div class="list" id="queueRows"><div class="muted">Queue bilgisi yükleniyor...</div></div>
    </div>
  </div>

  <div class="three">
    <div class="card">
      <h2>Servis Bağlantı Sağlığı</h2>
      <div class="list" id="bindingRows"><div class="muted">Yükleniyor...</div></div>
      <div class="toolbar"><a class="btn" href="/api/system-check" target="_blank">Detay JSON</a><a class="btn" href="/admin">Servisleri Aç</a></div>
    </div>
    <div class="card">
      <h2>Fiyat Cache / Kâr Hazırlığı</h2>
      <div class="list" id="priceRows"><div class="muted">Yükleniyor...</div></div>
      <div class="toolbar"><form method="post" action="/admin/update-services" style="display:inline"><button class="green" type="submit">Fiyatları Kontrol Et</button></form></div>
    </div>
    <div class="card">
      <h2>Aynı Link Koruması</h2>
      <div class="list" id="linkRows"><div class="muted">Yükleniyor...</div></div>
      <div class="toolbar"><a class="btn" href="/admin/pending-orders">Pending Gör</a></div>
    </div>
  </div>

  <div class="two">
    <div class="card"><h2>Son Pending Siparişler</h2><div id="pendingRows" class="list"><div class="muted">Yükleniyor...</div></div></div>
    <div class="card"><h2>Son Failed Siparişler</h2><div id="failedRows" class="list"><div class="muted">Yükleniyor...</div></div></div>
  </div>

  <div class="two">
    <div class="card"><h2>Son RAM Logları</h2><div id="logs" class="list"><div class="muted">Yükleniyor...</div></div></div>
    <div class="card"><h2>Hızlı İşlemler</h2><div class="list">
      <a class="btn" href="/admin/manual-order">Manuel Sipariş</a>
      <a class="btn" href="/admin/service-search">Servis Ara</a>
      <a class="btn" href="/admin/packages">Paketler</a>
      <a class="btn" href="/admin/queue-dead">Dead Queue</a>
      <a class="btn" href="/admin/itemsatis-adverts">Itemsatış İlanları</a>
      <a class="btn" href="/admin/adverts-bind">İlan Bağla</a>
    </div></div>
  </div>
</div>
<script>
function esc(v){return String(v ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[ch]));}
function pill(cls,text){return '<span class="pill '+cls+'">'+esc(text)+'</span>'}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'}); if(!r.ok) throw new Error(url+' '+r.status); return await r.json();}
function minsAgo(ts){ts=Number(ts||0); if(!ts) return '-'; return Math.max(0, Math.floor((Date.now()/1000-ts)/60))+' dk';}
function row(label,value,cls){return '<div class="row"><b>'+esc(label)+'</b><span class="'+(cls||'')+'">'+value+'</span></div>';}

async function loadLocalOps(){
  try{
    const d=await getJSON('/api/dashboard-ops');
    document.getElementById('pendingCount').textContent=d.counts.pending||0;
    document.getElementById('failedCount').textContent=d.counts.failed||0;
    document.getElementById('activeServiceCount').textContent=d.counts.active_services||0;
    document.getElementById('activePackageCount').textContent=d.counts.active_packages||0;

    const ops=[];
    ops.push(row('Redis env', pill(d.redis.configured?'ok':'bad', d.redis.configured?'Hazır':'Eksik'), ''));
    ops.push(row('Redis backoff', pill(d.redis.backoff_active?'bad':'ok', d.redis.backoff_active?'Aktif':'Yok'), ''));
    ops.push(row('Telegram', pill(d.telegram.main_configured?'ok':'bad', d.telegram.main_configured?'Hazır':'Eksik'), ''));
    ops.push(row('Panel env hazır', pill(d.counts.configured_panels>0?'ok':'bad', String(d.counts.configured_panels)+' panel'), ''));
    ops.push(row('Pending yaş uyarısı', pill((d.pending_age.delayed_count||0)>0?'warn':'ok', (d.pending_age.delayed_count||0)+' geciken'), ''));
    ops.push(row('Son 24s failed', pill((d.failed_24h.count||0)>0?'warn':'ok', String(d.failed_24h.count||0)), ''));
    document.getElementById('opsRows').innerHTML=ops.join('');

    const b=d.service_binding_safety||{};
    const binding=[];
    binding.push(row('Dynamic kontrol', String(b.checked_dynamic||0), ''));
    binding.push(row('Paket component kontrol', String(b.checked_package_components||0), ''));
    binding.push(row('Sorun', pill((b.issue_count||0)>0?'bad':'ok', String(b.issue_count||0)), ''));
    (b.issues||[]).slice(0,5).forEach(x=>binding.push('<div class="row"><div><b>'+esc(x.code||'issue')+'</b><div class="muted small">'+esc(x.context||'')+' · '+esc(x.detail||'')+'</div></div><span class="pill bad">kontrol</span></div>'));
    document.getElementById('bindingRows').innerHTML=binding.join('');

    const price=[];
    price.push(row('Fiyat cache kaydı', String(d.price_cache.count||0), ''));
    price.push(row('Cache eşleşmeyen aktif servis', pill((d.price_cache.missing_active_service_prices||0)>0?'warn':'ok', String(d.price_cache.missing_active_service_prices||0)), ''));
    price.push(row('Panel servis adı cache', String(d.panel_service_name_cache.count||0), ''));
    price.push(row('Panel adı eksik aktif servis', pill((d.panel_service_name_cache.missing_active_service_names||0)>0?'warn':'ok', String(d.panel_service_name_cache.missing_active_service_names||0)), ''));
    document.getElementById('priceRows').innerHTML=price.join('');

    const links=[];
    links.push(row('Aktif pending link kilidi', String(d.link_locks.count||0), ''));
    if((d.link_locks.sample||[]).length){
      d.link_locks.sample.forEach(x=>links.push('<div class="row"><div><b>'+esc(x.product_name||'Sipariş')+'</b><div class="muted small">'+esc(x.link||'')+'</div></div><span class="pill info">pending</span></div>'));
    } else {
      links.push('<div class="muted">Şu an aktif link kilidi yok.</div>');
    }
    document.getElementById('linkRows').innerHTML=links.join('');

    const pending=(d.latest.pending||[]);
    document.getElementById('pendingRows').innerHTML=pending.length?pending.map(o=>'<div class="row"><div><b>'+esc(o.product_name||'Sipariş')+'</b><div class="muted small">'+esc(o.link||'')+' · '+esc(o.panel||'')+' #'+esc(o.smm_order_id||'')+'</div></div><span class="pill '+(o.stale?'bad':'info')+'">'+(o.stale?'gecikmiş · ':'')+minsAgo(o.created_at)+'</span></div>').join(''):'<div class="muted">Bekleyen sipariş yok.</div>';
    const failed=(d.latest.failed||[]);
    document.getElementById('failedRows').innerHTML=failed.length?failed.map(o=>'<div class="row"><div><b>'+esc(o.product_name||'Sipariş')+'</b><div class="muted small">'+esc(o.reason||'')+' · '+esc(o.detail||'')+'</div></div><span class="pill bad">failed</span></div>').join(''):'<div class="muted">Başarısız sipariş yok.</div>';

    const logs=(d.latest.logs||[]);
    document.getElementById('logs').innerHTML=logs.length?logs.slice().reverse().map(x=>'<div class="row"><div><b>'+esc(String(x.level||'info').toUpperCase())+'</b><div class="muted small">'+esc(x.ts||'')+'</div></div><pre>'+esc(x.event||'')+'</pre></div>').join(''):'<div class="muted">Log yok.</div>';
  }catch(e){
    document.getElementById('opsRows').innerHTML='<pre>'+esc(String(e))+'</pre>';
  }
}

async function loadQueueStatus(){
  const el=document.getElementById('queueRows');
  el.innerHTML='<div class="muted">Canlı queue kontrol ediliyor...</div>';
  try{
    const d=await getJSON('/api/queue-status');
    const q=d.queue||{};
    const rows=[];
    rows.push(row('Waiting', pill((q.waiting||0)>0?'warn':'ok', String(q.waiting||0)), ''));
    rows.push(row('Processing', pill((q.processing||0)>0?'warn':'ok', String(q.processing||0)), ''));
    rows.push(row('Dead', pill((q.dead||0)>0?'bad':'ok', String(q.dead||0)), ''));
    const openCircuits=(d.circuits||[]).filter(x=>x.open);
    rows.push(row('Açık circuit', pill(openCircuits.length?'bad':'ok', String(openCircuits.length)), ''));
    openCircuits.slice(0,5).forEach(x=>rows.push('<div class="row"><div><b>'+esc(x.panel)+'</b><div class="muted small">Retry after: '+esc(x.retry_after||0)+' sn</div></div><span class="pill bad">open</span></div>'));
    el.innerHTML=rows.join('');
  }catch(e){
    el.innerHTML='<pre>'+esc(String(e))+'</pre>';
  }
}

loadLocalOps();
loadQueueStatus();
setInterval(loadLocalOps, 45000);
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

def build_dashboard_ops_payload():
    """Dashboard için hafif, Redis'e yeni history/stat yazmayan operasyon özeti üretir."""
    services_all = get_all_services(include_inactive=True)
    services_active = get_all_services(include_inactive=False)
    packages_active = get_package_configs(include_inactive=False)
    service_binding_safety = build_service_binding_safety_report()
    pending_age = build_pending_age_report()
    failed_24h = build_failed_24h_report()

    def _service_cache_key(service: dict) -> str:
        service = get_service_config(service or {})
        panel_key = normalize_panel_key(service.get("panel_key") or service.get("panel") or "")
        service_id = str(service.get("service_id") or "").strip()
        return make_panel_service_cache_key(panel_key, service_id) if panel_key and service_id else ""

    active_service_cache_keys = []
    for raw_service in services_active.values():
        key = _service_cache_key(raw_service)
        if key:
            active_service_cache_keys.append(key)
    for package in packages_active.values():
        for component in (package or {}).get("components", []) or []:
            component = normalize_package_component(component)
            if not component.get("active", True):
                continue
            key = _service_cache_key(component)
            if key:
                active_service_cache_keys.append(key)

    unique_active_service_keys = list(dict.fromkeys(active_service_cache_keys))
    missing_price_count = sum(1 for key in unique_active_service_keys if key not in (SERVICE_PRICE_CACHE or {}))
    missing_name_count = sum(1 for key in unique_active_service_keys if key not in (PANEL_SERVICE_NAME_CACHE or {}))

    link_samples = []
    seen_links = set()
    for item in PENDING_ORDERS:
        if not isinstance(item, dict) or item.get("cancelled"):
            continue
        normalized_link = normalize_link_for_check(item.get("link", ""), item.get("platform", ""))
        if not normalized_link or normalized_link in seen_links:
            continue
        seen_links.add(normalized_link)
        if len(link_samples) < 6:
            link_samples.append({
                "product_name": item.get("product_name", ""),
                "link": item.get("link", ""),
                "itemsatis_order_id": item.get("itemsatis_order_id", ""),
                "smm_order_id": item.get("smm_order_id", ""),
            })

    configured_panels = [key for key in PANEL_MAP.keys() if is_panel_configured(key)]
    return {
        "ok": True,
        "time_tr": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {
            "pending": len(PENDING_ORDERS),
            "failed": len(FAILED_ORDERS),
            "all_services": len(services_all),
            "active_services": len(services_active),
            "active_packages": len(packages_active),
            "configured_panels": len(configured_panels),
        },
        "redis": {
            "configured": bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN),
            "backoff_active": bool(_REDIS_BACKOFF_UNTIL and time.time() < _REDIS_BACKOFF_UNTIL),
            "backoff_remaining_sec": max(0, int(_REDIS_BACKOFF_UNTIL - time.time())) if _REDIS_BACKOFF_UNTIL else 0,
        },
        "telegram": {
            "main_configured": bool(BOT_TOKEN and CHAT_ID),
            "alerts_configured": bool(BOT_TOKEN and CHAT_ID_ALERTS),
            "sales_configured": bool(BOT_TOKEN and CHAT_ID_SALES),
            "errors_configured": bool(BOT_TOKEN and CHAT_ID_ERRORS),
        },
        "service_binding_safety": service_binding_safety,
        "pending_age": pending_age,
        "failed_24h": failed_24h,
        "price_cache": {
            "count": len(SERVICE_PRICE_CACHE or {}),
            "missing_active_service_prices": missing_price_count,
        },
        "panel_service_name_cache": {
            "count": len(PANEL_SERVICE_NAME_CACHE or {}),
            "missing_active_service_names": missing_name_count,
        },
        "link_locks": {
            "count": len(seen_links),
            "sample": link_samples,
        },
        "latest": {
            "pending": [enrich_pending_order_for_display(item) for item in PENDING_ORDERS[-8:]][::-1],
            "failed": [normalize_failed_order(item) for item in FAILED_ORDERS[-8:] if isinstance(item, dict)][::-1],
            "logs": list(LOG_HISTORY)[-max(1, int(API_LOG_LIMIT)):],
        },
    }


@app.get("/api/dashboard-ops")
def api_dashboard_ops(user: str = Depends(get_current_admin)):
    """Dashboard verisini kısa süre RAM cache ile döndürür; admin panel açıkken Redis/panel yükünü azaltır."""
    global _DASHBOARD_OPS_CACHE
    now_ts = time.time()
    try:
        cached = _DASHBOARD_OPS_CACHE.get("data")
        cached_ts = float(_DASHBOARD_OPS_CACHE.get("ts", 0) or 0)
        if cached and (now_ts - cached_ts) < max(1, int(DASHBOARD_OPS_CACHE_SECONDS)):
            data = dict(cached)
            data["cached"] = True
            data["cache_age_seconds"] = round(now_ts - cached_ts, 2)
            return data
    except Exception:
        pass

    data = build_dashboard_ops_payload()
    try:
        _DASHBOARD_OPS_CACHE = {"ts": now_ts, "data": data}
    except Exception:
        pass
    return data


@app.get("/", response_class=HTMLResponse)
def dashboard(user: str = Depends(get_current_admin)):
    return DASHBOARD_HTML


@app.get("/api/stats")
def api_stats(user: str = Depends(get_current_admin)):
    return {"today_count": 0, "today_gross": 0, "today_net": 0, "pending_count": len(PENDING_ORDERS), "failed_count": len(FAILED_ORDERS)}


@app.get("/api/pending")
def api_pending(user: str = Depends(get_current_admin)):
    return {"orders": [enrich_pending_order_for_display(item) for item in PENDING_ORDERS]}


@app.get("/api/failed")
def api_failed(user: str = Depends(get_current_admin)):
    return {"orders": FAILED_ORDERS}


@app.get("/api/logs")
def api_logs(user: str = Depends(get_current_admin)):
    return {"logs": list(LOG_HISTORY)[-max(1, int(API_LOG_LIMIT)):]}


@app.get("/api/history")
def api_history(user: str = Depends(get_current_admin)):
    return {"orders": []}


@app.get("/api/balance-history")
def api_balance_history(user: str = Depends(get_current_admin)):
    return {"history": {}}


@app.get("/api/link-audit")
def api_link_audit(user: str = Depends(get_current_admin)):
    return {"items": []}


@app.get("/api/favorites")
def api_favorites(user: str = Depends(get_current_admin)):
    return {"items": {}}


@app.get("/api/panel-stats")
def api_panel_stats(user: str = Depends(get_current_admin)):
    return {"items": {}}


@app.get("/api/service-completion-stats")
def api_service_completion_stats(user: str = Depends(get_current_admin)):
    return {"items": {}}


@app.get("/api/buyer-stats")
def api_buyer_stats(user: str = Depends(get_current_admin)):
    return {"items": {}}


@app.get("/api/order-notes")
def api_order_notes(user: str = Depends(get_current_admin)):
    return {"items": {}}


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
    row_html = []
    for row in rows:
        row_id = html.escape(str(row.get("id", "")))
        order_id_html = html.escape(str(row.get("order_id", "")))
        attempts_html = html.escape(str(row.get("attempts", "")))
        reason_html = html.escape(str(row.get("dead_reason", "")))
        payload_html = html.escape(str(row.get("payload_preview", "")))
        row_html.append(
            "<tr>"
            f"<td><code>{row_id}</code></td>"
            f"<td>{order_id_html}</td>"
            f"<td>{attempts_html}</td>"
            f"<td>{reason_html}</td>"
            f"<td><pre style='white-space:pre-wrap;max-width:520px'>{payload_html}</pre></td>"
            "<td>"
            "<form method='post' action='/admin/queue-dead/retry'>"
            f"<input type='hidden' name='queue_id' value='{row_id}'>"
            "<button>Tekrar kuyruğa al</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    rows_text = "".join(row_html) or "<tr><td colspan='6'>Dead queue boş.</td></tr>"
    body = (
        "<div class='card'>"
        "<form method='post' action='/admin/queue-dead/retry'>"
        "<input type='hidden' name='retry_all' value='1'>"
        "<button>Tümünü tekrar kuyruğa al</button>"
        "</form>"
        "</div>"
        "<div class='card'><table class='table'>"
        "<thead><tr><th>Queue ID</th><th>Sipariş</th><th>Deneme</th><th>Sebep</th><th>Payload</th><th>İşlem</th></tr></thead>"
        f"<tbody>{rows_text}</tbody>"
        "</table></div>"
    )
    return simple_admin_page("Queue Dead", body)


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
    config_health = build_config_health_report()
    service_health = build_service_health_summary()
    pending_age = build_pending_age_report()
    failed_24h = build_failed_24h_report()
    service_binding_safety = build_service_binding_safety_report()
    recommended_actions = build_recommended_actions(config_health, service_health, pending_age, failed_24h)
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
        "ok": not bool(duplicate_routes) and bool(config_health.get("ok", True)),
        "time_tr": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "webhook_security": {
            "ip_whitelist_count": len(WEBHOOK_IP_WHITELIST),
            "rate_limit": True,
        },
        "routes_count": len(app.routes),
        "duplicate_routes": duplicate_routes,
        "missing_env": missing_env,
        "configured_panels": configured_panels,
        "missing_panels": missing_panels,
        "pending_count": len(PENDING_ORDERS),
        "failed_count": len(FAILED_ORDERS),
        "pending_age": pending_age,
        "failed_24h": failed_24h,
        "packages_count": len(PACKAGE_CONFIGS or {}),
        "dynamic_services_count": len(DYNAMIC_SERVICES or {}),
        "config_health": config_health,
        "service_binding_safety": service_binding_safety,
        "service_health": service_health,
        "recommended_actions": recommended_actions,
        "balance_alerts": {
            "threshold_tl": BALANCE_WARN_THRESHOLD_TL,
            "repeat_minutes": BALANCE_WARN_REPEAT_MINUTES,
        },
        "background_tasks": background,
        "redis": {
            "configured": bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN),
            "ok": bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN) and not (_REDIS_BACKOFF_UNTIL and time.time() < _REDIS_BACKOFF_UNTIL),
            "backoff_active": bool(_REDIS_BACKOFF_UNTIL and time.time() < _REDIS_BACKOFF_UNTIL),
        },
        "queue_status": {
            "ok": True,
            "not_checked": True,
            "queue": {"waiting": 0, "processing": 0, "dead": 0},
            "note": "Light system-check does not query Redis queue. Use /api/queue-status for live queue counts.",
        },
        "itemsatis_adverts": {
            "profile_url_configured": bool(ITEMSATIS_PROFILE_URL),
            "cached_count": 0,
            "local_count": len(DYNAMIC_SERVICES or {}) + len(PACKAGE_CONFIGS or {}),
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
        fieldnames=["order_id", "advert_id", "product_name", "panel", "smm_order_id", "link", "price", "duration_minutes", "estimated_completion_minutes", "submitted_at", "completed_at"],
        extrasaction="ignore",
    )
    writer.writeheader()
    output.seek(0)
    filename = f"boostera_orders_{now_tr().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.head("/check-panel-health")
def check_panel_health_head():
    return {"ok": True, "status": "alive", "endpoint": "check-panel-health"}


@app.get("/check-panel-health")
def check_panel_health():
    return check_all_panel_balances(force_alert=False)


@app.head("/check-balances")
def check_balances_head():
    return {"ok": True, "status": "alive", "endpoint": "check-balances"}


@app.get("/check-balances")
def check_balances_now(user: str = Depends(get_current_admin)):
    return check_all_panel_balances(force_alert=False)



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

/* BOOSTERA_MOBILE_USABILITY_SAFE_LAYER */
:focus-visible {
  outline: 3px solid rgba(125, 211, 252, .92) !important;
  outline-offset: 3px !important;
  box-shadow: 0 0 0 5px rgba(14, 165, 233, .16) !important;
}
button:disabled, .btn.disabled, input:disabled, select:disabled, textarea:disabled {
  opacity: .55 !important;
  cursor: not-allowed !important;
  transform: none !important;
  filter: grayscale(.2) !important;
}
.actions, .toolbar, .top-actions, .nav, .pkg-actions {
  row-gap: 10px !important;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
}
.actions form, .actions .btn, .toolbar form, .toolbar .btn {
  min-width: 0;
}
.notice.warning, .badge.warn, .pill.warn {
  border-color: rgba(245, 158, 11, .36) !important;
  background: rgba(245, 158, 11, .13) !important;
  color: #fde68a !important;
}
.notice.danger, .danger-note, .badge.bad, .pill.bad {
  border-color: rgba(239, 68, 68, .36) !important;
  background: rgba(239, 68, 68, .13) !important;
  color: #fecaca !important;
}
.card > table, .notice > table, .filter-box > table {
  min-width: 760px;
}
@media (min-width: 761px) {
  .card:has(> table), .notice:has(> table), .filter-box:has(> table) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
}
@media (max-width: 760px) {
  .card:has(> table), .notice:has(> table), .filter-box:has(> table) {
    overflow: visible !important;
  }
  .card > table, .notice > table, .filter-box > table, table.table {
    min-width: 0 !important;
    width: 100% !important;
    display: block !important;
    overflow: visible !important;
  }
  thead { display: none !important; }
  tbody {
    display: grid !important;
    gap: 12px !important;
    min-width: 0 !important;
    width: 100% !important;
  }
  tr {
    display: grid !important;
    min-width: 0 !important;
    width: 100% !important;
    border: 1px solid rgba(148, 163, 184, .18) !important;
    border-radius: 14px !important;
    background: rgba(15, 23, 42, .78) !important;
    padding: 8px !important;
  }
  td, .table td {
    display: grid !important;
    grid-template-columns: 118px minmax(0, 1fr) !important;
    gap: 10px !important;
    align-items: start !important;
    min-width: 0 !important;
    width: 100% !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
  }
  td::before, .table td::before {
    content: attr(data-label);
    color: #94a3b8;
    font-size: 10px;
    font-weight: 900;
    letter-spacing: .08em;
    text-transform: uppercase;
  }
  td[data-label="İşlem"], td[data-label="İşlem"] form, td[data-label="İşlem"] .btn,
  td[data-label="Islem"], td[data-label="İŞLEM"] {
    grid-template-columns: 1fr !important;
  }
  td form, td .actions, td .toolbar {
    display: grid !important;
    grid-template-columns: 1fr !important;
    width: 100% !important;
    gap: 8px !important;
  }
}
@media (max-width: 480px) {
  .wrap, .container, .shell {
    width: calc(100% - 12px) !important;
  }
  .card, .package-card, .component-card, .component-form, .notice {
    padding: 12px !important;
  }
  td, .table td {
    grid-template-columns: 1fr !important;
  }
  .pill, .badge, .price-badge {
    width: fit-content;
    max-width: 100%;
    white-space: normal !important;
    text-align: left;
  }
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


def remember_unbound_webhook(advert_id: str, product_name: str, buyer: str, price, order_id: str, reason: str = "unbound_advert") -> dict:
    advert_id = str(advert_id or "").strip() or "unknown"
    entry = {
        "advert_id": advert_id,
        "product_name": str(product_name or ""),
        "buyer": str(buyer or ""),
        "price": float(price or 0),
        "order_id": str(order_id or ""),
        "ts": int(time.time()),
        "ts_text": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "reason": str(reason or "unbound_advert"),
    }
    _LAST_UNBOUND_WEBHOOK[advert_id] = entry
    while len(_LAST_UNBOUND_WEBHOOK) > 50:
        oldest_key = next(iter(_LAST_UNBOUND_WEBHOOK.keys()), None)
        if oldest_key is None:
            break
        _LAST_UNBOUND_WEBHOOK.pop(oldest_key, None)
    return entry


def notify_unbound_advert(advert_id: str, product_name: str, buyer: str, price, order_id: str, reason: str = "unbound_advert"):
    entry = remember_unbound_webhook(advert_id, product_name, buyer, price, order_id, reason)
    cooldown_key = str(advert_id or "unknown")
    now_ts = int(time.time())
    last_ts = int(_UNBOUND_ADVERT_ALERT_LAST.get(cooldown_key, 0) or 0)
    if last_ts and now_ts - last_ts < UNBOUND_ADVERT_ALERT_COOLDOWN_SECONDS:
        return entry
    _UNBOUND_ADVERT_ALERT_LAST[cooldown_key] = now_ts
    bind_link = f"/admin/bind-service?advert_id={html.escape(str(advert_id or ''))}"
    send_telegram_alert(
        "Baglanmamis Itemsatis ilanindan siparis geldi.\n\n"
        f"Advert ID: {advert_id or '-'}\n"
        f"Urun: {product_name or '-'}\n"
        f"Musteri: {buyer or '-'}\n"
        f"Tutar: {float(price or 0):.2f} TL\n"
        f"Siparis ID: {order_id or '-'}\n"
        f"Baglama linki: {bind_link}\n\n"
        "Otomatik panel siparisi acilmadi."
    )
    return entry


def find_similar_bound_advert_ids(name: str, current_advert_id: str = "") -> list[str]:
    normalized = normalize_text(name or "")
    if not normalized:
        return []
    current_advert_id = str(current_advert_id or "").strip()
    matches = []
    for item in collect_itemsatis_adverts_from_local_state(include_cache=True, include_history=False):
        advert_id = str((item or {}).get("advert_id") or "").strip()
        if not advert_id or advert_id == current_advert_id:
            continue
        bind = get_advert_binding_status(advert_id)
        if bind.get("status") == "missing":
            continue
        item_name = normalize_text((item or {}).get("name") or "")
        if item_name and item_name == normalized:
            matches.append(advert_id)
        if len(matches) >= 5:
            break
    return matches


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
    <form class='grid' method='get' action='/admin/service-search'><select name='panel'>{options}</select><input name='q' value='{html.escape(str(q))}' placeholder='Örn: tiktok views, takipçi, 123'><button>Ara</button></form></div>
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
    bound_title_map = defaultdict(list)
    for bound_item in items:
        bound_advert_id = str((bound_item or {}).get("advert_id", "")).strip()
        if not bound_advert_id:
            continue
        bound_status = get_advert_binding_status(bound_advert_id)
        if bound_status.get("status") == "missing":
            continue
        title_key = normalize_text((bound_item or {}).get("name") or "")
        if title_key:
            bound_title_map[title_key].append(bound_advert_id)
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
        last_unbound = _LAST_UNBOUND_WEBHOOK.get(advert_id) or {}
        unbound_note = ""
        if last_unbound:
            unbound_note = (
                f"<div class='notice warning'>Son kacan siparis: "
                f"{html.escape(str(last_unbound.get('order_id') or '-'))} | "
                f"{html.escape(str(last_unbound.get('buyer') or '-'))} | "
                f"{float(last_unbound.get('price') or 0):.2f} TL | "
                f"{html.escape(str(last_unbound.get('ts_text') or '-'))}</div>"
            )
        similar_ids = [sid for sid in bound_title_map.get(normalize_text(name_raw), []) if sid != advert_id][:5]
        similar_note = ""
        if bind["status"] == "missing" and similar_ids:
            similar_note = f"<div class='notice warning'>Benzer baslikli bagli ilan var: {html.escape(', '.join(similar_ids))}</div>"
        if unbound_note or similar_note:
            source = f"{source}</div>{unbound_note}{similar_note}<div class='muted'>"
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
      <form class='grid' method='get' action='/admin/adverts-bind'><input type='hidden' name='status' value='{html.escape(status)}'><input name='q' value='{html.escape(q)}' placeholder='İlan adı veya ID ara'><button>Filtrele</button></form>
    </div>
    <div class='card'><table class='table'><thead><tr><th>ID</th><th>İlan</th><th>Durum</th><th>Tahmin</th><th>İşlem</th></tr></thead><tbody>{''.join(rows) or '<tr><td>Bu filtrede ilan yok. Önce Itemsatış İlanları sayfasından içe aktar.</td></tr>'}</tbody></table></div>
    """
    return simple_admin_page("İlan Bağlama Sihirbazı", body)


@app.get("/admin/bind-service", response_class=HTMLResponse)
def admin_bind_service_page(advert_id: str, panel: str = "", service_id: str = "", q: str = "", quantity: int = 0, platform: str = "", user: str = Depends(get_current_admin)):
    advert = get_itemsatis_advert_record(advert_id)
    name = str(advert.get("name") or f"Itemsatış İlanı {advert_id}")
    infer = infer_advert_binding_fields(name)
    existing = get_all_services(include_inactive=True).get(str(advert_id), {})
    existing_is_dynamic = (existing or {}).get("source") == "dynamic"
    existing_panel = (existing or {}).get("panel_key") or (existing or {}).get("panel") or ""
    existing_service_id = str((existing or {}).get("service_id") or "")
    existing_quantity = int((existing or {}).get("quantity") or 0)
    existing_platform = str((existing or {}).get("platform") or "")
    panel_key = normalize_panel_key(panel or existing_panel or "medyabayim")
    service_id = str(service_id or existing_service_id or "").strip()
    quantity = int(quantity or existing_quantity or infer.get("quantity") or 1000)
    platform = normalize_text(platform or existing_platform or infer.get("platform") or "other") or "other"
    q = str(q or infer.get("search_query") or "")
    result = search_panel_services(panel_key, q, 80) if q else {"items": []}
    rows = service_search_rows_for_binding(result.get("items", []), advert_id, quantity, platform, "service")
    existing_note = ""
    if existing:
        edit_hint = "Aşağıdaki formdan mevcut bağlantıyı silemeden düzenleyebilirsin." if existing_is_dynamic else "Bu servis kod içi görünüyor; düzenleme kaydedilirse dinamik servis olarak üzerine yazılır."
        existing_note = f"<div class='notice warning'>Bu ilan zaten servise bağlı: {html.escape(str(existing.get('panel')))} / {html.escape(str(existing.get('service_id')))} / {html.escape(str(existing.get('quantity')))}<br>{html.escape(edit_hint)}</div>"
    body = f"""
    <div class='card'><h2>{html.escape(name)}</h2><div class='muted'>İlan ID: <code>{html.escape(str(advert_id))}</code></div>{existing_note}</div>
    <div class='card'><h2>Direkt Servis Bağla / Düzenle</h2><form class='grid' method='post' action='/admin/bind-service/save'>
      <input type='hidden' name='advert_id' value='{html.escape(str(advert_id))}'>
      <select name='panel'>{build_panel_select_options(panel_key)}</select>
      <input name='service_id' value='{html.escape(service_id)}' placeholder='Panel Servis ID' pattern='^\\d+$' required>
      <input type='number' name='quantity' value='{quantity}' min='1' max='1000000' required>
      <select name='platform'>{build_platform_options(platform)}</select>
      <button class='green'>Kaydet</button>
    </form></div>
    <div class='card'><h2>Servis Ara ve Tek Tıkla Bağla</h2><form class='grid' method='get' action='/admin/bind-service'>
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
        previous = DYNAMIC_SERVICES.get(str(advert_id).strip(), {}) if isinstance(DYNAMIC_SERVICES, dict) else {}
        previous_panel = normalize_panel_key((previous or {}).get("panel_key") or (previous or {}).get("panel") or "")
        previous_service_id = str((previous or {}).get("service_id") or "").strip()
        set_dynamic_service(advert_id, panel, service_id, quantity, platform, True)
        advert = get_itemsatis_advert_record(advert_id)
        panel_key = normalize_panel_key(panel)
        service_id_s = str(service_id or "").strip()
        service_ref_changed = previous_panel != panel_key or previous_service_id != service_id_s
        if service_ref_changed:
            if not get_cached_panel_service_name(panel_key, service_id_s):
                panel_service_name = fetch_panel_service_name_by_id(panel_key, service_id_s)
                if panel_service_name:
                    cache_panel_service_name(panel_key, service_id_s, panel_service_name)
            if not _service_price_cache_exists(panel_key, service_id_s):
                prime_service_price_cache(panel_key, service_id_s, str(advert.get("name") or f"Itemsatış ilanı {advert_id}"))
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
    <div class='card'><h2>Servis Ara ve Bileşen Olarak Ekle</h2><form class='grid' method='get' action='/admin/bind-package'>
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
    rows = ""
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
    <div class='card'><div class='muted'>Gerçek sipariş açmadan paket bileşenlerini ve link yakalamayı test eder.</div><form class='grid' method='get' action='/admin/package-test'><select name='advert_id'>{options}</select><input name='link' value='{link}' placeholder='Test linki'><button>Paketi Test Et</button></form></div>{result_html}
    """
    return simple_admin_page("Paket Test", body)


@app.get("/admin/profit-calculator", response_class=HTMLResponse)
def admin_profit_calculator(sale: float = 0, cost: float = 0, user: str = Depends(get_current_admin)):
    result = calculate_profit(sale, cost)
    body = f"""
    <div class='card'><form class='grid' method='get' action='/admin/profit-calculator'><input type='number' step='0.01' name='sale' value='{sale}' placeholder='Satış TL'><input type='number' step='0.01' name='cost' value='{cost}' placeholder='Panel maliyeti TL'><button>Hesapla</button></form></div>
    <div class='card'><h2>Sonuç</h2><p>Brüt satış: <b>{format_tl_amount(result['sale_price'])}</b></p><p>Itemsatış komisyonu: <b>{format_tl_amount(result['commission'])}</b></p><p>Panel maliyeti: <b>{format_tl_amount(result['panel_cost'])}</b></p><p>Net kâr: <b>{format_tl_amount(result['profit'])}</b> · Marj: <b>%{result['margin_pct']}</b></p></div>
    """
    return simple_admin_page("Kâr Hesaplayıcı", body)


@app.get("/admin/balance-history", response_class=HTMLResponse)
def admin_balance_history(user: str = Depends(get_current_admin)):
    body = "<div class='card'><table class='table'><tbody><tr><td>Kayıt yok.</td></tr></tbody></table></div>"
    return simple_admin_page("Panel Bakiye Geçmişi", body)


@app.get("/admin/link-audit", response_class=HTMLResponse)
def admin_link_audit(user: str = Depends(get_current_admin)):
    body = "<div class='card'><table class='table'><tbody><tr><td>Kayıt yok.</td></tr></tbody></table></div>"
    return simple_admin_page("Link Yakalama Geçmişi", body)


@app.get("/admin/failed-actions", response_class=HTMLResponse)
def admin_failed_actions(user: str = Depends(get_current_admin)):
    row_parts = []
    anti_loss_count = 0
    category_classes = {"profit": "bad", "balance": "warn", "link": "warn", "config": "bad", "panel_timeout": "warn", "panel": "warn", "preflight": "warn", "service": "bad"}
    for o in reversed(FAILED_ORDERS[-50:]):
        if not isinstance(o, dict):
            continue
        product_name = html.escape(str(o.get("product_name", "")))
        order_id = html.escape(str(o.get("order_id", "")))
        smm_order_id = html.escape(str(o.get("smm_order_id", "-")))
        panel = html.escape(str(o.get("panel", "-")))
        reason = html.escape(str(o.get("reason", "")))
        link = html.escape(str(o.get("link", "")))
        category = str(o.get("category") or classify_failed_reason(o.get("reason", ""), o.get("detail", "")) or "other")
        if category == "profit":
            anti_loss_count += 1
        category_badge = f"<span class='badge {category_classes.get(category, 'passive')}'>{html.escape(category)}</span>"
        row_parts.append(
            f"<tr><td data-label='Ürün'>{product_name}</td><td data-label='Sipariş'>{order_id}</td>"
            f"<td data-label='SMM'>{smm_order_id}</td><td data-label='Panel'>{panel}</td>"
            f"<td data-label='Kategori'>{category_badge}</td>"
            f"<td data-label='Sebep'>{reason}</td><td data-label='Link'>{link}</td>"
            f"<td data-label='İşlem'><form method='post' action='/admin/failed/mark-completed'>"
            f"<input type='hidden' name='smm_order_id' value='{smm_order_id}'>"
            f"<input type='hidden' name='order_id' value='{order_id}'>"
            f"<button class='green' type='submit'>Tamamlandı İşaretle</button></form></td></tr>"
        )
    rows = "".join(row_parts)
    body = f"<div class='card'><div class='muted'>Başarısız siparişler için hızlı çözüm merkezi.</div><table class='table'><thead><tr><th>Ürün</th><th>Sipariş</th><th>SMM</th><th>Panel</th><th>Sebep</th><th>Link</th><th>İşlem</th></tr></thead><tbody>{rows or '<tr><td>Başarısız sipariş yok.</td></tr>'}</tbody></table></div>"
    if anti_loss_count:
        body = body.replace("<table class='table'>", f"<div class='notice warning'>Anti-loss tarafindan engellenen kayit: {anti_loss_count}. Otomatik retry yapilmaz; fiyat/maliyet kontrol edilmeli.</div><table class='table'>")
    body = body.replace("<th>Panel</th><th>Sebep</th>", "<th>Panel</th><th>Kategori</th><th>Sebep</th>")
    return simple_admin_page("Hatalı Sipariş Çözüm Merkezi", body)


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


@app.get("/robots.txt")
def robots_txt():
    return HTMLResponse("User-agent: *\nDisallow: /\n", media_type="text/plain")


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
    """Pending siparişlerin panel durumunu kontrol eder.
    Tamamlanan/iptal olan/hatalı siparişler pending listesinden çıkarılır.
    Bu fonksiyon hafif status polling içindir; yeni sipariş/retry açmaz.
    """
    completed_indexes = set()
    changed = False
    failed_count = 0
    pending_age = check_pending_order_age_alerts()

    for index, item in list(enumerate(PENDING_ORDERS)):
        if not isinstance(item, dict):
            completed_indexes.add(index)
            changed = True
            continue

        if item.get("cancelled"):
            completed_indexes.add(index)
            changed = True
            continue

        created_at = int(item.get("created_at", 0) or 0)
        if created_at and int(time.time()) - created_at < MIN_PENDING_STATUS_CHECK_DELAY_SECONDS:
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

        status = extract_panel_status(status_data)
        delay_alert_sent = bool(item.get("delay_alert_sent", False))

        if is_failed_panel_status(status_data):
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
                f"Panel durumu: {status or status_data.get('status', '-')}",
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
                f"Durum: {status or status_data.get('status', '-')}\n"
                f"Link: {item.get('link', '')}\n\n"
                f"Admin panelden kontrol et. Otomatik tekrar sipariş verilmedi."
            )
            completed_indexes.add(index)
            changed = True
            continue

        if is_completed_panel_status(status_data):
            log("success", "order_completed", smm_order_id=item.get("smm_order_id"), product=item.get("product_name"), status=status)
            duration_minutes = int((time.time() - int(item.get("created_at", time.time()) or time.time())) / 60)
            manual_order = is_manual_itemsatis_order_id(item.get("itemsatis_order_id", ""))
            completed_text = (
                f"SMM siparişi tamamlandı.\n\n"
                f"Ürün: {item.get('product_name', 'Bilinmiyor')}\n"
                f"Panel: {item.get('panel', 'Bilinmiyor')}\n"
                f"{'Manuel ID' if manual_order else 'Itemsatış ID'}: {item.get('itemsatis_order_id', 'Bilinmiyor')}\n"
                f"SMM ID: {item.get('smm_order_id', 'Bilinmiyor')}\n"
                f"Durum: {status or status_data.get('status', '-')}\n"
                f"Link: {item.get('link', '')}\n\n"
                f"Tamamlanma süresi: {format_duration_minutes(duration_minutes)}"
            )
            if not manual_order:
                notify_customer_order_completed(item.get("itemsatis_order_id", ""), item.get("product_name", ""), item.get("link", ""))
                completed_text += "\nMüşteriye değerlendirme mesajı gönderildi."
            else:
                completed_text += "\nManuel sipariş olduğu için müşteriye Itemsatış mesajı gönderilmedi."
            send_telegram(completed_text)
            completed_indexes.add(index)
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
                    f"Durum: {status or status_data.get('status', '-')}\n"
                    f"Link: {item.get('link', '')}\n\n"
                    f"Geçen süre: {format_duration_minutes(waited_seconds / 60)}\n"
                    f"Paneli kontrol et."
                )
                item["delay_alert_sent"] = True
                changed = True

    for index in sorted(completed_indexes, reverse=True):
        if 0 <= index < len(PENDING_ORDERS):
            PENDING_ORDERS.pop(index)

    if changed:
        save_state()

    return {"ok": True, "pending_count": len(PENDING_ORDERS), "completed_count": len(completed_indexes), "failed_count": failed_count, "pending_age": pending_age}


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
            mark_cache_state_dirty()
            save_cache_state()
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

    if SERVICE_PRICE_CACHE.get(cache_key) != current_rate_raw or f"missing:{cache_key}" in SERVICE_PRICE_CACHE:
        SERVICE_PRICE_CACHE[cache_key] = current_rate_raw
        SERVICE_PRICE_CACHE.pop(f"missing:{cache_key}", None)
        mark_cache_state_dirty()
        save_cache_state()
    return {"ok": True, "rate": current_rate_raw, "service_name": service_name}


@app.head("/check-services")
def check_services_head():
    return {"ok": True, "status": "alive", "endpoint": "check-services"}


@app.get("/check-services")
def check_services():
    global SERVICE_PRICE_CACHE
    changed_count = 0
    missing_count = 0
    initialized_count = 0
    services_data_by_panel = {}

    for service in get_price_check_targets(include_inactive=False):
        if not service.get("api_url") or not service.get("api_key"):
            log("warning", "service_panel_missing", advert_id=service.get("advert_id"), panel=service.get("panel_key"))
            continue

        panel_cache_key = service.get("panel_key") or service.get("panel") or f'{service["api_url"]}|{service["api_key"]}'
        if panel_cache_key not in services_data_by_panel:
            services_data_by_panel[panel_cache_key] = get_panel_services(service["api_url"], service["api_key"], service.get("panel", ""))
        services_data = services_data_by_panel[panel_cache_key]
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
                mark_cache_state_dirty()
                missing_count += 1
            continue

        if missing_key in SERVICE_PRICE_CACHE:
            SERVICE_PRICE_CACHE.pop(missing_key, None)
            mark_cache_state_dirty()
        panel_service_name = get_panel_service_display_name(service, target_service)
        current_rate = str(target_service.get("rate", ""))
        old_rate = SERVICE_PRICE_CACHE.get(cache_key)
        current_rate_norm = normalize_panel_rate(current_rate)
        old_rate_norm = normalize_panel_rate(old_rate)

        if old_rate is None:
            SERVICE_PRICE_CACHE[cache_key] = current_rate
            mark_cache_state_dirty()
            initialized_count += 1
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
            mark_cache_state_dirty()
            changed_count += 1

    if changed_count or missing_count or initialized_count:
        save_cache_state()
    return {"ok": True, "changed_count": changed_count, "missing_count": missing_count, "initialized_count": initialized_count}


def process_itemsatis_webhook_payload(data: dict):
    """Eski Itemsatış webhook işleme mantığı. Worker tarafından thread içinde çağrılır."""
    if not is_itemsatis_purchase_event(data):
        event = get_event(data)
        log("info", "itemsatis_non_order_webhook_ignored", webhook_event=event, order_id=get_order_id(data), advert_id=get_advert_id(data))
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
        queue_id = str((data or {}).get("_queue_id", "") or "")
        payload_fingerprint = make_webhook_payload_fingerprint(data)

        ignored_events = {"review_received", "review_created", "message_created", "question_created", "advert_updated"}
        if event in ignored_events:
            log("info", "webhook_ignored", webhook_event=event)
            return {"ignored": True, "event": event}

        report_product_name = get_itemsatis_report_name(advert_id, product_name)


        log("info", "sale_received", order_id=order_id, product=report_product_name, buyer=buyer, price=price)

        all_packages = get_package_configs()
        if advert_id in all_packages:
            package = all_packages[advert_id]
            package_name = get_package_display_name(advert_id, package, product_name)
            package_platform = normalize_text(package.get("platform", "tiktok")) or "tiktok"
            customer_link, detected_link_platform = find_package_order_link(data, package)

            if not customer_link:
                add_failed_order(order_id, advert_id, package_name, "Paket sipariş linki bulunamadı")
                notify_customer_order_failed(order_id, package_name)
                send_telegram(
                    f"Paket sipariş linki bulunamadı.\n\nSipariş ID: {order_id}\nPaket: {package_name}\nPlatform: {package_platform}\nMüşteri: {buyer}\n\n"
                    f"Bot hiçbir panel siparişi açmadı. Itemsatış müşteri bilgi alanında gerçek sosyal medya linki olduğundan emin ol."
                )
                return {"ok": False, "error": "package_link_not_found"}

            log("info", "package_customer_link_detected", advert_id=advert_id, platform=detected_link_platform, link=customer_link)


            normalized_link = normalize_link_for_check(customer_link, detected_link_platform or package_platform)
            duplicate_link_key = f"package:{advert_id}:{normalized_link}"
            order_keys = build_order_idempotency_keys(order_id, advert_id, buyer, customer_link, detected_link_platform or package_platform, queue_id, payload_fingerprint)

            if has_processed_order(order_keys):
                return {"ignored": True, "reason": "duplicate_package_order"}

            active_pending = find_active_pending_by_link(customer_link, detected_link_platform or package_platform)
            if active_pending:
                add_failed_order(
                    order_id,
                    advert_id,
                    package_name,
                    "Aynı link için aktif pending sipariş var",
                    f"Bu link için önceki sipariş hâlâ pending durumda. Temiz hedef: {normalize_panel_link(customer_link, detected_link_platform or package_platform)}. Önceki sipariş tamamlanmadan yeni panel siparişi geçilmedi.",
                    link=customer_link,
                    panel="package",
                    platform=detected_link_platform or package_platform,
                    retryable=False,
                    existing_pending_order_id=active_pending.get("itemsatis_order_id", ""),
                    existing_smm_order_id=active_pending.get("smm_order_id", ""),
                )
                mark_processed_order(order_keys)
                save_state()
                notify_customer_order_failed(order_id, package_name)
                send_telegram(
                    f"Aynı link için aktif pending sipariş var.\n\n"
                    f"Sipariş ID: {order_id}\nPaket: {package_name}\nLink: {customer_link}\n"
                    f"Mevcut SMM ID: {active_pending.get('smm_order_id', '-')}\n\n"
                    f"Önceki sipariş tamamlanmadan yeni panel siparişi geçilmedi."
                )
                return {"ok": False, "reason": "active_pending_same_link"}

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
                mark_processed_order(order_keys)
                save_state()
                return {"ok": False, "error": "anti_loss_guardrail", "type": "package_order", "guard": anti_loss}

            for component in components:
                component = normalize_package_component(component)
                if not component.get("active", True):
                    continue
                component_name = component.get("name") or "Paket Bileşeni"
                service = get_service_config(component)
                component_label = f"{package_name} - {component_name}"
                component_link = normalize_panel_link(customer_link, service.get("platform", detected_link_platform or package_platform))

                preflight = validate_service_order_preflight(service, component_link, component_label)
                if not preflight.get("ok"):
                    failed_rows.append((component_name, service.get("panel", "Panel"), preflight.get("detail", "Ön kontrol hatası")))
                    add_preflight_failed_order(order_id, advert_id, component_label, service, preflight, component_link or customer_link)
                    continue
                component_link = preflight.get("link") or component_link

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
                    add_failed_order(
                        order_id,
                        advert_id,
                        component_label,
                        "Panel order ID eksik",
                        error_text,
                        link=customer_link,
                        panel=service.get("panel", ""),
                        service_id=service.get("service_id", ""),
                        retryable=False,
                        manual_check_required=True,
                        uncertain_panel_response=True,
                        panel_response=sanitize_panel_response(smm_result),
                    )
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
                success_rows.append({
                    "name": component_name,
                    "panel": service.get("panel", "Panel"),
                    "smm_order_id": smm_order_id,
                    "cost_tl": estimated_cost,
                    "balance_before_tl": current_balance_tl,
                    "balance_after_tl": (current_balance_tl - estimated_cost) if current_balance_tl is not None and estimated_cost is not None else None,
                })

            if success_rows:
                PROCESSED_LINKS.add(duplicate_link_key)
                mark_processed_order(order_keys)
                save_state()
                notify_customer_order_started(order_id, package_name, customer_link)

            success_lines = []
            for row in success_rows:
                cost_text = format_optional_tl(row.get("cost_tl"))
                before_text = format_optional_tl(row.get("balance_before_tl"))
                after_text = format_optional_tl(row.get("balance_after_tl"))
                success_lines.append(
                    f"✅ {row.get('name')} | {row.get('panel')} | SMM ID: {row.get('smm_order_id')} | "
                    f"Maliyet: {cost_text} | Bakiye: {before_text} → {after_text}"
                )
            success_text = "\n".join(success_lines) or "Yok"
            failed_text = "\n".join([f"❌ {name} | {panel} | {err}" for name, panel, err in failed_rows]) or "Yok"
            successful_costs = [row.get("cost_tl") for row in success_rows if row.get("cost_tl") is not None]
            package_cost = round(sum(float(v) for v in successful_costs), 4) if successful_costs else estimate_package_cost_tl(components)
            send_telegram(
                f"Paket sipariş geldi ve panele girildi.\n\nPaket: {package_name}\nItemsatış ID: {order_id}\nLink: {customer_link}\n\n"
                f"Başarılı:\n{success_text}\n\nHatalı:\n{failed_text}\n\n"
                f"{build_finance_summary(price, package_cost)}"
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

            normalized_link = normalize_link_for_check(customer_link, platform)
            duplicate_link_key = f"{advert_id}:{normalized_link}"
            order_keys = build_order_idempotency_keys(order_id, advert_id, buyer, customer_link, platform, queue_id, payload_fingerprint)

            if has_processed_order(order_keys):
                return {"ignored": True, "reason": "duplicate_order"}

            active_pending = find_active_pending_by_link(customer_link, platform)
            if active_pending:
                add_failed_order(
                    order_id,
                    advert_id,
                    service_name,
                    "Aynı link için aktif pending sipariş var",
                    f"Bu link için önceki sipariş hâlâ pending durumda. Temiz hedef: {normalize_panel_link(customer_link, platform)}. Önceki sipariş tamamlanmadan yeni panel siparişi geçilmedi.",
                    link=customer_link,
                    panel=service.get("panel", ""),
                    panel_key=service.get("panel_key", ""),
                    service_id=service.get("service_id", ""),
                    quantity=service.get("quantity", ""),
                    platform=platform,
                    retryable=False,
                    existing_pending_order_id=active_pending.get("itemsatis_order_id", ""),
                    existing_smm_order_id=active_pending.get("smm_order_id", ""),
                )
                mark_processed_order(order_keys)
                save_state()
                notify_customer_order_failed(order_id, service_name)
                send_telegram(
                    f"Aynı link için aktif pending sipariş var.\n\n"
                    f"Sipariş ID: {order_id}\nÜrün: {service_name}\nLink: {customer_link}\n"
                    f"Mevcut SMM ID: {active_pending.get('smm_order_id', '-')}\n\n"
                    f"Önceki sipariş tamamlanmadan yeni panel siparişi geçilmedi."
                )
                return {"ok": False, "reason": "active_pending_same_link"}

            preflight = validate_service_order_preflight(service, customer_link, service_name)
            if not preflight.get("ok"):
                add_preflight_failed_order(order_id, advert_id, service_name, service, preflight, customer_link)
                notify_customer_order_failed(order_id, service_name)
                send_telegram(
                    f"Sipariş ön kontrol hatası.\n\n"
                    f"Sipariş ID: {order_id}\n"
                    f"Ürün: {service_name}\n"
                    f"Panel: {service.get('panel', '-')}\n"
                    f"Sebep: {preflight.get('detail', preflight.get('code', '-'))}\n\n"
                    f"Panel siparişi açılmadı."
                )
                return {"ok": False, "error": "preflight_failed", "reason_code": preflight.get("code")}
            customer_link = preflight.get("link") or customer_link

            if not service.get("api_url") or not service.get("api_key"):
                add_failed_order(order_id, advert_id, service_name, "Panel bilgileri eksik", service.get("panel_key", ""))
                send_telegram(f"Panel bilgileri eksik.\n\nSipariş ID: {order_id}\nÜrün: {service_name}\nPanel: {service['panel']}\n\nRender Environment ayarlarını kontrol et.")
                return {"ok": False, "error": "panel_config_missing"}

            anti_loss = check_anti_loss_guardrail_for_services([service], price, f"Itemsatış ilanı {advert_id}")
            if not anti_loss.get("ok"):
                add_failed_order(order_id, advert_id, service_name, "Zararına satış engellendi", json.dumps(anti_loss, ensure_ascii=False)[:500], link=customer_link, panel=service.get("panel", ""), retryable=False)
                send_telegram(format_anti_loss_message("Dikkat: Zararına satış engellendi.", service_name, order_id, anti_loss))
                mark_processed_order(order_keys)
                save_state()
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
                add_failed_order(
                    order_id,
                    advert_id,
                    service_name,
                    "Panel order ID eksik",
                    str(smm_result)[:500],
                    link=customer_link,
                    panel=service.get("panel", ""),
                    service_id=service.get("service_id", ""),
                    retryable=False,
                    manual_check_required=True,
                    uncertain_panel_response=True,
                    panel_response=sanitize_panel_response(smm_result),
                )
                notify_customer_order_failed(order_id, service_name)
                send_telegram(
                    f"Panel siparişi belirsiz cevap verdi.\n\n"
                    f"Sipariş ID: {order_id}\nÜrün: {service_name}\nPanel: {service.get('panel', '')}\n"
                    f"Panel order ID dönmediği için bot pending'e eklemedi. Panelden manuel kontrol gerekli."
                )
                return {"ok": False, "error": "panel_order_id_missing", "manual_check_required": True}

            PROCESSED_LINKS.add(duplicate_link_key)
            mark_processed_order(order_keys)
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

            # YENİ: Müşteriye sipariş başladı bildirimi
            notify_customer_order_started(order_id, service_name, customer_link)

            estimated_cost = estimate_order_cost_from_service(service)
            current_balance_tl = convert_balance_to_try(balance, currency)
            balance_text = format_order_balance_line(current_balance_tl, estimated_cost)
            send_telegram(
                f"Sipariş geldi ve panele girildi.\n\nÜrün: {service_name}\nPanel: {service['panel']}\n"
                f"Itemsatış ID: {order_id}\nSMM ID: {smm_order_id}\nLink: {customer_link}\n"
                f"Adet: {service['quantity']}\n{balance_text}\n\n"
                f"{build_finance_summary(price, estimated_cost)}"
            )

            return {"ok": True, "type": "smm_order", "smm_order_id": smm_order_id}

        log("info", "webhook_unmatched", advert_id=advert_id, product=product_name)
        notify_unbound_advert(advert_id, report_product_name, buyer, price, order_id, "unbound_advert")
        return {"ignored": True, "product": product_name, "advert_id": advert_id, "reason": "unbound_advert"}

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
        log("info", "webhook_ignored_before_queue", webhook_event=event, advert_id=get_advert_id(data), order_id=get_order_id(data), reason="non_order_webhook")
        return {"ok": True, "ignored": True, "event": event, "reason": "non_order_webhook"}

    ignored_events = {"review_received", "review_created", "message_created", "question_created", "advert_updated"}
    if event in ignored_events:
        log("info", "webhook_ignored_before_queue", webhook_event=event)
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
        send_telegram("""Bot komutları:

/panels - Ekli panelleri göster
/balance - Tüm panel bakiyeleri
/balance paneladi - Seçili panel bakiyesi
/balance-all - Tüm panel bakiyeleri
/check-balances - Bakiye alarm check-up
/medyabalance - MedyaBayim bakiyesi
/status - Bot durumu
/health - Sistem durumu
/failed - Başarısız siparişler
/pending - Bekleyen siparişler
/services - Servis eşleştirmeleri
/admin - Web servis yönetim paneli
/cancel smm_id - Siparişi iptal et
/help - Komutları gösterir""")
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
        result = check_all_panel_balances(force_alert=False)
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


    send_telegram("Bilinmeyen komut. /help ile komutları gör.")
    return {"ok": True}
