"""Loss guard: estimated profit before an order is sent. No storage of its own."""
import time

DEFAULTS = {"mode": "observe", "min_profit": 10.0, "commission": 0.07}
MODES = {"off": "Kapalı", "observe": "Gözlem (hesaplar, engellemez)", "enforce": "Koruma açık (engeller)"}
CODES = {"low_profit", "cost_unknown", "price_unknown"}


def money(value):
    if value is None:
        return "hesaplanamadı"
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text + " TL"


def guard_settings(store):
    saved = store.setting("profit_guard", {}) or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def evaluate(order, panels, guard):
    """Profit = sale price - Itemsatis commission - current panel cost of every component."""
    sale = order.get("sale_price")
    parts, unknown, total = [], [], 0.0
    for part in order.get("parts", []):
        info = panels.service_rate(part["panel"], part["service_id"])
        if not info:
            unknown.append({"panel": part["panel"], "service_id": part["service_id"]})
            continue
        per_order = "package" in info["type"].lower()
        cost = info["rate"] if per_order else info["rate"] * int(part["quantity"]) / 1000
        total += cost
        parts.append({"panel": part["panel"], "service_id": part["service_id"], "quantity": part["quantity"],
                      "rate": info["rate"], "per_order": per_order, "cost": round(cost, 2)})
    commission = round(sale * guard["commission"], 2) if sale else None
    cost = None if unknown or not order.get("parts") else round(total, 2)
    profit = round(sale - commission - cost, 2) if sale and cost is not None else None
    ok = profit is not None and profit >= guard["min_profit"]
    if not sale:
        code, message = "price_unknown", "Bildirimde satış fiyatı bulunamadı; kâr hesaplanamadı."
    elif cost is None:
        missing = ", ".join(f"{u['panel']} / servis {u['service_id']}" for u in unknown) or "servis yok"
        code, message = "cost_unknown", f"Panel servis fiyatı alınamadı ({missing}); kâr hesaplanamadı."
    elif not ok:
        code, message = "low_profit", f"Tahmini kâr {money(profit)}, sınır {money(guard['min_profit'])}."
    else:
        code, message = "", ""
    return {"ok": ok, "code": code, "message": message, "at": time.time(), "sale": sale,
            "source": order.get("price_source", ""), "commission_rate": guard["commission"],
            "commission": commission, "cost": cost, "profit": profit, "min_profit": guard["min_profit"],
            "parts": parts, "unknown": unknown}


def lines(check):
    """Short Turkish breakdown for alerts."""
    rate = round(check.get("commission_rate", 0) * 100, 1)
    return (f"💰 Satış: {money(check.get('sale'))} · Komisyon (%{rate:g}): {money(check.get('commission'))}\n"
            f"🏷️ Panel maliyeti: {money(check.get('cost'))} · Tahmini kâr: {money(check.get('profit'))} "
            f"(sınır {money(check.get('min_profit'))})")
