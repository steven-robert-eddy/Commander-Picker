import json
import shutil
from pathlib import Path

import pytest

from commander_picker import db, edhrec_client, scryfall_client

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def populated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(edhrec_client, "DATA_DIR", tmp_path)
    edhrec_dir = tmp_path / "edhrec"
    edhrec_dir.mkdir()
    monkeypatch.setattr(edhrec_client, "EDHREC_DIR", edhrec_dir)
    monkeypatch.setattr(edhrec_client, "META_PATH", tmp_path / "edhrec_meta.json")

    shutil.copy(FIXTURES / "sample_color_page.json", edhrec_dir / "color__rakdos.json")
    shutil.copy(FIXTURES / "sample_theme_page.json", edhrec_dir / "theme__aristocrats.json")

    return tmp_path


@pytest.fixture
def populated_cache_with_set(populated_cache):
    shutil.copy(FIXTURES / "sample_set_page.json", populated_cache / "edhrec" / "set__sos.json")
    return populated_cache


def test_load_commanders_merges_color_and_theme_data(populated_cache):
    commanders = db.load_commanders(color_slugs=["rakdos"], theme_slugs=["aristocrats"])

    assert set(commanders) == {
        "Valgavoth, Harrower of Souls",
        "Prosper, Tome-Bound",
        "Rakdos, Lord of Riots",
        "Krark, the Thumbless // Vial Smasher the Fierce",
    }

    # Color identity comes from the page itself (the "rakdos" slug), not
    # a per-cardview field -- real EDHREC cardviews don't carry one.
    valgavoth = commanders["Valgavoth, Harrower of Souls"]
    assert valgavoth.color_identity == ("B", "R")
    assert valgavoth.num_decks == 28969
    assert valgavoth.rank == 1
    assert valgavoth.themes == set()  # not on the aristocrats theme fixture

    rakdos_lor = commanders["Rakdos, Lord of Riots"]
    assert rakdos_lor.themes == {"aristocrats"}


def test_load_commanders_no_cache_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(edhrec_client, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edhrec_client, "EDHREC_DIR", tmp_path / "edhrec")
    monkeypatch.setattr(edhrec_client, "META_PATH", tmp_path / "edhrec_meta.json")

    with pytest.raises(db.DbError):
        db.load_commanders(color_slugs=["rakdos"], theme_slugs=[])


def test_build_database_writes_queryable_sqlite(populated_cache):
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute(
            "SELECT name, color_identity, num_decks FROM commanders ORDER BY num_decks DESC"
        ).fetchall()
        assert rows[0]["name"] == "Valgavoth, Harrower of Souls"
        assert rows[0]["color_identity"] == "BR"

        theme_rows = conn.execute(
            "SELECT commander_name FROM commander_themes WHERE theme = 'aristocrats'"
        ).fetchall()
        assert {r["commander_name"] for r in theme_rows} == {
            "Rakdos, Lord of Riots",
            "Krark, the Thumbless // Vial Smasher the Fierce",
        }
    finally:
        conn.close()


def test_build_database_populates_commander_sets_excluding_reprints(populated_cache_with_set):
    db_path = populated_cache_with_set / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], set_slugs=["sos"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute("SELECT commander_name, set_slug, set_name FROM commander_sets").fetchall()
        by_name = {r["commander_name"]: r for r in rows}
        assert set(by_name) == {"Rakdos, Lord of Riots", "Prosper, Tome-Bound"}
        assert "Valgavoth, Harrower of Souls" not in by_name  # commanders(reprints) -- excluded
        assert by_name["Rakdos, Lord of Riots"]["set_slug"] == "sos"
        assert by_name["Rakdos, Lord of Riots"]["set_name"] == "Secrets of Strixhaven"
    finally:
        conn.close()


def test_build_database_populates_commander_sets_from_plain_commanders_tag(populated_cache):
    # Older/simpler set pages (e.g. Amonkhet) have no dedicated
    # Commander-precon product to split into commanders(<code>)/
    # commanders(<precon code>) -- just a single plain "commanders" tag.
    # That shape must still be picked up, not just the parenthesized one.
    shutil.copy(FIXTURES / "sample_set_page_plain_tag.json", populated_cache / "edhrec" / "set__akh.json")
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], set_slugs=["akh"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute("SELECT commander_name, set_slug FROM commander_sets").fetchall()
        by_name = {r["commander_name"]: r for r in rows}
        assert set(by_name) == {"Rakdos, Lord of Riots"}
        assert "Valgavoth, Harrower of Souls" not in by_name  # commanders(reprints) -- excluded
        assert by_name["Rakdos, Lord of Riots"]["set_slug"] == "akh"
    finally:
        conn.close()


def test_build_database_default_set_slugs_loads_whatever_is_cached(populated_cache_with_set):
    db_path = populated_cache_with_set / "commanders.db"

    # No explicit set_slugs -- should still pick up the cached "sos" page.
    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute("SELECT commander_name FROM commander_sets").fetchall()
        assert {r["commander_name"] for r in rows} == {"Rakdos, Lord of Riots", "Prosper, Tome-Bound"}
    finally:
        conn.close()


def test_build_database_without_set_pages_leaves_commander_sets_empty(populated_cache):
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute("SELECT * FROM commander_sets").fetchall()
        assert rows == []
    finally:
        conn.close()


def test_connect_missing_db_raises(tmp_path):
    with pytest.raises(db.DbError):
        db.connect(db_path=tmp_path / "nope.db")


def test_build_database_populates_image_urls_from_lookup(populated_cache):
    db_path = populated_cache / "commanders.db"
    image_lookup = {
        "Rakdos, Lord of Riots": ["https://img/rakdos.jpg"],
        # Partner pair -- each half is a separate Scryfall card, so both
        # should show up in the combined commander's image list.
        "Krark, the Thumbless": ["https://img/krark.jpg"],
        "Vial Smasher the Fierce": ["https://img/vial.jpg"],
    }

    db.build_database(
        color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path, image_lookup=image_lookup
    )

    conn = db.connect(db_path=db_path)
    try:
        row = conn.execute(
            "SELECT image_urls FROM commanders WHERE name = 'Rakdos, Lord of Riots'"
        ).fetchone()
        assert json.loads(row["image_urls"]) == ["https://img/rakdos.jpg"]

        partner_row = conn.execute(
            "SELECT image_urls FROM commanders WHERE name = 'Krark, the Thumbless // Vial Smasher the Fierce'"
        ).fetchone()
        assert json.loads(partner_row["image_urls"]) == ["https://img/krark.jpg", "https://img/vial.jpg"]

        no_image_row = conn.execute(
            "SELECT image_urls FROM commanders WHERE name = 'Valgavoth, Harrower of Souls'"
        ).fetchone()
        assert json.loads(no_image_row["image_urls"]) == []
    finally:
        conn.close()


def test_build_database_without_image_lookup_leaves_image_urls_empty(populated_cache):
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute("SELECT image_urls FROM commanders").fetchall()
        assert all(json.loads(r["image_urls"]) == [] for r in rows)
    finally:
        conn.close()


def test_build_database_writes_rank(populated_cache):
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        row = conn.execute(
            "SELECT rank FROM commanders WHERE name = 'Valgavoth, Harrower of Souls'"
        ).fetchone()
        assert row["rank"] == 1
    finally:
        conn.close()


def test_build_database_populates_card_meta_from_lookup(populated_cache):
    db_path = populated_cache / "commanders.db"
    card_meta_lookup = {
        "Rakdos, Lord of Riots": scryfall_client.CardMeta(
            mana_cost="{2}{B}{R}", type_line="Legendary Creature — Devil", price_usd=5.5
        ),
    }

    db.build_database(
        color_slugs=["rakdos"],
        theme_slugs=["aristocrats"],
        db_path=db_path,
        card_meta_lookup=card_meta_lookup,
    )

    conn = db.connect(db_path=db_path)
    try:
        row = conn.execute(
            "SELECT mana_cost, type_line, price FROM commanders WHERE name = 'Rakdos, Lord of Riots'"
        ).fetchone()
        assert row["mana_cost"] == "{2}{B}{R}"
        assert row["type_line"] == "Legendary Creature — Devil"
        assert row["price"] == 5.5

        no_meta_row = conn.execute(
            "SELECT mana_cost, price FROM commanders WHERE name = 'Valgavoth, Harrower of Souls'"
        ).fetchone()
        assert no_meta_row["mana_cost"] is None
        assert no_meta_row["price"] is None
    finally:
        conn.close()


def test_build_database_without_card_meta_lookup_leaves_fields_null(populated_cache):
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        rows = conn.execute("SELECT mana_cost, type_line, price FROM commanders").fetchall()
        assert all(r["mana_cost"] is None and r["type_line"] is None and r["price"] is None for r in rows)
    finally:
        conn.close()


def test_build_database_populates_oracle_text_from_lookup(populated_cache):
    db_path = populated_cache / "commanders.db"
    card_meta_lookup = {
        "Rakdos, Lord of Riots": scryfall_client.CardMeta(
            mana_cost="{2}{B}{R}", type_line="Legendary Creature — Devil", oracle_text="Rakdos, Lord of Riots costs {2} less to cast..."
        ),
    }

    db.build_database(
        color_slugs=["rakdos"],
        theme_slugs=["aristocrats"],
        db_path=db_path,
        card_meta_lookup=card_meta_lookup,
    )

    conn = db.connect(db_path=db_path)
    try:
        row = conn.execute(
            "SELECT oracle_text FROM commanders WHERE name = 'Rakdos, Lord of Riots'"
        ).fetchone()
        assert row["oracle_text"] == "Rakdos, Lord of Riots costs {2} less to cast..."

        no_meta_row = conn.execute(
            "SELECT oracle_text FROM commanders WHERE name = 'Valgavoth, Harrower of Souls'"
        ).fetchone()
        assert no_meta_row["oracle_text"] is None
    finally:
        conn.close()


def test_load_commanders_applies_cached_detail_page(populated_cache):
    shutil.copy(
        FIXTURES / "sample_commander_detail_page.json",
        populated_cache / "edhrec" / "commander__rakdos-lord-of-riots.json",
    )

    commanders = db.load_commanders(color_slugs=["rakdos"], theme_slugs=["aristocrats"])

    rakdos_lor = commanders["Rakdos, Lord of Riots"]
    assert rakdos_lor.salt == 0.4550264550264551
    # Merged with the pre-existing tag-page theme, not replaced by it.
    assert "aristocrats" in rakdos_lor.themes
    assert "demons" in rakdos_lor.themes
    assert "burn" in rakdos_lor.themes
    assert len(rakdos_lor.themes - {"aristocrats"}) == db.TOP_TAGS_PER_COMMANDER
    # bracket_counts: {"1": 27, "2": 1140, "3": 846, "4": 270, "5": 43} -- 2 is dominant.
    assert rakdos_lor.power_level == 2

    # No cached detail page for this one -- left exactly as before.
    valgavoth = commanders["Valgavoth, Harrower of Souls"]
    assert valgavoth.salt is None
    assert valgavoth.power_level is None


def test_apply_commander_detail_keeps_only_top_n_tags_by_count():
    record = db.CommanderRecord(
        name="Test Commander",
        sanitized="test-commander",
        color_identity=("B", "R"),
        num_decks=100,
        edhrec_url=None,
    )
    payload = {
        "card": {"salt": 0.9},
        "panels": {
            "taglinks": [{"count": i, "slug": f"tag-{i}", "value": f"Tag {i}"} for i in range(1, 25)]
        },
    }

    db._apply_commander_detail(record, payload)

    assert record.salt == 0.9
    assert len(record.themes) == db.TOP_TAGS_PER_COMMANDER
    assert "tag-24" in record.themes  # highest count kept
    assert "tag-1" not in record.themes  # lowest count dropped
    assert record.power_level is None  # no bracket_counts in this payload


def test_apply_commander_detail_sets_dominant_power_level():
    record = db.CommanderRecord(
        name="Test Commander",
        sanitized="test-commander",
        color_identity=("B", "R"),
        num_decks=100,
        edhrec_url=None,
    )
    payload = {"card": {}, "bracket_counts": {"1": 5, "2": 5, "3": 400, "4": 10, "5": 1}}

    db._apply_commander_detail(record, payload)

    assert record.power_level == 3


def test_apply_commander_detail_empty_bracket_counts_leaves_power_level_none():
    record = db.CommanderRecord(
        name="Test Commander",
        sanitized="test-commander",
        color_identity=("B", "R"),
        num_decks=100,
        edhrec_url=None,
    )
    db._apply_commander_detail(record, {"card": {}, "bracket_counts": {}})
    assert record.power_level is None


def test_build_database_persists_salt_and_detail_themes(populated_cache):
    shutil.copy(
        FIXTURES / "sample_commander_detail_page.json",
        populated_cache / "edhrec" / "commander__rakdos-lord-of-riots.json",
    )
    db_path = populated_cache / "commanders.db"

    db.build_database(color_slugs=["rakdos"], theme_slugs=["aristocrats"], db_path=db_path)

    conn = db.connect(db_path=db_path)
    try:
        row = conn.execute("SELECT salt, power_level FROM commanders WHERE name = 'Rakdos, Lord of Riots'").fetchone()
        assert row["salt"] == 0.4550264550264551
        assert row["power_level"] == 2

        theme_rows = conn.execute(
            "SELECT theme FROM commander_themes WHERE commander_name = 'Rakdos, Lord of Riots'"
        ).fetchall()
        themes = {r["theme"] for r in theme_rows}
        assert "demons" in themes
        assert "aristocrats" in themes
    finally:
        conn.close()
