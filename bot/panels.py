"""Panel calls have no balance requests, circuit database writes or add retries."""
import threading
from dataclasses import dataclass

import requests

from .payloads import extract_panel_status, normalize_panel_status_text
from .presentation import REASONS, reason_code


TERMINAL = {
    "completed", "complete", "completed successfully", "success", "successful",
    "finished", "done", "tamamlandi", "basarili", "cancelled", "canceled",
    "partial", "partially completed", "refunded", "refund", "failed", "fail",
    "iptal", "iptal edildi", "kismi", "kismi iade", "iade", "iade edildi",
}


@dataclass
class AddResult:
    state: str  # submitted, error or uncertain
    order_id: str = ""
    error: str = ""


class PanelClient:
    def __init__(self, panels):
        self.panels = panels
        self.limits = {key: threading.BoundedSemaphore(2) for key in panels}

    def request(self, key, action, **fields):
        panel = self.panels.get(key, {})
        if not panel.get("api_url") or not panel.get("api_key"):
            raise ValueError("Panel API bilgileri eksik: " + key)
        with self.limits[key]:
            return requests.post(panel["api_url"],
                                 data={"key": panel["api_key"], "action": action, **fields},
                                 timeout=(5, 20), allow_redirects=False)

    def add(self, part, link):
        try:
            response = self.request(part["panel"], "add", service=part["service_id"],
                                    quantity=part["quantity"], link=link)
        except ValueError:
            return AddResult("error", error="Panel API bilgileri eksik.")
        except requests.RequestException:
            return AddResult("uncertain", error="Panel cevabı alınamadı. Panelden kontrol edin; otomatik tekrar yapılmadı.")
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            return AddResult("uncertain", error="Panel HTTP cevabı belirsiz; panelden kontrol edin.")
        try:
            data = response.json()
        except ValueError:
            return AddResult("uncertain", error="Panel geçerli JSON döndürmedi; panelden kontrol edin.")
        if not isinstance(data, dict):
            return AddResult("uncertain", error="Panel sipariş cevabı tanınmadı.")
        if data.get("error"):
            # Do not store API keys, raw request exceptions or arbitrary response bodies.
            return AddResult("error", error=REASONS[reason_code(str(data["error"]), "error")][0])
        value = data.get("order") or data.get("order_id") or data.get("id")
        if not value and isinstance(data.get("data"), dict):
            value = data["data"].get("order") or data["data"].get("order_id")
        value = str(value or "").strip()
        if response.status_code >= 400 or not value.isdigit() or int(value) <= 0:
            return AddResult("uncertain", error="Panel geçerli sipariş kimliği döndürmedi.")
        return AddResult("submitted", order_id=value)

    def status(self, part):
        try:
            response = self.request(part["panel"], "status", order=part["smm_id"])
            if response.status_code != 200:
                return None
            data = response.json()
            if not isinstance(data, dict) or data.get("error"):
                return None
            status = extract_panel_status(data)
            if not status:
                return None
            # Preserve the actual provider status for display.
            def original(obj, depth=0):
                if depth > 4:
                    return ""
                if isinstance(obj, dict):
                    for key in ("status", "Status", "state", "State", "order_status", "OrderStatus",
                                "orderStatus", "order_state", "orderState"):
                        value = obj.get(key)
                        if value and normalize_panel_status_text(value) == status:
                            return str(value)
                    for key in ("result", "data", "order", "response", "orders", "Orders"):
                        found = original(obj.get(key), depth + 1)
                        if found:
                            return found
                elif isinstance(obj, list):
                    for child in obj[:3]:
                        found = original(child, depth + 1)
                        if found:
                            return found
                return ""
            raw = original(data) or status
            return {"status": str(raw)[:100], "terminal": status in TERMINAL}
        except (requests.RequestException, ValueError, KeyError):
            return None
