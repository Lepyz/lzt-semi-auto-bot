import os
import requests
from fastapi import FastAPI, Request

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN veya CHAT_ID eksik")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    })

@app.get("/")
def home():
    return {"status": "bot çalışıyor"}

@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    data = await request.json()

    order_id = data.get("order_id", "Bilinmiyor")
    product_name = data.get("product_name", "Bilinmiyor")
    buyer = data.get("buyer", "Bilinmiyor")

    lzt_search_link = "https://lzt.market/steam/?order_by=price_to_up&title=5%20year%20medal%20cs2"

    message = f"""
Yeni sipariş geldi.

Sipariş ID: {order_id}
Ürün: {product_name}
Müşteri: {buyer}

LZT arama linki:
{lzt_search_link}

Hesabı manuel kontrol edip satın al.
"""

    send_telegram(message)

    return {"ok": True}
