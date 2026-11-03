"""Estimated profit after the fixed Itemsatis commission; no polling or own storage."""
import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

from .payloads import PRICE_PATHS

COMMISSION = Decimal("0.07")
CENT = Decimal("0.01")
DEFAULTS = {"mode": "enforce", "min_profit": 0.0, "commission": float(COMMISSION)}
MODES = {"off": "Kapalı", "observe": "Gözlem (hesaplar, engellemez)", "enforce": "Koruma açık (engeller)"}
CODES = {"low_profit", "cost_unknown", "price_unknown"}


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def rounded(value):
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP)) if value is not None else None


def money(value):
    value = number(value)
    if value is None:
        return "hesaplanamadı"
    text = f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text + " TL"


def guard_settings(store):
    saved = store.setting("profit_guard", {}) or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in {"mode", "min_profit"}}}


def sale_amount(order):
    source = order.get("price_source", "")
    # The old 'metin' fallback could be a commission or fee. Require confirmation.
    trusted = source == "manual" or source in PRICE_PATHS or (
        order.get("price_version") == 2 and source.startswith("metin:"))
    value = number(order.get("sale_price")) if trusted else None
    return value if value is not None and 0 < value < 1_000_000 else None


def calculation(order, guard, cost, parts, unknown, at=None):
    sale = sale_amount(order)
    minimum = number(guard["min_profit"])
    commission = (sale * COMMISSION).quantize(CENT, rounding=ROUND_HALF_UP) if sale is not None else None
    net = sale - commission if sale is not None else None
    cost = cost.quantize(CENT, rounding=ROUND_HALF_UP) if cost is not None else None
    profit = net - cost if net is not None and cost is not None else None
    ok = profit is not None and profit >= minimum
    if sale is None:
        code, message = "price_unknown", "Satış fiyatı güvenilir biçimde bulunamadı; Itemsatış'taki tutarı webden doğrula."
    elif cost is None:
        code, message = "cost_unknown", "Panel servis fiyatı alınamadı; kâr hesaplanamadı."
    elif not ok:
        code, message = "low_profit", f"Tahmini kâr {money(profit)}, sınır {money(minimum)}."
    else:
        code, message = "", ""
    def target(required):
        if cost is None:
            return None
        price = ((cost + required) / (1 - COMMISSION)).quantize(CENT, rounding=ROUND_CEILING)
        while price - (price * COMMISSION).quantize(CENT, rounding=ROUND_HALF_UP) - cost < required:
            price += CENT
        while price >= CENT and (price - CENT) - ((price - CENT) * COMMISSION).quantize(CENT, rounding=ROUND_HALF_UP) - cost >= required:
            price -= CENT
        return float(price)
    return {"version": 2, "ok": ok, "code": code, "message": message, "at": at if at is not None else time.time(),
            "sale": rounded(sale), "source": order.get("price_source", ""), "commission_rate": float(COMMISSION),
            "commission": rounded(commission), "net_sale": rounded(net), "cost": rounded(cost), "profit": rounded(profit),
            "margin": rounded(profit / sale * 100) if profit is not None else None,
            "break_even_sale": target(Decimal(0)), "target_sale": target(minimum), "min_profit": float(minimum),
            "parts": parts, "unknown": unknown}


def evaluate(order, panels, guard):
    """Current service prices, summed before rounding; packages are per purchase."""
    parts, unknown, total = [], [], Decimal(0)
    for part in order.get("parts", []):
        info = panels.service_rate(part["panel"], part["service_id"])
        rate = number(info.get("rate")) if info else None
        if rate is None or not 0 <= rate <= 1_000_000_000:
            unknown.append({"panel": part["panel"], "service_id": part["service_id"]})
            continue
        per_order = "package" in info["type"].lower()
        cost = rate if per_order else rate * int(part["quantity"]) / 1000
        total += cost
        parts.append({"panel": part["panel"], "service_id": part["service_id"], "quantity": part["quantity"],
                      "rate": float(rate), "per_order": per_order, "cost": rounded(cost)})
    cost = None if unknown or not order.get("parts") else total
    return calculation(order, guard, cost, parts, unknown)


def reprice(order, guard):
    """Manual sale correction reuses the cost snapshot; it never calls a panel."""
    old = order.get("profit") or {}
    return calculation(order, guard, number(old.get("cost")), old.get("parts", []), old.get("unknown", []), old.get("at"))


def lines(check):
    return (f"💰 Satış: {money(check.get('sale'))} · Komisyon (%7): {money(check.get('commission'))}\n"
            f"💵 Komisyon sonrası: {money(check.get('net_sale'))} · Panel: {money(check.get('cost'))}\n"
            f"📊 Tahmini kâr: {money(check.get('profit'))} (sınır {money(check.get('min_profit'))})")
