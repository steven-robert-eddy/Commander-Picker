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
    # Data-driven from commander_themes, not the static THEME_SLUGS list --
    # only "tokens" was actually fetched/tagged by the fixture, so a
    # curated-but-untagged slug like "aggro" must not show up.
    assert resp.json()["slugs"] == ["tokens"]


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


def test_api_pool_max_price_filters(client, monkeypatch):
    import sqlite3

    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("UPDATE commanders SET price = 5.0 WHERE name = 'Rakdos, Lord of Riots'")
    conn.execute("UPDATE commanders SET price = 80.0 WHERE name LIKE 'Krark%'")
    conn.commit()
    conn.close()

    resp = client.post("/api/pool", json=_pool_body(max_decks=10000, max_price=10.0, min_pool_size=1))
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["candidates"]}
    assert names == {"Rakdos, Lord of Riots"}


def test_api_pool_max_price_none_is_permissive_on_missing_price(client):
    # Fixture commanders have no price data at all by default -- an
    # active price filter must not exclude everything.
    resp = client.post("/api/pool", json=_pool_body(max_decks=10000, max_price=1.0))
    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 2


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


def test_undo_reverts_last_pick(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    a, b = created["pairing"]["candidates"]
    client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})

    undo_resp = client.post(f"/api/sessions/{session_id}/undo")
    assert undo_resp.status_code == 200

    info = client.get(f"/api/sessions/{session_id}").json()
    assert info["rounds_completed"] == 0

    board = {row["name"]: row for row in client.get("/api/leaderboard").json()["leaderboard"]}
    assert a["name"] not in board
    assert b["name"] not in board


def test_undo_with_nothing_to_undo_returns_400(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/undo")
    assert resp.status_code == 400


def test_undo_un_finishes_completed_session(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    target_rounds = created["info"]["target_rounds"]
    pairing = created["pairing"]
    for _ in range(target_rounds):
        a, b = pairing["candidates"]
        resp = client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})
        pairing = resp.json()

    info = client.get(f"/api/sessions/{session_id}").json()
    assert info["status"] == "complete"

    undo_resp = client.post(f"/api/sessions/{session_id}/undo")
    assert undo_resp.status_code == 200

    info = client.get(f"/api/sessions/{session_id}").json()
    assert info["status"] == "active"
    assert info["rounds_completed"] == target_rounds - 1


def test_undo_rejects_bracket_mode(client):
    created = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=4)).json()
    session_id = created["session_id"]
    a, b = created["pairing"]["candidates"]
    client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})

    resp = client.post(f"/api/sessions/{session_id}/undo")
    assert resp.status_code == 400


def test_session_auto_finishes_at_target_rounds(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    target_rounds = created["info"]["target_rounds"]
    assert target_rounds > 0

    pairing = created["pairing"]
    for _ in range(target_rounds):
        a, b = pairing["candidates"]
        resp = client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})
        assert resp.status_code == 200
        pairing = resp.json()

    # The pick that completed the final round should have returned no
    # further pairing -- the session auto-finished, not just "reached
    # the suggested count with nothing visibly different."
    assert pairing is None

    info = client.get(f"/api/sessions/{session_id}").json()
    assert info["status"] == "complete"
    assert info["rounds_completed"] == target_rounds

    # A stale client trying to pick again after auto-finish gets a
    # clear error, not silently-accepted data for a round that no
    # longer exists.
    a_name = created["pairing"]["candidates"][0]["name"]
    b_name = created["pairing"]["candidates"][1]["name"]
    late_pick = client.post(f"/api/sessions/{session_id}/pick", json={"winner": a_name, "loser": b_name})
    assert late_pick.status_code == 400


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


def test_leaderboard_empty_before_any_picks(client):
    resp = client.get("/api/leaderboard")
    assert resp.status_code == 200
    assert resp.json() == {"leaderboard": []}


def test_leaderboard_reflects_picks_and_persists_across_sessions(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    a = created["pairing"]["candidates"][0]["name"]
    b = created["pairing"]["candidates"][1]["name"]
    client.post(f"/api/sessions/{session_id}/pick", json={"winner": a, "loser": b})

    resp = client.get("/api/leaderboard")
    assert resp.status_code == 200
    board = {row["name"]: row for row in resp.json()["leaderboard"]}
    assert board[a]["rating"] > 1000.0
    assert board[a]["games_played"] == 1
    assert board[b]["rating"] < 1000.0

    # A brand-new session should seed the winner's rating from its
    # global history instead of resetting to 1000.
    second = client.post("/api/sessions", json=_pool_body()).json()
    second_candidates = {c["name"]: c["rating"] for c in second["pairing"]["candidates"]}
    if a in second_candidates:
        assert second_candidates[a] == pytest.approx(board[a]["rating"])


def test_leaderboard_filters_by_color(client):
    resp = client.post(
        "/api/sessions",
        json=_pool_body(colors="BR", color_mode="subset", max_decks=None, pool_size=4, min_pool_size=2),
    )
    session_id = resp.json()["session_id"]
    pairing = resp.json()["pairing"]
    while pairing:
        a, b = pairing["candidates"]
        pick = client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})
        pairing = pick.json()

    # Fixture data (see _pool_body/sample_color_page.json) is all
    # BR/Rakdos-identity commanders, so an exact-BR filter should
    # return everything rated, and an unrelated color should return
    # nothing.
    matching = client.get("/api/leaderboard?colors=BR&color_mode=exact").json()["leaderboard"]
    assert len(matching) > 0

    non_matching = client.get("/api/leaderboard?colors=U&color_mode=exact").json()["leaderboard"]
    assert non_matching == []


# ---- bracket mode ----


def test_create_bracket_session(client):
    resp = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=4))
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["mode"] == "bracket"
    assert data["info"]["pool_size"] == 4
    assert data["info"]["target_rounds"] == 2  # log2(4)
    assert data["pairing"]["round_label"] in ("Semifinal", "Final")
    assert len(data["pairing"]["candidates"]) == 2


def test_create_bracket_session_rejects_non_power_of_two_pool_size(client):
    resp = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=3))
    assert resp.status_code == 422


def test_create_bracket_session_rejects_unfulfillable_size(client):
    # Fixture only has 4 total commanders -- asking for a bracket of 8
    # can't be satisfied even though 8 is a valid bracket size.
    resp = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=8))
    assert resp.status_code == 422


def test_bracket_full_playthrough_and_tree(client):
    created = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=4)).json()
    session_id = created["session_id"]
    pairing = created["pairing"]

    while pairing:
        a, b = pairing["candidates"]
        resp = client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})
        assert resp.status_code == 200
        pairing = resp.json()

    info = client.get(f"/api/sessions/{session_id}").json()
    assert info["status"] == "complete"
    assert info["rounds_completed"] == 2

    bracket = client.get(f"/api/sessions/{session_id}/bracket").json()
    assert bracket["champion"] is not None
    assert len(bracket["rounds"]) == 2
    assert len(bracket["rounds"][0]) == 2  # 2 semifinal matches
    assert len(bracket["rounds"][1]) == 1  # 1 final
    assert bracket["rounds"][1][0]["winner"] == bracket["champion"]


def test_bracket_pick_mismatched_pair_returns_400(client):
    created = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=4)).json()
    session_id = created["session_id"]

    # 4-team bracket has two round-1 matches; both are ready simultaneously.
    # A "cross" pairing -- one name from each match -- was never actually
    # scheduled together, so it should be rejected even though both names
    # are valid, active bracket participants.
    bracket = client.get(f"/api/sessions/{session_id}/bracket").json()
    round1 = bracket["rounds"][0]
    assert len(round1) == 2
    cross_a, cross_b = round1[0]["seed_a"], round1[1]["seed_a"]

    resp = client.post(f"/api/sessions/{session_id}/pick", json={"winner": cross_a, "loser": cross_b})
    assert resp.status_code == 400


def test_bracket_session_cannot_finish_early(client):
    created = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=4)).json()
    session_id = created["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/finish")
    assert resp.status_code == 400


def test_reset_leaderboard_clears_ratings_but_not_session_results(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    a = created["pairing"]["candidates"][0]["name"]
    b = created["pairing"]["candidates"][1]["name"]
    client.post(f"/api/sessions/{session_id}/pick", json={"winner": a, "loser": b})

    assert client.get("/api/leaderboard").json()["leaderboard"] != []

    resp = client.delete("/api/leaderboard")
    assert resp.status_code == 200
    assert client.get("/api/leaderboard").json()["leaderboard"] == []

    # The session's own results are untouched.
    info = client.get(f"/api/sessions/{session_id}").json()
    assert info["rounds_completed"] == 1


def test_search_commanders_endpoint(client):
    resp = client.get("/api/commanders/search?q=rakdos")
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["name"] for r in results] == ["Rakdos, Lord of Riots"]
    assert "color_identity" in results[0]
    assert "num_decks" in results[0]


def test_search_commanders_requires_query(client):
    resp = client.get("/api/commanders/search")
    assert resp.status_code == 422


def test_create_custom_duel_session(client):
    resp = client.post(
        "/api/sessions/custom",
        json={"names": ["Rakdos, Lord of Riots", "Prosper, Tome-Bound"], "mode": "duel"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["mode"] == "duel"
    assert data["info"]["pool_size"] == 2
    assert "Custom list" in data["info"]["description"]
    names = {c["name"] for c in data["pairing"]["candidates"]}
    assert names == {"Rakdos, Lord of Riots", "Prosper, Tome-Bound"}


def test_create_custom_bracket_session(client):
    resp = client.post(
        "/api/sessions/custom",
        json={
            "names": [
                "Rakdos, Lord of Riots",
                "Prosper, Tome-Bound",
                "Valgavoth, Harrower of Souls",
                "Krark, the Thumbless // Vial Smasher the Fierce",
            ],
            "mode": "bracket",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["mode"] == "bracket"
    assert data["info"]["pool_size"] == 4
    assert data["info"]["target_rounds"] == 2


def test_create_custom_bracket_session_rejects_non_power_of_two(client):
    resp = client.post(
        "/api/sessions/custom",
        json={"names": ["Rakdos, Lord of Riots", "Prosper, Tome-Bound", "Valgavoth, Harrower of Souls"], "mode": "bracket"},
    )
    assert resp.status_code == 422


def test_create_custom_session_rejects_unknown_name(client):
    resp = client.post(
        "/api/sessions/custom",
        json={"names": ["Rakdos, Lord of Riots", "Not A Real Commander"], "mode": "duel"},
    )
    assert resp.status_code == 422
    assert "Unknown commander" in resp.json()["detail"]


def test_create_custom_session_rejects_duplicate_name(client):
    resp = client.post(
        "/api/sessions/custom",
        json={"names": ["Rakdos, Lord of Riots", "Rakdos, Lord of Riots"], "mode": "duel"},
    )
    assert resp.status_code == 422
    assert "Duplicate" in resp.json()["detail"]


def test_create_custom_session_rejects_bad_mode(client):
    resp = client.post("/api/sessions/custom", json={"names": ["Rakdos, Lord of Riots"], "mode": "nonsense"})
    assert resp.status_code == 422


def test_get_challenge_returns_32_entries(client):
    resp = client.get("/api/challenge")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 32
    assert all(e["status"] == "not_started" for e in entries)


def test_get_challenge_enriches_candidates_with_catalog_art(client):
    client.post("/api/challenge/rakdos/commanders", json={"commander_name": "Rakdos, Lord of Riots"})
    client.post("/api/challenge/rakdos/commanders", json={"commander_name": "Not In Catalog"})

    entries = client.get("/api/challenge").json()["entries"]
    rakdos = next(e for e in entries if e["slug"] == "rakdos")
    by_name = {c["name"]: c for c in rakdos["commanders"]}

    assert by_name["Rakdos, Lord of Riots"]["color_identity"] == "BR"
    assert isinstance(by_name["Rakdos, Lord of Riots"]["image_urls"], list)
    # A candidate with no catalog match still renders -- just no art.
    assert by_name["Not In Catalog"]["image_urls"] == []
    assert by_name["Not In Catalog"]["color_identity"] is None


def test_put_challenge_status_round_trips(client):
    resp = client.put("/api/challenge/rakdos", json={"status": "planning", "notes": "hmm"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "planning"
    assert resp.json()["notes"] == "hmm"

    entries = client.get("/api/challenge").json()["entries"]
    rakdos = next(e for e in entries if e["slug"] == "rakdos")
    assert rakdos["status"] == "planning"


def test_put_challenge_status_rejects_bad_slug_or_status(client):
    assert client.put("/api/challenge/not-a-slug", json={"status": "planning"}).status_code == 422
    assert client.put("/api/challenge/rakdos", json={"status": "vibing"}).status_code == 422


def test_challenge_commanders_add_choose_remove_round_trip(client):
    add_resp = client.post("/api/challenge/rakdos/commanders", json={"commander_name": "Rakdos, Lord of Riots"})
    assert add_resp.status_code == 200
    assert [c["name"] for c in add_resp.json()["commanders"]] == ["Rakdos, Lord of Riots"]

    choose_resp = client.post("/api/challenge/rakdos/commanders/Rakdos, Lord of Riots/choose")
    assert choose_resp.status_code == 200
    assert choose_resp.json()["commanders"][0]["is_chosen"] is True

    remove_resp = client.delete("/api/challenge/rakdos/commanders/Rakdos, Lord of Riots")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["commanders"] == []


def test_choose_challenge_commander_422_if_not_a_candidate(client):
    resp = client.post("/api/challenge/rakdos/commanders/Nobody/choose")
    assert resp.status_code == 422


def test_add_challenge_commander_422_on_unknown_slug(client):
    resp = client.post("/api/challenge/not-a-slug/commanders", json={"commander_name": "Whoever"})
    assert resp.status_code == 422


def test_finish_session_includes_winner_challenge_slug(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    a = created["pairing"]["candidates"][0]["name"]
    b = created["pairing"]["candidates"][1]["name"]
    client.post(f"/api/sessions/{session_id}/pick", json={"winner": a, "loser": b})

    finish_resp = client.post(f"/api/sessions/{session_id}/finish")
    assert finish_resp.status_code == 200
    # Fixture's only color page is "rakdos" (BR) -- every candidate is BR.
    assert finish_resp.json()["winner_challenge_slug"] == "rakdos"


def test_results_includes_winner_challenge_slug(client):
    created = client.post("/api/sessions", json=_pool_body()).json()
    session_id = created["session_id"]
    a = created["pairing"]["candidates"][0]["name"]
    b = created["pairing"]["candidates"][1]["name"]
    client.post(f"/api/sessions/{session_id}/pick", json={"winner": a, "loser": b})

    resp = client.get(f"/api/sessions/{session_id}/results")
    assert resp.status_code == 200
    assert resp.json()["winner_challenge_slug"] == "rakdos"


def test_bracket_includes_winner_challenge_slug(client):
    created = client.post("/api/sessions", json=_pool_body(mode="bracket", pool_size=4)).json()
    session_id = created["session_id"]

    for _ in range(4):
        pairing = client.get(f"/api/sessions/{session_id}/pairing").json()
        if pairing is None:
            break
        a, b = pairing["candidates"]
        client.post(f"/api/sessions/{session_id}/pick", json={"winner": a["name"], "loser": b["name"]})

    resp = client.get(f"/api/sessions/{session_id}/bracket")
    assert resp.status_code == 200
    assert resp.json()["champion"] is not None
    assert resp.json()["winner_challenge_slug"] == "rakdos"
