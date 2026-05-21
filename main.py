import os
import re
import json
import time
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

ITEMSATIS_COMMISSION_RATE = 0.07
RECORDED_SALES = set()

SMM_API_URL = os.getenv("SMM_API_URL", "https://smmrush.com/api/v2")
SMM_API_KEY = os.getenv("SMM_API_KEY", "")
INSTAGRAM_1000_SERVICE_ID = os.getenv("INSTAGRAM_1000_SERVICE_ID", "63")

MEDYABAYIM_API_URL = os.getenv("MEDYABAYIM_API_URL", "https://medyabayim.com/api/v2")
MEDYABAYIM_API_KEY = os.getenv("MEDYABAYIM_API_KEY", "")
MEDYABAYIM_100_TURK_SERVICE_ID = os.getenv("MEDYABAYIM_100_TURK_SERVICE_ID", "13743")

UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

CS2_ADVERT_ID = "5282114"

SMM_SERVICE_MAP = {
    "5098093": {
        "name": "Instagram 1000 Normal Takipçi",
        "panel": "SMMRush",
        "api_url": SMM_API_URL,
        "api_key": SMM_API_KEY,
        "service_id": INSTAGRAM_1000_SERVICE_ID,
        "quantity": 1000,
    },
    "5191839": {
        "name": "Instagram 100 Türk Takipçi",
        "panel": "MedyaBayim",
        "api_url": MEDYABAYIM_API_URL,
        "api_key": MEDYABAYIM_API_KEY,
        "service_id": MEDYABAYIM_100_TURK_SERVICE_ID,
        "quantity": 90,
    },
}

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

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}


def now_tr():
    return datetime.utcnow() + timedelta(hours=3)


def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN veya CHAT_ID eksik", flush=True)
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
        print("TELEGRAM RESPONSE:", r.status_code, r.text[:500], flush=True)
    except Exception as e:
        print("TELEGRAM ERROR:", str(e), flush=True)


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


def load_state():
    global PROCESSED_ORDERS, PROCESSED_LINKS, FAILED_ORDERS, PENDING_ORDERS
    global DAILY_STATS, LAST_DAILY_REPORT_DATE, SERVICE_PRICE_CACHE
    global WEEKLY_STATS, MONTHLY_STATS, LAST_WEEKLY_REPORT_DATE, LAST_MONTHLY_REPORT_DATE
    global RECORDED_SALES

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

    link = link.split("?")[0]
    link = link.rstrip("/")

    return link


def normalize_link_for_check(link: str) -> str:
    return (
        normalize_instagram_link(link)
        .lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .rstrip("/")
    )


def make_order_key(order_id, advert_id, buyer, link=""):
    if order_id and str(order_id) != "Bilinmiyor":
        return f"order:{order_id}"
    return f"fallback:{advert_id}:{buyer}:{normalize_link_for_check(link)}"


def add_failed_order(order_id, advert_id, product_name, reason, detail=""):
    FAILED_ORDERS.append(
        {
            "order_id": str(order_id),
            "advert_id": str(advert_id),
            "product_name": str(product_name),
            "reason": str(reason),
            "detail": str(detail),
            "created_at": int(time.time()),
        }
    )

    if len(FAILED_ORDERS) > 20:
        FAILED_ORDERS.pop(0)

    save_state()


def get_order_price(data: dict) -> float:
    value = get_nested(
        data,
        "price", "total", "amount", "total_price", "order_price",
        "details.price", "details.total", "details.amount", "details.total_price", "details.order_price",
        "data.price", "data.total", "data.amount", "data.total_price", "data.order_price",
        "payment.price", "payment.total", "payment.amount",
        "details.payment.price", "details.payment.total", "details.payment.amount",
        "data.payment.price", "data.payment.total", "data.payment.amount",
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


def record_itemsatis_sale(order_id, advert_id, buyer, product_name, price, link="") -> bool:
    global RECORDED_SALES

    sale_key = make_order_key(order_id, advert_id, buyer, link)

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


def add_pending_order(order_id, advert_id, product_name, panel, api_url, api_key, smm_order_id, link):
    if not smm_order_id or str(smm_order_id) == "Bilinmiyor":
        return

    if any(str(item.get("smm_order_id")) == str(smm_order_id) for item in PENDING_ORDERS):
        return

    PENDING_ORDERS.append(
        {
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
        }
    )

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
    return normalize_text(
        get_nested(
            data,
            "event", "type", "action",
            "details.event", "details.type", "details.action",
            "data.event", "data.type", "data.action",
        )
    )


def get_order_id(data: dict) -> str:
    return str(
        get_nested(
            data,
            "order_id", "id", "purchaseId", "purchase_id",
            "data.order_id", "data.id", "data.purchaseId",
            "details.order_id", "details.id", "details.purchaseId",
        )
        or "Bilinmiyor"
    )


def get_advert_id(data: dict) -> str:
    return str(
        get_nested(
            data,
            "advert.id", "details.advert.id", "data.advert.id",
            "advert_id", "details.advert_id", "data.advert_id",
        )
        or ""
    )


def get_product_name(data: dict) -> str:
    return str(
        get_nested(
            data,
            "product_name", "product", "advert.title", "advert.name",
            "details.advert.title", "details.advert.name",
            "data.advert.title", "data.advert.name",
            "details.product_name", "details.product",
            "data.product_name", "data.product", "title", "details.title", "data.title",
        )
        or ""
    ).strip()


def get_buyer(data: dict) -> str:
    buyer = get_nested(
        data,
        "buyer", "buyer.username", "username", "customer",
        "customer.username", "customer.name",
        "details.customer.username", "details.customer.name", "details.customer",
        "data.customer.username", "data.customer.name", "data.customer",
        "details.buyer.username", "details.buyer",
    )

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


def find_instagram_link(data: dict) -> str:
    priority_paths = [
        "post_datas.Profil Linki",
        "details.post_datas.Profil Linki",
        "data.post_datas.Profil Linki",
        "url", "link", "instagram", "instagram_link", "profile_link", "account_link",
        "note", "message", "content", "description", "order_note", "customer_note",
        "details.url", "details.link", "details.instagram", "details.instagram_link",
        "details.note", "details.message", "details.content", "details.description",
        "data.url", "data.link", "data.instagram", "data.instagram_link",
        "data.note", "data.message", "data.content", "data.description",
    ]

    for path in priority_paths:
        value = get_nested(data, path)

        if isinstance(value, str) and value.strip():
            if "instagram.com" in value.lower() or value.strip().startswith("@"):
                return normalize_instagram_link(value)

    all_strings = collect_strings(data)
    joined = "\n".join(all_strings)

    match = re.search(
        r"(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._/\-?=&%]+",
        joined,
        re.IGNORECASE,
    )

    if match:
        return normalize_instagram_link(match.group(0))

    for text in all_strings:
        text = text.strip()
        if text.startswith("@") and len(text) > 2:
            return normalize_instagram_link(text)

    return ""


def panel_balance(api_url, api_key):
    if not api_url or not api_key:
        return {"error": "API URL veya API KEY eksik"}

    try:
        r = requests.post(
            api_url,
            data={"key": api_key, "action": "balance"},
            headers=HEADERS,
            timeout=30,
        )

        print("BALANCE STATUS:", r.status_code, flush=True)
        print("BALANCE RESPONSE:", r.text[:500], flush=True)

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
        r = requests.post(
            api_url,
            data={
                "key": api_key,
                "action": "add",
                "service": service_id,
                "link": link,
                "quantity": quantity,
            },
            headers=HEADERS,
            timeout=30,
        )

        print("ORDER STATUS:", r.status_code, flush=True)
        print("ORDER RESPONSE:", r.text[:500], flush=True)

        try:
            return r.json()
        except Exception:
            return {"error": "Panel JSON cevap vermedi", "raw": r.text[:300]}

    except Exception as e:
        return {"error": str(e)}


def check_panel_order_status(api_url, api_key, order_id):
    if not api_url or not api_key or not order_id:
        return {"error": "Status için API bilgisi veya order ID eksik"}

    try:
        r = requests.post(
            api_url,
            data={"key": api_key, "action": "status", "order": order_id},
            headers=HEADERS,
            timeout=30,
        )

        print("STATUS CHECK:", r.status_code, r.text[:500], flush=True)

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
        r = requests.post(
            api_url,
            data={"key": api_key, "action": "services"},
            headers=HEADERS,
            timeout=30,
        )

        print("SERVICES STATUS:", r.status_code, flush=True)
        print("SERVICES RESPONSE:", r.text[:500], flush=True)

        try:
            return r.json()
        except Exception:
            return {"error": "Services JSON cevap vermedi", "raw": r.text[:300]}

    except Exception as e:
        return {"error": str(e)}


def check_low_balance(balance, currency, panel_name="Panel"):
    try:
        numeric_balance = float(balance)

        if str(currency).upper() == "USD":
            balance_tl = numeric_balance * 39
        else:
            balance_tl = numeric_balance

        if balance_tl <= 100:
            send_telegram(
                f"""
{panel_name} bakiyesi 100 TL altına düştü.

Kalan Bakiye: {balance} {currency}

Lütfen panel bakiyesini kontrol et.
"""
            )

    except Exception as e:
        print("BALANCE CHECK ERROR:", str(e), flush=True)


load_state()


@app.get("/")
def home():
    return {"status": "bot çalışıyor"}


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
        status_data = check_panel_order_status(
            item["api_url"],
            item["api_key"],
            item["smm_order_id"],
        )

        if "error" in status_data:
            print("STATUS ERROR:", status_data, flush=True)
            continue

        status = str(status_data.get("status", "")).lower()

        created_at = int(item.get("created_at", 0))
        delay_alert_sent = bool(item.get("delay_alert_sent", False))

        if created_at and not delay_alert_sent:
            waited_seconds = int(time.time()) - created_at

            if waited_seconds >= 5400:
                send_telegram(
                    f"""
Sipariş gecikti.

Ürün: {item["product_name"]}
Panel: {item["panel"]}
Itemsatış Sipariş ID: {item["itemsatis_order_id"]}
SMM Sipariş ID: {item["smm_order_id"]}
Link: {item["link"]}

Bekleme süresi: 1 saat 30 dakika geçti.
Paneli kontrol et.
"""
                )

                item["delay_alert_sent"] = True
                changed = True

        if status in ["completed", "complete", "tamamlandı"]:
            send_telegram(
                f"""
Instagram siparişi tamamlandı.

Ürün: {item["product_name"]}
Panel: {item["panel"]}
Itemsatış Sipariş ID: {item["itemsatis_order_id"]}
SMM Sipariş ID: {item["smm_order_id"]}
Link: {item["link"]}

Müşteriye değerlendirme mesajı gönderebilirsin.
"""
            )
            completed_indexes.append(index)
            changed = True

    for index in reversed(completed_indexes):
        PENDING_ORDERS.pop(index)

    if changed:
        save_state()

    return {
        "ok": True,
        "pending_count": len(PENDING_ORDERS),
        "completed_count": len(completed_indexes),
    }


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

    report_text = build_sales_report(
        "Günlük Satış Özeti",
        DAILY_STATS,
        "Bugün kayıtlı sipariş yok.",
    )

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

    report_text = build_sales_report(
        "Haftalık Satış Raporu",
        WEEKLY_STATS,
        "Bu hafta kayıtlı sipariş yok.",
    )

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

    report_text = build_sales_report(
        "Aylık Satış Raporu",
        MONTHLY_STATS,
        "Bu ay kayıtlı sipariş yok.",
    )

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

    for advert_id, service in SMM_SERVICE_MAP.items():
        services_data = get_panel_services(service["api_url"], service["api_key"])

        if isinstance(services_data, dict) and "error" in services_data:
            print("SERVICE CHECK ERROR:", services_data, flush=True)
            continue

        target_service = None

        for item in services_data:
            if str(item.get("service")) == str(service["service_id"]):
                target_service = item
                break

        if not target_service:
            continue

        current_rate = str(target_service.get("rate", ""))
        cache_key = f'{service["panel"]}:{service["service_id"]}'
        old_rate = SERVICE_PRICE_CACHE.get(cache_key)

        if old_rate is None:
            SERVICE_PRICE_CACHE[cache_key] = current_rate
            save_state()
            continue

        if str(old_rate) != str(current_rate):
            send_telegram(
                f"""
Servis fiyatı değişti.

Ürün: {service["name"]}
Panel: {service["panel"]}
Servis ID: {service["service_id"]}

Eski fiyat: {old_rate}
Yeni fiyat: {current_rate}

İlan fiyatını ve kâr marjını kontrol et.
"""
            )

            SERVICE_PRICE_CACHE[cache_key] = current_rate
            changed_count += 1

    if changed_count:
        save_state()

    return {
        "ok": True,
        "changed_count": changed_count,
        "tracked_services": len(SMM_SERVICE_MAP),
    }


@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        body = await request.body()
        data = {"raw_body": body.decode("utf-8", errors="ignore")}

    print("ITEMSATIS WEBHOOK DATA:", json.dumps(data, ensure_ascii=False), flush=True)

    event = get_event(data)
    order_id = get_order_id(data)
    advert_id = get_advert_id(data)
    product_name = get_product_name(data)
    buyer = get_buyer(data)
    price = get_order_price(data)

    ignored_events = {
        "review_received",
        "review_created",
        "message_created",
        "question_created",
        "advert_updated",
    }

    if event in ignored_events:
        print("IGNORED EVENT:", event, flush=True)
        return {"ignored": True, "event": event}

    report_product_name = (
        product_name
        or SMM_SERVICE_MAP.get(advert_id, {}).get("name")
        or ("CS2 5 Yıllık Hesap" if advert_id == CS2_ADVERT_ID else "Bilinmeyen Ürün")
    )

    record_itemsatis_sale(
        order_id=order_id,
        advert_id=advert_id,
        buyer=buyer,
        product_name=report_product_name,
        price=price,
    )

    send_telegram(
        f"""
Itemsatış webhook geldi.

Event: {event or "Yok"}
Advert ID: {advert_id or "Yok"}
Ürün: {report_product_name}
Sipariş ID: {order_id}
Müşteri: {buyer}
Tutar: {price:.2f} TL
"""
    )

    if advert_id == CS2_ADVERT_ID:
        order_key = make_order_key(order_id, advert_id, buyer)

        if order_key in PROCESSED_ORDERS:
            return {"ignored": True, "reason": "duplicate_cs2_order"}

        PROCESSED_ORDERS.add(order_key)
        save_state()

        send_telegram(
            f"""
Yeni CS2 5 yıllık hesap siparişi geldi.

Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {product_name}
Müşteri: {buyer}

{get_lzt_links()}

Hesabı manuel kontrol edip satın al.
"""
        )

        return {
            "ok": True,
            "type": "cs2",
            "order_id": order_id,
            "advert_id": advert_id,
        }

    if advert_id in SMM_SERVICE_MAP:
        service = SMM_SERVICE_MAP[advert_id]
        customer_link = find_instagram_link(data)

        if not customer_link:
            add_failed_order(
                order_id,
                advert_id,
                service["name"],
                "Instagram linki bulunamadı",
                "Müşteri link alanı bot tarafından algılanamadı.",
            )

            send_telegram(
                f"""
Instagram siparişi geldi ama müşteri linki bulunamadı.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {service["name"]}
Müşteri: {buyer}

Render Logs içindeki ITEMSATIS WEBHOOK DATA kısmını kontrol et.
"""
            )

            return {"ok": False, "error": "instagram_link_not_found"}

        normalized_link = normalize_link_for_check(customer_link)
        duplicate_link_key = f"{advert_id}:{normalized_link}"
        order_key = make_order_key(order_id, advert_id, buyer, customer_link)

        if order_key in PROCESSED_ORDERS:
            send_telegram(
                f"""
Aynı Itemsatış siparişi tekrar geldi.

Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {service["name"]}

Tekrar işlem yapılmadı.
"""
            )
            return {"ignored": True, "reason": "duplicate_order"}

        if duplicate_link_key in PROCESSED_LINKS:
            send_telegram(
                f"""
Aynı Instagram linki aynı ilana tekrar geldi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {service["name"]}
Link: {customer_link}

Bu sipariş panele tekrar girilmedi.
"""
            )
            return {"ignored": True, "reason": "duplicate_link"}

        balance_data = panel_balance(service["api_url"], service["api_key"])

        if "error" in balance_data:
            add_failed_order(
                order_id,
                advert_id,
                service["name"],
                "Panel bakiyesi alınamadı",
                balance_data.get("error", ""),
            )

            send_telegram(
                f"""
Instagram siparişi geldi ama panel bakiyesi alınamadığı için panele girilmedi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {service["name"]}
Panel: {service["panel"]}
Link: {customer_link}

Hata: {balance_data.get("error")}
"""
            )

            return {"ok": False, "error": "balance_failed"}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")

        check_low_balance(balance, currency, service["panel"])

        smm_result = create_panel_order(
            service["api_url"],
            service["api_key"],
            service["service_id"],
            customer_link,
            service["quantity"],
        )

        if "error" in smm_result:
            add_failed_order(
                order_id,
                advert_id,
                service["name"],
                "Panel sipariş hatası",
                smm_result.get("error", smm_result),
            )

            send_telegram(
                f"""
Instagram siparişi panele girilemedi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {service["name"]}
Panel: {service["panel"]}
Müşteri: {buyer}
Link: {customer_link}

Panel Hatası: {smm_result.get("error")}
Bakiye: {balance} {currency}
"""
            )

            return {
                "ok": False,
                "error": "panel_order_error",
                "detail": smm_result,
            }

        smm_order_id = smm_result.get("order", "Bilinmiyor")

        PROCESSED_LINKS.add(duplicate_link_key)
        PROCESSED_ORDERS.add(order_key)


        add_pending_order(
            order_id,
            advert_id,
            service["name"],
            service["panel"],
            service["api_url"],
            service["api_key"],
            smm_order_id,
            customer_link,
        )

        save_state()

        send_telegram(
            f"""
Instagram siparişi panele girildi.

Ürün: {service["name"]}
Panel: {service["panel"]}
Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
SMM Sipariş ID: {smm_order_id}
Müşteri: {buyer}
Link: {customer_link}
Adet: {service["quantity"]}

Bakiye: {balance} {currency}
"""
        )

        return {
            "ok": True,
            "type": "instagram_smm",
            "itemsatis_order_id": order_id,
            "advert_id": advert_id,
            "panel": service["panel"],
            "smm_order_id": smm_order_id,
            "instagram_link": customer_link,
            "quantity": service["quantity"],
            "balance": balance,
            "currency": currency,
        }

    print("IGNORED PRODUCT:", product_name, "ADVERT ID:", advert_id, flush=True)

    return {
        "ignored": True,
        "product": product_name,
        "advert_id": advert_id,
        "event": event,
    }


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()

    print("TELEGRAM WEBHOOK DATA:", json.dumps(data, ensure_ascii=False), flush=True)

    message = data.get("message", {})
    text = message.get("text", "").strip()
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != str(CHAT_ID):
        return {"ignored": True, "reason": "unauthorized_chat"}

    if text in ["/start", "/help"]:
        send_telegram(
            """
Bot komutları:

/balance - SMMRush bakiyesini gösterir
/medyabalance - MedyaBayim bakiyesini gösterir
/status - Bot durumunu gösterir
/health - Genel sistem durumunu gösterir
/failed - Başarısız siparişleri gösterir
/pending - Takip edilen siparişleri gösterir
/report - Bugünkü sipariş özetini gösterir
/help - Komutları gösterir
"""
        )
        return {"ok": True}

    if text == "/status":
        send_telegram(
            """
Bot aktif çalışıyor.

Render: Aktif
Telegram: Aktif
Itemsatış Webhook: Aktif
SMM Paneller: Aktif
Redis: Aktif
"""
        )
        return {"ok": True}

    if text == "/balance":
        balance_data = panel_balance(SMM_API_URL, SMM_API_KEY)

        if "error" in balance_data:
            send_telegram(f"SMMRush bakiye alınamadı.\n\nHata: {balance_data.get('error')}")
            return {"ok": False}

        send_telegram(
            f"""
SMMRush Panel Bakiyesi:

Bakiye: {balance_data.get("balance", "Bilinmiyor")} {balance_data.get("currency", "")}
"""
        )
        return {"ok": True}

    if text == "/medyabalance":
        balance_data = panel_balance(MEDYABAYIM_API_URL, MEDYABAYIM_API_KEY)

        if "error" in balance_data:
            send_telegram(f"MedyaBayim bakiye alınamadı.\n\nHata: {balance_data.get('error')}")
            return {"ok": False}

        send_telegram(
            f"""
MedyaBayim Panel Bakiyesi:

Bakiye: {balance_data.get("balance", "Bilinmiyor")} {balance_data.get("currency", "")}
"""
        )
        return {"ok": True}

    if text == "/health":
        main_balance = panel_balance(SMM_API_URL, SMM_API_KEY)
        medya_balance = panel_balance(MEDYABAYIM_API_URL, MEDYABAYIM_API_KEY)

        main_text = (
            f"SMMRush: Hatalı - {main_balance.get('error')}"
            if "error" in main_balance
            else f"SMMRush: Aktif - {main_balance.get('balance')} {main_balance.get('currency', '')}"
        )

        medya_text = (
            f"MedyaBayim: Hatalı - {medya_balance.get('error')}"
            if "error" in medya_balance
            else f"MedyaBayim: Aktif - {medya_balance.get('balance')} {medya_balance.get('currency', '')}"
        )

        redis_text = "Redis: Aktif" if UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN else "Redis: Eksik"

        send_telegram(
            f"""
Sistem Durumu

Bot: Aktif
Telegram: Aktif
Render: Aktif
{redis_text}
{main_text}
{medya_text}

Başarısız sipariş kaydı: {len(FAILED_ORDERS)}
Takip edilen sipariş: {len(PENDING_ORDERS)}
"""
        )
        return {"ok": True}

    if text == "/failed":
        if not FAILED_ORDERS:
            send_telegram("Başarısız sipariş kaydı yok.")
            return {"ok": True}

        lines = ["Başarısız Siparişler:\n"]

        for item in FAILED_ORDERS[-10:]:
            lines.append(
                f"""
Sipariş ID: {item["order_id"]}
Advert ID: {item["advert_id"]}
Ürün: {item["product_name"]}
Sebep: {item["reason"]}
Detay: {item["detail"]}
"""
            )

        send_telegram("\n".join(lines))
        return {"ok": True}

    if text == "/pending":
        if not PENDING_ORDERS:
            send_telegram("Takip edilen sipariş yok.")
            return {"ok": True}

        lines = ["Takip Edilen Siparişler:\n"]

        for item in PENDING_ORDERS[-10:]:
            created_at = int(item.get("created_at", 0))
            waited_minutes = int((time.time() - created_at) / 60) if created_at else 0

            lines.append(
                f"""
Ürün: {item["product_name"]}
Panel: {item["panel"]}
Itemsatış ID: {item["itemsatis_order_id"]}
SMM ID: {item["smm_order_id"]}
Bekleme: {waited_minutes} dakika
Link: {item["link"]}
"""
            )

        send_telegram("\n".join(lines))
        return {"ok": True}

    if text == "/report":
        report_text = build_sales_report(
            "Bugünkü Sipariş Özeti",
            DAILY_STATS,
            "Bugün kayıtlı sipariş yok.",
        )

        send_telegram(report_text)
        return {"ok": True}

    send_telegram("Bilinmeyen komut. Komutları görmek için: /help")
    return {"ok": True}
