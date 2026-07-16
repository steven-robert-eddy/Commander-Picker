import json

import pytest

from commander_picker import edhrec_client


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(edhrec_client, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edhrec_client, "EDHREC_DIR", tmp_path / "edhrec")
    monkeypatch.setattr(edhrec_client, "META_PATH", tmp_path / "edhrec_meta.json")
    yield


def test_fetch_color_page_writes_cache_and_meta(monkeypatch):
    payload = {"container": {"json_dict": {"cardlists": []}}}
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    result = edhrec_client.fetch_color_page("rakdos")

    assert not result.from_cache
    assert result.path.exists()
    assert json.loads(result.path.read_text()) == payload
    assert calls == ["https://json.edhrec.com/pages/commanders/rakdos.json"]


def test_fetch_theme_page_uses_theme_url(monkeypatch):
    payload = {"container": {"json_dict": {"cardlists": []}}}
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_theme_page("tokens")

    assert calls == ["https://json.edhrec.com/pages/tags/tokens.json"]


def test_second_fetch_within_freshness_window_uses_cache(monkeypatch):
    call_count = 0

    def fake_get(url, headers, timeout):
        nonlocal call_count
        call_count += 1
        return _FakeResponse({"container": {"json_dict": {"cardlists": []}}})

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_color_page("rakdos")
    result = edhrec_client.fetch_color_page("rakdos")

    assert result.from_cache
    assert call_count == 1


def test_force_bypasses_cache(monkeypatch):
    call_count = 0

    def fake_get(url, headers, timeout):
        nonlocal call_count
        call_count += 1
        return _FakeResponse({"container": {"json_dict": {"cardlists": []}}})

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_color_page("rakdos")
    result = edhrec_client.fetch_color_page("rakdos", force=True)

    assert not result.from_cache
    assert call_count == 2


def test_load_page_without_fetch_raises():
    with pytest.raises(edhrec_client.EdhrecFetchError):
        edhrec_client.load_page("color", "rakdos")


def test_page_exists(monkeypatch):
    monkeypatch.setattr(edhrec_client.requests, "get", lambda *a, **k: _FakeResponse({"container": {"json_dict": {"cardlists": []}}}))

    assert not edhrec_client.page_exists("color", "rakdos")
    edhrec_client.fetch_color_page("rakdos")
    assert edhrec_client.page_exists("color", "rakdos")


def test_fetch_all_pages_skips_bad_theme_slug_without_aborting(monkeypatch):
    import requests

    def fake_get(url, headers, timeout):
        if "/tags/" in url:
            resp = requests.Response()
            resp.status_code = 403
            raise requests.HTTPError("403 Client Error", response=resp)
        return _FakeResponse({"container": {"json_dict": {"cardlists": []}}})

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    results, failures = edhrec_client.fetch_all_pages(
        color_slugs=["rakdos"],
        theme_slugs=["not-a-real-tag"],
    )

    assert len(results) == 1
    assert results[0].kind == "color"
    assert len(failures) == 1
    assert failures[0].kind == "theme"
    assert failures[0].slug == "not-a-real-tag"


def test_fetch_all_pages_surfaces_color_failures_too(monkeypatch):
    import requests

    def fake_get(url, headers, timeout):
        resp = requests.Response()
        resp.status_code = 500
        raise requests.HTTPError("500 Server Error", response=resp)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    results, failures = edhrec_client.fetch_all_pages(color_slugs=["rakdos"], theme_slugs=[])

    assert results == []
    assert len(failures) == 1
    assert failures[0].kind == "color"
