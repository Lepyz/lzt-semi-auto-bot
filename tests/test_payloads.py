import json

import pytest

from bot.payloads import classify, extract_links, get_order_id, source_key, target_key, valid_link


def test_embedded_legacy_python_dict_payload():
    data = {"raw": "{'event':'advert_sold','order_id':'777','advert_id':'10','post_datas':{'Link':'https://instagram.com/customer'}}"}
    assert classify(data) == "order"
    assert get_order_id(data) == "777"
    assert extract_links(data)["instagram"] == "https://instagram.com/customer"


def test_notification_id_does_not_override_real_purchase_id():
    data = {"id": "notification123", "data": {"order_id": "purchase456", "advert_id": "10"}}
    assert get_order_id(data) == "purchase456"
    assert source_key(data) == "itemsatis:purchase456"


def test_legacy_details_id_is_still_supported():
    data = {"event": "advert_sold", "details": {"id": "777", "advert": {"id": "10"}}}
    assert get_order_id(data) == "777" and classify(data) == "order"


def test_json_encoded_customer_fields():
    data = {"post_datas": json.dumps({"Link": "https://tiktok.com/@customer"})}
    assert extract_links(data)["tiktok"] == "https://www.tiktok.com/@customer"


@pytest.mark.parametrize("event", ["listing_chat_started", "message.created", "review_received", "order.message"])
def test_non_purchase_webhooks_ignored(event):
    assert classify({"event": event, "order_id": "1", "advert_id": "10"}) == "ignore"


def test_missing_product_or_price_does_not_discard_purchase():
    assert classify({"order_id": "1", "advert_id": "10"}) == "order"


def test_known_sale_without_order_id_remains_compatible():
    assert classify({"event": "advert_sold", "advert_id": "10"}) == "order"
    assert classify({"event": "order.created"}) == "review"
    assert classify({"event": "unknown_notification", "advert_id": "10"}) == "review"


def test_legacy_payload_hash_matches_old_bot_and_ignores_queue_fields():
    import hashlib
    from bot.payloads import legacy_payload_key
    data = {"event": "advert_sold", "advert_id": "10", "details": {"time": 1700000000}}
    expected = hashlib.sha1(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:24]
    assert legacy_payload_key(data) == "legacy_payload:" + expected
    queued = dict(data, _queue_id="runtime-only", processing_started_at=1700000100)
    assert legacy_payload_key(queued) == legacy_payload_key(data)
    assert source_key(queued) == source_key(data)


@pytest.mark.parametrize("url", [
    "https://cdn.itemsatis.com/uploads/test.jpg",
    "https://instagram.com.evil.invalid/customer",
    "https://evil.invalid/?instagram.com/customer",
    "https://instagram.com@evil.invalid/customer",
    "https://itemsatis.com/ilan/10",
])
def test_invalid_customer_targets(url):
    assert not valid_link(url, "instagram")


def test_tracking_links_share_target_but_youtube_video_case_preserved():
    assert target_key("https://www.instagram.com/Customer/?igsh=123", "instagram") == target_key(
        "https://instagram.com/customer", "instagram")
    assert target_key("https://youtu.be/AbC?si=tracking", "youtube") == "youtube.com/watch?v=AbC"
    assert target_key("https://youtube.com/watch?v=AbC&feature=share", "youtube") == "youtube.com/watch?v=AbC"
    assert target_key("https://youtube.com/watch?v=abc", "youtube") != "youtube.com/watch?v=AbC"
    assert target_key("youtu.be/AbC", "youtube") == "youtube.com/watch?v=AbC"
    assert target_key("HTTPS://WWW.INSTAGRAM.COM/Customer/#share", "instagram") == "instagram.com/customer"
