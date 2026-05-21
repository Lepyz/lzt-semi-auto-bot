import os
import re
import json
import time
import hashlib
import asyncio
import secrets
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

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

# ─── YENİ: LOG GEÇMİŞİ (son 200 log dashboard için) ───────────────────────────
LOG_HISTORY = []
MAX_LOG_HISTORY = 200

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}


def now_tr():
    return datetime.utcnow() + timedelta(hours=3)


# ─── YENİ: GELİŞMİŞ LOGLAMA ──────────────────────────────────────────────────
def log(level: str, event: str, **kwargs):
    """
    Hem structlog ile JSON log yazar hem de dashboard için hafızada tutar.
    level: info | warning | error | success
    """
    entry = {
        "ts": now_tr().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "event": event,
        **kwargs,
    }

    # Structlog
    log_fn = getattr(logger, level if level != "success" else "info", logger.info)
    log_fn(event, **kwargs)

    # Dashboard geçmişi
    LOG_HISTORY.append(entry)
    if len(LOG_HISTORY) > MAX_LOG_HISTORY:
        LOG_HISTORY.pop(0)

    # Redis'e de kaydet (son 200)
    redis_set_json("log_history", LOG_HISTORY[-MAX_LOG_HISTORY:])


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
                "parse_mode": "HTML",
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
    if not ITEMSATIS_API_KEY:
        log("warning", "customer_notify_skip", reason="ITEMSATIS_API_KEY eksik", order_id=order_id)
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
        f"Takipçiler genellikle 0-24 saat içinde gelmeye başlar. "
        f"Herhangi bir sorun olursa bize ulaşabilirsiniz. Teşekkürler! 🙏"
    )
    return send_itemsatis_message(order_id, message)


def notify_customer_order_completed(order_id: str, product_name: str, link: str):
    """Sipariş tamamlanınca müşteriye bildirim gönder."""
    message = (
        f"Merhaba! '{product_name}' siparişiniz tamamlandı! 🎉\n\n"
        f"Hesabınız: {link}\n\n"
        f"Memnun kaldıysanız değerlendirme bırakırsanız çok seviniriz. "
        f"Tekrar alışveriş için görüşmek üzere! 😊"
    )
    return send_itemsatis_message(order_id, message)


def notify_customer_order_failed(order_id: str, product_name: str):
    """Sipariş başarısız olunca müşteriye bildirim gönder."""
    message = (
        f"Merhaba! '{product_name}' siparişinizde teknik bir sorun yaşandı. "
        f"En kısa sürede çözüp siparişinizi işleme alacağız. "
        f"Rahatsızlık için özür dileriz. 🙏"
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
        log("error", "redis_error", error=str(e))
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


def load_state():
    global PROCESSED_ORDERS, PROCESSED_LINKS, FAILED_ORDERS, PENDING_ORDERS
    global DAILY_STATS, LAST_DAILY_REPORT_DATE, SERVICE_PRICE_CACHE
    global WEEKLY_STATS, MONTHLY_STATS, LAST_WEEKLY_REPORT_DATE, LAST_MONTHLY_REPORT_DATE
    global RECORDED_SALES, LOG_HISTORY, PRODUCT_NAME_CACHE, PANEL_SERVICE_NAME_CACHE, DYNAMIC_SERVICES

    RECORDED_SALES = set(redis_get_json("recorded_sales", []))
    PROCESSED_ORDERS = set(redis_get_json("processed_orders", []))
    PROCESSED_LINKS = set(redis_get_json("processed_links", []))
    FAILED_ORDERS = redis_get_json("failed_orders", [])
    PENDING_ORDERS = redis_get_json("pending_orders", [])
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

    log("info", "state_loaded", pending=len(PENDING_ORDERS), failed=len(FAILED_ORDERS))


def save_state():
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


def add_failed_order(order_id, advert_id, product_name, reason, detail=""):
    entry = {
        "order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "reason": str(reason),
        "detail": str(detail),
        "created_at": int(time.time()),
    }
    FAILED_ORDERS.append(entry)
    if len(FAILED_ORDERS) > 20:
        FAILED_ORDERS.pop(0)
    log("error", "order_failed", order_id=order_id, reason=reason, product=product_name)
    save_state()


def get_order_price(data: dict) -> float:
    value = get_nested(
        data,
        "price", "total", "amount", "total_price", "order_price",
        "details.price", "details.total", "details.amount",
        "data.price", "data.total", "data.amount",
        "payment.price", "payment.total", "payment.amount",
    )
    try:
        clean_value = str(value or "0")
        clean_value = clean_value.replace("TL", "").replace("₺", "").replace("TRY", "")
        clean_value = clean_value.replace(" ", "").replace(",", ".").strip()
        return float(clean_value)
    except Exception:
        return 0.0


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


def add_daily_stat(product_name: str, price: float = 0):
    global DAILY_STATS, WEEKLY_STATS, MONTHLY_STATS
    product_name = str(product_name or "Bilinmeyen Ürün").strip() or "Bilinmeyen Ürün"

    def add_to(stats):
        stats[product_name] = normalize_stat_item(stats.get(product_name, {}))
        stats[product_name]["count"] += 1
        stats[product_name]["gross"] += float(price or 0)

    add_to(DAILY_STATS)
    add_to(WEEKLY_STATS)
    add_to(MONTHLY_STATS)
    save_state()


def record_itemsatis_sale(data, order_id, advert_id, buyer, product_name, price, link="") -> bool:
    global RECORDED_SALES
    sale_key = make_sale_key(data, order_id, advert_id, buyer, product_name, price, link)
    if sale_key in RECORDED_SALES:
        return False
    add_daily_stat(product_name, price)
    RECORDED_SALES.add(sale_key)
    save_state()
    return True


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
    global DAILY_STATS, WEEKLY_STATS, MONTHLY_STATS, RECORDED_SALES
    scope = str(scope or "daily").lower().strip()
    if scope == "daily":
        DAILY_STATS = {}
    elif scope == "weekly":
        WEEKLY_STATS = {}
    elif scope == "monthly":
        MONTHLY_STATS = {}
    elif scope == "all":
        DAILY_STATS = {}
        WEEKLY_STATS = {}
        MONTHLY_STATS = {}
        RECORDED_SALES = set()
    else:
        return False
    save_state()
    return True


def add_pending_order(order_id, advert_id, product_name, panel, api_url, api_key, smm_order_id, link):
    if not smm_order_id or str(smm_order_id) == "Bilinmiyor":
        return
    if any(str(item.get("smm_order_id")) == str(smm_order_id) for item in PENDING_ORDERS):
        return
    PENDING_ORDERS.append({
        "itemsatis_order_id": str(order_id),
        "advert_id": str(advert_id),
        "product_name": str(product_name),
        "panel": str(panel),
        "api_url": str(api_url),
        "api_key": str(api_key),
        "smm_order_id": str(smm_order_id),
        "link": str(link),
        "created_at": int(time.time()),
        "delay_alert_sent": False,
        "cancelled": False,  # YENİ
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


def get_event(data: dict) -> str:
    return normalize_text(get_nested(data, "event", "type", "action", "details.event", "data.event"))


def get_order_id(data: dict) -> str:
    return str(get_nested(data, "order_id", "id", "purchaseId", "purchase_id",
                          "data.order_id", "data.id", "details.order_id") or "Bilinmiyor")


def get_advert_id(data: dict) -> str:
    return str(get_nested(data, "advert.id", "details.advert.id", "data.advert.id",
                          "advert_id", "details.advert_id", "data.advert_id") or "")


def get_product_name(data: dict) -> str:
    """Itemsatış ilan adını mümkün olan tüm alanlardan yakalar."""
    value = get_nested(
        data,
        "product_name", "product", "product.title", "product.name",
        "title", "name",
        "advert.title", "advert.name", "advert.subject",
        "details.advert.title", "details.advert.name", "details.advert.subject",
        "data.advert.title", "data.advert.name", "data.advert.subject",
        "details.product_name", "details.product", "details.product.title", "details.product.name",
        "data.product_name", "data.product", "data.product.title", "data.product.name",
        "order.product_name", "order.product", "order.advert.title", "order.advert.name",
        "purchase.product_name", "purchase.product", "purchase.advert.title", "purchase.advert.name",
    )

    if isinstance(value, dict):
        value = value.get("title") or value.get("name") or value.get("subject") or ""

    return str(value or "").strip()


def cache_itemsatis_product_name(advert_id: str, product_name: str):
    """Webhook ile gelen ilan adını kaydeder; raporlarda Itemsatış ilan adı kullanılmasını sağlar."""
    global PRODUCT_NAME_CACHE
    advert_id = str(advert_id or "").strip()
    product_name = str(product_name or "").strip()
    if advert_id and product_name:
        PRODUCT_NAME_CACHE[advert_id] = product_name
        redis_set_json("product_name_cache", PRODUCT_NAME_CACHE)
    redis_set_json("panel_service_name_cache", PANEL_SERVICE_NAME_CACHE)
    redis_set_json("dynamic_services", DYNAMIC_SERVICES)


def get_itemsatis_report_name(advert_id: str, product_name: str = "") -> str:
    """Günlük/haftalık/aylık rapor için sadece Itemsatış ilan adını önceliklendirir."""
    product_name = str(product_name or "").strip()
    if product_name:
        cache_itemsatis_product_name(advert_id, product_name)
        return product_name

    cached_name = str(PRODUCT_NAME_CACHE.get(str(advert_id or ""), "")).strip()
    if cached_name:
        return cached_name

    if str(advert_id or "") == CS2_ADVERT_ID:
        return "CS2 5 Yıllık Hesap"

    if advert_id:
        return f"Itemsatış İlanı {advert_id}"

    return "Bilinmeyen Ürün"


def get_buyer(data: dict) -> str:
    buyer = get_nested(data, "buyer", "buyer.username", "username", "customer",
                       "customer.username", "details.customer.username", "data.customer.username")
    if isinstance(buyer, dict):
        return str(buyer.get("username") or buyer.get("name") or buyer.get("id") or "Bilinmiyor")
    return str(buyer or "Bilinmiyor")


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
    redis_set_json("dynamic_services", DYNAMIC_SERVICES)


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

    service_id = str(service_id or "").strip()
    if not service_id:
        raise ValueError("Panel servis ID boş olamaz")

    quantity = int(quantity or 0)
    if quantity <= 0:
        raise ValueError("Adet 0'dan büyük olmalı")

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


def build_all_panel_balances_text() -> str:
    lines = ["Panel Bakiyeleri:\n"]
    for key in PANEL_MAP.keys():
        panel = get_panel_config(key)
        if not is_panel_configured(key):
            lines.append(f"{panel['name']}: Eksik env")
            continue
        balance_data = panel_balance(panel["api_url"], panel["api_key"])
        if "error" in balance_data:
            lines.append(f"{panel['name']}: Hatalı - {balance_data.get('error')}")
        else:
            lines.append(f"{panel['name']}: {balance_data.get('balance', 'Bilinmiyor')} {balance_data.get('currency', '')}")
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

    send_telegram(
        f"{panel['name']} Bakiyesi:\n\n"
        f"Bakiye: {balance_data.get('balance', 'Bilinmiyor')} {balance_data.get('currency', '')}"
    )


def panel_balance(api_url, api_key):
    if not api_url or not api_key:
        return {"error": "API URL veya API KEY eksik"}
    try:
        r = requests.post(api_url, data={"key": api_key, "action": "balance"}, headers=HEADERS, timeout=30)
        try:
            return r.json()
        except Exception:
            return {"error": "Panel JSON cevap vermedi", "raw": r.text[:300]}
    except Exception as e:
        return {"error": str(e)}


def create_panel_order(api_url, api_key, service_id, link, quantity):
    if not api_url or not api_key:
        return {"error": "API URL veya API KEY eksik"}
    try:
        r = requests.post(api_url, data={"key": api_key, "action": "add", "service": service_id,
                                          "link": link, "quantity": quantity}, headers=HEADERS, timeout=30)
        try:
            return r.json()
        except Exception:
            return {"error": "Panel JSON cevap vermedi", "raw": r.text[:300]}
    except Exception as e:
        return {"error": str(e)}


def check_panel_order_status(api_url, api_key, order_id):
    if not api_url or not api_key or not order_id:
        return {"error": "Status için bilgi eksik"}
    try:
        r = requests.post(api_url, data={"key": api_key, "action": "status", "order": order_id},
                          headers=HEADERS, timeout=30)
        try:
            return r.json()
        except Exception:
            return {"error": "Status JSON cevap vermedi", "raw": r.text[:300]}
    except Exception as e:
        return {"error": str(e)}


def get_panel_services(api_url, api_key):
    if not api_url or not api_key:
        return {"error": "API URL veya API KEY eksik"}
    try:
        r = requests.post(api_url, data={"key": api_key, "action": "services"}, headers=HEADERS, timeout=30)
        try:
            return r.json()
        except Exception:
            return {"error": "Services JSON cevap vermedi", "raw": r.text[:300]}
    except Exception as e:
        return {"error": str(e)}


def check_low_balance(balance, currency, panel_name="Panel"):
    try:
        numeric_balance = float(balance)
        balance_tl = numeric_balance * 39 if str(currency).upper() == "USD" else numeric_balance
        if balance_tl <= 100:
            log("warning", "low_balance", panel=panel_name, balance=balance, currency=currency)
            send_telegram(f"{panel_name} bakiyesi 100 TL altına düştü.\n\nKalan: {balance} {currency}\n\nLütfen kontrol et.")
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
    asyncio.create_task(background_scheduler())


load_state()



# ─── ADMIN SERVİS YÖNETİM PANELİ ──────────────────────────────────────────────
def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if ADMIN_PASSWORD == "changeme":
        log("warning", "admin_default_password")
    correct_password = secrets.compare_digest(credentials.password or "", ADMIN_PASSWORD)
    if not correct_password:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


ADMIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera SMM Admin</title>
<style>
body { font-family: Arial, sans-serif; background:#0a0a0f; color:#e2e8f0; margin:0; padding:24px; }
.container { max-width:1100px; margin:auto; background:#111118; border:1px solid #1e1e2e; border-radius:14px; padding:24px; }
h1 { margin:0 0 6px; color:#fff; } .muted { color:#8a8fa3; font-size:13px; margin-bottom:22px; }
form.grid { display:grid; grid-template-columns: repeat(6, 1fr); gap:10px; margin-bottom:22px; }
input, select, button { padding:11px; border-radius:8px; border:1px solid #2a2a3a; background:#181824; color:#e2e8f0; }
button { background:#7c3aed; border:none; cursor:pointer; font-weight:700; }
button.delete { background:#ef4444; } button.toggle { background:#334155; }
table { width:100%; border-collapse:collapse; overflow:hidden; border-radius:10px; }
th, td { padding:12px; border-bottom:1px solid #242436; text-align:left; font-size:14px; }
th { background:#181824; color:#a8adbd; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
.badge { padding:4px 8px; border-radius:99px; font-size:12px; font-weight:700; }
.active { background:#064e3b; color:#86efac; } .passive { background:#3f1d1d; color:#fca5a5; }
a { color:#a78bfa; text-decoration:none; } .actions form { display:inline; }
.notice { background:#172554; color:#bfdbfe; padding:10px 12px; border-radius:8px; margin-bottom:14px; font-size:13px; }
@media (max-width: 900px) { form.grid { grid-template-columns: 1fr; } table { font-size:12px; } }
</style>
</head>
<body>
<div class="container">
<h1>Boostera SMM Admin</h1>
<div class="muted">API key girilmez. API keyler Render Environment içinde kalır. Buradan sadece Itemsatış ilanını panel servisine bağlarsın.</div>
<div class="notice">Yeni servis ekleme: Itemsatış İlan ID + Panel + Panel Servis ID + Adet + Platform.</div>
<form class="grid" method="post" action="/admin/add-service">
  <input name="advert_id" placeholder="Itemsatış İlan ID" required>
  <select name="panel" required>
    {% for key, panel in panels.items() %}
      <option value="{{ key }}">{{ panel.name }} ({{ key }})</option>
    {% endfor %}
  </select>
  <input name="service_id" placeholder="Panel Servis ID" required>
  <input name="quantity" type="number" min="1" placeholder="Adet" required>
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
<table>
<thead><tr><th>İlan ID</th><th>Panel</th><th>Servis ID</th><th>Adet</th><th>Platform</th><th>Durum</th><th>Kaynak</th><th>İşlem</th></tr></thead>
<tbody>
{% for advert_id, service in services.items() %}
<tr>
<td>{{ advert_id }}</td>
<td>{{ service.panel }}</td>
<td>{{ service.service_id }}</td>
<td>{{ service.quantity }}</td>
<td>{{ service.platform }}</td>
<td><span class="badge {{ 'active' if service.active else 'passive' }}">{{ 'Aktif' if service.active else 'Pasif' }}</span></td>
<td>{{ service.source }}</td>
<td class="actions">
  {% if service.source == 'dynamic' %}
  <form method="post" action="/admin/toggle-service"><input type="hidden" name="advert_id" value="{{ advert_id }}"><button class="toggle" type="submit">Aktif/Pasif</button></form>
  <form method="post" action="/admin/delete-service" onsubmit="return confirm('Silinsin mi?')"><input type="hidden" name="advert_id" value="{{ advert_id }}"><button class="delete" type="submit">Sil</button></form>
  {% else %}
  Kod içi servis
  {% endif %}
</td>
</tr>
{% else %}
<tr><td colspan="8" style="text-align:center;color:#8a8fa3;">Servis yok.</td></tr>
{% endfor %}
</tbody>
</table>
<p style="margin-top:18px"><a href="/">Dashboard'a dön</a></p>
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
        services[advert_id] = {
            "panel": service.get("panel"),
            "service_id": service.get("service_id"),
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
    delete_dynamic_service(advert_id)
    log("warning", "admin_service_deleted", advert_id=advert_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/toggle-service")
def admin_toggle_service(advert_id: str = Form(...), user: str = Depends(get_current_admin)):
    toggle_dynamic_service(advert_id)
    log("info", "admin_service_toggled", advert_id=advert_id)
    return RedirectResponse("/admin", status_code=303)


# ─── DASHBOARD HTML ───────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Boostera SMM Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap');

  :root {
    --bg: #0a0a0f;
    --surface: #111118;
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
    background: var(--bg);
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
    background: rgba(17,17,24,0.8);
    backdrop-filter: blur(12px);
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .logo {
    font-size: 20px;
    font-weight: 800;
    letter-spacing: -0.5px;
  }

  .logo span { color: var(--accent); }

  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 8px var(--success);
    animation: pulse 2s infinite;
    display: inline-block;
    margin-right: 8px;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .container { max-width: 1400px; margin: 0 auto; padding: 32px; }

  .grid-4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 28px;
  }

  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 28px;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }

  .stat-card {
    position: relative;
    overflow: hidden;
  }

  .stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent);
  }

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

  .stat-value {
    font-size: 32px;
    font-weight: 800;
    letter-spacing: -1px;
  }

  .stat-sub {
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
    font-family: 'JetBrains Mono', monospace;
  }

  .card-title {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }

  .log-list {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    max-height: 380px;
    overflow-y: auto;
  }

  .log-list::-webkit-scrollbar { width: 4px; }
  .log-list::-webkit-scrollbar-track { background: transparent; }
  .log-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .log-entry {
    display: flex;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    align-items: flex-start;
  }

  .log-ts { color: var(--muted); flex-shrink: 0; font-size: 11px; }

  .log-level {
    flex-shrink: 0;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 600;
    text-transform: uppercase;
  }

  .log-level.info { background: rgba(124,58,237,0.2); color: var(--accent); }
  .log-level.success { background: rgba(16,185,129,0.2); color: var(--success); }
  .log-level.warning { background: rgba(245,158,11,0.2); color: var(--warning); }
  .log-level.error { background: rgba(239,68,68,0.2); color: var(--danger); }

  .log-event { color: var(--text); flex: 1; }
  .log-meta { color: var(--muted); font-size: 11px; word-break: break-all; }

  .order-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    font-size: 13px;
  }

  .order-row:last-child { border-bottom: none; }

  .badge {
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 20px;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
  }

  .badge.pending { background: rgba(245,158,11,0.15); color: var(--warning); }
  .badge.failed { background: rgba(239,68,68,0.15); color: var(--danger); }
  .badge.ok { background: rgba(16,185,129,0.15); color: var(--success); }

  .refresh-btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 8px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    transition: all 0.2s;
  }

  .refresh-btn:hover {
    border-color: var(--accent);
    color: var(--accent);
  }

  .empty { color: var(--muted); font-size: 13px; text-align: center; padding: 24px; }

  .order-detail { font-size: 11px; color: var(--muted); font-family: 'JetBrains Mono', monospace; }

  .last-updated {
    font-size: 11px;
    color: var(--muted);
    font-family: 'JetBrains Mono', monospace;
  }
</style>
</head>
<body>

<header>
  <div class="logo">Boostera <span>SMM</span></div>
  <div style="display:flex;align-items:center;gap:16px">
    <span class="last-updated" id="lastUpdated">—</span>
    <button class="refresh-btn" onclick="loadAll()">↻ Yenile</button>
  </div>
</header>

<div class="container">

  <!-- İSTATİSTİK KARTLARI -->
  <div class="grid-4" id="statsGrid">
    <div class="card stat-card success">
      <div class="stat-label">Bugün Sipariş</div>
      <div class="stat-value" id="todayCount">—</div>
    </div>
    <div class="card stat-card cyan">
      <div class="stat-label">Bekleyen</div>
      <div class="stat-value" id="pendingCount">—</div>
    </div>
    <div class="card stat-card danger">
      <div class="stat-label">Başarısız</div>
      <div class="stat-value" id="failedCount">—</div>
    </div>
    <div class="card stat-card warning">
      <div class="stat-label">Bugün Brüt</div>
      <div class="stat-value" id="todayGross">—</div>
      <div class="stat-sub" id="todayNet">net —</div>
    </div>
  </div>

  <!-- BEKLEYEN + BAŞARISIZ -->
  <div class="grid-2">
    <div class="card">
      <div class="card-title">Bekleyen Siparişler</div>
      <div id="pendingList"><div class="empty">Yükleniyor...</div></div>
    </div>
    <div class="card">
      <div class="card-title">Son Başarısız Siparişler</div>
      <div id="failedList"><div class="empty">Yükleniyor...</div></div>
    </div>
  </div>

  <!-- LOG GEÇMİŞİ -->
  <div class="card">
    <div class="card-title" style="display:flex;justify-content:space-between">
      <span>Canlı Log</span>
      <span id="logCount" style="color:var(--muted);font-size:11px"></span>
    </div>
    <div class="log-list" id="logList"><div class="empty">Yükleniyor...</div></div>
  </div>

</div>

<script>
async function loadAll() {
  document.getElementById('lastUpdated').textContent = 'Güncelleniyor...';
  await Promise.all([loadStats(), loadPending(), loadFailed(), loadLogs()]);
  const now = new Date().toLocaleTimeString('tr-TR');
  document.getElementById('lastUpdated').textContent = `Son güncelleme: ${now}`;
}

async function loadStats() {
  const r = await fetch('/api/stats');
  const d = await r.json();
  document.getElementById('todayCount').textContent = d.today_count;
  document.getElementById('pendingCount').textContent = d.pending_count;
  document.getElementById('failedCount').textContent = d.failed_count;
  document.getElementById('todayGross').textContent = d.today_gross.toFixed(0) + ' ₺';
  document.getElementById('todayNet').textContent = 'net ' + d.today_net.toFixed(0) + ' ₺';
}

async function loadPending() {
  const r = await fetch('/api/pending');
  const d = await r.json();
  const el = document.getElementById('pendingList');
  if (!d.orders.length) { el.innerHTML = '<div class="empty">Bekleyen sipariş yok</div>'; return; }
  el.innerHTML = d.orders.map(o => {
    const mins = Math.floor((Date.now()/1000 - o.created_at) / 60);
    return `<div class="order-row">
      <div>
        <div>${o.product_name}</div>
        <div class="order-detail">${o.link} · ${o.panel} #${o.smm_order_id}</div>
      </div>
      <span class="badge pending">${mins}dk</span>
    </div>`;
  }).join('');
}

async function loadFailed() {
  const r = await fetch('/api/failed');
  const d = await r.json();
  const el = document.getElementById('failedList');
  if (!d.orders.length) { el.innerHTML = '<div class="empty">Başarısız sipariş yok</div>'; return; }
  el.innerHTML = d.orders.slice(-8).reverse().map(o => `
    <div class="order-row">
      <div>
        <div>${o.product_name}</div>
        <div class="order-detail">${o.reason}</div>
      </div>
      <span class="badge failed">hata</span>
    </div>`).join('');
}

async function loadLogs() {
  const r = await fetch('/api/logs');
  const d = await r.json();
  document.getElementById('logCount').textContent = `${d.logs.length} kayıt`;
  const el = document.getElementById('logList');
  if (!d.logs.length) { el.innerHTML = '<div class="empty">Log yok</div>'; return; }
  el.innerHTML = [...d.logs].reverse().map(l => {
    const meta = Object.entries(l)
      .filter(([k]) => !['ts','level','event'].includes(k))
      .map(([k,v]) => `${k}=${v}`).join(' ');
    return `<div class="log-entry">
      <span class="log-ts">${l.ts.slice(11,19)}</span>
      <span class="log-level ${l.level}">${l.level}</span>
      <span class="log-event">${l.event} <span class="log-meta">${meta}</span></span>
    </div>`;
  }).join('');
}

loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>
"""


# ─── API ENDPOINTS ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@app.get("/api/stats")
def api_stats():
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


@app.get("/api/pending")
def api_pending():
    return {"orders": PENDING_ORDERS}


@app.get("/api/failed")
def api_failed():
    return {"orders": FAILED_ORDERS}


@app.get("/api/logs")
def api_logs():
    return {"logs": LOG_HISTORY}


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

    for index, item in enumerate(PENDING_ORDERS):
        if item.get("cancelled"):
            completed_indexes.append(index)
            changed = True
            continue

        status_data = check_panel_order_status(item["api_url"], item["api_key"], item["smm_order_id"])

        if "error" in status_data:
            log("error", "status_check_error", smm_order_id=item["smm_order_id"], error=status_data)
            continue

        status = str(status_data.get("status", "")).lower()
        created_at = int(item.get("created_at", 0))
        delay_alert_sent = bool(item.get("delay_alert_sent", False))

        if created_at and not delay_alert_sent:
            waited_seconds = int(time.time()) - created_at
            if waited_seconds >= 5400:
                log("warning", "order_delayed", smm_order_id=item["smm_order_id"], waited_minutes=waited_seconds//60)
                send_telegram(
                    f"Sipariş gecikti.\n\nÜrün: {item['product_name']}\nPanel: {item['panel']}\n"
                    f"Itemsatış ID: {item['itemsatis_order_id']}\nSMM ID: {item['smm_order_id']}\n"
                    f"Link: {item['link']}\n\n1 saat 30 dakika geçti. Paneli kontrol et."
                )
                item["delay_alert_sent"] = True
                changed = True

        if status in ["completed", "complete", "tamamlandı"]:
            log("success", "order_completed", smm_order_id=item["smm_order_id"], product=item["product_name"])
            send_telegram(
                f"SMM siparişi tamamlandı.\n\nÜrün: {item['product_name']}\nPanel: {item['panel']}\n"
                f"Itemsatış ID: {item['itemsatis_order_id']}\nSMM ID: {item['smm_order_id']}\nLink: {item['link']}\n\n"
                f"Müşteriye değerlendirme mesajı gönderildi."
            )
            # YENİ: Müşteriye otomatik bildirim
            notify_customer_order_completed(item["itemsatis_order_id"], item["product_name"], item["link"])
            completed_indexes.append(index)
            changed = True

    for index in reversed(completed_indexes):
        PENDING_ORDERS.pop(index)

    if changed:
        save_state()

    return {"ok": True, "pending_count": len(PENDING_ORDERS), "completed_count": len(completed_indexes)}


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

        services_data = get_panel_services(service["api_url"], service["api_key"])
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
        order_key = make_order_key(order_id, advert_id, buyer, customer_link, platform)

        if order_key in PROCESSED_ORDERS:
            return {"ignored": True, "reason": "duplicate_order"}

        if duplicate_link_key in PROCESSED_LINKS:
            return {"ignored": True, "reason": "duplicate_link"}

        if not service.get("api_url") or not service.get("api_key"):
            add_failed_order(order_id, advert_id, service_name, "Panel bilgileri eksik", service.get("panel_key", ""))
            send_telegram(f"Panel bilgileri eksik.\n\nSipariş ID: {order_id}\nÜrün: {service_name}\nPanel: {service['panel']}\n\nRender Environment ayarlarını kontrol et.")
            return {"ok": False, "error": "panel_config_missing"}

        balance_data = panel_balance(service["api_url"], service["api_key"])

        if "error" in balance_data:
            add_failed_order(order_id, advert_id, service_name, "Panel bakiyesi alınamadı", balance_data.get("error"))
            notify_customer_order_failed(order_id, service_name)
            send_telegram(f"Panel bakiyesi alınamadı.\n\nSipariş ID: {order_id}\nHata: {balance_data.get('error')}")
            return {"ok": False, "error": "balance_failed"}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")
        check_low_balance(balance, currency, service["panel"])

        smm_result = create_panel_order(service["api_url"], service["api_key"],
                                        service["service_id"], customer_link, service["quantity"])

        if "error" in smm_result:
            add_failed_order(order_id, advert_id, service_name, "Panel sipariş hatası", smm_result.get("error"))
            notify_customer_order_failed(order_id, service_name)
            send_telegram(f"Panel siparişi başarısız.\n\nSipariş ID: {order_id}\nHata: {smm_result.get('error')}")
            return {"ok": False, "error": "panel_order_error"}

        smm_order_id = smm_result.get("order", "Bilinmiyor")

        PROCESSED_LINKS.add(duplicate_link_key)
        PROCESSED_ORDERS.add(order_key)
        add_pending_order(order_id, advert_id, service_name, service["panel"],
                          service["api_url"], service["api_key"], smm_order_id, customer_link)
        save_state()

        # YENİ: Müşteriye sipariş başladı bildirimi
        notify_customer_order_started(order_id, service_name, customer_link)

        send_telegram(
            f"SMM siparişi panele girildi.\n\nÜrün: {service_name}\nPanel: {service['panel']}\n"
            f"Itemsatış ID: {order_id}\nSMM ID: {smm_order_id}\nLink: {customer_link}\n"
            f"Adet: {service['quantity']}\nBakiye: {balance} {currency}"
        )

        return {"ok": True, "type": "smm_order", "smm_order_id": smm_order_id}

    log("info", "webhook_unmatched", advert_id=advert_id, product=product_name)
    return {"ignored": True, "product": product_name, "advert_id": advert_id}


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message", {})
    text = message.get("text", "").strip()
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != str(CHAT_ID):
        return {"ignored": True, "reason": "unauthorized_chat"}

    log("info", "telegram_command", command=text[:50])

    if text in ["/start", "/help"]:
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
            "/report - Bugünkü özet\n"
            "/week-report - Haftalık özet\n"
            "/month-report - Aylık özet\n"
            "/report-all - Tüm özetler\n"
            "/reset-report - Günlük raporu sıfırla\n"
            "/reset-all-reports - Tüm raporları sıfırla\n"
            "/help - Komutları gösterir"
        )
        return {"ok": True}

    if text == "/status":
        send_telegram("Bot aktif çalışıyor.\n\nRender: Aktif\nTelegram: Aktif\nItemsatış Webhook: Aktif")
        return {"ok": True}

    if text == "/panels":
        send_telegram(build_panels_list_text())
        return {"ok": True}

    if text == "/services":
        send_telegram(build_services_list_text())
        return {"ok": True}

    if text == "/balance" or text.startswith("/balance "):
        handle_panel_balance_command(text)
        return {"ok": True}

    if text == "/balance-all":
        handle_panel_balance_command("/balance all")
        return {"ok": True}

    if text == "/medyabalance":
        handle_panel_balance_command("/balance medyabayim")
        return {"ok": True}

    if text == "/health":
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
                panel_lines.append(f"{panel['name']}: Aktif - {balance_data.get('balance')} {balance_data.get('currency', '')}")

        panel_text = "\n".join(panel_lines)
        send_telegram(
            f"Sistem Durumu\n\nBot: Aktif\n{redis_t}\n{panel_text}\n\n"
            f"Başarısız: {len(FAILED_ORDERS)}\nBekleyen: {len(PENDING_ORDERS)}"
        )
        return {"ok": True}

    if text == "/failed":
        if not FAILED_ORDERS:
            send_telegram("Başarısız sipariş yok.")
            return {"ok": True}
        lines = ["Başarısız Siparişler:\n"]
        for item in FAILED_ORDERS[-10:]:
            lines.append(f"ID: {item['order_id']}\nÜrün: {item['product_name']}\nSebep: {item['reason']}\n")
        send_telegram("\n".join(lines))
        return {"ok": True}

    if text == "/pending":
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
    if text.startswith("/cancel"):
        handle_cancel_command(text)
        return {"ok": True}

    if text == "/report":
        send_telegram(build_sales_report("Bugünkü Sipariş Özeti", DAILY_STATS, "Bugün sipariş yok."))
        return {"ok": True}

    if text == "/week-report":
        send_telegram(build_sales_report("Haftalık Özet", WEEKLY_STATS, "Bu hafta sipariş yok."))
        return {"ok": True}

    if text == "/month-report":
        send_telegram(build_sales_report("Aylık Özet", MONTHLY_STATS, "Bu ay sipariş yok."))
        return {"ok": True}

    if text == "/report-all":
        daily = build_sales_report("Bugünkü Özet", DAILY_STATS, "Bugün sipariş yok.")
        weekly = build_sales_report("Haftalık Özet", WEEKLY_STATS, "Bu hafta sipariş yok.")
        monthly = build_sales_report("Aylık Özet", MONTHLY_STATS, "Bu ay sipariş yok.")
        send_telegram(daily + "\n\n---\n\n" + weekly + "\n\n---\n\n" + monthly)
        return {"ok": True}

    if text == "/reset-report":
        reset_sales_stats("daily")
        send_telegram("Günlük rapor sıfırlandı.")
        return {"ok": True}

    if text == "/reset-week-report":
        reset_sales_stats("weekly")
        send_telegram("Haftalık rapor sıfırlandı.")
        return {"ok": True}

    if text == "/reset-month-report":
        reset_sales_stats("monthly")
        send_telegram("Aylık rapor sıfırlandı.")
        return {"ok": True}

    if text == "/reset-all-reports":
        reset_sales_stats("all")
        send_telegram("Tüm raporlar sıfırlandı.")
        return {"ok": True}

    send_telegram("Bilinmeyen komut. /help ile komutları gör.")
    return {"ok": True}
