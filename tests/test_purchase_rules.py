"""Regressions for false purchase alerts and customer target protection."""
import json

import pytest
from fastapi.testclient import TestClient

from bot import bulk
from bot.engine import normalize_binding
from bot.links import link_issue, normalize_panel_link, target_key, valid_link
from bot.notifications import Notifier
from bot.payloads import classify, extract_links, get_order_id, source_key
from bot.profit import guard_settings
from conftest import payload, receive_and_run
from main import create_app


@pytest.mark.parametrize("event", ["", "unknown_notification", "advert_updated", "advert.created",
    "listing.renewed", "advert.expired", "advert.deleted", "order.cancelled", "order.completed", "order.status"])
def test_listing_or_status_events_never_become_new_purchases(event):
    data = {"event": event, "id": "notification-only", "advert": {"id": "10", "title": "Takipçi"}}
    assert classify(data) == "ignore"
    assert get_order_id(data) == ""
    if event.startswith("order."):
        assert classify(dict(data, order_id="old-order")) == "ignore"


def test_false_alert_burst_has_no_database_or_panel_calls(rig, monkeypatch):
    monkeypatch.setattr(rig.store, "transaction", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected SQL")))
    for number in range(100):
        order, created = rig.engine.receive({"advert_id": str(number), "product_name": "İlan",
                                             "id": str(number), "event": "unknown_notification"})
        assert order is None and not created
    assert not rig.jobs and not rig.notices and not rig.panels.adds and not rig.panels.rate_calls
    assert rig.engine.ignored_total == 100 and len(rig.engine.ignored) == 20


@pytest.mark.parametrize("data,kind", [
    ({"event": "advert_sold", "advert_id": "10"}, "order"),
    ({"event": "advert_sold"}, "review"),
    ({"order_id": "real", "advert_id": "10"}, "order"),
    ({"event": "changed_format", "order_id": "real", "advert_id": "10"}, "review"),
    ({"event": "payment.completed", "purchase_id": "real"}, "review"),
    ({"event": "siparis_odendi"}, "review"),
    ({"advert_id": "10", "post_datas": {"Link": "@customer"}, "sale_price": 100}, "review"),
])
def test_positive_purchase_evidence_is_still_kept(data, kind):
    assert classify(data) == kind


def test_known_legacy_sale_and_true_incomplete_sale_notify_once(rig):
    data = {"event": "advert_sold", "advert_id": "10", "post_datas": {"Link": "@customer"}}
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order["id"])
    assert rig.store.get(order["id"])["state"] == "submitted"
    rig.engine.receive(data)
    broken = dict(data, order_id="real-broken", post_datas={})
    order, _ = rig.engine.receive(broken)
    rig.engine.execute(order["id"])
    rig.engine.receive(broken)
    assert len(rig.panels.adds) == 1 and len(rig.notices) == 2
    assert rig.store.get(order["id"])["reason_code"] == "link_missing"


@pytest.mark.parametrize("value,platform", [
    ("instagram.com/customer", "instagram"), ("@customer", "instagram"), ("customer.name", "instagram"),
    ("@customer", "tiktok"), ("customer", "tiktok"), ("tiktok.com/@customer", "tiktok"),
])
def test_unambiguous_incomplete_customer_links_are_completed(value, platform):
    assert valid_link(value, platform, "profile")
    assert normalize_panel_link(value, platform).startswith("https://")
    assert platform in extract_links({"post_datas": {"Profil Linki": value}})


@pytest.mark.parametrize("value,platform", [
    ("https://evil.invalid/instagram.com/customer", "instagram"),
    ("https://instagram.com.evil.invalid/customer", "instagram"),
    ("https://instagram.com@evil.invalid/customer", "instagram"),
    ("https://instagram.com:444/customer", "instagram"),
    ("instgram.com/customer", "instagram"), ("https://instagram.com/", "instagram"),
    ("https://instagram.com/accounts/login", "instagram"), ("https://instagram.com/p/", "instagram"),
    ("https://instagram.com/customer photo", "instagram"), ("https://instagram.com/customer/image.jpg", "instagram"),
    ("https://instagram.com/%2563ustomer", "instagram"),
    ("https://youtube.com/watch", "youtube"), ("https://youtube.com/watch?v=", "youtube"),
    ("https://tiktok.com/@", "tiktok"), ("https://tiktok.com/@customer/video/", "tiktok"),
    ("https://vt.tiktok.com/ABC", "tiktok"), ("https://tiktok.com/@customer", "instagram"),
])
def test_invalid_or_unresolved_targets_are_not_sent(value, platform):
    assert not valid_link(value, platform)
    assert platform not in extract_links({"post_datas": {"Link": value}})


def test_seller_listing_and_image_links_are_not_customer_inputs():
    data = {"advert": {"description": "https://instagram.com/seller", "url": "https://tiktok.com/@seller"},
            "seller": {"instagram": "https://instagram.com/seller"}, "image": "https://instagram.com/p/SELLER"}
    assert extract_links(data) == {}
    data["post_datas"] = {"Link": "https://evil.invalid/instagram.com/customer"}
    data["content"] = "Satıcı https://instagram.com/seller"
    assert extract_links(data) == {}


def test_turkish_customer_connection_label_still_reads_the_target():
    assert extract_links({"post_datas": {"Bağlantı adresiniz": "instagram.com/customer"}})["instagram"] == "https://instagram.com/customer"


def test_alias_and_tracking_formats_lock_the_same_customer(rig):
    first = receive_and_run(rig, 1, "https://instagram.com/Customer?igsh=tracking")
    second = receive_and_run(rig, 2, "instagr.am/customer/")
    third = receive_and_run(rig, 3, "@CUSTOMER")
    assert first["state"] == "submitted" and second["state"] == third["state"] == "waiting"
    assert len(rig.panels.adds) == 1
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.refresh(first["id"])
    assert rig.store.get(second["id"])["state"] == "ready"
    assert rig.store.get(third["id"])["state"] == "waiting" and len(rig.panels.adds) == 1


def test_canonical_video_ids_preserve_case_and_ignore_tracking():
    assert target_key("https://instagram.com/p/AbC", "instagram") != target_key("https://instagram.com/p/abc", "instagram")
    assert target_key("https://youtube.com/shorts/AbC?si=1", "youtube") == target_key("https://youtu.be/AbC", "youtube")
    assert target_key("https://instagram.com/%63ustomer", "instagram") == target_key("https://instagram.com/customer", "instagram")
    assert target_key("https://mobile.instagr.am/Customer", "instagram") == target_key("@customer", "instagram")
    assert target_key("https://mobile.twitter.com/Customer", "x") == target_key("https://x.com/customer", "x")


def test_old_instagram_alias_lock_still_blocks_new_canonical_customer(rig):
    first = receive_and_run(rig, 1)
    old = "instagr.am/customer"
    rig.store.release_target(first["target"], first["id"])
    first["target"] = old
    first["parts"][0]["link"] = "https://instagr.am/customer"
    rig.store.save(first)
    rig.store.acquire_target(old, first["id"])
    second = receive_and_run(rig, 2, "@customer")
    assert second["state"] == "waiting" and len(rig.panels.adds) == 1
    # Complete via the old target; the canonical waiter still becomes ready,
    # and is never sent automatically.
    rig.engine.recent_checks.clear()
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.watch[second["target"]] = 0
    rig.engine.check_due()
    assert rig.store.get(second["id"])["state"] == "ready" and len(rig.panels.adds) == 1


def test_same_status_outage_does_not_keep_writing_or_notifying(rig, monkeypatch):
    order = receive_and_run(rig)
    monkeypatch.setattr(rig.panels, "status", lambda _: None)
    for _ in range(3):
        rig.engine.refresh(order["id"])
    saved = rig.store.get(order["id"])
    for _ in range(10):
        rig.engine.refresh(order["id"])
    assert rig.store.get(order["id"])["revision"] == saved["revision"]
    assert len(rig.notices) == 2 and rig.store.owner(order["target"]) == order["id"]


def test_manually_approved_old_alias_cannot_bypass_current_active_target(rig):
    first = receive_and_run(rig, 1)
    order, _ = rig.engine.receive(payload(2))
    rig.engine.prepare(order)
    order["parts"][0]["link"] = "https://instagr.am/customer"
    order.update(target="instagr.am/customer", state="review")
    rig.store.save(order)
    rig.engine.approve(order["id"], order["revision"])
    rig.engine.execute(order["id"])
    assert rig.store.get(order["id"])["state"] == "waiting" and len(rig.panels.adds) == 1
    assert rig.store.owner(first["target"]) == first["id"]


@pytest.mark.parametrize("value,code", [
    ("https://instagram.com/p/AbC", "link_type"),
    ("https://tiktok.com/@customer", "link_missing"),
    ("https://evil.invalid/instagram.com/customer", "link_missing"),
])
def test_bad_target_is_preserved_with_specific_reason_without_panel_cost_calls(rig, value, code):
    order = receive_and_run(rig, 1, value)
    assert order["state"] == "review" and order["reason_code"] == code
    assert order["customer_inputs"] == [value]
    assert not rig.panels.adds and not rig.panels.rate_calls
    assert len(rig.notices) == 1


def test_multiple_targets_and_tiktok_short_links_require_manual_repair(rig):
    data = payload()
    data["post_datas"] = {"Profil Linki": "@one", "Link": "@two"}
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order["id"])
    assert rig.store.get(order["id"])["reason_code"] == "link_ambiguous"
    binding = rig.store.setting("binding:10")
    binding["components"][0]["platform"] = "tiktok"
    rig.store.set_setting("binding:10", binding)
    order = receive_and_run(rig, 2, "https://vt.tiktok.com/ABC")
    assert order["reason_code"] == "link_short" and not rig.panels.adds
    rig.engine.repair(order["id"], "@customer", order["revision"])
    repaired = rig.store.get(order["id"])
    assert repaired["parts"][0]["link"] == "https://www.tiktok.com/@customer" and repaired["state"] == "review"
    assert not rig.panels.adds and len(rig.jobs) == 2


def test_target_type_survives_mapping_and_both_csv_formats(rig):
    current = rig.store.bindings()
    current["10"]["components"][0]["target_type"] = "content"
    current["10"] = normalize_binding(current["10"], rig.settings.panels)
    csv = bulk.export_csv(current, rig.settings.panels)
    changes, errors = bulk.parse_import(csv, {}, rig.settings.panels)
    assert not errors and changes[0]["after"]["components"][0]["target_type"] == "content"
    old_csv = "\n".join(";".join(line.split(";")[:8]) for line in csv.lstrip("\ufeff").splitlines())
    changes, errors = bulk.parse_import(old_csv, current, rig.settings.panels)
    assert not errors and not changes


def test_default_guard_blocks_loss_and_missing_price_but_allows_profit(rig):
    with rig.store.transaction() as conn:
        rig.store.execute(conn, "DELETE FROM settings WHERE key='profit_guard'")
    assert guard_settings(rig.store)["mode"] == "enforce" and guard_settings(rig.store)["min_profit"] == 0
    rig.panels.rates[("smmrush", "123")] = {"rate": 100, "type": "Default"}
    for number, sale, state, code in [(1, "10", "review", "low_profit"), (2, None, "review", "price_unknown"),
                                      (3, "20", "submitted", "")]:
        data = payload(number, f"https://instagram.com/person{number}")
        if sale:
            data["sale_price"] = sale
        order, _ = rig.engine.receive(data)
        rig.engine.execute(order["id"])
        order = rig.store.get(order["id"])
        assert order["state"] == state and order["reason_code"] == code
        if sale == "10":
            assert order["profit"]["profit"] == -0.7
    assert len(rig.panels.adds) == 1 and len(rig.notices) == 3


def test_old_advert_only_review_is_not_replayed_as_a_telegram_alert(rig, monkeypatch):
    data = payload()
    order, _ = rig.engine.receive(data)
    order.update(state="review", reason_code="review", itemsatis_id="", links={}, parts=[], sale_price=None)
    order.pop("receipt_kind")
    rig.store.save(order)
    item = {"key": order["id"] + ":review:0", "order_id": order["id"], "text": "Eski yanlış uyarı", "policy": "order-events-v3"}
    rig.store.notify(item)
    notifier = Notifier(rig.store, rig.settings)
    monkeypatch.setattr(notifier, "send", lambda _: (_ for _ in ()).throw(AssertionError("No Telegram")))
    notifier.deliver(item)
    assert rig.store.notification(item["key"])["state"] == "cancelled"
    assert rig.store.get(order["id"])["state"] == "review"


def test_mobile_link_help_and_mapping_selector_are_read_only(rig):
    order = receive_and_run(rig, 1, "https://instagram.com/p/AbC")
    with TestClient(create_app(rig.settings, rig.store, rig.panels, start_background=False)) as client:
        client.auth = (rig.settings.username, rig.settings.password)
        path = "/admin/orders/" + order["id"]
        page = client.get(path).text
        assert "Müşteriye yazılacak mesajı kopyala" in page and "https://instagram.com/p/AbC" in page
        assert 'data-field="target_type"' in client.get("/admin/services").text
        assert rig.store.get(order["id"])["revision"] == order["revision"] and not rig.panels.adds
