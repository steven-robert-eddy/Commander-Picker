import json
import shutil
from pathlib import Path

import pytest

from commander_picker import db, edhrec_client

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
        "Korvold, Fae-Cursed King",
        "Ob Nixilis, the Adversary",
        "Rakdos, Lord of Riots",
        "Obscura Interceptor",
    }

    korvold = commanders["Korvold, Fae-Cursed King"]
    assert korvold.color_identity == ("B", "R", "G")  # WUBRG order
    assert korvold.num_decks == 6543
    assert korvold.themes == set()  # not on the aristocrats theme fixture

    ob_nix = commanders["Ob Nixilis, the Adversary"]
    assert ob_nix.themes == {"aristocrats"}


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
        assert rows[0]["name"] == "Rakdos, Lord of Riots"
        assert rows[0]["color_identity"] == "BR"

        theme_rows = conn.execute(
            "SELECT commander_name FROM commander_themes WHERE theme = 'aristocrats'"
        ).fetchall()
        assert {r["commander_name"] for r in theme_rows} == {
            "Ob Nixilis, the Adversary",
            "Obscura Interceptor",
        }
    finally:
        conn.close()


def test_connect_missing_db_raises(tmp_path):
    with pytest.raises(db.DbError):
        db.connect(db_path=tmp_path / "nope.db")
