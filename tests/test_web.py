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


def wait_migration(client):
    import time
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = client.get("/api/migration-status").json()
        if result["state"] != "running":
            return result
        time.sleep(0.01)
    pytest.fail("Migration job did not finish")


def migration_source(monkeypatch):
    from test_migration import snapshot
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://redis.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "test-only-secret")
    monkeypatch.setattr("scripts.migrate_upstash.read_snapshot", snapshot)


def test_migration_page_never_reads_upstash_implicitly(client, monkeypatch):
    monkeypatch.setattr("scripts.migrate_upstash.read_snapshot",
                        lambda: pytest.fail("Opening a page must not query Upstash"))
    response = client.get("/admin/migration")
    assert response.status_code == 200
    assert "Eski kayıtları kontrol et" in response.text


def test_web_inspection_reads_counts_but_does_not_import(client, rig, monkeypatch):
    migration_source(monkeypatch)
    csrf = token(client, "/admin/migration")
    response = client.post("/admin/migration", data={"csrf": csrf, "mode": "inspect"})
    assert response.status_code == 200
    result = wait_migration(client)
    assert result["state"] == "done" and result["counts"]["pending_orders"] == 1
    assert rig.store.by_source("itemsatis:1") is None
    assert not rig.panels.adds


def test_web_import_requires_preview_paused_state_and_old_worker_confirmation(client, rig, monkeypatch):
    migration_source(monkeypatch)
    csrf = token(client, "/admin/migration")
    assert client.post("/admin/migration", data={"csrf": csrf, "mode": "import"}).status_code == 400
    rig.store.set_setting("paused", True)
    assert client.post("/admin/migration", data={"csrf": csrf, "mode": "import",
                                               "confirmed": "yes"}).status_code == 400
    client.post("/admin/migration", data={"csrf": csrf, "mode": "inspect"})
    assert wait_migration(client)["state"] == "done"
    assert client.post("/admin/migration", data={"csrf": csrf, "mode": "import"}).status_code == 400
    client.post("/admin/migration", data={"csrf": csrf, "mode": "import", "confirmed": "yes"})
    result = wait_migration(client)
    assert result["state"] == "done" and result["counts"]["active"] == 1
    assert rig.store.setting("migration_complete") is True
    assert rig.store.setting("paused") is True
    assert rig.store.by_source("itemsatis:1")["parts"][0]["smm_id"] == "700"
    assert not rig.panels.adds


def test_migration_error_never_exposes_connection_string(client, monkeypatch):
    migration_source(monkeypatch)
    def fail():
        raise RuntimeError("postgresql://SECRET-PASSWORD@private.invalid")
    monkeypatch.setattr("scripts.migrate_upstash.read_snapshot", fail)
    csrf = token(client, "/admin/migration")
    client.post("/admin/migration", data={"csrf": csrf, "mode": "inspect"})
    result = wait_migration(client)
    assert result["state"] == "error"
    assert "SECRET-PASSWORD" not in str(result)
    assert "SECRET-PASSWORD" not in client.get("/admin/migration").text


def test_migration_busy_blocks_other_mutations_and_status_uses_no_database(client, rig, monkeypatch):
    from threading import Event
    migration_source(monkeypatch)
    released, entered = Event(), Event()
    def delayed():
        from test_migration import snapshot
        entered.set()
        released.wait(timeout=3)
        return snapshot()
    monkeypatch.setattr("scripts.migrate_upstash.read_snapshot", delayed)
    csrf = token(client, "/admin/migration")
    client.post("/admin/migration", data={"csrf": csrf, "mode": "inspect"})
    assert entered.wait(timeout=1)
    try:
        assert client.post("/admin/pause", data={"csrf": csrf, "paused": "false"}).status_code == 409
        with monkeypatch.context() as scoped:
            scoped.setattr(rig.store, "transaction", lambda: pytest.fail("Status polling must use RAM"))
            assert client.get("/api/migration-status").json()["state"] == "running"
    finally:
        released.set()
    assert wait_migration(client)["state"] == "done"


def test_import_rechecks_source_instead_of_using_stale_preview(client, rig, monkeypatch):
    from test_migration import snapshot
    migration_source(monkeypatch)
    calls = []
    def source():
        calls.append(1)
        result = snapshot()
        if len(calls) == 2:
            result["processed_orders"].append("order:998")
        return result
    monkeypatch.setattr("scripts.migrate_upstash.read_snapshot", source)
    rig.store.set_setting("paused", True)
    csrf = token(client, "/admin/migration")
    client.post("/admin/migration", data={"csrf": csrf, "mode": "inspect"})
    assert wait_migration(client)["state"] == "done"
    client.post("/admin/migration", data={"csrf": csrf, "mode": "import", "confirmed": "yes"})
    assert wait_migration(client)["state"] == "done"
    assert rig.store.by_source("itemsatis:998") is not None
    assert len(calls) == 2


def test_services_page_lists_imported_bindings_on_every_database(client, rig):
    # Regression: on PostgreSQL the binding query raised ProgrammingError and
    # /admin/services returned Internal Server Error.
    for advert_id in ("5", "100", "20"):
        rig.store.set_setting("binding:" + advert_id, {
            "name": "Paket " + advert_id, "active": advert_id != "20",
            "components": [{"panel": "smmrush", "service_id": "11", "quantity": 50, "platform": "spotify"},
                           {"panel": "medyabayim", "service_id": "12", "quantity": 75, "platform": "spotify"}]})
    response = client.get("/admin/services")
    assert response.status_code == 200
    text = response.text
    assert text.index("Paket 5") < text.index("Paket 20") < text.index("Paket 100")
    assert set(rig.store.bindings()) == {"5", "10", "20", "100"}
    # An imported platform outside the default list stays selected when editing.
    assert "<option selected>spotify</option>" in text


def test_editing_imported_package_keeps_every_component(client, rig):
    import json
    csrf = token(client, "/admin/services")
    components = [{"panel": "smmrush", "service_id": "11", "quantity": "50", "platform": "tiktok", "name": "Beğeni"},
                  {"panel": "medyabayim", "service_id": "12", "quantity": "75", "platform": "tiktok", "name": ""}]
    response = client.post("/admin/services", data={"csrf": csrf, "advert_id": "30", "name": "Paket",
                                                   "active": "true", "components": json.dumps(components)})
    assert response.status_code == 200
    saved = rig.store.setting("binding:30")
    assert [(p["panel"], p["service_id"], p["quantity"]) for p in saved["components"]] == [
        ("smmrush", "11", 50), ("medyabayim", "12", 75)]
    bad = client.post("/admin/services", data={"csrf": csrf, "advert_id": "30", "components": "[1]"})
    assert bad.status_code == 400
    assert rig.store.setting("binding:30") == saved


def test_search_treats_wildcards_literally(client, rig):
    receive_and_run(rig, 1)
    assert client.get("/admin", params={"q": "%"}).text.count('href="/admin/orders/') == 0
    assert client.get("/admin", params={"q": "instagram.com/customer"}).text.count('href="/admin/orders/') == 1


def test_telegram_invalid_body_is_rejected_without_server_error(client, rig):
    rig.settings.telegram_secret = "secret"
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    assert client.post("/telegram-webhook", content="not json", headers=headers).status_code == 400
    assert client.post("/telegram-webhook", json=[1], headers=headers).status_code == 400


def test_csrf_cookie_is_secure_behind_https_proxy(client):
    response = client.get("/admin", headers={"X-Forwarded-Proto": "https"})
    assert "secure" in response.headers["set-cookie"].lower()
