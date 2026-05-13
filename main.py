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

    response = requests.post(SMM_API_URL, data=payload, timeout=30)
    print("SMM BALANCE RESPONSE:", response.text, flush=True)

    return response.json()


def create_smm_order(link: str, quantity: int = 1000):
    payload = {
        "key": SMM_API_KEY,
        "action": "add",
        "service": INSTAGRAM_1000_SERVICE_ID,
        "link": link,
        "quantity": quantity
    }

    response = requests.post(SMM_API_URL, data=payload, timeout=30)
    print("SMM ORDER RESPONSE:", response.text, flush=True)

    return response.json()


@app.get("/test")
def test_message():
    send_telegram("Test mesajı geldi. Bot aktif çalışıyor.")
    return {"ok": True}


@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    data = await request.json()

    print("ITEMSATIS WEBHOOK DATA:", data, flush=True)

    if data.get("details", {}).get("test") is True:
        message = f"""
Itemsatış webhook test mesajı geldi.

Başlık:
{data.get("title")}

İçerik:
{data.get("content")}
"""
        send_telegram(message)
        return {"ok": True, "type": "test"}

    order_id = (
        data.get("order_id")
        or data.get("id")
        or "Bilinmiyor"
    )

    product_name = (
        data.get("product_name")
        or data.get("product")
        or data.get("title")
        or ""
    )

    buyer = (
        data.get("buyer")
        or data.get("username")
        or data.get("customer")
        or "Bilinmiyor"
    )

    product = product_name.lower().strip()

    cs2_allowed_product = "cs2 5 yıllık rozetli hesap mail değişen | hızlı"
    instagram_allowed_product = "1000 instagram takipçi | garantili telafili"

    if product == cs2_allowed_product:
        message = f"""
Yeni CS2 5 yıllık hesap siparişi geldi.

Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}

{get_lzt_links()}

Hesabı manuel kontrol edip satın al.
"""
        send_telegram(message)
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

        normalized_link = customer_link.lower().strip().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")

        if normalized_link in PROCESSED_LINKS:
            send_telegram(f"""
Aynı Instagram linki tekrar geldi.

Itemsatış Sipariş ID: {order_id}
Link: {customer_link}

Bu sipariş panele tekrar girilmedi.
""")
            print("DUPLICATE LINK IGNORED:", normalized_link, flush=True)
            return {"ignored": True, "reason": "duplicate_link"}

        if not SMM_API_URL or not SMM_API_KEY:
            send_telegram("SMM API ayarları eksik. Render Environment Variables kontrol et.")
            return {"ok": False, "error": "smm_api_missing"}

        try:
            balance_data = get_smm_balance()
        except Exception as e:
            send_telegram(f"""
SMM bakiye kontrolü başarısız oldu.

Itemsatış Sipariş ID: {order_id}
Hata: {str(e)}

Sipariş panele girilmedi.
""")
            return {"ok": False, "error": "balance_check_failed"}

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

        try:
            smm_result = create_smm_order(customer_link, 1000)
        except Exception as e:
            send_telegram(f"""
Instagram 1000 takipçi siparişi panele girilemedi.

Itemsatış Sipariş ID: {order_id}
Link: {customer_link}
Hata: {str(e)}
""")
            return {"ok": False, "error": "smm_order_failed"}

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
