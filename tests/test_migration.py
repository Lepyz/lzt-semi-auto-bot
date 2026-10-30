import json

import pytest

from conftest import payload
from scripts.migrate_upstash import import_snapshot, read_snapshot


def snapshot():
    return {"dynamic_services": {"10": {"panel": "smmrush", "service_id": "123",
                                      "quantity": 100, "platform": "instagram", "active": True}},
            "package_configs": {}, "processed_orders": ["order:1", "itemsatis_order:1", "itemsatis_order:99"],
            "pending_orders": [{"itemsatis_order_id": "1", "advert_id": "10", "smm_order_id": "700",
                                "panel_key": "smmrush", "service_id": "123", "quantity": 100,
                                "platform": "instagram", "link": "https://instagram.com/customer",
                                "created_at": 1700000000}],
            "failed_orders": [], "queue": [json.dumps({"payload": payload(2)})],
            "processing": [json.dumps({"payload": payload(3)})], "dead": []}


def test_import_keeps_active_ids_and_dedup_and_never_submits(rig):
    counts = import_snapshot(rig.store, rig.settings, snapshot())
    assert counts["active"] == 1
    active = rig.store.by_source("itemsatis:1")
    assert active["state"] == "submitted" and active["parts"][0]["smm_id"] == "700"
    assert rig.store.owner(active["target"]) == active["id"]
    assert rig.store.by_source("itemsatis:99")["state"] == "legacy"
    assert rig.store.by_source("itemsatis:2")["state"] == "review"
    assert rig.store.by_source("itemsatis:3")["state"] == "uncertain"
    assert rig.store.setting("paused") and rig.store.setting("migration_complete")
    assert not rig.panels.adds


def test_import_can_be_rerun_without_duplicate_orders_or_parts(rig):
    import_snapshot(rig.store, rig.settings, snapshot())
    before = len(rig.store.orders())
    import_snapshot(rig.store, rig.settings, snapshot())
    assert len(rig.store.orders()) == before
    assert len(rig.store.by_source("itemsatis:1")["parts"]) == 1


def test_multiple_old_actives_on_same_target_are_all_respected(rig):
    data = snapshot()
    data["pending_orders"].append(dict(data["pending_orders"][0], itemsatis_order_id="4",
                                       smm_order_id="701"))
    import_snapshot(rig.store, rig.settings, data)
    first = rig.store.by_source("itemsatis:1")
    other = rig.store.by_source("itemsatis:4")
    rig.panels.current = {"status": "Completed", "terminal": True}
    rig.engine.refresh(first["id"])
    assert rig.engine.active_owner(first["target"]) == other["id"]


def test_partial_package_import_groups_component_ids(rig):
    data = snapshot()
    data["pending_orders"].append(dict(data["pending_orders"][0], smm_order_id="702",
                                       panel_key="medyabayim", service_id="222"))
    import_snapshot(rig.store, rig.settings, data)
    order = rig.store.by_source("itemsatis:1")
    assert len(order["parts"]) == 2
    assert {p["smm_id"] for p in order["parts"]} == {"700", "702"}


def test_unknown_legacy_panel_aborts_with_migration_gate_closed(rig):
    data = snapshot()
    data["pending_orders"][0]["panel_key"] = "unknown-old-panel"
    with pytest.raises(ValueError):
        import_snapshot(rig.store, rig.settings, data)
    assert rig.store.setting("paused") and not rig.store.setting("migration_complete")


def test_upstash_snapshot_is_read_only(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://redis.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "test-only")
    calls = []
    def request(url, **kwargs):
        command = kwargs["json"]
        calls.append(command)
        from types import SimpleNamespace
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"result": None})
    monkeypatch.setattr("scripts.migrate_upstash.requests.post", request)
    result = read_snapshot()
    assert len(calls) == 8
    assert all(c[0] in {"GET", "LRANGE"} for c in calls)
    assert result["pending_orders"] == []
