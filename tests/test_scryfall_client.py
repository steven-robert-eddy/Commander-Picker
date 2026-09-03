import gzip
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
    monkeypatch.setattr(scryfall_client, "SETS_PATH", tmp_path / "scryfall" / "sets.json")
    monkeypatch.setattr(scryfall_client, "SETS_META_PATH", tmp_path / "scryfall" / "sets_meta.json")
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


def test_fetch_oracle_cards_decompresses_jsonl_gz(monkeypatch):
    # Scryfall's current bulk-data shape: jsonl_download_uri pointing at a
    # gzip-compressed JSON-Lines file (one card object per line), not a
    # plain JSON array. fetch_oracle_cards should reassemble it into the
    # JSON-array shape every reader of ORACLE_CARDS_PATH expects.
    index_payload = {
        "data": [
            {
                "type": "oracle_cards",
                "jsonl_download_uri": "https://data.scryfall.io/oracle-cards.jsonl.gz",
            },
        ]
    }
    cards = [
        {"name": "Korvold, Fae-Cursed King", "image_uris": {"art_crop": "https://img/korvold.jpg"}},
        {"name": "Atraxa, Praetors' Voice"},
    ]
    jsonl_gz = gzip.compress("\n".join(json.dumps(c) for c in cards).encode())
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url == scryfall_client.BULK_DATA_INDEX_URL:
            return _FakeResponse(index_payload)
        return _FakeResponse(content=jsonl_gz)

    monkeypatch.setattr(scryfall_client.requests, "get", fake_get)

    path = scryfall_client.fetch_oracle_cards()

    assert calls == [scryfall_client.BULK_DATA_INDEX_URL, "https://data.scryfall.io/oracle-cards.jsonl.gz"]
    assert json.loads(path.read_text()) == cards


def test_fetch_oracle_cards_prefers_jsonl_download_uri_over_download_uri(monkeypatch):
    index_payload = {
        "data": [
            {
                "type": "oracle_cards",
                "download_uri": "https://data.scryfall.io/oracle-cards.json",
                "jsonl_download_uri": "https://data.scryfall.io/oracle-cards.jsonl.gz",
            },
        ]
    }

    def fake_get(url, headers, timeout):
        if url == scryfall_client.BULK_DATA_INDEX_URL:
            return _FakeResponse(index_payload)
        return _FakeResponse(content=gzip.compress(b""))

    monkeypatch.setattr(scryfall_client.requests, "get", fake_get)

    path = scryfall_client.fetch_oracle_cards()

    assert json.loads(path.read_text()) == []


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


def test_fetch_set_index_filters_to_relevant_set_types(monkeypatch):
    payload = {
        "data": [
            {"code": "sos", "name": "Secrets of Strixhaven", "set_type": "expansion", "released_at": "2026-01-01"},
            {"code": "sos1", "name": "Strixhaven Art Series", "set_type": "art_series", "released_at": "2026-01-01"},
            {"code": "psos", "name": "Strixhaven Promos", "set_type": "promo", "released_at": "2026-01-01"},
        ]
    }
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _FakeResponse(payload)

    monkeypatch.setattr(scryfall_client.requests, "get", fake_get)

    entries = scryfall_client.fetch_set_index()

    assert calls == [scryfall_client.SETS_INDEX_URL]
    assert entries == [{"code": "sos", "name": "Secrets of Strixhaven", "set_type": "expansion", "released_at": "2026-01-01"}]


def test_fetch_set_index_cache_reused_within_freshness_window(monkeypatch):
    call_count = 0

    def fake_get(url, headers, timeout):
        nonlocal call_count
        call_count += 1
        return _FakeResponse({"data": []})

    monkeypatch.setattr(scryfall_client.requests, "get", fake_get)

    scryfall_client.fetch_set_index()
    first_call_count = call_count
    scryfall_client.fetch_set_index()

    assert call_count == first_call_count


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


@pytest.mark.parametrize("order", ["real_first", "art_series_first"])
def test_build_image_lookup_ignores_art_series_duplicate_name(tmp_path, order):
    # Scryfall's oracle_cards bulk file includes Art Series collectible
    # cards, which Scryfall names identically to the real card they
    # depict. Regardless of which entry appears first in the file, the
    # real card's image must win -- not just whichever is processed last.
    real_card = {"name": "Cosima, God of the Voyage", "image_uris": {"normal": "https://img/cosima-real.jpg"}}
    art_series_card = {
        "name": "Cosima, God of the Voyage",
        "layout": "art_series",
        "card_faces": [
            {"image_uris": {"normal": "https://img/cosima-art-front.jpg"}},
            {"image_uris": {"normal": "https://img/cosima-art-back.jpg"}},
        ],
    }
    cards = [real_card, art_series_card] if order == "real_first" else [art_series_card, real_card]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_image_lookup(path)

    assert lookup["Cosima, God of the Voyage"] == ["https://img/cosima-real.jpg"]


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


def test_build_card_meta_lookup_reads_cost_type_price(tmp_path):
    cards = [
        {
            "name": "Simple Card",
            "mana_cost": "{2}{B}{R}",
            "type_line": "Legendary Creature — Devil",
            "prices": {"usd": "12.34", "usd_foil": "20.00"},
        },
        {"name": "No Price Card", "mana_cost": "{1}{G}", "type_line": "Creature — Bear", "prices": {"usd": None}},
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_card_meta_lookup(path)

    assert lookup["Simple Card"] == scryfall_client.CardMeta(
        mana_cost="{2}{B}{R}", type_line="Legendary Creature — Devil", price_usd=12.34
    )
    assert lookup["No Price Card"].price_usd is None


def test_build_card_meta_lookup_falls_back_to_usd_foil(tmp_path):
    cards = [{"name": "Foil Only", "mana_cost": "{1}{W}", "type_line": "Creature — Human", "prices": {"usd": None, "usd_foil": "5.00"}}]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_card_meta_lookup(path)

    assert lookup["Foil Only"].price_usd == 5.00


def test_build_card_meta_lookup_transform_card_uses_front_face_cost(tmp_path):
    cards = [
        {
            "name": "Valki, God of Lies // Tibalt, Cosmic Impostor",
            "type_line": "Legendary Creature — God // Legendary Planeswalker — Tibalt",
            "card_faces": [
                {"name": "Valki, God of Lies", "mana_cost": "{1}{B}", "type_line": "Legendary Creature — God"},
                {"name": "Tibalt, Cosmic Impostor", "mana_cost": "", "type_line": "Legendary Planeswalker — Tibalt"},
            ],
            "prices": {"usd": "8.00"},
        }
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_card_meta_lookup(path)

    meta = lookup["Valki, God of Lies // Tibalt, Cosmic Impostor"]
    assert meta.mana_cost == "{1}{B}"  # front face's cost, not the blank top-level one
    assert meta.type_line == "Legendary Creature — God // Legendary Planeswalker — Tibalt"


@pytest.mark.parametrize("order", ["real_first", "art_series_first"])
def test_build_card_meta_lookup_ignores_art_series_duplicate_name(tmp_path, order):
    # Same collision as build_image_lookup's art-series test, but for
    # the independent meta lookup -- Art Series cards are typed "Card"
    # by Scryfall, which must not clobber the real card's mana cost/type.
    real_card = {
        "name": "Cosima, God of the Voyage",
        "mana_cost": "{2}{U}",
        "type_line": "Legendary Creature — God",
        "prices": {"usd": "5.00"},
    }
    art_series_card = {
        "name": "Cosima, God of the Voyage",
        "layout": "art_series",
        "type_line": "Card // Card",
    }
    cards = [real_card, art_series_card] if order == "real_first" else [art_series_card, real_card]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_card_meta_lookup(path)

    meta = lookup["Cosima, God of the Voyage"]
    assert meta.mana_cost == "{2}{U}"
    assert meta.type_line == "Legendary Creature — God"


def test_build_card_meta_lookup_reads_oracle_text(tmp_path):
    cards = [
        {
            "name": "Simple Card",
            "mana_cost": "{2}{B}{R}",
            "type_line": "Legendary Creature — Devil",
            "oracle_text": "Flying, haste\nWhenever this creature attacks, draw a card.",
            "prices": {"usd": "12.34"},
        }
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_card_meta_lookup(path)

    assert lookup["Simple Card"].oracle_text == "Flying, haste\nWhenever this creature attacks, draw a card."


def test_build_card_meta_lookup_transform_card_uses_front_face_oracle_text(tmp_path):
    cards = [
        {
            "name": "Valki, God of Lies // Tibalt, Cosmic Impostor",
            "type_line": "Legendary Creature — God // Legendary Planeswalker — Tibalt",
            "card_faces": [
                {"name": "Valki, God of Lies", "mana_cost": "{1}{B}", "type_line": "Legendary Creature — God", "oracle_text": "Whenever you discard a card, put a +1/+1 counter on Valki."},
                {"name": "Tibalt, Cosmic Impostor", "mana_cost": "", "type_line": "Legendary Planeswalker — Tibalt", "oracle_text": "Static ability text."},
            ],
            "prices": {"usd": "8.00"},
        }
    ]
    path = tmp_path / "oracle_cards.json"
    path.write_text(json.dumps(cards))

    lookup = scryfall_client.build_card_meta_lookup(path)

    meta = lookup["Valki, God of Lies // Tibalt, Cosmic Impostor"]
    assert meta.oracle_text == "Whenever you discard a card, put a +1/+1 counter on Valki."


def test_resolve_card_meta_partner_pair_combines_oracle_text():
    lookup = {
        "Krark, the Thumbless": scryfall_client.CardMeta(mana_cost="{1}{U}{R}", oracle_text="Krark's ability text."),
        "Vial Smasher the Fierce": scryfall_client.CardMeta(mana_cost="{1}{B}{R}", oracle_text="Vial Smasher's ability text."),
    }
    meta = scryfall_client.resolve_card_meta("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert meta.oracle_text == "Krark's ability text.\nVial Smasher's ability text."


def test_resolve_card_meta_partner_pair_one_half_missing_oracle_text():
    lookup = {"Krark, the Thumbless": scryfall_client.CardMeta(mana_cost="{1}{U}{R}", oracle_text="Krark's ability text.")}
    meta = scryfall_client.resolve_card_meta("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert meta.oracle_text == "Krark's ability text."


def test_build_card_meta_lookup_missing_file_raises(tmp_path):
    with pytest.raises(scryfall_client.ScryfallFetchError):
        scryfall_client.build_card_meta_lookup(tmp_path / "nope.json")


def test_resolve_card_meta_direct_match():
    lookup = {"Simple Card": scryfall_client.CardMeta(mana_cost="{2}{B}", type_line="Creature", price_usd=3.0)}
    assert scryfall_client.resolve_card_meta("Simple Card", lookup) == lookup["Simple Card"]


def test_resolve_card_meta_partner_pair_combines_both_halves():
    lookup = {
        "Krark, the Thumbless": scryfall_client.CardMeta(mana_cost="{1}{U}{R}", type_line="Legendary Creature — Goblin Pirate", price_usd=2.0),
        "Vial Smasher the Fierce": scryfall_client.CardMeta(mana_cost="{1}{B}{R}", type_line="Legendary Creature — Human Warrior", price_usd=1.5),
    }
    meta = scryfall_client.resolve_card_meta("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert meta.mana_cost == "{1}{U}{R} // {1}{B}{R}"
    assert meta.type_line == "Legendary Creature — Goblin Pirate // Legendary Creature — Human Warrior"
    assert meta.price_usd == 3.5


def test_resolve_card_meta_partner_pair_one_half_missing_price_gives_none():
    lookup = {"Krark, the Thumbless": scryfall_client.CardMeta(mana_cost="{1}{U}{R}", price_usd=2.0)}
    meta = scryfall_client.resolve_card_meta("Krark, the Thumbless // Vial Smasher the Fierce", lookup)
    assert meta.mana_cost == "{1}{U}{R}"
    assert meta.price_usd is None  # can't understate a combined price when half is unknown


def test_resolve_card_meta_no_match_returns_empty_meta():
    assert scryfall_client.resolve_card_meta("Nonexistent Card", {}) == scryfall_client.CardMeta()
