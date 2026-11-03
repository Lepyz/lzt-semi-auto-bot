"""Offline payload parsing retained from the existing bot; no network calls."""
import ast
import json
import re
import hashlib
import html


from .links import PLATFORMS, normalize_panel_link, target_key, valid_link


def payload_variants(data):
    """Read common envelopes without allowing unbounded recursion."""
    queue = [(data, 0)]
    while queue:
        item, depth = queue.pop(0)
        if not isinstance(item, dict):
            continue
        yield normalize_payload_post_datas(item)
        if depth < 3:
            embedded = parse_embedded_itemsatis_payload(item)
            if embedded:
                queue.append((embedded, depth + 1))
            queue.extend((item[key], depth + 1) for key in ("payload", "data", "order", "purchase")
                         if isinstance(item.get(key), dict))


ORDER_ID_PATHS = ("order_id", "purchaseId", "purchase_id", "sale_id", "transaction_id",
                  "order.id", "order.order_id", "order.purchase_id", "purchase.id",
                  "purchase.order_id", "purchase.purchase_id", "details.order_id",
                  "details.purchaseId", "details.purchase_id", "details.order.id")
CHAT_WORDS = {"chat", "message", "review", "question", "support", "ticket", "comment"}
PURCHASE_WORDS = {"order", "siparis", "purchase", "sale", "satis", "satildi", "sold", "payment", "odeme", "paid"}


def explicit_order_id(data):
    """Only fields that name a purchase; a notification's generic id is not one."""
    for item in payload_variants(data):
        value = get_nested(item, *ORDER_ID_PATHS)
        if value not in ("", None, "Bilinmiyor"):
            return str(value)
    return ""


def get_order_id(data):
    variants = list(payload_variants(data))
    # Explicit order IDs must win over the notification/envelope's generic id.
    explicit = explicit_order_id(data)
    if explicit:
        return explicit
    if not purchase_event(data):
        return ""
    for item in variants:
        value = get_nested(item, "details.id", "data.id")
        if value not in ("", None):
            return str(value)
    for item in variants:
        value = item.get("id")
        if value not in ("", None):
            return str(value)
    return ""


def purchase_event(data):
    event = normalize_panel_status_text(get_event(data))
    return event in {"order created", "order create", "order paid", "order sold", "new order",
                     "purchase created", "purchase create", "purchase paid", "sale created", "sale paid",
                     "advert sold", "ilan satildi", "ilaniniz satildi", "siparis", "satildi", "sale", "purchase"}


def classify(data):
    """An advert or a generic notification ID is never evidence of a purchase."""
    event = normalize_panel_status_text(get_event(data))
    words = set(event.split())
    order_id, advert_id = get_order_id(data), get_advert_id(data)
    if words & CHAT_WORDS:
        return "ignore"
    if event in {"listing chat started", "listing chat", "chat started"}:
        return "ignore"
    # Listing lifecycle, payment reminders and existing-order status updates must
    # not become a fresh SMM purchase, even when they carry an order_id.
    if (not purchase_event(data) and words & {"updated", "update", "deleted", "expired", "renewed", "approved",
            "rejected", "cancelled", "canceled", "refunded", "completed", "shipped", "delivered", "status"}
            and not event == "payment completed"):
        return "ignore"
    if purchase_event(data):
        # Legacy Itemsatis sale notifications often have no purchase ID.
        # A known sale event + advert can proceed; binding/link checks still
        # happen before add. Exact webhook payloads are deduplicated.
        return "order" if advert_id else "review"
    if order_id and advert_id:
        return "order" if not event else "review"
    # A purchase in a changed format may lack the advert: keep it for review
    # instead of acknowledging it and losing it silently.
    if explicit_order_id(data) or words & PURCHASE_WORDS:
        return "review"
    if advert_id and customer_links(data) and get_sale_price(data)[0] is not None:
        return "review"  # A changed legacy sale format needs inspection, never auto-dispatch.
    return "ignore"


def ignored_summary(data):
    """What an ignored webhook looked like, without customer values."""
    event = normalize_panel_status_text(get_event(data))
    reason = ("Sohbet / mesaj bildirimi" if set(event.split()) & CHAT_WORDS or event in {"listing chat started", "listing chat", "chat started"}
              else "İlan güncelleme bildirimi" if event == "advert updated"
              else "Satın alma kanıtı yok; yalnızca ilan / bildirim bilgisi")
    return {"event": event[:60], "reason": reason,
            "fields": ", ".join(sorted(str(key)[:30] for key in data)[:12])}


def receipt_payload(data):
    safe = dict(data)
    safe.pop("_queue_id", None)
    safe.pop("processing_started_at", None)
    return json.dumps(safe, sort_keys=True, ensure_ascii=False, default=str)


def legacy_payload_key(data):
    """Exactly matches the previous bot's itemsatis_payload SHA1 algorithm."""
    return "legacy_payload:" + hashlib.sha1(receipt_payload(data).encode("utf-8", errors="ignore")).hexdigest()[:24]


def source_key(data):
    order_id = get_order_id(data)
    if order_id:
        return "itemsatis:" + order_id
    fingerprint = hashlib.sha256(receipt_payload(data).encode()).hexdigest()
    return "payload:" + fingerprint


def extract_links(data):
    result = {}
    for platform in (*PLATFORMS, "other"):
        link = find_order_link(data, platform)
        if valid_link(link, platform):
            result[platform] = normalize_panel_link(link, platform)
    return result


def normalize_text(text):
    return str(text or "").lower().strip()


def normalize_panel_status_text(value) -> str:
    text = str(value or "").strip().lower().replace("\u0307", "")
    if not text:
        return ""
    tr_map = str.maketrans({
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    })
    text = text.translate(tr_map)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def extract_panel_status(status_data: dict) -> str:
    """Panel status cevabını toleranslı okur.
    Farklı paneller status değerini root/result/data/order/response veya
    orders[0] gibi farklı seviyelerde döndürebiliyor. Tamamlandı/failed
    kararını sadece güvenilir status/state/order_status alanlarından verir.
    """
    status_keys = (
        "status", "Status",
        "state", "State",
        "order_status", "OrderStatus",
        "orderStatus", "order_state", "orderState",
    )

    def _read_direct(obj):
        if not isinstance(obj, dict):
            return ""
        for key in status_keys:
            value = obj.get(key)
            if value not in [None, ""]:
                normalized = normalize_panel_status_text(value)
                if normalized:
                    return normalized
        return ""

    if not isinstance(status_data, dict):
        return ""

    # Önce root seviyesini kontrol et.
    direct = _read_direct(status_data)
    if direct and direct not in {"success", "successful", "ok", "true", "200"}:
        return direct

    # Sonra sık kullanılan nested cevap formatları.
    for container_key in ("result", "data", "order", "response"):
        nested = status_data.get(container_key)
        if isinstance(nested, dict):
            found = _read_direct(nested)
            if found:
                return found
        elif isinstance(nested, list) and nested:
            for item in nested[:3]:
                found = _read_direct(item)
                if found:
                    return found

    # Bazı paneller orders: [{status: ...}] döndürür.
    orders = status_data.get("orders") or status_data.get("Orders")
    if isinstance(orders, list) and orders:
        for item in orders[:3]:
            found = _read_direct(item)
            if found:
                return found
    elif isinstance(orders, dict):
        found = _read_direct(orders)
        if found:
            return found

    return direct


def is_blocked_customer_asset_link(link: str) -> bool:
    """Itemsatış görsel/CDN linklerinin panele müşteri linki diye gitmesini engeller."""
    value = str(link or "").strip().lower()
    if not value:
        return True
    blocked_markers = [
        "cdn.itemsatis.com",
        "itemsatis.com/uploads",
        "/uploads/",
        "post_images",
        "product_images",
        "listing_images",
        "avatar",
    ]
    if any(marker in value for marker in blocked_markers):
        return True
    return bool(re.search(r"\.(?:jpg|jpeg|png|gif|webp|svg)(?:$|[?#])", value))


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


def parse_embedded_itemsatis_payload(data: dict) -> dict:
    """Itemsatış bazen asıl payload'u raw/raw_body içinde Python dict stringi olarak gönderir."""
    if not isinstance(data, dict):
        return {}
    for key in ["raw", "raw_body", "body", "payload"]:
        raw_value = data.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        raw_text = raw_value.strip()
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(raw_text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def parse_jsonish_post_datas(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return value
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else value
    except Exception:
        return value


def normalize_payload_post_datas(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    cloned = dict(data)
    keys = ("post_datas", "postData", "post_data")
    for key in keys:
        if key in cloned:
            cloned[key] = parse_jsonish_post_datas(cloned.get(key))
    for container_key in ("details", "data", "order", "purchase", "payload"):
        child = cloned.get(container_key)
        if isinstance(child, dict):
            child = dict(child)
            changed = False
            for key in keys:
                if key in child:
                    child[key] = parse_jsonish_post_datas(child.get(key))
                    changed = True
            if changed:
                cloned[container_key] = child
    return cloned


def extract_product_name_from_content(text: str) -> str:
    """'... başlıklı ilanınız 39.90 TL...' metninden gerçek ilan adını çeker."""
    text = str(text or "").strip()
    if not text:
        return ""
    patterns = [
        r"^(.*?)\s+başlıklı\s+ilanınız\s+",
        r"^(.*?)\s+baslikli\s+ilaniniz\s+",
        r"^(.*?)\s+başlıklı\s+ilaniniz\s+",
        r"^(.*?)\s+baslikli\s+ilanınız\s+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .:-|\n\t")
            if candidate and not is_generic_itemsatis_title(candidate):
                return candidate
    return ""


def get_event(data: dict) -> str:
    for payload in payload_variants(data):
        event = normalize_text(get_nested(payload, "event", "type", "action", "details.event", "data.event"))
        if event:
            return event
    return ""


def is_generic_itemsatis_title(value: str) -> bool:
    """Itemsatış webhooklarında gerçek ilan adı yerine gelen genel başlıkları filtreler.
    Türkçe büyük İ gibi karakterlerde Python lower() birleşik nokta üretebildiği için
    ASCII sadeleştirme de yapılır.
    """
    text = normalize_text(value)
    simplified = (
        text.replace("i̇", "i")
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    generic_values = {
        "ilanınız satıldı",
        "ilaniniz satildi",
        "advert sold",
        "advert_sold",
        "satıldı",
        "satildi",
        "order sold",
        "sipariş",
        "siparis",
    }
    generic_simplified = {
        item.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
        for item in generic_values
    }
    return text in generic_values or simplified in generic_simplified


def get_advert_id(data: dict) -> str:
    for payload in payload_variants(data):
        value = get_nested(
            payload,
            "advert.id", "details.advert.id", "data.advert.id",
            "advert_id", "details.advert_id", "data.advert_id",
            "advertId", "advert_id", "ilan_id", "ilan.id",
        )
        if value:
            return str(value)
    return ""


# Explicit price fields only. Keys such as fee, cost, commission or earning are
# deliberately not read: they are not what the buyer paid.
PRICE_PATHS = (
    "sale_price", "paid_price", "total_price", "order_price", "payment_amount",
    "order.total_price", "order.price", "purchase.total_price", "purchase.price",
    "payment.total", "payment.amount", "payment.price", "price", "total", "amount",
    "details.price", "details.total_price", "details.order_price", "details.sale_price", "details.paid_price",
    "details.payment.amount", "details.total", "details.amount",
    "data.price", "data.total_price", "data.order_price", "data.sale_price", "data.paid_price",
    "data.payment.amount", "data.total", "data.amount",
)


def parse_price(value):
    """'39.90', '39,90 TL', '1.250,00 ₺', 39.9 -> float; anything else -> None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if 0 < value < 1_000_000 else None
    text = str(value).strip().upper().replace("TL", "").replace("₺", "").replace("TRY", "").replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?", text):
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in text:
        text = text.replace(",", ".") if re.search(r",\d{1,2}$", text) else text.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")  # 1.250 = thousands
    number = float(text)
    return number if 0 < number < 1_000_000 else None


def get_sale_price(data):
    """The amount the buyer paid and the field it came from; (None, '') when absent."""
    for item in payload_variants(data):
        for path in PRICE_PATHS:
            value = get_nested(item, path)
            price = parse_price(value) if not isinstance(value, dict) else None
            if price:
                return round(price, 2), path
    # Only explicit sale phrases in messages qualify; arbitrary fee/commission
    # fields and product titles must never supply the buyer's payment amount.
    amount = r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:tl\b|₺)"
    patterns = (r"(?:satis|siparis|odeme)\s+(?:bedeli|tutari|fiyati|toplami)\s*[:=\-]?\s*" + amount,
                amount + r"\s*(?:tutarinda|bedelle|karsiliginda|fiyatina)?\s*satil(?:di|mistir)")
    candidates = {}
    for item in payload_variants(data):
        for field in ("content", "message", "description", "body", "text", "details.content", "details.message"):
            text = get_nested(item, field)
            if not isinstance(text, str):
                continue
            text = re.sub(r"<[^>]*>", " ", html.unescape(text)).casefold().replace("\u0307", "")
            text = text.translate(str.maketrans("ışğüöç", "isguoc"))
            for pattern in patterns:
                for match in re.finditer(pattern, text):
                    price = parse_price(match.group(1))
                    if price:
                        candidates[round(price, 2)] = "metin:" + field
    if len(candidates) == 1:
        return next(iter(candidates.items()))
    return None, ""


def get_product_name(data: dict) -> str:
    """Itemsatış ilan adını mümkün olan tüm alanlardan yakalar; genel webhook başlıklarını ürün adı sanmaz."""
    candidate_paths = [
        "advert.title", "advert.name", "advert.subject",
        "details.advert.title", "details.advert.name", "details.advert.subject",
        "data.advert.title", "data.advert.name", "data.advert.subject",
        "order.advert.title", "order.advert.name", "order.advert.subject",
        "purchase.advert.title", "purchase.advert.name", "purchase.advert.subject",
        "product_name", "product.title", "product.name",
        "details.product_name", "details.product.title", "details.product.name",
        "data.product_name", "data.product.title", "data.product.name",
        "order.product_name", "order.product.title", "order.product.name",
        "purchase.product_name", "purchase.product.title", "purchase.product.name",
        "content", "details.content", "data.content",
        "title", "name", "details.title", "data.title",
    ]

    for payload in payload_variants(data):
        for path in candidate_paths:
            value = get_nested(payload, path)
            if isinstance(value, dict):
                value = value.get("title") or value.get("name") or value.get("subject") or value.get("content") or ""
            value = str(value or "").strip()
            if not value:
                continue
            from_content = extract_product_name_from_content(value)
            if from_content:
                return from_content
            if value and not is_generic_itemsatis_title(value):
                return value

    # Son çare: tüm stringlerde "başlıklı ilanınız" kalıbını ara.
    for text in collect_strings(data):
        from_content = extract_product_name_from_content(text)
        if from_content:
            return from_content

    return ""




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


def customer_links(data):
    """Only buyer-supplied fields, never seller profiles, listing text or images."""
    result = []
    direct = ("url", "link", "profile_link", "account_link", "video_link", "post_link",
              "instagram", "instagram_link", "tiktok", "tiktok_link", "youtube", "youtube_link")
    notes = ("note", "message", "order_note", "customer_note", "content")
    for payload in payload_variants(data):
        for obj in (payload, payload.get("details", {})):
            if not isinstance(obj, dict):
                continue
            for key in ("post_datas", "postData", "post_data"):
                fields = parse_jsonish_post_datas(obj.get(key))
                if isinstance(fields, dict):
                    for label, value in fields.items():
                        label = normalize_panel_status_text(label)
                        if isinstance(value, str) and any(word in label for word in
                                ("link", "url", "profil", "kullanici", "username", "hesap", "kanal", "baglanti", "adres", "hedef")):
                            result.append(value.strip()[:500])
            result.extend(obj[key].strip()[:500] for key in direct if isinstance(obj.get(key), str) and obj[key].strip())
    if not result:
        # Legacy sale messages may embed a URL. Never extract a substring from an
        # untrusted hostname (e.g. evil.com/instagram.com/customer).
        for payload in payload_variants(data):
            for obj in (payload, payload.get("details", {})):
                if isinstance(obj, dict):
                    for key in notes:
                        text = obj.get(key)
                        if isinstance(text, str):
                            result.extend(re.findall(r"(?:https?://|www\.)[^\s<>'\"]+", text)[:10])
    return list(dict.fromkeys(value for value in result if value))[:10]


def find_order_link(data, platform=""):
    matches = {}
    for value in customer_links(data):
        # Trim wrapping punctuation, preserving dots in usernames.
        value = value.strip("\"'<> ()[]{};,!")
        if valid_link(value, platform):
            matches[target_key(value, platform)] = normalize_panel_link(value, platform)
    # Two different targets require a human choice, never silently pick the first.
    return next(iter(matches.values())) if len(matches) == 1 else ""
