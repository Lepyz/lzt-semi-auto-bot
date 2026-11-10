"""The panel receives clean https://www.instagram.com/<path> links; usernames are not links."""
import copy

import pytest

from bot.links import normalize_panel_link, target_key, valid_link
from bot.payloads import extract_links
from conftest import payload, receive_and_run

PROFILE = "https://www.instagram.com/resulullahinyolunda_orhan"
REEL = "https://www.instagram.com/reel/DfPnCQcgznf"


@pytest.mark.parametrize("value,expected,kind", [
    (PROFILE, PROFILE, "profile"),
    ("instagram.com/resulullahinyolunda_orhan", PROFILE, "profile"),
    ("www.instagram.com/resulullahinyolunda_orhan", PROFILE, "profile"),
    ("https://instagram.com/resulullahinyolunda_orhan", PROFILE, "profile"),
    ("  " + PROFILE + "  ", PROFILE, "profile"),
    (REEL, REEL, "content"),
    ("instagram.com/reel/DfPnCQcgznf", REEL, "content"),
    ("www.instagram.com/reel/DfPnCQcgznf", REEL, "content"),
    ("reel/DfPnCQcgznf", REEL, "content"),
    ("/reel/DfPnCQcgznf/", REEL, "content"),
    (PROFILE + "/?igsh=Example#share", PROFILE, "profile"),
    ("https://www.instagram.com/kemalinyericafe?utm_source=qr", "https://www.instagram.com/kemalinyericafe", "profile"),
    (REEL + "/?utm_source=ig_web_button_share_sheet#share", REEL, "content"),
])
def test_clean_www_format_without_tracking(value, expected, kind):
    assert normalize_panel_link(value, "instagram") == expected
    assert normalize_panel_link(expected, "instagram") == expected
    assert valid_link(value, "instagram", kind)
    assert extract_links({"post_datas": {"Link": value}})["instagram"] == expected


@pytest.mark.parametrize("raw", ["resulullahinyolunda_orhan", "@resulullahinyolunda_orhan", "@customer.com"])
def test_username_is_held_as_link_not_found_and_never_sent(rig, raw):
    order = receive_and_run(rig, 1, raw)
    assert order["state"] == "review" and order["reason_code"] == "link_username"
    assert "kullanıcı adı yazmış" in order["error"] and raw in order["error"]
    assert not rig.panels.adds
    alerts = [n for n in rig.notices if n["order_id"] == order["id"]]
    assert len(alerts) == 1 and "Link bulunamadı (müşteri yazdı: " + raw + ")" in alerts[0]["text"]


def test_old_unsent_record_completed_from_a_username_is_held_too(rig):
    order, _ = rig.engine.receive(payload(1, PROFILE))
    rig.engine.prepare(order)
    order.update(customer_inputs=["resulullahinyolunda_orhan"], state="queued")
    rig.store.save(order)
    rig.engine.execute(order["id"])
    assert rig.store.get(order["id"])["reason_code"] == "link_username" and not rig.panels.adds


def test_stored_link_with_tracking_is_cleaned_at_send_time(rig):
    order, _ = rig.engine.receive(payload(1, PROFILE))
    rig.engine.prepare(order)
    order["parts"][0]["link"] = PROFILE + "?utm_source=qr"
    order["state"] = "queued"
    rig.store.save(order)
    rig.engine.execute(order["id"])
    assert rig.panels.adds[0][1] == PROFILE


@pytest.mark.parametrize("raw,expected,kind", [
    ("https://instagram.com/resulullahinyolunda_orhan?utm_source=qr", PROFILE, "profile"),
    ("reel/DfPnCQcgznf", REEL, "content"),
])
def test_panel_receives_the_complete_url(rig, raw, expected, kind):
    binding = rig.store.setting("binding:10")
    binding["components"][0]["target_type"] = kind
    rig.store.set_setting("binding:10", binding)
    order = receive_and_run(rig, 1, raw)
    assert order["state"] == "submitted"
    assert order["link"] == order["parts"][0]["link"] == expected
    assert len(rig.panels.adds) == 1 and rig.panels.adds[0][1] == expected


def test_www_completion_does_not_bypass_an_existing_active_order(rig):
    first = receive_and_run(rig, 1, PROFILE)
    second = receive_and_run(rig, 2, PROFILE.replace("www.", "") + "/?igsh=other")
    assert first["state"] == "submitted" and second["state"] == "waiting"
    assert first["target"] == second["target"] and len(rig.panels.adds) == 1
    assert target_key(REEL, "instagram") != target_key(REEL.lower(), "instagram")


def test_partial_old_package_completes_only_the_remaining_components_link(rig):
    order, _ = rig.engine.receive(payload(1, PROFILE))
    rig.engine.prepare(order)
    submitted = order["parts"][0]
    submitted.update(state="submitted", smm_id="9001", link=PROFILE.replace("www.", ""))
    remaining = dict(submitted, service_id="456", state="error", smm_id="")
    order.update(parts=[submitted, remaining], state="queued")
    rig.store.save(order)
    rig.store.acquire_target(order["target"], order["id"])
    snapshot = copy.deepcopy(submitted)
    rig.engine.execute(order["id"])
    saved = rig.store.get(order["id"])
    assert saved["parts"][0] == snapshot
    assert len(rig.panels.adds) == 1 and rig.panels.adds[0][1] == PROFILE
    assert saved["state"] == "submitted"
