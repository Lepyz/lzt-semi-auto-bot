from concurrent.futures import ThreadPoolExecutor

import pytest

from bot.engine import Engine
from bot.panels import AddResult
from bot.store import Conflict, Store
from conftest import payload, receive_and_run


def test_normal_order_is_saved_before_add_and_has_no_balance_calls(rig):
    order, new = rig.engine.receive(payload())
    assert new and rig.store.get(order["id"])["state"] == "queued"
    assert not rig.panels.adds
    rig.engine.execute(order["id"])
    saved = rig.store.get(order["id"])
    assert saved["state"] == "submitted"
    assert saved["parts"][0]["smm_id"] == "1001"
    assert len(rig.panels.adds) == 1
    assert not rig.panels.checks


@pytest.mark.parametrize("status", ["Completed", "Partial", "Canceled", "Refunded"])
def test_blocked_order_never_automatically_submits_after_terminal_status(rig, status):
    first = receive_and_run(rig)
    second = receive_and_run(rig, 2)
    assert second["state"] == "waiting" and second["manual_required"]
    assert len(rig.panels.adds) == 1
    rig.panels.current = {"status": status, "terminal": True}
    rig.engine.refresh(first["id"])
    assert rig.store.get(second["id"])["state"] == "ready"
    assert len(rig.panels.adds) == 1
    ready_notices = [n for n in rig.notices if n["key"] == second["id"] + ":ready"]
    assert len(ready_notices) == 1 and status in ready_notices[0]["text"]
    for _ in range(3):
        rig.engine.refresh(first["id"])
        rig.engine.make_ready(first["target"], rig.store.get(first["id"]))
    assert len([n for n in rig.notices if n["key"] == second["id"] + ":ready"]) == 1
    rig.engine.approve(second["id"])
    rig.engine.execute(second["id"])
    assert len(rig.panels.adds) == 2
    assert rig.store.get(second["id"])["state"] == "submitted"


def test_approve_still_checks_active_target(rig):
    receive_and_run(rig)
    second = receive_and_run(rig, 2)
    rig.engine.approve(second["id"])
    rig.engine.execute(second["id"])
    assert rig.store.get(second["id"])["state"] == "waiting"
    assert len(rig.panels.adds) == 1


def test_waiting_fifo_requires_individual_approval(rig):
    first = receive_and_run(rig, 1)
    second = receive_and_run(rig, 2)
    third = receive_and_run(rig, 3)
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.refresh(first["id"])
    assert rig.store.get(second["id"])["state"] == "ready"
    assert rig.store.get(third["id"])["state"] == "waiting"
    # Trying the later purchase cannot jump the older one.
    rig.engine.approve(third["id"])
    rig.engine.execute(third["id"])
    assert len(rig.panels.adds) == 1
    rig.engine.approve(second["id"])
    rig.engine.execute(second["id"])
    assert len(rig.panels.adds) == 2
    rig.engine.refresh(second["id"])
    assert rig.store.get(third["id"])["state"] == "ready"
    assert len(rig.panels.adds) == 2


def test_same_purchase_repeated_does_not_create_duplicate(rig):
    first = receive_and_run(rig)
    second, created = rig.engine.receive(payload())
    assert not created and second["id"] == first["id"]
    rig.engine.execute(second["id"])
    assert len(rig.panels.adds) == 1


def test_sale_without_order_id_is_automatic_and_repeats_are_deduplicated(rig):
    data = payload()
    del data["order_id"]
    data["event"] = "advert_sold"
    data["details"] = {"time": 1700000000}
    first, created = rig.engine.receive(data)
    assert created and first["state"] == "queued"
    rig.engine.execute(first["id"])
    again, created = rig.engine.receive(dict(data))
    assert not created and again["id"] == first["id"]
    assert len(rig.panels.adds) == 1
    # A later independent purchase for the same link is held, not discarded.
    later = dict(data, details={"time": 1700000001})
    second, created = rig.engine.receive(later)
    assert created and second["id"] != first["id"]
    rig.engine.execute(second["id"])
    assert rig.store.get(second["id"])["state"] == "waiting"
    assert len(rig.panels.adds) == 1


def test_imported_legacy_fingerprint_blocks_old_webhook_replay(rig):
    from bot.payloads import legacy_payload_key
    from scripts.migrate_upstash import empty_order
    data = payload()
    del data["order_id"]
    data["event"] = "advert_sold"
    legacy, _ = rig.store.create(empty_order(legacy_payload_key(data)))
    received, created = rig.engine.receive(data)
    assert not created and received["id"] == legacy["id"]
    assert not rig.jobs and not rig.panels.adds


def test_legacy_marker_imported_after_receipt_still_prevents_send(rig):
    from scripts.migrate_upstash import empty_order
    data = payload()
    del data["order_id"]
    order, _ = rig.engine.receive(data)
    rig.store.create(empty_order(order["legacy_source_key"]))
    rig.engine.execute(order["id"])
    assert rig.store.get(order["id"])["state"] == "closed"
    assert not rig.panels.adds


def test_different_links_are_independent(rig):
    receive_and_run(rig)
    other = receive_and_run(rig, 2, "https://instagram.com/other")
    assert other["state"] == "submitted" and len(rig.panels.adds) == 2


def test_unknown_order_event_saved_for_review(rig):
    data = payload()
    data["event"] = "future_sale_format"
    order, _ = rig.engine.receive(data)
    assert order["state"] == "review" and not rig.jobs
    assert not rig.panels.adds


def test_missing_link_can_be_fixed_without_automatic_submission(rig):
    data = payload()
    del data["post_datas"]
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order["id"])
    current = rig.store.get(order["id"])
    assert current["state"] == "review"
    rig.engine.repair(order["id"], "https://instagram.com/customer", current["revision"])
    assert not rig.panels.adds
    rig.engine.approve(order["id"])
    rig.engine.execute(order["id"])
    assert len(rig.panels.adds) == 1


def test_missing_binding_saved_not_discarded(rig):
    rig.store.delete_binding("10")
    order = receive_and_run(rig)
    assert order["state"] == "review"
    assert "eşleştirmesi" in order["error"]
    assert not rig.panels.adds


def test_uncertain_response_requires_manual_reconciliation(rig):
    rig.panels.results = [AddResult("uncertain", error="timeout")]
    order = receive_and_run(rig)
    assert order["state"] == "uncertain"
    with pytest.raises(ValueError):
        rig.engine.approve(order["id"])
    rig.engine.execute(order["id"])
    assert len(rig.panels.adds) == 1
    rig.engine.reconcile(order["id"], 0, smm_id="9000", revision=order["revision"])
    assert rig.store.get(order["id"])["parts"][0]["smm_id"] == "9000"
    assert len(rig.panels.adds) == 1


def test_explicit_absent_confirmation_does_not_itself_resend(rig):
    rig.panels.results = [AddResult("uncertain", error="timeout")]
    order = receive_and_run(rig)
    rig.engine.reconcile(order["id"], 0, confirmed_absent=True, revision=order["revision"])
    assert len(rig.panels.adds) == 1
    rig.engine.approve(order["id"])
    rig.engine.execute(order["id"])
    assert len(rig.panels.adds) == 2


def test_manual_send_click_twice_cannot_send_twice(rig):
    rig.store.set_setting("paused", True)
    order = receive_and_run(rig)
    rig.store.set_setting("paused", False)
    rig.engine.approve(order["id"], order["revision"])
    with pytest.raises((ValueError, Conflict)):
        rig.engine.approve(order["id"], order["revision"])
    rig.engine.execute(order["id"])
    rig.engine.execute(order["id"])
    assert len(rig.panels.adds) == 1


def test_pause_resume_does_not_release_held_orders(rig):
    rig.store.set_setting("paused", True)
    order = receive_and_run(rig)
    assert order["state"] == "paused"
    rig.store.set_setting("paused", False)
    rig.engine.execute(order["id"])
    assert not rig.panels.adds


def test_restart_retains_waiting_and_ready_without_submission(rig):
    first = receive_and_run(rig)
    second = receive_and_run(rig, 2)
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.refresh(first["id"])
    restarted = Engine(Store(rig.settings.database_url), rig.panels, rig.notifier, rig.settings)
    jobs = []
    restarted.enqueue = jobs.append
    restarted.start()
    try:
        assert restarted.store.get(second["id"])["state"] == "ready"
        assert not jobs
        assert len(rig.panels.adds) == 1
    finally:
        restarted.close()


def test_restart_during_add_becomes_uncertain_not_retried(rig):
    order, _ = rig.engine.receive(payload())
    rig.engine.prepare(order)
    order["parts"][0]["state"] = "sending"
    order["state"] = "sending"
    rig.store.acquire_target(order["target"], order["id"])
    rig.store.save(order)
    restarted = Engine(rig.store, rig.panels, rig.notifier, rig.settings)
    restarted.enqueue = lambda _: pytest.fail("Recovery must not auto-submit")
    restarted.start()
    try:
        assert rig.store.get(order["id"])["state"] == "uncertain"
        assert not rig.panels.adds
    finally:
        restarted.close()


def test_no_database_or_panel_calls_on_idle_check(rig, monkeypatch):
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Idle database query"))
    for _ in range(100):
        rig.engine.check_due()
    assert not rig.panels.checks


def test_only_blocking_orders_are_polled(rig):
    first = receive_and_run(rig)
    receive_and_run(rig, 2)
    receive_and_run(rig, 3, "https://instagram.com/unrelated")
    rig.engine.watch[first["target"]] = 0
    rig.engine.check_due()
    assert len(rig.panels.checks) == 1
    assert rig.panels.checks[0]["smm_id"] == first["parts"][0]["smm_id"]
    assert len(rig.notices) == 3  # two submitted, one waiting; no delay message


def test_concurrent_duplicate_webhooks_have_one_record_and_add(rig):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: rig.engine.receive(payload()), range(30)))
    assert sum(created for _, created in results) == 1
    order_id = results[0][0]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: rig.engine._run(order_id), range(30)))
    assert len(rig.panels.adds) == 1


def test_burst_same_target_opens_only_one_order(rig):
    orders = [rig.engine.receive(payload(i))[0] for i in range(30)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda o: rig.engine._run(o["id"]), orders))
    assert len(rig.panels.adds) == 1
    assert len(rig.store.orders(states={"waiting"})) == 29


def test_package_retry_does_not_repeat_successful_component(rig):
    binding = rig.store.setting("binding:10")
    binding["components"].append(dict(binding["components"][0], panel="medyabayim", service_id="999"))
    rig.store.set_setting("binding:10", binding)
    rig.panels.results = [AddResult("submitted", "1234"), AddResult("error", error="balance")]
    order = receive_and_run(rig)
    assert order["state"] == "error" and len(rig.panels.adds) == 2
    with pytest.raises(ValueError):
        rig.engine.approve(order["id"])
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.approve(order["id"])
    rig.engine.execute(order["id"])
    assert len(rig.panels.adds) == 3
    assert rig.panels.adds[-1][0]["service_id"] == "999"


def test_unchanged_status_does_not_write_order(rig):
    first = receive_and_run(rig)
    rig.engine.refresh(first["id"])
    revision = rig.store.get(first["id"])["revision"]
    rig.engine.refresh(first["id"])
    assert rig.store.get(first["id"])["revision"] == revision


def test_closed_unsubmitted_purchase_does_not_hold_later_purchase(rig):
    first = receive_and_run(rig)
    second = receive_and_run(rig, 2)
    third = receive_and_run(rig, 3)
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.refresh(first["id"])
    current = rig.store.get(second["id"])
    rig.engine.close_unsubmitted(second["id"], current["revision"])
    assert rig.store.get(second["id"])["state"] == "closed"
    assert rig.store.get(third["id"])["state"] == "ready"
    assert len(rig.panels.adds) == 1


def test_active_purchase_cannot_be_locally_closed(rig):
    order = receive_and_run(rig)
    with pytest.raises((ValueError, Conflict)):
        rig.engine.close_unsubmitted(order["id"], order["revision"])


def test_no_status_calls_after_last_waiter_removed(rig):
    first = receive_and_run(rig)
    second = receive_and_run(rig, 2)
    rig.engine.close_unsubmitted(second["id"], second["revision"])
    rig.engine.watch[first["target"]] = 0
    rig.engine.check_due()
    assert not rig.panels.checks
