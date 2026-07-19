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

from commander_picker import colors, db, elo, sessions
from commander_picker import pool as pool_module

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
    # "duel" (continuous rating-adjacent swiping) or "bracket"
    # (single-elimination tournament to one champion) -- see
    # sessions.create_session for the engine each one drives.
    mode: str = "duel"
    # Opt-in (see pool.PoolFilters.max_price) -- None means no price filter.
    max_price: float | None = None


def _to_pool_filters(body: FiltersBody) -> pool_module.PoolFilters:
    return pool_module.PoolFilters(
        colors=body.colors,
        color_mode=body.color_mode,
        max_decks=body.max_decks,
        min_decks=body.min_decks,
        themes=tuple(body.themes),
        themes_mode=body.themes_mode,
        max_price=body.max_price,
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


def _build_pool_or_422(conn, body: FiltersBody, *, enforce_bracket_size: bool = False) -> list[pool_module.Commander]:
    # enforce_bracket_size forces min_pool_size up to exactly pool_size:
    # build_pool only ever *trims* a larger match set down to
    # max_pool_size, it never tops up a smaller one, so without this a
    # bracket could silently get created with e.g. 12 candidates when 16
    # were requested -- a size that fails elo.is_valid_bracket_size.
    # Pinning min == max here means build_pool either raises
    # PoolTooSmallError (caught below, -> 422) or hands back exactly
    # pool_size candidates, one or the other. Only api_create_session
    # passes this -- the /api/pool preview endpoint must NOT, since its
    # pool_size reflects whatever the duel-mode input currently holds
    # (the frontend doesn't thread the chosen bracket size into preview
    # calls), so enforcing it there would 422 on a perfectly fine preview.
    min_pool_size = body.pool_size if enforce_bracket_size else body.min_pool_size
    try:
        return pool_module.build_pool(
            conn,
            _to_pool_filters(body),
            max_pool_size=body.pool_size,
            min_pool_size=min_pool_size,
        )
    except pool_module.PoolTooSmallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _pairing_payload(conn, session_id: str) -> dict | None:
    info = sessions.get_session(conn, session_id)
    if info.mode == "bracket":
        return _bracket_pairing_payload(conn, session_id, info)
    pair = sessions.next_pairing(conn, session_id)
    if pair is None:
        return None
    details = sessions.get_candidates(conn, session_id)
    return {
        "round": info.rounds_completed + 1,
        "target_rounds": info.target_rounds,
        "candidates": [asdict(details[pair[0]]), asdict(details[pair[1]])],
    }


def _bracket_pairing_payload(conn, session_id: str, info: sessions.SessionInfo) -> dict | None:
    match = sessions.next_bracket_match(conn, session_id)
    if match is None:
        return None
    round_num, _slot, seed_a, seed_b = match
    details = sessions.get_candidates(conn, session_id)
    return {
        "round": round_num,
        "target_rounds": info.target_rounds,
        "round_label": elo.bracket_round_label(round_num, info.target_rounds),
        "candidates": [asdict(details[seed_a]), asdict(details[seed_b])],
    }


@app.get("/api/themes")
def api_themes():
    with _catalog_conn() as conn:
        return {"slugs": pool_module.list_known_themes(conn)}


@app.get("/api/commanders/search")
def api_search_commanders(q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=50)):
    with _catalog_conn() as conn:
        rows = pool_module.search_commanders(conn, q, limit=limit)
    return {"results": [{"name": r["name"], "color_identity": r["color_identity"], "num_decks": r["num_decks"]} for r in rows]}


@app.post("/api/pool")
def api_pool(body: FiltersBody):
    with _catalog_conn() as conn:
        filters = _to_pool_filters(body)
        total_matches = pool_module.count_matches(conn, filters)
        candidates = _build_pool_or_422(conn, body)
    return {"total_matches": total_matches, "candidates": [asdict(c) for c in candidates]}


@app.post("/api/sessions")
def api_create_session(body: FiltersBody):
    if body.mode not in ("duel", "bracket"):
        raise HTTPException(status_code=422, detail=f"mode must be 'duel' or 'bracket', got {body.mode!r}")
    if body.mode == "bracket" and not elo.is_valid_bracket_size(body.pool_size):
        raise HTTPException(
            status_code=422,
            detail=f"Bracket mode needs pool_size to be a power of two (4, 8, 16, ...) -- got {body.pool_size}.",
        )

    with _catalog_conn() as conn:
        candidates = _build_pool_or_422(conn, body, enforce_bracket_size=(body.mode == "bracket"))

    with _sessions_conn() as session_conn:
        description = pool_module.describe_filters(_to_pool_filters(body))
        session_id = sessions.create_session(session_conn, candidates, description=description, mode=body.mode)
        info = sessions.get_session(session_conn, session_id)
        pairing = _pairing_payload(session_conn, session_id)
    return {"session_id": session_id, "info": asdict(info), "pairing": pairing}


class CustomSessionBody(BaseModel):
    names: list[str]
    mode: str = "duel"


@app.post("/api/sessions/custom")
def api_create_custom_session(body: CustomSessionBody):
    if body.mode not in ("duel", "bracket"):
        raise HTTPException(status_code=422, detail=f"mode must be 'duel' or 'bracket', got {body.mode!r}")
    if body.mode == "bracket" and not elo.is_valid_bracket_size(len(body.names)):
        raise HTTPException(
            status_code=422,
            detail=f"Bracket mode needs a custom list size that's a power of two (4, 8, 16, ...) -- got {len(body.names)}.",
        )

    with _catalog_conn() as conn:
        try:
            candidates = pool_module.commanders_by_names(conn, body.names)
        except pool_module.CommanderLookupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    with _sessions_conn() as session_conn:
        description = f"Custom list ({len(candidates)} commanders)"
        session_id = sessions.create_session(session_conn, candidates, description=description, mode=body.mode)
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
            info = sessions.get_session(conn, session_id)
            if info.mode == "bracket":
                sessions.record_bracket_pick(conn, session_id, body.winner, body.loser)
            else:
                sessions.record_pick(conn, session_id, body.winner, body.loser)
            return _pairing_payload(conn, session_id)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/undo")
def api_undo(session_id: str):
    with _sessions_conn() as conn:
        try:
            sessions.undo_last_pick(conn, session_id)
            return _pairing_payload(conn, session_id)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _challenge_slug_for_name(rankings: list, name: str | None) -> str | None:
    """The 32-deck-challenge slug this commander belongs to, or None if
    there's no winner yet or its color identity doesn't parse (should
    never happen for a real commander, but the tracker prompt is purely
    additive so silently omitting it is fine).
    """
    if name is None:
        return None
    match = next((r for r in rankings if r.name == name), None)
    if match is None:
        return None
    try:
        return sessions.challenge_slug_for_commander(match.color_identity)
    except colors.UnknownColorIdentityError:
        return None


@app.post("/api/sessions/{session_id}/finish")
def api_finish(session_id: str):
    with _sessions_conn() as conn:
        try:
            info = sessions.get_session(conn, session_id)
            if info.mode == "bracket":
                raise HTTPException(
                    status_code=400,
                    detail="Bracket sessions can't be finished early -- there's no partial champion, play out the remaining matches.",
                )
            sessions.finish_session(conn, session_id)
            rankings = sessions.get_rankings(conn, session_id)
            winner_name = rankings[0].name if rankings else None
            return {
                "rankings": [asdict(r) for r in rankings],
                "winner_challenge_slug": _challenge_slug_for_name(rankings, winner_name),
            }
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/results")
def api_results(session_id: str):
    with _sessions_conn() as conn:
        try:
            sessions.get_session(conn, session_id)
            rankings = sessions.get_rankings(conn, session_id)
            winner_name = rankings[0].name if rankings else None
            return {
                "rankings": [asdict(r) for r in rankings],
                "winner_challenge_slug": _challenge_slug_for_name(rankings, winner_name),
            }
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/bracket")
def api_bracket(session_id: str):
    with _sessions_conn() as conn:
        try:
            sessions.get_session(conn, session_id)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        bracket = sessions.get_bracket(conn, session_id)
        rankings = sessions.get_rankings(conn, session_id)
        return {
            "champion": bracket.champion,
            "rounds": [[asdict(m) for m in round_matches] for round_matches in bracket.rounds],
            "winner_challenge_slug": _challenge_slug_for_name(rankings, bracket.champion),
        }


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


def _enrich_challenge_entries(entries: list) -> list[dict]:
    """Attach image_urls/color_identity to each entry's candidates, for
    a card-art view instead of plain text -- challenge_commanders only
    stores names, so this looks them up against the catalog DB
    separately. Missing/unreachable catalog data degrades gracefully
    (no art, not an error) rather than breaking the whole screen.
    """
    all_names = {c.name for e in entries for c in e.commanders}
    images_by_name: dict[str, dict] = {}
    if all_names:
        try:
            with _catalog_conn() as conn:
                images_by_name = pool_module.commander_images_by_name(conn, list(all_names))
        except HTTPException:
            pass  # no catalog yet -- candidates just render without art

    result = []
    for e in entries:
        d = asdict(e)
        for c in d["commanders"]:
            info = images_by_name.get(c["name"], {})
            c["image_urls"] = info.get("image_urls", [])
            c["color_identity"] = info.get("color_identity")
        result.append(d)
    return result


@app.get("/api/challenge")
def api_get_challenge():
    with _sessions_conn() as conn:
        entries = sessions.get_challenge_tracker(conn)
    return {"entries": _enrich_challenge_entries(entries)}


class ChallengeStatusBody(BaseModel):
    status: str
    notes: str | None = None


@app.put("/api/challenge/{slug}")
def api_set_challenge_status(slug: str, body: ChallengeStatusBody):
    with _sessions_conn() as conn:
        try:
            entry = sessions.set_challenge_status(conn, slug, body.status, body.notes)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(entry)


class ChallengeCommanderBody(BaseModel):
    commander_name: str


@app.post("/api/challenge/{slug}/commanders")
def api_add_challenge_commander(slug: str, body: ChallengeCommanderBody):
    with _sessions_conn() as conn:
        try:
            entry = sessions.add_challenge_commander(conn, slug, body.commander_name)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(entry)


@app.delete("/api/challenge/{slug}/commanders/{commander_name}")
def api_remove_challenge_commander(slug: str, commander_name: str):
    with _sessions_conn() as conn:
        try:
            entry = sessions.remove_challenge_commander(conn, slug, commander_name)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(entry)


@app.post("/api/challenge/{slug}/commanders/{commander_name}/choose")
def api_choose_challenge_commander(slug: str, commander_name: str):
    with _sessions_conn() as conn:
        try:
            entry = sessions.choose_challenge_commander(conn, slug, commander_name)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(entry)


class ChallengeAddByColorBody(BaseModel):
    commander_name: str
    color_identity: str


@app.post("/api/challenge/commanders")
def api_add_challenge_commander_auto(body: ChallengeAddByColorBody):
    """Add a candidate without the caller knowing which combo it belongs
    to -- the commander's own color identity determines that (same
    `slug_for_colors` logic the results-screen nudge already uses),
    instead of every one of the 32 rows needing its own scoped search.
    `color_identity` comes straight from the search result the frontend
    already has (GET /api/commanders/search), no extra catalog lookup
    needed here.
    """
    try:
        slug = colors.slug_for_colors(body.color_identity)
    except colors.UnknownColorIdentityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with _sessions_conn() as conn:
        try:
            entry = sessions.add_challenge_commander(conn, slug, body.commander_name)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"slug": slug, **asdict(entry)}


class NoCacheStaticFiles(StaticFiles):
    """Force browsers to revalidate static assets on every request.

    Without this, FastAPI's default StaticFiles sends no explicit
    Cache-Control, so browsers fall back to their own heuristic caching --
    mobile Safari/Chrome hang onto a cached app.js far more stubbornly
    than a desktop tab with dev tools open. That can pair a freshly
    fetched index.html (so new UI markup renders) with a stale cached
    app.js (so that markup's click handlers don't exist yet) right after
    a deploy, which looks exactly like "the button's there but does
    nothing." ETag/Last-Modified conditional GETs still make revalidation
    cheap -- this only forces the check, not a full re-download.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
