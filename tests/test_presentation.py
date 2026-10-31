import pytest

from bot.presentation import order_view, panel_label, reason_code
from bot.panels import PanelClient
from types import SimpleNamespace


@pytest.mark.parametrize("raw,word", [("Completed", "tamamlandı"), ("Canceled", "iptal"),
                                      ("Partial", "kısmi"), ("Refunded", "iade")])
def test_provider_states_are_presented_in_turkish(raw, word):
    order = {"state": "finished", "parts": [{"status": raw}], "error": ""}
    assert word in order_view(order)["title"]
    assert raw not in panel_label(raw)


def test_mixed_completed_and_cancelled_package_is_partial():
    view = order_view({"state": "finished", "parts": [{"status": "Completed"}, {"status": "Canceled"}]})
    assert view["code"] == "partial" and view["tone"] == "warning"


@pytest.mark.parametrize("raw,code", [("Insufficient funds", "balance"), ("Invalid service", "service"),
                                      ("Quantity less than minimum", "quantity"), ("Incorrect API key", "panel_config")])
def test_panel_rejections_are_translated_without_persisting_raw_response(raw, code, monkeypatch):
    client = PanelClient({"test": {"api_url": "https://invalid.example", "api_key": "secret"}})
    monkeypatch.setattr(client, "request", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"error": raw}))
    result = client.add({"panel": "test", "service_id": "1", "quantity": 100}, "https://example.com")
    assert result.state == "error" and raw not in result.error
    assert reason_code(result.error, "error") == code


@pytest.mark.parametrize("raw", ["Not completed", "Unsuccessful", "Unknown status"])
def test_unrecognized_status_is_never_claimed_to_be_completed(raw):
    assert "tamamlandı" not in panel_label(raw)
