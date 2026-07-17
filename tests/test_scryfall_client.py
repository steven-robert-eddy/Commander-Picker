import json

import pytest

from commander_picker import scryfall_client


class _FakeResponse:
    def __init__(self, payload=None, content=None):
        self._payload = payload
        self._content = content if content is not None else json.dumps(payload or {}).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    @property
    def content(self):
        return self._content


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scryfall_client, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scryfall_client, "SCRYFALL_DIR", tmp_path / "scryfall")
    monkeypatch.setattr(scryfall_client, "ORACLE_CARDS_PATH", tmp_path / "scryfall" / "oracle_cards.json")
    monkeypatch.setattr(scryfall_client, "META_PATH", tmp_path / "scryfall" / "meta.json")
    yield


def test_fetch_oracle_cards_follows_index_to_download_uri(monkeypatch):
    index_payload = {
        "data": [
            {"type": "default_cards", "download_uri": "https://data.scryfall.io/default.json"},
            {"type": "oracle_cards", "download_uri": "https://data.scryfall.io/oracle-cards.json"},
        ]
    }
    cards_payload = [{"name": "Korvold, Fae-Cursed King", "image_uris": {"art_crop": "https://img/korvold.jpg"}}]
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url == scryfall_client.BULK_DATA_INDEX_URL:
            return _FakeResponse(index_payload)
        return _FakeResponse(content=json.dumps(cards_payload).encode())

    monkeypatch.setattr(scryfall_client.requests, "get", fake_get)

    path = scryfall_client.fetch_oracle_cards()

    assert calls == [scryfall_client.BULK_DATA_INDEX_URL, "https://data.scryfall.io/oracle-cards.json"]
    assert path.exists()
    assert json.loads(path.read_text()) == cards_payload


def test_fetch_oracle_cards_missing_oracle_entry_raises(monkeypatch):
    monkeypatch.setattr(
        scryfall_client.requests,
        "get",
        lambda *a, **k: _FakeResponse({"data": [{"type": "default_cards", "download_uri": "x"}]}),
    )
    with pytest.raises(scryfall_client.ScryfallFetchError):
        scryfall_client.fetch_oracle_cards()


def test_fetch_oracle_cards_cache_reused_within_freshness_window(monkeypatch):
    call_count = 0

    def fake_get(url, headers, timeout):
        nonlocal call_count
        call_count += 1
        if url == scryfall_client.BULK_DATA_INDEX_URL:
            return _FakeResponse({"data": [{"type": "oracle_cards", "download_uri": "https://x/oracle.json"}]})
        return _FakeResponse(content=b"[]")

    monkeypatch.setattr(scryfall_client.requests, "get", fake_get)

    scryfall_client.fetch_oracle_cards()
    first_call_count = call_count
    scryfall_client.fetch_oracle_cards()

    assert call_count == first_call_count  # second call served from cache, no new requests


def test_build_image_lookup_prefers_art_crop(tmp_path):
    cards = [
        {"name": "Simple Card", "image_uris": {"art_crop": "https://img/simple-art.jpg", "normal": "https://img/simple.jpg"}},
        {"name": "No Art Crop", "image_uris": {"normal": "https://img/normal-only.jpg"}},
        {"name": "No Images At All"},
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Simple Card"] == "https://img/simple-art.jpg"
    assert lookup["No Art Crop"] == "https://img/normal-only.jpg"
    assert "No Images At All" not in lookup


def test_build_image_lookup_uses_first_face_for_dfc(tmp_path):
    cards = [
        {
            "name": "Valki, God of Lies // Tibalt, Cosmic Impostor",
            "card_faces": [
                {"name": "Valki, God of Lies", "image_uris": {"art_crop": "https://img/valki.jpg"}},
                {"name": "Tibalt, Cosmic Impostor", "image_uris": {"art_crop": "https://img/tibalt.jpg"}},
            ],
        }
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Valki, God of Lies // Tibalt, Cosmic Impostor"] == "https://img/valki.jpg"


def test_build_image_lookup_missing_file_raises(tmp_path):
    with pytest.raises(scryfall_client.ScryfallFetchError):
        scryfall_client.build_image_lookup(tmp_path / "nope.json")


def test_resolve_image_url_direct_match():
    lookup = {"Korvold, Fae-Cursed King": "https://img/korvold.jpg"}
    assert scryfall_client.resolve_image_url("Korvold, Fae-Cursed King", lookup) == "https://img/korvold.jpg"


def test_resolve_image_url_partner_pair_falls_back_to_first_half():
    # EDHREC's combined name isn't itself a Scryfall card; Scryfall has
    # each partner as a separate entry.
    lookup = {"Krark, the Thumbless": "https://img/krark.jpg", "Vial Smasher the Fierce": "https://img/vial.jpg"}
    resolved = scryfall_client.resolve_image_url("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert resolved == "https://img/krark.jpg"


def test_resolve_image_url_no_match_returns_none():
    assert scryfall_client.resolve_image_url("Nonexistent Card", {}) is None
