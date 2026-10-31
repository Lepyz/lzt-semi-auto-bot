"""Boostera: receive durably, submit once, hold duplicates for manual approval."""
import asyncio
import copy
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.config import Settings
from bot.engine import Engine, MANUAL_STATES, normalize_binding
from bot.migration import MigrationJob
from bot.notifications import Notifier, callbacks_allowed, register_telegram_webhook, telegram_api
from bot.panels import PanelClient
from bot.store import Conflict, Store
from bot.presentation import order_view, panel_label, summary as order_summary

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class HideQuery(logging.Filter):
    """The Itemsatis webhook key travels in the query string; keep it out of logs."""

    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            record.args = record.args[:2] + (record.args[2].split("?", 1)[0],) + record.args[3:]
        return True


logging.getLogger("uvicorn.access").addFilter(HideQuery())
security = HTTPBasic()
TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent / "bot" / "templates"),
                        autoescape=select_autoescape())
LABELS = {"queued": "Alındı", "processing": "Hazırlanıyor", "sending": "Gönderiliyor",
          "submitted": "Panele iletildi", "waiting": "Aktif siparişi bekliyor",
          "ready": "Senin göndermeni bekliyor", "review": "Bilgileri kontrol et",
          "error": "Gönderilemedi", "uncertain": "Panelden kontrol et", "paused": "Duraklatıldı",
          "finished": "Sonuçlandı", "legacy": "Eski işlenmiş sipariş", "closed": "Gönderilmeden kapatıldı"}
TEMPLATES.filters["date"] = lambda ts: datetime.fromtimestamp(
    ts / 1_000_000, timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
TEMPLATES.filters["panel_status"] = panel_label
TEMPLATES.filters["order_view"] = order_view
TEMPLATES.filters["clock"] = lambda ts: datetime.fromtimestamp(
    ts, timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M") if ts else "Henüz kontrol edilmedi"


def create_app(settings=None, store=None, panels=None, start_background=True):
    settings = settings or Settings()

    def load_saved_secrets(database):
        # Keys created from the admin panel; Render Environment values take precedence.
        if not settings.webhook_secret:
            settings.webhook_secret = database.setting("itemsatis_webhook_secret", "")
            settings.webhook_enforced = bool(settings.webhook_secret and
                                             database.setting("itemsatis_webhook_enforced", False))
        if not settings.telegram_secret:
            settings.telegram_secret = database.setting("telegram_webhook_secret", "")

    @asynccontextmanager
    async def lifespan(app):
        database = store or Store(settings.database_url)
        await asyncio.to_thread(database.initialize)
        await asyncio.to_thread(load_saved_secrets, database)
        notifier = Notifier(database, settings)
        engine = Engine(database, panels or PanelClient(settings.panels), notifier, settings)
        app.state.store, app.state.engine, app.state.notifier = database, engine, notifier
        app.state.migration = MigrationJob(database, settings)
        app.state.ready = True
        if start_background:
            notifier.start()
            engine.start()
        try:
            yield
        finally:
            app.state.ready = False
            await asyncio.to_thread(engine.close)
            await asyncio.to_thread(notifier.close)

    app = FastAPI(title="Boostera", version="3.1.1", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)

    def admin(credentials: HTTPBasicCredentials = Depends(security)):
        if not settings.password or settings.password == "changeme":
            raise HTTPException(503, "Render Environment içinde ADMIN_PASSWORD ayarlayın.")
        if not (secrets.compare_digest(credentials.username.encode(), settings.username.encode()) and
                secrets.compare_digest(credentials.password.encode(), settings.password.encode())):
            raise HTTPException(401, "Giriş bilgileri hatalı.", headers={"WWW-Authenticate": "Basic"})

    def signature(nonce):
        return hmac.new(settings.password.encode(), nonce.encode(), hashlib.sha256).hexdigest()

    def valid_csrf(value):
        nonce, _, sig = str(value or "").partition(".")
        return bool(nonce and sig and secrets.compare_digest(signature(nonce), sig))

    async def mutation(request: Request, _=Depends(admin)):
        form = await request.form()
        cookie = request.cookies.get("csrf", "")
        token = str(form.get("csrf", ""))
        if not valid_csrf(token) or not secrets.compare_digest(cookie, token):
            raise HTTPException(403, "İşlem anahtarı geçersiz; sayfayı yenileyin.")
        if app.state.migration.status()["state"] == "running":
            raise HTTPException(409, "Geçiş işlemi sürüyor. Tamamlanmasını bekleyin.")

    def page(request, template, **values):
        token = request.cookies.get("csrf", "")
        if not valid_csrf(token):
            nonce = secrets.token_urlsafe(24)
            token = nonce + "." + signature(nonce)
        html = TEMPLATES.get_template(template).render(
            csrf=token, labels=LABELS, panels=settings.panels, manual_states=MANUAL_STATES,
            message=request.query_params.get("message", ""),
            active_minutes=settings.active_check_interval // 60, blocked_minutes=settings.check_interval // 60, **values)
        response = HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                              "X-Content-Type-Options": "nosniff",
                                              "Referrer-Policy": "same-origin"})
        # Render terminates TLS at its proxy; the app itself sees plain HTTP.
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie("csrf", token, httponly=True, samesite="strict", secure=https)
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        if request.url.path.startswith("/admin/orders/"):
            response = page(request, "order_error.html", error=str(exc),
                            back="/admin/orders/" + request.url.path.split("/")[3])
            response.status_code = 400
            return response
        return HTMLResponse("İşlem yapılamadı: " + __import__("html").escape(str(exc)), status_code=400)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        if request.url.path.startswith("/admin/orders/"):
            response = page(request, "order_error.html", error=str(exc),
                            back="/admin/orders/" + request.url.path.split("/")[3])
            response.status_code = 409
            return response
        return HTMLResponse(__import__("html").escape(str(exc)), status_code=409)

    @app.api_route("/health", methods=["GET", "HEAD"])
    @app.api_route("/test", methods=["GET", "HEAD"])
    @app.api_route("/check-orders", methods=["GET", "HEAD"])
    @app.api_route("/check-services", methods=["GET", "HEAD"])
    @app.api_route("/check-balances", methods=["GET", "HEAD"])
    @app.api_route("/check-panel-health", methods=["GET", "HEAD"])
    def health():
        # Uptime checks must never query a database, panel or Telegram.
        return {"ok": bool(getattr(app.state, "ready", False)), "version": "3.1.1"}

    @app.post("/itemsatis-webhook")
    async def webhook(request: Request):
        supplied = request.headers.get("X-Webhook-Secret", "") or request.query_params.get("key", "")
        authenticated = bool(settings.webhook_secret) and secrets.compare_digest(
            supplied.encode(), settings.webhook_secret.encode())
        if settings.webhook_enforced and not authenticated:
            raise HTTPException(401, "Webhook yetkisi doğrulanamadı.")
        if settings.webhook_ips:
            allowed = {ip.strip() for ip in settings.webhook_ips.split(",") if ip.strip()}
            if not request.client or request.client.host not in allowed:
                raise HTTPException(401, "Webhook IP adresi doğrulanamadı.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                raise HTTPException(413, "Webhook çok büyük.")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            from urllib.parse import parse_qs
            try:
                form = parse_qs(body.decode("utf-8"), max_num_fields=100)
                data = {k: v[-1] for k, v in form.items()}
                if not data:
                    raise ValueError()
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, "Webhook JSON veya form verisi olmalı.")
        if not isinstance(data, dict):
            raise HTTPException(400, "Webhook nesne olmalı.")
        try:
            order, created = await asyncio.to_thread(app.state.engine.receive, data)
        except Exception as exc:
            logger.error("webhook_not_saved type=%s", type(exc).__name__)
            raise HTTPException(503, "Sipariş kaydedilemedi; yeniden gönderilmesi gerekiyor.")
        if authenticated and not settings.webhook_enforced and not getattr(app.state, "key_seen", False):
            # One write during the switch-over: proves Itemsatis uses the new address.
            try:
                await asyncio.to_thread(app.state.store.set_setting, "itemsatis_webhook_seen",
                                        int(datetime.now(timezone.utc).timestamp()))
                app.state.key_seen = True
            except Exception as exc:
                logger.error("webhook_key_seen_not_saved type=%s", type(exc).__name__)
        return {"ok": True, "status": "ignored" if order is None else ("saved" if created else "already_saved"),
                "id": order["id"] if order else None}

    @app.get("/", dependencies=[Depends(admin)])
    @app.get("/admin", dependencies=[Depends(admin)])
    def dashboard(request: Request, state: str = "", q: str = "", view: str = ""):
        sections = {"inbox": {"ready", "review", "error", "uncertain", "paused"},
                    "active": {"submitted", "processing", "sending", "queued"},
                    "waiting": {"waiting", "ready", "paused"}, "finished": {"finished", "closed"},
                    "all": set(LABELS) - {"legacy"}}
        view = view if view in sections else "all" if q or state else "inbox"
        rows = app.state.store.orders(states={state} if state in LABELS else sections[view],
                                      search=q, limit=500, newest=True, exclude_unmapped=view == "inbox")
        rows = [dict(o, display=order_view(o)) for o in rows]
        if view == "inbox":
            priority = {"ready": 0, "uncertain": 1, "error": 2, "review": 3, "paused": 4}
            rows.sort(key=lambda o: (bool(o.get("handling")), priority.get(o["state"], 5), o["created_at"]))
        counts = app.state.store.state_counts()
        totals = {key: sum(counts.get(state, 0) for state in states) for key, states in sections.items()}
        return page(request, "orders.html", orders=rows, selected=state, query=q, section=view, totals=totals,
                    paused=app.state.store.setting("paused", False))

    @app.get("/admin/orders/{order_id}", dependencies=[Depends(admin)])
    def detail(request: Request, order_id: str):
        order = app.state.store.get(order_id)
        if not order:
            raise HTTPException(404, "Sipariş bulunamadı.")
        related = app.state.store.orders(target=order["target"], limit=50, newest=True) if order.get("target") else []
        owner_id = app.state.store.owner(order["target"]) if order.get("target") else None
        owner = app.state.store.get(owner_id) if owner_id and owner_id != order_id else None
        preview, preview_error = None, ""
        if request.query_params.get("preview") == "1":
            try:
                if order["state"] not in MANUAL_STATES:
                    raise ValueError("Bu kayıt şu an gönderime uygun değil.")
                if any(p["state"] in {"submitted", "sending", "uncertain"} for p in order["parts"]):
                    raise ValueError("Önce paneldeki aktif veya belirsiz bileşenleri kontrol edin.")
                prepared = copy.deepcopy(order)
                app.state.engine.prepare(prepared)
                preview = prepared
            except ValueError as exc:
                preview_error = str(exc)
        homes = {}
        for key, panel in settings.panels.items():
            url = urlsplit(panel.get("api_url", ""))
            if url.scheme == "https" and url.hostname:
                homes[key] = "https://" + url.hostname
        checks = app.state.engine.check_results.get(order_id, {"at": order.get("last_checked", 0), "ok": True})
        return page(request, "detail.html", order=order, display=order_view(order), related=related,
                    owner=owner, preview=preview, preview_error=preview_error, checks=checks, panel_homes=homes)

    @app.post("/admin/orders/{order_id}/send", dependencies=[Depends(mutation)])
    def send(order_id: str, revision: int = Form(...), confirmed: str = Form("")):
        if confirmed != "yes":
            raise ValueError("Gönderim özetindeki ürün, adet ve hedefi kontrol edip onaylayın.")
        app.state.engine.approve(order_id, revision)
        return RedirectResponse("/admin/orders/" + order_id + "?" + urlencode({"message": "Gönderim isteği alındı. Aktif hedef kontrolü tekrar yapılacak."}), 303)

    @app.post("/admin/orders/{order_id}/attention", dependencies=[Depends(mutation)])
    def attention(order_id: str, revision: int = Form(...), handling: str = Form("yes")):
        order = app.state.store.get(order_id)
        if not order or order["revision"] != revision:
            raise Conflict("Kayıt değişti; sayfayı yenileyin.")
        order["handling"] = handling == "yes"
        app.state.store.save(order)
        return RedirectResponse("/admin/orders/" + order_id, 303)

    @app.post("/admin/orders/{order_id}/repair", dependencies=[Depends(mutation)])
    def repair(order_id: str, link: str = Form(...), revision: int = Form(...)):
        app.state.engine.repair(order_id, link, revision)
        return RedirectResponse("/admin/orders/" + order_id + "?" + urlencode({"message": "Bilgiler kaydedildi. Henüz sipariş gönderilmedi; gönderim özetinden devam edebilirsin."}), 303)

    @app.post("/admin/orders/{order_id}/refresh", dependencies=[Depends(mutation)])
    def refresh(order_id: str):
        app.state.engine.refresh(order_id)
        return RedirectResponse("/admin/orders/" + order_id, 303)

    @app.post("/admin/orders/{order_id}/close", dependencies=[Depends(mutation)])
    def close_order(order_id: str, revision: int = Form(...), confirmed: str = Form(...)):
        if confirmed != "yes":
            raise ValueError("Kapatma işlemini doğrulayın.")
        app.state.engine.close_unsubmitted(order_id, revision)
        return RedirectResponse("/admin/orders/" + order_id + "?" + urlencode({"message": "Kayıt takipten çıkarıldı. Bu işlem panelde iptal veya iade yapmaz."}), 303)

    @app.post("/admin/orders/{order_id}/reconcile", dependencies=[Depends(mutation)])
    def reconcile(order_id: str, index: int = Form(...), revision: int = Form(...),
                  smm_id: str = Form(""), absent: str = Form("")):
        app.state.engine.reconcile(order_id, index, smm_id.strip(), absent == "yes", revision)
        return RedirectResponse("/admin/orders/" + order_id + "?" + urlencode({"message": "Panel kontrolü sonucu kaydedildi. Bu işlem yeni sipariş oluşturmadı."}), 303)

    @app.post("/admin/pause", dependencies=[Depends(mutation)])
    def pause(paused: str = Form(...)):
        if paused == "false" and settings.require_import and not app.state.store.setting("migration_complete", False):
            raise ValueError("Önce eski Upstash kayıtlarının geçişini tamamlayın.")
        app.state.store.set_setting("paused", paused == "true")
        return RedirectResponse("/admin", 303)

    @app.get("/admin/migration", dependencies=[Depends(admin)])
    def migration_page(request: Request):
        return page(request, "migration.html", job=app.state.migration.status(),
                    configured=app.state.migration.configured(),
                    paused=app.state.store.setting("paused", True),
                    complete=app.state.store.setting("migration_complete", False),
                    inspected=app.state.migration.inspected)

    @app.get("/api/migration-status", dependencies=[Depends(admin)])
    def migration_status():
        return app.state.migration.status()  # RAM only: UI progress adds no SQL/Redis queries.

    @app.post("/admin/migration", dependencies=[Depends(mutation)])
    def run_migration(mode: str = Form(...), confirmed: str = Form("")):
        app.state.migration.start(mode, confirmed == "yes")
        return RedirectResponse("/admin/migration", 303)

    @app.get("/admin/services", dependencies=[Depends(admin)])
    @app.get("/admin/packages", dependencies=[Depends(admin)])
    def services(request: Request):
        bindings = app.state.store.bindings()
        return page(request, "services.html", bindings=bindings,
                    versions={key: binding_version(value) for key, value in bindings.items()},
                    saved=request.query_params.get("saved", ""))

    @app.get("/admin/assets/services.js", dependencies=[Depends(admin)])
    def services_script():
        return Response((Path(__file__).parent / "static" / "services.js").read_text(encoding="utf-8"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/admin/assets/orders.js", dependencies=[Depends(admin)])
    def orders_script():
        return Response((Path(__file__).parent / "static" / "orders.js").read_text(encoding="utf-8"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    def binding_version(binding):
        return hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @app.post("/admin/services", dependencies=[Depends(mutation)])
    def save_service(advert_id: str = Form(...), name: str = Form(""),
                     panel: str = Form(""), service_id: str = Form(""), quantity: int = Form(0),
                     platform: str = Form("instagram"), components: str = Form(""),
                     active: str = Form("true"), mode: str = Form(""), version: str = Form("")):
        advert_id = advert_id.strip()
        if not advert_id.isdigit() or int(advert_id) <= 0:
            raise ValueError("Geçerli bir ilan numarası girin; yalnızca rakam kullanın.")
        if mode not in {"", "create", "edit"} or active not in {"true", "false"}:
            raise ValueError("Eşleştirme işlemi veya durumu geçersiz.")
        data = {"name": name, "active": active == "true"}
        if components.strip():
            try:
                data["components"] = json.loads(components)
            except ValueError:
                raise ValueError("Paket servisleri okunamadı; formu kontrol edin.") from None
        else:
            data.update(panel=panel, service_id=service_id, quantity=quantity, platform=platform)
        binding = normalize_binding(data, settings.panels)
        store = app.state.store
        if not mode:  # Existing clients keep their upsert behavior.
            store.set_setting("binding:" + advert_id, binding)
        else:
            key, value = "binding:" + advert_id, json.dumps(binding, ensure_ascii=False)
            with store.transaction() as conn:
                if mode == "create":
                    cursor = store.execute(conn, """INSERT INTO settings(key,value) VALUES (?,?)
                        ON CONFLICT(key) DO NOTHING""", (key, value))
                    if cursor.rowcount != 1:
                        raise Conflict("Bu ilan zaten eşleştirilmiş. Mevcut ilan kartından Düzenle'yi seçin.")
                else:
                    current = store.execute(conn, "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                    if not current or not secrets.compare_digest(
                            binding_version(json.loads(current["value"])).encode(), version.encode()):
                        raise Conflict("Eşleştirme başka bir ekranda değişmiş veya kaldırılmış. Sayfayı yenileyin.")
                    cursor = store.execute(conn, "UPDATE settings SET value=? WHERE key=? AND value=?",
                                           (value, key, current["value"]))
                    if cursor.rowcount != 1:
                        raise Conflict("Eşleştirme değişti; sayfayı yenileyip tekrar deneyin.")
        if mode:
            return RedirectResponse("/admin/services?saved=" + advert_id, 303)
        return RedirectResponse("/admin/services", 303)

    @app.post("/admin/services/delete", dependencies=[Depends(mutation)])
    def delete_service(advert_id: str = Form(...)):
        app.state.store.delete_binding(advert_id)
        return RedirectResponse("/admin/services", 303)

    @app.get("/admin/integrations", dependencies=[Depends(admin)])
    def integrations(request: Request):
        key = settings.webhook_secret
        return page(request, "integrations.html",
                    webhook_url=settings.public_url + "/itemsatis-webhook" + ("?key=" + key if key else ""),
                    key_from_env=bool(os.getenv("ITEMSATIS_WEBHOOK_SECRET")), has_key=bool(key),
                    enforced=settings.webhook_enforced,
                    seen=app.state.store.setting("itemsatis_webhook_seen") if key else None,
                    telegram=dict(token=bool(settings.bot_token), chat=bool(settings.chat_id),
                                  group=settings.chat_id.startswith("-"),
                                  admins=bool(settings.telegram_admins.strip()),
                                  secret=bool(settings.telegram_secret),
                                  secret_from_env=bool(os.getenv("TELEGRAM_WEBHOOK_SECRET")),
                                  buttons=callbacks_allowed(settings), public=settings.public_url),
                    ip_list=bool(settings.webhook_ips))

    def back(message):
        return RedirectResponse("/admin/integrations?" + urlencode({"message": message}), 303)

    @app.post("/admin/integrations/itemsatis", dependencies=[Depends(mutation)])
    def itemsatis_key(action: str = Form(...), confirmed: str = Form("")):
        store = app.state.store
        if os.getenv("ITEMSATIS_WEBHOOK_SECRET"):
            raise ValueError("Anahtar Render Environment içinde tanımlı; oradan yönetin.")
        if action == "create":
            if settings.webhook_enforced:
                raise ValueError("Anahtar zorunluyken yenisi oluşturulamaz; önce zorunluluğu kaldırın.")
            if confirmed != "yes" and settings.webhook_secret:
                raise ValueError("Yeni anahtar eski adresi geçersiz kılar; işlemi doğrulayın.")
            store.set_setting("itemsatis_webhook_seen", None)
            store.set_setting("itemsatis_webhook_secret", secrets.token_urlsafe(32))
            settings.webhook_secret = store.setting("itemsatis_webhook_secret")
            app.state.key_seen = False
            return back("Anahtar oluşturuldu. Aşağıdaki adresi Itemsatış webhook ayarına kaydet.")
        if action == "enforce":
            if not settings.webhook_secret or not store.setting("itemsatis_webhook_seen"):
                raise ValueError("Itemsatış'tan henüz anahtarlı bildirim gelmedi; adres güncellenmeden "
                                 "zorunlu yapmak siparişlerin reddedilmesine yol açar.")
            store.set_setting("itemsatis_webhook_enforced", True)
            settings.webhook_enforced = True
            return back("Artık yalnızca anahtarlı Itemsatış bildirimleri kabul ediliyor.")
        if action == "relax":
            store.set_setting("itemsatis_webhook_enforced", False)
            settings.webhook_enforced = False
            return back("Anahtarsız bildirimler yeniden kabul ediliyor.")
        raise ValueError("İşlem tanınmadı.")

    @app.post("/admin/integrations/telegram", dependencies=[Depends(mutation)])
    def telegram_setup(action: str = Form(...)):
        if action == "register":
            secret = settings.telegram_secret
            if not secret:
                secret = secrets.token_urlsafe(32)
                # Saved before Telegram learns it, so no update can arrive unverifiable.
                app.state.store.set_setting("telegram_webhook_secret", secret)
            register_telegram_webhook(settings, secret)
            settings.telegram_secret = secret
        elif action != "check":
            raise ValueError("İşlem tanınmadı.")
        info = telegram_api(settings, "getWebhookInfo") or {}
        expected = settings.public_url + "/telegram-webhook"
        parts = ["Telegram webhook: " + ("bu uygulamaya bağlı" if info.get("url") == expected
                                         else ("başka adrese bağlı: " + info["url"] if info.get("url")
                                               else "kayıtlı değil"))]
        parts.append("Bekleyen güncelleme: " + str(info.get("pending_update_count", 0)))
        if info.get("last_error_message"):
            when = datetime.fromtimestamp(info.get("last_error_date", 0), timezone(timedelta(hours=3)))
            parts.append("Son hata (" + when.strftime("%d.%m.%Y %H:%M") + "): " + str(info["last_error_message"])[:200])
        return back(" · ".join(parts))

    @app.get("/api/orders", dependencies=[Depends(admin)])
    def api_orders(state: str = "", q: str = ""):
        return {"orders": app.state.store.orders(states={state} if state else set(LABELS) - {"legacy"},
                                                 search=q, limit=500, newest=True)}

    @app.get("/admin/export", dependencies=[Depends(admin)])
    def export():
        result = io.StringIO()
        writer = csv.writer(result, delimiter=";")
        writer.writerow(["Itemsatış sipariş numarası", "İlan", "Ürün", "Link", "Durum", "Panel", "Panel sipariş numarası", "Adet"])
        def safe(value):
            text = str(value or "")
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
        for order in app.state.store.orders(states=set(LABELS) - {"legacy"}, limit=100000):
            for part in order["parts"] or [{}]:
                writer.writerow([safe(v) for v in (
                    order["itemsatis_id"], order["advert_id"], order["product_name"], order["link"],
                    order_view(order)["title"], part.get("panel", ""),
                    part.get("smm_id", ""), part.get("quantity", ""))])
        return Response("\ufeff" + result.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="siparisler.csv"'})

    @app.post("/telegram-webhook")
    async def telegram(request: Request):
        if not settings.telegram_secret or not secrets.compare_digest(
                request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), settings.telegram_secret):
            raise HTTPException(401, "Telegram webhook yetkisi doğrulanamadı.")
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "Telegram verisi okunamadı.")
        if not isinstance(data, dict):
            raise HTTPException(400, "Telegram verisi okunamadı.")
        callback = data.get("callback_query") or {}
        message = callback.get("message") or data.get("message") or {}
        chat = str(message.get("chat", {}).get("id", ""))
        sender = str((callback.get("from") or message.get("from") or {}).get("id", ""))
        allowed = {v.strip() for v in settings.telegram_admins.split(",") if v.strip()}
        if not allowed and not settings.chat_id.startswith("-"):
            allowed = {settings.chat_id}
        if chat != settings.chat_id or sender not in allowed:
            return {"ok": True, "ignored": True}
        text = "Yönetim paneli: " + (settings.public_url + "/admin" if settings.public_url else "Render adresiniz /admin")
        if callback:
            action = str(callback.get("data", ""))
            if action.startswith("send:"):
                text = "Bu düğme eski sürüme ait. Siparişi web panelinde açıp Gönderimi incele düğmesinden devam et. Henüz sipariş gönderilmedi."
            # Stop Telegram's button spinner through the independent notifier.
            notice = {"key": "callback:" + str(callback.get("id")), "text": text,
                      "callback_id": str(callback.get("id")), "order_id": "", "action": False}
        else:
            raw = str(message.get("text", "")).strip()
            command = raw.split(" ")[0].split("@")[0]
            command = {"/pending": "/bekleyen", "/failed": "/sorunlar", "/status": "/durum",
                       "📋 Bekleyenler": "/bekleyen", "⚠️ Sorunlar": "/sorunlar",
                       "🟢 Bot durumu": "/durum", "🔎 Sipariş ara": "/ara"}.get(raw,
                       {"/pending": "/bekleyen", "/failed": "/sorunlar", "/status": "/durum"}.get(command, command))
            if command == "/durum":
                paused = await asyncio.to_thread(app.state.store.setting, "paused", False)
                text = ("⏸️ Yeni otomatik gönderimler duraklatıldı." if paused else "🟢 Yeni otomatik gönderimler açık.")
                text += "\nBekletilmiş siparişler sen göndermeden başlamaz.\n\n" + text_link(settings.public_url)
            elif command in {"/bekleyen", "/sorunlar", "/ara"}:
                query = raw.partition(" ")[2].strip() if command == "/ara" and raw.startswith("/") else ""
                if command == "/ara" and len(query) < 2:
                    text = "🔎 /ara komutundan sonra kayıt numarası, panel sipariş numarası veya hedef linki yaz.\nÖrnek: /ara 123456"
                else:
                    states = {"waiting", "ready", "paused"} if command == "/bekleyen" else {"error", "review", "uncertain"} if command == "/sorunlar" else set(LABELS) - {"legacy"}
                    orders = await asyncio.to_thread(app.state.store.orders, states=states, search=query,
                                                    limit=10, newest=True, exclude_unmapped=command == "/sorunlar")
                    text = "\n\n".join(order_view(o)["icon"] + " " + order_view(o)["title"] + "\n" + order_summary(o) for o in orders) or "Bu aramada kayıt yok."
                    text += "\n\n" + text_link(settings.public_url)
            else:
                text = "👋 Sipariş yönetimi\n\n📋 /bekleyen — Bekletilen ve hazır siparişler\n⚠️ /sorunlar — Kontrol gereken kayıtlar\n🟢 /durum — Otomatik gönderim durumu\n🔎 /ara kayıt-no — Sipariş ara\n\n" + text_link(settings.public_url)
            notice = {"key": "telegram:" + str(data.get("update_id")), "text": text[:3500],
                      "order_id": "", "action": False, "menu": command in {"/start", "/yardim"}}
        notice["ephemeral"] = True
        app.state.notifier.enqueue(notice)
        return {"ok": True}

    return app


def text_link(public_url):
    return "Web paneli: " + public_url + "/admin?view=inbox" if public_url else "Siparişlerini web panelindeki İşlem bekleyenler ekranından yönetebilirsin."


app = create_app()
