import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from bot.engine import Engine
from bot.panels import AddResult
from bot.store import Conflict, Store
from conftest import payload, receive_and_run
from bot.presentation import panel_label


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


def test_one_hundred_successful_orders_produce_no_telegram_rows(rig):
    for number in range(100):
        receive_and_run(rig, number + 1, f"https://instagram.com/person{number}")
    assert len(rig.panels.adds) == 100
    assert not rig.notices and not rig.store.pending_notifications()


def test_unmapped_advert_is_recorded_without_any_notification(rig):
    rig.store.delete_binding("10")
    for number in range(10):
        order = receive_and_run(rig, number + 1)
        assert order["state"] == "review" and order["reason_code"] == "binding_missing"
    assert not rig.notices and not rig.store.pending_notifications()
    assert not rig.panels.adds


def test_back_to_back_same_link_sends_first_and_reports_second_without_repeats(rig):
    first = receive_and_run(rig, 1)
    second = receive_and_run(rig, 2)
    assert first["state"] == "submitted" and first["parts"][0]["smm_id"]
    assert second["state"] == "waiting" and not second["parts"][0]["smm_id"]
    assert len(rig.notices) == 1 and rig.notices[0]["order_id"] == second["id"]
    for _ in range(5):
        rig.engine.execute(second["id"])
        rig.engine.receive(payload(2))
    assert len(rig.panels.adds) == len(rig.notices) == 1


def test_each_distinct_rejected_purchase_has_its_own_alert(rig):
    rig.panels.results = [AddResult("error", error="Insufficient balance")] * 20
    for number in range(20):
        receive_and_run(rig, number + 1, f"https://instagram.com/person{number}")
    assert len(rig.store.orders(states={"error"})) == 20
    assert len(rig.notices) == len(rig.store.pending_notifications()) == 20
    assert "bakiye" in rig.notices[0]["text"]


def test_each_uncertain_purchase_has_an_alert_and_retains_its_lock(rig):
    rig.panels.results = [AddResult("uncertain", error="timeout")] * 20
    for number in range(20):
        order = receive_and_run(rig, number + 1, f"https://instagram.com/person{number}")
        assert rig.store.owner(order["target"]) == order["id"]
    assert len(rig.store.orders(states={"uncertain"})) == 20
    assert len(rig.notices) == len(rig.store.pending_notifications()) == 20
    assert len(rig.panels.adds) == 20  # One initial attempt for each distinct real purchase; no retries.


@pytest.mark.parametrize("status", ["Canceled", "Partial", "Refunded"])
def test_nonblocking_terminal_result_notifies_once_in_turkish(rig, status):
    order = receive_and_run(rig)
    rig.panels.current = {"status": status, "terminal": True}
    rig.engine.active_checks[order["id"]] = 0
    rig.engine.check_due()
    assert rig.store.get(order["id"])["state"] == "finished"
    assert len(rig.notices) == 1 and status not in rig.notices[0]["text"]
    rig.engine.refresh(order["id"])
    assert len(rig.notices) == 1
    assert order["id"] not in rig.engine.active_checks


def test_active_completion_without_waiting_order_is_quiet(rig):
    order = receive_and_run(rig)
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.active_checks[order["id"]] = 0
    rig.engine.check_due()
    assert rig.store.get(order["id"])["state"] == "finished"
    assert not rig.notices


def test_terminal_alert_is_durable_even_if_ready_transition_fails(rig, monkeypatch):
    order = receive_and_run(rig)
    rig.panels.current = {"status": "Canceled", "terminal": True}
    def fail(*args):
        raise RuntimeError("simulated interruption")
    monkeypatch.setattr(rig.engine, "make_ready", fail)
    with pytest.raises(RuntimeError):
        rig.engine.refresh(order["id"])
    assert rig.store.get(order["id"])["state"] == "finished"
    assert len(rig.notices) == len(rig.store.pending_notifications()) == 1


def test_status_failure_never_releases_lock_or_resends_and_warns_once(rig, monkeypatch):
    order = receive_and_run(rig)
    monkeypatch.setattr(rig.panels, "status", lambda _: None)
    for _ in range(5):
        rig.engine.refresh(order["id"])
    current = rig.store.get(order["id"])
    assert current["state"] == "submitted" and current["status_error"]
    assert rig.store.owner(order["target"]) == order["id"]
    assert len(rig.panels.adds) == 1 and len(rig.notices) == 1


def test_monitor_has_no_sql_until_active_order_is_due(rig, monkeypatch):
    order = receive_and_run(rig)
    assert order["id"] in rig.engine.active_checks
    monkeypatch.setattr(rig.store, "transaction", lambda: pytest.fail("Not-yet-due database query"))
    for _ in range(100):
        rig.engine.check_due()
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
    ready_notices = [n for n in rig.notices if n["key"].startswith(second["id"] + ":ready:")]
    assert len(ready_notices) == 1 and panel_label(status) in ready_notices[0]["text"]
    assert status not in ready_notices[0]["text"]
    for _ in range(3):
        rig.engine.refresh(first["id"])
        rig.engine.make_ready(first["target"], rig.store.get(first["id"]))
    assert len([n for n in rig.notices if n["key"].startswith(second["id"] + ":ready:")]) == 1
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


def test_recent_migration_write_does_not_make_old_order_look_new(rig):
    first = receive_and_run(rig)
    first["created_at"] -= 86_400_000_000
    rig.store.save(first)  # updated_at is now, but the panel order itself is old.
    rig.panels.current = {"status": "Completed", "terminal": True}
    second = receive_and_run(rig, 2)
    assert rig.panels.checks
    assert second["state"] == "submitted"
    assert len(rig.panels.adds) == 2


def test_unknown_order_event_saved_for_review(rig):
    data = payload()
    data["event"] = "future_sale_format"
    order, _ = rig.engine.receive(data)
    assert order["state"] == "review" and not rig.jobs
    assert not rig.panels.adds
    assert len(rig.notices) == 1 and rig.notices[0]["order_id"] == order["id"]
    rig.engine.receive(data)
    assert len(rig.notices) == 1
    rig.store.delete_binding("10")
    data["order_id"] = "2"
    rig.engine.receive(data)
    assert len(rig.notices) == 1  # Unmapped adverts remain deliberately quiet.


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
    assert len(rig.notices) == 1 and rig.notices[0]["order_id"] == order["id"]
    rig.store.set_setting("paused", False)
    rig.engine.execute(order["id"])
    assert not rig.panels.adds
    assert len(rig.notices) == 1


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


def unfinished(rig, state, part_state, age):
    order, _ = rig.engine.receive(payload())
    rig.engine.prepare(order)
    order["parts"][0]["state"] = part_state
    order["state"] = state
    rig.store.acquire_target(order["target"], order["id"])
    rig.store.save(order)
    with rig.store.transaction() as conn:  # Simulate the previous instance's last write time.
        current = rig.store.get(order["id"])
        current["updated_at"] -= int(age * 1_000_000)
        rig.store.execute(conn, "UPDATE orders SET document=? WHERE id=?",
                          (json.dumps({k: v for k, v in current.items() if k != "revision"}), order["id"]))
    return order


def test_restart_during_add_becomes_uncertain_not_retried(rig):
    order = unfinished(rig, "sending", "sending", age=600)
    restarted = Engine(rig.store, rig.panels, rig.notifier, rig.settings)
    restarted.enqueue = lambda _: pytest.fail("Recovery must not auto-submit")
    restarted.start()
    try:
        # Startup itself never touches claims: the previous instance may still own them.
        assert rig.store.get(order["id"])["state"] == "sending"
        assert restarted.recover() is True
        assert rig.store.get(order["id"])["state"] == "uncertain"
        assert rig.store.get(order["id"])["parts"][0]["state"] == "uncertain"
        assert not rig.panels.adds
        assert any(n["key"].startswith(order["id"] + ":recovery:") for n in rig.notices)
    finally:
        restarted.close()


def test_deploy_overlap_leaves_previous_instance_add_alone(rig):
    order = unfinished(rig, "sending", "sending", age=5)
    restarted = Engine(rig.store, rig.panels, rig.notifier, rig.settings)
    restarted.enqueue = lambda _: pytest.fail("Recovery must not auto-submit")
    try:
        assert restarted.recover() is False  # Retried later, once certainly stale.
        assert rig.store.get(order["id"])["state"] == "sending"
        # The previous instance can still record its real panel result.
        current = rig.store.get(order["id"])
        current["parts"][0].update(state="submitted", smm_id="555")
        current["state"] = "submitted"
        rig.store.save(current)
        assert rig.store.get(order["id"])["parts"][0]["smm_id"] == "555"
    finally:
        restarted.close()


def test_stale_claim_that_never_reached_panel_is_sent_once(rig):
    order = unfinished(rig, "processing", "new", age=600)
    restarted = Engine(rig.store, rig.panels, rig.notifier, rig.settings)
    jobs = []
    restarted.enqueue = jobs.append
    try:
        assert restarted.recover() is True
        assert rig.store.get(order["id"])["state"] == "queued"
        for job in jobs:
            restarted._run(job)
        assert rig.store.get(order["id"])["state"] == "submitted"
        assert len(rig.panels.adds) == 1
    finally:
        restarted.close()


def test_recovery_skips_order_this_instance_is_processing(rig):
    order = unfinished(rig, "sending", "sending", age=600)
    rig.engine.running.add(order["id"])
    assert rig.engine.recover() is True
    assert rig.store.get(order["id"])["state"] == "sending"


def test_recovery_dispatches_receipts_saved_by_previous_instance(rig):
    restarted = Engine(rig.store, rig.panels, rig.notifier, rig.settings)
    jobs = []
    restarted.enqueue = jobs.append
    try:
        restarted.start()
        late, _ = rig.engine.receive(payload(77))  # Saved after the scan, never dispatched.
        assert late["id"] not in jobs
        restarted.recover()
        assert late["id"] in jobs
    finally:
        restarted.close()


def test_explicit_manual_retry_that_is_blocked_again_is_reported(rig):
    receive_and_run(rig)
    second = receive_and_run(rig, 2)
    rig.engine.approve(second["id"])
    rig.engine.execute(second["id"])
    waiting = [n for n in rig.notices if n["key"].startswith(second["id"] + ":waiting:")]
    assert len(waiting) == 2 and len({n["key"] for n in waiting}) == 2
    assert len(rig.panels.adds) == 1


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
    assert len(rig.notices) == 1  # Only the held purchase, not the two successes.


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
