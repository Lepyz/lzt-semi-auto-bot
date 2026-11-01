"""Bounded purchase history and in-flight progress markers; no I/O."""
from .presentation import order_view, panel_label, summary

IN_FLIGHT = {"queued", "processing", "sending"}
STALLED_AFTER = 300
HISTORY_LIMIT = 10


def phase(order):
    return (order.get("state"), tuple((p.get("state"), p.get("smm_id", "")) for p in order.get("parts", [])))


def phase_since(order):
    return order.get("phase_started_at", order.get("updated_at", order["created_at"]))


def annotate(previous, order, now):
    """Capture actual transitions only; metadata edits cannot reset the stall timer."""
    entries = list((previous or {}).get("history") or [])
    def add(title, detail="", panel=""):
        entries.append({"at": now, "title": title, "detail": detail[:200], "panel": panel})
    if previous is None:
        add("Sipariş kaydedildi" if order["state"] in {"queued", "review"} else "Eski kayıt içe alındı")
    if previous is None or phase(previous) != phase(order):
        order.update(phase_started_at=now, phase_revision=order.get("revision", 0))
    else:
        order.update(phase_started_at=phase_since(previous), phase_revision=previous.get("phase_revision", 0))
    if previous is None or order["state"] == "queued" and previous["state"] != "queued":
        order["dispatch_revision"] = order.get("revision", 0)
    else:
        order["dispatch_revision"] = previous.get("dispatch_revision", 0)
    state_changed = previous and (previous["state"] != order["state"] or order_view(previous)["code"] != order_view(order)["code"])
    if (previous is None and order["state"] == "review") or state_changed:
        view = order_view(order)
        title = view["title"]
        if order["state"] == "queued":
            title = "Gönderimi onayladın" if previous["state"] in {"waiting", "ready", "paused", "review", "error"} else "Gönderim sırasına alındı"
        add(title, view["reason"])
    if previous:
        for index, part in enumerate(order.get("parts", [])):
            old = previous.get("parts", [])[index] if index < len(previous.get("parts", [])) else {}
            detail = "Servis " + str(part.get("service_id", ""))
            if part.get("smm_id"):
                detail += " · Panel no: " + str(part["smm_id"])
            if part.get("smm_id") and part.get("smm_id") != old.get("smm_id"):
                add("Panel siparişi kaydedildi", detail, part.get("panel", ""))
            elif not state_changed and part.get("status") and panel_label(part["status"]) != panel_label(old.get("status", "")):
                add(panel_label(part["status"]), detail, part.get("panel", ""))
        if (order.get("sale_price"), order.get("price_source")) != (previous.get("sale_price"), previous.get("price_source")):
            add("Satış tutarı güncellendi", "%7 komisyon hesabı yenilendi.")
        if order["state"] == previous["state"] == "review" and (
                order.get("link"), order.get("advert_id")) != (previous.get("link"), previous.get("advert_id")):
            add("Sipariş bilgileri güncellendi", "Bilgiler kaydedildi; gönderim için onay gerekiyor.")
        if order.get("status_error") and not previous.get("status_error"):
            add("Panel durumu doğrulanamıyor", "Son doğrulanmış durum ve aktif işlem koruması korunuyor.")
        elif previous.get("status_error") and not order.get("status_error"):
            add("Panel durumuna yeniden ulaşıldı")
    order["history"] = entries[-HISTORY_LIMIT:]


def is_stalled(order, now):
    return bool(order and order.get("state") in IN_FLIGHT and now - phase_since(order) >= STALLED_AFTER * 1_000_000)


def stalled_notice(order, now):
    minutes = max(5, int((now - phase_since(order)) / 60_000_000))
    stage = order_view(order)["title"]
    return {"key": order["id"] + ":stalled:" + str(order.get("dispatch_revision", 0)),
            "kind": "stalled", "phase_revision": order.get("phase_revision", 0),
            "dispatch_revision": order.get("dispatch_revision", 0), "order_id": order["id"],
            "text": ("⚠️ SİPARİŞ İLERLEMİYOR\n\n" + summary(order) +
                     f"\n\nAşama: {stage}\nBu aşamada en az {minutes} dakikadır ilerleme yok.\n"
                     "👉 Kaydı ve paneli kontrol et. Panelde sipariş açılmış olabilir. Bu uyarı otomatik tekrar gönderim yapmaz."),
            "action": False, "policy": "order-events-v3"}
