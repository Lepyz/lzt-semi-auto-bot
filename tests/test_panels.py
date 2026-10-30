from types import SimpleNamespace

import pytest
import requests

from bot.panels import PanelClient


def client_and_part():
    return PanelClient({"smmrush": {"api_url": "https://panel.invalid", "api_key": "test-secret"}}), {
        "panel": "smmrush", "service_id": "123", "quantity": 100, "smm_id": "1"}


def test_add_timeout_is_uncertain_and_not_retried(monkeypatch):
    client, part = client_and_part()
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs["data"]["action"])
        raise requests.Timeout()
    monkeypatch.setattr(requests, "post", timeout)
    assert client.add(part, "https://instagram.com/customer").state == "uncertain"
    assert calls == ["add"]


@pytest.mark.parametrize("status", ["Not completed", "Unsuccessful", "Pending", "In progress", "Processing"])
def test_substrings_cannot_misclassify_active_status_as_completed(status, monkeypatch):
    client, part = client_and_part()
    monkeypatch.setattr(client, "request", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"status": status}))
    assert client.status(part)["terminal"] is False


@pytest.mark.parametrize("status", ["Completed", "Partial", "Canceled", "Kısmi iade", "İptal edildi"])
def test_actual_terminal_statuses(status, monkeypatch):
    client, part = client_and_part()
    monkeypatch.setattr(client, "request", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"status": status}))
    assert client.status(part) == {"status": status, "terminal": True}


def test_add_error_hides_panel_key(monkeypatch):
    client, part = client_and_part()
    monkeypatch.setattr(client, "request", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"error": "invalid test-secret"}))
    result = client.add(part, "https://instagram.com/customer")
    assert result.state == "error" and "test-secret" not in result.error


def test_server_error_after_add_is_uncertain(monkeypatch):
    client, part = client_and_part()
    monkeypatch.setattr(client, "request", lambda *a, **k: SimpleNamespace(status_code=503))
    assert client.add(part, "https://instagram.com/customer").state == "uncertain"


def test_api_success_wrapper_is_not_an_order_completion(monkeypatch):
    client, part = client_and_part()
    monkeypatch.setattr(client, "request", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"status": "success", "data": {"status": "Pending"}}))
    assert client.status(part) == {"status": "Pending", "terminal": False}
