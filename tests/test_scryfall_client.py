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


def test_build_image_lookup_prefers_full_card_over_art_crop(tmp_path):
    cards = [
        {
            "name": "Simple Card",
            "image_uris": {"art_crop": "https://img/simple-art.jpg", "normal": "https://img/simple.jpg"},
        },
        {"name": "Large Only", "image_uris": {"large": "https://img/large-only.jpg"}},
        {"name": "Art Crop Only Fallback", "image_uris": {"art_crop": "https://img/fallback-art.jpg"}},
        {"name": "No Images At All"},
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Simple Card"] == ["https://img/simple.jpg"]  # full card, not the art crop
    assert lookup["Large Only"] == ["https://img/large-only.jpg"]
    assert lookup["Art Crop Only Fallback"] == ["https://img/fallback-art.jpg"]  # last-resort fallback
    assert "No Images At All" not in lookup


def test_build_image_lookup_uses_both_faces_for_dfc(tmp_path):
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

    # Both faces, front then back -- a transform/MDFC commander's two
    # sides are genuinely different images, not interchangeable art.
    assert lookup["Valki, God of Lies // Tibalt, Cosmic Impostor"] == [
        "https://img/valki.jpg",
        "https://img/tibalt.jpg",
    ]


def test_build_image_lookup_aliases_front_face_name_for_transform_commanders(tmp_path):
    # EDHREC names a true transform/MDFC commander after its front face only
    # (e.g. "Heliod, the Radiant Dawn"), not Scryfall's full "A // B" name --
    # an exact-match lookup on that front-face-only name must still resolve
    # both images, not come up empty.
    cards = [
        {
            "name": "Heliod, the Radiant Dawn // Heliod, the Warped Eclipse",
            "card_faces": [
                {"name": "Heliod, the Radiant Dawn", "image_uris": {"normal": "https://img/heliod-front.jpg"}},
                {"name": "Heliod, the Warped Eclipse", "image_uris": {"normal": "https://img/heliod-back.jpg"}},
            ],
        }
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Heliod, the Radiant Dawn"] == [
        "https://img/heliod-front.jpg",
        "https://img/heliod-back.jpg",
    ]


def test_build_image_lookup_front_face_alias_does_not_override_real_card(tmp_path):
    # If a front-face name happens to collide with a real, independent
    # card's own full name, the real card's own entry must win.
    cards = [
        {
            "name": "Two-Face Card // Two-Face Card Back",
            "card_faces": [
                {"name": "Shared Name", "image_uris": {"normal": "https://img/dfc-front.jpg"}},
                {"name": "Two-Face Card Back", "image_uris": {"normal": "https://img/dfc-back.jpg"}},
            ],
        },
        {"name": "Shared Name", "image_uris": {"normal": "https://img/real-card.jpg"}},
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Shared Name"] == ["https://img/real-card.jpg"]


def test_build_image_lookup_split_card_uses_single_whole_card_image(tmp_path):
    # Split/adventure layouts also carry `card_faces`, but (unlike
    # transform/MDFC) share one whole-card `image_uris` at the top
    # level rather than per-face images -- still just one URL.
    cards = [
        {
            "name": "Fire // Ice",
            "image_uris": {"normal": "https://img/fire-ice.jpg"},
            "card_faces": [{"name": "Fire"}, {"name": "Ice"}],
        }
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Fire // Ice"] == ["https://img/fire-ice.jpg"]


def test_build_image_lookup_missing_file_raises(tmp_path):
    with pytest.raises(scryfall_client.ScryfallFetchError):
        scryfall_client.build_image_lookup(tmp_path / "nope.json")


def test_resolve_image_urls_direct_match():
    lookup = {"Korvold, Fae-Cursed King": ["https://img/korvold.jpg"]}
    assert scryfall_client.resolve_image_urls("Korvold, Fae-Cursed King", lookup) == ["https://img/korvold.jpg"]


def test_resolve_image_urls_dfc_returns_both_faces():
    lookup = {"Valki, God of Lies // Tibalt, Cosmic Impostor": ["https://img/valki.jpg", "https://img/tibalt.jpg"]}
    resolved = scryfall_client.resolve_image_urls("Valki, God of Lies // Tibalt, Cosmic Impostor", lookup)
    assert resolved == ["https://img/valki.jpg", "https://img/tibalt.jpg"]


def test_resolve_image_urls_partner_pair_combines_both_halves():
    # EDHREC's combined name isn't itself a Scryfall card; Scryfall has
    # each partner as a separate entry -- show both, not just the first.
    lookup = {"Krark, the Thumbless": ["https://img/krark.jpg"], "Vial Smasher the Fierce": ["https://img/vial.jpg"]}
    resolved = scryfall_client.resolve_image_urls("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert resolved == ["https://img/krark.jpg", "https://img/vial.jpg"]


def test_resolve_image_urls_partner_pair_one_half_missing():
    lookup = {"Krark, the Thumbless": ["https://img/krark.jpg"]}
    resolved = scryfall_client.resolve_image_urls("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert resolved == ["https://img/krark.jpg"]


def test_resolve_image_urls_no_match_returns_empty_list():
    assert scryfall_client.resolve_image_urls("Nonexistent Card", {}) == []
