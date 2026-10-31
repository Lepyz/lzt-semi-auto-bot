import logging
import queue
import threading

import requests

logger = logging.getLogger(__name__)


def callbacks_allowed(settings):
    """Private chat owner, or explicitly listed group admins; secret is mandatory."""
    return bool(settings.telegram_secret and settings.chat_id and
                (not settings.chat_id.startswith("-") or settings.telegram_admins.strip()))


def telegram_api(settings, method, payload=None):
    """Explicit admin-triggered call. The bot token never appears in errors or logs."""
    if not settings.bot_token:
        raise ValueError("Render Environment içinde BOT_TOKEN tanımlı değil.")
    try:
        response = requests.post("https://api.telegram.org/bot" + settings.bot_token + "/" + method,
                                 json=payload or {}, timeout=(5, 15))
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ValueError("Telegram'a ulaşılamadı; biraz sonra tekrar deneyin.") from None
    if not isinstance(data, dict) or not data.get("ok"):
        raise ValueError("Telegram isteği reddetti. Bot erişimini, sohbet iznini ve bağlantı ayarlarını kontrol edin.")
    return data.get("result")


def register_telegram_webhook(settings, secret):
    if not settings.public_url.startswith("https://"):
        raise ValueError("Uygulamanın HTTPS adresi bulunamadı (RENDER_EXTERNAL_URL).")
    telegram_api(settings, "setWebhook", {
        "url": settings.public_url + "/telegram-webhook", "secret_token": secret,
        "allowed_updates": ["message", "callback_query"], "drop_pending_updates": False})


class Notifier:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None

    def enqueue(self, notification):
        self.queue.put(notification)

    def start(self):
        self.store.recover_notifications()
        for item in self.store.pending_notifications():
            self.enqueue(item)
        self.thread = threading.Thread(target=self.run, daemon=True, name="telegram")
        self.thread.start()

    def send(self, notification):
        if not self.settings.bot_token or not self.settings.chat_id:
            return "disabled"
        if notification.get("callback_id"):
            try:
                response = requests.post(
                    "https://api.telegram.org/bot" + self.settings.bot_token + "/answerCallbackQuery",
                    json={"callback_query_id": notification["callback_id"], "text": notification["text"][:180],
                          "show_alert": True}, timeout=(5, 10))
                return "sent" if response.status_code == 200 else "failed"
            except requests.RequestException:
                return "failed"
        payload = {"chat_id": self.settings.chat_id, "text": notification["text"],
                   "disable_web_page_preview": True}
        buttons = []
        if self.settings.public_url:
            destination = ("/admin/orders/" + notification["order_id"]
                           if notification.get("order_id") else "/admin?view=inbox")
            if notification.get("action"):
                destination += "?preview=1"
            buttons.append({"text": "Kontrol edip gönder" if notification.get("action") else
                            "İşlem bekleyenleri aç" if notification.get("grouped") else "Siparişi aç",
                            "url": self.settings.public_url + destination})
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [buttons]}
        if notification.get("menu"):
            payload["reply_markup"] = {"keyboard": [["📋 Bekleyenler", "⚠️ Sorunlar"], ["🟢 Bot durumu", "🔎 Sipariş ara"]],
                                       "resize_keyboard": True}
        try:
            response = requests.post("https://api.telegram.org/bot" + self.settings.bot_token + "/sendMessage",
                                     json=payload, timeout=(5, 15))
            if response.status_code == 429 or response.status_code >= 500:
                return "retry"
            data = response.json()
            return "sent" if response.status_code == 200 and isinstance(data, dict) and data.get("ok") else "failed"
        except (requests.RequestException, ValueError):
            return "failed"  # Delivery uncertain; don't flood the chat with retries.

    def deliver(self, item):
        if item.get("ephemeral"):
            self.send(item)
            return
        key = item["key"]
        if not self.store.claim_notification(key):
            return
        # Old pending routine notices must not reappear after this upgrade.
        if (any(event in key for event in (":submitted:", ":waiting:", ":paused:")) or
                ":review:" in key and "eşleştirmesi yok" in item.get("text", "")):
            self.store.finish_notification(key, True)
            return
        result = self.send(item)
        self.store.finish_notification(key, result in {"sent", "disabled"})
        if result == "retry":
            self.store.retry_notification(key)
            row = self.store.notification(key)
            if row and row["state"] == "pending" and not self.stop_event.wait(10):
                self.enqueue(item)

    def run(self):
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.deliver(item)
            except Exception as exc:
                logger.error("notification_failed type=%s", type(exc).__name__)
            finally:
                self.queue.task_done()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=22)
