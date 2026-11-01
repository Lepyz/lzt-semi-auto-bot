import re

import pytest
from fastapi.testclient import TestClient

from bot.panels import PanelClient
from bot.payloads import get_sale_price, parse_price
from conftest import payload
from main import create_app


def priced(number=1, price="49,90 TL", link="https://www.instagram.com/customer"):
    data = payload(number, link)
    data["price"] = price
    return data


def run(rig, data):
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order["id"])
    return rig.store.get(order["id"])


def enforce(rig, minimum=10):
    rig.store.set_setting("profit_guard", {"mode": "enforce", "min_profit": minimum, "commission": 0.07})


@pytest.mark.parametrize("value,expected", [
    ("39.90", 39.9), ("39,90 TL", 39.9), ("1.250,00 ₺", 1250.0), ("1,250.50", 1250.5),
    (39.9, 39.9), ("12", 12.0), ("abc", None), ("0", None), (True, None), (None, None), ("39.9.9", None),
])
def test_price_parsing(value, expected):
    assert parse_price(value) == expected


def test_sale_price_ignores_fee_and_cost_fields_and_reads_message_text():
    assert get_sale_price({"fee": "5", "cost": "3", "commission": "2"}) == (None, "")
    assert get_sale_price({"data": {"price": "49,90"}}) == (49.9, "data.price")
    assert get_sale_price({"details": {"content": "Takipçi başlıklı ilanınız 39.90 TL tutarında satıldı"}}) == (39.9, "metin:details.content")


def test_observe_mode_records_profit_but_never_blocks(rig):
    rig.panels.rates[("smmrush", "123")] = {"rate": 400.0, "type": "Default"}  # 100 adet = 40 TL
    order = run(rig, priced(price="45,00"))
    assert order["state"] == "submitted" and len(rig.panels.adds) == 1
    assert order["sale_price"] == 45.0 and order["price_source"] == "price"
    check = order["profit"]
    assert check["cost"] == 40.0 and check["commission"] == 3.15 and check["profit"] == 1.85 and not check["ok"]


def test_enforce_holds_low_profit_once_and_override_sends_once(rig):
    enforce(rig)
    rig.panels.rates[("smmrush", "123")] = {"rate": 400.0, "type": "Default"}
    order = run(rig, priced(price="45,00"))
    assert order["state"] == "review" and order["reason_code"] == "low_profit"
    assert not rig.panels.adds
    alerts = [n for n in rig.notices if n["order_id"] == order["id"]]
    assert len(alerts) == 1 and "Tahmini kâr: 1,85 TL" in alerts[0]["text"] and "sınır 10,00 TL" in alerts[0]["text"]
    # A plain send is refused with the reason and changes nothing.
    with pytest.raises(ValueError, match="kâr onayını"):
        rig.engine.approve(order["id"], order["revision"])
    assert rig.store.get(order["id"])["state"] == "review"
    rig.engine.approve(order["id"], order["revision"], profit_override=True)
    rig.engine.execute(order["id"])
    sent = rig.store.get(order["id"])
    assert sent["state"] == "submitted" and len(rig.panels.adds) == 1
    assert not sent.get("profit_override")  # consumed by this one send


def test_enforce_holds_unknown_cost_and_missing_price(rig):
    enforce(rig)
    rig.panels.rates[("smmrush", "123")] = None
    unknown_cost = run(rig, priced(1, "99,90", "https://www.instagram.com/one"))
    assert unknown_cost["state"] == "review" and unknown_cost["reason_code"] == "cost_unknown"
    rig.panels.rates[("smmrush", "123")] = {"rate": 10.0, "type": "Default"}
    no_price = run(rig, payload(2, "https://www.instagram.com/two"))
    assert no_price["state"] == "review" and no_price["reason_code"] == "price_unknown"
    assert not rig.panels.adds


def test_enough_profit_is_sent_automatically(rig):
    enforce(rig)
    rig.panels.rates[("smmrush", "123")] = {"rate": 100.0, "type": "Default"}  # 10 TL
    order = run(rig, priced(price="49,90"))
    assert order["state"] == "submitted" and order["profit"]["profit"] == 36.41
    assert len(rig.notices) == 1 and rig.notices[0]["key"].endswith(":submitted")


def test_package_type_is_priced_per_order_and_components_are_summed(rig):
    enforce(rig)
    binding = rig.store.setting("binding:10")
    binding["components"].append(dict(binding["components"][0], panel="medyabayim", service_id="77"))
    rig.store.set_setting("binding:10", binding)
    rig.panels.rates[("smmrush", "123")] = {"rate": 100.0, "type": "Default"}   # 100 adet -> 10 TL
    rig.panels.rates[("medyabayim", "77")] = {"rate": 25.0, "type": "Package"}  # per order -> 25 TL
    order = run(rig, priced(price="49,90"))
    assert order["profit"]["cost"] == 35.0 and order["profit"]["profit"] == 11.41
    assert order["state"] == "submitted" and len(rig.panels.adds) == 2


def test_waiting_order_is_rechecked_with_current_price_when_sent(rig):
    enforce(rig)
    rig.panels.rates[("smmrush", "123")] = {"rate": 100.0, "type": "Default"}
    first = run(rig, priced(1, "49,90"))
    second = run(rig, priced(2, "49,90"))
    assert first["state"] == "submitted" and second["state"] == "waiting"
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.refresh(first["id"])
    ready = rig.store.get(second["id"])
    assert ready["state"] == "ready"
    rig.panels.rates[("smmrush", "123")] = {"rate": 450.0, "type": "Default"}  # price went up: 45 TL
    with pytest.raises(ValueError, match="Tahmini kâr"):
        rig.engine.approve(second["id"], ready["revision"])
    assert len(rig.panels.adds) == 1


def test_panel_service_list_is_cached_and_failures_back_off(monkeypatch):
    now = [1000]
    monkeypatch.setattr("bot.panels.time.monotonic", lambda: now[0])
    calls = []
    class Reply:
        status_code = 200
        def __init__(self, data):
            self.data = data
        def json(self):
            return self.data
    replies = [None, [{"service": 5, "rate": "12,5", "type": "Default"}, {"service": "6", "rate": "x"}]]
    def fake_post(url, data=None, timeout=None, allow_redirects=None):
        calls.append(data["action"])
        reply = replies.pop(0)
        if reply is None:
            raise __import__("requests").ConnectionError("down")
        return Reply(reply)
    monkeypatch.setattr("bot.panels.requests.post", fake_post)
    client = PanelClient({"p": {"name": "P", "api_url": "https://p.invalid/api", "api_key": "k"}})
    assert client.service_rate("p", "5") is None
    assert client.service_rate("p", "5") is None          # no repeated request during the outage
    now[0] += 61
    assert client.service_rate("p", "5") == {"rate": 12.5, "type": "Default"}
    assert client.service_rate("p", 5) == {"rate": 12.5, "type": "Default"}
    assert client.service_rate("p", "6") is None          # unparsable rate = unknown
    assert calls == ["services", "services"]


@pytest.fixture
def client(rig):
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        client.app.state.engine.enqueue = rig.jobs.append
        client.auth = (rig.settings.username, rig.settings.password)
        yield client


def token(client, url):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(url).text).group(1)


def test_settings_preview_override_and_csv(client, rig):
    csrf = token(client, "/admin/integrations")
    assert client.post("/admin/integrations/profit", data={"csrf": csrf, "mode": "enforce", "min_profit": "abc",
                                                           "commission": "7"}).status_code == 400
    assert client.post("/admin/integrations/profit", data={"csrf": csrf, "mode": "enforce", "min_profit": "10",
                                                           "commission": "7"}).status_code == 200
    assert rig.store.setting("profit_guard") == {"mode": "enforce", "min_profit": 10.0, "commission": 0.07}
    rig.panels.rates[("smmrush", "123")] = {"rate": 400.0, "type": "Default"}
    order = run(rig, priced(price="45,00"))
    page = client.get("/admin/orders/" + order["id"] + "?preview=1").text
    assert "Tahmini kâr: 1,85 TL" in page and 'name="profit_override"' in page
    assert "Fiyat kaynağı: Itemsatış bildirimi" in page
    csrf = token(client, "/admin/orders/" + order["id"])
    refused = client.post("/admin/orders/" + order["id"] + "/send",
                          data={"csrf": csrf, "revision": order["revision"], "confirmed": "yes"})
    assert refused.status_code == 400 and rig.store.get(order["id"])["state"] == "review"
    accepted = client.post("/admin/orders/" + order["id"] + "/send",
                           data={"csrf": csrf, "revision": order["revision"], "confirmed": "yes", "profit_override": "yes"})
    assert accepted.status_code == 200 and rig.store.get(order["id"])["state"] == "queued"
    rows = client.get("/admin/export").text.splitlines()
    assert rows[0].endswith("Satış (TL);Komisyon (TL);Panel maliyeti (TL);Tahmini kâr (TL)")
    assert any(row.endswith("45,00;3,15;40,00;1,85") for row in rows[1:])
