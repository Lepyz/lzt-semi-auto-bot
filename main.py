import os
import requests
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


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


@app.get("/test")
def test_message():
    message = f"""
Test siparişi geldi.

Sipariş ID: 12345
Ürün: CS2 5 Year Medal
Müşteri: test_user

{get_lzt_links()}
"""
    send_telegram(message)
    return {"ok": True, "message": "Telegram test mesajı gönderildi"}


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

    allowed_products = [
        "cs2 5 yıllık rozetli hesap mail değişen | hızlı"
    ]

    product = product_name.lower().strip()

    if product not in allowed_products:
        print("IGNORED PRODUCT:", product_name, flush=True)
        return {"ignored": True, "product": product_name}

    message = f"""
Yeni CS2 5 yıllık hesap siparişi geldi.

Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}

{get_lzt_links()}

Hesabı manuel kontrol edip satın al.
"""

    send_telegram(message)

    return {"ok": True}
