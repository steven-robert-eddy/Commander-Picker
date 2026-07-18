"""FastAPI app: JSON API for the commander picker + serves the static frontend.

Local-only for now, same posture as the sibling `commander-synergy`
project's Phase 4: no auth, no rate limiting -- fine for a single-user
local tool, would need attention before exposing beyond localhost.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from commander_picker import db, pool as pool_module, sessions
from commander_picker.themes import THEME_SLUGS

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Commander Picker")


class FiltersBody(BaseModel):
    colors: str | None = None
    color_mode: str = "subset"
    max_decks: int | None = pool_module.DEFAULT_MAX_DECKS
    min_decks: int | None = None
    themes: list[str] = []
    themes_mode: str = "any"
    # Bounded so a stray client value (or someone poking the API
    # directly) can't request an absurd pool size -- 200 is well above
    # any reasonable duel session length.
    pool_size: int = Field(default=pool_module.DEFAULT_MAX_POOL_SIZE, ge=2, le=200)
    min_pool_size: int = Field(default=pool_module.DEFAULT_MIN_POOL_SIZE, ge=1, le=200)


def _to_pool_filters(body: FiltersBody) -> pool_module.PoolFilters:
    return pool_module.PoolFilters(
        colors=body.colors,
        color_mode=body.color_mode,
        max_decks=body.max_decks,
        min_decks=body.min_decks,
        themes=tuple(body.themes),
        themes_mode=body.themes_mode,
    )


def _catalog_conn():
    try:
        return db.connect()
    except db.DbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _build_pool_or_422(conn, body: FiltersBody) -> list[pool_module.Commander]:
    try:
        return pool_module.build_pool(
            conn,
            _to_pool_filters(body),
            max_pool_size=body.pool_size,
            min_pool_size=body.min_pool_size,
        )
    except pool_module.PoolTooSmallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _pairing_payload(conn, session_id: str) -> dict | None:
    info = sessions.get_session(conn, session_id)
    pair = sessions.next_pairing(conn, session_id)
    if pair is None:
        return None
    details = sessions.get_candidates(conn, session_id)
    return {
        "round": info.rounds_completed + 1,
        "target_rounds": info.target_rounds,
        "candidates": [asdict(details[pair[0]]), asdict(details[pair[1]])],
    }


@app.get("/api/themes")
def api_themes():
    return {"slugs": THEME_SLUGS}


@app.post("/api/pool")
def api_pool(body: FiltersBody):
    conn = _catalog_conn()
    try:
        filters = _to_pool_filters(body)
        total_matches = pool_module.count_matches(conn, filters)
        candidates = _build_pool_or_422(conn, body)
    finally:
        conn.close()
    return {"total_matches": total_matches, "candidates": [asdict(c) for c in candidates]}


@app.post("/api/sessions")
def api_create_session(body: FiltersBody):
    conn = _catalog_conn()
    try:
        candidates = _build_pool_or_422(conn, body)
    finally:
        conn.close()

    session_conn = sessions.connect()
    try:
        description = pool_module.describe_filters(_to_pool_filters(body))
        session_id = sessions.create_session(session_conn, candidates, description=description)
        info = sessions.get_session(session_conn, session_id)
        pairing = _pairing_payload(session_conn, session_id)
    finally:
        session_conn.close()
    return {"session_id": session_id, "info": asdict(info), "pairing": pairing}


@app.get("/api/sessions")
def api_list_sessions():
    conn = sessions.connect()
    try:
        return {"sessions": [asdict(s) for s in sessions.list_sessions(conn)]}
    finally:
        conn.close()


@app.get("/api/sessions/{session_id}")
def api_get_session(session_id: str):
    conn = sessions.connect()
    try:
        info = sessions.get_session(conn, session_id)
    except sessions.SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()
    return asdict(info)


@app.get("/api/sessions/{session_id}/pairing")
def api_get_pairing(session_id: str):
    conn = sessions.connect()
    try:
        sessions.get_session(conn, session_id)
        return _pairing_payload(conn, session_id)
    except sessions.SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


class PickBody(BaseModel):
    winner: str
    loser: str


@app.post("/api/sessions/{session_id}/pick")
def api_pick(session_id: str, body: PickBody):
    conn = sessions.connect()
    try:
        sessions.record_pick(conn, session_id, body.winner, body.loser)
        return _pairing_payload(conn, session_id)
    except sessions.SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.post("/api/sessions/{session_id}/finish")
def api_finish(session_id: str):
    conn = sessions.connect()
    try:
        sessions.get_session(conn, session_id)
        sessions.finish_session(conn, session_id)
        return {"rankings": [asdict(r) for r in sessions.get_rankings(conn, session_id)]}
    except sessions.SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/sessions/{session_id}/results")
def api_results(session_id: str):
    conn = sessions.connect()
    try:
        sessions.get_session(conn, session_id)
        return {"rankings": [asdict(r) for r in sessions.get_rankings(conn, session_id)]}
    except sessions.SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/leaderboard")
def api_leaderboard(limit: int = Query(default=100, ge=1, le=500)):
    conn = sessions.connect()
    try:
        return {"leaderboard": [asdict(r) for r in sessions.get_leaderboard(conn, limit=limit)]}
    finally:
        conn.close()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
