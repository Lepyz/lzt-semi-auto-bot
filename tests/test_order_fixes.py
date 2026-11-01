import json
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bot import bulk
from bot.notifications import Notifier
from bot.panels import AddResult
from bot.payloads import get_sale_price
from bot.profit import evaluate, guard_settings
from conftest import payload, receive_and_run
from main import create_app


@pytest.fixture
def client(rig):
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        client.auth = (rig.settings.username, rig.settings.password)
        client.app.state.engine.enqueue = rig.jobs.append
        client.get('/admin')
        yield client


def form_value(page, name):
    import html
    return html.unescape(re.search(r'name="' + name + r'" value="([^"]*)"', page).group(1))


@pytest.mark.parametrize('data,expected', [
    ({'commission': '7 TL'}, None),
    ({'fee': '5 TL', 'content': 'Satış bedeli 100 TL'}, 100),
    ({'content': 'Kesinti 7 TL. Satış bedeli 100 TL'}, 100),
    ({'product_name': '100 TL değerinde hizmet', 'advert': {'price': 100}}, None),
    ({'content': 'Satış bedeli 100 TL. Ödeme tutarı 90 TL'}, None),
    ({'price': 150, 'sale_price': 100}, 100),
    ({'content': 'İlanınız <b>49,90 TL</b> tutarında satıldı'}, 49.9),
])
def test_only_identifiable_sale_amounts_are_accepted(data, expected):
    assert get_sale_price(data)[0] == expected


def test_success_notice_has_panel_id_and_is_actually_sent_only_once(rig, monkeypatch):
    order = receive_and_run(rig)
    notice = rig.notices[0]
    assert notice['key'] == order['id'] + ':submitted'
    assert '1001' in notice['text'] and 'PANELE GÖNDERİLDİ' in notice['text']
    rig.engine.save(order, 'submitted')  # A revision change cannot create a second success notice.
    rig.engine.receive(payload())
    assert len(rig.notices) == len(rig.panels.adds) == 1
    rig.settings.bot_token, rig.settings.chat_id = 'test-only', '123'
    rig.settings.public_url = 'https://example.invalid'
    calls = []
    monkeypatch.setattr('bot.notifications.requests.post', lambda *a, **kw: calls.append(kw['json']) or
                        SimpleNamespace(status_code=200, json=lambda: {'ok': True}))
    notifier = Notifier(rig.store, rig.settings)
    notifier.deliver(notice)
    notifier.deliver(notice)
    assert len(calls) == 1 and '1001' in calls[0]['text']
    assert rig.store.notification(notice['key'])['document'] == '{}'


def test_package_failure_lists_already_accepted_components(rig):
    binding = rig.store.setting('binding:10')
    binding['components'].append(dict(binding['components'][0], service_id='456'))
    rig.store.set_setting('binding:10', binding)
    rig.panels.results = [AddResult('submitted', '9001'), AddResult('error', error='Insufficient balance')]
    order = receive_and_run(rig)
    assert order['state'] == 'error' and len(rig.notices) == 1
    assert '9001' in rig.notices[0]['text'] and not rig.notices[0]['key'].endswith(':submitted')


def test_missing_advert_alert_can_be_repaired_without_automatic_send(rig):
    data = {'event': 'payment.completed', 'order_id': 'missing-advert'}
    order, _ = rig.engine.receive(data)
    assert order['reason_code'] == 'advert_missing' and len(rig.notices) == 1
    rig.engine.receive(data)
    assert len(rig.notices) == 1
    rig.engine.repair(order['id'], 'https://instagram.com/customer', order['revision'], advert_id='10')
    repaired = rig.store.get(order['id'])
    assert repaired['advert_id'] == '10' and repaired['state'] == 'review' and not rig.panels.adds
    rig.engine.approve(order['id'], repaired['revision'])
    rig.engine.execute(order['id'])
    assert len(rig.panels.adds) == 1
    assert not rig.engine.receive(data)[1]


def test_profit_uses_fixed_seven_percent_and_includes_net_and_target_prices(rig):
    rig.store.set_setting('profit_guard', {'mode': 'observe', 'min_profit': 10, 'commission': 0.2})
    guard = guard_settings(rig.store)
    assert guard['commission'] == 0.07
    order = {'sale_price': 100, 'price_source': 'price', 'parts': [
        {'panel': 'smmrush', 'service_id': '123', 'quantity': 100}]}
    rig.panels.rates[('smmrush', '123')] = {'rate': 400, 'type': 'Default'}
    check = evaluate(order, rig.panels, guard)
    assert (check['commission'], check['net_sale'], check['cost'], check['profit']) == (7, 93, 40, 53)
    assert check['margin'] == 53 and check['break_even_sale'] == 43.01 and check['target_sale'] == 53.76
    order['sale_price'] = 3.50
    assert evaluate(order, rig.panels, guard)['commission'] == 0.25  # Half-kuruş rounds up.


def test_old_unqualified_text_price_requires_manual_confirmation(rig):
    rig.store.set_setting('profit_guard', {'mode': 'enforce', 'min_profit': 10})
    data = dict(payload(), price=100)
    order, _ = rig.engine.receive(data)
    order.update(sale_price=7, price_source='metin', price_version=1)
    rig.store.save(order)
    rig.engine.execute(order['id'])
    saved = rig.store.get(order['id'])
    assert saved['reason_code'] == 'price_unknown' and not rig.panels.adds


def test_sale_correction_is_confirmed_and_has_no_external_side_effect(client, rig, monkeypatch):
    data = dict(payload(), price=100)
    rig.panels.rates[('smmrush', '123')] = {'rate': 400, 'type': 'Default'}
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order['id'])
    order = rig.store.get(order['id'])
    before = len(rig.notices)
    monkeypatch.setattr(rig.panels, 'service_rate', lambda *a: pytest.fail('Correction called a panel'))
    path = '/admin/orders/' + order['id'] + '/price'
    form = {'csrf': client.cookies['csrf'], 'revision': order['revision'], 'price': '200,00'}
    assert client.post(path, data=form).status_code == 400
    assert client.post(path, data={**form, 'confirmed': 'yes'}, follow_redirects=False).status_code == 303
    corrected = rig.store.get(order['id'])
    assert corrected['state'] == 'submitted' and corrected['profit']['profit'] == 146
    assert corrected['profit']['at'] == order['profit']['at']  # Cost snapshot, not a fresh price lookup.
    assert len(rig.notices) == before and len(rig.panels.adds) == 1
    assert client.post(path, data={**form, 'confirmed': 'yes'}).status_code == 409


def test_negative_profit_remains_numeric_in_csv_and_text_fields_are_escaped(client, rig):
    rig.panels.rates[('smmrush', '123')] = {'rate': 400, 'type': 'Default'}
    data = dict(payload(), price=30, product_name='=unsafe-cell')
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order['id'])
    csv = client.get('/admin/export').text
    assert "'=unsafe-cell" in csv and '30,00;2,10;40,00;-12,10' in csv


@pytest.mark.parametrize('operation', ['import', 'swap'])
def test_preview_uses_the_same_snapshot_as_its_changes(client, rig, monkeypatch, operation):
    original = rig.store.bindings
    calls = []
    def change_after_read():
        current = original()
        calls.append(True)
        changed = json.loads(json.dumps(current['10']))
        changed['components'][0]['service_id'] = '456'
        rig.store.set_setting('binding:10', changed)
        return current
    csv = bulk.export_csv(original(), rig.settings.panels).replace('123;100', '999;100')
    monkeypatch.setattr(rig.store, 'bindings', change_after_read)
    csrf = client.cookies['csrf']
    if operation == 'import':
        page = client.post('/admin/services/import', data={'csrf': csrf},
                           files={'file': ('x.csv', csv.encode(), 'text/csv')}).text
    else:
        page = client.post('/admin/services/swap', data={'csrf': csrf, 'panel': 'smmrush',
                                                       'old_service': '123', 'new_service': '999'}).text
    response = client.post('/admin/services/bulk-apply', data={'csrf': csrf, 'confirmed': 'yes',
        'payload': form_value(page, 'payload'), 'snapshot': form_value(page, 'snapshot')}, follow_redirects=False)
    assert response.status_code == 409 and rig.store.setting('binding:10')['components'][0]['service_id'] == '456'
    assert len(calls) == 1 and not rig.panels.adds


def test_binding_writers_serialize_during_bulk_apply(client, rig, monkeypatch):
    if not rig.store.postgres:
        pytest.skip('Concurrent row writers verified on PostgreSQL')
    csrf = client.cookies['csrf']
    page = client.post('/admin/services/swap', data={'csrf': csrf, 'panel': 'smmrush',
        'old_service': '123', 'new_service': '999'}).text
    original = rig.store.execute
    attempting, blocked = Event(), Event()
    changed = rig.store.setting('binding:10')
    changed['components'][0]['service_id'] = '456'
    futures = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        def write():
            attempting.set()
            rig.store.set_setting('binding:10', changed)
        def execute(conn, sql, params=()):
            result = original(conn, sql, params)
            if sql.startswith('SELECT key,value FROM settings WHERE key LIKE') and not futures:
                futures.append(pool.submit(write))
                assert attempting.wait(5)
                blocked.set()
                from concurrent.futures import TimeoutError
                with pytest.raises(TimeoutError):
                    futures[0].result(timeout=0.2)
            return result
        monkeypatch.setattr(rig.store, 'execute', execute)
        response = client.post('/admin/services/bulk-apply', data={'csrf': csrf, 'confirmed': 'yes',
            'payload': form_value(page, 'payload'), 'snapshot': form_value(page, 'snapshot')}, follow_redirects=False)
        assert response.status_code == 303 and blocked.is_set()
        futures[0].result(timeout=10)
    assert rig.store.setting('binding:10')['components'][0]['service_id'] == '456'
