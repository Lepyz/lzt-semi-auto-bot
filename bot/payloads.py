"""Offline payload parsing retained from the existing bot; no network calls."""
import ast
import json
import re
import hashlib
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


PLATFORMS = {
    "instagram": ("instagram.com", "instagr.am"),
    "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "x": ("x.com", "twitter.com"),
    "twitter": ("x.com", "twitter.com"),
    "twitch": ("twitch.tv",),
    "kick": ("kick.com",),
    "facebook": ("facebook.com", "fb.watch"),
    "telegram": ("t.me", "telegram.me"),
}


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


def get_order_id(data):
    variants = list(payload_variants(data))
    # Explicit order IDs must win over the notification/envelope's generic id.
    paths = ("order_id", "purchaseId", "purchase_id", "sale_id", "transaction_id",
             "order.id", "order.order_id", "order.purchase_id", "purchase.id",
             "purchase.order_id", "purchase.purchase_id", "details.order_id",
             "details.purchaseId", "details.purchase_id", "details.order.id")
    for item in variants:
        value = get_nested(item, *paths)
        if value not in ("", None, "Bilinmiyor"):
            return str(value)
    for item in variants:
        value = get_nested(item, "details.id", "data.id")
        if value not in ("", None):
            return str(value)
    for item in variants:
        value = item.get("id")
        if value not in ("", None):
            return str(value)
    return ""


def classify(data):
    """Unknown order-shaped messages are saved for review, never silently lost."""
    event = normalize_panel_status_text(get_event(data))
    words = set(event.split())
    order_id, advert_id = get_order_id(data), get_advert_id(data)
    if words & {"chat", "message", "review", "question", "support", "ticket", "comment"}:
        return "ignore"
    if event in {"listing chat started", "listing chat", "chat started", "advert updated"}:
        return "ignore"
    purchase = any(term in event for term in ("order created", "order create", "order paid",
                   "purchase created", "purchase create", "purchase paid", "sale created",
                   "sale paid", "advert sold", "ilan satildi", "ilaniniz satildi", "new order"))
    purchase = purchase or event in {"siparis", "satildi", "sale", "purchase"}
    if purchase:
        return "order" if order_id and advert_id else "review"
    if order_id and advert_id:
        return "order" if not event else "review"
    return "review" if advert_id else "ignore"


def source_key(data):
    order_id = get_order_id(data)
    if order_id:
        return "itemsatis:" + order_id
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                            default=str).encode()).hexdigest()
    return "payload:" + fingerprint


def valid_link(link, platform):
    value = normalize_panel_link(link, platform)
    if not value or is_blocked_customer_asset_link(value):
        return False
    parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return False
    allowed = PLATFORMS.get(platform)
    if not allowed:
        allowed = tuple(domain for domains in PLATFORMS.values() for domain in domains)
    return bool(parsed.path.strip("/")) and any(host == d or host.endswith("." + d) for d in allowed)


def target_key(link, platform=""):
    """Canonicalize tracking parameters, preserving case-sensitive video IDs."""
    parsed = urlparse(normalize_panel_link(link, platform))
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host == "twitter.com":
        host = "x.com"
    path = parsed.path.rstrip("/")
    if host in {"instagram.com", "tiktok.com"}:
        path = path.lower()
    query = dict(parse_qsl(parsed.query))
    if host in {"youtu.be", "youtube.com"}:
        video = path.lstrip("/") if host == "youtu.be" else query.get("v")
        if path.startswith(("/shorts/", "/embed/")):
            video = path.split("/")[2]
        if video:
            return "youtube.com/watch?v=" + video
    kept = [(k, v) for k, v in parse_qsl(parsed.query)
            if not k.lower().startswith(("utm_", "_")) and k.lower() not in {"si", "igsh", "feature"}]
    if host in {"instagram.com", "tiktok.com"}:
        kept = []
    return host + path + ("?" + urlencode(sorted(kept)) if kept else "")


def extract_links(data):
    result = {}
    for platform in (*PLATFORMS, "other"):
        link = find_order_link(data, platform)
        if valid_link(link, platform):
            result[platform] = normalize_panel_link(link, platform)
    return result

def normalize_text(text: str) -> str:
    return str(text or "").lower().strip()


def normalize_instagram_link(link: str) -> str:
    link = str(link or "").strip()
    if not link:
        return ""
    if link.startswith("@"):
        link = f"https://www.instagram.com/{link[1:]}"
    if not re.match(r"^https?://", link, re.IGNORECASE):
        if "instagram.com" not in link.lower() and "instagr.am" not in link.lower():
            link = f"https://www.instagram.com/{link.lstrip('@')}"
        else:
            link = "https://" + link

    # Sadece Instagram için soru işaretinden sonrasını temizle.
    # YouTube/TikTok/X gibi platformlarda ?v= veya benzeri kısımlar linkin parçası olabilir.
    link = link.split("?")[0].split("#")[0]
    link = link.rstrip("/")
    return link


def normalize_tiktok_link(link: str) -> str:
    """TikTok paylaşım linklerini aynı hedef için kanonik hale getirir.

    TikTok aynı profil/video linkine _r, _t, utm vb. geçici query parametreleri
    ekleyebiliyor. Pending aynı-link koruması bu parametreler yüzünden kaçmasın
    diye TikTok linklerinde query ve fragment temizlenir. Kısa vt/vm linkleri
    canlı resolve edilmez; sadece üzerindeki query temizlenir.
    """
    link = str(link or "").strip()
    if not link:
        return ""

    if link.startswith("@"):
        handle = link.split("?", 1)[0].split("#", 1)[0].strip().lstrip("@").strip("/")
        return f"https://www.tiktok.com/@{handle}" if handle else ""

    lower = link.lower()
    if not lower.startswith(("http://", "https://")):
        if "tiktok.com" in lower:
            link = "https://" + link.lstrip("/")
        else:
            return link

    try:
        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").rstrip("/")
        if not host:
            return link.split("?", 1)[0].split("#", 1)[0].rstrip("/")

        canonical_host = host
        if host in {"tiktok.com", "m.tiktok.com", "www.tiktok.com"}:
            canonical_host = "www.tiktok.com"

        # Query/fragment TikTok hedefini değil paylaşım izleme parametrelerini taşır.
        return urlunparse((parsed.scheme or "https", canonical_host, path or "/", "", "", "")).rstrip("/")
    except Exception:
        return link.split("?", 1)[0].split("#", 1)[0].rstrip("/")


def is_tiktok_platform_or_link(link: str = "", platform: str = "") -> bool:
    platform = normalize_text(platform)
    link_text = str(link or "").lower()
    return platform in {"tiktok", "tik_tok", "tt"} or "tiktok.com" in link_text or "vm.tiktok.com" in link_text or "vt.tiktok.com" in link_text


def normalize_panel_link(link: str, platform: str = "") -> str:
    link = str(link or "").strip()
    platform = normalize_text(platform)

    if not link:
        return ""

    if platform == "instagram":
        return normalize_instagram_link(link)

    if is_tiktok_platform_or_link(link, platform):
        return normalize_tiktok_link(link)

    if not re.match(r"^https?://", link, re.IGNORECASE) and "." in link.split("/")[0]:
        link = "https://" + link
    return link


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


def find_order_link(data: dict, platform: str = "") -> str:
    """Müşterinin girdiği gerçek sosyal medya linkini bulur.

    ÖNEMLİ GÜVENLİK KURALI:
    Itemsatış webhook içinde ilan görseli gibi CDN linkleri de gelebiliyor.
    Paket sisteminde bu CDN linki yanlışlıkla panele gönderilmesin diye,
    platform belli ise sadece o platformun domainlerini kabul ederiz.
    Link bulunamazsa boş döner ve sipariş panele gönderilmez.
    """
    platform = normalize_text(platform)

    priority_paths = [
        # Önce müşterinin doldurduğu post_datas alanları
        "post_datas.Profil Linki",
        "post_datas.Link",
        "post_datas.Video Linki",
        "post_datas.Gönderi Linki",
        "post_datas.Kanal Linki",
        "post_datas.TikTok Linki",
        "post_datas.Instagram Linki",
        "post_datas.YouTube Linki",
        "post_datas.Youtube Linki",
        "details.post_datas.Profil Linki",
        "details.post_datas.Link",
        "details.post_datas.Video Linki",
        "details.post_datas.Gönderi Linki",
        "details.post_datas.Kanal Linki",
        "details.post_datas.TikTok Linki",
        "details.post_datas.Instagram Linki",
        "details.post_datas.YouTube Linki",
        "details.post_datas.Youtube Linki",
        "data.post_datas.Profil Linki",
        "data.post_datas.Link",
        "data.post_datas.Video Linki",
        "data.post_datas.Gönderi Linki",
        "data.post_datas.Kanal Linki",
        "data.post_datas.TikTok Linki",
        "data.post_datas.Instagram Linki",
        "data.post_datas.YouTube Linki",
        "data.post_datas.Youtube Linki",
        # Sonra açık link alanları
        "url", "link", "profile_link", "account_link", "video_link", "post_link",
        "instagram", "instagram_link", "tiktok", "tiktok_link", "youtube", "youtube_link",
        "details.url", "details.link", "details.instagram_link", "details.tiktok_link", "details.youtube_link",
        "data.url", "data.link", "data.instagram_link", "data.tiktok_link", "data.youtube_link",
        # Not alanları en son; burada ilan görseli/linki de olabilir, bu yüzden domain filtresi uygulanır.
        "note", "message", "order_note", "customer_note",
        "details.note", "details.message", "details.order_note", "details.customer_note",
        "data.note", "data.message", "data.order_note", "data.customer_note",
    ]

    platform_domains = {
        "instagram": ["instagram.com"],
        "tiktok": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
        "youtube": ["youtube.com", "youtu.be"],
        "x": ["x.com", "twitter.com"],
        "twitter": ["x.com", "twitter.com"],
        "twitch": ["twitch.tv"],
        "kick": ["kick.com"],
        "facebook": ["facebook.com", "fb.watch"],
        "telegram": ["t.me", "telegram.me"],
    }

    blocked_url_markers = [
        "cdn.itemsatis.com",
        "itemsatis.com/uploads",
        "/uploads/",
        "post_images",
        "product_images",
        "advert_images",
        "ilan-resim",
    ]
    blocked_extensions = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".avif")

    def clean_candidate(value: str) -> str:
        v = str(value or "").strip()
        # Noktalama/HTML kırıntılarını temizle
        return v.strip().strip("'\"<>.,;)])}")

    def is_asset_or_itemsatis_image(value: str) -> bool:
        v = str(value or "").strip().lower()
        if not v:
            return True
        if any(marker in v for marker in blocked_url_markers):
            return True
        no_query = v.split("?")[0]
        if no_query.endswith(blocked_extensions):
            return True
        return False

    def has_allowed_platform_domain(value: str) -> bool:
        v = str(value or "").lower()
        domains = platform_domains.get(platform, [])
        return bool(domains and any(domain in v for domain in domains))

    def looks_like_link(value: str) -> bool:
        v = clean_candidate(value).lower()
        if not v:
            return False
        if is_asset_or_itemsatis_image(v):
            return False

        domains = platform_domains.get(platform, [])

        # Instagram kullanıcı adı desteklenir.
        if platform == "instagram" and v.startswith("@") and len(v) > 2:
            return True

        # Platform belliyse sadece o platformun domainleri kabul edilir.
        # Böylece cdn.itemsatis.com ilan görseli TikTok linki sanılmaz.
        if domains:
            return any(domain in v for domain in domains)

        # Platform other/general ise asset olmayan genel URL kabul edilir.
        if v.startswith("http://") or v.startswith("https://"):
            return True
        if "." in v and " " not in v:
            return True
        return False

    # Öncelikli alanlarda tek alan direkt link ise al.
    # Önemli: Itemsatış bazen asıl alanları raw string içindeki dict olarak gönderir;
    # bu yüzden hem ana payload hem raw içindeki gömülü payload taranır.
    for payload in payload_variants(data):
        for path in priority_paths:
            value = get_nested(payload, path)
            if isinstance(value, str) and looks_like_link(value):
                return normalize_panel_link(clean_candidate(value), platform)

    all_strings = collect_strings(data)
    joined = "\n".join(all_strings)

    # Platform belliyse önce sadece o platformun domainini ara.
    domains = platform_domains.get(platform, [])
    if platform == "instagram":
        match = re.search(r"(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._/\-?=&%]+", joined, re.IGNORECASE)
        if match:
            candidate = clean_candidate(match.group(0))
            if not is_asset_or_itemsatis_image(candidate):
                return normalize_panel_link(candidate, platform)
        for text in all_strings:
            text = clean_candidate(text)
            if text.startswith("@") and len(text) > 2:
                return normalize_panel_link(text, platform)
        return ""

    if domains:
        domain_pattern = "|".join(re.escape(d) for d in domains)
        match = re.search(rf"(?:https?://)?(?:www\.)?(?:{domain_pattern})/[^\s<>'\"]+", joined, re.IGNORECASE)
        if match:
            value = clean_candidate(match.group(0))
            if not value.startswith("http"):
                value = "https://" + value
            if not is_asset_or_itemsatis_image(value):
                return normalize_panel_link(value, platform)
        return ""

    # Platform bilinmiyorsa genel URL ara ama ilan görseli/CDN linklerini reddet.
    for match in re.finditer(r"https?://[^\s<>'\"]+", joined, re.IGNORECASE):
        candidate = clean_candidate(match.group(0))
        if not is_asset_or_itemsatis_image(candidate):
            return normalize_panel_link(candidate, platform)

    return ""
