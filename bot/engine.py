import collections
import copy
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .config import panel_key
from .payloads import classify, customer_links, extract_links, get_advert_id, get_event, get_order_id, get_product_name
from .links import PLATFORMS, link_issue, looks_like_username, target_type
from .payloads import get_sale_price, ignored_summary, legacy_payload_key, normalize_panel_link, parse_price, source_key, target_key, valid_link
from .store import Conflict
from .history import IN_FLIGHT, STALLED_AFTER, is_stalled, phase_since, stalled_notice
from .profit import CODES as PROFIT_CODES, evaluate, guard_settings, reprice
from .presentation import alert, panel_label, reason_code, summary

logger = logging.getLogger(__name__)
MANUAL_STATES = {"waiting", "ready", "paused", "review", "error"}
# Render starts the new instance while the previous one is still finishing its
# work, so unfinished claims are only recovered once they are certainly stale.
RECOVERY_DELAY = 120
STALE_SECONDS = 120


class Hold(ValueError):
    """A reason to keep an order for the admin, with its code set at the source."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalize_binding(data, panels):
    parts = data.get("components") if "components" in data else [data]
    if not isinstance(parts, list) or not parts:
        raise ValueError("En az bir servis gerekli.")
    result = []
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError("Servis bilgisi okunamadı.")
        if not part.get("active", True):
            continue
        platform = str(part.get("platform") or data.get("platform") or "instagram").lower()
        kind = part.get("target_type", "auto")
        if platform not in {*PLATFORMS, "other"} or kind not in {"auto", "profile", "content"}:
            raise ValueError("Platform veya hedef link türü geçersiz.")
        key = panel_key(part.get("panel_key") or part.get("panel"))
        service = str(part.get("service_id", "")).strip()
        try:
            quantity = int(part.get("quantity", 0))
        except (ValueError, TypeError):
            quantity = 0
        if key not in panels or not service.isdigit() or not 0 < quantity <= 1_000_000:
            raise ValueError("Panel, servis kimliği veya adet geçersiz.")
        result.append({"panel": key, "service_id": service, "quantity": quantity,
                       "platform": platform,
                       "name": str(part.get("name", ""))[:150]})
        if kind != "auto":
            result[-1]["target_type"] = kind
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
        self.active_checks = {}
        self.check_results = {}
        self.recent_checks = {}
        self.running = set()
        self.dispatch_checks = {}
        # Memory only: recent ignored webhooks, so a changed purchase format is noticed.
        self.ignored = collections.deque(maxlen=20)
        self.ignored_total = 0
        self.recover_at = None
        self.monitor = None

    def notice(self, order, event, text, action=False):
        # The revision makes each transition notify once, including a re-entry
        # into the same state after the admin's own action.
        return {"key": order["id"] + ":" + event + ":" + str(order.get("revision", 0)),
                "text": text[:3500], "order_id": order["id"], "action": action}

    def save(self, order, event="", text="", action=False, code=None):
        order["reason_code"] = code or (reason_code(order.get("error"), order["state"]) if order.get("error") else "")
        notification = alert(order, event) if event else None
        notified = self.store.save(order, notification)
        if notified:
            self.notifier.enqueue(notification)

    def summary(self, order):
        return summary(order)

    def receive(self, payload):
        kind = classify(payload)
        if kind == "ignore":
            self.ignored.appendleft(dict(ignored_summary(payload), at=time.time()))
            self.ignored_total += 1
            return None, False
        legacy_key = legacy_payload_key(payload)
        legacy = self.store.by_source(legacy_key)
        if legacy:
            return legacy, False
        now = int(time.time() * 1_000_000)
        price, price_source = get_sale_price(payload)
        order = {"id": uuid.uuid4().hex, "source_key": source_key(payload),
                 "legacy_source_key": legacy_key,
                 "itemsatis_id": get_order_id(payload), "advert_id": get_advert_id(payload),
                 "product_name": get_product_name(payload)[:200], "links": extract_links(payload),
                 "customer_inputs": customer_links(payload), "receipt_kind": kind,
                 "receipt_event": get_event(payload)[:80],
                 "sale_price": price, "price_source": price_source,
                 "price_version": 2,
                 "link": "", "target": "", "parts": [], "state": "queued" if kind == "order" else "review",
                 "manual_required": kind != "order", "error": "", "created_at": now, "updated_at": now}
        if kind != "order":
            order["error"] = "Sipariş bilgisi eksik veya webhook türü tanınmadı. Kontrol edip gönderin."
            order["reason_code"] = "review"
            if not order["advert_id"]:
                order.update(error="Satın alma alındı ancak ilan numarası okunamadı.", reason_code="advert_missing")
        saved, created = self.store.create(order)
        if created:
            if saved["state"] == "queued":
                self.schedule_dispatch(saved)
                self.enqueue(saved["id"])
            else:
                binding = self.store.setting("binding:" + saved["advert_id"]) if saved["advert_id"] else None
                if not saved["advert_id"] or binding and binding.get("active", True):
                    notification = alert(saved, "review")
                    if notification and self.store.notify(notification):
                        self.notifier.enqueue(notification)
        return saved, created

    def enqueue(self, order_id):
        if not self.stop_event.is_set():
            with self.guard:
                self.dispatch_checks.setdefault(order_id, time.monotonic() + STALLED_AFTER)
            self.pool.submit(self._run, order_id)

    def schedule_dispatch(self, order, grace=0):
        with self.guard:
            if order["state"] in IN_FLIGHT:
                remaining = STALLED_AFTER - (time.time() * 1_000_000 - phase_since(order)) / 1_000_000
                self.dispatch_checks[order["id"]] = time.monotonic() + max(grace, remaining, 0)
            else:
                self.dispatch_checks.pop(order["id"], None)

    def check_stalled(self):
        with self.guard:
            due = [key for key, when in self.dispatch_checks.items() if when <= time.monotonic()][:10]
        for order_id in due:
            try:
                order = self.store.get(order_id)
                if not order or order["state"] not in IN_FLIGHT:
                    with self.guard:
                        self.dispatch_checks.pop(order_id, None)
                    continue
                now = int(time.time() * 1_000_000)
                if not is_stalled(order, now):
                    self.schedule_dispatch(order)
                    continue
                notification = stalled_notice(order, now)
                result = self.store.notify_stalled(notification)
                with self.guard:
                    if result == "changed":
                        self.dispatch_checks[order_id] = time.monotonic() + 60
                    else:
                        self.dispatch_checks.pop(order_id, None)
                if result == "queued":
                    self.notifier.enqueue(notification)
            except Exception as exc:
                logger.error("stalled_check_failed type=%s", type(exc).__name__)
                with self.guard:
                    self.dispatch_checks[order_id] = time.monotonic() + 60

    def _run(self, order_id):
        with self.guard:
            self.running.add(order_id)
        try:
            self._execute_once(order_id)
        finally:
            with self.guard:
                self.running.discard(order_id)
            try:
                current = self.store.get(order_id)
                if not current or current["state"] not in IN_FLIGHT:
                    with self.guard:
                        self.dispatch_checks.pop(order_id, None)
            except Exception:
                pass  # The scheduled check remains if the final state couldn't be read.

    def _execute_once(self, order_id):
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

    @staticmethod
    def username_hold(inputs, platform):
        """The buyer typed only a username: hold it as 'link bulunamadı', never complete it."""
        if inputs and not any(valid_link(v, platform) for v in inputs) and any(looks_like_username(v) for v in inputs):
            shown = next(v for v in inputs if looks_like_username(v))[:60]
            raise Hold("link_username", f"Link bulunamadı: müşteri link yerine kullanıcı adı yazmış ({shown}). "
                                        "Müşteriden tam linki alıp düzelt.")

    def prepare(self, order):
        if order["parts"]:
            for part in order["parts"]:
                if part["state"] in {"new", "error"}:
                    # Older records may hold a link completed from a username.
                    self.username_hold(order.get("customer_inputs", []), part["platform"])
                    issue = link_issue(part["link"], part["platform"], target_type(part, order.get("product_name", "")))
                    if issue:
                        raise Hold(issue, "Müşteri linki gönderime uygun değil; hedefi kontrol edin.")
                    part["link"] = normalize_panel_link(part["link"], part["platform"])
            if all(p["state"] in {"new", "error"} for p in order["parts"]):
                targets = {target_key(p["link"], p["platform"]) for p in order["parts"]}
                if len(targets) != 1:
                    raise Hold("package_target", "Paket bileşenlerinin aynı hedef linki kullanması gerekiyor.")
                order.update(target=targets.pop(), link=normalize_panel_link(order["parts"][0]["link"], order["parts"][0]["platform"]))
            return
        binding = self.store.setting("binding:" + order["advert_id"])
        if not binding or not binding.get("active", True):
            raise Hold("binding_missing", "İlanın aktif servis eşleştirmesi yok. Eşleştirmeyi ekleyip gönderin.")
        binding = normalize_binding(binding, self.settings.panels)
        if not order["product_name"]:
            order["product_name"] = binding["name"]
        parts = copy.deepcopy(binding["components"])
        for part in parts:
            link = order["links"].get(part["platform"]) or order.get("link") or ""
            inputs = order.get("customer_inputs", [])
            matches = {target_key(v, part["platform"]): v for v in inputs if valid_link(v, part["platform"])}
            if len(matches) > 1:
                raise Hold("link_ambiguous", "Birden fazla hedef linki var; doğru hedefi seçip kaydedin.")
            if not link and len(inputs) == 1:
                link = inputs[0]
            if not link:
                self.username_hold(inputs, part["platform"])
            issue = link_issue(link, part["platform"], target_type(part, binding["name"]))
            if issue == "link_username":
                self.username_hold([link], part["platform"])
            if issue:
                raise Hold(issue, "Müşteri linki eksik, belirsiz veya servis hedefiyle uyumsuz.")
            part.update(link=normalize_panel_link(link, part["platform"]), state="new", smm_id="", status="")
        targets = {target_key(p["link"], p["platform"]) for p in parts}
        if len(targets) != 1:
            raise Hold("package_target", "Paket bileşenlerinin aynı hedef linki kullanması gerekiyor.")
        order.update(parts=parts, link=parts[0]["link"], target=targets.pop())

    def earlier_hold(self, order):
        candidates = self.store.orders(states=MANUAL_STATES | {"uncertain", "queued", "processing"},
                                       target=order["target"], limit=10000)
        candidates += self.store.alias_orders(order["target"], MANUAL_STATES | {"uncertain", "queued", "processing"})
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
        for candidate in self.store.alias_orders(target, {"submitted", "error", "processing", "sending", "uncertain"}):
            if candidate["state"] == "uncertain" or any(p["state"] in {"submitted", "sending", "uncertain"} for p in candidate["parts"]):
                return candidate["id"]
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
            self.save(order, "review", "Sipariş gönderilemedi.\n" + self.summary(order) + "\n" + str(exc),
                      code=getattr(exc, "code", None))
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
                if time.time() - owner.get("last_checked", owner["created_at"] / 1_000_000) > 90:
                    self.refresh(owner_id, force=False)
            if self.active_owner(order["target"]):
                self.wait(order, "Aynı linkte aktif veya sonucu belirsiz bir sipariş var.")
                return
        earlier = self.earlier_hold(order)
        if earlier:
            self.wait(order, "Bu linkte daha önce alınmış, senin işlemini bekleyen sipariş var.", monitor=False)
            return
        # Loss guard: checked with current panel prices before anything is sent.
        override = order.pop("profit_override", False)
        guard = guard_settings(self.store)
        if guard["mode"] != "off":
            check = evaluate(order, self.panels, guard)
            order["profit"] = check
            if guard["mode"] == "enforce" and not check["ok"] and not override:
                order.update(state="review", manual_required=True, error=check["message"])
                self.save(order, "profit", code=check["code"])
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
        self.schedule_active(order)
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
        checked = False
        successes = 0
        attempted = sum(p["state"] == "submitted" for p in order["parts"])
        previous_state = order["state"]
        for part in order["parts"]:
            if part["state"] != "submitted":
                continue
            result = self.panels.status(part)
            if not result:
                continue
            checked = True
            successes += 1
            if part.get("status") != result["status"]:
                part["status"] = result["status"]
                changed = True
            if result["terminal"]:
                part["state"] = "finished"
                changed = True
        if checked and successes == attempted:
            self.check_results[order_id] = {"at": time.time(), "ok": True}
            if order.pop("status_error", ""):
                changed = True
            if order.pop("status_failures", 0):
                changed = True
        elif attempted:
            self.check_results[order_id] = {"at": time.time(), "ok": False}
            # Stored on the order (a write only on failure) so a restart doesn't reset it.
            order["status_failures"] = min(order.get("status_failures", 0) + 1, 3)
            if order["status_failures"] < 3:
                self.store.save(order)
            elif not order.get("status_error"):
                order["status_error"] = "Panelden güncel durum alınamadı. Son doğrulanmış durum gösteriliyor."
                problem = dict(order, state="error", reason_code="status_unavailable", manual_approved=False,
                               alert_panel=next((p["panel"] for p in order["parts"] if p["state"] == "submitted"), ""))
                notification = alert(problem, "status_error")
                notified = self.store.save(order, notification)
                if notified:
                    self.notifier.enqueue(notification)
        active = any(p["state"] in {"submitted", "sending", "uncertain"} for p in order["parts"])
        if order["parts"] and not active:
            notification = None
            if all(p["state"] == "finished" for p in order["parts"]):
                changed = changed or order["state"] != "finished"
                order["state"] = "finished"
                if previous_state != "finished":
                    notification = alert(order, "outcome")
            if changed:
                order["last_checked"] = time.time() if checked else order.get("last_checked", 0)
                self.store.save(order, notification)  # Durable outcome + alert before releasing the target.
            ready = None
            try:
                self.store.release_target(order["target"], order["id"])
                ready = self.make_ready(order["target"], order)
            finally:
                if notification:
                    if ready:
                        # The ready alert already contains the previous result: keep one message.
                        self.store.finish_notification(notification["key"], True)
                    else:
                        self.notifier.enqueue(notification)
        elif changed:
            order["last_checked"] = time.time() if checked else order.get("last_checked", 0)
            self.store.save(order)
        self.schedule_active(order)
        return order

    def make_ready(self, target, previous=None):
        """Only a notice. This method NEVER enqueues or submits a waiting order."""
        waiting = self.store.orders(states={"waiting"}, target=target, limit=10000)
        for order in waiting:
            if self.active_owner(target) or self.earlier_hold(order):
                continue
            order.update(state="ready", manual_required=True, error="")
            statuses = ", ".join(panel_label(p.get("status", "")) for p in (previous or {}).get("parts", []) if p.get("status"))
            order["previous_result"] = statuses
            self.save(order, "ready", "Bekletilen siparişi artık kontrol edip gönderebilirsin.\n" +
                      self.summary(order) + ("\nÖnceki sipariş durumu: " + statuses if statuses else ""),
                      action=True)
            return order  # FIFO: only the first waiting purchase becomes ready.
        return None

    def approve(self, order_id, revision=None, profit_override=False):
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
        guard = guard_settings(self.store)
        if guard["mode"] == "enforce" and not profit_override:
            prepared = copy.deepcopy(order)
            try:
                self.prepare(prepared)
            except ValueError:
                prepared = None  # execute() reports the missing data as usual.
            if prepared is not None:
                check = evaluate(prepared, self.panels, guard)
                if not check["ok"]:
                    raise ValueError(check["message"] + " Göndermek için gönderim özetindeki kâr onayını işaretle.")
        # The override covers this one send only; execute() consumes it.
        order.update(state="queued", manual_required=True, manual_approved=True, error="", reason_code="",
                     profit_override=bool(profit_override))
        self.store.save(order)
        self.schedule_dispatch(order)
        self.enqueue(order_id)

    def repair(self, order_id, link, revision, advert_id=""):
        order = self.store.get(order_id)
        if not order or order["state"] not in MANUAL_STATES or order["revision"] != revision:
            raise Conflict("Sipariş değişti veya düzenlemeye uygun değil.")
        if any(p["state"] in {"submitted", "finished", "sending", "uncertain"} for p in order["parts"]):
            raise ValueError("Panele iletilen paket bileşenleri yeniden yazılamaz.")
        if advert_id:
            if order.get("advert_id") or not advert_id.isdigit() or int(advert_id) <= 0:
                raise ValueError("Eksik ilan numarası için geçerli bir ilan seçin.")
            order["advert_id"] = advert_id
        order.update(parts=[], link=link.strip(), customer_inputs=[link.strip()], links={p: link.strip() for p in (*order["links"], "other")},
                     state="review", manual_required=True, error="", reason_code="")
        # Include all known platforms so a newly added binding can use the corrected link.
        from .payloads import PLATFORMS
        order["links"].update({p: link.strip() for p in PLATFORMS})
        self.prepare(order)
        order["state"] = "review"
        self.store.save(order)

    def close_unsubmitted(self, order_id, revision):
        self.cleanup([(order_id, revision)], "close")

    def update_sale_price(self, order_id, value, revision):
        order = self.store.get(order_id)
        if not order or order["revision"] != revision or order["state"] in {"legacy", "deleted"}:
            raise Conflict("Kayıt değişti veya fiyat düzeltmeye uygun değil; sayfayı yenileyin.")
        price = parse_price(value)
        if price is None:
            raise ValueError("Itemsatış'taki geçerli satış tutarını TL olarak girin.")
        order.update(sale_price=price, price_source="manual", price_version=2)
        order["profit"] = reprice(order, guard_settings(self.store))
        if order.get("reason_code") in PROFIT_CODES:
            order.update(reason_code=order["profit"]["code"], error=order["profit"]["message"])
        self.store.save(order)  # Pure bookkeeping: no enqueue, panel request or Telegram alert.

    def cleanup(self, selections, action):
        targets = self.store.cleanup_orders(selections, action)
        for target in targets:
            self.make_ready(target)

    def reconcile(self, order_id, index, smm_id="", confirmed_absent=False, revision=None):
        order = self.store.get(order_id)
        if (order and revision == order["revision"] and index == -1 and not order["parts"]
                and order["state"] == "uncertain" and confirmed_absent):
            order.update(state="review", manual_required=True, reason_code="review",
                         error="Panelde açılmadığı yönetici tarafından doğrulandı.")
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
        order.update(error="", reason_code="", manual_required=True)
        self.store.save(order)
        self.schedule_active(order)
        if any(p["state"] == "submitted" for p in order["parts"]) and self.store.orders(states={"waiting"}, target=order["target"], limit=1):
            with self.guard:
                self.watch.setdefault(order["target"], time.monotonic() + self.settings.check_interval)
        if not any(p["state"] in {"submitted", "uncertain", "sending"} for p in order["parts"]):
            self.store.release_target(order["target"], order["id"])
            self.make_ready(order["target"], order)

    def schedule_active(self, order):
        with self.guard:
            if any(p["state"] == "submitted" for p in order["parts"]):
                self.active_checks[order["id"]] = time.monotonic() + self.settings.active_check_interval
            else:
                self.active_checks.pop(order["id"], None)
                # Settled orders need no in-memory check history.
                self.recent_checks.pop(order["id"], None)
                self.check_results.pop(order["id"], None)

    def check_due(self):
        # Memory-only scheduling: no database queries when nothing is due.
        self.check_stalled()
        with self.guard:
            active_due = [key for key, when in self.active_checks.items() if when <= time.monotonic()][:10]
        for key in active_due:
            try:
                self.refresh(key, force=False)
                with self.guard:
                    if key in self.active_checks:
                        self.active_checks[key] = time.monotonic() + self.settings.active_check_interval
            except Exception as exc:
                logger.error("active_check_failed type=%s", type(exc).__name__)
                with self.guard:
                    self.active_checks[key] = time.monotonic() + self.settings.active_check_interval
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
                if not self.active_owner(target):
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
        # One Uvicorn worker is required. Queued claims are compare-and-swap, so
        # dispatching them while the previous instance drains is safe.
        for order in self.store.orders(states={"queued"}, limit=100000):
            self.schedule_dispatch(order, grace=RECOVERY_DELAY)
            self.enqueue(order["id"])
        for order in self.store.orders(states={"processing", "sending"}, limit=100000):
            self.schedule_dispatch(order, grace=RECOVERY_DELAY)
        for order in self.store.orders(states={"waiting"}, limit=100000):
            self.watch.setdefault(order["target"], time.monotonic() + self.settings.check_interval)
        for order in self.store.orders(states={"submitted", "error"}, limit=100000):
            self.schedule_active(order)
        self.recover_at = time.monotonic() + RECOVERY_DELAY
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()

    def recover(self):
        """One-off cleanup after a restart. Never repeats an add with an unknown result.

        Returns True when every unfinished claim was stale and has been handled.
        """
        cutoff = (time.time() - STALE_SECONDS) * 1_000_000
        complete = True
        for order in self.store.orders(states={"processing", "sending"}, limit=100000):
            with self.guard:
                if order["id"] in self.running:
                    continue
            if order.get("updated_at", order["created_at"]) > cutoff:
                complete = False  # Possibly still owned by the previous instance.
                continue
            try:
                if any(p["state"] == "sending" for p in order["parts"]):
                    for part in order["parts"]:
                        if part["state"] == "sending":
                            part["state"] = "uncertain"
                    order.update(state="uncertain", manual_required=True,
                                 error="Yeniden başlatma sırasında panel cevabı alınamadı. "
                                       "Panelden kontrol edin; otomatik tekrar yapılmadı.")
                    self.save(order, "recovery", "Yarım kalan siparişi panelden kontrol edin.\n" +
                              self.summary(order))
                else:
                    # The 'sending' state is committed before every add call, so
                    # this claim never reached a panel and can be dispatched again.
                    order.update(state="queued", error="")
                    self.store.save(order)
            except Conflict:
                continue
        # Receipts saved by the previous instance after this one started.
        for order in self.store.orders(states={"queued"}, limit=100000):
            self.enqueue(order["id"])
        for item in self.store.pending_notifications():
            self.notifier.enqueue(item)
        for order in self.store.orders(states={"submitted", "error"}, limit=100000):
            with self.guard:
                if order["id"] not in self.active_checks:
                    self.schedule_active(order)
        return complete

    def _monitor(self):
        while not self.stop_event.wait(10):
            if self.recover_at is not None and time.monotonic() >= self.recover_at:
                self.recover_at = None
                try:
                    if not self.recover():
                        self.recover_at = time.monotonic() + STALE_SECONDS
                except Exception as exc:
                    logger.error("recovery_failed type=%s", type(exc).__name__)
                    self.recover_at = time.monotonic() + RECOVERY_DELAY
            self.check_due()  # No SQL at all when self.watch is empty.

    def close(self):
        self.stop_event.set()
        if self.monitor:
            self.monitor.join(timeout=2)
        self.pool.shutdown(wait=True, cancel_futures=True)
