import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from commander_picker import db, sessions
from commander_picker.web.app import app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path, monkeypatch):
    edhrec_dir = tmp_path / "edhrec"
    edhrec_dir.mkdir()
    shutil.copy(FIXTURES / "sample_color_page.json", edhrec_dir / "color__rakdos.json")
    shutil.copy(FIXTURES / "sample_theme_page.json", edhrec_dir / "theme__tokens.json")

    from commander_picker import edhrec_client

    monkeypatch.setattr(edhrec_client, "DATA_DIR", tmp_path)
    monkeypatch.setattr(edhrec_client, "EDHREC_DIR", edhrec_dir)
    monkeypatch.setattr(edhrec_client, "META_PATH", tmp_path / "edhrec_meta.json")

    db_path = tmp_path / "commanders.db"
    db.build_database(color_slugs=["rakdos"], theme_slugs=["tokens"], db_path=db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)

    sessions_path = tmp_path / "sessions.db"
    monkeypatch.setattr(sessions, "SESSIONS_DB_PATH", sessions_path)

    return TestClient(app)


def _pool_body(**overrides):
    body = {
        "colors": None,
        "color_mode": "subset",
        "max_decks": 30000,
        "min_decks": None,
        "themes": [],
        "themes_mode": "any",
        "pool_size": 40,
        "min_pool_size": 2,
    }
    body.update(overrides)
    return body


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Commander" in resp.text


def test_static_files_served(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    resp = client.get("/static/style.css")
    assert resp.status_code == 200


def test_api_themes(client):
    resp = client.get("/api/themes")
    assert resp.status_code == 200
    assert "tokens" in resp.json()["slugs"]


def test_api_pool_returns_filtered_candidates(client):
    resp = client.post("/api/pool", json=_pool_body(max_decks=10000))
    assert resp.status_code == 200
    body = resp.json()
    names = {c["name"] for c in body["candidates"]}
    assert names == {"Rakdos, Lord of Riots", "Krark, the Thumbless // Vial Smasher the Fierce"}
    assert body["total_matches"] == 2


def test_api_pool_total_matches_uncapped_by_pool_size(client):
    # 4 fixture commanders total, no deck-count ceiling -- total_matches
    # should report all 4 even when pool_size caps candidates lower.
    resp = client.post("/api/pool", json=_pool_body(max_decks=None, pool_size=2))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_matches"] == 4
    assert len(body["candidates"]) == 2


def test_api_pool_size_out_of_bounds_rejected(client):
    resp = client.post("/api/pool", json=_pool_body(pool_size=500))
    assert resp.status_code == 422


def test_api_pool_too_small_returns_422(client):
    resp = client.post("/api/pool", json=_pool_body(colors="U", color_mode="exact"))
    assert resp.status_code == 422


def test_api_pool_no_catalog_returns_503(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nope.db")
    monkeypatch.setattr(sessions, "SESSIONS_DB_PATH", tmp_path / "sessions.db")
    client = TestClient(app)
    resp = client.post("/api/pool", json=_pool_body())
    assert resp.status_code == 503


def test_create_session_returns_pairing(client):
    resp = client.post("/api/sessions", json=_pool_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["status"] == "active"
    assert data["info"]["pool_size"] == 4
    assert len(data["pairing"]["candidates"]) == 2


def test_full_session_lifecycle(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    a, b = created["pairing"]["candidates"]

    pick_resp = client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})
    assert pick_resp.status_code == 200
    next_pairing = pick_resp.json()
    assert next_pairing["round"] == 2

    info_resp = client.get(f"/api/sessions/{session_id}")
    assert info_resp.json()["rounds_completed"] == 1

    finish_resp = client.post(f"/api/sessions/{session_id}/finish")
    assert finish_resp.status_code == 200
    rankings = finish_resp.json()["rankings"]
    assert rankings[0]["name"] == a["name"]
    assert rankings[0]["rating"] > 1000.0

    # Session is complete -- pairing should now be null, not another duel.
    pairing_resp = client.get(f"/api/sessions/{session_id}/pairing")
    assert pairing_resp.status_code == 200
    assert pairing_resp.json() is None


def test_pick_unknown_session_returns_400(client):
    resp = client.post("/api/sessions/does-not-exist/pick", json={"winner": "A", "loser": "B"})
    assert resp.status_code == 400


def test_get_unknown_session_returns_404(client):
    resp = client.get("/api/sessions/does-not-exist")
    assert resp.status_code == 404


def test_list_sessions(client):
    client.post("/api/sessions", json=_pool_body())
    client.post("/api/sessions", json=_pool_body())
    resp = client.get("/api/sessions")
    assert len(resp.json()["sessions"]) == 2
