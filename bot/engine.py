import copy
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .config import panel_key
from .payloads import classify, extract_links, get_advert_id, get_order_id, get_product_name
from .payloads import legacy_payload_key, normalize_panel_link, source_key, target_key, valid_link
from .store import Conflict

logger = logging.getLogger(__name__)
MANUAL_STATES = {"waiting", "ready", "paused", "review", "error"}


def normalize_binding(data, panels):
    parts = data.get("components") if "components" in data else [data]
    if not isinstance(parts, list) or not parts:
        raise ValueError("En az bir servis gerekli.")
    result = []
    for part in parts:
        if not part.get("active", True):
            continue
        key = panel_key(part.get("panel_key") or part.get("panel"))
        service = str(part.get("service_id", "")).strip()
        try:
            quantity = int(part.get("quantity", 0))
        except (ValueError, TypeError):
            quantity = 0
        if key not in panels or not service.isdigit() or not 0 < quantity <= 1_000_000:
            raise ValueError("Panel, servis kimliği veya adet geçersiz.")
        result.append({"panel": key, "service_id": service, "quantity": quantity,
                       "platform": str(part.get("platform") or data.get("platform") or "instagram").lower(),
                       "name": str(part.get("name", ""))[:150]})
    if not result:
        raise ValueError("Aktif servis bulunamadı.")
    return {"name": str(data.get("name", ""))[:200], "active": bool(data.get("active", True)),
            "components": result}


class Engine:
    def __init__(self, store, panels, notifier, settings):
        self.store, self.panels, self.notifier, self.settings = store, panels, notifier, settings
        self.pool = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="order")
        self.guard = threading.RLock()
        self.stop_event = threading.Event()
        self.watch = {}
        self.recent_checks = {}
        self.monitor = None

    def notice(self, order, event, text, action=False):
        return {"key": order["id"] + ":" + event, "text": text[:3500],
                "order_id": order["id"], "action": action}

    def save(self, order, event="", text="", action=False):
        notification = self.notice(order, event, text, action) if event else None
        self.store.save(order, notification)
        if notification:
            self.notifier.enqueue(notification)

    def summary(self, order):
        return (f"Itemsatış: {order.get('itemsatis_id') or 'Bildirim kaydı ' + order['id'][:10]}\n"
                f"Ürün: {order.get('product_name') or order.get('advert_id')}\n"
                f"Link: {order.get('link') or '-'}")

    def receive(self, payload):
        kind = classify(payload)
        if kind == "ignore":
            return None, False
        legacy_key = legacy_payload_key(payload)
        legacy = self.store.by_source(legacy_key)
        if legacy:
            return legacy, False
        now = int(time.time() * 1_000_000)
        order = {"id": uuid.uuid4().hex, "source_key": source_key(payload),
                 "legacy_source_key": legacy_key,
                 "itemsatis_id": get_order_id(payload), "advert_id": get_advert_id(payload),
                 "product_name": get_product_name(payload)[:200], "links": extract_links(payload),
                 "link": "", "target": "", "parts": [], "state": "queued" if kind == "order" else "review",
                 "manual_required": kind != "order", "error": "", "created_at": now, "updated_at": now}
        if kind != "order":
            order["error"] = "Sipariş bilgisi eksik veya webhook türü tanınmadı. Kontrol edip gönderin."
        saved, created = self.store.create(order)
        if created:
            if saved["state"] == "queued":
                self.enqueue(saved["id"])
            else:
                n = self.notice(saved, "review", "Sipariş kontrol gerekiyor.\n" + self.summary(saved))
                self.store.notify(n)
                self.notifier.enqueue(n)
        return saved, created

    def enqueue(self, order_id):
        if not self.stop_event.is_set():
            self.pool.submit(self._run, order_id)

    def _run(self, order_id):
        try:
            self.execute(order_id)
        except Conflict:
            pass  # Another explicit action or worker already claimed this order.
        except Exception as exc:
            # Do not log request URLs/credentials or retry an external side effect.
            logger.error("order_processing_failed order=%s type=%s", order_id, type(exc).__name__)
            try:
                order = self.store.get(order_id)
                if order and order["state"] in {"processing", "sending"}:
                    for part in order["parts"]:
                        if part["state"] == "sending":
                            part["state"] = "uncertain"
                    order.update(state="uncertain" if any(p["state"] == "uncertain" for p in order["parts"]) else "review",
                                 manual_required=True, error="İşlem tamamlanamadı; panel ve sipariş kaydını kontrol edin.")
                    self.save(order, "processing_error", self.summary(order) + "\n" + order["error"])
            except Exception:
                pass  # Persisted claim is recovered conservatively on restart.

    def prepare(self, order):
        if order["parts"]:
            return
        binding = self.store.setting("binding:" + order["advert_id"])
        if not binding or not binding.get("active", True):
            raise ValueError("İlanın aktif servis eşleştirmesi yok. Eşleştirmeyi ekleyip gönderin.")
        binding = normalize_binding(binding, self.settings.panels)
        if not order["product_name"]:
            order["product_name"] = binding["name"]
        parts = copy.deepcopy(binding["components"])
        for part in parts:
            link = order["links"].get(part["platform"]) or order.get("link") or ""
            if not valid_link(link, part["platform"]):
                raise ValueError("Müşteri linki eksik veya servis platformuyla uyumsuz.")
            part.update(link=normalize_panel_link(link, part["platform"]), state="new", smm_id="", status="")
        targets = {target_key(p["link"], p["platform"]) for p in parts}
        if len(targets) != 1:
            raise ValueError("Paket bileşenlerinin aynı hedef linki kullanması gerekiyor.")
        order.update(parts=parts, link=parts[0]["link"], target=targets.pop())

    def earlier_hold(self, order):
        candidates = self.store.orders(states=MANUAL_STATES | {"uncertain", "queued", "processing"},
                                       target=order["target"], limit=10000)
        return next((o for o in candidates if o["id"] != order["id"] and
                     (o["created_at"], o["id"]) < (order["created_at"], order["id"])), None)

    def active_owner(self, target):
        owner = self.store.owner(target)
        if owner:
            return owner
        # Migration can contain several old active purchases for a single target.
        for candidate in self.store.orders(target=target, limit=100000):
            if any(p["state"] in {"submitted", "sending", "uncertain"} for p in candidate["parts"]):
                return self.store.acquire_target(target, candidate["id"])
        return None

    def wait(self, order, reason, monitor=True):
        order.update(state="waiting", manual_required=True, error=reason)
        self.save(order, "waiting", "Yeni sipariş bekletildi; otomatik gönderilmeyecek.\n" +
                  self.summary(order) + "\n" + reason)
        if monitor:
            with self.guard:
                self.watch.setdefault(order["target"], time.monotonic() + self.settings.check_interval)

    def execute(self, order_id):
        order = self.store.get(order_id)
        if not order or order["state"] != "queued":
            return
        order["state"] = "processing"
        self.store.save(order)  # Atomic compare-and-swap claim.
        if order.get("legacy_source_key") and self.store.by_source(order["legacy_source_key"]):
            order.update(state="closed", manual_required=True,
                         error="Bu bildirim eski sürümde işlenmiş; tekrar sipariş açılmadı.")
            self.store.save(order)
            return
        try:
            self.prepare(order)
        except ValueError as exc:
            order.update(state="review", manual_required=True, error=str(exc))
            self.save(order, "review", "Sipariş gönderilemedi.\n" + self.summary(order) + "\n" + str(exc))
            return
        if self.store.setting("paused", False):
            order.update(state="paused", manual_required=True, error="Yeni gönderimler duraklatıldı.")
            self.save(order, "paused", "Sipariş duraklatma nedeniyle tutuldu.\n" + self.summary(order))
            return
        owner_id = self.active_owner(order["target"])
        if owner_id and owner_id != order["id"]:
            owner = self.store.get(owner_id)
            if (owner and owner["state"] not in {"processing", "sending", "uncertain"}
                    and not any(p["state"] in {"submitted", "sending", "uncertain"} for p in owner["parts"])):
                self.store.release_target(order["target"], owner_id)
            if owner and any(p["state"] == "submitted" for p in owner["parts"]):
                # A just-created order is certainly active; do not immediately query it.
                if time.time() - owner.get("last_checked", owner["updated_at"] / 1_000_000) > 90:
                    self.refresh(owner_id, force=False)
            if self.active_owner(order["target"]):
                self.wait(order, "Aynı linkte aktif veya sonucu belirsiz bir sipariş var.")
                return
        earlier = self.earlier_hold(order)
        if earlier:
            self.wait(order, "Bu linkte daha önce alınmış, senin işlemini bekleyen sipariş var.", monitor=False)
            return
        lock_owner = self.store.acquire_target(order["target"], order["id"])
        if lock_owner != order["id"]:
            self.wait(order, "Aynı linkte başka bir sipariş işleniyor.")
            return
        # The target lock is acquired before any add call, and remains while active/uncertain.
        for part in order["parts"]:
            if part["state"] in {"submitted", "finished"}:
                continue
            if part["state"] in {"sending", "uncertain"}:
                order.update(state="uncertain", manual_required=True, error="Önce paneldeki belirsiz siparişi kontrol edin.")
                self.save(order, "uncertain", self.summary(order) + "\n" + order["error"])
                return
            if self.store.setting("paused", False):
                order.update(state="paused", manual_required=True, error="Gönderimler duraklatıldı.")
                self.save(order)
                if not any(p["state"] == "submitted" for p in order["parts"]):
                    self.store.release_target(order["target"], order["id"])
                return
            part["state"] = "sending"
            order["state"] = "sending"
            self.store.save(order)  # Commit BEFORE calling the external panel.
            result = self.panels.add(part, part["link"])
            part.update(state=result.state, smm_id=result.order_id, error=result.error)
            if result.state != "submitted":
                order.update(state=result.state, manual_required=True, error=result.error)
                self.save(order, "send_error:" + str(order["revision"]),
                          "Sipariş kontrol gerekiyor.\n" + self.summary(order) + "\n" + result.error)
                if result.state == "error" and not any(p["state"] == "submitted" for p in order["parts"]):
                    self.store.release_target(order["target"], order["id"])
                return
            self.store.save(order)
        order.update(state="submitted", error="")
        ids = ", ".join(p["panel"] + ":" + p["smm_id"] for p in order["parts"])
        self.save(order, "submitted", "Sipariş panele iletildi.\n" + self.summary(order) + "\nSMM: " + ids)
        if self.store.orders(states={"waiting"}, target=order["target"], limit=1):
            with self.guard:
                self.watch.setdefault(order["target"], time.monotonic() + self.settings.check_interval)

    def refresh(self, order_id, force=True):
        order = self.store.get(order_id)
        if not order:
            raise ValueError("Sipariş bulunamadı.")
        with self.guard:
            now = time.monotonic()
            if not force and now - self.recent_checks.get(order_id, -1000) < 90:
                return order
            self.recent_checks[order_id] = now
        changed = False
        for part in order["parts"]:
            if part["state"] != "submitted":
                continue
            result = self.panels.status(part)
            if not result:
                continue
            if part.get("status") != result["status"]:
                part["status"] = result["status"]
                changed = True
            if result["terminal"]:
                part["state"] = "finished"
                changed = True
        active = any(p["state"] in {"submitted", "sending", "uncertain"} for p in order["parts"])
        if order["parts"] and not active:
            if all(p["state"] == "finished" for p in order["parts"]):
                changed = changed or order["state"] != "finished"
                order["state"] = "finished"
            if changed:
                self.store.save(order)
            self.store.release_target(order["target"], order["id"])
            self.make_ready(order["target"], order)
        elif changed:
            self.store.save(order)
        return order

    def make_ready(self, target, previous=None):
        """Only a notice. This method NEVER enqueues or submits a waiting order."""
        waiting = self.store.orders(states={"waiting"}, target=target, limit=10000)
        for order in waiting:
            if self.active_owner(target) or self.earlier_hold(order):
                continue
            order.update(state="ready", manual_required=True, error="")
            statuses = ", ".join(p.get("status", "") for p in (previous or {}).get("parts", []) if p.get("status"))
            self.save(order, "ready", "Bekletilen siparişi artık kontrol edip gönderebilirsin.\n" +
                      self.summary(order) + ("\nÖnceki sipariş durumu: " + statuses if statuses else ""),
                      action=True)
            break  # FIFO: only the first waiting purchase becomes ready.

    def approve(self, order_id, revision=None):
        order = self.store.get(order_id)
        if not order or order["state"] not in MANUAL_STATES:
            raise ValueError("Bu sipariş gönderime uygun değil; mevcut durumu kontrol edin.")
        if revision is not None and order["revision"] != revision:
            raise Conflict("Sipariş değişti; sayfayı yenileyin.")
        if order.get("legacy_source_key") and self.store.by_source(order["legacy_source_key"]):
            raise ValueError("Bu bildirim eski sürümde işlenmiş; yeniden gönderilemez.")
        if self.store.setting("paused", False):
            raise ValueError("Önce yeni gönderimleri tekrar etkinleştirin.")
        if any(p["state"] in {"sending", "uncertain"} for p in order["parts"]):
            raise ValueError("Önce panelde belirsiz siparişi kontrol edin.")
        if any(p["state"] == "submitted" for p in order["parts"]):
            self.refresh(order_id)
            order = self.store.get(order_id)
            if any(p["state"] == "submitted" for p in order["parts"]):
                raise ValueError("Bu siparişin aktif paket bileşeni var; sonuçlanmasını bekleyin.")
        order.update(state="queued", manual_required=True, error="")
        self.store.save(order)
        self.enqueue(order_id)

    def repair(self, order_id, link, revision):
        order = self.store.get(order_id)
        if not order or order["state"] not in MANUAL_STATES or order["revision"] != revision:
            raise Conflict("Sipariş değişti veya düzenlemeye uygun değil.")
        if any(p["state"] in {"submitted", "finished", "sending", "uncertain"} for p in order["parts"]):
            raise ValueError("Panele iletilen paket bileşenleri yeniden yazılamaz.")
        order.update(parts=[], link=link.strip(), links={p: link.strip() for p in (*order["links"], "other")},
                     state="review", manual_required=True, error="")
        # Include all known platforms so a newly added binding can use the corrected link.
        from .payloads import PLATFORMS
        order["links"].update({p: link.strip() for p in PLATFORMS})
        self.prepare(order)
        order["state"] = "review"
        self.store.save(order)

    def close_unsubmitted(self, order_id, revision):
        order = self.store.get(order_id)
        if not order or order["revision"] != revision or order["state"] not in MANUAL_STATES:
            raise Conflict("Sipariş değişti veya kapatmaya uygun değil.")
        if any(p["state"] in {"submitted", "sending", "uncertain"} for p in order["parts"]):
            raise ValueError("Aktif veya belirsiz panel siparişi varken bu kayıt kapatılamaz.")
        order.update(state="closed", manual_required=True, error="Yönetici tarafından gönderilmeden kapatıldı.")
        self.store.save(order)
        if order["target"]:
            self.store.release_target(order["target"], order["id"])
            self.make_ready(order["target"], order)

    def reconcile(self, order_id, index, smm_id="", confirmed_absent=False, revision=None):
        order = self.store.get(order_id)
        if (order and revision == order["revision"] and index == -1 and not order["parts"]
                and order["state"] == "uncertain" and confirmed_absent):
            order.update(state="review", manual_required=True, error="Panelde açılmadığı yönetici tarafından doğrulandı.")
            self.store.save(order)
            if order["target"]:
                self.store.release_target(order["target"], order["id"])
            return
        if not order or revision != order["revision"] or not 0 <= index < len(order["parts"]):
            raise Conflict("Sipariş değişti; sayfayı yenileyin.")
        part = order["parts"][index]
        if part["state"] not in {"uncertain", "sending"}:
            raise ValueError("Bu bileşen belirsiz durumda değil.")
        if smm_id:
            if not smm_id.isdigit() or int(smm_id) <= 0:
                raise ValueError("Geçerli SMM sipariş kimliği gerekli.")
            part.update(state="submitted", smm_id=smm_id, error="")
        elif confirmed_absent:
            part.update(state="error", smm_id="", error="Panelde açılmadığı yönetici tarafından doğrulandı.")
        else:
            raise ValueError("Panel kimliğini girin veya açılmadığını açıkça doğrulayın.")
        if any(p["state"] in {"uncertain", "sending"} for p in order["parts"]):
            order["state"] = "uncertain"
        elif all(p["state"] in {"submitted", "finished"} for p in order["parts"]):
            order["state"] = "submitted"
        else:
            order["state"] = "error"
        order.update(error="", manual_required=True)
        self.store.save(order)
        if not any(p["state"] in {"submitted", "uncertain", "sending"} for p in order["parts"]):
            self.store.release_target(order["target"], order["id"])
            self.make_ready(order["target"], order)

    def check_due(self):
        with self.guard:
            due = [t for t, when in self.watch.items() if when <= time.monotonic()]
        for target in due:
            try:
                if not self.store.orders(states={"waiting"}, target=target, limit=1):
                    with self.guard:
                        self.watch.pop(target, None)
                    continue
                owner = self.active_owner(target)
                if owner:
                    self.refresh(owner, force=False)
                else:
                    self.make_ready(target)
                # Query only while an actual active order blocks another purchase.
                owner = self.active_owner(target)
                blocked = self.store.orders(states={"waiting"}, target=target, limit=1)
                owner_order = self.store.get(owner) if owner else None
                with self.guard:
                    if blocked and owner_order and any(p["state"] == "submitted" for p in owner_order["parts"]):
                        self.watch[target] = time.monotonic() + self.settings.check_interval
                    else:
                        self.watch.pop(target, None)
            except Exception as exc:
                logger.error("blocked_check_failed type=%s", type(exc).__name__)
                with self.guard:
                    self.watch[target] = time.monotonic() + self.settings.check_interval

    def start(self):
        # One Uvicorn worker is required. Recovery never repeats an unfinished add.
        for order in self.store.orders(states={"processing", "sending"}, limit=100000):
            for part in order["parts"]:
                if part["state"] == "sending":
                    part["state"] = "uncertain"
            order.update(state="uncertain" if any(p["state"] == "uncertain" for p in order["parts"]) else "review",
                         manual_required=True, error="Yeniden başlatma sırasında işlem yarım kaldı. Kontrol edin.")
            self.save(order, "recovery", "Yarım kalan siparişi kontrol edin.\n" + self.summary(order))
        for order in self.store.orders(states={"queued"}, limit=100000):
            self.enqueue(order["id"])
        for order in self.store.orders(states={"waiting"}, limit=100000):
            self.watch.setdefault(order["target"], time.monotonic() + self.settings.check_interval)
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()

    def _monitor(self):
        while not self.stop_event.wait(10):
            self.check_due()  # No SQL at all when self.watch is empty.

    def close(self):
        self.stop_event.set()
        if self.monitor:
            self.monitor.join(timeout=2)
        self.pool.shutdown(wait=True, cancel_futures=True)
