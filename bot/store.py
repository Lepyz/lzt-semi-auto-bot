"""PostgreSQL in production, file SQLite for local tests.

No background polling, broad state snapshots, balance history or message logs.
Each order update uses optimistic concurrency. Target locks survive restarts.
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse


class Conflict(Exception):
    pass


class Store:
    def __init__(self, url):
        if not url:
            raise ValueError("DATABASE_URL gerekli. Render'da kalıcı PostgreSQL kullanın.")
        self.url = url
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        if not self.postgres and not url.startswith("sqlite:///"):
            raise ValueError("DATABASE_URL PostgreSQL veya sqlite:/// ile başlamalı.")
        if not self.postgres:
            if os.getenv("RENDER"):
                raise ValueError("Render'da geçici SQLite kullanılamaz; DATABASE_URL PostgreSQL olmalı.")
            self.path = url.removeprefix("sqlite:///")
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def transaction(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            options = {"connect_timeout": 15, "row_factory": dict_row}
            from urllib.parse import parse_qs
            sslmode = parse_qs(urlparse(self.url).query).get("sslmode", [""])[0]
            if (urlparse(self.url).hostname not in {"localhost", "127.0.0.1", "::1"}
                    and sslmode not in {"require", "verify-ca", "verify-full"}):
                options["sslmode"] = "require"
            conn = psycopg.connect(self.url, **options)
        else:
            conn = sqlite3.connect(self.path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, conn, sql, params=()):
        if not self.postgres:
            return conn.execute(sql, params)
        # psycopg parses '%' placeholders whenever params is not None, even ().
        return conn.execute(sql.replace("?", "%s"), params or None)

    def initialize(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL,
                state TEXT NOT NULL, target TEXT NOT NULL, created_at BIGINT NOT NULL,
                revision INTEGER NOT NULL, document TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS orders_state ON orders(state)",
            "CREATE INDEX IF NOT EXISTS orders_target ON orders(target, created_at)",
            "CREATE TABLE IF NOT EXISTS target_locks (target TEXT PRIMARY KEY, owner TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            """CREATE TABLE IF NOT EXISTS notifications (
                key TEXT PRIMARY KEY, document TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)""",
        ]
        with self.transaction() as conn:
            if not self.postgres:
                conn.execute("PRAGMA journal_mode=WAL")
            for sql in statements:
                self.execute(conn, sql)
            self.execute(conn, """INSERT INTO settings(key,value) VALUES ('paused','true')
                ON CONFLICT(key) DO NOTHING""")

    @staticmethod
    def decode(row):
        if not row:
            return None
        doc = json.loads(row["document"])
        doc["revision"] = row["revision"]
        return doc

    def get(self, order_id):
        with self.transaction() as conn:
            return self.decode(self.execute(conn, "SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())

    def by_source(self, source):
        with self.transaction() as conn:
            return self.decode(self.execute(conn, "SELECT * FROM orders WHERE source_key=?", (source,)).fetchone())

    def create(self, order):
        with self.transaction() as conn:
            row = self.execute(conn, """INSERT INTO orders
                (id,source_key,state,target,created_at,revision,document)
                VALUES (?,?,?,?,?,0,?) ON CONFLICT(source_key) DO NOTHING RETURNING id""",
                (order["id"], order["source_key"], order["state"], order.get("target", ""),
                 order["created_at"], json.dumps(order, ensure_ascii=False))).fetchone()
            current = self.decode(self.execute(conn, "SELECT * FROM orders WHERE source_key=?",
                                              (order["source_key"],)).fetchone())
            return current, bool(row)

    def save(self, order, notification=None):
        """Persist transition and its one-off notification in the same transaction."""
        revision = order["revision"]
        document = dict(order, updated_at=int(time.time() * 1_000_000), revision=revision + 1)
        notified = False
        with self.transaction() as conn:
            cursor = self.execute(conn, """UPDATE orders SET state=?,target=?,revision=?,document=?
                WHERE id=? AND revision=?""",
                (document["state"], document.get("target", ""), revision + 1,
                 json.dumps(document, ensure_ascii=False), order["id"], revision))
            if cursor.rowcount != 1:
                raise Conflict("Sipariş başka bir işlem tarafından güncellendi; sayfayı yenileyin.")
            if notification:
                notified = self._notification(conn, notification)
        order.update(document)
        return notified

    def _notification(self, conn, notification):
        cursor = self.execute(conn, """INSERT INTO notifications(key,document,state)
            VALUES (?,?,'pending') ON CONFLICT(key) DO NOTHING""",
            (notification["key"], json.dumps(notification, ensure_ascii=False)))
        return cursor.rowcount == 1

    def notify(self, notification):
        with self.transaction() as conn:
            return self._notification(conn, notification)

    def pending_notifications(self):
        with self.transaction() as conn:
            return [json.loads(r["document"]) for r in self.execute(conn,
                    "SELECT document FROM notifications WHERE state='pending'").fetchall()]

    def recover_notifications(self):
        # A timeout/restart may have happened after Telegram accepted a message.
        # Do not automatically repeat these ambiguous deliveries.
        with self.transaction() as conn:
            self.execute(conn, "UPDATE notifications SET state='failed' WHERE state='sending'")

    def notification(self, key):
        with self.transaction() as conn:
            row = self.execute(conn, "SELECT * FROM notifications WHERE key=?", (key,)).fetchone()
            return dict(row) if row else None

    def claim_notification(self, key):
        with self.transaction() as conn:
            return self.execute(conn, """UPDATE notifications SET state='sending',attempts=attempts+1
                WHERE key=? AND state='pending' AND attempts<3""", (key,)).rowcount == 1

    def finish_notification(self, key, success):
        with self.transaction() as conn:
            self.execute(conn, """UPDATE notifications SET state=?
                WHERE key=?""", ("sent" if success else "failed", key))
            # Keep only undelivered entries; a sent marker needs no message text.
            if success:
                self.execute(conn, "UPDATE notifications SET document='{}' WHERE key=?", (key,))

    def retry_notification(self, key):
        with self.transaction() as conn:
            self.execute(conn, """UPDATE notifications SET state='pending'
                WHERE key=? AND state='failed' AND attempts<3""", (key,))

    def orders(self, states=None, target=None, limit=200, search="", newest=False, exclude_unmapped=False):
        sql, params = "SELECT * FROM orders WHERE 1=1", []
        if states:
            sql += " AND state IN (" + ",".join("?" for _ in states) + ")"
            params.extend(states)
        if target is not None:
            sql += " AND target=?"
            params.append(target)
        if exclude_unmapped:
            sql += " AND document NOT LIKE ? AND document NOT LIKE ?"
            params.extend(('%"reason_code": "binding_missing"%', '%İlanın aktif servis eşleştirmesi yok.%'))
        if search:
            sql += " AND LOWER(document) LIKE ? ESCAPE '!'"
            escaped = search.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            params.append("%" + escaped + "%")
        sql += " ORDER BY created_at " + ("DESC" if newest else "ASC") + ",id LIMIT ?"
        params.append(limit)
        with self.transaction() as conn:
            return [self.decode(r) for r in self.execute(conn, sql, tuple(params)).fetchall()]

    def state_counts(self):
        with self.transaction() as conn:
            rows = self.execute(conn, """SELECT state,COUNT(*) AS count FROM orders WHERE state<>'legacy'
                AND document NOT LIKE ? AND document NOT LIKE ? GROUP BY state""",
                ('%"reason_code": "binding_missing"%', '%İlanın aktif servis eşleştirmesi yok.%')).fetchall()
            return {r["state"]: r["count"] for r in rows}

    def acquire_target(self, target, owner):
        with self.transaction() as conn:
            self.execute(conn, """INSERT INTO target_locks(target,owner) VALUES (?,?)
                ON CONFLICT(target) DO NOTHING""", (target, owner))
            return self.execute(conn, "SELECT owner FROM target_locks WHERE target=?", (target,)).fetchone()["owner"]

    def owner(self, target):
        with self.transaction() as conn:
            row = self.execute(conn, "SELECT owner FROM target_locks WHERE target=?", (target,)).fetchone()
            return row["owner"] if row else None

    def release_target(self, target, owner):
        with self.transaction() as conn:
            self.execute(conn, "DELETE FROM target_locks WHERE target=? AND owner=?", (target, owner))

    def setting(self, key, default=None):
        with self.transaction() as conn:
            row = self.execute(conn, "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        with self.transaction() as conn:
            self.execute(conn, """INSERT INTO settings(key,value) VALUES (?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, json.dumps(value, ensure_ascii=False)))

    def bindings(self):
        with self.transaction() as conn:
            rows = self.execute(conn, "SELECT key,value FROM settings WHERE key LIKE ? ORDER BY LENGTH(key),key",
                                ("binding:%",)).fetchall()
            return {r["key"][8:]: json.loads(r["value"]) for r in rows}

    def delete_binding(self, advert_id):
        with self.transaction() as conn:
            self.execute(conn, "DELETE FROM settings WHERE key=?", ("binding:" + advert_id,))
