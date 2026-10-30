import logging
import queue
import threading

import requests

logger = logging.getLogger(__name__)


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
        # Private chat owner, or explicitly listed group admins; secret is mandatory.
        callbacks_allowed = (self.settings.telegram_secret and
                             (not self.settings.chat_id.startswith("-") or self.settings.telegram_admins))
        if notification.get("action") and callbacks_allowed:
            buttons.append({"text": "Siparişi gönder", "callback_data": "send:" + notification["order_id"]})
        if self.settings.public_url:
            buttons.append({"text": "Admin panelinde aç",
                            "url": self.settings.public_url + ("/admin/orders/" + notification["order_id"]
                                   if notification.get("order_id") else "/admin")})
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [buttons]}
        try:
            response = requests.post("https://api.telegram.org/bot" + self.settings.bot_token + "/sendMessage",
                                     json=payload, timeout=(5, 15))
            if response.status_code == 429 or response.status_code >= 500:
                return "retry"
            data = response.json()
            return "sent" if response.status_code == 200 and data.get("ok") else "failed"
        except (requests.RequestException, ValueError):
            return "failed"  # Delivery uncertain; don't flood the chat with retries.

    def deliver(self, item):
        if item.get("ephemeral"):
            self.send(item)
            return
        key = item["key"]
        if not self.store.claim_notification(key):
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
