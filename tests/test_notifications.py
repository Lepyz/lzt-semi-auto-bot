from bot.notifications import Notifier


def notification():
    return {"key": "order:ready", "order_id": "a" * 32, "text": "Gönderebilirsin.", "action": True}


def test_repeated_delivery_has_one_send_and_no_saved_message_body(rig, monkeypatch):
    notifier = Notifier(rig.store, rig.settings)
    item = notification()
    rig.store.notify(item)
    calls = []
    monkeypatch.setattr(notifier, "send", lambda n: calls.append(n) or "sent")
    notifier.deliver(item)
    notifier.deliver(item)
    assert len(calls) == 1
    row = rig.store.notification(item["key"])
    assert row["state"] == "sent" and row["document"] == "{}"


def test_uncertain_telegram_delivery_is_not_automatically_repeated(rig, monkeypatch):
    notifier = Notifier(rig.store, rig.settings)
    item = notification()
    rig.store.notify(item)
    monkeypatch.setattr(notifier, "send", lambda _: "failed")
    notifier.deliver(item)
    assert rig.store.notification(item["key"])["state"] == "failed"
    assert notifier.queue.empty()


def test_command_reply_uses_no_database(rig, monkeypatch):
    notifier = Notifier(rig.store, rig.settings)
    monkeypatch.setattr(rig.store, "transaction", lambda: (_ for _ in ()).throw(AssertionError("No database")))
    calls = []
    monkeypatch.setattr(notifier, "send", lambda n: calls.append(n) or "sent")
    notifier.deliver(dict(notification(), ephemeral=True))
    assert len(calls) == 1


def test_ready_button_opens_authenticated_web_preview_instead_of_sending(rig, monkeypatch):
    import requests
    from types import SimpleNamespace
    notifier = Notifier(rig.store, rig.settings)
    rig.settings.bot_token, rig.settings.chat_id = "test-only", "123"
    captured = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: captured.append(k["json"]) or SimpleNamespace(
        status_code=200, json=lambda: {"ok": True}))
    notifier.send(notification())
    assert "reply_markup" not in captured[-1]
    rig.settings.telegram_secret = "secret"
    rig.settings.public_url = "https://example.invalid"
    notifier.send(notification())
    button = captured[-1]["reply_markup"]["inline_keyboard"][0][0]
    assert "callback_data" not in button
    assert button["url"].endswith("/admin/orders/" + "a" * 32 + "?preview=1")
    assert button["text"] == "Kontrol edip gönder"


def test_restart_does_not_repeat_ambiguous_inflight_notification(rig):
    rig.store.notify(notification())
    rig.store.claim_notification("order:ready")
    rig.store.recover_notifications()
    assert not rig.store.pending_notifications()
    assert rig.store.notification("order:ready")["state"] == "failed"


def test_unsent_policy_waiting_notice_is_delivered_once_not_filtered_as_legacy(rig, monkeypatch):
    from conftest import receive_and_run
    receive_and_run(rig, 1)
    held = receive_and_run(rig, 2)
    assert held["state"] == "waiting"
    notices = rig.store.pending_notifications()
    assert len(notices) == 1 and notices[0]["order_id"] == held["id"]
    assert notices[0]["policy"] == "unsent-v2"
    notifier = Notifier(rig.store, rig.settings)
    calls = []
    monkeypatch.setattr(notifier, "send", lambda item: calls.append(item) or "sent")
    for _ in range(3):
        notifier.deliver(notices[0])
    assert len(calls) == 1
    assert "BEKLETİLDİ" in calls[0]["text"] and held["itemsatis_id"] in calls[0]["text"]
