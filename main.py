import os
import re
import json
import requests
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

SMM_API_URL = os.getenv("SMM_API_URL", "https://smmrush.com/api/v2")
SMM_API_KEY = os.getenv("SMM_API_KEY", "")
INSTAGRAM_1000_SERVICE_ID = os.getenv("INSTAGRAM_1000_SERVICE_ID", "63")

MEDYABAYIM_API_URL = os.getenv("MEDYABAYIM_API_URL", "https://medyabayim.com/api/v2")
MEDYABAYIM_API_KEY = os.getenv("MEDYABAYIM_API_KEY", "")
MEDYABAYIM_100_TURK_SERVICE_ID = os.getenv("MEDYABAYIM_100_TURK_SERVICE_ID", "13743")

CS2_ADVERT_ID = "5282114"

SMM_SERVICE_MAP = {
    "5098093": {
        "name": "Instagram 1000 Normal Takipçi",
        "panel": "smmrush",
        "api_url": SMM_API_URL,
        "api_key": SMM_API_KEY,
        "service_id": INSTAGRAM_1000_SERVICE_ID,
        "quantity": 1000,
    },
    "5191839": {
        "name": "Instagram 100 Türk Takipçi",
        "panel": "medyabayim",
        "api_url": MEDYABAYIM_API_URL,
        "api_key": MEDYABAYIM_API_KEY,
        "service_id": MEDYABAYIM_100_TURK_SERVICE_ID,
        "quantity": 100,
    },
}

PROCESSED_ORDERS = set()
PROCESSED_LINKS = set()
FAILED_ORDERS = []
PENDING_ORDERS = []

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}


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


def add_failed_order(order_id, advert_id, product_name, reason, detail=""):
    FAILED_ORDERS.append(
        {
            "order_id": str(order_id),
            "advert_id": str(advert_id),
            "product_name": str(product_name),
            "reason": str(reason),
            "detail": str(detail),
        }
    )

    if len(FAILED_ORDERS) > 20:
        FAILED_ORDERS.pop(0)


def add_pending_order(order_id, advert_id, product_name, panel, api_url, api_key, smm_order_id, link):
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
        }
    )


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
            "event",
            "type",
            "action",
            "details.event",
            "details.type",
            "details.action",
        )
    )


def get_order_id(data: dict) -> str:
    return str(
        get_nested(
            data,
            "order_id",
            "id",
            "purchaseId",
            "purchase_id",
            "data.order_id",
            "data.id",
            "data.purchaseId",
            "details.order_id",
            "details.id",
            "details.purchaseId",
        )
        or "Bilinmiyor"
    )


def get_advert_id(data: dict) -> str:
    return str(
        get_nested(
            data,
            "advert.id",
            "details.advert.id",
            "data.advert.id",
        )
        or ""
    )


def get_product_name(data: dict) -> str:
    return str(
        get_nested(
            data,
            "product_name",
            "product",
            "advert.title",
            "advert.name",
            "details.advert.title",
            "details.advert.name",
            "data.advert.title",
            "data.advert.name",
            "details.product_name",
            "details.product",
            "data.product_name",
            "data.product",
            "title",
            "details.title",
            "data.title",
        )
        or ""
    ).strip()


def get_buyer(data: dict) -> str:
    buyer = get_nested(
        data,
        "buyer",
        "buyer.username",
        "username",
        "customer",
        "customer.username",
        "customer.name",
        "details.customer.username",
        "details.customer.name",
        "details.customer",
        "data.customer.username",
        "data.customer.name",
        "data.customer",
        "details.buyer.username",
        "details.buyer",
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
        "url",
        "link",
        "instagram",
        "instagram_link",
        "profile_link",
        "account_link",
        "note",
        "message",
        "content",
        "description",
        "order_note",
        "customer_note",
        "details.url",
        "details.link",
        "details.instagram",
        "details.instagram_link",
        "details.note",
        "details.message",
        "details.content",
        "details.description",
        "data.url",
        "data.link",
        "data.instagram",
        "data.instagram_link",
        "data.note",
        "data.message",
        "data.content",
        "data.description",
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
            data={
                "key": api_key,
                "action": "balance",
            },
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
    try:
        r = requests.post(
            api_url,
            data={
                "key": api_key,
                "action": "status",
                "order": order_id,
            },
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


@app.get("/check-orders")
def check_orders():
    completed_indexes = []

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

    for index in reversed(completed_indexes):
        PENDING_ORDERS.pop(index)

    return {
        "ok": True,
        "pending_count": len(PENDING_ORDERS),
        "completed_count": len(completed_indexes),
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

    if order_id in PROCESSED_ORDERS and order_id != "Bilinmiyor":
        send_telegram(
            f"""
Aynı Itemsatış siparişi tekrar geldi.

Sipariş ID: {order_id}
Advert ID: {advert_id or "Yok"}

Tekrar işlem yapılmadı.
"""
        )
        return {"ignored": True, "reason": "duplicate_order"}

    send_telegram(
        f"""
Itemsatış webhook geldi.

Event: {event or "Yok"}
Advert ID: {advert_id or "Yok"}
Ürün: {product_name or "Bulunamadı"}
Sipariş ID: {order_id}
Müşteri: {buyer}
"""
    )

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

    if advert_id == CS2_ADVERT_ID:
        PROCESSED_ORDERS.add(order_id)

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
            send_telegram(
                f"""
Instagram siparişi geldi ama müşteri linki bulunamadı.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {product_name}
Müşteri: {buyer}

Render Logs içindeki ITEMSATIS WEBHOOK DATA kısmını kontrol et.
"""
            )

            add_failed_order(
                order_id,
                advert_id,
                product_name,
                "Instagram linki bulunamadı",
                "Müşteri link alanı bot tarafından algılanamadı.",
            )

            return {"ok": False, "error": "instagram_link_not_found"}

        normalized_link = normalize_link_for_check(customer_link)
        duplicate_key = f"{advert_id}:{normalized_link}"

        if duplicate_key in PROCESSED_LINKS:
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

            add_failed_order(
                order_id,
                advert_id,
                service["name"],
                "Panel bakiyesi alınamadı",
                balance_data.get("error", ""),
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

            add_failed_order(
                order_id,
                advert_id,
                service["name"],
                "Panel sipariş hatası",
                smm_result.get("error", smm_result),
            )

            return {
                "ok": False,
                "error": "panel_order_error",
                "detail": smm_result,
            }

        smm_order_id = smm_result.get("order", "Bilinmiyor")

        PROCESSED_LINKS.add(duplicate_key)
        PROCESSED_ORDERS.add(order_id)

        if smm_order_id != "Bilinmiyor":
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

/balance - Ana panel bakiyesini gösterir
/medyabalance - MedyaBayim bakiyesini gösterir
/status - Bot durumunu gösterir
/health - Genel sistem durumunu gösterir
/failed - Başarısız siparişleri gösterir
/pending - Takip edilen siparişleri gösterir
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

        send_telegram(
            f"""
Sistem Durumu

Bot: Aktif
Telegram: Aktif
Render: Aktif
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
            lines.append(
                f"""
Ürün: {item["product_name"]}
Panel: {item["panel"]}
Itemsatış ID: {item["itemsatis_order_id"]}
SMM ID: {item["smm_order_id"]}
Link: {item["link"]}
"""
            )

        send_telegram("\n".join(lines))
        return {"ok": True}

    send_telegram("Bilinmeyen komut. Komutları görmek için: /help")
    return {"ok": True}
