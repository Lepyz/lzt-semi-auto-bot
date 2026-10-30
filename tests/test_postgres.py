"""Runs against a dedicated disposable database in CI; never uses DATABASE_URL."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from bot.store import Conflict, Store
from scripts.migrate_upstash import empty_order

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Dedicated PostgreSQL test URL not provided")


@pytest.fixture
def database():
    store = Store(os.environ["TEST_DATABASE_URL"])
    assert store.postgres, "Integration tests require a dedicated PostgreSQL database"
    store.initialize()
    return store


def new_order():
    value = uuid.uuid4().hex
    return empty_order("postgres-test:" + value, value)


def test_concurrent_postgres_receipt_is_unique(database):
    order = new_order()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: database.create(dict(order)), range(16)))
    assert sum(created for _, created in results) == 1


def test_postgres_revision_conflict_rolls_back_notification(database):
    order, _ = database.create(new_order())
    stale = dict(order)
    order["state"] = "review"
    database.save(order)
    notice = {"key": order["id"] + ":test", "text": "must roll back"}
    with pytest.raises(Conflict):
        database.save(stale, notice)
    assert database.notification(notice["key"]) is None


def test_postgres_target_lock_has_one_owner(database):
    target = "test-" + uuid.uuid4().hex
    assert database.acquire_target(target, "one") == "one"
    assert database.acquire_target(target, "two") == "one"
    database.release_target(target, "two")
    assert database.owner(target) == "one"
    database.release_target(target, "one")
    assert database.acquire_target(target, "two") == "two"


def test_postgres_order_and_notice_commit_together(database):
    order, _ = database.create(new_order())
    order.update(state="ready", product_name="Türkçe sipariş")
    notice = {"key": order["id"] + ":ready", "text": "Gönderebilirsin"}
    database.save(order, notice)
    assert database.get(order["id"])["product_name"] == "Türkçe sipariş"
    assert database.notification(notice["key"])["state"] == "pending"


def test_postgres_literal_percent_query_without_parameters(database):
    # Regression for /admin/services: psycopg parsed '%' even with empty params.
    database.set_setting("binding:" + uuid.uuid4().hex[:8], {"name": "x", "components": []})
    with database.transaction() as conn:
        rows = database.execute(conn, "SELECT key FROM settings WHERE key LIKE 'binding:%'").fetchall()
    assert rows
    assert database.bindings()
