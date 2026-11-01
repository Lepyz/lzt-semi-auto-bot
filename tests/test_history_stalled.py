import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from bot.engine import Engine
from bot.history import STALLED_AFTER, phase_since
from bot.notifications import Notifier
from bot.panels import AddResult
from bot.store import Conflict
from conftest import payload, receive_and_run
from main import create_app


def age_phase(rig, order_id, seconds=STALLED_AFTER + 10):
    order = rig.store.get(order_id)
    since = int((time.time() - seconds) * 1_000_000)
    order['phase_started_at'] = since
    order['created_at'] = min(order['created_at'], since)
    with rig.store.transaction() as conn:
        rig.store.execute(conn, 'UPDATE orders SET document=?,created_at=? WHERE id=?',
                          (json.dumps(order, ensure_ascii=False), order['created_at'], order_id))
    rig.engine.dispatch_checks[order_id] = 0
    return rig.store.get(order_id)


def test_history_records_real_transitions_and_duplicate_receipts_change_nothing(rig):
    order = receive_and_run(rig)
    titles = [e['title'] for e in order['history']]
    assert titles == ['Sipariş kaydedildi', 'Gönderim hazırlanıyor', 'Panel cevabı bekleniyor',
                      'Panel siparişi kaydedildi', 'Panele gönderildi']
    assert any('1001' in e['detail'] for e in order['history'])
    assert all('instagram.com' not in json.dumps(e) for e in order['history'])
    duplicate, created = rig.engine.receive(payload())
    assert not created and duplicate == order


def test_history_keeps_ten_changes_and_metadata_does_not_reset_phase(rig):
    order, _ = rig.engine.receive(payload())
    old = age_phase(rig, order['id'])
    since = phase_since(old)
    for n in range(15):
        rig.engine.update_sale_price(order['id'], str(100 + n), rig.store.get(order['id'])['revision'])
    current = rig.store.get(order['id'])
    assert len(current['history']) == 10
    assert all(e['title'] == 'Satış tutarı güncellendi' for e in current['history'])
    assert phase_since(current) == since
    assert current['dispatch_revision'] == old['dispatch_revision']


def test_identical_panel_checks_and_status_failure_counts_do_not_fill_history(rig, monkeypatch):
    order = receive_and_run(rig)
    rig.engine.refresh(order['id'])
    previous = rig.store.get(order['id'])
    for _ in range(10):
        rig.engine.refresh(order['id'])
    assert rig.store.get(order['id']) == previous
    monkeypatch.setattr(rig.panels, 'status', lambda _: None)
    for _ in range(6):
        rig.engine.refresh(order['id'])
    history = rig.store.get(order['id'])['history']
    assert sum(e['title'] == 'Panel durumu doğrulanamıyor' for e in history) == 1
    assert len(history) == len(previous['history']) + 1


def test_stale_update_cannot_replace_history_or_add_a_notification(rig):
    order, _ = rig.engine.receive(payload())
    stale = dict(order)
    order['state'] = 'review'
    rig.store.save(order)
    stale['state'] = 'error'
    with pytest.raises(Conflict):
        rig.store.save(stale, {'key': 'stale-event', 'text': 'must not be added'})
    assert rig.store.get(order['id']) == order
    assert rig.store.notification('stale-event') is None


def test_stalled_warning_is_once_per_attempt_and_does_not_update_the_order(rig, monkeypatch):
    order, _ = rig.engine.receive(payload())
    order = age_phase(rig, order['id'])
    rig.engine.check_stalled()
    assert rig.store.get(order['id']) == order
    assert len(rig.notices) == 1 and 'İLERLEMİYOR' in rig.notices[0]['text']
    assert not rig.panels.adds and not rig.panels.checks
    assert order['id'] not in rig.engine.dispatch_checks
    restarted = Engine(rig.store, rig.panels, rig.notifier, rig.settings)
    try:
        restarted.schedule_dispatch(order)
        restarted.dispatch_checks[order['id']] = 0
        restarted.check_stalled()
        assert len(rig.notices) == 1  # SQL marker survives restarts.
    finally:
        restarted.close()
    notifier = Notifier(rig.store, rig.settings)
    sent = []
    monkeypatch.setattr(notifier, 'send', lambda n: sent.append(n) or 'sent')
    notifier.deliver(rig.notices[0])
    notifier.deliver(rig.notices[0])
    assert len(sent) == 1
    monkeypatch.setattr(rig.store, 'transaction', lambda *a, **k: pytest.fail('Idle watchdog queried SQL'))
    for _ in range(50):
        rig.engine.check_due()


def test_progress_reschedules_the_check_instead_of_warning(rig):
    order, _ = rig.engine.receive(payload())
    age_phase(rig, order['id'])
    current = rig.store.get(order['id'])
    current['state'] = 'processing'
    rig.store.save(current)
    rig.engine.check_stalled()
    assert not rig.notices
    assert rig.engine.dispatch_checks[order['id']] > time.monotonic()


def test_dispatch_has_no_sql_before_its_deadline(rig, monkeypatch):
    rig.engine.receive(payload())
    monkeypatch.setattr(rig.store, 'transaction', lambda *a, **k: pytest.fail('Premature dispatch query'))
    for _ in range(50):
        rig.engine.check_due()


def test_unmapped_stalled_purchase_remains_silent(rig):
    rig.store.delete_binding('10')
    order, _ = rig.engine.receive(payload())
    age_phase(rig, order['id'])
    rig.engine.check_stalled()
    assert not rig.notices and not rig.store.pending_notifications()
    assert order['id'] not in rig.engine.dispatch_checks


def test_explicit_new_attempt_can_warn_again(rig):
    order, _ = rig.engine.receive(payload())
    age_phase(rig, order['id'])
    rig.engine.check_stalled()
    current = rig.store.get(order['id'])
    current['state'] = 'review'
    rig.store.save(current)
    rig.engine.approve(order['id'], current['revision'])
    age_phase(rig, order['id'])
    rig.engine.check_stalled()
    assert len(rig.notices) == 2 and len({n['key'] for n in rig.notices}) == 2
    assert not rig.panels.adds


def test_slow_panel_reply_still_commits_and_resolved_warning_is_cancelled(rig, monkeypatch):
    order, _ = rig.engine.receive(payload())
    entered, release = Event(), Event()
    calls = []
    def slow_add(part, link):
        calls.append(True)
        entered.set()
        assert release.wait(15)
        return AddResult('submitted', '88888')
    monkeypatch.setattr(rig.panels, 'add', slow_add)
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(rig.engine._run, order['id'])
        try:
            assert entered.wait(10)
            pending = age_phase(rig, order['id'])
            owner = rig.store.owner(pending['target'])
            rig.engine.check_stalled()
            warning = rig.notices[-1]
            assert rig.store.get(order['id'])['revision'] == pending['revision']
            assert rig.store.owner(pending['target']) == owner
        finally:
            release.set()
        job.result(timeout=15)
    saved = rig.store.get(order['id'])
    assert saved['state'] == 'submitted' and saved['parts'][0]['smm_id'] == '88888'
    assert len(calls) == 1 and order['id'] not in rig.engine.dispatch_checks
    notifier = Notifier(rig.store, rig.settings)
    monkeypatch.setattr(notifier, 'send', lambda _: pytest.fail('Resolved warning was sent'))
    notifier.deliver(warning)
    assert rig.store.notification(warning['key'])['state'] == 'cancelled'


def test_close_is_recorded_and_delete_removes_the_history(rig):
    rig.store.set_setting('paused', True)
    order = receive_and_run(rig)
    rig.engine.close_unsubmitted(order['id'], order['revision'])
    closed = rig.store.get(order['id'])
    assert closed['history'][-1]['title'] == 'Gönderilmeden kapatıldı'
    rig.engine.cleanup([(closed['id'], closed['revision'])], 'delete')
    assert 'history' not in rig.store.get(order['id'])


def test_stalled_purchase_is_visible_in_inbox_and_detail_pages_do_not_mutate(rig, monkeypatch):
    order, _ = rig.engine.receive(payload())
    order = age_phase(rig, order['id'])
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        client.auth = (rig.settings.username, rig.settings.password)
        monkeypatch.setattr(rig.panels, 'add', lambda *a: pytest.fail('Page sent an order'))
        assert order['id'] in client.get('/admin').text
        detail = client.get('/admin/orders/' + order['id']).text
        assert 'İşlem geçmişi' in detail and 'ilerlemiyor' in detail and 'Sipariş kaydedildi' in detail
    assert rig.store.get(order['id']) == order


def test_legacy_record_gains_only_new_events(rig):
    order, _ = rig.engine.receive(payload())
    with rig.store.transaction() as conn:
        legacy = {k: v for k, v in order.items() if k not in {'history', 'phase_started_at', 'phase_revision', 'dispatch_revision'}}
        rig.store.execute(conn, 'UPDATE orders SET document=? WHERE id=?', (json.dumps(legacy), order['id']))
    current = rig.store.get(order['id'])
    current['state'] = 'review'
    rig.store.save(current)
    assert len(current['history']) == 1 and current['history'][0]['title'] == 'Bilgiler kontrol edilmeli'
