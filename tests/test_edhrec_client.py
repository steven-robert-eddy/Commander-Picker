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


def test_fetch_set_page_uses_set_url(monkeypatch):
    payload = {"container": {"json_dict": {"cardlists": []}}}
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_set_page("sos")

    assert calls == ["https://json.edhrec.com/pages/sets/sos.json"]


def test_cached_slugs_returns_only_fetched_slugs_of_that_kind(monkeypatch):
    monkeypatch.setattr(
        edhrec_client.requests, "get", lambda *a, **k: _FakeResponse({"container": {"json_dict": {"cardlists": []}}})
    )

    assert edhrec_client.cached_slugs("set") == []
    edhrec_client.fetch_set_page("sos")
    edhrec_client.fetch_color_page("rakdos")

    assert edhrec_client.cached_slugs("set") == ["sos"]


def test_fetch_all_pages_fetches_given_set_slugs(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse({"container": {"json_dict": {"cardlists": []}}})

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    results, failures = edhrec_client.fetch_all_pages(color_slugs=[], theme_slugs=[], set_slugs=["sos"])

    assert failures == []
    assert len(results) == 1
    assert results[0].kind == "set"
    assert calls == ["https://json.edhrec.com/pages/sets/sos.json"]


def test_fetch_all_pages_no_set_slugs_fetches_nothing_for_sets(monkeypatch):
    monkeypatch.setattr(
        edhrec_client.requests, "get", lambda *a, **k: _FakeResponse({"container": {"json_dict": {"cardlists": []}}})
    )

    results, failures = edhrec_client.fetch_all_pages(color_slugs=[], theme_slugs=[])

    assert results == []
    assert failures == []


def test_discover_set_slugs_keeps_only_resolving_codes(monkeypatch):
    from commander_picker import scryfall_client

    monkeypatch.setattr(
        scryfall_client,
        "fetch_set_index",
        lambda force=False: [
            {"code": "sos", "name": "Secrets of Strixhaven", "set_type": "expansion", "released_at": "2026-01-01"},
            {"code": "nope", "name": "Not On EDHREC", "set_type": "expansion", "released_at": "2020-01-01"},
        ],
    )
    monkeypatch.setattr(edhrec_client.time, "sleep", lambda *_: None)

    import requests

    def fake_get(url, headers, timeout):
        if url.endswith("/nope.json"):
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError("404 Client Error", response=resp)
        return _FakeResponse({"container": {"json_dict": {"cardlists": []}}})

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    found = edhrec_client.discover_set_slugs()

    assert found == ["sos"]


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


def _cardview(num_decks, name=None):
    n = name or f"Commander {num_decks}"
    return {"name": n, "sanitized": n.lower(), "url": f"/commanders/{n.lower()}", "num_decks": num_decks}


def test_pagination_follows_more_chain_and_merges_cardviews(monkeypatch):
    monkeypatch.setattr(edhrec_client.time, "sleep", lambda *_: None)
    first_page = {
        "container": {
            "json_dict": {
                "cardlists": [
                    {
                        "tag": "rakdoscommanders",
                        "cardviews": [_cardview(9957), _cardview(560)],
                        "more": "commanders/rakdos-rakdoscommanders-1.json",
                    }
                ]
            }
        }
    }
    continuation_page = {
        "cardviews": [_cardview(500), _cardview(400)],
        "is_paginated": False,
    }

    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if "rakdoscommanders-1" in url:
            return _FakeResponse(continuation_page)
        return _FakeResponse(first_page)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_color_page("rakdos")

    assert calls == [
        "https://json.edhrec.com/pages/commanders/rakdos.json",
        "https://json.edhrec.com/pages/commanders/rakdos-rakdoscommanders-1.json",
    ]

    cached = edhrec_client.load_page("color", "rakdos")
    cardlist = cached["container"]["json_dict"]["cardlists"][0]
    assert [cv["num_decks"] for cv in cardlist["cardviews"]] == [9957, 560, 500, 400]
    assert "more" not in cardlist
    assert "is_paginated" not in cardlist


def test_pagination_stops_below_deck_floor(monkeypatch):
    monkeypatch.setattr(edhrec_client.time, "sleep", lambda *_: None)
    first_page = {
        "container": {
            "json_dict": {
                "cardlists": [
                    {
                        "tag": "rakdoscommanders",
                        "cardviews": [_cardview(200)],
                        "more": "commanders/rakdos-rakdoscommanders-1.json",
                    }
                ]
            }
        }
    }
    # Below MIN_DECKS_FLOOR (50) -- should stop here even though this
    # page itself still claims is_paginated/more.
    below_floor_page = {
        "cardviews": [_cardview(60), _cardview(30)],
        "is_paginated": True,
        "more": "commanders/rakdos-rakdoscommanders-2.json",
    }

    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if "rakdoscommanders-2" in url:
            pytest.fail("should not have fetched a third page once below the deck floor")
        if "rakdoscommanders-1" in url:
            return _FakeResponse(below_floor_page)
        return _FakeResponse(first_page)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_color_page("rakdos")

    assert len(calls) == 2  # first page + exactly one continuation page

    cached = edhrec_client.load_page("color", "rakdos")
    cardlist = cached["container"]["json_dict"]["cardlists"][0]
    # The 30-deck entry is filtered out (below floor); 200 and 60 stay.
    assert [cv["num_decks"] for cv in cardlist["cardviews"]] == [200, 60]


def test_pagination_stops_at_max_continuation_pages(monkeypatch):
    monkeypatch.setattr(edhrec_client.time, "sleep", lambda *_: None)
    first_page = {
        "container": {
            "json_dict": {
                "cardlists": [
                    {
                        "tag": "rakdoscommanders",
                        "cardviews": [_cardview(9000)],
                        "more": "commanders/page-0.json",
                    }
                ]
            }
        }
    }

    def fake_get(url, headers, timeout):
        if "commanders/page-" in url:
            # Every continuation page still claims more, and stays
            # comfortably above the deck floor -- only the page cap
            # should stop this.
            n = int(url.rsplit("page-", 1)[1].split(".")[0])
            return _FakeResponse(
                {
                    "cardviews": [_cardview(8000 - n)],
                    "is_paginated": True,
                    "more": f"commanders/page-{n + 1}.json",
                }
            )
        return _FakeResponse(first_page)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_color_page("rakdos")

    cached = edhrec_client.load_page("color", "rakdos")
    cardlist = cached["container"]["json_dict"]["cardlists"][0]
    # 1 (first page) + MAX_CONTINUATION_PAGES continuation pages.
    assert len(cardlist["cardviews"]) == 1 + edhrec_client.MAX_CONTINUATION_PAGES


def test_fetch_commander_detail_page_uses_color_url_template(monkeypatch):
    # Same URL template as color pages -- EDHREC serves both a
    # color-combo slug and a specific commander's own slug from
    # /pages/commanders/<slug>.json (confirmed live 2026-07-19).
    payload = {"header": "Rakdos, Lord of Riots (Commander)", "card": {"salt": 0.5}}
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    result = edhrec_client.fetch_commander_detail_page("rakdos-lord-of-riots")

    assert not result.from_cache
    assert calls == ["https://json.edhrec.com/pages/commanders/rakdos-lord-of-riots.json"]
    assert json.loads(result.path.read_text()) == payload


def test_commander_detail_page_cache_does_not_collide_with_color_page(monkeypatch):
    # Deliberately the SAME slug for both -- "rakdos" is both a real color
    # combo and (in principle) could be a commander's own slug. Since both
    # kinds share the exact same URL template, the request URL is
    # literally identical for the two fetches below; the cache-key prefix
    # ("color__" vs "commander__") is what has to keep them apart, not the
    # URL, so the two responses are told apart by call order instead.
    color_payload = {"container": {"json_dict": {"cardlists": []}}}
    detail_payload = {"header": "Rakdos (Commander)", "card": {"salt": 0.5}}
    payloads = iter([color_payload, detail_payload])

    def fake_get(url, headers, timeout):
        return _FakeResponse(next(payloads))

    monkeypatch.setattr(edhrec_client.requests, "get", fake_get)

    edhrec_client.fetch_color_page("rakdos")
    edhrec_client.fetch_commander_detail_page("rakdos")

    assert edhrec_client.load_page("color", "rakdos") == color_payload
    assert edhrec_client.load_page("commander", "rakdos") == detail_payload


def test_page_exists_for_commander_kind(monkeypatch):
    monkeypatch.setattr(edhrec_client.requests, "get", lambda *a, **k: _FakeResponse({"card": {}}))
    assert not edhrec_client.page_exists("commander", "rakdos-lord-of-riots")
    edhrec_client.fetch_commander_detail_page("rakdos-lord-of-riots")
    assert edhrec_client.page_exists("commander", "rakdos-lord-of-riots")
