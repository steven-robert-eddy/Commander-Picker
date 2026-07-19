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
