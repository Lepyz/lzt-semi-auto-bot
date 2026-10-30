import sys
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture
def rig(tmp_path):
    settings = Settings(database_url="sqlite:///" + str(tmp_path / "test.sqlite"),
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
