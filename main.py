@app.post("/itemsatis-webhook")
async def itemsatis_webhook(request: Request):
    data = await request.json()

    print("ITEMSATIS WEBHOOK DATA:", data, flush=True)

    # TEST WEBHOOK KONTROLÜ
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

    # SİPARİŞ VERİLERİ
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

    # SADECE BU İLANA İZİN VER
    allowed_products = [
        "cs2 5 yıllık rozetli hesap mail değişen | hızlı"
    ]

    # ÜRÜN ADINI KÜÇÜLT
    product = product_name.lower().strip()

    # EŞLEŞMİYORSA BİLDİRİM GÖNDERME
    if product not in allowed_products:
        print("IGNORED PRODUCT:", product_name, flush=True)
        return {"ignored": True}

    # TELEGRAM MESAJI
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
