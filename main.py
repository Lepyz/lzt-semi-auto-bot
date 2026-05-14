import os
import requests
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SMM_API_URL = os.getenv("SMM_API_URL")
SMM_API_KEY = os.getenv("SMM_API_KEY")
INSTAGRAM_1000_SERVICE_ID = os.getenv("INSTAGRAM_1000_SERVICE_ID", "63")

PROCESSED_LINKS = set()

SMM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*"
}


def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN veya CHAT_ID eksik", flush=True)
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    })

    print("TELEGRAM RESPONSE:", response.text, flush=True)


@app.get("/")
def home():
    return {"status": "bot çalışıyor"}


def get_lzt_links():
    return """
LZT arama linkleri:

1) 5 years medal:
https://lzt.market/steam/?order_by=price_to_up&title=5%20years%20medal

2) CS2 5 years:
https://lzt.market/steam/?order_by=price_to_up&title=cs2%205%20years

3) CS2 medal:
https://lzt.market/steam/?order_by=price_to_up&title=cs2%20medal
"""


def find_customer_link(data: dict):
    possible_fields = [
        "link",
        "url",
        "account_link",
        "profile_link",
        "instagram",
        "instagram_link",
        "username",
        "note",
        "content",
        "description",
        "order_note",
        "customer_note",
        "message"
    ]

    for field in possible_fields:
        value = data.get(field)
        if value and isinstance(value, str):
            return value.strip()

    details = data.get("details")
    if isinstance(details, dict):
        for field in possible_fields:
            value = details.get(field)
            if value and isinstance(value, str):
                return value.strip()

    return ""


def get_smm_balance():
    payload = {
        "key": SMM_API_KEY,
        "action": "balance"
    }

    response = requests.post(
        SMM_API_URL,
        data=payload,
        headers=SMM_HEADERS,
        timeout=30
    )

    print("SMM BALANCE STATUS:", response.status_code, flush=True)
    print("SMM BALANCE RESPONSE:", response.text[:500], flush=True)

    try:
        return response.json()
    except Exception:
        return {
            "error": "SMM panel JSON cevap vermedi. Cloudflare veya API erişim engeli olabilir.",
            "raw": response.text[:300]
        }


def create_smm_order(link: str, quantity: int = 1000):
    payload = {
        "key": SMM_API_KEY,
        "action": "add",
        "service": INSTAGRAM_1000_SERVICE_ID,
        "url": link,
        "quantity": quantity
    }

    response = requests.post(
        SMM_API_URL,
        data=payload,
        headers=SMM_HEADERS,
        timeout=30
    )

    print("SMM ORDER STATUS:", response.status_code, flush=True)
    print("SMM ORDER RESPONSE:", response.text[:500], flush=True)

    try:
        return response.json()
    except Exception:
        return {
            "error": "SMM panel JSON cevap vermedi. Cloudflare veya API erişim engeli olabilir.",
            "raw": response.text[:300]
        }


@app.get("/test")
def test_message():
    send_telegram("Test mesajı geldi. Bot aktif çalışıyor.")
    return {"ok": True}


@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    data = await request.json()

    print("ITEMSATIS WEBHOOK DATA:", data, flush=True)

    if data.get("details", {}).get("test") is True:
        send_telegram(f"""
Itemsatış webhook test mesajı geldi.

Başlık:
{data.get("title")}

İçerik:
{data.get("content")}
""")
        return {"ok": True, "type": "test"}
        
order_id = data.get("order_id") or data.get("id") or "Bilinmiyor"

event = data.get("details", {}).get("event", "")

if event and event != "purchase_created":
    print("IGNORED EVENT:", event, flush=True)
    return {"ignored": True, "event": event}

advert = data.get("advert", {})

product_name = (
    data.get("product_name")
    or data.get("product")
    or advert.get("title")
    or data.get("title")
    or ""
)

buyer = data.get("buyer") or data.get("username") or data.get("customer") or "Bilinmiyor"

product = product_name.lower().strip()

    cs2_allowed_product = "cs2 5 yıllık rozetli hesap mail değişen | hızlı"
    instagram_allowed_product = "1000 instagram takipçi | garantili telafili"

    if product == cs2_allowed_product:
        send_telegram(f"""
Yeni CS2 5 yıllık hesap siparişi geldi.

Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}

{get_lzt_links()}

Hesabı manuel kontrol edip satın al.
""")
        return {"ok": True, "type": "cs2"}

    if product == instagram_allowed_product:
        customer_link = find_customer_link(data)

        if not customer_link:
            send_telegram(f"""
Instagram 1000 takipçi siparişi geldi ama müşteri linki bulunamadı.

Itemsatış Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}

Render Logs içindeki ITEMSATIS WEBHOOK DATA kısmını kontrol et.
""")
            return {"ok": False, "error": "customer_link_not_found"}

        normalized_link = (
            customer_link.lower()
            .strip()
            .replace("https://", "")
            .replace("http://", "")
            .replace("www.", "")
            .rstrip("/")
        )

        if normalized_link in PROCESSED_LINKS:
            send_telegram(f"""
Aynı Instagram linki tekrar geldi.

Itemsatış Sipariş ID: {order_id}
Link: {customer_link}

Bu sipariş panele tekrar girilmedi.
""")
            return {"ignored": True, "reason": "duplicate_link"}

        if not SMM_API_URL or not SMM_API_KEY:
            send_telegram("SMM API ayarları eksik. Render Environment Variables kontrol et.")
            return {"ok": False, "error": "smm_api_missing"}

        balance_data = get_smm_balance()

        if "error" in balance_data:
            send_telegram(f"""
SMM bakiye alınamadı.

Itemsatış Sipariş ID: {order_id}
Hata:
{balance_data.get("error")}

Sipariş panele girilmedi.
""")
            return {"ok": False, "error": "balance_failed"}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")

        try:
            numeric_balance = float(balance)

            if currency.upper() == "USD":
                balance_tl = numeric_balance * 39
            else:
                balance_tl = numeric_balance

            if balance_tl <= 100:
                send_telegram(f"""
SMM panel bakiyesi 100 TL altına düştü.

Kalan Bakiye:
{balance} {currency}

Lütfen panel bakiyesini kontrol et.
""")
        except Exception as e:
            print("BALANCE CHECK ERROR:", str(e), flush=True)

        smm_result = create_smm_order(customer_link, 1000)

        if "error" in smm_result:
            send_telegram(f"""
Instagram 1000 takipçi siparişi panele girilemedi.

Itemsatış Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}
Link: {customer_link}

Panel Hatası:
{smm_result.get("error")}

Bakiye:
{balance} {currency}
""")
            return {"ok": False, "error": "smm_panel_error", "detail": smm_result}

        smm_order_id = smm_result.get("order", "Bilinmiyor")
        PROCESSED_LINKS.add(normalized_link)

        print(
            f"ORDER MAP | ITEMSATIS_ID={order_id} | SMM_ORDER_ID={smm_order_id} | LINK={customer_link}",
            flush=True
        )

        send_telegram(f"""
Instagram 1000 takipçi siparişi panele girildi.

Itemsatış Sipariş ID: {order_id}
SMM Sipariş ID: {smm_order_id}

Ürün: {product_name}
Müşteri: {buyer}
Link: {customer_link}

Bakiye:
{balance} {currency}
""")

        return {
            "ok": True,
            "type": "instagram_1000",
            "itemsatis_order_id": order_id,
            "smm_order_id": smm_order_id,
            "balance": balance,
            "currency": currency
        }

    print("IGNORED PRODUCT:", product_name, flush=True)
    return {"ignored": True, "product": product_name}


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()

    print("TELEGRAM WEBHOOK DATA:", data, flush=True)

    message = data.get("message", {})
    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != str(CHAT_ID):
        return {"ignored": True, "reason": "unauthorized_chat"}

    if text == "/start" or text == "/help":
        send_telegram("""
Bot komutları:

/balance - SMM panel bakiyesini gösterir
/status - Bot durumunu gösterir
/help - Komutları gösterir
""")
        return {"ok": True}

    if text == "/status":
        send_telegram("""
Bot aktif çalışıyor.

Render: Aktif
Telegram: Aktif
Itemsatış Webhook: Aktif
""")
        return {"ok": True}

    if text == "/balance":
        if not SMM_API_URL or not SMM_API_KEY:
            send_telegram("SMM API ayarları eksik.")
            return {"ok": False}

        balance_data = get_smm_balance()

        if "error" in balance_data:
            send_telegram(f"""
SMM bakiye alınamadı.

Hata:
{balance_data.get("error")}
""")
            return {"ok": False, "error": balance_data.get("error")}

        balance = balance_data.get("balance", "Bilinmiyor")
        currency = balance_data.get("currency", "")

        send_telegram(f"""
SMM Panel Bakiyesi:

Bakiye:
{balance} {currency}
""")

        return {"ok": True, "balance": balance, "currency": currency}

    send_telegram("""
Bilinmeyen komut.

Komutları görmek için:
/help
""")

    return {"ok": True}

@app.get("/my-ip")
def my_ip():
    response = requests.get("https://api.ipify.org?format=json", timeout=30)
    return response.json()
