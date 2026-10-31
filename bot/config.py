import os
from dataclasses import dataclass, field


ALIASES = {"smm": "smmrush", "medya": "medyabayim", "lion": "lionfollow",
           "lf": "lionfollow", "morethan": "morethanpanel", "mtp": "morethanpanel"}


def panel_key(value):
    key = str(value or "").strip().lower()
    return ALIASES.get(key, key)


def load_panels():
    definitions = [
        ("smmrush", "SMMRush", "SMM", "https://smmrush.com/api/v2"),
        ("medyabayim", "MedyaBayim", "MEDYABAYIM", "https://medyabayim.com/api/v2"),
        ("lionfollow", "LionFollow", "LIONFOLLOW", "https://lionfollow.com/api/v2"),
        ("morethanpanel", "MoreThanPanel", "MORETHANPANEL", "https://morethanpanel.com/api/v2"),
        ("oldsmm", os.getenv("OldSmm", "OldSmm"), "OLDSMM", ""),
    ]
    definitions += [(f"panel{i}", os.getenv(f"PANEL{i}_NAME", f"Panel {i}"), f"PANEL{i}", "")
                    for i in range(4, 7)]
    return {key: {"name": name, "api_url": os.getenv(f"{prefix}_API_URL", url),
                  "api_key": os.getenv(f"{prefix}_API_KEY", "")}
            for key, name, prefix, url in definitions}


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    username: str = field(default_factory=lambda: os.getenv("ADMIN_USERNAME", "admin"))
    password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    chat_id: str = field(default_factory=lambda: os.getenv("CHAT_ID", ""))
    telegram_secret: str = field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_SECRET", ""))
    telegram_admins: str = field(default_factory=lambda: os.getenv("TELEGRAM_ADMIN_USER_IDS", ""))
    webhook_secret: str = field(default_factory=lambda: os.getenv("ITEMSATIS_WEBHOOK_SECRET", ""))
    # An environment secret is always enforced; a key created in the admin panel
    # is enforced only after Itemsatis has been seen using it.
    webhook_enforced: bool = field(default_factory=lambda: bool(os.getenv("ITEMSATIS_WEBHOOK_SECRET")))
    webhook_ips: str = field(default_factory=lambda: os.getenv("WEBHOOK_IP_WHITELIST", ""))
    require_import: bool = field(default_factory=lambda: os.getenv(
        "REQUIRE_LEGACY_IMPORT", "true" if os.getenv("UPSTASH_REDIS_REST_URL") else "false").lower() == "true")
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/"))
    workers: int = field(default_factory=lambda: max(1, min(8, int(os.getenv("ORDER_WORKERS", "4")))))
    check_interval: int = field(default_factory=lambda: max(300, int(os.getenv("BLOCKED_CHECK_INTERVAL_SECONDS", "900"))))
    active_check_interval: int = field(default_factory=lambda: max(900, int(os.getenv("ACTIVE_CHECK_INTERVAL_SECONDS", "1800"))))
    panels: dict = field(default_factory=load_panels)
