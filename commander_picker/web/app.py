"""FastAPI app: JSON API for the commander picker + serves the static frontend.

No auth, no rate limiting, no per-user scoping -- fine for a
single-user or personal-link deployment (see PLAN.md's "Known
limitations"), would need real accounts before supporting more than
one person concurrently.
"""

from __future__ import annotations

from contextlib import contextmanager
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


@contextmanager
def _catalog_conn():
    try:
        conn = db.connect()
    except db.DbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _sessions_conn():
    conn = sessions.connect()
    try:
        yield conn
    finally:
        conn.close()


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
    with _catalog_conn() as conn:
        filters = _to_pool_filters(body)
        total_matches = pool_module.count_matches(conn, filters)
        candidates = _build_pool_or_422(conn, body)
    return {"total_matches": total_matches, "candidates": [asdict(c) for c in candidates]}


@app.post("/api/sessions")
def api_create_session(body: FiltersBody):
    with _catalog_conn() as conn:
        candidates = _build_pool_or_422(conn, body)

    with _sessions_conn() as session_conn:
        description = pool_module.describe_filters(_to_pool_filters(body))
        session_id = sessions.create_session(session_conn, candidates, description=description)
        info = sessions.get_session(session_conn, session_id)
        pairing = _pairing_payload(session_conn, session_id)
    return {"session_id": session_id, "info": asdict(info), "pairing": pairing}


@app.get("/api/sessions")
def api_list_sessions():
    with _sessions_conn() as conn:
        return {"sessions": [asdict(s) for s in sessions.list_sessions(conn)]}


@app.get("/api/sessions/{session_id}")
def api_get_session(session_id: str):
    with _sessions_conn() as conn:
        try:
            info = sessions.get_session(conn, session_id)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(info)


@app.get("/api/sessions/{session_id}/pairing")
def api_get_pairing(session_id: str):
    with _sessions_conn() as conn:
        try:
            sessions.get_session(conn, session_id)
            return _pairing_payload(conn, session_id)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


class PickBody(BaseModel):
    winner: str
    loser: str


@app.post("/api/sessions/{session_id}/pick")
def api_pick(session_id: str, body: PickBody):
    with _sessions_conn() as conn:
        try:
            sessions.record_pick(conn, session_id, body.winner, body.loser)
            return _pairing_payload(conn, session_id)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/finish")
def api_finish(session_id: str):
    with _sessions_conn() as conn:
        try:
            sessions.get_session(conn, session_id)
            sessions.finish_session(conn, session_id)
            return {"rankings": [asdict(r) for r in sessions.get_rankings(conn, session_id)]}
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/results")
def api_results(session_id: str):
    with _sessions_conn() as conn:
        try:
            sessions.get_session(conn, session_id)
            return {"rankings": [asdict(r) for r in sessions.get_rankings(conn, session_id)]}
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/leaderboard")
def api_leaderboard(
    limit: int = Query(default=100, ge=1, le=500),
    colors: str | None = None,
    color_mode: str = "subset",
):
    with _sessions_conn() as conn:
        ranked = sessions.get_leaderboard(conn, limit=limit, colors=colors, color_mode=color_mode)
        return {"leaderboard": [asdict(r) for r in ranked]}


@app.delete("/api/leaderboard")
def api_reset_leaderboard():
    # Confirmation happens client-side (the web UI asks before calling
    # this) -- there's no undo once it runs, same posture as every
    # other destructive action this local-only, no-auth app exposes.
    with _sessions_conn() as conn:
        sessions.reset_leaderboard(conn)
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
