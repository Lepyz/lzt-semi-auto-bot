"""Read-only Upstash export and idempotent import. Never sends panel orders."""
import argparse
import json
import hashlib
import os
import sys
import time
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import Settings, panel_key
from bot.engine import normalize_binding
from bot.payloads import extract_links, get_advert_id, get_order_id, get_product_name, source_key, target_key
from bot.store import Store


def read_snapshot():
    url, token = os.getenv("UPSTASH_REDIS_REST_URL"), os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        raise ValueError("Upstash ortam değişkenleri eksik.")
    snapshot = {}
    commands = [
        ("dynamic_services", ["GET", "dynamic_services"], {}),
        ("package_configs", ["GET", "package_configs"], {}),
        ("pending_orders", ["GET", "pending_orders"], []),
        ("processed_orders", ["GET", "processed_orders"], []),
        ("failed_orders", ["GET", "failed_orders"], []),
    ]
    for name, env_key, default in [
        ("queue", "ITEMSATIS_WEBHOOK_QUEUE_KEY", "queue:itemsatis:webhooks"),
        ("processing", "ITEMSATIS_WEBHOOK_PROCESSING_KEY", "queue:itemsatis:processing"),
        ("dead", "ITEMSATIS_WEBHOOK_DEAD_KEY", "queue:itemsatis:dead"),
    ]:
        commands.append((name, ["LRANGE", os.getenv(env_key, default), 0, -1], []))
    for name, command, default in commands:
        try:
            response = requests.post(url, headers={"Authorization": "Bearer " + token},
                                     json=command, timeout=(5, 30))
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError()
            value = result.get("result")
            snapshot[name] = json.loads(value) if isinstance(value, str) else (value if value is not None else default)
        except (requests.RequestException, ValueError):
            raise ValueError("Upstash okunamadı: " + name + ". Kaynak kayıtlar değiştirilmedi.") from None
    return snapshot


def empty_order(source, itemsatis_id="", advert_id="", created_at=None):
    now = int(time.time() * 1_000_000)
    return {"id": uuid.uuid4().hex, "source_key": source, "itemsatis_id": itemsatis_id,
            "advert_id": advert_id, "product_name": "", "link": "", "links": {}, "target": "",
            "state": "legacy", "parts": [], "manual_required": True, "error": "",
            "created_at": created_at or now, "updated_at": now}


def restore_panel(value, settings):
    key = panel_key(value)
    if key in settings.panels:
        return key
    for candidate, panel in settings.panels.items():
        if str(panel["name"]).lower() == str(value).lower():
            return candidate
    raise ValueError("Eski kayıtta tanınmayan panel var: " + str(value)[:60])


def merge_order(store, order):
    current, created = store.create(order)
    if not created and current["state"] == "legacy" and order["state"] != "legacy":
        order.update(id=current["id"], revision=current["revision"])
        store.save(order)
        return order
    return current


def import_snapshot(store, settings, snapshot):
    """Rerunnable import: source keys and panel IDs are never submitted again."""
    store.initialize()
    store.set_setting("paused", True)
    store.set_setting("migration_complete", False)
    counts = {"bindings": 0, "history": 0, "active": 0, "review": 0}
    for kind in ("dynamic_services", "package_configs"):
        for advert_id, raw in snapshot.get(kind, {}).items():
            data = dict(raw)
            parts = data.get("components") if kind == "package_configs" else [data]
            for part in parts or []:
                part["panel"] = restore_panel(part.get("panel_key") or part.get("panel"), settings)
                part.pop("panel_key", None)
            if kind == "package_configs":
                data["components"] = parts
            binding = normalize_binding(data, settings.panels)
            store.set_setting("binding:" + str(advert_id), binding)
            counts["bindings"] += 1
    # Old multi-key dedup records map back to one real purchase.
    for key in snapshot.get("processed_orders", []):
        key = str(key)
        if key.startswith("itemsatis_payload:"):
            fingerprint = key.split(":", 1)[1]
            if not fingerprint:
                raise ValueError("Eski bildirim koruma anahtarı boş.")
            _, created = store.create(empty_order("legacy_payload:" + fingerprint))
            counts["history"] += int(created)
            continue
        if key.startswith(("order:", "itemsatis_order:")):
            itemsatis_id = key.split(":", 1)[1]
        elif key.startswith("itemsatis_advert_order:"):
            itemsatis_id = key.split(":", 2)[-1]
        else:
            continue
        _, created = store.create(empty_order("itemsatis:" + itemsatis_id, itemsatis_id))
        counts["history"] += int(created)
    for item in snapshot.get("pending_orders", []):
        smm_id = str(item.get("smm_order_id") or "")
        if not smm_id:
            raise ValueError("Eski bekleyen siparişte SMM kimliği eksik; önce kaydı kontrol edin.")
        itemsatis_id = str(item.get("itemsatis_order_id") or item.get("order_id") or "")
        known_id = itemsatis_id and itemsatis_id != "Bilinmiyor"
        source = "itemsatis:" + itemsatis_id if known_id else "legacy_smm:" + str(item.get("panel")) + ":" + smm_id
        key = restore_panel(item.get("panel_key") or item.get("panel"), settings)
        platform = str(item.get("platform") or "other")
        link = str(item.get("link") or "")
        if not link:
            raise ValueError("Eski aktif siparişte link eksik; geçiş tamamlanmadı.")
        previous = store.by_source(source)
        base = empty_order(source, itemsatis_id if known_id else "", str(item.get("advert_id") or ""),
                           int(float(item.get("created_at") or time.time()) * 1_000_000))
        base.update(state="submitted", link=link, target=target_key(link, platform),
                    product_name=str(item.get("product_name") or ""), links={platform: link})
        if previous and previous["state"] != "legacy":
            base = previous
        part = {"panel": key, "service_id": str(item.get("service_id") or ""),
                "quantity": item.get("quantity") or 0, "platform": platform, "link": link,
                "state": "finished" if item.get("cancelled") else "submitted",
                "smm_id": smm_id, "status": "Canceled" if item.get("cancelled") else ""}
        if not any(p["panel"] == key and p.get("smm_id") == smm_id for p in base["parts"]):
            base["parts"].append(part)
        if all(p["state"] == "finished" for p in base["parts"]):
            base["state"] = "finished"
        elif any(p["state"] == "submitted" for p in base["parts"]):
            base["state"] = "submitted"
        if previous and previous["state"] != "legacy":
            store.save(base)
        else:
            base = merge_order(store, base)
        if any(p["state"] == "submitted" for p in base["parts"]):
            store.acquire_target(base["target"], base["id"])
        counts["active"] += 1
    for item in snapshot.get("failed_orders", []):
        itemsatis_id = str(item.get("order_id") or "")
        source = ("itemsatis:" + itemsatis_id if itemsatis_id and itemsatis_id != "Bilinmiyor"
                  else "legacy_failed:" + hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest())
        order = empty_order(source, "" if itemsatis_id == "Bilinmiyor" else itemsatis_id, str(item.get("advert_id") or ""),
                            int(float(item.get("created_at") or time.time()) * 1_000_000))
        reason = str(item.get("reason") or "").lower()
        detail = str(item.get("detail") or "").lower()
        uncertain = (item.get("manual_check_required") or item.get("uncertain_panel_response")
                     or "panel sipariş hatası" in reason or "order id" in reason
                     or "timeout" in detail or "connectionerror" in detail)
        order.update(state="uncertain" if uncertain else "review",
                     product_name=str(item.get("product_name") or ""),
                     link=str(item.get("link") or ""),
                     error="Eski gönderilemeyen sipariş: " + str(item.get("reason") or "")[:200])
        if order["link"]:
            order["links"] = {"other": order["link"]}
            order["target"] = target_key(order["link"], str(item.get("platform") or ""))
        imported = merge_order(store, order)
        if imported["state"] == "uncertain" and imported["target"]:
            store.acquire_target(imported["target"], imported["id"])
        counts["review"] += 1
    for name in ("queue", "processing", "dead"):
        for raw in snapshot.get(name, []):
            item = json.loads(raw) if isinstance(raw, str) else raw
            payload = item.get("payload", item)
            if not isinstance(payload, dict):
                raise ValueError("Eski kuyruk verisi okunamadı; kaynak silinmedi.")
            source = source_key(payload)
            order = empty_order(source, get_order_id(payload), get_advert_id(payload),
                                int(float(item.get("created_at") or time.time()) * 1_000_000))
            order.update(product_name=get_product_name(payload), links=extract_links(payload),
                         state="uncertain" if name == "processing" else "review",
                         error="Eski " + name + " kaydı. Kontrol et; otomatik gönderilmeyecek.")
            merge_order(store, order)
            counts["review"] += 1
    store.set_setting("migration_complete", True)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="PostgreSQL'e aktar; aksi halde yalnızca oku ve say.")
    parser.add_argument("--old-service-stopped", action="store_true", help="Eski sipariş işleyicisinin durduğu doğrulandı.")
    args = parser.parse_args()
    if args.apply and not args.old_service_stopped:
        parser.error("Eski servisi durdurduktan sonra --old-service-stopped kullanın.")
    try:
        snapshot = read_snapshot()
        if not args.apply:
            print(json.dumps({k: len(v) for k, v in snapshot.items()}, ensure_ascii=False))
            print("Ön inceleme tamamlandı. Hiçbir kaynak kayıt değiştirilmedi.")
        else:
            settings = Settings()
            print(json.dumps(import_snapshot(Store(settings.database_url), settings, snapshot), ensure_ascii=False))
            print("Geçiş tamamlandı. Gönderimler duraklatıldı; eşleştirmeleri doğrulayıp admin panelinden etkinleştirin.")
    except Exception as exc:
        print("Geçiş tamamlanamadı (" + type(exc).__name__ + "). Kaynak Upstash kayıtları silinmedi.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
