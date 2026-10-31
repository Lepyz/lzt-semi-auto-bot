"""Free-tier behaviour: Neon compute only wakes when the database has work to do."""
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import bot.engine as engine_module
import bot.store as store_module
from bot import quota
from conftest import receive_and_run
from main import create_app


@pytest.fixture
def client(rig):
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        client.app.state.engine.enqueue = rig.jobs.append
        client.auth = (rig.settings.username, rig.settings.password)
        yield client


def count_transactions(store, monkeypatch):
    calls = []
    original = store.transaction

    def counted():
        calls.append(1)
        return original()
    monkeypatch.setattr(store, "transaction", counted)
    return calls


def make_due(rig, order_id):
    rig.engine.active_checks[order_id] = 0
    rig.engine.recent_checks.pop(order_id, None)  # Simulate the 30 minutes between slots.


def test_orders_submitted_at_different_times_share_one_check_slot(rig, monkeypatch):
    clock = [10_000.0]
    monkeypatch.setattr(engine_module, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    orders = []
    for number, now in enumerate([10_000.0, 10_500.0, 11_600.0]):
        clock[0] = now
        orders.append(receive_and_run(rig, number + 1, f"https://instagram.com/person{number}"))
    slots = {rig.engine.active_checks[o["id"]] for o in orders}
    interval = rig.settings.active_check_interval
    assert len(slots) == 1
    assert slots.pop() - 11_600.0 >= interval / 2  # Never checked moments after submission.


def test_blocked_and_active_slots_line_up(rig, monkeypatch):
    clock = [50_000.0]
    monkeypatch.setattr(engine_module, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    active = rig.engine.slot(rig.settings.active_check_interval)
    blocked = rig.engine.slot(rig.settings.check_interval)
    assert active % rig.settings.check_interval == 0 and blocked % rig.settings.check_interval == 0


def test_unchanged_status_check_runs_without_any_sql(rig, monkeypatch):
    order = receive_and_run(rig)
    rig.engine.refresh(order["id"])  # Status known: "In progress".
    make_due(rig, order["id"])
    checks = len(rig.panels.checks)
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Unchanged status read the database"))
    rig.engine.check_due()
    assert len(rig.panels.checks) == checks + 1
    assert rig.engine.check_results[order["id"]]["ok"]
    assert rig.engine.stats["quiet_checks"] == 1
    assert rig.engine.active_checks[order["id"]] > 0


def test_changed_status_is_stored_with_a_single_panel_call(rig):
    order = receive_and_run(rig)
    make_due(rig, order["id"])
    rig.engine.check_due()
    assert len(rig.panels.checks) == 1
    assert rig.store.get(order["id"])["parts"][0]["status"] == "In progress"
    rig.panels.current = {"status": "Completed", "terminal": True}
    make_due(rig, order["id"])
    rig.engine.check_due()
    assert len(rig.panels.checks) == 2
    assert rig.store.get(order["id"])["state"] == "finished"
    assert order["id"] not in rig.engine.active_checks and order["id"] not in rig.engine.snapshots


def test_status_outage_writes_once_and_recovery_clears_warning(rig, monkeypatch):
    order = receive_and_run(rig)
    rig.engine.refresh(order["id"])
    calls = count_transactions(rig.store, monkeypatch)
    working = rig.panels.status
    monkeypatch.setattr(rig.panels, "status", lambda _: None)
    for _ in range(2):
        make_due(rig, order["id"])
        rig.engine.check_due()
    assert not calls  # First failures are only counted in memory.
    make_due(rig, order["id"])
    rig.engine.check_due()
    assert rig.store.get(order["id"])["status_error"] and len(rig.notices) == 1
    calls.clear()
    for _ in range(3):
        make_due(rig, order["id"])
        rig.engine.check_due()
    assert not calls and len(rig.notices) == 1  # Warning already stored; no repeats.
    monkeypatch.setattr(rig.panels, "status", working)
    make_due(rig, order["id"])
    rig.engine.check_due()
    assert not rig.store.get(order["id"]).get("status_error")
    assert rig.store.owner(order["target"]) == order["id"]
    assert len(rig.panels.adds) == 1


def test_blocked_target_with_unchanged_owner_needs_no_sql(rig, monkeypatch):
    first = receive_and_run(rig)
    second = receive_and_run(rig, 2)
    assert second["state"] == "waiting"
    rig.engine.refresh(first["id"])
    rig.engine.recent_checks.clear()
    rig.engine.watch[first["target"]] = 0
    checks = len(rig.panels.checks)
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Unchanged blocker read the database"))
    rig.engine.check_due()
    assert len(rig.panels.checks) == checks + 1
    assert rig.engine.watch[first["target"]] > 0


def test_blocked_owner_finishing_makes_waiter_ready_from_scheduled_check(rig):
    first = receive_and_run(rig)
    second = receive_and_run(rig, 2)
    rig.engine.refresh(first["id"])
    rig.engine.recent_checks.clear()
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.watch[first["target"]] = 0
    checks = len(rig.panels.checks)
    rig.engine.check_due()
    assert len(rig.panels.checks) == checks + 1  # Answer reused by the database update.
    assert rig.store.get(second["id"])["state"] == "ready"
    assert first["target"] not in rig.engine.watch
    assert len(rig.panels.adds) == 1


def test_next_check_is_reported_from_memory(rig, monkeypatch):
    assert rig.engine.next_check() is None
    order = receive_and_run(rig)
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Next check read the database"))
    upcoming = rig.engine.next_check()
    assert upcoming and upcoming > time.time()
    assert order["id"] in rig.engine.snapshots


def test_wake_estimate_merges_queries_inside_the_idle_window(rig, monkeypatch):
    clock = [1_000.0]
    monkeypatch.setattr(store_module, "time", SimpleNamespace(time=lambda: clock[0]))
    store = store_module.Store(rig.settings.database_url)
    for now in (1_000.0, 1_060.0, 1_120.0):  # One burst: a single wake-up.
        clock[0] = now
        store._touch(start=True)
        store._touch(start=False)
    clock[0] = 5_000.0  # Long after the compute went back to sleep.
    store._touch(start=True)
    store._touch(start=False)
    clock[0] = 10_000.0
    report = store.usage_report()
    assert report["wakes"] == 2 and report["transactions"] == 4
    assert report["awake"] == pytest.approx((1_120 + 300 - 1_000) + 300)
    assert report["ratio"] == pytest.approx(report["awake"] / 9_000)


def test_quota_projection_flags_an_always_awake_database():
    always = {"ratio": 1.0, "elapsed": 7 * 3600, "awake": 7 * 3600, "postgres": True}
    assert quota.neon(always)["cu_hours"] > quota.NEON_FREE_CU_HOURS
    assert quota.neon(always)["tone"] == "danger"
    batched = dict(always, ratio=0.2, awake=0.2 * 7 * 3600)
    assert quota.neon(batched)["tone"] == "success"
    assert "CU-saat" in quota.telegram_line(batched)
    assert quota.telegram_line(dict(batched, elapsed=60)) == ""


def test_usage_page_reads_storage_once_and_shows_estimates(client, rig, monkeypatch):
    receive_and_run(rig)
    calls = count_transactions(rig.store, monkeypatch)
    client.head("/health")
    response = client.get("/admin/usage")
    assert response.status_code == 200
    text = response.text
    assert "CU-saat" in text and "MB / 512 MB" in text and "Takipteki aktif sipariş" in text
    assert "1 istek" in text
    assert len(calls) == 1  # Admin auth and memory stats add no queries.
    assert 'href="/admin/usage"' in client.get("/admin").text


def test_health_counts_calls_without_sql_and_reports_dead_threads(client, rig, monkeypatch):
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Health read the database"))
    assert client.get("/health").json()["ok"]
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    state = client.app.state
    monkeypatch.setattr(state.engine, "monitor", dead)
    monkeypatch.setattr(state.notifier, "thread", dead)
    state.background = True
    response = client.get("/health")
    assert response.status_code == 503 and not response.json()["ok"]
    assert client.head("/health").status_code == 503
    state.background = False


def test_status_command_reports_checks_from_memory(client, rig):
    rig.settings.telegram_secret, rig.settings.chat_id = "secret", "123"
    engine = client.app.state.engine
    order, _ = engine.receive(payload_for(0))
    engine.execute(order["id"])
    data = {"message": {"chat": {"id": 123}, "from": {"id": 123}, "text": "/durum"}}
    assert client.post("/telegram-webhook", json=data,
                       headers={"X-Telegram-Bot-Api-Secret-Token": "secret"}).status_code == 200
    text = client.app.state.notifier.queue.get_nowait()["text"]
    assert "Takipteki aktif sipariş: 1" in text and "sonraki kontrol" in text


def test_dashboard_shows_100_records_by_default_with_more_on_request(client, rig):
    rig.store.delete_binding("10")  # Plain unmapped receipts: fast to create.
    for number in range(101):
        rig.engine.receive(dict(payload_for(number)))
    page = client.get("/admin?view=all").text
    assert page.count('class="card order-card"') == 100 and "limit=500" in page
    more = client.get("/admin?view=all&limit=500").text
    assert more.count('class="card order-card"') == 101 and "Daha fazla kayıt göster" not in more


def payload_for(number):
    from conftest import payload
    return payload(number + 1, f"https://instagram.com/person{number}")


def test_usage_page_still_renders_when_database_is_unreachable(client, rig, monkeypatch):
    def down():
        raise RuntimeError("compute suspended")
    monkeypatch.setattr(rig.store, "storage_report", down)
    response = client.get("/admin/usage")
    assert response.status_code == 200 and "Veritabanına şu an ulaşılamadı" in response.text
    assert "compute suspended" not in response.text
