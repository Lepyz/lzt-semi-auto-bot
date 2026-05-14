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

CS2_ADVERT_ID = "5282114"
INSTAGRAM_ADVERT_ID = "5098093"

PROCESSED_ORDERS = set()
PROCESSED_LINKS = set()

SMM_HEADERS = {
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

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
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
        link = match.group(0)
        return normalize_instagram_link(link)

    for text in all_strings:
        text = text.strip()
        if text.startswith("@") and len(text) > 2:
            return normalize_instagram_link(text)

    return ""


def get_smm_balance():
    if not SMM_API_URL or not SMM_API_KEY:
        return {"error": "SMM_API_URL veya SMM_API_KEY eksik"}

    payload = {
        "key": SMM_API_KEY,
        "action": "balance",
    }

    try:
        r = requests.post(
            SMM_API_URL,
            data=payload,
            headers=SMM_HEADERS,
            timeout=30,
        )

        print("SMM BALANCE STATUS:", r.status_code, flush=True)
        print("SMM BALANCE RESPONSE:", r.text[:500], flush=True)

        try:
            return r.json()
        except Exception:
            return {
                "error": "SMM panel JSON cevap vermedi",
                "raw": r.text[:300],
            }

    except Exception as e:
        return {"error": str(e)}


def create_smm_order(link: str, quantity: int = 1000):
    if not SMM_API_URL or not SMM_API_KEY:
        return {"error": "SMM_API_URL veya SMM_API_KEY eksik"}

    payload = {
        "key": SMM_API_KEY,
        "action": "add",
        "service": INSTAGRAM_1000_SERVICE_ID,
        "link": link,
        "quantity": quantity,
    }

    try:
        r = requests.post(
            SMM_API_URL,
            data=payload,
            headers=SMM_HEADERS,
            timeout=30,
        )

        print("SMM ORDER STATUS:", r.status_code, flush=True)
        print("SMM ORDER RESPONSE:", r.text[:500], flush=True)

        try:
            return r.json()
        except Exception:
            return {
                "error": "SMM panel JSON cevap vermedi",
                "raw": r.text[:300],
            }

    except Exception as e:
        return {"error": str(e)}


def check_low_balance(balance, currency):
    try:
        numeric_balance = float(balance)

        if str(currency).upper() == "USD":
            balance_tl = numeric_balance * 39
        else:
            balance_tl = numeric_balance

        if balance_tl <= 100:
            send_telegram(
                f"""
SMM panel bakiyesi 100 TL altına düştü.

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
    send_telegram("Test mesajı geldi.\nBot aktif çalışıyor.")
    return {"ok": True}


@app.get("/my-ip")
def my_ip():
    r = requests.get("https://api.ipify.org?format=json", timeout=30)
    return r.json()


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

    if advert_id == INSTAGRAM_ADVERT_ID:
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

            return {"ok": False, "error": "instagram_link_not_found"}

        normalized_link = normalize_link_for_check(customer_link)

        if normalized_link in PROCESSED_LINKS:
            send_telegram(
                f"""
Aynı Instagram linki tekrar geldi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Link: {customer_link}

Bu sipariş panele tekrar girilmedi.
"""
            )

            return {"ignored": True, "reason": "duplicate_link"}

        balance_data = get_smm_balance()

        if "error" in balance_data:
            send_telegram(
                f"""
Instagram siparişi geldi ama SMM bakiye alınamadığı için panele girilmedi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {product_name}
Link: {customer_link}

Hata: {balance_data.get("error")}
"""
            )

            return {"ok": False, "error": "balance_failed"}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")

        check_low_balance(balance, currency)

        smm_result = create_smm_order(customer_link, 1000)

        if "error" in smm_result:
            send_telegram(
                f"""
Instagram 1000 takipçi siparişi panele girilemedi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
Ürün: {product_name}
Müşteri: {buyer}
Link: {customer_link}

Panel Hatası: {smm_result.get("error")}
Bakiye: {balance} {currency}
"""
            )

            return {
                "ok": False,
                "error": "smm_panel_error",
                "detail": smm_result,
            }

        smm_order_id = smm_result.get("order", "Bilinmiyor")

        PROCESSED_LINKS.add(normalized_link)
        PROCESSED_ORDERS.add(order_id)

        print(
            f"ORDER MAP | ITEMSATIS_ID={order_id} | ADVERT_ID={advert_id} | SMM_ORDER_ID={smm_order_id} | LINK={customer_link}",
            flush=True,
        )

        send_telegram(
            f"""
Instagram 1000 takipçi siparişi panele girildi.

Itemsatış Sipariş ID: {order_id}
Advert ID: {advert_id}
SMM Sipariş ID: {smm_order_id}
Ürün: {product_name}
Müşteri: {buyer}
Link: {customer_link}

Bakiye: {balance} {currency}
"""
        )

        return {
            "ok": True,
            "type": "instagram_1000",
            "itemsatis_order_id": order_id,
            "advert_id": advert_id,
            "smm_order_id": smm_order_id,
            "instagram_link": customer_link,
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

/balance - SMM panel bakiyesini gösterir
/status - Bot durumunu gösterir
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
SMMRush: /balance ile kontrol edilebilir
"""
        )
        return {"ok": True}

    if text == "/balance":
        balance_data = get_smm_balance()

        if "error" in balance_data:
            send_telegram(
                f"""
SMM bakiye alınamadı.

Hata: {balance_data.get("error")}
"""
            )
            return {"ok": False, "error": balance_data.get("error")}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")

        send_telegram(
            f"""
SMM Panel Bakiyesi:

Bakiye: {balance} {currency}
"""
        )

        return {"ok": True, "balance": balance, "currency": currency}

    send_telegram("Bilinmeyen komut. Komutları görmek için: /help")
    return {"ok": True}
