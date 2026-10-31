import json

import pytest
from fastapi.testclient import TestClient

from bot.notifications import Notifier
from bot.store import Conflict
from conftest import payload, receive_and_run
from main import create_app


@pytest.fixture
def client(rig):
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        client.app.state.engine.enqueue = rig.jobs.append
        client.auth = (rig.settings.username, rig.settings.password)
        client.get('/admin?view=all')
        yield client


def selection(order):
    return order['id'] + ':' + str(order['revision'])


def clean(client, orders, action='delete', **extra):
    return client.post('/admin/order-cleanup', data={
        'csrf': client.cookies['csrf'], 'selected': [selection(o) for o in orders],
        'action': action, 'confirmed': 'yes', **extra}, follow_redirects=False)


def test_close_unmapped_purchases_in_bulk_without_sending_or_alerting(client, rig):
    rig.store.delete_binding('10')
    orders = [receive_and_run(rig, n) for n in (1, 2)]
    response = clean(client, orders, 'close', view='all', q='Takipçi')
    assert response.status_code == 303 and 'view=all' in response.headers['location']
    assert len(rig.store.orders(states={'closed'})) == 2
    assert not rig.panels.adds and not rig.notices
    _, created = rig.engine.receive(payload())
    assert not created


def test_delete_removes_details_from_lists_but_retains_duplicate_protection(client, rig):
    rig.store.delete_binding('10')
    order = receive_and_run(rig)
    assert clean(client, [order]).status_code == 303
    deleted = rig.store.get(order['id'])
    assert deleted['state'] == 'deleted'
    assert 'instagram.com' not in json.dumps(deleted)
    assert deleted['source_key'] == order['source_key']
    assert deleted['legacy_source_key'] == order['legacy_source_key']
    assert not rig.store.orders() and not rig.store.state_counts()
    assert order['id'] not in client.get('/admin?view=all').text
    assert 'Kayıt ayrıntıları silindi' in client.get('/admin/orders/' + order['id']).text
    duplicate = client.post('/itemsatis-webhook', json=payload()).json()
    assert duplicate['status'] == 'already_saved' and duplicate['id'] == order['id']
    assert not rig.panels.adds


@pytest.mark.parametrize('action', ['close', 'delete'])
def test_protected_record_in_selection_prevents_all_cleanup(client, rig, action):
    first = receive_and_run(rig)
    held = receive_and_run(rig, 2)
    assert clean(client, [held, first], action).status_code == 400
    assert rig.store.get(held['id']) == held
    assert rig.store.owner(first['target']) == first['id']
    assert rig.store.get(first['id']) == first


def test_stale_selection_rolls_back_every_record(client, rig):
    rig.store.delete_binding('10')
    first, second = [receive_and_run(rig, n) for n in (1, 2)]
    changed = dict(second, handling=True)
    rig.store.save(changed)
    assert clean(client, [first, second]).status_code == 409
    assert rig.store.get(first['id']) == first
    assert rig.store.get(second['id'])['handling']


def test_uncertain_legacy_receipt_without_parts_cannot_be_closed_or_deleted(client, rig):
    rig.store.delete_binding('10')
    order = receive_and_run(rig)
    order.update(state='uncertain', parts=[])
    rig.store.save(order)
    for action in ('close', 'delete'):
        assert clean(client, [order], action).status_code == 400
    assert rig.store.get(order['id']) == order


def test_finished_deletion_does_not_remove_new_active_target_lock(client, rig):
    first = receive_and_run(rig)
    rig.panels.current = {'status': 'Completed', 'terminal': True}
    rig.engine.refresh(first['id'])
    finished = rig.store.get(first['id'])
    active = receive_and_run(rig, 2)
    assert clean(client, [finished]).status_code == 303
    assert rig.store.owner(active['target']) == active['id']
    assert len(rig.panels.adds) == 2


def test_bulk_cleanup_cancels_queued_alerts_and_does_not_send_selected_waiters(client, rig, monkeypatch):
    active = receive_and_run(rig)
    held = [receive_and_run(rig, n) for n in (2, 3)]
    pending = rig.store.pending_notifications()
    assert len(pending) == 2
    assert clean(client, held).status_code == 303
    notifier = Notifier(rig.store, rig.settings)
    monkeypatch.setattr(notifier, 'send', lambda _: pytest.fail('Deleted record sent an alert'))
    for notification in pending:
        notifier.deliver(notification)
    assert not rig.store.pending_notifications()
    assert len(rig.panels.adds) == 1
    assert rig.store.owner(active['target']) == active['id']


def test_bulk_close_only_makes_unselected_next_purchase_ready(client, rig):
    first = receive_and_run(rig)
    held = [receive_and_run(rig, n) for n in (2, 3, 4)]
    rig.panels.current = {'status': 'Completed', 'terminal': True}
    rig.engine.refresh(first['id'])
    selected = [rig.store.get(o['id']) for o in held[:2]]
    assert clean(client, selected, 'close').status_code == 303
    assert len(rig.store.orders(states={'closed'})) == 2
    assert rig.store.get(held[2]['id'])['state'] == 'ready'
    notice = client.app.state.notifier.queue.get_nowait()
    assert notice['order_id'] == held[2]['id'] and notice['action']
    assert client.app.state.notifier.queue.empty()
    assert len(rig.panels.adds) == 1


def test_cleanup_requires_admin_csrf_confirmation_and_valid_action(client, rig):
    rig.store.delete_binding('10')
    order = receive_and_run(rig)
    assert client.post('/admin/order-cleanup', data={'action': 'delete'}).status_code == 403
    assert clean(client, [order], confirmed='').status_code == 400
    assert clean(client, [order], action='send').status_code == 400
    assert client.post('/admin/order-cleanup', auth=('bad', 'bad'), data={
        'csrf': client.cookies['csrf'], 'selected': selection(order), 'action': 'delete', 'confirmed': 'yes'}).status_code == 401
    assert rig.store.get(order['id']) == order


def test_deleted_purchase_cannot_be_approved_and_double_cleanup_is_rejected(client, rig):
    rig.store.delete_binding('10')
    order = receive_and_run(rig)
    assert clean(client, [order]).status_code == 303
    assert clean(client, [order]).status_code == 409
    with pytest.raises(ValueError):
        rig.engine.approve(order['id'])
    with pytest.raises((ValueError, Conflict)):
        rig.engine.close_unsubmitted(order['id'], rig.store.get(order['id'])['revision'])
    assert not rig.panels.adds
