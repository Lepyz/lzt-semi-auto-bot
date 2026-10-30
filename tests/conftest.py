import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import Settings
from bot.engine import Engine
from bot.panels import AddResult
from bot.store import Store


class FakePanels:
    def __init__(self):
        self.adds = []
        self.checks = []
        self.results = []
        self.current = {"status": "In progress", "terminal": False}

    def add(self, part, link):
        self.adds.append((dict(part), link))
        return self.results.pop(0) if self.results else AddResult("submitted", str(1000 + len(self.adds)))

    def status(self, part):
        self.checks.append(dict(part))
        return self.current


def disposable_postgres():
    """Dedicated test database only; production DATABASE_URL is never read here."""
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("Dedicated PostgreSQL test URL not provided")
    if not urlparse(url).path.rstrip("/").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end with _test")
    store = Store(url)
    store.initialize()
    with store.transaction() as conn:
        conn.execute("TRUNCATE orders, settings, target_locks, notifications")
    return url


# Every engine/web test also runs on PostgreSQL: SQLite hides driver differences.
@pytest.fixture(params=["sqlite", "postgres"])
def rig(request, tmp_path):
    url = (disposable_postgres() if request.param == "postgres"
           else "sqlite:///" + str(tmp_path / "test.sqlite"))
    settings = Settings(database_url=url,
                        password="test-admin-password", bot_token="", chat_id="", telegram_secret="",
                        telegram_admins="", webhook_secret="", webhook_ips="", public_url="",
                        require_import=False, panels={
                            "smmrush": {"name": "SMMRush", "api_url": "https://panel.invalid/api",
                                        "api_key": "test-panel-secret"},
                            "medyabayim": {"name": "MedyaBayim", "api_url": "https://other.invalid/api",
                                          "api_key": "other-test-secret"}})
    store = Store(settings.database_url)
    store.initialize()
    store.set_setting("paused", False)
    store.set_setting("binding:10", {
        "name": "Takipçi", "active": True,
        "components": [{"panel": "smmrush", "service_id": "123", "quantity": 100,
                        "platform": "instagram"}]})
    panels = FakePanels()
    notices, jobs = [], []
    notifier = SimpleNamespace(enqueue=notices.append)
    engine = Engine(store, panels, notifier, settings)
    engine.enqueue = jobs.append
    yield SimpleNamespace(settings=settings, store=store, panels=panels, engine=engine,
                          notices=notices, jobs=jobs, notifier=notifier)
    engine.close()


def payload(number=1, link="https://www.instagram.com/customer"):
    return {"event": "order.created", "order_id": str(number), "advert_id": "10",
            "product_name": "Takipçi", "post_datas": {"Link": link}}


def receive_and_run(rig, number=1, link="https://www.instagram.com/customer"):
    order, _ = rig.engine.receive(payload(number, link))
    rig.engine.execute(order["id"])
    return rig.store.get(order["id"])
