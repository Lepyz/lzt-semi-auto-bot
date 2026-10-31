"""Shared Turkish labels, reasons and notification policy. No network or storage."""
from .payloads import normalize_panel_status_text

STATES = {
    "queued": ("📥", "Sipariş alındı", "info"),
    "processing": ("🔄", "Gönderim hazırlanıyor", "info"),
    "sending": ("🔄", "Panel cevabı bekleniyor", "info"),
    "submitted": ("🟢", "Panele gönderildi", "success"),
    "waiting": ("⏳", "Aktif işlemi bekliyor", "warning"),
    "ready": ("🔔", "Gönderebilirsin — onayın bekleniyor", "warning"),
    "review": ("🛠️", "Bilgiler kontrol edilmeli", "warning"),
    "error": ("🔴", "Sipariş başlatılamadı", "danger"),
    "uncertain": ("⚠️", "Panelden kontrol gerekiyor", "danger"),
    "paused": ("⏸️", "Gönderim duraklatıldı", "warning"),
    "finished": ("✅", "Sonuçlandı", "success"),
    "closed": ("⚪", "Gönderilmeden kapatıldı", "muted"),
    "legacy": ("📁", "Eski işlem koruması", "muted"),
    "completed": ("✅", "Sipariş tamamlandı", "success"),
    "cancelled": ("⛔", "Panel iptal bildirdi", "danger"),
    "partial": ("🟠", "Sipariş kısmi sonuçlandı", "warning"),
    "refunded": ("↩️", "Panel iade bildirdi", "warning"),
    "failed": ("🔴", "Panel işlemi başarısız sonuçlandı", "danger"),
}

REASONS = {
    "binding_missing": ("Bu ilan otomasyona bağlı değil veya eşleştirmesi pasif.", "İstersen ilan ayarını web panelinden düzenleyebilirsin."),
    "link_missing": ("Müşteri linki eksik veya seçilen platformla uyumsuz.", "Linki düzeltip bilgileri kaydet. Kaydetmek sipariş göndermez."),
    "package_target": ("Paket bileşenlerinin hedef linkleri birbiriyle uyumlu değil.", "Paket servislerini ve müşteri linkini kontrol et."),
    "panel_config": ("Panel bağlantı bilgileri eksik.", "Bağlantı ayarlarını kontrol et; ardından kaydı tekrar incele."),
    "balance": ("Panel siparişi bakiye yetersizliği nedeniyle reddetti.", "Panel bakiyesini kendin kontrol et. Bot bakiye sorgulamaz."),
    "service": ("Seçilen panel servisi kullanılamıyor veya geçersiz.", "İlanın servis numarasını panelden kontrol edip düzelt."),
    "quantity": ("Panel gönderilecek adedi kabul etmedi.", "Servisin minimum ve maksimum adet sınırlarını kontrol et."),
    "duplicate": ("Panel aynı hedefteki başka bir işlem nedeniyle isteği reddetti.", "Paneldeki mevcut işlemi kontrol et; tekrar göndermeden önce sonucu doğrula."),
    "panel_rejected": ("Panel sipariş oluşturma isteğini reddetti.", "Paneldeki servis koşullarını ve sipariş bilgilerini kontrol et."),
    "uncertain": ("Panel cevabı kesinleşmedi; sipariş açılmış olabilir.", "Önce panelden kontrol et. Otomatik tekrar gönderim yapılmaz."),
    "active_target": ("Aynı hedef linkinde aktif veya sonucu belirsiz bir işlem var.", "Önceki işlem sonuçlandığında haber verilecek. Bu kayıt kendiliğinden gönderilmeyecek."),
    "earlier_hold": ("Aynı linkte daha önce alınmış, senin işlemini bekleyen bir kayıt var.", "Önce bu linkteki daha eski kaydı kontrol et."),
    "paused": ("Yeni gönderimler yönetim panelinden duraklatıldı.", "Gönderimleri açmak, daha önce tutulan kayıtları otomatik başlatmaz."),
    "legacy_duplicate": ("Bu bildirim eski sürümde işlenmiş.", "Çift siparişi önlemek için yeniden gönderilmedi."),
    "review": ("Sipariş bilgileri otomatik gönderim için yeterli değil.", "Ürün, hedef link ve servis bilgilerini web panelinden kontrol et."),
    "status_unavailable": ("Panelden güncel sipariş durumu alınamadı.", "Mevcut sipariş aktif kabul ediliyor. Son doğrulanmış durumu kontrol et."),
}


def reason_code(text, state=""):
    value = str(text or "").casefold()
    if state == "uncertain":
        return "uncertain"
    rules = [
        ("binding_missing", ("eşleştirmesi yok", "eşleştirme pasif", "aktif servis eşleştirmesi")),
        ("link_missing", ("müşteri linki", "invalid link", "invalid url", "incorrect link", "link format")),
        ("package_target", ("paket bileşenlerinin",)),
        ("panel_config", ("api bilgileri eksik", "panel bağlantı bilgileri", "invalid api key", "incorrect api key", "incorrect key", "unauthorized", "invalid key")),
        ("balance", ("balance", "funds", "bakiye", "yetersiz kredi")),
        ("quantity", ("quantity", "minimum", "maximum", "min order", "max order", "adet sınır", "adedi kabul")),
        ("service", ("invalid service", "incorrect service", "service not", "service is", "servis numarası", "panel servisi")),
        ("duplicate", ("duplicate", "already", "active order", "in progress order")),
        ("earlier_hold", ("daha önce alınmış",)),
        ("active_target", ("aynı linkte",)),
        ("paused", ("duraklat",)),
        ("legacy_duplicate", ("eski sürümde işlenmiş",)),
        ("uncertain", ("timeout", "cevabı alınamadı", "belirsiz", "kimliği döndürmedi", "json", "cevabı tanınmadı")),
    ]
    for code, patterns in rules:
        if any(pattern in value for pattern in patterns):
            return code
    return "panel_rejected" if state == "error" else "review"


def panel_kind(status):
    value = normalize_panel_status_text(status)
    groups = {
        "completed": {"completed", "complete", "completed successfully", "success", "successful", "finished", "done", "tamamlandi", "basarili"},
        "cancelled": {"cancelled", "canceled", "iptal", "iptal edildi"},
        "partial": {"partial", "partially completed", "kismi", "kismi iade"},
        "refunded": {"refunded", "refund", "iade", "iade edildi"},
        "failed": {"failed", "fail"},
    }
    return next((key for key, values in groups.items() if value in values), "")


def panel_label(status):
    kind = panel_kind(status)
    if kind:
        return STATES[kind][0] + " " + STATES[kind][1]
    value = normalize_panel_status_text(status)
    labels = {"pending": "İşleme alınmayı bekliyor", "queued": "Panel kuyruğunda", "processing": "İşleniyor",
              "in progress": "İşlem devam ediyor", "inprogress": "İşlem devam ediyor", "running": "İşlem devam ediyor"}
    return labels.get(value, "Henüz sorgulanmadı" if not value else "Panel durumu tanınmadı; panelden kontrol et")


def outcome(order):
    if order.get("state") != "finished":
        return order.get("state", "review")
    kinds = {panel_kind(part.get("status", "")) for part in order.get("parts", [])}
    if "partial" in kinds or "completed" in kinds and len(kinds) > 1:
        return "partial"
    if len(kinds) == 1 and next(iter(kinds), "") in STATES:
        return next(iter(kinds))
    if kinds and kinds <= {"cancelled", "refunded", "failed"}:
        return "cancelled"
    return "finished"


def order_view(order):
    code = outcome(order)
    icon, title, tone = STATES.get(code, STATES["review"])
    issue = order.get("reason_code") or reason_code(order.get("error"), order.get("state"))
    reason, advice = REASONS.get(issue, REASONS["review"])
    if issue == "status_unavailable":
        icon, title, tone = "⚠️", "Panel durumu doğrulanamıyor", "warning"
    if not order.get("error") and order.get("state") not in {"review", "error", "uncertain", "waiting", "paused"}:
        reason, advice = "", ""
    if code == "ready":
        reason, advice = "Önceki engel kalktı. Bu sipariş henüz panele gönderilmedi.", "Ürün, adet ve hedefi kontrol edip gönderimi onayla."
    if code == "review" and not order.get("error") and order.get("parts") and all(p.get("state") == "new" for p in order["parts"]):
        icon, title, tone = "📋", "Bilgiler kaydedildi — onayın bekleniyor", "info"
        reason = "Ürün, servis ve müşteri linki kaydedildi. Henüz yeni sipariş açılmadı."
        advice = "Gönderim özetini aç. Aktif hedef kontrolü gönderimde yeniden yapılır."
    if code == "closed" and issue != "legacy_duplicate":
        reason, advice = "Bu kayıt yönetici tarafından takipten çıkarıldı.", "Bu işlem yeni sipariş açmadı; panelde daha önce açılmış bileşenleri iptal etmez veya para iadesi yapmaz."
    if code in {"cancelled", "partial", "refunded", "failed"}:
        reason = "Panel bu sonucu bildirdi. Bu sonuç için ayrıntılı bir gerekçe doğrulanmadı."
        advice = "İade tutarı veya kalan miktar doğrulanmadı. Gerekirse panelden kontrol et; otomatik telafi siparişi açılmaz."
    return {"code": code, "icon": icon, "title": title, "tone": tone, "issue": issue,
            "reason": reason, "advice": advice,
            "actionable": order.get("state") in {"ready", "review", "error", "uncertain", "paused"} and issue != "binding_missing"}


def summary(order):
    def line(value):
        return " ".join(str(value).split())[:300]
    return (f"🧾 Kayıt: {order.get('itemsatis_id') or order['id'][:10]}\n"
            f"📦 Ürün: {line(order.get('product_name') or 'İlan ' + order.get('advert_id', ''))}\n"
            f"🔗 Hedef: {line(order.get('link') or next(iter(order.get('links', {}).values()), 'Link eksik'))}")


def alert(order, event):
    """Each distinct unsent purchase is reported; routine successes stay quiet."""
    view = order_view(order)
    state = order.get("state")
    if state not in {"ready", "waiting", "paused", "uncertain", "error", "review"} and view["code"] not in {"cancelled", "partial", "refunded", "failed"}:
        return None
    if view["issue"] == "binding_missing":
        return None
    panel = order.get("alert_panel") or next((p.get("panel", "") for p in reversed(order.get("parts", []))
                                             if p.get("state") in {"error", "uncertain", "sending"}), "") or next((p.get("panel", "") for p in order.get("parts", [])), "")
    key = order["id"] + ":" + event + ":" + str(order.get("revision", 0))
    if state == "finished":
        key = order["id"] + ":outcome:" + view["code"]
    title = ("Sipariş başlatılmadı — bekletildi" if state == "waiting" else
             "Sipariş başlatılmadı — duraklatıldı" if state == "paused" else view["title"])
    text = f"{view['icon']} {title.replace('i','İ').replace('ı','I').upper()}\n\n" + summary(order)
    if panel:
        text += "\nPanel: " + panel
    if order.get("previous_result"):
        text += "\nÖnceki işlem: " + order["previous_result"]
    text += "\n\nNeden: " + view["reason"] + "\n👉 " + view["advice"]
    return {"key": key, "text": text[:3500], "order_id": order["id"],
            "action": state == "ready", "grouped": False, "policy": "unsent-v2"}
