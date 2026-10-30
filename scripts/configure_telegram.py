"""Register the bot webhook with its secret. Run explicitly after deployment."""
import os
import requests


def main():
    token = os.getenv("BOT_TOKEN", "")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    base = os.getenv("PUBLIC_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
    if not token or not secret or not base.startswith("https://"):
        print("BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET ve HTTPS PUBLIC_BASE_URL gerekli.")
        return 1
    try:
        response = requests.post("https://api.telegram.org/bot" + token + "/setWebhook",
                                 json={"url": base + "/telegram-webhook", "secret_token": secret,
                                       "allowed_updates": ["message", "callback_query"],
                                       "drop_pending_updates": False}, timeout=(5, 20))
        if response.status_code == 200 and response.json().get("ok"):
            print("Telegram webhook kaydedildi. Bekleyen güncellemeler silinmedi.")
            return 0
    except (requests.RequestException, ValueError):
        pass
    print("Webhook kaydı doğrulanamadı. Anahtar değerleri yazdırılmadı.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
