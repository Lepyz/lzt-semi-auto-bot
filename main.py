"""Boostera: receive durably, submit once, hold duplicates for manual approval."""
import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.config import Settings
from bot.engine import Engine, MANUAL_STATES, normalize_binding
from bot.migration import MigrationJob
from bot.notifications import Notifier
from bot.panels import PanelClient
from bot.store import Conflict, Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
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


def create_app(settings=None, store=None, panels=None, start_background=True):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        database = store or Store(settings.database_url)
        await asyncio.to_thread(database.initialize)
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

    app = FastAPI(title="Boostera", version="3.0.0", docs_url=None, redoc_url=None,
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
            message=request.query_params.get("message", ""), **values)
        response = HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                              "X-Content-Type-Options": "nosniff",
                                              "Referrer-Policy": "same-origin"})
        response.set_cookie("csrf", token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return HTMLResponse("İşlem yapılamadı: " + __import__("html").escape(str(exc)), status_code=400)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return HTMLResponse(__import__("html").escape(str(exc)), status_code=409)

    @app.api_route("/health", methods=["GET", "HEAD"])
    @app.api_route("/test", methods=["GET", "HEAD"])
    @app.api_route("/check-orders", methods=["GET", "HEAD"])
    @app.api_route("/check-services", methods=["GET", "HEAD"])
    @app.api_route("/check-balances", methods=["GET", "HEAD"])
    @app.api_route("/check-panel-health", methods=["GET", "HEAD"])
    def health():
        # Uptime checks must never query a database, panel or Telegram.
        return {"ok": bool(getattr(app.state, "ready", False)), "version": "3.0.0"}

    @app.post("/itemsatis-webhook")
    async def webhook(request: Request):
        if settings.webhook_secret and not secrets.compare_digest(
                request.headers.get("X-Webhook-Secret", ""), settings.webhook_secret):
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
        return {"ok": True, "status": "ignored" if order is None else ("saved" if created else "already_saved"),
                "id": order["id"] if order else None}

    @app.get("/", dependencies=[Depends(admin)])
    @app.get("/admin", dependencies=[Depends(admin)])
    def dashboard(request: Request, state: str = "", q: str = ""):
        rows = app.state.store.orders(states={state} if state else set(LABELS) - {"legacy"},
                                      search=q, limit=500, newest=True)
        return page(request, "orders.html", orders=rows, selected=state, query=q,
                    paused=app.state.store.setting("paused", False))

    @app.get("/admin/orders/{order_id}", dependencies=[Depends(admin)])
    def detail(request: Request, order_id: str):
        order = app.state.store.get(order_id)
        if not order:
            raise HTTPException(404, "Sipariş bulunamadı.")
        return page(request, "detail.html", order=order)

    @app.post("/admin/orders/{order_id}/send", dependencies=[Depends(mutation)])
    def send(order_id: str, revision: int = Form(...)):
        app.state.engine.approve(order_id, revision)
        return RedirectResponse("/admin/orders/" + order_id, 303)

    @app.post("/admin/orders/{order_id}/repair", dependencies=[Depends(mutation)])
    def repair(order_id: str, link: str = Form(...), revision: int = Form(...)):
        app.state.engine.repair(order_id, link, revision)
        return RedirectResponse("/admin/orders/" + order_id, 303)

    @app.post("/admin/orders/{order_id}/refresh", dependencies=[Depends(mutation)])
    def refresh(order_id: str):
        app.state.engine.refresh(order_id)
        return RedirectResponse("/admin/orders/" + order_id, 303)

    @app.post("/admin/orders/{order_id}/close", dependencies=[Depends(mutation)])
    def close_order(order_id: str, revision: int = Form(...), confirmed: str = Form(...)):
        if confirmed != "yes":
            raise ValueError("Kapatma işlemini doğrulayın.")
        app.state.engine.close_unsubmitted(order_id, revision)
        return RedirectResponse("/admin/orders/" + order_id, 303)

    @app.post("/admin/orders/{order_id}/reconcile", dependencies=[Depends(mutation)])
    def reconcile(order_id: str, index: int = Form(...), revision: int = Form(...),
                  smm_id: str = Form(""), absent: str = Form("")):
        app.state.engine.reconcile(order_id, index, smm_id.strip(), absent == "yes", revision)
        return RedirectResponse("/admin/orders/" + order_id, 303)

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
        return page(request, "services.html", bindings=app.state.store.bindings())

    @app.post("/admin/services", dependencies=[Depends(mutation)])
    def save_service(advert_id: str = Form(...), name: str = Form(""),
                     panel: str = Form(""), service_id: str = Form(""), quantity: int = Form(0),
                     platform: str = Form("instagram"), components: str = Form(""),
                     active: str = Form("true")):
        if not advert_id.isdigit():
            raise ValueError("İlan kimliği sadece rakam olmalı.")
        data = {"name": name, "active": active == "true"}
        if components.strip():
            data["components"] = json.loads(components)
        else:
            data.update(panel=panel, service_id=service_id, quantity=quantity, platform=platform)
        binding = normalize_binding(data, settings.panels)
        app.state.store.set_setting("binding:" + advert_id, binding)
        return RedirectResponse("/admin/services", 303)

    @app.post("/admin/services/delete", dependencies=[Depends(mutation)])
    def delete_service(advert_id: str = Form(...)):
        app.state.store.delete_binding(advert_id)
        return RedirectResponse("/admin/services", 303)

    @app.get("/api/orders", dependencies=[Depends(admin)])
    def api_orders(state: str = "", q: str = ""):
        return {"orders": app.state.store.orders(states={state} if state else set(LABELS) - {"legacy"},
                                                 search=q, limit=500, newest=True)}

    @app.get("/admin/export", dependencies=[Depends(admin)])
    def export():
        result = io.StringIO()
        writer = csv.writer(result, delimiter=";")
        writer.writerow(["Itemsatis ID", "İlan", "Ürün", "Link", "Durum", "Panel", "SMM ID", "Adet"])
        def safe(value):
            text = str(value or "")
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
        for order in app.state.store.orders(states=set(LABELS) - {"legacy"}, limit=100000):
            for part in order["parts"] or [{}]:
                writer.writerow([safe(v) for v in (
                    order["itemsatis_id"], order["advert_id"], order["product_name"], order["link"],
                    LABELS.get(order["state"], order["state"]), part.get("panel", ""),
                    part.get("smm_id", ""), part.get("quantity", ""))])
        return Response("\ufeff" + result.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="siparisler.csv"'})

    @app.post("/telegram-webhook")
    async def telegram(request: Request):
        if not settings.telegram_secret or not secrets.compare_digest(
                request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), settings.telegram_secret):
            raise HTTPException(401, "Telegram webhook yetkisi doğrulanamadı.")
        data = await request.json()
        callback = data.get("callback_query", {})
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
                try:
                    await asyncio.to_thread(app.state.engine.approve, action[5:])
                    text = "Gönderim isteği alındı. Aktif sipariş kontrolü tekrar yapılacak."
                except (ValueError, Conflict) as exc:
                    text = str(exc)
            # Stop Telegram's button spinner through the independent notifier.
            notice = {"key": "callback:" + str(callback.get("id")), "text": text,
                      "callback_id": str(callback.get("id")), "order_id": "", "action": False}
        else:
            command = str(message.get("text", "")).split("@")[0].split(" ")[0]
            if command in {"/pending", "/failed", "/status"}:
                states = {"waiting", "ready", "paused"} if command == "/pending" else {"error", "review", "uncertain"}
                if command == "/status":
                    text = "Bot çalışıyor. " + text
                else:
                    orders = await asyncio.to_thread(app.state.store.orders, states=states, limit=10)
                    text = "\n\n".join(LABELS[o["state"]] + "\n" + app.state.engine.summary(o) for o in orders) or "Kayıt yok."
            notice = {"key": "telegram:" + str(data.get("update_id")), "text": text[:3500],
                      "order_id": "", "action": False}
        notice["ephemeral"] = True
        app.state.notifier.enqueue(notice)
        return {"ok": True}

    return app


app = create_app()
