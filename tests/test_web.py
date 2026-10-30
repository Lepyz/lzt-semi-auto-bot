import re

import pytest
from fastapi.testclient import TestClient

from conftest import payload, receive_and_run
from main import create_app


@pytest.fixture
def client(rig):
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        # Exercise the HTTP endpoints without creating real background dispatches.
        client.app.state.engine.enqueue = rig.jobs.append
        client.auth = (rig.settings.username, rig.settings.password)
        yield client


def token(client, url="/admin"):
    response = client.get(url)
    assert response.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def test_health_and_legacy_uptime_routes_never_access_db(client, rig, monkeypatch):
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Uptime queried the database"))
    for path in ["/health", "/test", "/check-orders", "/check-services", "/check-balances", "/check-panel-health"]:
        assert client.get(path).status_code == 200
        assert client.head(path).status_code == 200
    assert not rig.panels.checks


def test_admin_auth_required(client):
    response = client.get("/admin", auth=("wrong", "wrong"))
    assert response.status_code == 401


def test_webhook_saved_and_duplicate_idempotent(client, rig):
    first = client.post("/itemsatis-webhook", json=payload())
    assert first.status_code == 200 and first.json()["status"] == "saved"
    again = client.post("/itemsatis-webhook", json=payload())
    assert again.json()["status"] == "already_saved"
    assert first.json()["id"] == again.json()["id"]
    assert not rig.panels.adds


def test_webhook_db_failure_returns_503_not_false_ack(client, rig, monkeypatch):
    monkeypatch.setattr(rig.store, "create", lambda _: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    response = client.post("/itemsatis-webhook", json=payload())
    assert response.status_code == 503


def test_form_encoded_legacy_webhook(client):
    response = client.post("/itemsatis-webhook", data={"payload": __import__("json").dumps(payload())})
    assert response.status_code == 200 and response.json()["status"] == "saved"


def test_invalid_body_is_not_silently_accepted(client):
    assert client.post("/itemsatis-webhook", content="invalid body").status_code == 400
    assert client.post("/itemsatis-webhook", json=[]).status_code == 400
    assert client.post("/itemsatis-webhook", content="x" * 262145).status_code == 413


def test_csrf_required_for_mutations(client):
    assert client.post("/admin/pause", data={"paused": "true"}).status_code == 403
    csrf = token(client)
    assert client.post("/admin/pause", data={"paused": "true", "csrf": csrf},
                       follow_redirects=False).status_code == 303


def test_all_admin_templates_render_without_secrets(client, rig):
    order = receive_and_run(rig)
    for path in ["/admin", "/admin/services", "/admin/packages", "/admin/orders/" + order["id"]]:
        response = client.get(path)
        assert response.status_code == 200
        assert "test-panel-secret" not in response.text
        assert rig.settings.password not in response.text


def test_missing_link_repair_form_and_manual_send(client, rig):
    data = payload()
    del data["post_datas"]
    response = client.post("/itemsatis-webhook", json=data)
    order_id = response.json()["id"]
    rig.engine.execute(order_id)
    path = "/admin/orders/" + order_id
    csrf = token(client, path)
    revision = rig.store.get(order_id)["revision"]
    response = client.post(path + "/repair", data={"csrf": csrf, "revision": revision,
                                                  "link": "https://instagram.com/customer"})
    assert response.status_code == 200
    assert not rig.panels.adds
    revision = rig.store.get(order_id)["revision"]
    response = client.post(path + "/send", data={"csrf": csrf, "revision": revision})
    assert response.status_code == 200
    assert rig.store.get(order_id)["state"] == "queued"


def test_telegram_requires_secret_and_explicit_chat_owner(client, rig):
    data = {"update_id": 1, "message": {"chat": {"id": 123}, "from": {"id": 123}, "text": "/status"}}
    assert client.post("/telegram-webhook", json=data).status_code == 401
    rig.settings.telegram_secret = "test-webhook-secret"
    rig.settings.chat_id = "123"
    response = client.post("/telegram-webhook", json=data,
                           headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"})
    assert response.status_code == 200
    assert not rig.store.pending_notifications()  # command replies aren't permanent logs


def test_group_callback_requires_explicit_user_allowlist(client, rig):
    rig.settings.telegram_secret, rig.settings.chat_id = "secret", "-123"
    order = receive_and_run(rig)
    data = {"callback_query": {"id": "cb1", "data": "send:" + order["id"],
                              "message": {"chat": {"id": -123}}, "from": {"id": 999}}}
    response = client.post("/telegram-webhook", json=data,
                           headers={"X-Telegram-Bot-Api-Secret-Token": "secret"})
    assert response.status_code == 200 and response.json()["ignored"]


def test_migration_gate_prevents_enabling_before_import(client, rig):
    rig.settings.require_import = True
    csrf = token(client)
    response = client.post("/admin/pause", data={"paused": "false", "csrf": csrf})
    assert response.status_code == 400


def test_service_binding_create_edit_and_delete(client, rig):
    csrf = token(client, "/admin/services")
    data = {"csrf": csrf, "advert_id": "20", "name": "Test ürün", "panel": "medyabayim",
            "service_id": "456", "quantity": "100", "platform": "tiktok"}
    assert client.post("/admin/services", data=data).status_code == 200
    assert rig.store.setting("binding:20")["components"][0]["service_id"] == "456"
    data["quantity"] = "200"
    assert client.post("/admin/services", data=data).status_code == 200
    assert rig.store.setting("binding:20")["components"][0]["quantity"] == 200
    assert client.post("/admin/services/delete", data={"csrf": csrf, "advert_id": "20"}).status_code == 200
    assert rig.store.setting("binding:20") is None


def test_real_background_lifespan_dispatches_saved_receipt(rig):
    import time
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=True)) as live:
        response = live.post("/itemsatis-webhook", json=payload())
        assert response.status_code == 200
        order_id = response.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and rig.store.get(order_id)["state"] != "submitted":
            time.sleep(0.02)
        assert rig.store.get(order_id)["state"] == "submitted"
        assert len(rig.panels.adds) == 1
