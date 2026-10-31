"""Free-tier estimates for Neon, Render and UptimeRobot. Arithmetic only: no I/O.

Limits change; check the providers' pricing pages. These are the values the
usage page compares against.
"""
import calendar
import time
from datetime import datetime, timedelta, timezone

HOURS_PER_MONTH = 730
NEON_FREE_CU_HOURS = 100       # Per project per month on Neon Free.
NEON_MIN_CU = 0.25             # Smallest compute; set autoscaling max to this too.
NEON_FREE_STORAGE = 512 * 1024 * 1024
RENDER_FREE_HOURS = 750        # Per workspace per month, shared by all free services.
UPTIME_INTERVAL = 300          # UptimeRobot Free checks every 5 minutes.
RENDER_IDLE = 900              # Render Free sleeps after 15 minutes without inbound traffic.


def level(percent):
    return "success" if percent < 60 else "warning" if percent < 90 else "danger"


def neon(usage, storage=None):
    monthly_hours = usage["ratio"] * HOURS_PER_MONTH
    cu_hours = monthly_hours * NEON_MIN_CU
    percent = cu_hours / NEON_FREE_CU_HOURS * 100
    result = {"monthly_hours": monthly_hours, "cu_hours": cu_hours, "percent": percent,
              "tone": level(percent), "reliable": usage["elapsed"] >= 6 * 3600,
              "awake_hours": usage["awake"] / 3600, "elapsed_hours": usage["elapsed"] / 3600}
    if storage:
        used = storage["bytes"] / NEON_FREE_STORAGE * 100
        result.update(storage_mb=storage["bytes"] / 1024 / 1024, storage_percent=used,
                      storage_tone=level(used))
    return result


def render(started, now=None):
    now = now or time.time()
    local = datetime.fromtimestamp(now, timezone(timedelta(hours=3)))
    days = calendar.monthrange(local.year, local.month)[1]
    full_month = days * 24
    return {"uptime_hours": (now - started) / 3600, "full_month_hours": full_month,
            "fits": full_month <= RENDER_FREE_HOURS, "spare_hours": RENDER_FREE_HOURS - full_month}


def uptime(health, started, now=None):
    now = now or time.time()
    last = health.get("last", 0.0)
    silent = now - (last or started)
    # Only judge after the monitor has had time to call at least twice.
    expected = now - started > 2 * UPTIME_INTERVAL + 60
    return {"hits": health.get("hits", 0), "last": last, "silent_minutes": silent / 60,
            "warning": expected and silent > 2 * UPTIME_INTERVAL}


def telegram_line(usage):
    """Short memory-only status for /durum; nothing until the estimate is reliable."""
    estimate = neon(usage)
    if not usage["postgres"] or not estimate["reliable"]:
        return ""
    return (f"📊 Neon tahmini: ayda ~{estimate['cu_hours']:.0f} / {NEON_FREE_CU_HOURS} CU-saat "
            f"(%{estimate['percent']:.0f})")
