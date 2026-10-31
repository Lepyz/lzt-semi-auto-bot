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


def test_inbox_ignores_intentionally_unmapped_adverts_but_keeps_all_records(client, rig):
    rig.store.delete_binding("10")
    order = receive_and_run(rig)
    path = 'href="/admin/orders/' + order["id"]
    assert path not in client.get("/admin?view=inbox").text
    assert path in client.get("/admin?view=all").text


def test_preview_and_attention_do_not_send_or_notify(client, rig):
    rig.store.set_setting("paused", True)
    order = receive_and_run(rig)
    path = "/admin/orders/" + order["id"]
    before = rig.store.get(order["id"])
    preview = client.get(path + "?preview=1")
    assert preview.status_code == 200 and "Gönderim önizlemesi" in preview.text
    assert rig.store.get(order["id"]) == before
    csrf = token(client, path)
    assert client.post(path + "/send", data={"csrf": csrf, "revision": before["revision"]}).status_code == 400
    assert client.post(path + "/attention", data={"csrf": csrf, "revision": before["revision"]}).status_code == 200
    assert rig.store.get(order["id"])["handling"] is True
    assert not rig.panels.adds and not rig.store.pending_notifications()


def test_cancelled_result_is_never_displayed_as_green_completed(client, rig):
    order = receive_and_run(rig)
    rig.panels.current = {"status": "Canceled", "terminal": True}
    rig.engine.refresh(order["id"])
    for path in ["/admin?view=finished", "/admin/orders/" + order["id"]]:
        text = client.get(path).text
        assert "Panel iptal bildirdi" in text and "tone-danger" in text
        assert "Canceled" not in text


def test_turkish_telegram_menu_and_paused_status_are_truthful(client, rig):
    rig.settings.telegram_secret, rig.settings.chat_id = "secret", "123"
    rig.store.set_setting("paused", True)
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    for command in ["/start", "🟢 Bot durumu", "/bekleyen", "/sorunlar", "/ara"]:
        data = {"message": {"chat": {"id": 123}, "from": {"id": 123}, "text": command}}
        assert client.post("/telegram-webhook", json=data, headers=headers).status_code == 200
        notice = client.app.state.notifier.queue.get_nowait()
        assert notice["ephemeral"]
        if command == "🟢 Bot durumu":
            assert "duraklatıldı" in notice["text"]
        if command == "/start":
            assert notice["menu"] and "/bekleyen" in notice["text"]
    assert not rig.store.pending_notifications()


def test_old_telegram_send_callback_cannot_skip_web_preview(client, rig):
    rig.settings.telegram_secret, rig.settings.chat_id = "secret", "123"
    rig.store.set_setting("paused", True)
    order = receive_and_run(rig)
    body = {"callback_query": {"id": "old", "data": "send:" + order["id"],
            "message": {"chat": {"id": 123}}, "from": {"id": 123}}}
    response = client.post("/telegram-webhook", json=body,
                           headers={"X-Telegram-Bot-Api-Secret-Token": "secret"})
    assert response.status_code == 200 and rig.store.get(order["id"])["state"] == "paused"
    notice = client.app.state.notifier.queue.get_nowait()
    assert "eski sürüme ait" in notice["text"] and notice["ephemeral"]
    assert not rig.panels.adds


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
    response = client.post(path + "/send", data={"csrf": csrf, "revision": revision, "confirmed": "yes"})
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
    # The single JS editor receives imported platforms without replacing them.
    assert '"platform": "spotify"' in text


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


def mapping_data(client):
    import json
    text = client.get("/admin/services").text
    return json.loads(re.search(r'<script type="application/json" id="mapping-data">(.*?)</script>',
                                text, re.S).group(1))


def test_mapping_editor_refuses_duplicate_new_advert_without_overwriting(client, rig):
    before = rig.store.setting("binding:10")
    response = client.post("/admin/services", data={"csrf": token(client, "/admin/services"),
                           "mode": "create", "advert_id": "10", "panel": "medyabayim",
                           "service_id": "999", "quantity": "100"})
    assert response.status_code == 409
    assert rig.store.setting("binding:10") == before


def test_mapping_editor_rejects_stale_or_deleted_mapping(client, rig):
    page = mapping_data(client)
    before = rig.store.setting("binding:10")
    rig.store.set_setting("binding:10", dict(before, name="Diğer sekmede değişti"))
    data = {"csrf": token(client, "/admin/services"), "mode": "edit", "advert_id": "10",
            "version": page["versions"]["10"], "panel": "smmrush", "service_id": "123", "quantity": "200"}
    assert client.post("/admin/services", data=data).status_code == 409
    assert rig.store.setting("binding:10")["name"] == "Diğer sekmede değişti"
    rig.store.delete_binding("10")
    assert client.post("/admin/services", data=data).status_code == 409
    assert rig.store.setting("binding:10") is None


def test_mapping_editor_copy_and_edit_leave_orders_and_notifications_unchanged(client, rig, monkeypatch):
    import json
    order = receive_and_run(rig)
    before = rig.store.get(order["id"])
    notices = rig.store.pending_notifications()
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("Mapping UI called an external API"))
    page = mapping_data(client)
    csrf = token(client, "/admin/services")
    components = page["bindings"]["10"]["components"] + [{
        "panel": "medyabayim", "service_id": "456", "quantity": 50, "platform": "instagram"}]
    data = {"csrf": csrf, "mode": "create", "advert_id": "20", "name": "Yeni paket",
            "active": "false", "components": json.dumps(components)}
    assert client.post("/admin/services", data=data).status_code == 200
    copied = rig.store.setting("binding:20")
    assert copied["active"] is False and len(copied["components"]) == 2
    assert rig.store.setting("binding:10") == page["bindings"]["10"]
    data.update(mode="edit", version=mapping_data(client)["versions"]["20"], name="Düzenlenen paket")
    assert client.post("/admin/services", data=data).status_code == 200
    assert rig.store.setting("binding:20")["name"] == "Düzenlenen paket"
    assert rig.store.get(order["id"]) == before
    assert rig.store.pending_notifications() == notices
    assert len(rig.panels.adds) == 1


def test_mapping_script_is_authenticated_and_does_not_query_database(client, rig, monkeypatch):
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Script queried database"))
    response = client.get("/admin/assets/services.js")
    assert response.status_code == 200 and "application/javascript" in response.headers["content-type"]
    assert client.get("/admin/assets/services.js", auth=("wrong", "wrong")).status_code == 401


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


def test_itemsatis_key_switch_over_never_rejects_before_key_is_seen(client, rig):
    csrf = token(client, "/admin/integrations")
    assert client.post("/itemsatis-webhook", json=payload(1)).json()["status"] == "saved"
    assert client.post("/admin/integrations/itemsatis", data={"csrf": csrf, "action": "create"}).status_code == 200
    key = rig.store.setting("itemsatis_webhook_secret")
    assert key and len(key) >= 40
    # Created but not enforced: the old address keeps working.
    assert client.post("/itemsatis-webhook", json=payload(2)).status_code == 200
    assert client.post("/admin/integrations/itemsatis", data={"csrf": csrf, "action": "enforce"}).status_code == 400
    assert client.post("/itemsatis-webhook?key=" + key, json=payload(3)).status_code == 200
    assert rig.store.setting("itemsatis_webhook_seen")
    assert client.post("/admin/integrations/itemsatis", data={"csrf": csrf, "action": "enforce"}).status_code == 200
    assert client.post("/itemsatis-webhook", json=payload(4)).status_code == 401
    assert client.post("/itemsatis-webhook?key=wrong", json=payload(4)).status_code == 401
    assert client.post("/itemsatis-webhook", json=payload(4), headers={"X-Webhook-Secret": key}).status_code == 200
    assert rig.store.by_source("itemsatis:4") is not None
    # A new key can't be generated while enforced; relaxing restores acceptance.
    assert client.post("/admin/integrations/itemsatis", data={"csrf": csrf, "action": "create",
                                                             "confirmed": "yes"}).status_code == 400
    assert client.post("/admin/integrations/itemsatis", data={"csrf": csrf, "action": "relax"}).status_code == 200
    assert client.post("/itemsatis-webhook", json=payload(5)).status_code == 200


def test_saved_keys_survive_restart_and_page_never_calls_telegram(rig, monkeypatch):
    rig.store.set_setting("itemsatis_webhook_secret", "k" * 43)
    rig.store.set_setting("itemsatis_webhook_enforced", True)
    rig.store.set_setting("telegram_webhook_secret", "t" * 43)
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("Page view called an external API"))
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as live:
        live.auth = (rig.settings.username, rig.settings.password)
        assert live.post("/itemsatis-webhook", json=payload(9)).status_code == 401
        assert live.post("/itemsatis-webhook?key=" + "k" * 43, json=payload(9)).status_code == 200
        assert rig.settings.telegram_secret == "t" * 43
        page = live.get("/admin/integrations")
        assert page.status_code == 200 and "Anahtar zorunlu" in page.text


def test_environment_key_wins_and_cannot_be_changed_from_panel(client, rig, monkeypatch):
    monkeypatch.setenv("ITEMSATIS_WEBHOOK_SECRET", "env-key")
    rig.settings.webhook_secret, rig.settings.webhook_enforced = "env-key", True
    csrf = token(client, "/admin/integrations")
    assert client.post("/admin/integrations/itemsatis", data={"csrf": csrf, "action": "relax"}).status_code == 400
    assert client.post("/itemsatis-webhook", json=payload()).status_code == 401
    assert "env-key" not in client.get("/admin/integrations").text.split("<details>")[0]


def test_webhook_key_is_removed_from_access_log():
    import logging
    from main import HideQuery
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:0", "POST", "/itemsatis-webhook?key=SECRET", "1.1", 200), None)
    HideQuery().filter(record)
    assert "SECRET" not in record.getMessage()


def test_telegram_registration_saves_secret_before_registering(client, rig, monkeypatch):
    calls = []
    class Reply:
        def __init__(self, result):
            self.result = result
        def json(self):
            return {"ok": True, "result": self.result}
    def fake_post(url, json=None, timeout=None):
        method = url.rsplit("/", 1)[1]
        calls.append((method, dict(json or {}), rig.store.setting("telegram_webhook_secret")))
        return Reply({"url": rig.settings.public_url + "/telegram-webhook", "pending_update_count": 0}
                     if method == "getWebhookInfo" else True)
    monkeypatch.setattr("bot.notifications.requests.post", fake_post)
    rig.settings.bot_token, rig.settings.chat_id = "123:test-token", "555"
    rig.settings.public_url = "https://bot.example.test"
    csrf = token(client, "/admin/integrations")
    response = client.post("/admin/integrations/telegram", data={"csrf": csrf, "action": "register"})
    assert response.status_code == 200 and "bu uygulamaya bağlı" in response.text
    method, sent, saved = calls[0]
    assert method == "setWebhook" and sent["secret_token"] == saved == rig.settings.telegram_secret
    assert sent["url"] == "https://bot.example.test/telegram-webhook"
    assert "123:test-token" not in response.text and saved not in response.text
    # The button is now offered for a private chat, and the webhook accepts Telegram.
    from bot.notifications import callbacks_allowed
    assert callbacks_allowed(rig.settings)
    data = {"update_id": 5, "message": {"chat": {"id": 555}, "from": {"id": 555}, "text": "/status"}}
    assert client.post("/telegram-webhook", json=data,
                       headers={"X-Telegram-Bot-Api-Secret-Token": saved}).status_code == 200
    # Registering again reuses the same secret.
    client.post("/admin/integrations/telegram", data={"csrf": csrf, "action": "register"})
    assert calls[-2][1]["secret_token"] == saved


def test_telegram_errors_never_expose_token(client, rig, monkeypatch):
    class Reply:
        def json(self):
            return {"ok": False, "description": "Unauthorized for bot 123:test-token"}
    monkeypatch.setattr("bot.notifications.requests.post", lambda *a, **k: Reply())
    rig.settings.bot_token = "123:test-token"
    csrf = token(client, "/admin/integrations")
    response = client.post("/admin/integrations/telegram", data={"csrf": csrf, "action": "check"})
    assert response.status_code == 400 and "test-token" not in response.text
