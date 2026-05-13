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

    order_id = data.get("order_id", "Bilinmiyor")
    product_name = data.get("product_name", "Bilinmiyor")
    buyer = data.get("buyer", "Bilinmiyor")

    message = f"""
Yeni sipariş geldi.

Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}

{get_lzt_links()}

Hesabı manuel kontrol edip satın al.
"""

    send_telegram(message)

    return {"ok": True}
